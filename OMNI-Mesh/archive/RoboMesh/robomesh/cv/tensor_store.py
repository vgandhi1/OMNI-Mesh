"""Pitfall #1 — keep tabular metadata in Iceberg, **never** inline tensors.

The :class:`TensorStore` writes high-dimensional embedding tensors to a flat
``data/tensors/<episode>/<key>.npy`` partition and returns a stable URI that
Iceberg can store as a plain string column. In a production deployment the
same store would target S3 (``s3://robomesh-tensors/<episode>/<key>.npy``);
the URI scheme is preserved end-to-end.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import numpy as np

from robomesh.config import get_settings
from robomesh.logging_setup import get_logger

log = get_logger(__name__)

_TENSOR_SCHEME = "tensors://"


@dataclass(frozen=True)
class TensorStore:
    """File-system / S3-compatible blob store for raw numerical tensors."""

    root: Path

    def write(self, episode_id: str, key: str, array: np.ndarray) -> str:
        """Persist ``array`` to ``<root>/<episode_id>/<key>.npy``; return its URI."""
        episode_id = _sanitize(episode_id)
        key = _sanitize(key)
        episode_dir = (self.root / episode_id).resolve()
        # Path traversal defense — the resolved directory must remain under root.
        root_resolved = self.root.resolve()
        if not str(episode_dir).startswith(str(root_resolved)):
            raise ValueError("tensor_store.path_traversal_blocked")
        episode_dir.mkdir(parents=True, exist_ok=True)
        out = episode_dir / f"{key}.npy"
        np.save(out, array, allow_pickle=False)
        log.debug(
            "tensor_store.write episode=%s key=%s shape=%s dtype=%s",
            episode_id, key, tuple(array.shape), array.dtype,
        )
        return f"{_TENSOR_SCHEME}{episode_id}/{key}.npy"

    def write_batch(
        self, episode_id: str, items: Iterable[tuple[str, np.ndarray]]
    ) -> list[str]:
        return [self.write(episode_id, k, v) for k, v in items]

    def read(self, uri: str) -> np.ndarray:
        path = tensor_uri_to_path(uri, root=self.root)
        return np.load(path, allow_pickle=False)


def _sanitize(name: str) -> str:
    """Allow only ``[A-Za-z0-9._-]``; reject anything that looks like a path.

    The previous implementation silently rewrote invalid characters to ``_``,
    which let path-traversal-looking inputs like ``"../../etc"`` slip
    through as ``"......etc"`` — a benign-looking but anomalous directory
    name that the test correctly flagged as a security gap (workspace
    path_traversal_prevention rule).

    We now refuse the input outright (``ValueError``) rather than mangle it,
    so callers see a clear failure instead of a silently corrupted URI.
    """
    if not name:
        raise ValueError("tensor_store.empty_name")
    # Reject any traversal indicator before sanitization so the caller cannot
    # smuggle ``..`` past the allow-list with creative quoting / encoding.
    if (
        ".." in name
        or "/" in name
        or "\\" in name
        or name in (".", "..")
        or name.startswith(".")
    ):
        raise ValueError("tensor_store.path_traversal_blocked")
    if not all(c.isalnum() or c in (".", "_", "-") for c in name):
        raise ValueError("tensor_store.invalid_characters")
    return name


def tensor_uri_to_path(uri: str, *, root: Path | None = None) -> Path:
    """Resolve ``tensors://<episode>/<key>.npy`` → on-disk Path safely."""
    if not uri.startswith(_TENSOR_SCHEME):
        raise ValueError(f"tensor_store.bad_scheme: {uri[:32]}")
    rel = uri[len(_TENSOR_SCHEME):]
    base = (root or get_tensor_store().root).resolve()
    candidate = (base / rel).resolve()
    if not str(candidate).startswith(str(base)):
        raise ValueError("tensor_store.path_traversal_blocked")
    return candidate


@lru_cache(maxsize=1)
def get_tensor_store() -> TensorStore:
    s = get_settings()
    root = (s.data_root / "tensors").resolve()
    root.mkdir(parents=True, exist_ok=True)
    log.info("tensor_store.init root=%s", root)
    return TensorStore(root=root)
