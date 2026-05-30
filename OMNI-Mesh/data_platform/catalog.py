"""Hardened Iceberg table manager with TOCTOU-safe writes.

Merges the concurrent-write recovery pattern shared by all three projects
(MFG-Mesh ``write_to_factory_lakehouse``, RoboMesh ``write_managed_table``,
heal-mesh ``bootstrap_iceberg``): if two workers both see a table missing, the
loser of the ``create_table`` race reloads and appends instead of crashing.
"""

from __future__ import annotations

import logging
from typing import Iterable

import pyarrow as pa
from pyiceberg.catalog.sql import SqlCatalog
from pyiceberg.exceptions import (
    NamespaceAlreadyExistsError,
    NoSuchTableError,
    TableAlreadyExistsError,
)

from config.settings import get_settings

logger = logging.getLogger("omni_mesh.catalog")

NAMESPACE_BRONZE = "bronze"
NAMESPACE_SILVER = "silver"
NAMESPACE_GOLD = "gold"
_DEFAULT_NAMESPACES = (NAMESPACE_BRONZE, NAMESPACE_SILVER, NAMESPACE_GOLD)

# Process-wide cache keyed by (profile, catalog_db, warehouse) for full isolation.
_CATALOG_CACHE: dict[tuple[str, str, str], SqlCatalog] = {}


def get_catalog() -> SqlCatalog:
    settings = get_settings()
    settings.ensure_dirs()
    key = (
        settings.profile.value,
        str(settings.catalog_db.resolve()),
        str(settings.warehouse_dir.resolve()),
    )
    catalog = _CATALOG_CACHE.get(key)
    if catalog is None:
        catalog = SqlCatalog(
            "omni_mesh",
            uri=settings.catalog_uri,
            warehouse=settings.warehouse_uri,
        )
        _CATALOG_CACHE[key] = catalog
    return catalog


def reset_catalog_cache() -> None:
    """Clear the catalog cache (test isolation hook)."""
    _CATALOG_CACHE.clear()


def ensure_namespaces(namespaces: Iterable[str] = _DEFAULT_NAMESPACES) -> None:
    catalog = get_catalog()
    existing = {".".join(n) for n in catalog.list_namespaces()}
    for namespace in namespaces:
        if namespace not in existing:
            try:
                catalog.create_namespace(namespace)
            except NamespaceAlreadyExistsError:
                pass


def _as_table(batch) -> pa.Table:
    """Coerce a pyarrow Table / RecordBatch / RecordBatchReader into a Table."""
    if isinstance(batch, pa.Table):
        return batch
    if isinstance(batch, pa.RecordBatch):
        return pa.Table.from_batches([batch])
    if hasattr(batch, "read_all"):  # RecordBatchReader
        return batch.read_all()
    return pa.table(batch)


def _align_batch(batch: pa.Table, target_schema: pa.Schema) -> pa.Table:
    """Project ``batch`` onto ``target_schema``, null-filling missing columns."""
    batch = _as_table(batch)
    columns = []
    for field in target_schema:
        if field.name in batch.schema.names:
            columns.append(batch.column(field.name).cast(field.type))
        else:
            columns.append(pa.nulls(batch.num_rows, type=field.type))
    return pa.table(columns, schema=target_schema)


def write_data_product(
    namespace: str,
    table_name: str,
    batch: pa.Table,
    *,
    expected_schema: pa.Schema | None = None,
    overwrite: bool = False,
) -> int:
    """Append (or overwrite) ``batch`` into ``namespace.table_name`` atomically."""
    catalog = get_catalog()
    ensure_namespaces([namespace])
    identifier = f"{namespace}.{table_name}"

    batch = _as_table(batch)
    if expected_schema is not None and not batch.schema.equals(
        expected_schema, check_metadata=False
    ):
        batch = _align_batch(batch, expected_schema)

    try:
        table = catalog.load_table(identifier)
    except NoSuchTableError:
        try:
            table = catalog.create_table(identifier, schema=batch.schema)
            logger.info("created iceberg table %s", identifier)
        except TableAlreadyExistsError:
            logger.info("create race lost for %s; reloading", identifier)
            table = catalog.load_table(identifier)

    aligned = _align_batch(batch, table.schema().as_arrow())
    if overwrite:
        table.overwrite(aligned)
    else:
        table.append(aligned)
    return aligned.num_rows


def read_table_arrow(identifier: str) -> pa.Table:
    return get_catalog().load_table(identifier).scan().to_arrow()
