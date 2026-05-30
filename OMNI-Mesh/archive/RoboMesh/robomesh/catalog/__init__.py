"""Apache Iceberg local catalog wrapper (Phase 1 — Unified storage layer)."""
from robomesh.catalog.iceberg import (
    get_catalog,
    ensure_namespaces,
    register_bronze_table,
    list_tables,
)

__all__ = [
    "get_catalog",
    "ensure_namespaces",
    "register_bronze_table",
    "list_tables",
]
