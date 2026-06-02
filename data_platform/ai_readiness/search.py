"""Word-boundary RAG engine over the active profile's lakehouse.

Entity extraction uses ``\\b`` word boundaries so domain terms can never match a
substring of an unrelated word (e.g. ``EU`` inside ``revenue``) — adopting the
correct MFG-Mesh / heal-mesh approach and fixing RoboMesh's substring matching.
A DuckDB connection (wrapped in ``try/finally``) joins matched terms back to the
lakehouse, and a deterministic responder answers offline when no LLM is available.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import duckdb

from config.profiles import ProfileSpec, active_spec
from data_platform import catalog
from data_platform.ai_readiness import vector_store

logger = logging.getLogger("omni_mesh.search")


@dataclass
class Answer:
    question: str
    filters: dict[str, str]
    matched_ids: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    answer: str = ""


def extract_filters(query: str) -> dict[str, str]:
    """Extract ``metadata-field -> term`` pairs via word-boundary regex."""
    spec = active_spec()
    filters: dict[str, str] = {}
    for field_name, terms in spec.rag_vocab.items():
        for term in terms:
            if re.search(rf"\b{re.escape(term)}\b", query, re.IGNORECASE):
                filters[field_name] = term
                break
    return filters


def _row_text(spec: ProfileSpec, row: dict) -> str:
    profile = spec.profile.value
    pairs = ", ".join(f"{k}={row.get(k)}" for k in spec.silver_schema.names if k != "timestamp")
    return f"[{profile}] {pairs}"


def build_chunks() -> list[dict]:
    """Read Bronze and build (id, text, metadata) chunks for the active profile."""
    spec = active_spec()
    identifier = f"{catalog.NAMESPACE_BRONZE}.{spec.bronze_table}"
    table = catalog.read_table_arrow(identifier)
    chunks: list[dict] = []
    for i, row in enumerate(table.to_pylist()):
        metadata = {k: row[k] for k in spec.rag_vocab if row.get(k) is not None}
        metadata.setdefault("profile", spec.profile.value)
        chunks.append(
            {"id": f"{spec.profile.value}-{i}", "text": _row_text(spec, row), "metadata": metadata}
        )
    return chunks


def index() -> int:
    """Embed Bronze chunks into the profile's Chroma collection."""
    spec = active_spec()
    chunks = build_chunks()
    if not chunks:
        return 0
    collection = vector_store.get_collection(spec.chroma_collection)
    collection.upsert(
        ids=[c["id"] for c in chunks],
        documents=[c["text"] for c in chunks],
        metadatas=[c["metadata"] for c in chunks],
    )
    return len(chunks)


def _build_where(filters: dict[str, str]) -> dict | None:
    if not filters:
        return None
    clauses = [{key: {"$eq": value}} for key, value in filters.items()]
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def _join_lakehouse(spec: ProfileSpec, filters: dict[str, str]) -> list[dict]:
    """Filter the Bronze table by extracted terms via DuckDB (TOCTOU-clean close)."""
    identifier = f"{catalog.NAMESPACE_BRONZE}.{spec.bronze_table}"
    try:
        arrow = catalog.read_table_arrow(identifier)
    except Exception:
        return []
    connection = duckdb.connect()
    try:
        connection.register("t", arrow)
        sql = "SELECT * FROM t"
        params: list[str] = []
        if filters:
            sql += " WHERE " + " AND ".join(f"{col} = ?" for col in filters)
            params.extend(filters.values())
        sql += " LIMIT 20"
        cursor = connection.execute(sql, params)
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, record)) for record in cursor.fetchall()]
    finally:
        connection.close()


def _fallback_responder(question: str, filters: dict[str, str], documents: list[str]) -> str:
    scope = ", ".join(f"{k}={v}" for k, v in filters.items()) or "no specific filter"
    return (
        f"Profile '{active_spec().profile.value}' brief for: {question!r}\n"
        f"  Applied filter: {scope}\n"
        f"  Retrieved {len(documents)} matching record(s) from the lakehouse."
    )


def ask(question: str, *, k: int = 5) -> Answer:
    """Run a profile-aware RAG query end-to-end."""
    spec = active_spec()
    filters = extract_filters(question)
    collection = vector_store.get_collection(spec.chroma_collection)
    result = collection.query(query_texts=[question], n_results=k, where=_build_where(filters))
    ids = (result.get("ids") or [[]])[0]
    documents = (result.get("documents") or [[]])[0]
    rows = _join_lakehouse(spec, filters)
    return Answer(
        question=question,
        filters=filters,
        matched_ids=ids,
        rows=rows,
        answer=_fallback_responder(question, filters, documents),
    )
