"""Tests for the CV feature-extraction layer.

These tests exercise the fallback (no-PyTorch) path so they run in any
environment. If PyTorch is installed the same tests still pass because the
public surface is identical.
"""
from __future__ import annotations

import numpy as np
import pytest

from robomesh.cv import HAS_TORCH, extract_episode_embeddings, get_backbone_name
from robomesh.cv.tensor_store import get_tensor_store, tensor_uri_to_path


def _camera_rows():
    out: list[dict] = []
    for ep in ("EP_TEST_001", "EP_TEST_002"):
        for cam in ("cam_overhead", "cam_wrist_left"):
            for idx in range(3):
                out.append(
                    {
                        "episode_id": ep,
                        "camera_id": cam,
                        "frame_index": idx,
                        "ts_us": 1_000_000 + idx * 33_333,
                        "video_uri": f"s3://bucket/{ep}/{cam}_{idx:05d}.mp4",
                    }
                )
    return out


def test_backbone_reports_correctly() -> None:
    name = get_backbone_name()
    assert "resnet18" in name or "numpy" in name


def test_extract_writes_one_uri_per_frame() -> None:
    rows = _camera_rows()
    out = extract_episode_embeddings(rows, batch_size=4)
    assert len(out) == len(rows)
    for emb in out:
        assert emb.embedding_uri.startswith("tensors://")
        # The tensor file must exist and be loadable.
        path = tensor_uri_to_path(emb.embedding_uri)
        assert path.exists()
        vec = np.load(path)
        assert vec.shape == (emb.embedding_dim,)
        # L2 normalized.
        assert abs(float(np.linalg.norm(vec)) - 1.0) < 1e-3


def test_tensor_store_rejects_path_traversal(tmp_path) -> None:
    store = get_tensor_store()
    with pytest.raises(ValueError):
        store.write("../../etc", "passwd", np.zeros(4, dtype=np.float32))


def test_uri_resolution_rejects_traversal() -> None:
    with pytest.raises(ValueError):
        tensor_uri_to_path("tensors://../../etc/passwd")


def test_embeddings_are_deterministic() -> None:
    rows = _camera_rows()[:2]
    a = extract_episode_embeddings(rows, batch_size=4)
    b = extract_episode_embeddings(rows, batch_size=4)
    for ea, eb in zip(a, b):
        va = np.load(tensor_uri_to_path(ea.embedding_uri))
        vb = np.load(tensor_uri_to_path(eb.embedding_uri))
        # Without PyTorch the encoder is fully deterministic; with PyTorch
        # eval-mode + no dropout is also deterministic on CPU.
        assert np.allclose(va, vb, atol=1e-5)


@pytest.mark.skipif(not HAS_TORCH, reason="torch not installed")
def test_resnet18_returns_512_dim() -> None:
    rows = _camera_rows()[:1]
    out = extract_episode_embeddings(rows, batch_size=1)
    assert out[0].embedding_dim == 512
