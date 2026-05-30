"""Dagster Software-Defined Assets — one asset per layer of the lakehouse.

This file gives a Dagster Definitions object that mirrors the CLI exactly so
the user can either:

* ``make demo``          — run everything via Typer.
* ``make dagster``       — open the Dagit UI and materialize the same assets.
"""
from __future__ import annotations

from typing import Any

from dagster import (
    AssetExecutionContext,
    AssetIn,
    MetadataValue,
    asset,
)

from robomesh.catalog.iceberg import list_tables
from robomesh.config import get_settings
from robomesh.generators import (
    generate_simulation_drops,
    generate_telemetry_drops,
    generate_teleop_drops,
)
from robomesh.governance import apply_dynamic_masking, enforce_all_contracts
from robomesh.ingestion import ingest_all_domains
from robomesh.orchestration.finops import run_finops_audit
from robomesh.semantic import build_episode_summaries, upsert_episode_vectors
from robomesh.transformations import build_gold_layer, build_silver_layer


@asset(
    group_name="phase_0_synthesize",
    description="Synthetic Bronze drops across the 3 mesh domains.",
)
def raw_drops(context: AssetExecutionContext) -> dict[str, Any]:
    s = get_settings()
    teleop = generate_teleop_drops(s.raw_root, s.demo_episodes, s.seed)
    telemetry = generate_telemetry_drops(s.raw_root, s.demo_episodes, s.seed)
    simulation = generate_simulation_drops(s.raw_root, s.demo_episodes, s.seed)
    context.add_output_metadata(
        {
            "teleop_files": MetadataValue.int(len(teleop)),
            "telemetry_files": MetadataValue.int(len(telemetry)),
            "simulation_files": MetadataValue.int(len(simulation)),
            "n_episodes": MetadataValue.int(s.demo_episodes),
        }
    )
    return {"teleop": teleop, "telemetry": telemetry, "simulation": simulation}


@asset(
    group_name="phase_1_iceberg",
    description="Bronze Iceberg tables (one per raw drop, partitioned by domain).",
    ins={"_raw": AssetIn("raw_drops")},
)
def bronze_tables(context: AssetExecutionContext, _raw: dict[str, Any]) -> list[str]:
    result = ingest_all_domains()
    flat = [t for v in result.values() for t in v]
    context.add_output_metadata({"n_tables": MetadataValue.int(len(flat))})
    return flat


@asset(
    group_name="phase_2_medallion",
    description="Silver — multimodal time-synchronized trajectories.",
    deps=[bronze_tables],
)
def silver_synchronized_trajectories(context: AssetExecutionContext) -> str:
    name = build_silver_layer()
    context.add_output_metadata({"iceberg_table": MetadataValue.text(name)})
    return name


@asset(
    group_name="phase_2_medallion",
    description="Gold — VLA-ready per-episode feature store.",
    deps=[silver_synchronized_trajectories],
)
def gold_vla_episodes(context: AssetExecutionContext) -> str:
    name = build_gold_layer()
    context.add_output_metadata({"iceberg_table": MetadataValue.text(name)})
    return name


@asset(
    group_name="phase_3_governance",
    description="Cell-level masked mirrors for proprietary columns.",
    deps=[bronze_tables],
)
def governed_masked_tables(context: AssetExecutionContext) -> list[str]:
    out = apply_dynamic_masking()
    context.add_output_metadata({"n_governed_tables": MetadataValue.int(len(out))})
    return out


@asset(
    group_name="phase_3_governance",
    description="dbt-style data-contract enforcement on Silver + Gold.",
    deps=[silver_synchronized_trajectories, gold_vla_episodes],
)
def contract_report(context: AssetExecutionContext) -> dict[str, list[str]]:
    report = enforce_all_contracts(raise_on_violation=False)
    n_violations = sum(len(v) for v in report.values())
    context.add_output_metadata(
        {
            "n_violations": MetadataValue.int(n_violations),
            "tables_checked": MetadataValue.int(len(report)),
        }
    )
    return report


@asset(
    group_name="phase_4_semantic",
    description="Semantic embeddings + ChromaDB vector index over episodes.",
    deps=[gold_vla_episodes],
)
def episode_semantic_index(context: AssetExecutionContext) -> int:
    summaries = build_episode_summaries()
    n = upsert_episode_vectors(summaries)
    context.add_output_metadata({"n_vectors": MetadataValue.int(n)})
    return n


@asset(
    group_name="phase_2_5_vla",
    description="Frame-level CV embeddings written as .npy URIs in Iceberg.",
    deps=[silver_synchronized_trajectories],
)
def frame_embeddings(context: AssetExecutionContext) -> str:
    from robomesh.cv import HAS_TORCH, get_backbone_name
    from robomesh.transformations import build_frame_embeddings

    name = build_frame_embeddings()
    context.add_output_metadata(
        {
            "iceberg_table": MetadataValue.text(name),
            "torch_available": MetadataValue.bool(HAS_TORCH),
            "backbone": MetadataValue.text(get_backbone_name()),
        }
    )
    return name


@asset(
    group_name="phase_2_5_vla",
    description="Gold v2 — per-episode VLA features (joins Gold + CV stats).",
    deps=[gold_vla_episodes, frame_embeddings],
)
def gold_vla_episodes_v2(context: AssetExecutionContext) -> str:
    from robomesh.transformations import build_gold_vla_v2

    name = build_gold_vla_v2()
    context.add_output_metadata({"iceberg_table": MetadataValue.text(name)})
    return name


@asset(
    group_name="phase_2_5_vla",
    description="Pre-shuffled WebDataset shards for VLA training workers.",
    deps=[gold_vla_episodes_v2],
)
def training_shards(context: AssetExecutionContext) -> list[str]:
    from robomesh.training import write_training_shards

    paths = write_training_shards(samples_per_shard=64)
    context.add_output_metadata(
        {
            "n_shards": MetadataValue.int(len(paths)),
            "total_bytes": MetadataValue.int(
                sum(p.stat().st_size for p in paths)
            ),
        }
    )
    return [str(p) for p in paths]


@asset(
    group_name="phase_6_closed_loop",
    description="Closed loop: live-inference events streamed back into Bronze.",
    deps=[gold_vla_episodes_v2],
)
def live_inference_events(context: AssetExecutionContext) -> dict:
    from robomesh.closed_loop import simulate_live_inference
    from robomesh.closed_loop.inference_logger import closed_loop_summary

    n = simulate_live_inference()
    summary = closed_loop_summary()
    context.add_output_metadata(
        {
            "n_events_written": MetadataValue.int(n),
            "n_events_total": MetadataValue.int(int(summary["n_events"])),
            "n_failures": MetadataValue.int(int(summary["n_failures"])),
            "mean_confidence": MetadataValue.float(float(summary["mean_confidence"])),
        }
    )
    return summary


@asset(
    group_name="phase_5_finops",
    description="FinOps cost-attribution audit across all warehouses.",
    deps=[gold_vla_episodes],
)
def finops_audit(context: AssetExecutionContext) -> list[dict]:
    rows = run_finops_audit()
    materialized_tables = list_tables()
    context.add_output_metadata(
        {
            "n_queries_audited": MetadataValue.int(len(rows)),
            "n_iceberg_tables": MetadataValue.int(len(materialized_tables)),
            "tables": MetadataValue.json(materialized_tables),
        }
    )
    return [row.__dict__ for row in rows]
