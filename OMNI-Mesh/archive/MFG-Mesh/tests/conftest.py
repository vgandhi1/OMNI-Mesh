"""Pytest fixtures: isolated MFG-Mesh runtime per test session."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def isolated_runtime(tmp_path_factory) -> None:
    """Point every config-driven path at a per-session temp dir."""
    base: Path = tmp_path_factory.mktemp("mfg_mesh_test")

    os.environ["MFG_MESH_MASKING_SALT"] = "test-salt-" + "x" * 32
    os.environ["MFG_MESH_WAREHOUSE_DIR"] = str(base / "warehouse")
    os.environ["MFG_MESH_CATALOG_DB"] = str(base / "catalog.db")
    os.environ["MFG_MESH_CHROMA_DIR"] = str(base / "chroma")
    os.environ["MFG_MESH_FACILITIES"] = "Texas_Giga_01,Berlin_Giga_02"
    os.environ["MFG_MESH_LINES_PER_FACILITY"] = "2"
    os.environ["MFG_MESH_REGISTERS_PER_LINE"] = "4"
    os.environ["MFG_MESH_KAFKA_ENABLED"] = "false"

    # Refresh any cached config / secrets.
    from mfg_mesh import config as cfg_mod
    from mfg_mesh import security as sec_mod

    cfg_mod.get_config.cache_clear()
    sec_mod.reset_secret_cache()
    yield
