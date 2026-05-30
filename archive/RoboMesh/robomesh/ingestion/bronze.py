"""Sweep the ``data/raw`` Bronze drops into the Iceberg catalog."""
from __future__ import annotations

from pathlib import Path

from robomesh.catalog.iceberg import ensure_namespaces, register_bronze_table
from robomesh.config import DOMAINS, get_settings
from robomesh.logging_setup import get_logger

log = get_logger(__name__)


def ingest_all_domains() -> dict[str, list[str]]:
    """Register every ``data/raw/<domain>/*.parquet`` file as a Bronze table.

    Returns a mapping of domain → list of fully-qualified Iceberg table names.
    """
    s = get_settings()
    ensure_namespaces()
    result: dict[str, list[str]] = {d: [] for d in DOMAINS}

    for domain in DOMAINS:
        domain_dir: Path = s.raw_root / domain
        if not domain_dir.exists():
            log.warning("ingest.skip.no_dir domain=%s", domain)
            continue
        # Resolve and stay inside raw_root (path-traversal safe).
        raw_root_resolved = s.raw_root.resolve()
        for pq in sorted(domain_dir.glob("*.parquet")):
            resolved = pq.resolve()
            if not str(resolved).startswith(str(raw_root_resolved)):
                # Defense in depth — should never happen since we glob inside.
                log.error("ingest.reject.path_traversal path=%s", pq.name)
                continue
            full = register_bronze_table(domain, pq.stem, resolved)
            result[domain].append(full)

    total = sum(len(v) for v in result.values())
    log.info("ingest.done total_tables=%d", total)
    return result
