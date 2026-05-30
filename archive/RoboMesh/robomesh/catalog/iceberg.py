"""Local Apache Iceberg setup.

In production this would be a Project Polaris REST catalog backed by S3/GCS.
For the laptop reference implementation we use ``pyiceberg``'s SQLite-backed
:class:`pyiceberg.catalog.sql.SqlCatalog` writing Iceberg v2 metadata into the
local file-system warehouse — same on-disk format you would deploy to S3.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Iterable

import pyarrow as pa
import pyarrow.parquet as pq
from pyiceberg.catalog.sql import SqlCatalog
from pyiceberg.exceptions import (
    NamespaceAlreadyExistsError,
    NoSuchNamespaceError,
    NoSuchTableError,
    TableAlreadyExistsError,
)

from robomesh.config import DOMAINS, get_settings
from robomesh.logging_setup import get_logger

log = get_logger(__name__)

_CATALOG_NAME = "robomesh"


@lru_cache(maxsize=1)
def get_catalog() -> SqlCatalog:
    """Return a singleton SqlCatalog rooted at the local warehouse."""
    s = get_settings()
    log.info("iceberg.catalog.init warehouse=%s", s.warehouse_root)
    catalog = SqlCatalog(
        _CATALOG_NAME,
        **{
            "uri": s.catalog_uri,
            "warehouse": f"file://{s.warehouse_root}",
        },
    )
    return catalog


def ensure_namespaces(extra: Iterable[str] = ()) -> None:
    """Create one Iceberg namespace per data-mesh domain (and any extras)."""
    cat = get_catalog()
    targets = set(DOMAINS) | set(extra)
    for ns in targets:
        try:
            cat.create_namespace(ns)
            log.info("iceberg.namespace.created name=%s", ns)
        except NamespaceAlreadyExistsError:
            log.debug("iceberg.namespace.exists name=%s", ns)


def register_bronze_table(
    domain: str,
    table_name: str,
    parquet_path: Path,
) -> str:
    """Append a Parquet drop into ``<domain>.bronze_<table>``.

    Iceberg is the canonical store: we read the Parquet from the Bronze raw
    drop and append into a managed Iceberg table inside the warehouse.
    """
    cat = get_catalog()
    full = f"{domain}.bronze_{table_name}"
    pa_table = pq.read_table(parquet_path)

    try:
        tbl = cat.load_table(full)
        log.debug("iceberg.table.load name=%s", full)
    except NoSuchTableError:
        tbl = cat.create_table(full, schema=pa_table.schema)
        log.info("iceberg.table.create name=%s rows=%d", full, pa_table.num_rows)

    # Align column order to the table schema for safe append.
    pa_table = pa_table.select(tbl.schema().as_arrow().names)
    tbl.append(pa_table)
    log.info("iceberg.table.append name=%s appended_rows=%d", full, pa_table.num_rows)
    return full


def list_tables() -> list[str]:
    """Enumerate fully-qualified Iceberg tables across known namespaces.

    Only ``NoSuchNamespaceError`` is treated as "expected" — that branch
    fires before the first ingest into a domain. Any other exception
    (programming error, broken catalog file, missing dependency) is
    re-raised so it surfaces in tests and CI instead of silently producing
    a partial list. (REVIEW_FEEDBACK.md Issue 11.)
    """
    cat = get_catalog()
    out: list[str] = []
    for ns in DOMAINS + ("gold",):
        try:
            for ident in cat.list_tables(ns):
                # `list_tables` returns tuples like ('teleop', 'bronze_vr_trajectories')
                out.append(".".join(ident))
        except NoSuchNamespaceError:
            continue
    return sorted(out)


def read_table_arrow(full_name: str) -> pa.Table:
    """Materialize an Iceberg table to an Arrow table (used by downstream xforms)."""
    cat = get_catalog()
    tbl = cat.load_table(full_name)
    return tbl.scan().to_arrow()


def write_managed_table(
    namespace: str,
    table_name: str,
    arrow_table: pa.Table,
    overwrite: bool = True,
) -> str:
    """Create or overwrite an Iceberg table from an Arrow table.

    Concurrency note (TOCTOU): two parallel Dagster workers can both observe
    ``NoSuchTableError`` on the first write to a fresh namespace and both
    call ``create_table``. Without the inner ``TableAlreadyExistsError``
    guard the loser of that race would crash the asset materialization with
    a confusing error. Catching it lets the loser fall through to a
    ``load_table`` + ``append`` that semantically matches what the winner
    already wrote. (REVIEW_FEEDBACK.md Issue 9 / Bug 3.)
    """
    cat = get_catalog()
    ensure_namespaces(extra=[namespace])
    full = f"{namespace}.{table_name}"

    # Materialize the row count up front for logging (works for ``pa.Table``
    # but not for ``pa.RecordBatchReader``, which is a streaming object). If
    # ``arrow_table`` lacks ``num_rows`` (e.g. it is a streaming reader
    # produced by ``duckdb.connect().execute(...).arrow()`` in DuckDB 1.x),
    # we fall through to the underlying append/overwrite call which will
    # raise the clearer pyiceberg ``ValueError`` about expected types.
    n_rows = getattr(arrow_table, "num_rows", -1)

    try:
        tbl = cat.load_table(full)
    except NoSuchTableError:
        try:
            tbl = cat.create_table(full, schema=arrow_table.schema)
        except TableAlreadyExistsError:
            # Lost the create race — another worker just won. Reload and
            # fall through to ``append`` so we add this batch on top of
            # whatever the winning worker already wrote.
            log.info("iceberg.table.create.race.lost name=%s reloading", full)
            tbl = cat.load_table(full)
        else:
            log.info("iceberg.table.create name=%s rows=%d", full, n_rows)
        tbl.append(arrow_table)
        log.info("iceberg.table.append name=%s appended_rows=%d", full, n_rows)
        return full

    if overwrite:
        tbl.overwrite(arrow_table)
        log.info("iceberg.table.overwrite name=%s rows=%d", full, n_rows)
    else:
        tbl.append(arrow_table)
        log.info("iceberg.table.append name=%s rows=%d", full, n_rows)
    return full
