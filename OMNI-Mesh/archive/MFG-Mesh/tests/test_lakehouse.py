"""Phase 2 + Phase 3 integration tests against the local Iceberg catalog."""

from __future__ import annotations

from mfg_mesh.config import get_config
from mfg_mesh.edge.opc_ua_simulator import OpcUaSimulator
from mfg_mesh.lakehouse.catalog import get_catalog
from mfg_mesh.lakehouse.ingest import run_bronze_ingest
from mfg_mesh.lakehouse.schema_manager import current_columns
from mfg_mesh.quality.contracts import build_gold_aggregates, enforce_silver_contract


def test_bronze_ingest_creates_table_and_persists_rows():
    cfg = get_config()
    sim = OpcUaSimulator(
        facilities=cfg.facilities,
        lines_per_facility=cfg.lines_per_facility,
        registers_per_line=cfg.registers_per_line,
        anomaly_rate=0.1,
        schema_drift_after=None,
        seed=11,
    )
    result = run_bronze_ingest(sim.batch(120))
    assert result["rows_written"] == 120
    assert result["table"] == f"{cfg.namespace_bronze}.{cfg.table_bronze}"

    cat = get_catalog(cfg)
    cols = list(current_columns(cat, result["table"]))
    assert "voltage" in cols
    assert "facility_id" in cols


def test_schema_evolution_adds_new_register_column():
    cfg = get_config()
    sim_initial = OpcUaSimulator(
        facilities=cfg.facilities,
        lines_per_facility=1,
        registers_per_line=2,
        schema_drift_after=None,
        seed=21,
    )
    run_bronze_ingest(sim_initial.batch(20))

    sim_drift = OpcUaSimulator(
        facilities=cfg.facilities,
        lines_per_facility=1,
        registers_per_line=2,
        schema_drift_after=0,  # immediately drift
        anomaly_rate=0.0,
        seed=22,
    )
    run_bronze_ingest(sim_drift.batch(10))

    cat = get_catalog(cfg)
    cols = list(current_columns(cat, f"{cfg.namespace_bronze}.{cfg.table_bronze}"))
    assert "skin_conductance_us" in cols, cols


def test_silver_contract_flags_violations_and_builds_gold():
    cfg = get_config()
    sim = OpcUaSimulator(
        facilities=cfg.facilities,
        lines_per_facility=cfg.lines_per_facility,
        registers_per_line=cfg.registers_per_line,
        anomaly_rate=0.4,    # force violations
        schema_drift_after=None,
        seed=31,
    )
    run_bronze_ingest(sim.batch(150))

    result = enforce_silver_contract(cfg)
    assert result.rows_in > 0
    assert 0 <= result.rows_out <= result.rows_in
    assert result.contract_violations == result.rows_in - result.rows_out
    assert result.elapsed_sec >= 0.0

    gold = build_gold_aggregates(cfg)
    assert gold["rows_written"] >= 0
    assert gold["table"] is None or gold["table"].startswith("gold.")
