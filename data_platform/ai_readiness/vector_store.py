"""ChromaDB persistent client with an embedding-model drift guard.

ChromaDB only enforces vector dimensionality, so swapping embedding models with the
same dimension would silently corrupt retrieval. We store the model name in the
collection metadata and refuse to read/write a collection built with a different
model (pattern shared by RoboMesh and heal-mesh).
"""

from __future__ import annotations

import logging

import chromadb
from chromadb.config import Settings as ChromaSettings

from config.settings import get_settings

logger = logging.getLogger("omni_mesh.vector_store")

_CLIENT_CACHE: dict[str, chromadb.api.ClientAPI] = {}


def get_client() -> chromadb.api.ClientAPI:
    settings = get_settings()
    settings.ensure_dirs()
    key = str(settings.chroma_dir.resolve())
    client = _CLIENT_CACHE.get(key)
    if client is None:
        client = chromadb.PersistentClient(
            path=str(settings.chroma_dir),
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
        )
        _CLIENT_CACHE[key] = client
    return client


def reset_client_cache() -> None:
    """Clear the cached Chroma client (test isolation hook)."""
    _CLIENT_CACHE.clear()


def _embedding_function():
    settings = get_settings()
    try:
        from chromadb.utils.embedding_functions import (
            SentenceTransformerEmbeddingFunction,
        )

        return SentenceTransformerEmbeddingFunction(model_name=settings.embedding_model)
    except Exception as exc:  # pragma: no cover - depends on optional model download
        logger.warning("falling back to default chroma embeddings (%s)", type(exc).__name__)
        return None


def _assert_collection_compatible(collection) -> None:
    stored = dict(collection.metadata or {}).get("embedding_model")
    expected = get_settings().embedding_model
    if stored and stored != expected:
        raise RuntimeError(
            f"vector index was built with embedding_model={stored!r}, "
            f"but settings expect {expected!r}; rebuild the index."
        )


def get_collection(name: str):
    client = get_client()
    settings = get_settings()
    kwargs = {
        "name": name,
        "metadata": {"hnsw:space": "cosine", "embedding_model": settings.embedding_model},
    }
    embedding_fn = _embedding_function()
    if embedding_fn is not None:
        kwargs["embedding_function"] = embedding_fn
    collection = client.get_or_create_collection(**kwargs)
    _assert_collection_compatible(collection)
    return collection
