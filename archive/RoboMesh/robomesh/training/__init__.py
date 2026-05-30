"""Gold → Training interface (Phase 2.5 — Ray Data + WebDataset)."""
from robomesh.training.webdataset_writer import write_training_shards
from robomesh.training.iterable_dataset import (
    iter_arrow_batches,
    RoboMeshTorchDataset,
)
from robomesh.training.ray_loader import build_ray_dataset, HAS_RAY

__all__ = [
    "write_training_shards",
    "iter_arrow_batches",
    "RoboMeshTorchDataset",
    "build_ray_dataset",
    "HAS_RAY",
]
