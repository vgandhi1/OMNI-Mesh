"""Dagster Software-Defined Assets + FinOps audit (Phase 5 + 6)."""
from robomesh.orchestration.assets import (
    raw_drops,
    bronze_tables,
    silver_synchronized_trajectories,
    gold_vla_episodes,
    frame_embeddings,
    gold_vla_episodes_v2,
    training_shards,
    governed_masked_tables,
    contract_report,
    episode_semantic_index,
    live_inference_events,
    finops_audit,
)
from robomesh.orchestration.finops import run_finops_audit

__all__ = [
    "raw_drops",
    "bronze_tables",
    "silver_synchronized_trajectories",
    "gold_vla_episodes",
    "frame_embeddings",
    "gold_vla_episodes_v2",
    "training_shards",
    "governed_masked_tables",
    "contract_report",
    "episode_semantic_index",
    "live_inference_events",
    "finops_audit",
    "run_finops_audit",
]
