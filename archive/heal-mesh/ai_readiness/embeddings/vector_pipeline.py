"""Phase 4 step 2 — embedding pipeline + vector store ingestion.

Reads the JSONL of natural-language paragraphs produced by the semantic
serializer, chunks each one with a recursive character splitter, embeds the
chunks with a sentence-transformers model, and upserts them into a ChromaDB
collection with the metadata filters listed in the blueprint
(``age_bracket``, ``sleep_risk_tier``, ``region``).

The pipeline is wrapped in an OpenTelemetry span so the FinOps / observability
dashboards (Phase 5) capture its latency next to dbt / Spark runtimes.
"""

from __future__ import annotations

import json
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ai_readiness.serialization.semantic_serializer import OUTPUT_PATH as SUMMARIES_PATH
from orchestration.observability.otel import start_span
from scripts._config import configure_logging, get_settings

LOG = configure_logging()
SETTINGS = get_settings()

COLLECTION_NAME = "heal_mesh_patient_narratives"


def _probe_embedding_dim(embedder: SentenceTransformerEmbeddingFunction) -> int:
    """Return the output dimensionality of ``embedder``.

    We embed a single non-empty token rather than reading the model card so
    the probe works for any ``EmbeddingFunction`` implementation (OpenAI,
    Cohere, local sentence-transformers). The cost is negligible — the
    model is loaded lazily on the first ``__call__`` either way.
    """
    sample = embedder(["dimension probe"])
    if not sample or not sample[0]:
        raise RuntimeError("embedding function returned an empty vector during probe")
    return len(sample[0])


def _assert_collection_compatible(
    collection: chromadb.Collection,
    *,
    expected_model: str,
    expected_dim: int,
) -> None:
    """Refuse to read/write a collection that was built with a different model.

    ChromaDB itself only enforces a fixed ``embedding_dim`` per collection,
    which means changing the model to one with the same dimensionality
    silently corrupts retrieval semantics with no error. We store the model
    name + dimension on creation and compare them on every subsequent open.
    (REVIEW_FEEDBACK.md Cross-Project Issue 1 / Sprint 2.)
    """
    meta = dict(collection.metadata or {})
    stored_model = meta.get("embedding_model")
    stored_dim = meta.get("embedding_dim")
    if stored_model and stored_model != expected_model:
        raise RuntimeError(
            f"vector index was built with embedding_model={stored_model!r} but "
            f"the runtime is configured for {expected_model!r}. Delete the "
            f"index ('{collection.name}') or revert the model env var."
        )
    if stored_dim and int(stored_dim) != expected_dim:
        raise RuntimeError(
            f"vector index dimension mismatch: stored={stored_dim} runtime={expected_dim}."
        )


def _load_summaries(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(
            f"Expected {path} - run `python -m ai_readiness.serialization.semantic_serializer` first"
        )
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def build_vector_index(summaries_path: Path | None = None) -> int:
    summaries_path = summaries_path or SUMMARIES_PATH
    summaries = _load_summaries(summaries_path)
    LOG.info("loaded %d semantic summaries from %s", len(summaries), summaries_path)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=400,
        chunk_overlap=40,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    SETTINGS.vector_db_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(SETTINGS.vector_db_path))
    embedder = SentenceTransformerEmbeddingFunction(model_name=SETTINGS.embedding_model)
    embedding_dim = _probe_embedding_dim(embedder)

    # Recreate the collection so each run gives a clean index.
    if COLLECTION_NAME in [c.name for c in client.list_collections()]:
        client.delete_collection(COLLECTION_NAME)
    collection = client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedder,
        # Persist the model name + dimension as collection metadata so a
        # subsequent run with a different ``HEAL_MESH_EMBEDDING_MODEL`` is
        # detected loudly via ``_assert_collection_compatible`` instead of
        # silently corrupting retrieval results. ChromaDB only enforces the
        # dimensionality natively — the model identity check is ours.
        metadata={
            "hnsw:space": "cosine",
            "embedding_model": SETTINGS.embedding_model,
            "embedding_dim": embedding_dim,
        },
    )
    _assert_collection_compatible(
        collection,
        expected_model=SETTINGS.embedding_model,
        expected_dim=embedding_dim,
    )

    documents: list[str] = []
    metadatas: list[dict] = []
    ids: list[str] = []

    with start_span("vector_pipeline.chunk_and_embed") as span:
        span.set_attribute("heal_mesh.summary_count", len(summaries))
        for entry in summaries:
            chunks = splitter.split_text(entry["paragraph"])
            for idx, chunk in enumerate(chunks):
                documents.append(chunk)
                metadatas.append(
                    {
                        "patient_id": entry["patient_id"],
                        "week_start": entry["week_start"],
                        "age_bracket": entry["age_bracket"],
                        "sleep_risk_tier": entry["sleep_risk_tier"],
                        "region": entry["region"],
                        "mrr_churn_risk": entry["mrr_churn_risk"],
                        "study_id": entry["study_id"],
                    }
                )
                ids.append(f"{entry['patient_id']}:{entry['week_start']}:{idx}")

        # Upsert in modest batches to keep the embedder warm.
        batch_size = 256
        for start in range(0, len(documents), batch_size):
            end = start + batch_size
            collection.upsert(
                ids=ids[start:end],
                documents=documents[start:end],
                metadatas=metadatas[start:end],
            )
        span.set_attribute("heal_mesh.chunks", len(documents))

    LOG.info(
        "vector pipeline wrote %d chunks for %d patients into '%s'",
        len(documents),
        len({m["patient_id"] for m in metadatas}),
        COLLECTION_NAME,
    )
    return len(documents)


if __name__ == "__main__":
    build_vector_index()
