"""Dagster asset graph for MFG-Mesh.

Each asset returns a `MaterializeResult` with rich SLA metadata so the
asset-lineage UI doubles as a data-trustworthiness dashboard for Forward
Deployed Engineers (matches the spec exactly).
"""

from __future__ import annotations

import time

from dagster import (
    AssetExecutionContext,
    Definitions,
    MaterializeResult,
    MetadataValue,
    asset,
)

from ..config import get_config
from ..edge.opc_ua_simulator import OpcUaSimulator
from ..lakehouse.ingest import run_bronze_ingest
from ..quality.contracts import build_gold_aggregates, enforce_silver_contract
from ..rag.chunker import build_failure_chunks
from ..rag.vector_store import FactoryFailureIndex
from ..security import assert_platform_secrets

DEFAULT_BATCH_SIZE = 500


@asset(description="OPC UA telemetry simulator → bronze Iceberg table.")
def telemetry_bronze(context: AssetExecutionContext) -> MaterializeResult:
    assert_platform_secrets()
    cfg = get_config()
    sim = OpcUaSimulator(
        facilities=cfg.facilities,
        lines_per_facility=cfg.lines_per_facility,
        registers_per_line=cfg.registers_per_line,
        anomaly_rate=0.08,
        schema_drift_after=DEFAULT_BATCH_SIZE // 2,
        seed=42,
    )
    started = time.perf_counter()
    readings = sim.batch(DEFAULT_BATCH_SIZE)
    result = run_bronze_ingest(readings)
    elapsed = time.perf_counter() - started

    return MaterializeResult(
        metadata={
            "factory_rows_processed": MetadataValue.int(result["rows_written"]),
            "iceberg_table": MetadataValue.text(str(result["table"])),
            "execution_duration_sec": MetadataValue.float(elapsed),
            "facilities": MetadataValue.text(", ".join(cfg.facilities)),
        }
    )


@asset(deps=["telemetry_bronze"], description="Silver layer with enforced SLA contracts.")
def telemetry_silver_processing(context: AssetExecutionContext) -> MaterializeResult:
    result = enforce_silver_contract()
    return MaterializeResult(
        metadata={
            "factory_rows_processed": MetadataValue.int(result.rows_out),
            "sla_contract_violations": MetadataValue.int(result.contract_violations),
            "pipeline_success_flag": MetadataValue.bool(result.pipeline_success_flag),
            "execution_duration_sec": MetadataValue.float(result.elapsed_sec),
            "iceberg_table": MetadataValue.text(result.table),
        }
    )


@asset(deps=["telemetry_silver_processing"], description="Gold rollup per facility.")
def facility_health_gold(context: AssetExecutionContext) -> MaterializeResult:
    started = time.perf_counter()
    result = build_gold_aggregates()
    elapsed = time.perf_counter() - started
    return MaterializeResult(
        metadata={
            "factory_rows_processed": MetadataValue.int(result["rows_written"]),
            "iceberg_table": MetadataValue.text(str(result["table"])),
            "execution_duration_sec": MetadataValue.float(elapsed),
        }
    )


@asset(deps=["telemetry_bronze"], description="Failure-event chunks indexed for RAG search.")
def failure_taxonomy_index(context: AssetExecutionContext) -> MaterializeResult:
    started = time.perf_counter()
    chunks = build_failure_chunks()
    index = FactoryFailureIndex()
    upserted = index.upsert(chunks)
    elapsed = time.perf_counter() - started
    return MaterializeResult(
        metadata={
            "chunks_indexed": MetadataValue.int(upserted),
            "collection_size": MetadataValue.int(index.count()),
            "execution_duration_sec": MetadataValue.float(elapsed),
        }
    )


defs = Definitions(
    assets=[
        telemetry_bronze,
        telemetry_silver_processing,
        facility_health_gold,
        failure_taxonomy_index,
    ]
)
