"""Local sentence-transformer embeddings.

Mirrors the OpenAI ``text-embedding-3-small`` step from the blueprint with a
zero-cost local model that runs on CPU.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Sequence

import numpy as np

from robomesh.config import get_settings
from robomesh.logging_setup import get_logger

log = get_logger(__name__)


@lru_cache(maxsize=1)
def _model():  # type: ignore[no-untyped-def]
    # Imported lazily — sentence-transformers is a heavy dep.
    from sentence_transformers import SentenceTransformer

    s = get_settings()
    log.info("embed.model.load name=%s", s.embedding_model)
    return SentenceTransformer(s.embedding_model)


def embed_texts(texts: Sequence[str]) -> np.ndarray:
    """Return an ``(n, d)`` float32 numpy array of embeddings."""
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    model = _model()
    vectors = model.encode(
        list(texts),
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    log.info("embed.done n=%d dim=%d", vectors.shape[0], vectors.shape[1])
    return vectors.astype(np.float32)
