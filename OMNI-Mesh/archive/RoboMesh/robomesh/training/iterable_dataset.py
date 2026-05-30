"""PyTorch ``IterableDataset`` that streams Arrow batches from Iceberg.

This is the canonical training-time entry point: a DDP/FSDP worker creates
this dataset, points it at the local Iceberg warehouse, and gets a stream of
``(features, label, metadata)`` tuples without ever materializing the full
table on disk.

If ``torch`` is not installed we fall back to a plain Python iterator so the
upstream phases of the demo still work.
"""
from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from typing import Iterator

import numpy as np
import pyarrow as pa  # noqa: F401  (re-exported via type annotations downstream)

from robomesh.catalog.iceberg import read_table_arrow
from robomesh.config import get_settings
from robomesh.cv.feature_extractor import HAS_TORCH
from robomesh.logging_setup import get_logger

log = get_logger(__name__)


def iter_arrow_batches(
    table_name: str = "gold.vla_episodes_v2",
    *,
    batch_size: int = 32,
) -> Iterator[pa.RecordBatch]:
    """Stream Arrow batches straight from Iceberg — zero-copy when possible."""
    table = read_table_arrow(table_name)
    for batch in table.to_batches(max_chunksize=batch_size):
        yield batch


def _iter_shard_samples(shard_path: Path) -> Iterator[dict]:
    """Lazy WebDataset-style iteration over a single ``.tar`` shard."""
    with tarfile.open(shard_path, mode="r") as tar:
        # Group members by stem to reconstruct samples.
        buckets: dict[str, dict[str, bytes]] = {}
        for member in tar:
            if not member.isfile():
                continue
            f = tar.extractfile(member)
            if f is None:
                continue
            # ``key.vla_features.npy`` -> key="key", suffix="vla_features.npy"
            stem, _, suffix = member.name.partition(".")
            buckets.setdefault(stem, {})[suffix] = f.read()
        for key, files in buckets.items():
            yield {
                "__key__": key,
                "features": np.load(
                    io.BytesIO(files["vla_features.npy"]),
                    allow_pickle=False,
                ),
                "metadata": json.loads(files["vla_metadata.json"].decode("utf-8")),
            }


# --------------------------------------------------------------------------- #
# Optional PyTorch IterableDataset — degrades gracefully when torch missing.
# --------------------------------------------------------------------------- #
if HAS_TORCH:
    import torch
    from torch.utils.data import IterableDataset

    class RoboMeshTorchDataset(IterableDataset):
        """Streaming dataset over RoboMesh WebDataset shards.

        Sharding is split between DDP workers automatically via
        :func:`torch.utils.data.get_worker_info`. Each worker reads a disjoint
        subset of shards so global throughput scales linearly.
        """

        def __init__(
            self,
            shards_dir: Path | None = None,
            *,
            shuffle_shards: bool = True,
        ) -> None:
            super().__init__()
            self.shards_dir = Path(shards_dir) if shards_dir else (
                get_settings().artifacts_root / "training_shards"
            )
            self.shuffle_shards = shuffle_shards

        def _list_shards(self) -> list[Path]:
            return sorted(self.shards_dir.glob("robomesh-vla-*.tar"))

        def __iter__(self) -> Iterator[dict]:
            shards = self._list_shards()
            if not shards:
                return iter([])

            worker_info = torch.utils.data.get_worker_info()
            if worker_info is not None:
                # Each worker takes a striped slice — no overlap, no gaps.
                shards = shards[worker_info.id :: worker_info.num_workers]

            if self.shuffle_shards:
                import random
                random.shuffle(shards)

            log.info("torch.dataset.iter n_shards=%d", len(shards))
            for shard in shards:
                yield from _iter_shard_samples(shard)
else:
    class RoboMeshTorchDataset:  # type: ignore[no-redef]
        """Stub used when PyTorch is not installed.

        The class exists so callers can import it unconditionally; instantiating
        it raises a clear, actionable error.
        """

        def __init__(self, *args, **kwargs) -> None:
            raise RuntimeError(
                "robomesh.training.RoboMeshTorchDataset requires PyTorch. "
                "Install with: pip install -r requirements-ml.txt"
            )

        def __iter__(self):  # pragma: no cover
            return iter([])
