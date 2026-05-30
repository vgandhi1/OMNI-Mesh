"""Unified OMNI-Mesh CLI (replaces three per-project CLIs).

Every command is profile-aware via ``OMNI_MESH_PROFILE``; switch the env var to run
the same pipeline as ROBOTICS, MANUFACTURING, or HEALTH_TECH.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from config.profiles import active_spec
from config.settings import get_settings
from data_platform import catalog, finops, generators, governance, medallion, policies
from data_platform.ai_readiness import search
from data_platform.vla import closed_loop, feature_extractor, shards

app = typer.Typer(
    help="OMNI-Mesh: universal polymorphic cyber-physical data mesh.",
    add_completion=False,
)
console = Console()


@app.command()
def doctor() -> None:
    """Print the active configuration and salt status (never prints the salt)."""
    settings = get_settings()
    spec = active_spec()
    table = Table(title="OMNI-Mesh doctor")
    table.add_column("key", style="cyan")
    table.add_column("value", style="white")
    table.add_row("profile", settings.profile.value)
    table.add_row("bronze_table", spec.bronze_table)
    table.add_row("warehouse_dir", str(settings.warehouse_dir))
    table.add_row("catalog_db", str(settings.catalog_db))
    table.add_row("chroma_dir", str(settings.chroma_dir))
    table.add_row("embedding_model", settings.embedding_model)
    table.add_row("active_role", settings.active_role)
    table.add_row("masking_salt", governance.salt_status())
    console.print(table)


@app.command()
def ingest(count: int = typer.Option(64, help="Rows to push into Bronze.")) -> None:
    """Generate synthetic telemetry and append to the Bronze Iceberg table."""
    governance.assert_platform_secrets()  # fail closed before any work
    spec = active_spec()
    catalog.ensure_namespaces()
    batch = generators.make_bronze_batch(spec.profile, n=count)
    written = catalog.write_data_product(
        catalog.NAMESPACE_BRONZE, spec.bronze_table, batch, expected_schema=spec.silver_schema
    )
    console.print(f"[green]ingested[/green] {written} rows -> bronze.{spec.bronze_table}")


@app.command()
def enforce() -> None:
    """Run the dbt medallion (Bronze -> Silver/Gold) and publish back to Iceberg."""
    governance.assert_platform_secrets()
    published = medallion.run_medallion()
    for name, rows in published.items():
        console.print(f"  [cyan]{name}[/cyan]: {rows} rows")
    console.print("[green]medallion complete[/green]")


@app.command()
def index() -> None:
    """Build Bronze chunks and (re)populate the ChromaDB index."""
    count = search.index()
    console.print(f"[green]indexed[/green] {count} chunks into '{active_spec().chroma_collection}'")


@app.command()
def ask(question: str = typer.Argument(..., help="Natural-language question.")) -> None:
    """Run a profile-aware agentic RAG query."""
    result = search.ask(question)
    console.print(f"[bold]filters:[/bold] {result.filters or '{}'}")
    console.print(f"[bold]lakehouse rows:[/bold] {len(result.rows)}")
    console.print(result.answer)


@app.command()
def vla(limit: int = typer.Option(64, help="Max episodes to embed.")) -> None:
    """ROBOTICS only — extract CV features into gold.vla_episodes."""
    count = feature_extractor.build_vla_gold(limit=limit)
    console.print(
        f"[green]vla[/green] embedded {count} episodes via "
        f"{feature_extractor.get_backbone_name()} -> gold.vla_episodes"
    )


@app.command(name="shards")
def write_shards(
    samples_per_shard: int = typer.Option(64, "--samples-per-shard"),
) -> None:
    """Write pre-shuffled WebDataset training shards from gold.vla_episodes."""
    written = shards.write_training_shards(samples_per_shard=samples_per_shard)
    console.print(f"[green]shards[/green] wrote {len(written)} shard(s)")


@app.command(name="closed-loop")
def closed_loop_cmd(
    model_version: str = typer.Option("vla_diffusion_v3", "--model-version"),
    env: str = typer.Option("isaac_sim", "--env"),
) -> None:
    """Score deployed-policy inference and log outcomes back to bronze.live_inference."""
    scored = closed_loop.run_closed_loop(model_version=model_version, deployment_env=env)
    console.print(f"[green]closed-loop[/green] scored {scored} episodes -> bronze.live_inference")


@app.command(name="finops")
def finops_cmd() -> None:
    """Per-data-product cost attribution from the latest dbt run."""
    rows = finops.run_audit()
    if not rows:
        console.print("[yellow]no dbt run_results.json found; run `omni-mesh enforce` first[/yellow]")
        return
    table = Table(title=f"FinOps — {get_settings().profile.value}")
    table.add_column("node", style="cyan")
    table.add_column("status")
    table.add_column("time (s)", justify="right")
    table.add_column("cost ($)", justify="right")
    for row in rows:
        table.add_row(row.node, row.status, f"{row.execution_time_s:.3f}", f"{row.estimated_cost_usd:.4f}")
    console.print(table)
    console.print(f"total estimated cost: [bold]${finops.total_cost(rows):.4f}[/bold]")


@app.command(name="governance")
def governance_cmd(
    dialect: str = typer.Option("snowflake", help="snowflake | databricks | bigquery"),
) -> None:
    """Emit profile-aware RLS / masking policy SQL for a cloud dialect."""
    console.print(policies.render_policy(dialect))


@app.command()
def orchestrate() -> None:
    """Run the full Dagster job in-process: ingest -> dbt -> index -> rag."""
    from dagster import materialize

    from orchestration.definitions import ALL_ASSETS

    result = materialize(ALL_ASSETS)
    status = "success" if result.success else "FAILED"
    console.print(f"[green]orchestration {status}[/green]")
    if not result.success:
        raise typer.Exit(code=1)


@app.command()
def gateway(
    host: str = typer.Option("127.0.0.1", help="Bind host."),
    port: int = typer.Option(8000, help="Bind port."),
) -> None:
    """Launch the 500Hz->30Hz telemetry WebSocket gateway (profile-aware)."""
    import uvicorn

    from streaming_gateway.gateway import RENDER_HZ, SAMPLES_PER_FRAME, app as gateway_app

    console.print(
        f"[green]gateway[/green] profile={get_settings().profile.value} "
        f"-> ws://{host}:{port}/ws/telemetry ({SAMPLES_PER_FRAME} samples/frame @ {RENDER_HZ}Hz)"
    )
    uvicorn.run(gateway_app, host=host, port=port, log_level="warning")


@app.command()
def demo(count: int = typer.Option(64, help="Rows for the demo run.")) -> None:
    """Run the full chain: ingest -> enforce -> index -> ask."""
    ingest(count=count)
    enforce()
    index()
    ask("show me failures")


if __name__ == "__main__":
    app()
