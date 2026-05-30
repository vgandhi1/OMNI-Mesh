"""Iceberg REST-catalog-equivalent for local development.

In production MFG-Mesh would point at Apache Polaris or AWS Glue. For the
runnable reference we use the SQL-backed catalog with a SQLite file, which
gives us atomic table commits + namespaces without external infra.
"""

from __future__ import annotations

import logging
from typing import Iterable

from pyiceberg.catalog import Catalog
from pyiceberg.catalog.sql import SqlCatalog

from ..config import MFGMeshConfig, get_config

logger = logging.getLogger(__name__)

# Process-wide cache keyed on the (catalog_db, warehouse_dir) tuple. We can't
# use `lru_cache(get_catalog)` because the config dataclass contains list
# fields (e.g. `facilities`) and is therefore unhashable.
_CATALOG_CACHE: dict[tuple[str, str], Catalog] = {}


def get_catalog(cfg: MFGMeshConfig | None = None) -> Catalog:
    """Return a process-wide cached Iceberg catalog handle."""
    cfg = cfg or get_config()
    cfg.ensure_dirs()
    cache_key = (str(cfg.catalog_db.resolve()), str(cfg.warehouse_dir.resolve()))
    cached = _CATALOG_CACHE.get(cache_key)
    if cached is not None:
        return cached
    uri = f"sqlite:///{cfg.catalog_db}"
    warehouse_uri = f"file://{cfg.warehouse_dir.resolve()}"
    catalog = SqlCatalog(
        "mfg_mesh",
        **{
            "uri": uri,
            "warehouse": warehouse_uri,
        },
    )
    _CATALOG_CACHE[cache_key] = catalog
    logger.info("Iceberg catalog ready (warehouse=%s)", cfg.warehouse_dir)
    return catalog


def reset_catalog_cache() -> None:
    """Test hook: drop the process-wide catalog cache."""
    _CATALOG_CACHE.clear()


def ensure_namespaces(catalog: Catalog | None = None, namespaces: Iterable[str] | None = None) -> None:
    """Create the bronze/silver/gold namespaces if they do not already exist."""
    cfg = get_config()
    cat = catalog or get_catalog(cfg)
    namespaces = list(namespaces or (cfg.namespace_bronze, cfg.namespace_silver, cfg.namespace_gold))
    existing = {".".join(n) for n in cat.list_namespaces()}
    for ns in namespaces:
        if ns not in existing:
            cat.create_namespace(ns)
            logger.info("Created namespace: %s", ns)
