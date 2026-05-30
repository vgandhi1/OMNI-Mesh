"""In-place Iceberg schema evolution.

The spec calls out the specific case where a new firmware revision exposes an
extra register column (e.g. ``skin_conductance_us``). Tearing the table down
and rewriting it would destroy history; instead we mutate the Iceberg
metadata through ``update_schema()`` so the lakehouse picks up the new field
without invalidating any prior snapshots.
"""

from __future__ import annotations

import logging
from typing import Iterable

import pyarrow as pa
from pyiceberg.catalog import Catalog
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.types import (
    BooleanType,
    DoubleType,
    FloatType,
    IcebergType,
    IntegerType,
    LongType,
    StringType,
    TimestampType,
)

logger = logging.getLogger(__name__)


def _arrow_to_iceberg_type(field: pa.Field) -> IcebergType:
    t = field.type
    if pa.types.is_string(t) or pa.types.is_large_string(t):
        return StringType()
    if pa.types.is_boolean(t):
        return BooleanType()
    if pa.types.is_integer(t):
        # Iceberg only supports 32/64-bit signed ints; default to 64 to be safe.
        return LongType() if t.bit_width > 32 else IntegerType()
    if pa.types.is_floating(t):
        return DoubleType() if t.bit_width >= 64 else FloatType()
    if pa.types.is_timestamp(t):
        return TimestampType()
    raise TypeError(f"Unsupported Arrow type for Iceberg evolution: {t}")


def evolve_industrial_schema(
    catalog: Catalog,
    table_name: str,
    new_arrow_schema: pa.Schema,
) -> list[str]:
    """Add any net-new columns from ``new_arrow_schema`` to ``table_name``.

    Returns the list of column names that were added (empty if the schema was
    already a superset).
    """
    try:
        tbl = catalog.load_table(table_name)
    except NoSuchTableError:
        logger.debug("Schema evolve skipped: table %s does not exist yet", table_name)
        return []

    existing = set(tbl.schema().as_arrow().names)
    new_fields: list[pa.Field] = [f for f in new_arrow_schema if f.name not in existing]
    if not new_fields:
        return []

    added: list[str] = []
    with tbl.update_schema() as update:
        for field in new_fields:
            iceberg_type = _arrow_to_iceberg_type(field)
            update.add_column(field.name, iceberg_type)
            added.append(field.name)

    logger.info("Evolved schema for %s: added columns %s", table_name, added)
    return added


def current_columns(catalog: Catalog, table_name: str) -> Iterable[str]:
    try:
        tbl = catalog.load_table(table_name)
    except NoSuchTableError:
        return []
    return tbl.schema().as_arrow().names
