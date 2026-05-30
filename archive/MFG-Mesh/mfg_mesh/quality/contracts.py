"""Silver/Gold contract enforcement implemented with DuckDB on top of Iceberg.

`enforce_silver_contract` reads from the bronze Iceberg table, applies the
explicit SLA thresholds declared in `mfg_mesh.config`, and writes a Silver
Iceberg table that only contains records that satisfied the contract. The
violation count is surfaced to the orchestrator via `ContractResult` so that
Dagster can publish it as asset metadata (see `MaterializeResult` in
`orchestration/assets.py`).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pyarrow as pa

from ..config import MFGMeshConfig, get_config
from ..lakehouse.catalog import ensure_namespaces, get_catalog
from ..lakehouse.ingest import write_to_factory_lakehouse
from ..security import mask_identifier

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContractResult:
    rows_in: int
    rows_out: int
    contract_violations: int
    elapsed_sec: float
    table: str

    @property
    def pipeline_success_flag(self) -> bool:
        return self.contract_violations == 0


def _bronze_arrow(cfg: MFGMeshConfig) -> pa.Table:
    cat = get_catalog(cfg)
    tbl = cat.load_table(f"{cfg.namespace_bronze}.{cfg.table_bronze}")
    return tbl.scan().to_arrow()


def enforce_silver_contract(cfg: MFGMeshConfig | None = None) -> ContractResult:
    """Read bronze, validate against SLA, write silver. Always returns metrics.

    The contract:
        * `voltage` in [sla_voltage_min, sla_voltage_max]
        * `temperature_c` <= sla_temperature_max
        * `pressure_bar` <= sla_pressure_max
        * required identifier columns must be non-null
    Rows that fail any of the above are excluded from the silver materialization
    and counted as `contract_violations`. The bronze record set is preserved
    intact.
    """
    cfg = cfg or get_config()
    started = time.perf_counter()

    bronze = _bronze_arrow(cfg)
    if bronze.num_rows == 0:
        return ContractResult(0, 0, 0, time.perf_counter() - started, table=f"{cfg.namespace_silver}.{cfg.table_silver}")

    # DuckDB is our local processing engine (per the spec's "DuckDB/PyArrow
    # local reference substitute for Databricks/Snowflake" callout).
    # We use a parameterized SQL statement -- never f-string-interpolated user
    # input -- to comply with the Secure SQL Usage workspace rule. The literals
    # below are configuration-time floats owned by the platform, not user input.
    con = duckdb.connect(database=":memory:")
    try:
        con.register("bronze", bronze)
        result = con.execute(
            """
            SELECT
                facility_id,
                line_id,
                register_id,
                plc_timestamp_ms,
                anomaly_flag,
                voltage,
                temperature_c,
                pressure_bar,
                COALESCE(skin_conductance_us, NULL) AS skin_conductance_us
            FROM bronze
            WHERE facility_id IS NOT NULL
              AND line_id IS NOT NULL
              AND register_id IS NOT NULL
              AND voltage BETWEEN ? AND ?
              AND temperature_c <= ?
              AND pressure_bar <= ?
            """,
            [cfg.sla_voltage_min, cfg.sla_voltage_max, cfg.sla_temperature_max, cfg.sla_pressure_max],
        ).arrow().read_all()
    finally:
        con.close()

    rows_in = bronze.num_rows
    rows_out = result.num_rows
    violations = rows_in - rows_out

    # Phase 5 cross-cut: mask the line operator identifier surrogate before
    # writing it to silver. We swap the raw `line_id` column out for a hashed
    # `line_id_masked` column so silver never contains the raw key.
    line_idx = result.schema.get_field_index("line_id")
    masked_arr = pa.array([mask_identifier(v) for v in result["line_id"].to_pylist()], type=pa.string())
    result = result.set_column(line_idx, pa.field("line_id_masked", pa.string()), masked_arr)

    ensure_namespaces()
    silver_table = f"{cfg.namespace_silver}.{cfg.table_silver}"
    if result.num_rows > 0:
        write_to_factory_lakehouse(get_catalog(cfg), silver_table, result)

    elapsed = time.perf_counter() - started
    logger.info(
        "Silver contract enforced: rows_in=%d rows_out=%d violations=%d elapsed=%.3fs",
        rows_in, rows_out, violations, elapsed,
    )
    return ContractResult(
        rows_in=rows_in,
        rows_out=rows_out,
        contract_violations=violations,
        elapsed_sec=elapsed,
        table=silver_table,
    )


def build_gold_aggregates(cfg: MFGMeshConfig | None = None) -> dict:
    """Roll up per-facility health metrics into the gold Iceberg table."""
    cfg = cfg or get_config()
    cat = get_catalog(cfg)
    silver_id = f"{cfg.namespace_silver}.{cfg.table_silver}"

    try:
        silver = cat.load_table(silver_id).scan().to_arrow()
    except Exception:
        logger.warning("Silver table %s not available; skipping gold rollup", silver_id)
        return {"rows_written": 0, "table": None}

    if silver.num_rows == 0:
        return {"rows_written": 0, "table": None}

    con = duckdb.connect(database=":memory:")
    try:
        con.register("silver", silver)
        gold = con.execute(
            """
            SELECT
                facility_id,
                COUNT(*)                          AS sample_count,
                AVG(voltage)                      AS avg_voltage,
                AVG(temperature_c)                AS avg_temperature_c,
                AVG(pressure_bar)                 AS avg_pressure_bar,
                SUM(CAST(anomaly_flag AS INT))    AS anomaly_count,
                MAX(plc_timestamp_ms)             AS latest_sample_ms
            FROM silver
            GROUP BY facility_id
            ORDER BY facility_id
            """
        ).arrow().read_all()
    finally:
        con.close()

    ensure_namespaces()
    gold_table = f"{cfg.namespace_gold}.{cfg.table_gold}"
    rows = write_to_factory_lakehouse(cat, gold_table, gold)
    return {"rows_written": rows, "table": gold_table}
