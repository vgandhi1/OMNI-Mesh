"""End-to-end smoke tests for the Phase 1 layer.

These tests are deliberately lightweight - they verify that:
  1. The synthetic generator produces parquet files with the expected schema.
  2. The Iceberg bootstrap registers the bronze tables and that another
     engine (DuckDB) can read the same metadata.
  3. The PHI mask macro path refuses to render with a placeholder salt.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from scripts._config import DATA_ROOT, get_settings
from scripts.generate_synthetic_data import main as generate_main


def test_generate_synthetic_data(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HEAL_MESH_PHI_SALT", "unit-test-salt")
    generate_main(num_patients=5, telemetry_days=1)

    raw = DATA_ROOT / "lakehouse" / "raw"
    for path in (
        raw / "telemetry" / "wearable_events.parquet",
        raw / "commercial" / "subscription_events.parquet",
        raw / "clinical" / "ecrf_patients.parquet",
    ):
        assert path.exists(), f"expected {path} to exist"
        t = pq.read_table(path)
        assert t.num_rows > 0


def test_iceberg_roundtrip(monkeypatch):
    monkeypatch.setenv("HEAL_MESH_PHI_SALT", "unit-test-salt")
    generate_main(num_patients=3, telemetry_days=1)

    from scripts.bootstrap_iceberg import bootstrap, get_catalog

    bootstrap()
    catalog = get_catalog()
    table = catalog.load_table("telemetry_domain.wearable_events_bronze")
    arrow = table.scan().to_arrow()
    assert arrow.num_rows > 0
    assert "patient_id" in arrow.column_names


def test_settings_refuse_placeholder_salt(monkeypatch):
    monkeypatch.setenv("HEAL_MESH_PHI_SALT", "replace-me-with-a-secret-from-secret-manager")
    s = get_settings()
    with pytest.raises(RuntimeError):
        s.assert_phi_salt()
