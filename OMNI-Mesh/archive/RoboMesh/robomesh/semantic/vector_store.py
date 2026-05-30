"""ChromaDB-backed vector store (stand-in for Databricks Vector Search)."""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Sequence

import chromadb
from chromadb.config import Settings as ChromaSettings

from robomesh.config import get_settings
from robomesh.logging_setup import get_logger
from robomesh.semantic.embeddings import embed_texts

log = get_logger(__name__)

_COLLECTION = "robomesh_episodes"


@lru_cache(maxsize=1)
def _client() -> chromadb.api.ClientAPI:
    s = get_settings()
    s.chroma_path.mkdir(parents=True, exist_ok=True)
    log.info("chroma.client.init path=%s", s.chroma_path)
    return chromadb.PersistentClient(
        path=str(s.chroma_path),
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def _probe_embedding_dim() -> int:
    """One-shot probe of the embedding model's output dimensionality."""
    vec = embed_texts(["dimension probe"])
    if vec.size == 0:
        raise RuntimeError("embed_texts returned an empty result during dim probe")
    return int(vec.shape[1])


def _assert_collection_compatible(coll: chromadb.api.models.Collection.Collection) -> None:
    """Refuse to use a collection that was built with a different model.

    ChromaDB enforces a fixed embedding dimensionality per collection, but
    swapping to a same-dimension model would otherwise silently corrupt
    retrieval semantics. We persist ``embedding_model`` + ``embedding_dim``
    on creation and check both on every subsequent open. (REVIEW_FEEDBACK.md
    Cross-Project Issue 1 / Sprint 2.)
    """
    meta = dict(coll.metadata or {})
    stored_model = meta.get("embedding_model")
    expected_model = get_settings().embedding_model
    if stored_model and stored_model != expected_model:
        raise RuntimeError(
            f"vector index was built with embedding_model={stored_model!r} but "
            f"runtime is configured for {expected_model!r}. Delete "
            f"'{coll.name}' or revert the env var."
        )


def _collection() -> chromadb.api.models.Collection.Collection:
    c = _client()
    expected_model = get_settings().embedding_model
    existing = {col.name for col in c.list_collections()}
    if _COLLECTION in existing:
        coll = c.get_collection(name=_COLLECTION)
        _assert_collection_compatible(coll)
        return coll
    # First creation — embed once to discover the dimensionality, then store
    # both the model name and dim as collection metadata for future drift
    # detection.
    expected_dim = _probe_embedding_dim()
    coll = c.create_collection(
        name=_COLLECTION,
        metadata={
            "hnsw:space": "cosine",
            "embedding_model": expected_model,
            "embedding_dim": expected_dim,
        },
    )
    log.info(
        "chroma.collection.created name=%s dim=%d model=%s",
        _COLLECTION, expected_dim, expected_model,
    )
    return coll


def upsert_episode_vectors(summaries: list[dict]) -> int:
    """Embed and upsert summaries; return the number of vectors written."""
    if not summaries:
        return 0
    texts = [s["text"] for s in summaries]
    ids = [s["episode_id"] for s in summaries]
    metas: list[dict[str, Any]] = []
    for s in summaries:
        # Chroma accepts only primitive scalar metadata values.
        metas.append(
            {
                "robot_model_id": str(s.get("robot_model_id") or ""),
                "failure_type_tag": str(s.get("failure_type_tag") or ""),
                "success_flag": bool(s.get("success_flag")),
                "gripper_type": str(s.get("gripper_type") or ""),
                "policy_family": str(s.get("policy_family") or ""),
            }
        )
    embeddings = embed_texts(texts)
    coll = _collection()
    coll.upsert(
        ids=ids,
        embeddings=embeddings.tolist(),
        documents=texts,
        metadatas=metas,
    )
    log.info("chroma.upsert n=%d", len(ids))
    return len(ids)


def query_episodes(
    query_text: str,
    *,
    k: int = 5,
    where: dict[str, Any] | None = None,
) -> list[dict]:
    """Run a semantic similarity query over the episode index."""
    if not query_text or not query_text.strip():
        return []
    q_emb = embed_texts([query_text])[0].tolist()
    coll = _collection()
    res = coll.query(
        query_embeddings=[q_emb],
        n_results=max(1, min(k, 50)),
        where=where or None,
    )
    out: list[dict] = []
    ids = (res.get("ids") or [[]])[0]
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    distances = (res.get("distances") or [[]])[0]
    for i, ep_id in enumerate(ids):
        out.append(
            {
                "episode_id": ep_id,
                "text": docs[i] if i < len(docs) else "",
                "metadata": metas[i] if i < len(metas) else {},
                "similarity": 1.0 - float(distances[i]) if i < len(distances) else None,
            }
        )
    log.info("chroma.query k=%d hits=%d", k, len(out))
    return out


def index_size() -> int:
    try:
        return int(_collection().count())
    except Exception:  # noqa: BLE001
        return 0


# Helper for splitter-style API parity with the blueprint (LangChain text splitter).
def chunk_long_text(text: str, chunk_size: int = 512, overlap: int = 64) -> Sequence[str]:
    """Lightweight text splitter that mirrors LangChain's RecursiveCharacterSplitter."""
    if len(text) <= chunk_size:
        return [text]
    out: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        out.append(text[start:end])
        if end == len(text):
            break
        start = max(0, end - overlap)
    return out
