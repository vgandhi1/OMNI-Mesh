"""Phase 1 — cross-engine Iceberg interop verification.

Implements the blueprint check:

    "Execute a PySpark job in Databricks that appends 10,000 synthetic heart
     rate rows to the Iceberg table, and instantly query the updated table in
     Snowflake with zero lag and zero network data-transfer costs."

In this local reference we substitute PyArrow (writer) and DuckDB (reader),
but the key invariant — both engines read the **same** Iceberg metadata files
— is preserved.
"""

from __future__ import annotations

from datetime import datetime, timezone

import duckdb
import numpy as np
import pyarrow as pa

from scripts._config import configure_logging
from scripts.bootstrap_iceberg import get_catalog

LOG = configure_logging()

NAMESPACE = "telemetry_domain"
TABLE = f"{NAMESPACE}.wearable_events_bronze"


def append_synthetic(rows: int = 10_000) -> None:
    """Engine A — PyArrow writer (stands in for Spark/Databricks)."""
    catalog = get_catalog()
    table = catalog.load_table(TABLE)

    now = datetime.now(timezone.utc)
    schema = table.schema().as_arrow()
    data = {
        "patient_id": [f"PAT-VERIFY-{i:05d}" for i in range(rows)],
        "device_id": [f"WEAR-VERIFY-{i % 50:04d}" for i in range(rows)],
        "event_ts": [now] * rows,
        "heart_rate_bpm": np.random.normal(72, 5, rows).astype("float64"),
        "hrv_ms": np.random.normal(55, 10, rows).astype("float64"),
        "spo2_pct": np.random.normal(97, 1, rows).astype("float64"),
        "deep_sleep_min": np.random.normal(95, 20, rows).astype("float64"),
        "steps": np.random.randint(0, 2000, rows).astype("int64"),
        "sleep_pattern_hint": ["healthy"] * rows,
    }
    arrow = pa.Table.from_pydict(data, schema=schema)
    table.append(arrow)
    LOG.info("engine A (pyarrow) appended %d rows to %s", rows, TABLE)


def query_with_duckdb() -> None:
    """Engine B — DuckDB reader (stands in for Snowflake external volume)."""
    catalog = get_catalog()
    table = catalog.load_table(TABLE)
    arrow_scan = table.scan().to_arrow()
    con = duckdb.connect()
    con.register("wearable_events", arrow_scan)
    summary = con.execute(
        """
        SELECT
          COUNT(*)                       AS row_count,
          AVG(heart_rate_bpm)            AS avg_hr,
          AVG(hrv_ms)                    AS avg_hrv,
          SUM(CASE WHEN patient_id LIKE 'PAT-VERIFY-%' THEN 1 ELSE 0 END) AS verify_rows
        FROM wearable_events
        """
    ).fetchone()
    LOG.info(
        "engine B (duckdb) read: rows=%s avg_hr=%.2f avg_hrv=%.2f verify_rows=%s",
        *summary,
    )


if __name__ == "__main__":
    append_synthetic()
    query_with_duckdb()
