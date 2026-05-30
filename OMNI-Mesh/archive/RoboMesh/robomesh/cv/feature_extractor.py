"""Frozen vision-backbone feature extraction.

Production:    distributed PyTorch job inside Spark / Ray running a frozen
               ViT-B/16 or ResNet-50 on real MP4 frames decoded by ``torchvision``.
Local demo:    same code path, ResNet18 weights, synthetic frames generated
               deterministically from ``(episode_id, camera_id, frame_index)``.

If PyTorch is not installed, we fall back to a NumPy hash-based pseudo-encoder
so the rest of the pipeline (Gold tier, WebDataset writer, RAG) still runs.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

import numpy as np

from robomesh.config import get_settings
from robomesh.cv.tensor_store import get_tensor_store
from robomesh.logging_setup import get_logger

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Optional PyTorch import — we never let an ImportError crash the rest of the
# pipeline. ``HAS_TORCH`` lets downstream modules decide whether to invoke
# real-tensor code paths or the deterministic NumPy fallback.
# --------------------------------------------------------------------------- #
try:
    import torch
    from torchvision import models, transforms
    HAS_TORCH = True
except Exception:  # noqa: BLE001
    torch = None  # type: ignore[assignment]
    HAS_TORCH = False


_EMBED_DIM_TORCH = 512   # ResNet18 penultimate layer
_EMBED_DIM_FALLBACK = 128


@dataclass(frozen=True)
class FrameEmbedding:
    """One row per (episode, camera, frame) — the canonical Silver+ payload."""

    episode_id: str
    camera_id: str
    frame_index: int
    ts_us: int
    embedding_uri: str
    embedding_dim: int
    backbone: str


def get_backbone_name() -> str:
    return "torchvision/resnet18" if HAS_TORCH else "numpy/sha256-prng"


@lru_cache(maxsize=1)
def _torch_backbone():  # type: ignore[no-untyped-def]
    """Load ResNet18 → penultimate features. Frozen, eval mode, CPU."""
    if not HAS_TORCH:
        raise RuntimeError("torch not available")
    log.info("cv.backbone.load name=resnet18 frozen=True")
    weights = models.ResNet18_Weights.DEFAULT
    net = models.resnet18(weights=weights)
    # Replace final classifier with identity so we get 512-d features.
    net.fc = torch.nn.Identity()
    net.eval()
    for p in net.parameters():
        p.requires_grad = False
    return net, transforms.Compose([
        transforms.ToTensor(),
        transforms.Resize((224, 224), antialias=True),
        transforms.Normalize(mean=weights.transforms().mean,
                             std=weights.transforms().std),
    ])


# --------------------------------------------------------------------------- #
# Synthetic frame generation — deterministic per (episode, camera, frame).
# A real deployment would replace this with ``decord`` / ``av`` reading the
# ``video_uri`` from the Silver table.
# --------------------------------------------------------------------------- #

def _synthetic_frame(episode_id: str, camera_id: str, frame_index: int) -> np.ndarray:
    """Generate a stable 224×224 RGB ``uint8`` frame from a content hash."""
    seed = int.from_bytes(
        hashlib.sha256(
            f"{episode_id}/{camera_id}/{frame_index}".encode("utf-8")
        ).digest()[:4],
        "big",
    )
    rng = np.random.default_rng(seed)
    # Smooth gradients give the backbone something to embed besides pure noise.
    base = rng.integers(0, 255, size=(8, 8, 3), dtype=np.uint8)
    upscaled = np.kron(base, np.ones((28, 28, 1), dtype=np.uint8))  # → 224×224
    return upscaled.astype(np.uint8)


def _embed_torch(frames: np.ndarray) -> np.ndarray:
    """Run the frozen ResNet on a batch of HWC uint8 frames → (N, 512) float32."""
    net, tfm = _torch_backbone()
    tensors = torch.stack([tfm(f) for f in frames])
    with torch.no_grad():
        feats = net(tensors)
    arr = feats.cpu().numpy().astype(np.float32)
    # L2 normalize so cosine similarity downstream is well-defined.
    norms = np.linalg.norm(arr, axis=1, keepdims=True) + 1e-12
    return arr / norms


def _embed_fallback(frames: np.ndarray) -> np.ndarray:
    """Hash-based deterministic encoder — only used when torch is absent.

    The previous slice ``(h * repeat)[: _EMBED_DIM_FALLBACK * 4]`` was
    correct *by accident*: it asked for 512 bytes from a 128-byte tile
    buffer and Python silently returned all 128, which happened to match
    ``_EMBED_DIM_FALLBACK``. Anyone bumping ``_EMBED_DIM_FALLBACK`` would
    have produced silently truncated vectors. We now compute the exact
    number of 32-byte tiles required and slice at the embedding length in
    bytes (= float count, since each slot is one ``uint8``).
    (REVIEW_FEEDBACK.md Issue 8.)
    """
    out = np.zeros((len(frames), _EMBED_DIM_FALLBACK), dtype=np.float32)
    n_tiles = math.ceil(_EMBED_DIM_FALLBACK / hashlib.sha256().digest_size)
    for i, f in enumerate(frames):
        h = hashlib.sha256(f.tobytes()).digest()
        tiled = (h * n_tiles)[:_EMBED_DIM_FALLBACK]  # exactly D bytes
        out[i] = np.frombuffer(tiled, dtype=np.uint8).astype(np.float32) / 255.0
    norms = np.linalg.norm(out, axis=1, keepdims=True) + 1e-12
    return out / norms


def extract_episode_embeddings(
    camera_rows: Iterable[dict],
    *,
    batch_size: int = 32,
) -> list[FrameEmbedding]:
    """Embed every (episode, camera, frame) tuple and persist tensors.

    ``camera_rows`` should yield dicts with at least::

        episode_id, camera_id, frame_index, ts_us, video_uri

    Returns a list of :class:`FrameEmbedding` rows — these are what the Gold
    tier joins back to the Silver table (only URIs land in Iceberg).
    """
    store = get_tensor_store()
    s = get_settings()
    log.info("cv.extract.start torch=%s batch=%d", HAS_TORCH, batch_size)

    out: list[FrameEmbedding] = []
    batch: list[dict] = []
    backbone = get_backbone_name()
    embed_dim = _EMBED_DIM_TORCH if HAS_TORCH else _EMBED_DIM_FALLBACK

    def _flush() -> None:
        if not batch:
            return
        frames = np.stack(
            [_synthetic_frame(r["episode_id"], r["camera_id"], r["frame_index"])
             for r in batch]
        )
        if HAS_TORCH:
            vectors = _embed_torch(frames)
        else:
            vectors = _embed_fallback(frames)
        # Persist each vector and remember its URI in the Gold-bound rows.
        for row, vec in zip(batch, vectors):
            key = f"{row['camera_id']}_{int(row['frame_index']):06d}"
            uri = store.write(row["episode_id"], key, vec.astype(np.float32))
            out.append(
                FrameEmbedding(
                    episode_id=row["episode_id"],
                    camera_id=row["camera_id"],
                    frame_index=int(row["frame_index"]),
                    ts_us=int(row["ts_us"]),
                    embedding_uri=uri,
                    embedding_dim=embed_dim,
                    backbone=backbone,
                )
            )
        batch.clear()

    for row in camera_rows:
        batch.append(row)
        if len(batch) >= batch_size:
            _flush()
    _flush()

    log.info(
        "cv.extract.done n_embeddings=%d backbone=%s dim=%d seed=%d",
        len(out), backbone, embed_dim, s.seed,
    )
    return out
