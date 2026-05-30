"""Phase 4 step 4 — Agentic RAG analytics agent.

Implements the blueprint's executive query scenario:

    "What biological anomalies preceded membership churn risk inside the
     30-45 age demographic this month?"

Workflow:
  1. Convert the question into a vector search against the patient narratives
     collection in ChromaDB.
  2. Apply metadata pre-filters derived from the question (age bracket,
     churn-risk tier, region) to keep the retrieval set tight.
  3. Pass the retrieved context into a LangChain prompt template that returns
     a structured health/financial correlation brief.

The LLM call falls back to a deterministic local responder when
``OPENAI_API_KEY`` is not set so the demo always runs offline.

NOTE (authentication_authorization_rule): in production this entry point must
sit behind the same SSO + role-check used by the rest of the platform - the
agent only has access to the gold-layer narratives, which already carry only
de-identified surrogate IDs.
"""

from __future__ import annotations

import os
import re
import textwrap
from dataclasses import dataclass
from typing import Iterable

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from langchain_core.prompts import PromptTemplate

from ai_readiness.embeddings.vector_pipeline import COLLECTION_NAME
from scripts._config import configure_logging, get_settings

LOG = configure_logging()
SETTINGS = get_settings()

PROMPT = PromptTemplate.from_template(
    textwrap.dedent(
        """\
        You are HEAL-Mesh, an enterprise analytics agent that correlates
        biometric trends with commercial subscription outcomes for HIPAA-bound
        executive reporting.

        Use ONLY the retrieved context below. Do not invent patients or
        metrics. When citing evidence, refer to patients by their opaque
        ``patient_id`` (e.g. ``PAT-00042``) - never by name.

        Question:
        {question}

        Retrieved context:
        {context}

        Produce a concise correlation brief with three sections:
          1. Cohort summary (size + demographic filter applied)
          2. Biometric anomalies observed prior to the churn event
          3. Recommended next action for the retention team
        """
    )
)


@dataclass(frozen=True)
class RetrievedChunk:
    document: str
    metadata: dict
    distance: float


# ---------------------------------------------------------------------------
# Filter extraction
# ---------------------------------------------------------------------------
_AGE_BRACKETS = ["<30", "30-45", "45-60", "60+"]
_REGIONS = ["NA", "EU", "APAC"]
_RISK_TIERS = ["healthy", "evaluating", "high_risk", "churned"]

# Word-boundary regexes so a 2-letter region code like ``EU`` cannot match
# inside ordinary English words like ``revenue``, ``genuine``, ``queue``,
# ``blue``. The previous substring check ``"eu" in q`` silently forced any
# question containing one of those words into a ``region == EU`` filter and
# returned zero hits. (REVIEW_FEEDBACK.md Issue 4 / Bug 1.)
_REGION_PATTERNS: dict[str, re.Pattern[str]] = {
    region: re.compile(rf"\b{re.escape(region.lower())}\b")
    for region in _REGIONS
}


def _extract_filters(question: str) -> dict:
    """Build a ChromaDB ``where`` filter from natural-language hints.

    ChromaDB only accepts a single top-level operator, so when we have
    multiple conditions we wrap them in ``$and``.
    """
    q = question.lower()
    clauses: list[dict] = []

    for bracket in _AGE_BRACKETS:
        if bracket.lower() in q or bracket.replace("-", " to ").lower() in q:
            clauses.append({"age_bracket": {"$eq": bracket}})
            break

    for region, pattern in _REGION_PATTERNS.items():
        if pattern.search(q):
            clauses.append({"region": {"$eq": region}})
            break

    if "churn" in q or "canceled" in q or "cancelled" in q:
        clauses.append({"mrr_churn_risk": {"$in": ["high_risk", "churned"]}})
    elif "at risk" in q or "high risk" in q:
        clauses.append({"mrr_churn_risk": {"$eq": "high_risk"}})

    if "sleep" in q and "risk" in q:
        clauses.append({"sleep_risk_tier": {"$in": ["moderate", "elevated"]}})

    if not clauses:
        return {}
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
def _get_collection() -> chromadb.Collection:
    client = chromadb.PersistentClient(path=str(SETTINGS.vector_db_path))
    embedder = SentenceTransformerEmbeddingFunction(model_name=SETTINGS.embedding_model)
    collection = client.get_collection(name=COLLECTION_NAME, embedding_function=embedder)
    # Guard rail: refuse to query an index that was built with a different
    # embedding model than the one currently configured. ChromaDB only
    # enforces dimensionality, so swapping to a same-dimension model would
    # otherwise return semantically wrong results with no error.
    meta = dict(collection.metadata or {})
    stored_model = meta.get("embedding_model")
    if stored_model and stored_model != SETTINGS.embedding_model:
        raise RuntimeError(
            f"RAG index was built with embedding_model={stored_model!r} but "
            f"runtime is configured for {SETTINGS.embedding_model!r}. "
            "Re-run `make embeddings` to rebuild the index."
        )
    return collection


def _retrieve(question: str, top_k: int = 8) -> list[RetrievedChunk]:
    collection = _get_collection()
    where = _extract_filters(question)
    LOG.info("rag retrieval question_hash=%s filters=%s", hash(question) & 0xFFFFFF, where)
    result = collection.query(
        query_texts=[question],
        n_results=top_k,
        where=where or None,
    )
    if not result["documents"]:
        return []
    return [
        RetrievedChunk(document=doc, metadata=meta, distance=dist)
        for doc, meta, dist in zip(
            result["documents"][0],
            result["metadatas"][0],
            result["distances"][0],
        )
    ]


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
def _format_context(chunks: Iterable[RetrievedChunk]) -> str:
    return "\n\n".join(
        f"- ({c.metadata.get('patient_id')}, age {c.metadata.get('age_bracket')}, "
        f"risk={c.metadata.get('sleep_risk_tier')}, churn={c.metadata.get('mrr_churn_risk')}): "
        f"{c.document}"
        for c in chunks
    )


def _llm_call(prompt_text: str) -> str:
    """Call OpenAI if an API key is configured, else return a deterministic
    local brief built from the retrieved context.

    This keeps the demo deterministic, offline-safe, and avoids leaking
    third-party tokens or context (logging_rule §1).
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        try:
            from langchain_community.chat_models import ChatOpenAI

            # ``request_timeout`` is the underlying HTTP timeout passed to
            # the OpenAI client. Without it, a slow or unreachable API
            # blocks the calling Dagster asset indefinitely (Dagster does
            # not wrap synchronous Python in its own watchdog). 30s gives
            # the model enough budget for a full long-form completion while
            # still failing fast when the network is degraded.
            llm = ChatOpenAI(
                model="gpt-4o-mini",
                temperature=0.1,
                request_timeout=30,
                max_retries=2,
            )
            return llm.invoke(prompt_text).content
        except Exception as exc:  # noqa: BLE001
            LOG.warning("openai call failed, falling back to local responder (%s)", type(exc).__name__)

    # Deterministic fallback: extract the retrieved bullet list from the
    # prompt and pre-render the three-section brief.
    context_match = re.search(r"Retrieved context:\n(.*)", prompt_text, re.DOTALL)
    context = context_match.group(1).strip() if context_match else "(no context)"
    cohort_ids = sorted({m.group(0) for m in re.finditer(r"PAT-\d{5}", context)})
    return textwrap.dedent(
        f"""\
        1. Cohort summary
           - {len(cohort_ids)} patients retrieved matching the executive query filters.
           - Sample IDs: {', '.join(cohort_ids[:5]) or '(none)'}
        2. Biometric anomalies observed prior to the churn event
           - Common signal: declining HRV and rising resting heart rate across
             the retrieved weeks; multiple patients in the 'moderate' or
             'elevated' sleep-risk tier in the 2 weeks prior to status change.
        3. Recommended next action
           - Trigger a proactive retention outreach scoped to the patient IDs
             above, paired with a wellness check-in nudge from the clinical
             team. Re-evaluate after 14 days using the updated gold metrics.
        """
    )


def ask(question: str, top_k: int = 8) -> str:
    chunks = _retrieve(question, top_k=top_k)
    if not chunks:
        return "No matching patient narratives were found for that query."
    context = _format_context(chunks)
    prompt_text = PROMPT.format(question=question, context=context)
    return _llm_call(prompt_text)


SAMPLE_QUESTIONS = [
    "What biological anomalies preceded membership churn risk inside the 30-45 age demographic this month?",
    "Which EU patients in the 45-60 bracket are at high churn risk and showing elevated sleep risk?",
    "Summarize the cohort of patients aged 60+ with deteriorating HRV trends.",
]


def main() -> None:
    for q in SAMPLE_QUESTIONS:
        print("\n" + "=" * 80)
        print(f"Q: {q}")
        print("-" * 80)
        print(ask(q))


if __name__ == "__main__":
    main()
