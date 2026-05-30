"""Phase 2: Medallion lakehouse on Apache Iceberg with native schema evolution."""

from .catalog import get_catalog, ensure_namespaces
from .ingest import readings_to_arrow, write_to_factory_lakehouse, run_bronze_ingest
from .schema_manager import evolve_industrial_schema

__all__ = [
    "get_catalog",
    "ensure_namespaces",
    "readings_to_arrow",
    "write_to_factory_lakehouse",
    "run_bronze_ingest",
    "evolve_industrial_schema",
]
