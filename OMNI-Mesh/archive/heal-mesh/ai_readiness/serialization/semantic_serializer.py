"""Phase 4 step 1 — semantic serialization of gold metrics.

Reads the cross-domain gold tables (telemetry health index + commercial CLV +
clinical cohort) and emits natural-language paragraphs of the form described in
the blueprint:

    "Patient ID X948 registered a 14% drop in deep sleep duration over a
     72-hour period. This trend correlates with a 5bpm spike in resting heart
     rate and a 20ms decrease in Heart Rate Variability (HRV)."

Each paragraph is annotated with the metadata that powers downstream filters
(``age_bracket``, ``sleep_risk_tier``, ``region``, ``mrr_churn_risk``).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import duckdb

from scripts._config import DATA_ROOT, configure_logging

LOG = configure_logging()

OUTPUT_PATH = DATA_ROOT / "warehouse" / "semantic_summaries.jsonl"

# Each warehouse file is a per-domain DuckDB DB produced by dbt-duckdb.
TELEMETRY_DB = DATA_ROOT / "warehouse" / "telemetry.duckdb"
COMMERCIAL_DB = DATA_ROOT / "warehouse" / "commercial.duckdb"
CLINICAL_DB = DATA_ROOT / "warehouse" / "clinical.duckdb"


@dataclass(frozen=True)
class PatientSemanticRow:
    patient_id: str
    week_start: str
    paragraph: str
    age_bracket: str
    sleep_risk_tier: str
    region: str
    mrr_churn_risk: str
    study_id: str


# DuckDB does not parameterize the ``ATTACH`` statement. The ``alias`` is
# embedded directly as an identifier and the ``path`` as a literal, so we
# defend in depth: aliases are allow-listed and paths are validated to be
# real files inside our managed warehouse before they are interpolated.
# Today these inputs are static module constants — the allow-list exists so
# that if a future refactor accidentally exposes them to a config file or
# CLI, we still cannot hand a SQL injection vector to ``ATTACH``.
_ALLOWED_ATTACH_ALIASES = frozenset({"telemetry", "commercial", "clinical"})


def _attach_domain_warehouses(con: duckdb.DuckDBPyConnection) -> None:
    """Federate the three per-domain DBs through one DuckDB connection."""
    for alias, path in (
        ("telemetry", TELEMETRY_DB),
        ("commercial", COMMERCIAL_DB),
        ("clinical", CLINICAL_DB),
    ):
        if alias not in _ALLOWED_ATTACH_ALIASES:
            # secure_sql §3 — the alias is a SQL identifier, not parameterizable.
            raise ValueError(f"ATTACH alias not in allow-list: {alias!r}")
        if not path.is_file():
            raise FileNotFoundError(
                f"Expected dbt-built warehouse {path} - did you run `make dbt-all`?"
            )
        # ``path`` is a ``Path`` resolved at import time from our DATA_ROOT;
        # ``alias`` was just allow-listed above. Both are safe to interpolate.
        con.execute(f"ATTACH '{path}' AS {alias} (READ_ONLY)")


def _fetch_joined_rows(con: duckdb.DuckDBPyConnection) -> Iterable[dict]:
    # NB: dbt-duckdb prefixes user-defined schemas with the connection's
    # default database name ("main"). Production Snowflake/BigQuery have no
    # such prefix; the table-name constants live next to the SQL to keep
    # cross-environment swaps mechanical.
    sql = """
        WITH t AS (
          SELECT * FROM telemetry.main_telemetry_gold.gold_patient_health_index
        ),
        c AS (
          SELECT * FROM commercial.main_commercial_gold.gold_customer_value
        ),
        clin AS (
          SELECT * FROM clinical.main_clinical_gold.gold_patient_cohort
        )
        SELECT
          t.patient_id,
          CAST(t.week_start AS VARCHAR)       AS week_start,
          t.avg_hr_bpm,
          t.avg_hrv_ms,
          t.total_deep_sleep_min,
          t.hrv_delta_vs_prev_week,
          t.hr_delta_vs_prev_week,
          t.sleep_risk_tier,
          clin.age_bracket,
          clin.region,
          clin.study_id,
          c.mrr_churn_risk
        FROM t
        JOIN clin ON clin.patient_id = t.patient_id
        LEFT JOIN c ON c.customer_pseudo_id = t.patient_id
        ORDER BY t.patient_id, t.week_start
    """
    for row in con.execute(sql).fetchall():
        cols = [desc[0] for desc in con.description]
        yield dict(zip(cols, row))


def _format_paragraph(row: dict) -> str:
    """Render a single row as a clinician-grade narrative paragraph."""
    hrv_delta = row.get("hrv_delta_vs_prev_week")
    hr_delta = row.get("hr_delta_vs_prev_week")

    hrv_clause = (
        f"a {abs(hrv_delta):.1f}ms {'decrease' if hrv_delta < 0 else 'increase'} in HRV"
        if hrv_delta is not None
        else "a stable HRV"
    )
    hr_clause = (
        f"a {abs(hr_delta):.1f}bpm {'spike' if hr_delta > 0 else 'drop'} in resting heart rate"
        if hr_delta is not None
        else "a stable resting heart rate"
    )

    return (
        f"Patient {row['patient_id']} (age {row['age_bracket']}, region {row['region']}, "
        f"study {row['study_id']}) during the week starting {row['week_start']} averaged "
        f"{row['avg_hr_bpm']:.1f}bpm heart rate and {row['avg_hrv_ms']:.1f}ms HRV with "
        f"{row['total_deep_sleep_min']:.0f} minutes of deep sleep. "
        f"Week-over-week the patient shows {hr_clause} and {hrv_clause}, "
        f"placing them in the '{row['sleep_risk_tier']}' sleep-risk tier. "
        f"Their current subscription churn-risk tier is '{row.get('mrr_churn_risk') or 'unknown'}'."
    )


def serialize() -> Path:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    # try/finally so the connection (and any DuckDB-held SQLite catalog
    # handles) is released even if ``_attach_domain_warehouses`` raises
    # ``FileNotFoundError`` because dbt has not been built yet, or if the
    # join query fails. Without this, repeated invocations from a long-lived
    # Dagster worker eventually exhaust open file descriptors.
    con = duckdb.connect()
    try:
        _attach_domain_warehouses(con)

        written = 0
        with OUTPUT_PATH.open("w", encoding="utf-8") as fh:
            for row in _fetch_joined_rows(con):
                semantic = PatientSemanticRow(
                    patient_id=row["patient_id"],
                    week_start=row["week_start"],
                    paragraph=_format_paragraph(row),
                    age_bracket=row["age_bracket"],
                    sleep_risk_tier=row["sleep_risk_tier"],
                    region=row["region"],
                    mrr_churn_risk=row.get("mrr_churn_risk") or "unknown",
                    study_id=row["study_id"],
                )
                fh.write(json.dumps(asdict(semantic)) + "\n")
                written += 1
    finally:
        con.close()

    LOG.info("semantic serializer wrote %d paragraphs → %s", written, OUTPUT_PATH)
    return OUTPUT_PATH


if __name__ == "__main__":
    serialize()
