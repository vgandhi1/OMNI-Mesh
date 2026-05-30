"""Phase 3 — Dynamic, role-based, cell-level masking.

Proprietary factory blueprint cells (``factory_blueprint_cell``) are tokenized
with HMAC-SHA-256 + an enterprise salt. Only the ``SECURITY_OPERATIONS`` role
sees unmasked values.

This module is intentionally side-effect free at import time; call
``apply_dynamic_masking`` to materialize a masked Iceberg view.
"""
from __future__ import annotations

import hashlib
import hmac

import pyarrow as pa

from robomesh.catalog.iceberg import read_table_arrow, write_managed_table
from robomesh.config import get_settings
from robomesh.logging_setup import get_logger

log = get_logger(__name__)

_UNMASK_ROLE = "SECURITY_OPERATIONS"

# Columns that contain proprietary, IP-sensitive values per domain owners.
_MASKED_COLUMNS: dict[str, tuple[str, ...]] = {
    "telemetry.bronze_network_health": ("factory_blueprint_cell",),
}


def mask_value(plaintext: str | None, role: str | None = None) -> str | None:
    """Return the HMAC-SHA-256 token unless ``role`` is the unmask role.

    Raises ``RuntimeError`` if the configured masking salt is empty or a
    known placeholder — fail closed so a clone-and-run reviewer cannot
    accidentally generate reversible tokens with a public salt.
    """
    if plaintext is None:
        return None
    if role == _UNMASK_ROLE:
        return plaintext
    settings = get_settings()
    settings.assert_masking_salt()
    salt = settings.masking_salt.encode("utf-8")
    digest = hmac.new(salt, plaintext.encode("utf-8"), hashlib.sha256).hexdigest()
    # Tag the token so downstream consumers know it has been masked.
    return f"masked_sha256:{digest[:16]}"


def _mask_column(table: pa.Table, column: str, role: str) -> pa.Table:
    """Replace ``column`` in ``table`` with its masked equivalent."""
    if column not in table.schema.names:
        return table
    masked_values = [mask_value(v, role) for v in table.column(column).to_pylist()]
    return table.set_column(
        table.schema.get_field_index(column),
        column,
        pa.array(masked_values, type=pa.string()),
    )


def apply_dynamic_masking(role: str | None = None) -> list[str]:
    """Build a ``governed.*`` masked mirror of each sensitive table.

    Returns the list of fully-qualified governed tables written.
    """
    settings = get_settings()
    # Fail closed before doing any work. ``mask_value`` re-checks per cell so
    # the call below is defense in depth, but we want a single, early error
    # rather than partial governed tables when the salt is missing.
    settings.assert_masking_salt()
    effective_role = role or settings.active_role
    # Logging rule: never log the masking salt or raw sensitive values.
    log.info("masking.start role=%s n_tables=%d",
             effective_role, len(_MASKED_COLUMNS))

    written: list[str] = []
    for source_name, columns in _MASKED_COLUMNS.items():
        table = read_table_arrow(source_name)
        for col in columns:
            table = _mask_column(table, col, effective_role)
        target_basename = source_name.split(".", 1)[1]  # e.g. "bronze_network_health"
        full = write_managed_table("governed", target_basename, table)
        written.append(full)
        log.info(
            "masking.applied source=%s target=%s columns=%s",
            source_name, full, list(columns),
        )

    return written


def schema_evolution_audit(table_name: str) -> dict[str, object]:
    """Demonstrate Iceberg's safe schema evolution detection.

    Reports column counts/types so a downstream alerting layer can compare
    snapshots and flag breaking changes (used by the Dagster sensor).
    """
    table = read_table_arrow(table_name)
    return {
        "table": table_name,
        "row_count": int(table.num_rows),
        "n_columns": len(table.schema.names),
        "columns": list(table.schema.names),
    }
