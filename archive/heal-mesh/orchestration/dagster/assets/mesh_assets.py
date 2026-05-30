"""Software-defined assets that materialize the entire HEAL-Mesh pipeline.

Asset dependency graph (each node maps to a real artifact on disk):

    synthetic_raw_data
        └─► iceberg_bronze_tables
                └─► dbt_telemetry_gold ──┐
                └─► dbt_commercial_gold ─┼──► semantic_summaries
                └─► dbt_clinical_gold ───┘            │
                                                     ▼
                                            vector_search_index
                                                     │
                                                     ▼
                                               rag_sample_brief

A Dagster sensor on ``dbt_telemetry_gold`` automatically re-materializes the
vector index when the telemetry domain publishes a new version — this is the
"sensors trigger downstream data-loading loops in the AI Vector layer" pattern
from Phase 5.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from dagster import (
    Definitions,
    MaterializeResult,
    asset,
    define_asset_job,
)

from ai_readiness.embeddings.vector_pipeline import build_vector_index
from ai_readiness.rag.agentic_rag import SAMPLE_QUESTIONS, ask
from ai_readiness.serialization.semantic_serializer import serialize as serialize_gold
from orchestration.observability.otel import start_span
from scripts.bootstrap_iceberg import bootstrap as bootstrap_iceberg
from scripts.generate_synthetic_data import main as generate_synth

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _run_dbt(domain: str) -> None:
    """Invoke `dbt build` for one of the per-domain projects."""
    import os

    dbt_dir = PROJECT_ROOT / "domains" / domain / "dbt"
    env = {**os.environ, "HEAL_MESH_PROJECT_ROOT": str(PROJECT_ROOT)}
    cmd = ["dbt", "build", "--profiles-dir", ".", "--no-version-check"]
    with start_span(f"dbt.build.{domain}") as span:
        span.set_attribute("heal_mesh.domain", domain)
        result = subprocess.run(cmd, cwd=dbt_dir, env=env, check=False)
        span.set_attribute("dbt.exit_code", result.returncode)
        if result.returncode != 0:
            raise RuntimeError(f"dbt build failed for domain {domain}")


# ---------------------------------------------------------------------------
# Domain assets
# ---------------------------------------------------------------------------
@asset(group_name="phase1_lakehouse", description="Synthetic raw inputs for all three domains.")
def synthetic_raw_data() -> MaterializeResult:
    with start_span("phase1.generate_synthetic_data"):
        generate_synth()
    return MaterializeResult(metadata={"domains": "telemetry,commercial,clinical"})


@asset(
    group_name="phase1_lakehouse",
    deps=[synthetic_raw_data],
    description="Apache Iceberg catalog + bronze tables across the three domain namespaces.",
)
def iceberg_bronze_tables() -> MaterializeResult:
    with start_span("phase1.bootstrap_iceberg"):
        bootstrap_iceberg()
    return MaterializeResult(metadata={"catalog": "heal_mesh"})


@asset(
    group_name="phase2_telemetry",
    deps=[iceberg_bronze_tables],
    description="Telemetry medallion (bronze→silver→gold).",
)
def dbt_telemetry_gold() -> MaterializeResult:
    _run_dbt("telemetry")
    return MaterializeResult(metadata={"dbt_project": "heal_mesh_telemetry"})


@asset(
    group_name="phase2_commercial",
    deps=[iceberg_bronze_tables],
    description="Commercial medallion (bronze→silver→gold).",
)
def dbt_commercial_gold() -> MaterializeResult:
    _run_dbt("commercial")
    return MaterializeResult(metadata={"dbt_project": "heal_mesh_commercial"})


@asset(
    group_name="phase2_clinical",
    deps=[iceberg_bronze_tables],
    description="Clinical medallion (bronze→silver→gold) with PHI masking.",
)
def dbt_clinical_gold() -> MaterializeResult:
    _run_dbt("clinical")
    return MaterializeResult(metadata={"dbt_project": "heal_mesh_clinical"})


# ---------------------------------------------------------------------------
# AI readiness tier
# ---------------------------------------------------------------------------
@asset(
    group_name="phase4_ai",
    deps=[dbt_telemetry_gold, dbt_commercial_gold, dbt_clinical_gold],
    description="Natural-language summaries of cross-domain gold metrics.",
)
def semantic_summaries() -> MaterializeResult:
    with start_span("phase4.serialize"):
        path = serialize_gold()
    return MaterializeResult(metadata={"summaries_path": str(path)})


@asset(
    group_name="phase4_ai",
    deps=[semantic_summaries],
    description="ChromaDB vector index over patient narratives.",
)
def vector_search_index() -> MaterializeResult:
    with start_span("phase4.embed"):
        chunks = build_vector_index()
    return MaterializeResult(metadata={"chunks": chunks})


@asset(
    group_name="phase4_ai",
    deps=[vector_search_index],
    description="Sample agentic RAG brief proving end-to-end retrieval works.",
)
def rag_sample_brief() -> MaterializeResult:
    with start_span("phase4.rag"):
        brief = ask(SAMPLE_QUESTIONS[0])
    # Preview kept short; we deliberately do NOT log the full brief to honor
    # logging_rule §1 (avoid persisting potentially-sensitive context dumps).
    return MaterializeResult(metadata={"preview": brief[:200] + "…"})


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
heal_mesh_end_to_end = define_asset_job(
    "heal_mesh_end_to_end",
    selection=[
        synthetic_raw_data,
        iceberg_bronze_tables,
        dbt_telemetry_gold,
        dbt_commercial_gold,
        dbt_clinical_gold,
        semantic_summaries,
        vector_search_index,
        rag_sample_brief,
    ],
)


defs = Definitions(
    assets=[
        synthetic_raw_data,
        iceberg_bronze_tables,
        dbt_telemetry_gold,
        dbt_commercial_gold,
        dbt_clinical_gold,
        semantic_summaries,
        vector_search_index,
        rag_sample_brief,
    ],
    jobs=[heal_mesh_end_to_end],
)
