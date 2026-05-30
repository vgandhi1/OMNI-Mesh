"""Phase 4: Semantic discovery / RAG troubleshooting assistant."""

from .chunker import build_failure_chunks, FailureChunk
from .vector_store import FactoryFailureIndex
from .agent import RagAssistant

__all__ = [
    "build_failure_chunks",
    "FailureChunk",
    "FactoryFailureIndex",
    "RagAssistant",
]
