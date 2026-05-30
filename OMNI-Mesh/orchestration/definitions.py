"""Profile-aware software-defined assets for the end-to-end OMNI-Mesh pipeline.

    bronze_ingest -> bronze_parquet -> dbt_medallion -> semantic_index -> rag_smoke

Every asset reads ``OMNI_MESH_PROFILE`` at runtime, so the same graph materializes
the ROBOTICS, MANUFACTURING, or HEALTH_TECH lakehouse depending on the environment.
Run it headless via ``omni-mesh orchestrate`` or interactively with
``dagster dev -m orchestration.definitions``.
"""

from __future__ import annotations

from dagster import Definitions, MaterializeResult, asset, define_asset_job

from config.profiles import active_spec
from config.settings import get_settings
from data_platform import catalog, generators, governance, medallion
from data_platform.ai_readiness import search


@asset(group_name="phase1_lakehouse", description="Generate synthetic Bronze and append to Iceberg.")
def bronze_ingest() -> MaterializeResult:
    governance.assert_platform_secrets()
    spec = active_spec()
    catalog.ensure_namespaces()
    batch = generators.make_bronze_batch(spec.profile, n=get_settings_count())
    rows = catalog.write_data_product(
        catalog.NAMESPACE_BRONZE, spec.bronze_table, batch, expected_schema=spec.silver_schema
    )
    return MaterializeResult(metadata={"profile": spec.profile.value, "rows": rows})


@asset(group_name="phase2_medallion", deps=[bronze_ingest], description="Export Bronze to parquet for dbt.")
def bronze_parquet() -> MaterializeResult:
    return MaterializeResult(metadata={"parquet": medallion.export_bronze_parquet()})


@asset(group_name="phase2_medallion", deps=[bronze_parquet], description="dbt Silver+Gold, published to Iceberg.")
def dbt_medallion() -> MaterializeResult:
    medallion.run_dbt("build")
    published = medallion.publish_to_iceberg()
    return MaterializeResult(metadata={f"rows.{k}": v for k, v in published.items()})


@asset(group_name="phase4_ai", deps=[dbt_medallion], description="Embed Bronze chunks into ChromaDB.")
def semantic_index() -> MaterializeResult:
    return MaterializeResult(metadata={"chunks": search.index()})


@asset(group_name="phase4_ai", deps=[semantic_index], description="Smoke-test the agentic RAG layer.")
def rag_smoke() -> MaterializeResult:
    answer = search.ask("show me failures")
    return MaterializeResult(metadata={"rows": len(answer.rows), "filters": str(answer.filters)})


def get_settings_count() -> int:
    """Demo ingest volume (kept small for the orchestrated run)."""
    return 64


ALL_ASSETS = [bronze_ingest, bronze_parquet, dbt_medallion, semantic_index, rag_smoke]

omni_mesh_end_to_end = define_asset_job("omni_mesh_end_to_end", selection="*")

defs = Definitions(assets=ALL_ASSETS, jobs=[omni_mesh_end_to_end])
