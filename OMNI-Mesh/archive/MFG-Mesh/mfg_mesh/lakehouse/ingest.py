"""Hardened bronze-layer ingest.

Implements the exact pattern from the spec: explicit `try/except` around table
creation to defuse the TOCTOU race when multiple workers try to bootstrap the
same Iceberg table concurrently. We also opportunistically widen the schema
in place when a freshly-arrived batch contains new sensor columns (Phase 2
schema evolution).
"""

from __future__ import annotations

import logging
from typing import Iterable, Sequence

import pyarrow as pa
from pyiceberg.catalog import Catalog
from pyiceberg.exceptions import NoSuchTableError, TableAlreadyExistsError

from ..config import get_config
from ..edge.opc_ua_simulator import SensorReading
from .catalog import ensure_namespaces, get_catalog
from .schema_manager import evolve_industrial_schema

logger = logging.getLogger(__name__)


# Stable known-payload keys. New keys (e.g. `skin_conductance_us`) will be
# detected at runtime and added via the schema manager.
_BASE_PAYLOAD_KEYS: tuple[str, ...] = ("voltage", "temperature_c", "pressure_bar")


def readings_to_arrow(readings: Sequence[SensorReading]) -> pa.Table:
    """Flatten ``SensorReading`` rows into a wide Arrow table.

    Payload keys become top-level columns so Iceberg can prune & evolve them
    without forcing downstream consumers to parse JSON blobs.
    """
    if not readings:
        raise ValueError("readings batch must not be empty")

    # Collect the union of payload keys actually present in this batch.
    payload_keys: list[str] = list(_BASE_PAYLOAD_KEYS)
    for r in readings:
        for k in r.sensor_payload.keys():
            if k not in payload_keys:
                payload_keys.append(k)

    rows: dict[str, list] = {
        "facility_id": [r.facility_id for r in readings],
        "line_id": [r.line_id for r in readings],
        "register_id": [r.register_id for r in readings],
        "plc_timestamp_ms": [r.plc_timestamp_ms for r in readings],
        "anomaly_flag": [r.anomaly_flag for r in readings],
    }
    for key in payload_keys:
        rows[key] = [float(r.sensor_payload.get(key)) if r.sensor_payload.get(key) is not None else None for r in readings]

    schema = pa.schema(
        [
            pa.field("facility_id", pa.string(), nullable=False),
            pa.field("line_id", pa.string(), nullable=False),
            pa.field("register_id", pa.string(), nullable=False),
            pa.field("plc_timestamp_ms", pa.int64(), nullable=False),
            pa.field("anomaly_flag", pa.bool_(), nullable=False),
            *(pa.field(k, pa.float64(), nullable=True) for k in payload_keys),
        ]
    )
    return pa.table(rows, schema=schema)


def write_to_factory_lakehouse(
    cat: Catalog,
    table_identifier: str,
    arrow_batch: pa.Table,
) -> int:
    """Append an Arrow batch to an Iceberg table, hardened against races.

    Returns the number of rows appended. Mirrors the spec exactly:

    * `load_table` first; if missing, attempt `create_table`.
    * Treat a concurrent `TableAlreadyExistsError` as a recoverable race —
      reload and continue.
    * Once the table exists, widen the schema in place if the incoming batch
      introduced new columns, then append without rewriting history.
    """
    try:
        tbl = cat.load_table(table_identifier)
    except NoSuchTableError:
        try:
            tbl = cat.create_table(table_identifier, schema=arrow_batch.schema)
            logger.info("Created Iceberg table %s", table_identifier)
        except TableAlreadyExistsError:
            tbl = cat.load_table(table_identifier)

    # In-place schema evolution if the batch widened the columns.
    evolve_industrial_schema(cat, table_identifier, arrow_batch.schema)
    tbl = cat.load_table(table_identifier)  # reload to pick up new schema

    # Align the Arrow batch to the current table schema (adds NULLs for any
    # columns we don't have in this batch). This keeps appends safe even
    # after schema evolution from prior batches.
    target_schema = tbl.schema().as_arrow()
    aligned = _align_batch(arrow_batch, target_schema)

    tbl.append(aligned)
    logger.info("Appended %d rows to %s", aligned.num_rows, table_identifier)
    return aligned.num_rows


def _align_batch(batch: pa.Table, target: pa.Schema) -> pa.Table:
    """Project `batch` onto `target`, filling missing columns with NULLs."""
    columns: dict[str, pa.Array] = {}
    n = batch.num_rows
    for field in target:
        if field.name in batch.schema.names:
            arr = batch[field.name]
            # Promote types if the table widened (e.g. int -> float64).
            if arr.type != field.type:
                arr = arr.cast(field.type, safe=False)
            columns[field.name] = arr
        else:
            columns[field.name] = pa.nulls(n, type=field.type)
    return pa.table(columns, schema=target)


def run_bronze_ingest(readings: Iterable[SensorReading]) -> dict:
    """Convenience helper: convert readings -> Arrow -> bronze Iceberg table."""
    cfg = get_config()
    readings_list = list(readings)
    if not readings_list:
        return {"rows_written": 0, "table": None}

    ensure_namespaces()
    table_identifier = f"{cfg.namespace_bronze}.{cfg.table_bronze}"
    arrow_batch = readings_to_arrow(readings_list)
    cat = get_catalog(cfg)
    rows_written = write_to_factory_lakehouse(cat, table_identifier, arrow_batch)
    return {"rows_written": rows_written, "table": table_identifier}
