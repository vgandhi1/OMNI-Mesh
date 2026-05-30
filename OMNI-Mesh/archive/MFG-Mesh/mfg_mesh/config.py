"""Centralized runtime configuration for MFG-Mesh.

All paths are resolved relative to the repository root by default so the
end-to-end demo can run hermetically without external services.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env", override=False)


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _csv(name: str, default: List[str]) -> List[str]:
    raw = os.getenv(name)
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _resolve(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


@dataclass(frozen=True)
class MFGMeshConfig:
    """Immutable view of the platform's runtime configuration."""

    warehouse_dir: Path
    catalog_db: Path
    chroma_dir: Path

    facilities: List[str]
    lines_per_facility: int
    registers_per_line: int
    sim_interval_ms: int

    kafka_enabled: bool
    kafka_bootstrap: str
    kafka_topic: str

    embedding_model: str
    embedding_dim: int

    # Lakehouse layout
    namespace_bronze: str = "bronze"
    namespace_silver: str = "silver"
    namespace_gold: str = "gold"
    table_bronze: str = "telemetry_raw"
    table_silver: str = "telemetry_clean"
    table_gold: str = "facility_health"

    # SLA thresholds applied during quality enforcement.
    sla_voltage_min: float = 12.0
    sla_voltage_max: float = 16.0
    sla_temperature_max: float = 95.0
    sla_pressure_max: float = 9.5

    repo_root: Path = field(default=REPO_ROOT)

    def ensure_dirs(self) -> None:
        for d in (self.warehouse_dir, self.chroma_dir, self.catalog_db.parent):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_config() -> MFGMeshConfig:
    cfg = MFGMeshConfig(
        warehouse_dir=_resolve(os.getenv("MFG_MESH_WAREHOUSE_DIR", "./.mfg_mesh/warehouse")),
        catalog_db=_resolve(os.getenv("MFG_MESH_CATALOG_DB", "./.mfg_mesh/catalog.db")),
        chroma_dir=_resolve(os.getenv("MFG_MESH_CHROMA_DIR", "./.mfg_mesh/chroma")),
        facilities=_csv("MFG_MESH_FACILITIES", ["Texas_Giga_01", "Berlin_Giga_02"]),
        lines_per_facility=_int("MFG_MESH_LINES_PER_FACILITY", 2),
        registers_per_line=_int("MFG_MESH_REGISTERS_PER_LINE", 4),
        sim_interval_ms=_int("MFG_MESH_SIM_INTERVAL_MS", 50),
        kafka_enabled=_bool("MFG_MESH_KAFKA_ENABLED", False),
        kafka_bootstrap=os.getenv("MFG_MESH_KAFKA_BOOTSTRAP", "localhost:9092"),
        kafka_topic=os.getenv("MFG_MESH_KAFKA_TOPIC", "mfg.telemetry.raw"),
        embedding_model=os.getenv("MFG_MESH_EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
        embedding_dim=_int("MFG_MESH_EMBEDDING_DIM", 384),
    )
    cfg.ensure_dirs()
    return cfg
