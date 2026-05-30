"""Dagster Definitions entry-point.

Run ``dagster dev -m robomesh.orchestration.definitions`` to open Dagit.
"""
from __future__ import annotations

from dagster import Definitions, define_asset_job

from robomesh.orchestration.assets import (
    bronze_tables,
    contract_report,
    episode_semantic_index,
    finops_audit,
    frame_embeddings,
    gold_vla_episodes,
    gold_vla_episodes_v2,
    governed_masked_tables,
    live_inference_events,
    raw_drops,
    silver_synchronized_trajectories,
    training_shards,
)

all_assets = [
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
]

robomesh_pipeline = define_asset_job(
    name="robomesh_pipeline",
    selection="*",
    description="End-to-end RoboMesh lakehouse: synthesize → Bronze → Silver → "
    "Gold → governance → semantic index → FinOps audit.",
)

defs = Definitions(
    assets=all_assets,
    jobs=[robomesh_pipeline],
)
