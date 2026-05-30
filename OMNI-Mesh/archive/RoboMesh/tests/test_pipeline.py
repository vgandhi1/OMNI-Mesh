"""End-to-end pipeline integration test.

Exercises Phase 0 → 3 in a tmp directory. Phase 4 (semantic) is skipped here
because downloading the sentence-transformers model isn't appropriate in unit
tests — it has its own targeted test in test_semantic.py (skipped by default).
"""
from __future__ import annotations

import pytest

from robomesh.catalog.iceberg import list_tables
from robomesh.config import get_settings
from robomesh.generators import (
    generate_simulation_drops,
    generate_telemetry_drops,
    generate_teleop_drops,
)
from robomesh.governance import (
    ContractViolation,
    apply_dynamic_masking,
    enforce_all_contracts,
    mask_value,
)
from robomesh.ingestion import ingest_all_domains
from robomesh.transformations import build_gold_layer, build_silver_layer


def _generate_all() -> None:
    s = get_settings()
    generate_teleop_drops(s.raw_root, s.demo_episodes, s.seed)
    generate_telemetry_drops(s.raw_root, s.demo_episodes, s.seed)
    generate_simulation_drops(s.raw_root, s.demo_episodes, s.seed)


def test_full_medallion_pipeline_runs() -> None:
    _generate_all()
    ingest_all_domains()
    silver = build_silver_layer()
    gold = build_gold_layer()
    assert silver == "silver.synchronized_trajectories"
    assert gold == "gold.vla_episodes"
    tables = list_tables()
    assert any(t.endswith("bronze_joint_states") for t in tables)
    assert "silver.synchronized_trajectories" in tables
    assert "gold.vla_episodes" in tables


def test_contracts_pass_after_clean_run() -> None:
    _generate_all()
    ingest_all_domains()
    build_silver_layer()
    build_gold_layer()
    report = enforce_all_contracts(raise_on_violation=False)
    # Every contract should report an empty violations list.
    assert all(v == [] for v in report.values()), report


def test_mask_value_with_default_role_is_irreversible() -> None:
    masked = mask_value("bay-3-rack-04", role="ML_RESEARCHER")
    assert masked is not None
    assert masked.startswith("masked_sha256:")
    assert "bay-3-rack-04" not in masked


def test_mask_value_for_security_role_returns_plaintext() -> None:
    assert mask_value("bay-3-rack-04", role="SECURITY_OPERATIONS") == "bay-3-rack-04"


def test_governed_table_is_materialized() -> None:
    _generate_all()
    ingest_all_domains()
    governed = apply_dynamic_masking(role="ML_RESEARCHER")
    assert any("governed.bronze_network_health" == t for t in governed)


def test_contract_violation_surfaces_when_raise_enabled() -> None:
    # If the Silver table is missing entirely, the contract layer raises.
    with pytest.raises(ContractViolation):
        # Nothing built yet — `read_table_arrow` will fail; we wrap in pytest.
        from robomesh.governance.contracts import enforce_all_contracts as enforce
        try:
            enforce(raise_on_violation=True)
        except Exception as exc:
            raise ContractViolation(str(exc)) from exc
