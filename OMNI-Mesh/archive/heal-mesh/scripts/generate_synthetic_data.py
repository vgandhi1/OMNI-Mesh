"""Phase 1 — synthetic raw inputs for the three HEAL-Mesh domains.

This emulates the production sources called out in the blueprint:

* Biometric Telemetry Domain  → wearable IoT JSON/Parquet drops
* Commercial Subscription     → Stripe / App Store webhook events
* Clinical Compliance         → eCRF metadata + PHI rows

The output is written as Parquet under ``data/lakehouse/raw/<domain>/`` and is
the *bronze* feed for the rest of the pipeline. All identifiers are deliberately
synthetic — see ``faker`` — so no real PII ever lands in the repo.
"""

from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from faker import Faker

from scripts._config import DATA_ROOT, configure_logging

LOG = configure_logging()
FAKE = Faker()
Faker.seed(20260526)
random.seed(20260526)
np.random.seed(20260526)

RAW_ROOT = DATA_ROOT / "lakehouse" / "raw"


# ---------------------------------------------------------------------------
# Telemetry domain — wearable device events
# ---------------------------------------------------------------------------
def _generate_telemetry(num_patients: int, days: int) -> pd.DataFrame:
    """Synthesize per-minute wearable telemetry for ``num_patients`` patients."""
    base_time = datetime.now(timezone.utc) - timedelta(days=days)
    rows: list[dict] = []
    for pidx in range(num_patients):
        # Stable surrogate patient ID. Real patient mapping never leaves the
        # clinical domain; downstream domains only see this opaque ID.
        patient_id = f"PAT-{pidx:05d}"
        baseline_hr = np.random.normal(68, 6)
        baseline_hrv = np.random.normal(55, 12)
        sleep_pattern = np.random.choice(["healthy", "fragmented", "deteriorating"])

        for day_offset in range(days):
            day_time = base_time + timedelta(days=day_offset)
            # Sample 24 hourly events per day → manageable but realistic.
            for hour in range(24):
                ts = day_time + timedelta(hours=hour)
                hr_jitter = np.random.normal(0, 3)
                hrv_jitter = np.random.normal(0, 6)
                if sleep_pattern == "deteriorating":
                    hrv_jitter -= day_offset * 0.4  # gradual decline
                    hr_jitter += day_offset * 0.15
                rows.append(
                    {
                        "patient_id": patient_id,
                        "device_id": f"WEAR-{pidx % 1000:04d}",
                        "event_ts": ts,
                        "heart_rate_bpm": float(np.clip(baseline_hr + hr_jitter, 35, 180)),
                        "hrv_ms": float(np.clip(baseline_hrv + hrv_jitter, 5, 200)),
                        "spo2_pct": float(np.clip(np.random.normal(97, 1.2), 80, 100)),
                        "deep_sleep_min": float(np.clip(np.random.normal(95, 22), 0, 240)),
                        "steps": int(max(0, np.random.normal(420, 280))),
                        "sleep_pattern_hint": sleep_pattern,
                    }
                )
    df = pd.DataFrame(rows)
    LOG.info("telemetry: generated %d rows across %d patients", len(df), num_patients)
    return df


# ---------------------------------------------------------------------------
# Commercial domain — Stripe / App-Store webhook events
# ---------------------------------------------------------------------------
def _generate_commercial(num_patients: int) -> pd.DataFrame:
    """Synthesize subscription lifecycle events that mirror Stripe webhooks."""
    plans = [
        ("basic", 9.99),
        ("premium", 24.99),
        ("clinical_plus", 49.99),
    ]
    statuses = ["active", "active", "active", "trialing", "past_due", "canceled"]

    rows = []
    base_time = datetime.now(timezone.utc) - timedelta(days=180)
    for pidx in range(num_patients):
        patient_id = f"PAT-{pidx:05d}"
        plan, price = random.choice(plans)
        status = random.choice(statuses)
        start = base_time + timedelta(days=random.randint(0, 120))
        events = ["customer.created", "subscription.created"]
        if status in {"past_due", "canceled"}:
            events.append("invoice.payment_failed")
        if status == "canceled":
            events.append("subscription.deleted")
        for n, ev in enumerate(events):
            rows.append(
                {
                    "event_id": f"evt_{FAKE.uuid4()}",
                    "customer_pseudo_id": patient_id,
                    "event_type": ev,
                    "plan": plan,
                    "amount_usd": price if "subscription" in ev or "invoice" in ev else 0.0,
                    "currency": "USD",
                    "subscription_status": status,
                    "event_ts": start + timedelta(days=n * 7),
                }
            )
    df = pd.DataFrame(rows)
    LOG.info("commercial: generated %d webhook events", len(df))
    return df


# ---------------------------------------------------------------------------
# Clinical domain — eCRF metadata + PHI rows
# ---------------------------------------------------------------------------
def _generate_clinical(num_patients: int) -> pd.DataFrame:
    """Synthesize eCRF rows containing PHI columns that will be masked downstream."""
    studies = ["CLINICAL_STUDY_01", "CLINICAL_STUDY_02"]
    rows = []
    for pidx in range(num_patients):
        patient_id = f"PAT-{pidx:05d}"
        # NOTE (logging_rule + auth): these fields are deliberately PII/PHI.
        # They are persisted only in the clinical bronze layer and are masked
        # before any other domain or analyst role can read them.
        rows.append(
            {
                "patient_id": patient_id,
                "mrn": f"MRN-{FAKE.numerify('########')}",  # medical record number
                "first_name": FAKE.first_name(),
                "last_name": FAKE.last_name(),
                "email": FAKE.email(),
                "dob": FAKE.date_of_birth(minimum_age=18, maximum_age=90),
                "sex_at_birth": random.choice(["M", "F", "X"]),
                "study_id": random.choice(studies),
                "consent_signed": random.choice([True, True, True, False]),
                "region": random.choice(["NA", "EU", "APAC"]),
                "enrolled_ts": datetime.now(timezone.utc)
                - timedelta(days=random.randint(7, 720)),
            }
        )
    df = pd.DataFrame(rows)
    LOG.info("clinical: generated %d eCRF rows", len(df))
    return df


def _write_parquet(df: pd.DataFrame, domain: str, table: str) -> Path:
    out_dir = RAW_ROOT / domain
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{table}.parquet"
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), out_path)
    LOG.info("wrote %s (%d rows) → %s", table, len(df), out_path.relative_to(DATA_ROOT))
    return out_path


def main(num_patients: int = 200, telemetry_days: int = 14) -> None:
    RAW_ROOT.mkdir(parents=True, exist_ok=True)

    telemetry = _generate_telemetry(num_patients=num_patients, days=telemetry_days)
    commercial = _generate_commercial(num_patients=num_patients)
    clinical = _generate_clinical(num_patients=num_patients)

    _write_parquet(telemetry, "telemetry", "wearable_events")
    _write_parquet(commercial, "commercial", "subscription_events")
    _write_parquet(clinical, "clinical", "ecrf_patients")

    LOG.info("synthetic data generation complete")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate HEAL-Mesh synthetic data")
    parser.add_argument("--patients", type=int, default=200)
    parser.add_argument("--telemetry-days", type=int, default=14)
    args = parser.parse_args()
    main(num_patients=args.patients, telemetry_days=args.telemetry_days)
