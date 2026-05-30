"""Centralized runtime configuration for RoboMesh.

All paths, secrets, and tunables come from environment variables (see
``.env.example``) and fall back to sensible local defaults so the entire demo
runs on a laptop with zero cloud credentials.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _data_root() -> Path:
    raw = os.environ.get("ROBOMESH_DATA_ROOT", str(REPO_ROOT / "data"))
    # Resolve user-supplied path safely (Phase 3 — Path Traversal Prevention).
    # We intentionally do not call .resolve(strict=True) so the path can be
    # created on first run.
    root = Path(raw).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


# Sentinel salt values that must never reach a masking call. Any of these is
# treated as "unset" by ``Settings.assert_masking_salt`` so we fail closed
# instead of silently producing reversible tokens with a known-public key.
_PLACEHOLDER_SALTS = frozenset(
    {
        "",
        "robomesh-local-dev-salt",
        "replace-me",
        "changeme",
        "please-change-me-in-production",
    }
)
# Any salt with one of these prefixes is also rejected so accidentally
# editing only part of the placeholder still trips the assertion.
_PLACEHOLDER_PREFIXES: tuple[str, ...] = ("replace-me", "please-change-me")


@dataclass(frozen=True)
class Settings:
    """Immutable runtime configuration snapshot."""

    data_root: Path
    raw_root: Path
    warehouse_root: Path
    vectors_root: Path
    artifacts_root: Path
    catalog_db_path: Path
    masking_salt: str
    embedding_model: str
    demo_episodes: int
    seed: int
    active_role: str

    @property
    def catalog_uri(self) -> str:
        """SQLite URI accepted by ``pyiceberg.catalog.sql.SqlCatalog``."""
        return f"sqlite:///{self.catalog_db_path}"

    @property
    def duckdb_path(self) -> Path:
        return self.artifacts_root / "robomesh.duckdb"

    @property
    def chroma_path(self) -> Path:
        return self.vectors_root / "chroma"

    def assert_masking_salt(self) -> None:
        """Refuse to run when the masking salt is empty or a known placeholder.

        Mirrors HEAL-Mesh's ``assert_phi_salt``. Called at the entry of every
        masking code path so an attacker who clones the repo cannot reverse
        the HMAC tokens by re-using the default development salt.

        We deliberately compare against a small allow-list of placeholders
        instead of the much weaker "non-empty" check; the previous default
        (``"robomesh-local-dev-salt"``) is non-empty but fully public.
        """
        salt = (self.masking_salt or "").strip()
        if salt in _PLACEHOLDER_SALTS or any(
            salt.startswith(p) for p in _PLACEHOLDER_PREFIXES
        ):
            raise RuntimeError(
                "ROBOMESH_MASKING_SALT is unset or still using a placeholder. "
                "Set a real salt sourced from your secret manager before "
                "applying dynamic masking. (See REVIEW_FEEDBACK.md S3.)"
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Materialize the runtime settings exactly once per process."""
    root = _data_root()
    raw = root / "raw"
    warehouse = root / "warehouse"
    vectors = root / "vectors"
    artifacts = root / "artifacts"
    for p in (raw, warehouse, vectors, artifacts):
        p.mkdir(parents=True, exist_ok=True)

    # Note (Security rule — Sensitive data in logs):
    # The masking salt is never logged or printed. Only its presence is logged
    # in `cli.doctor` via a boolean ("set"/"unset").
    #
    # Default is the empty string (fail-closed): any masking attempt raises
    # via ``assert_masking_salt`` so a clone-and-run reviewer cannot
    # accidentally produce reversible tokens with a known-public salt. The
    # previous default ("robomesh-local-dev-salt") was non-empty and embedded
    # in this repository, defeating the entire purpose of keyed hashing.
    salt = os.environ.get("ROBOMESH_MASKING_SALT", "")

    return Settings(
        data_root=root,
        raw_root=raw,
        warehouse_root=warehouse,
        vectors_root=vectors,
        artifacts_root=artifacts,
        catalog_db_path=artifacts / "iceberg_catalog.db",
        masking_salt=salt,
        embedding_model=os.environ.get(
            "ROBOMESH_EMBEDDING_MODEL",
            "sentence-transformers/all-MiniLM-L6-v2",
        ),
        demo_episodes=int(os.environ.get("ROBOMESH_DEMO_EPISODES", "24")),
        seed=int(os.environ.get("ROBOMESH_SEED", "42")),
        active_role=os.environ.get("ROBOMESH_ACTIVE_ROLE", "ML_RESEARCHER"),
    )


# Mesh domain names used as Iceberg namespaces and Bronze sub-directories.
DOMAINS = ("teleop", "telemetry", "simulation")
