"""Shared runtime configuration for HEAL-Mesh local execution.

All values can be overridden via environment variables (see ``.env.example``).
Importing this module is side-effect free aside from reading ``.env``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# ``override=False`` so that real shell exports always win over the .env file.
load_dotenv(override=False)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data"

# Keep Hugging Face downloads inside the workspace so the demo never needs
# write access to ``~/.cache``. Real deployments override HF_HOME to a shared
# read-only model registry.
os.environ.setdefault("HF_HOME", str(DATA_ROOT / "cache" / "hf"))
os.environ.setdefault("HEAL_MESH_PROJECT_ROOT", str(PROJECT_ROOT))


@dataclass(frozen=True)
class Settings:
    """Strongly-typed runtime settings used across phases.

    All defaults are resolved at construction time so that tests can use
    ``monkeypatch.setenv`` and then call ``get_settings()`` again to observe
    the change.
    """

    catalog_name: str = field(
        default_factory=lambda: os.getenv("HEAL_MESH_CATALOG_NAME", "heal_mesh")
    )
    catalog_uri: str = field(
        default_factory=lambda: os.getenv(
            "HEAL_MESH_CATALOG_URI",
            f"sqlite:///{DATA_ROOT}/lakehouse/catalog.db",
        )
    )
    warehouse_path: Path = field(
        default_factory=lambda: Path(
            os.getenv("HEAL_MESH_WAREHOUSE_PATH", str(DATA_ROOT / "lakehouse" / "warehouse"))
        )
    )

    # Phase 3 — PHI salt. We refuse to run if the placeholder is still in use
    # so that the macro never produces predictable hashes in production.
    phi_salt: str = field(default_factory=lambda: os.getenv("HEAL_MESH_PHI_SALT", ""))

    embedding_model: str = field(
        default_factory=lambda: os.getenv(
            "HEAL_MESH_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        )
    )
    vector_db_path: Path = field(
        default_factory=lambda: Path(
            os.getenv("HEAL_MESH_VECTOR_DB_PATH", str(DATA_ROOT / "vector" / "chroma"))
        )
    )

    log_level: str = field(default_factory=lambda: os.getenv("HEAL_MESH_LOG_LEVEL", "INFO"))
    otel_service_name: str = field(
        default_factory=lambda: os.getenv("HEAL_MESH_OTEL_SERVICE_NAME", "heal-mesh")
    )

    def ensure_dirs(self) -> None:
        """Create local-only directories. Cloud deployments skip this entirely."""
        for d in (
            self.warehouse_path,
            self.vector_db_path,
            DATA_ROOT / "lakehouse",
            DATA_ROOT / "warehouse",
            DATA_ROOT / "vector",
        ):
            d.mkdir(parents=True, exist_ok=True)

    def assert_phi_salt(self) -> None:
        """Refuse to run with a default / empty PHI salt."""
        if not self.phi_salt or self.phi_salt.startswith("replace-me"):
            raise RuntimeError(
                "HEAL_MESH_PHI_SALT is unset or still using the placeholder value. "
                "Set a real salt sourced from your secret manager before processing PHI."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide singleton ``Settings``.

    The result is cached so ``assert_phi_salt`` cannot be silently bypassed by
    a re-instantiated dataclass that re-reads env vars on every call. Tests
    must invoke ``get_settings.cache_clear()`` (see ``conftest.py``) after
    monkeypatching ``HEAL_MESH_*`` environment variables, otherwise the cached
    instance from a previous test would be observed.
    """
    return Settings()


def configure_logging(level: str | None = None) -> logging.Logger:
    """Configure root logging with a structured-ish format.

    NOTE (logging_rule): we deliberately do **not** log raw payloads. Callers
    must only emit non-sensitive correlation IDs and operation outcomes.
    """
    s = get_settings()
    logging.basicConfig(
        level=(level or s.log_level).upper(),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    return logging.getLogger("heal_mesh")
