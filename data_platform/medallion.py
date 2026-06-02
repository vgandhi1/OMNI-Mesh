"""Phase 2 medallion: Bronze (Iceberg) -> dbt-duckdb Silver/Gold -> back to Iceberg.

The polymorphic ``dbt/`` project has one model folder per profile. We export the
active profile's Bronze Iceberg table to a parquet drop (what the dbt sources read
via ``read_parquet``), run ``dbt build`` for that profile's folder, then publish the
resulting silver/gold tables back into the Iceberg lakehouse so it stays the system
of record.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys

import duckdb
import pyarrow.parquet as pq

from config.profiles import active_spec
from config.settings import get_settings
from data_platform import catalog

logger = logging.getLogger("omni_mesh.medallion")


def export_bronze_parquet() -> str:
    """Materialize the active profile's Bronze Iceberg table as a parquet drop."""
    settings = get_settings()
    settings.ensure_dirs()
    spec = active_spec()
    arrow = catalog.read_table_arrow(f"{catalog.NAMESPACE_BRONZE}.{spec.bronze_table}")
    target = settings.bronze_parquet
    pq.write_table(arrow, target)
    logger.info("exported %d bronze rows -> %s", arrow.num_rows, target)
    return str(target)


def _dbt_executable() -> str:
    found = shutil.which("dbt")
    if found:
        return found
    candidate = os.path.join(os.path.dirname(sys.executable), "dbt")
    if os.path.exists(candidate):
        return candidate
    return "dbt"


def run_dbt(command: str = "build") -> int:
    """Run ``dbt <command>`` for the active profile's model folder."""
    settings = get_settings()
    env = {
        **os.environ,
        "OMNI_MESH_BRONZE_PARQUET": str(settings.bronze_parquet),
        "OMNI_MESH_DBT_DUCKDB": str(settings.duckdb_path),
    }
    cmd = [
        _dbt_executable(),
        command,
        "--project-dir",
        str(settings.dbt_dir),
        "--profiles-dir",
        str(settings.dbt_dir),
        "--select",
        settings.dbt_selector,
        "--no-version-check",
    ]
    logger.info("running dbt: %s", " ".join(cmd))
    result = subprocess.run(cmd, env=env, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"dbt {command} failed (exit {result.returncode}) for profile "
            f"{settings.profile.value}"
        )
    return result.returncode


def publish_to_iceberg() -> dict[str, int]:
    """Copy dbt silver_/gold_ tables from DuckDB into the Iceberg lakehouse."""
    settings = get_settings()
    published: dict[str, int] = {}
    connection = duckdb.connect(str(settings.duckdb_path), read_only=True)
    try:
        names = [
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name LIKE 'silver_%' OR table_name LIKE 'gold_%'"
            ).fetchall()
        ]
        for name in names:
            arrow = connection.execute(f'SELECT * FROM "{name}"').arrow()
            namespace = catalog.NAMESPACE_SILVER if name.startswith("silver_") else catalog.NAMESPACE_GOLD
            written = catalog.write_data_product(namespace, name, arrow, overwrite=True)
            published[f"{namespace}.{name}"] = written
    finally:
        connection.close()
    return published


def run_medallion() -> dict[str, int]:
    """Full Phase 2 pass: export Bronze -> dbt build -> publish to Iceberg."""
    export_bronze_parquet()
    run_dbt("build")
    return publish_to_iceberg()
