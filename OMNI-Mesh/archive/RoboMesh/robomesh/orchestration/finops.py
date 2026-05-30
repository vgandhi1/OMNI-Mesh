"""Local FinOps audit — mirrors the Snowflake long-running-query query from
Phase 5 of the blueprint, but executed against a DuckDB-emulated query log."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import duckdb

from robomesh.catalog.iceberg import read_table_arrow
from robomesh.config import get_settings
from robomesh.logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class FinOpsRow:
    query_id: str
    user_name: str
    warehouse_name: str
    execution_time_seconds: float
    estimated_compute_cost_usd: float
    query_text: str


def _instrument_queries() -> Path:
    """Run a few representative queries against the lakehouse, recording timings.

    In production this data would come from
    ``snowflake.account_usage.query_history``. Locally we instrument DuckDB so
    the same audit shape works without a warehouse.
    """
    s = get_settings()
    s.artifacts_root.mkdir(parents=True, exist_ok=True)
    out_path = s.artifacts_root / "query_history.parquet"

    silver = read_table_arrow("silver.synchronized_trajectories")
    gold = read_table_arrow("gold.vla_episodes")

    rows: list[dict] = []
    con = duckdb.connect()
    con.register("silver", silver)
    con.register("gold", gold)

    probes = [
        ("ANALYTICS_BI", "wh_analytics", "SELECT robot_model_id, COUNT(*) FROM gold GROUP BY 1"),
        ("ML_TRAINING", "wh_ml_xlarge",
         "SELECT episode_id, AVG(max_joint_torque_nm) FROM silver GROUP BY 1"),
        ("DATA_OPS",   "wh_ops",
         "SELECT failure_type_tag, AVG(peak_torque_nm) FROM gold GROUP BY 1"),
        ("ML_TRAINING", "wh_ml_xlarge",
         "INSERT INTO silver SELECT * FROM silver LIMIT 0"),  # noop, simulates ingest
    ]

    for user, warehouse, sql in probes:
        t0 = time.perf_counter()
        try:
            con.execute(sql).fetchall()
        except Exception as exc:  # noqa: BLE001
            log.warning("finops.probe.err sql=%s err=%s", sql[:40], exc)
            continue
        elapsed = time.perf_counter() - t0
        rows.append(
            {
                "query_id": f"q_{int(time.time()*1000)}_{len(rows)}",
                "user_name": user,
                "warehouse_name": warehouse,
                "execution_time": elapsed * 1000.0,  # ms (Snowflake convention)
                "query_text": sql,
            }
        )

    con.close()

    import pyarrow as pa
    import pyarrow.parquet as pq

    if out_path.exists():
        out_path.unlink()
    pq.write_table(pa.Table.from_pylist(rows), out_path, compression="zstd")
    log.info("finops.instrument rows=%d path=%s", len(rows), out_path.name)
    return out_path


def run_finops_audit(*, hourly_rate_usd: float = 4.00) -> list[FinOpsRow]:
    """Run the long-running-query audit and return cost estimates."""
    history_path = _instrument_queries()
    con = duckdb.connect()
    audit = con.execute(
        """
        SELECT
            query_id,
            user_name,
            warehouse_name,
            execution_time / 1000.0                       AS execution_time_seconds,
            (execution_time / 3600000.0) * ?              AS estimated_compute_cost_usd,
            query_text
        FROM read_parquet(?)
        ORDER BY execution_time_seconds DESC
        """,
        (hourly_rate_usd, str(history_path)),
    ).fetchall()
    cols = [d[0] for d in con.description]
    con.close()
    out = [FinOpsRow(**dict(zip(cols, r))) for r in audit]
    for row in out:
        log.info(
            "finops.row user=%s wh=%s sec=%.3f cost_usd=%.4f",
            row.user_name, row.warehouse_name,
            row.execution_time_seconds, row.estimated_compute_cost_usd,
        )
    return out
