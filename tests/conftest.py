"""Test isolation: valid salt, per-test temp data root, and full lru_cache purge.

Merges the conftest patterns from all three source projects. Pytest runs the whole
suite in one process, so cached singletons (settings, catalog, salt, chroma client)
must be cleared between tests or monkeypatched env vars would leak.
"""

from __future__ import annotations

import pytest

PROFILES = ["ROBOTICS", "MANUFACTURING", "HEALTH_TECH", "COMMERCIAL", "CLINICAL"]


def _clear_caches() -> None:
    from config import settings
    from data_platform import catalog, governance
    from data_platform.ai_readiness import vector_store

    settings.get_settings.cache_clear()
    governance.reset_secret_cache()
    catalog.reset_catalog_cache()
    vector_store.reset_client_cache()


@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("OMNI_MESH_MASKING_SALT", "unit-test-salt-1234567890")
    monkeypatch.setenv("OMNI_MESH_DATA_ROOT", str(tmp_path / "omni"))
    monkeypatch.setenv("OMNI_MESH_PROFILE", "ROBOTICS")
    _clear_caches()
    yield
    _clear_caches()


@pytest.fixture(params=PROFILES)
def profile(request, monkeypatch):
    monkeypatch.setenv("OMNI_MESH_PROFILE", request.param)
    _clear_caches()
    return request.param
