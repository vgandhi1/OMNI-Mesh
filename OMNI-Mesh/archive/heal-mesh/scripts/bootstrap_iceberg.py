"""Phase 1 — Apache Iceberg catalog + bronze table registration.

This module is the local analogue of the blueprint's:

    "Setup a centralized, external REST catalog (e.g., Tabular, AWS Glue, or
     Polaris Catalog)."

We use ``pyiceberg``'s SQL catalog backed by SQLite, with the warehouse rooted
under ``data/lakehouse/warehouse``. All three domains land their bronze tables
into the same catalog so any compute engine that speaks Iceberg (Spark,
Snowflake external volumes, DuckDB, Trino, ...) can read them with zero copy.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
from pyiceberg.catalog import load_catalog
from pyiceberg.catalog.sql import SqlCatalog
from pyiceberg.exceptions import NamespaceAlreadyExistsError, NoSuchTableError

from scripts._config import DATA_ROOT, configure_logging, get_settings

LOG = configure_logging()
SETTINGS = get_settings()

RAW_ROOT = DATA_ROOT / "lakehouse" / "raw"

# Three logical domains == three Iceberg namespaces. In production these map to
# distinct buckets:
#   s3://healmesh-telemetry-domain/
#   s3://healmesh-commercial-domain/
#   s3://healmesh-clinical-secure/
DOMAIN_TABLES = {
    "telemetry_domain": {
        "wearable_events_bronze": RAW_ROOT / "telemetry" / "wearable_events.parquet",
    },
    "commercial_domain": {
        "subscription_events_bronze": RAW_ROOT / "commercial" / "subscription_events.parquet",
    },
    "clinical_domain": {
        "ecrf_patients_bronze": RAW_ROOT / "clinical" / "ecrf_patients.parquet",
    },
}


def get_catalog() -> SqlCatalog:
    """Return a PyIceberg SQL catalog rooted at the configured warehouse path."""
    SETTINGS.ensure_dirs()
    catalog = load_catalog(
        SETTINGS.catalog_name,
        **{
            "type": "sql",
            "uri": SETTINGS.catalog_uri,
            "warehouse": f"file://{SETTINGS.warehouse_path.resolve()}",
        },
    )
    LOG.info(
        "iceberg catalog ready name=%s warehouse=%s",
        SETTINGS.catalog_name,
        SETTINGS.warehouse_path,
    )
    return catalog


def _ensure_namespace(catalog: SqlCatalog, namespace: str) -> None:
    try:
        catalog.create_namespace(namespace)
        LOG.info("created iceberg namespace %s", namespace)
    except NamespaceAlreadyExistsError:
        LOG.debug("namespace %s already exists", namespace)


def _load_or_create_table(catalog: SqlCatalog, identifier: str, parquet_path: Path):
    """Overwrite an Iceberg table with the contents of ``parquet_path``."""
    if not parquet_path.exists():
        raise FileNotFoundError(
            f"Expected raw parquet {parquet_path} - did you run `make seed`?"
        )

    arrow_table = pq.read_table(parquet_path)

    try:
        table = catalog.load_table(identifier)
        LOG.info("overwriting existing iceberg table %s (%d rows)", identifier, arrow_table.num_rows)
        table.overwrite(arrow_table)
    except NoSuchTableError:
        LOG.info("creating new iceberg table %s (%d rows)", identifier, arrow_table.num_rows)
        catalog.create_table(identifier=identifier, schema=arrow_table.schema)
        catalog.load_table(identifier).append(arrow_table)


def bootstrap() -> None:
    catalog = get_catalog()
    for namespace, tables in DOMAIN_TABLES.items():
        _ensure_namespace(catalog, namespace)
        for table_name, parquet_path in tables.items():
            _load_or_create_table(catalog, f"{namespace}.{table_name}", parquet_path)

    LOG.info("iceberg bootstrap complete — %d namespaces registered", len(DOMAIN_TABLES))


if __name__ == "__main__":
    bootstrap()
