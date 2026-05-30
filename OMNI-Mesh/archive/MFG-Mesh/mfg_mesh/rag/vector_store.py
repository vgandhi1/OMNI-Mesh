"""ChromaDB-backed vector store for failure-event chunks.

The collection metadata embeds embedding-model + dimension to make accidental
drift detectable (per spec). The embedding function defaults to a small local
SentenceTransformer model; if that isn't available we fall back to Chroma's
built-in default so the demo still runs offline.
"""

from __future__ import annotations

import logging
from typing import Iterable, List, Sequence

import chromadb
from chromadb.config import Settings

from ..config import MFGMeshConfig, get_config
from .chunker import FailureChunk, dedupe

logger = logging.getLogger(__name__)


_COLLECTION_NAME = "factory_failure_taxonomy"


def _embedding_function(cfg: MFGMeshConfig):
    """Best-effort local embedding function.

    We prefer SentenceTransformer (the spec mentions `all-MiniLM-L6-v2`), but
    we degrade gracefully to Chroma's default if the model isn't downloadable
    in the current sandbox.
    """
    try:
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

        return SentenceTransformerEmbeddingFunction(model_name=cfg.embedding_model)
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.warning("Falling back to default Chroma embeddings (%s)", type(exc).__name__)
        return None


class FactoryFailureIndex:
    """Thin wrapper around a Chroma collection with deterministic upserts."""

    def __init__(self, cfg: MFGMeshConfig | None = None) -> None:
        self.cfg = cfg or get_config()
        self._client = chromadb.PersistentClient(
            path=str(self.cfg.chroma_dir),
            settings=Settings(anonymized_telemetry=False, allow_reset=True),
        )
        self._embedding_fn = _embedding_function(self.cfg)
        self._collection = self._client.get_or_create_collection(
            name=_COLLECTION_NAME,
            metadata={
                # `hnsw:space` is a Chroma collection setting; the rest is for
                # drift tracking as documented in the spec.
                "hnsw:space": "cosine",
                "embedding_model": self.cfg.embedding_model,
                "embedding_dimension": self.cfg.embedding_dim,
            },
            embedding_function=self._embedding_fn,
        )

    def upsert(self, chunks: Iterable[FailureChunk]) -> int:
        chunks = dedupe(chunks)
        if not chunks:
            return 0
        ids = [c.chunk_id for c in chunks]
        docs = [c.text for c in chunks]
        metadatas = [
            {
                "facility_id": c.facility_id,
                "line_id_masked": c.line_id_masked,
                "register_id": c.register_id,
                "plc_timestamp_ms": c.plc_timestamp_ms,
                # ChromaDB metadata must be scalar -- skip Nones.
                **({"voltage": c.voltage} if c.voltage is not None else {}),
                **({"temperature_c": c.temperature_c} if c.temperature_c is not None else {}),
                **({"pressure_bar": c.pressure_bar} if c.pressure_bar is not None else {}),
            }
            for c in chunks
        ]
        self._collection.upsert(ids=ids, documents=docs, metadatas=metadatas)
        logger.info("Upserted %d chunks into %s", len(chunks), _COLLECTION_NAME)
        return len(chunks)

    def query(
        self,
        prompt: str,
        *,
        n_results: int = 5,
        where: dict | None = None,
    ) -> List[dict]:
        if not prompt or not prompt.strip():
            return []
        result = self._collection.query(
            query_texts=[prompt],
            n_results=n_results,
            where=where or None,
        )
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0] if result.get("distances") else [None] * len(ids)
        return [
            {"id": id_, "document": doc, "metadata": meta, "distance": dist}
            for id_, doc, meta, dist in zip(ids, docs, metas, distances)
        ]

    def count(self) -> int:
        return self._collection.count()

    def reset(self) -> None:
        self._client.delete_collection(_COLLECTION_NAME)
        # Recreate so the index is immediately usable again.
        self._collection = self._client.get_or_create_collection(
            name=_COLLECTION_NAME,
            metadata={
                "hnsw:space": "cosine",
                "embedding_model": self.cfg.embedding_model,
                "embedding_dimension": self.cfg.embedding_dim,
            },
            embedding_function=self._embedding_fn,
        )
