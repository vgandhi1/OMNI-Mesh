"""Semantic indexing + Agentic RAG (Phase 4)."""
from robomesh.semantic.summarizer import build_episode_summaries
from robomesh.semantic.embeddings import embed_texts
from robomesh.semantic.vector_store import upsert_episode_vectors, query_episodes
from robomesh.semantic.rag_agent import RoboMeshAgent, AgentAnswer

__all__ = [
    "build_episode_summaries",
    "embed_texts",
    "upsert_episode_vectors",
    "query_episodes",
    "RoboMeshAgent",
    "AgentAnswer",
]
