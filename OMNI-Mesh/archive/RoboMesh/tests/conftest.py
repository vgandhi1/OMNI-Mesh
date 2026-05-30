"""Pytest configuration — every test runs in an isolated temporary lakehouse.

This conftest also clears every ``functools.lru_cache``-decorated factory in
the codebase before and after each test. Without that flush the cached
``Settings``, Iceberg ``SqlCatalog``, and ChromaDB client would survive across
tests (pytest runs in a single process by default), leaking the previous
test's monkeypatched ``ROBOMESH_DATA_ROOT`` into the next test and producing
order-dependent failures. See ``REVIEW_FEEDBACK.md`` Issue 2.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from robomesh import config


def _clear_all_lru_caches() -> None:
    """Flush every process-scoped factory we cache.

    Imports are local so an import-time failure in an optional submodule (e.g.
    ChromaDB on a stripped-down dev box) does not break test collection.
    """
    config.get_settings.cache_clear()

    from robomesh.catalog import iceberg

    iceberg.get_catalog.cache_clear()

    from robomesh.cv import tensor_store

    tensor_store.get_tensor_store.cache_clear()

    try:
        from robomesh.cv import feature_extractor
    except Exception:  # noqa: BLE001 — optional torchvision path
        feature_extractor = None  # type: ignore[assignment]
    if feature_extractor is not None:
        feature_extractor._torch_backbone.cache_clear()

    try:
        from robomesh.semantic import vector_store
    except Exception:  # noqa: BLE001 — optional ChromaDB import path
        vector_store = None  # type: ignore[assignment]
    if vector_store is not None:
        vector_store._client.cache_clear()

    try:
        from robomesh.semantic import embeddings
    except Exception:  # noqa: BLE001 — optional sentence-transformers path
        embeddings = None  # type: ignore[assignment]
    if embeddings is not None:
        embeddings._model.cache_clear()


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``ROBOMESH_DATA_ROOT`` at a per-test tmp directory.

    Every cached factory is cleared on entry *and* exit so cross-test state
    cannot leak in either direction.
    """
    root = tmp_path / "robomesh-data"
    monkeypatch.setenv("ROBOMESH_DATA_ROOT", str(root))
    monkeypatch.setenv("ROBOMESH_DEMO_EPISODES", "4")
    monkeypatch.setenv("ROBOMESH_SEED", "7")
    # A real, non-placeholder salt so masking is exercised end-to-end. We
    # never log this value; see logging_rule §1.
    monkeypatch.setenv("ROBOMESH_MASKING_SALT", "robomesh-pytest-salt")

    _clear_all_lru_caches()
    yield root
    _clear_all_lru_caches()
