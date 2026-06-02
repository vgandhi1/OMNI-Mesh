"""CV feature extraction: torchvision ResNet18 if available, else a deterministic
numpy/SHA-256 fallback. Materializes ``gold.vla_episodes`` (feature vectors) in the
Iceberg lakehouse — the input tier for VLA model training.
"""

from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass

import numpy as np
import pyarrow as pa

from config.profiles import MeshProfile, active_spec
from data_platform import catalog

logger = logging.getLogger("omni_mesh.vla")

try:  # optional ML stack (requirements-ml.txt)
    import torch
    from torchvision import models

    HAS_TORCH = True
except Exception:  # pragma: no cover - exercised when torchvision is absent
    torch = None
    models = None
    HAS_TORCH = False

_EMBED_DIM_FALLBACK = 128
_backbone = None


def get_backbone_name() -> str:
    return "torchvision/resnet18" if HAS_TORCH else "numpy/sha256-prng"


@dataclass(frozen=True)
class FrameEmbedding:
    episode_id: str
    robot_model_id: str
    failure_type_tag: str
    success_flag: bool
    embedding: list[float]


def _synth_frame(seed: bytes, size: int = 64) -> np.ndarray:
    """Deterministic pseudo-frame stand-in (no real camera bytes in the demo)."""
    digest = hashlib.sha256(seed).digest()
    rng = np.random.default_rng(int.from_bytes(digest[:8], "little"))
    return rng.random((size, size, 3), dtype=np.float32)


def _torch_backbone():
    global _backbone
    if _backbone is None:
        net = models.resnet18(weights=None)
        net.fc = torch.nn.Identity()
        net.eval()
        _backbone = net
    return _backbone


def reset_backbone_cache() -> None:
    global _backbone
    _backbone = None


def _embed_torch(frames: np.ndarray) -> np.ndarray:
    tensor = torch.from_numpy(frames).permute(0, 3, 1, 2)
    tensor = torch.nn.functional.interpolate(
        tensor, size=(224, 224), mode="bilinear", align_corners=False
    )
    with torch.no_grad():
        out = _torch_backbone()(tensor).cpu().numpy()
    norms = np.linalg.norm(out, axis=1, keepdims=True) + 1e-8
    return (out / norms).astype(np.float32)


def _embed_fallback(frames: np.ndarray) -> np.ndarray:
    out = np.zeros((len(frames), _EMBED_DIM_FALLBACK), dtype=np.float32)
    tiles = math.ceil(_EMBED_DIM_FALLBACK / hashlib.sha256().digest_size)
    for i, frame in enumerate(frames):
        digest = hashlib.sha256(frame.tobytes()).digest()
        tiled = (digest * tiles)[:_EMBED_DIM_FALLBACK]
        vector = np.frombuffer(tiled, dtype=np.uint8).astype(np.float32) / 255.0
        out[i] = vector / (np.linalg.norm(vector) + 1e-8)
    return out


def embed_frames(frames: np.ndarray) -> np.ndarray:
    return _embed_torch(frames) if HAS_TORCH else _embed_fallback(frames)


_GOLD_SCHEMA = pa.schema(
    [
        ("episode_id", pa.string()),
        ("robot_model_id", pa.string()),
        ("failure_type_tag", pa.string()),
        ("success_flag", pa.bool_()),
        ("vla_feature_vector", pa.list_(pa.float32())),
        ("feature_dim", pa.int32()),
        ("backbone", pa.string()),
    ]
)


def build_vla_gold(limit: int = 64) -> int:
    """Embed robot frames and write ``gold.vla_episodes`` to the lakehouse."""
    spec = active_spec()
    if spec.profile != MeshProfile.ROBOTICS:
        raise ValueError("The VLA flywheel is only defined for the ROBOTICS profile.")

    source = None
    for namespace, table in (
        (catalog.NAMESPACE_SILVER, "silver_robot_signals"),
        (catalog.NAMESPACE_BRONZE, spec.bronze_table),
    ):
        try:
            source = catalog.read_table_arrow(f"{namespace}.{table}")
            break
        except Exception:
            continue
    if source is None or source.num_rows == 0:
        return 0

    rows = source.slice(0, limit).to_pylist()
    frames = np.stack(
        [
            _synth_frame(
                f"{row.get('camera_frame_uri', '')}|{row.get('joint_positions')}".encode()
            )
            for row in rows
        ]
    )
    embeddings = embed_frames(frames)

    out_rows = [
        {
            "episode_id": f"{row.get('robot_id', 'rid')}-{i:05d}",
            "robot_model_id": row.get("robot_model_id"),
            "failure_type_tag": row.get("failure_type_tag"),
            "success_flag": bool(row.get("success_flag")),
            "vla_feature_vector": embeddings[i].tolist(),
            "feature_dim": int(embeddings.shape[1]),
            "backbone": get_backbone_name(),
        }
        for i, row in enumerate(rows)
    ]
    arrow = pa.Table.from_pylist(out_rows, schema=_GOLD_SCHEMA)
    catalog.write_data_product(catalog.NAMESPACE_GOLD, "vla_episodes", arrow, overwrite=True)
    logger.info("vla gold: %d episodes via %s", arrow.num_rows, get_backbone_name())
    return arrow.num_rows
