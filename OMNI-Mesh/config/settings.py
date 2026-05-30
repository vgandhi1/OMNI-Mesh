"""Unified runtime settings (merge of the three projects' Settings dataclasses).

Per-profile path isolation: each profile gets its own warehouse / catalog / chroma
directory under ``OMNI_MESH_DATA_ROOT/<profile>/`` so the domains never collide,
mirroring how MFG-Mesh / RoboMesh / heal-mesh each owned a separate warehouse.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from config.profiles import MeshProfile, get_active_profile

load_dotenv(override=False)  # shell exports win over .env

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _resolve(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = _REPO_ROOT / path
    return path.resolve()


@dataclass(frozen=True)
class Settings:
    profile: MeshProfile
    data_root: Path
    warehouse_dir: Path
    catalog_db: Path
    chroma_dir: Path
    masking_salt: str
    embedding_model: str
    active_role: str
    unmask_role: str
    # dbt medallion (Phase 2)
    dbt_dir: Path
    duckdb_path: Path
    bronze_parquet: Path

    @property
    def catalog_uri(self) -> str:
        return f"sqlite:///{self.catalog_db}"

    @property
    def warehouse_uri(self) -> str:
        return f"file://{self.warehouse_dir.resolve()}"

    @property
    def dbt_selector(self) -> str:
        """dbt path selector for the active profile's model folder."""
        return f"path:models/{self.profile.value.lower()}"

    def ensure_dirs(self) -> None:
        for directory in (
            self.warehouse_dir,
            self.catalog_db.parent,
            self.chroma_dir,
            self.duckdb_path.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Materialize settings once per process (cleared in tests via cache_clear)."""
    profile = get_active_profile()
    data_root = _resolve(os.getenv("OMNI_MESH_DATA_ROOT", ".omni_mesh"))
    profile_root = data_root / profile.value.lower()
    return Settings(
        profile=profile,
        data_root=data_root,
        warehouse_dir=profile_root / "warehouse",
        catalog_db=profile_root / "catalog.db",
        chroma_dir=profile_root / "chroma",
        masking_salt=os.getenv("OMNI_MESH_MASKING_SALT", ""),
        embedding_model=os.getenv(
            "OMNI_MESH_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        ),
        active_role=os.getenv("OMNI_MESH_ACTIVE_ROLE", "ML_RESEARCHER"),
        unmask_role=os.getenv("OMNI_MESH_UNMASK_ROLE", "SECURITY_OPERATIONS"),
        dbt_dir=_REPO_ROOT / "dbt",
        duckdb_path=profile_root / "dbt" / "omni_mesh.duckdb",
        bronze_parquet=profile_root / "dbt" / "bronze.parquet",
    )
