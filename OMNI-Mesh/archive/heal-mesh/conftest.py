"""Pytest conftest for HEAL-Mesh.

* Ensures the package root is on ``sys.path`` so module-style imports
  (``from scripts.bootstrap_iceberg import ...``) resolve regardless of the
  current working directory pytest is invoked from.
* Provides an autouse fixture that flushes every process-scoped
  ``functools.lru_cache`` we use for runtime configuration. Without this
  fixture, ``get_settings()`` (and any future ``lru_cache``-decorated factory)
  would survive across tests because pytest runs the entire suite in a single
  Python process — meaning a prior test's monkeypatched env vars would leak
  into later tests via the cached :class:`Settings` instance.

Reviewer-facing note: this fixture is the test-isolation guard recommended in
``REVIEW_FEEDBACK.md`` Issue 2. It runs for every test, regardless of whether
the test imports the cached factories directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _clear_lru_caches():
    """Flush ``lru_cache``-cached factories before and after each test."""
    # Imported lazily so collecting this conftest never imports modules that
    # depend on the optional Phase 4 ChromaDB / sentence-transformers stack.
    from scripts import _config

    _config.get_settings.cache_clear()
    yield
    _config.get_settings.cache_clear()
