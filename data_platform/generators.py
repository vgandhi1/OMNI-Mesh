"""Minimal per-profile synthetic Bronze generators.

Distilled from the full generators in the source projects (OPC-UA simulator,
robotics EpisodeMeta, wearable/eCRF faker) — just enough rows, with a few
anomalies / failure tags / regions, to exercise ingest + RAG. Identifier columns
are produced already-masked via :func:`governance.mask`.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

import pyarrow as pa

from config.profiles import (
    AGE_BRACKETS,
    FACILITIES,
    FAILURE_TAGS,
    PLAN_TIERS,
    REGIONS,
    REGISTRY,
    ROBOT_MODELS,
    STUDY_IDS,
    MeshProfile,
)

_PLAN_REVENUE = {"FREE": 0.0, "PRO": 99.0, "ENTERPRISE": 499.0}
from data_platform import governance

_BASE_TS = datetime(2026, 1, 1)  # naive -> maps cleanly to Iceberg timestamp(us)


def make_bronze_batch(profile: MeshProfile, n: int = 64, seed: int = 42) -> pa.Table:
    rng = random.Random(seed)
    rows: list[dict] = []

    for i in range(n):
        ts = _BASE_TS + timedelta(milliseconds=i * 20)

        if profile == MeshProfile.ROBOTICS:
            failed = rng.random() < 0.25
            rows.append(
                {
                    "timestamp": ts,
                    "robot_id": governance.mask(f"serial-{i % 8}"),
                    "robot_model_id": rng.choice(ROBOT_MODELS),
                    "joint_positions": [round(rng.uniform(-3.14, 3.14), 4) for _ in range(7)],
                    "camera_frame_uri": f"s3://omni-mesh/frames/{i:06d}.jpg",
                    "failure_type_tag": rng.choice(FAILURE_TAGS) if failed else "NO_FAILURE",
                    "success_flag": not failed,
                }
            )
        elif profile == MeshProfile.MANUFACTURING:
            anomaly = rng.random() < 0.15
            rows.append(
                {
                    "timestamp": ts,
                    "facility_id": rng.choice(FACILITIES),
                    "register_id": governance.mask(f"REG-{i % 4}"),
                    "measured_voltage": round(
                        rng.choice([11.5, 16.8]) if anomaly else rng.gauss(14.5, 0.2), 3
                    ),
                    "temperature_c": round(rng.gauss(72.0, 3.0), 3),
                    "pressure_bar": round(rng.gauss(6.5, 0.5), 3),
                    "anomaly_flag": anomaly,
                }
            )
        elif profile == MeshProfile.HEALTH_TECH:
            rows.append(
                {
                    "timestamp": ts,
                    "patient_id_hashed": governance.mask(f"PAT-{i % 20:05d}"),
                    "heart_rate_variability": int(max(5, rng.gauss(55, 12))),
                    "sleep_efficiency": round(min(1.0, max(0.0, rng.gauss(0.8, 0.1))), 3),
                    "region": rng.choice(REGIONS),
                }
            )
        elif profile == MeshProfile.COMMERCIAL:
            tier = rng.choice(PLAN_TIERS)
            rows.append(
                {
                    "timestamp": ts,
                    "customer_id_hashed": governance.mask(f"CUST-{i % 50:05d}"),
                    "plan_tier": tier,
                    "region": rng.choice(REGIONS),
                    "monthly_revenue": round(_PLAN_REVENUE[tier] * rng.uniform(0.9, 1.1), 2),
                    "tenure_months": int(max(1, rng.gauss(18, 10))),
                    "churned_flag": rng.random() < 0.2,
                }
            )
        elif profile == MeshProfile.CLINICAL:
            rows.append(
                {
                    "timestamp": ts,
                    "patient_id_hashed": governance.mask(f"PAT-{i % 30:05d}"),
                    "study_id": rng.choice(STUDY_IDS),
                    "age_bracket": rng.choice(AGE_BRACKETS),
                    "region": rng.choice(REGIONS),
                    "adverse_event_flag": rng.random() < 0.1,
                }
            )
        else:  # pragma: no cover - registry and generators kept in lockstep
            raise ValueError(f"No generator defined for profile {profile!r}")

    return pa.Table.from_pylist(rows, schema=REGISTRY[profile].silver_schema)
