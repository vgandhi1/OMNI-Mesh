"""Deterministic semantic chunking of anomaly events.

Produces the exact "Facility: ... | Line: ... | Anomaly detected ..." string
format from the spec, with stable IDs derived from the source record so the
vector store is idempotent across re-runs.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List

import pyarrow as pa

from ..config import MFGMeshConfig, get_config
from ..lakehouse.catalog import get_catalog

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FailureChunk:
    chunk_id: str
    text: str
    facility_id: str
    line_id_masked: str
    register_id: str
    plc_timestamp_ms: int
    voltage: float | None
    temperature_c: float | None
    pressure_bar: float | None


def _format_event(row: dict, *, sla_voltage_min: float, sla_voltage_max: float, sla_temperature_max: float, sla_pressure_max: float) -> str:
    ts = datetime.fromtimestamp(row["plc_timestamp_ms"] / 1000.0, tz=timezone.utc)
    fragments: List[str] = [
        f"Facility: {row['facility_id']}",
        f"Line: {row['line_id_masked']}",
        f"Anomaly detected at {ts.strftime('%H:%M:%S UTC on %Y-%m-%d')}.",
    ]
    register = row["register_id"]
    voltage = row.get("voltage")
    temperature = row.get("temperature_c")
    pressure = row.get("pressure_bar")
    if voltage is not None and (voltage < sla_voltage_min or voltage > sla_voltage_max):
        fragments.append(
            f"Machine register {register} voltage drifted to {voltage:.2f}V "
            f"(SLA window: {sla_voltage_min:.1f}-{sla_voltage_max:.1f}V)."
        )
    if temperature is not None and temperature > sla_temperature_max:
        fragments.append(
            f"Register {register} temperature reached {temperature:.1f}C "
            f"(SLA max: {sla_temperature_max:.1f}C)."
        )
    if pressure is not None and pressure > sla_pressure_max:
        fragments.append(
            f"Register {register} pressure spiked to {pressure:.2f}bar "
            f"(SLA max: {sla_pressure_max:.2f}bar)."
        )
    fragments.append(f"Failure localized to {register}.")
    return " ".join(fragments)


def _chunk_id(row: dict) -> str:
    raw = f"{row['facility_id']}|{row['line_id_masked']}|{row['register_id']}|{row['plc_timestamp_ms']}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def build_failure_chunks(cfg: MFGMeshConfig | None = None) -> List[FailureChunk]:
    """Materialize anomaly chunks from the bronze table.

    We scan bronze (not silver) because we want the failed records — silver is
    the *cleaned* set with SLA breaches removed.
    """
    cfg = cfg or get_config()
    cat = get_catalog(cfg)
    try:
        bronze = cat.load_table(f"{cfg.namespace_bronze}.{cfg.table_bronze}").scan().to_arrow()
    except Exception:
        logger.warning("Bronze table missing; skipping chunk build")
        return []

    if bronze.num_rows == 0:
        return []

    # Only keep rows that were anomalies (either flagged at the edge or
    # outside the SLA envelope).
    filter_mask = pa.compute.or_(
        bronze["anomaly_flag"],
        pa.compute.or_(
            pa.compute.or_(
                pa.compute.less(bronze["voltage"], cfg.sla_voltage_min),
                pa.compute.greater(bronze["voltage"], cfg.sla_voltage_max),
            ),
            pa.compute.or_(
                pa.compute.greater(bronze["temperature_c"], cfg.sla_temperature_max),
                pa.compute.greater(bronze["pressure_bar"], cfg.sla_pressure_max),
            ),
        ),
    )
    anomalies = bronze.filter(filter_mask)
    if anomalies.num_rows == 0:
        return []

    from ..security import mask_identifier

    chunks: List[FailureChunk] = []
    pylist = anomalies.to_pylist()
    for row in pylist:
        row["line_id_masked"] = mask_identifier(row["line_id"])
        text = _format_event(
            row,
            sla_voltage_min=cfg.sla_voltage_min,
            sla_voltage_max=cfg.sla_voltage_max,
            sla_temperature_max=cfg.sla_temperature_max,
            sla_pressure_max=cfg.sla_pressure_max,
        )
        chunks.append(
            FailureChunk(
                chunk_id=_chunk_id(row),
                text=text,
                facility_id=row["facility_id"],
                line_id_masked=row["line_id_masked"],
                register_id=row["register_id"],
                plc_timestamp_ms=row["plc_timestamp_ms"],
                voltage=row.get("voltage"),
                temperature_c=row.get("temperature_c"),
                pressure_bar=row.get("pressure_bar"),
            )
        )
    return chunks


def dedupe(chunks: Iterable[FailureChunk]) -> List[FailureChunk]:
    seen: set[str] = set()
    out: list[FailureChunk] = []
    for c in chunks:
        if c.chunk_id in seen:
            continue
        seen.add(c.chunk_id)
        out.append(c)
    return out
