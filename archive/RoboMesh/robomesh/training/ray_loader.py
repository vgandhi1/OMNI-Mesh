"""Ray Data loader over the RoboMesh Gold-tier (optional).

Ray Data sits between Iceberg and DDP/FSDP workers, streaming Arrow buffers
into GPU processes. The integration is intentionally thin — Ray Data already
handles parallel reads from Parquet/Iceberg natively, so we only need to
point it at the right location and apply a tensor-loading map step.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from robomesh.catalog.iceberg import read_table_arrow
from robomesh.config import get_settings
from robomesh.logging_setup import get_logger

log = get_logger(__name__)


try:
    import ray  # noqa: F401
    import ray.data  # noqa: F401
    HAS_RAY = True
except Exception:  # noqa: BLE001
    HAS_RAY = False


def build_ray_dataset(
    table_name: str = "gold.vla_episodes_v2",
    *,
    override_shards_dir: Path | None = None,
) -> Any:
    """Return a ``ray.data.Dataset`` over the Gold tier (if Ray installed).

    Falls back to ``None`` so callers can take a plain torch DataLoader path.
    """
    if not HAS_RAY:
        log.info("ray.fallback.no_ray installed=False")
        return None

    import ray.data as rd

    arrow_table = read_table_arrow(table_name)
    ds = rd.from_arrow(arrow_table)
    log.info("ray.dataset.from_arrow rows=%d schema=%s",
             arrow_table.num_rows, len(arrow_table.schema.names))

    shards_dir = (
        override_shards_dir
        or (get_settings().artifacts_root / "training_shards")
    )

    def _load_tensor(row: dict) -> dict:
        from robomesh.cv.tensor_store import get_tensor_store
        store = get_tensor_store()
        uri = row.get("mean_embedding_uri")
        if uri:
            row["features"] = store.read(uri).tolist()
        return row

    # ``map`` runs lazily — no I/O until the consumer iterates.
    return ds.map(_load_tensor)
