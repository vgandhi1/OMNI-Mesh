"""``robomesh`` — one CLI for every phase of the lakehouse demo.

::

    python -m robomesh.cli --help
    python -m robomesh.cli demo
    python -m robomesh.cli ask "find me grasp failures on Figure-01"
"""
from __future__ import annotations

import json
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from robomesh.config import get_settings
from robomesh.logging_setup import get_logger

app = typer.Typer(
    add_completion=False,
    help="RoboMesh — Federated Robotics Telemetry & Demonstration Data Mesh.",
    no_args_is_help=True,
)
console = Console()
log = get_logger(__name__)


# ---------- Phase 0 ------------------------------------------------------- #

@app.command()
def generate() -> None:
    """Phase 0 — synthesize raw multimodal robotics data into Bronze drops."""
    from robomesh.generators import (
        generate_simulation_drops,
        generate_telemetry_drops,
        generate_teleop_drops,
    )

    s = get_settings()
    console.rule("[bold cyan]Phase 0 — Synthesizing raw drops")
    t = generate_teleop_drops(s.raw_root, s.demo_episodes, s.seed)
    e = generate_telemetry_drops(s.raw_root, s.demo_episodes, s.seed)
    p = generate_simulation_drops(s.raw_root, s.demo_episodes, s.seed)

    tbl = Table(title="Bronze drops", show_lines=False, header_style="bold magenta")
    tbl.add_column("Domain", style="cyan")
    tbl.add_column("Table")
    tbl.add_column("Path", overflow="fold")
    for name, path in t.items():
        tbl.add_row("teleop", name, str(path))
    for name, path in e.items():
        tbl.add_row("telemetry", name, str(path))
    for name, path in p.items():
        tbl.add_row("simulation", name, str(path))
    console.print(tbl)


# ---------- Phase 1 ------------------------------------------------------- #

@app.command()
def ingest() -> None:
    """Phase 1 — register raw drops into the Apache Iceberg catalog (Bronze)."""
    from robomesh.ingestion import ingest_all_domains

    console.rule("[bold cyan]Phase 1 — Iceberg Bronze ingestion")
    result = ingest_all_domains()
    tbl = Table(title="Iceberg Bronze tables", header_style="bold magenta")
    tbl.add_column("Domain", style="cyan")
    tbl.add_column("Tables")
    for domain, tables in result.items():
        tbl.add_row(domain, "\n".join(tables) or "(none)")
    console.print(tbl)


# ---------- Phase 2 ------------------------------------------------------- #

@app.command()
def medallion() -> None:
    """Phase 2 — Silver (time-sync) + Gold (VLA tokenization)."""
    from robomesh.transformations import build_gold_layer, build_silver_layer

    console.rule("[bold cyan]Phase 2 — Medallion (Silver → Gold)")
    silver = build_silver_layer()
    gold = build_gold_layer()
    console.print(Panel.fit(f"Silver: [green]{silver}[/]\nGold:   [green]{gold}[/]"))


# ---------- Phase 2.5 ----------------------------------------------------- #

@app.command()
def vla() -> None:
    """Phase 2.5 — PyTorch CV embeddings (Silver→Gold visual features)."""
    from robomesh.cv import HAS_TORCH, get_backbone_name
    from robomesh.transformations import build_vla_layer

    console.rule("[bold cyan]Phase 2.5 — VLA feature store (CV embeddings)")
    silver, gold = build_vla_layer()
    console.print(
        Panel.fit(
            f"Backbone:        [magenta]{get_backbone_name()}[/]\n"
            f"PyTorch loaded:  [{'green' if HAS_TORCH else 'yellow'}]"
            f"{HAS_TORCH}[/]\n"
            f"Silver:          [green]{silver}[/]\n"
            f"Gold v2:         [green]{gold}[/]"
        )
    )


@app.command()
def shards(
    samples_per_shard: int = typer.Option(64, "--samples-per-shard"),
) -> None:
    """Phase 2.5 — write pre-shuffled WebDataset shards for VLA training."""
    from robomesh.training import write_training_shards

    console.rule("[bold cyan]Phase 2.5 — WebDataset shard writer")
    paths = write_training_shards(samples_per_shard=samples_per_shard)
    tbl = Table(title="Training shards", header_style="bold magenta")
    tbl.add_column("Shard")
    tbl.add_column("Bytes", justify="right")
    for p in paths:
        tbl.add_row(p.name, f"{p.stat().st_size:,}")
    console.print(tbl)


# ---------- Phase 6 — closed loop ---------------------------------------- #

@app.command(name="closed-loop")
def closed_loop(
    model_version: str = typer.Option("vla_diffusion_v3", "--model-version"),
    deployment_env: str = typer.Option("isaac_sim", "--env"),
    steps: int = typer.Option(4, "--steps", help="Inference steps per episode."),
) -> None:
    """Phase 6 — stream deployed-model inference back into Bronze."""
    from robomesh.closed_loop import simulate_live_inference
    from robomesh.closed_loop.inference_logger import closed_loop_summary

    console.rule("[bold cyan]Phase 6 — Closed-loop policy evaluation")
    n = simulate_live_inference(
        model_version=model_version,
        deployment_env=deployment_env,
        n_steps_per_episode=steps,
    )
    summary = closed_loop_summary()
    console.print(
        Panel.fit(
            f"Inference events written: [green]{n}[/]\n"
            f"Total events in Bronze:   [green]{summary['n_events']}[/]\n"
            f"Failures observed:        [yellow]{summary['n_failures']}[/]\n"
            f"Mean confidence:          [magenta]{summary['mean_confidence']:.3f}[/]\n"
            f"Bronze table:             [cyan]simulation.bronze_live_inference[/]"
        )
    )


# ---------- Phase 3 ------------------------------------------------------- #

@app.command()
def governance() -> None:
    """Phase 3 — enforce data contracts and apply role-based masking."""
    from robomesh.governance import apply_dynamic_masking, enforce_all_contracts

    console.rule("[bold cyan]Phase 3 — Governance")
    report = enforce_all_contracts(raise_on_violation=False)
    tbl = Table(title="Contract report", header_style="bold magenta")
    tbl.add_column("Table", style="cyan")
    tbl.add_column("Violations")
    for k, v in report.items():
        tbl.add_row(k, "[green]none[/]" if not v else "[red]" + str(len(v)) + "[/]")
    console.print(tbl)

    governed = apply_dynamic_masking()
    console.print(
        Panel.fit(
            "Role: [bold]" + get_settings().active_role + "[/]\n"
            "Masked tables: " + ", ".join(governed)
        )
    )


# ---------- Phase 4 ------------------------------------------------------- #

@app.command()
def semantic() -> None:
    """Phase 4 — summarize episodes, embed, and upsert into the vector index."""
    from robomesh.semantic import build_episode_summaries, upsert_episode_vectors

    console.rule("[bold cyan]Phase 4 — Semantic index")
    summaries = build_episode_summaries()
    n = upsert_episode_vectors(summaries)
    console.print(Panel.fit(f"Indexed [green]{n}[/] episode summaries"))


@app.command()
def ask(
    question: str = typer.Argument(..., help="Natural-language data-mining question."),
    k: int = typer.Option(8, "--k", help="Max hits to return."),
) -> None:
    """Ask the Agentic RAG layer (queries the semantic + Iceberg layers)."""
    from robomesh.semantic.rag_agent import RoboMeshAgent

    console.rule(f"[bold cyan]Agentic RAG — {question!r}")
    answer = RoboMeshAgent(k=k).answer(question)
    console.print(Panel.fit(answer.natural_language, title="Answer"))
    if answer.iceberg_rows:
        tbl = Table(title="Top Iceberg rows", header_style="bold magenta")
        for col in answer.iceberg_rows[0]:
            tbl.add_column(col)
        for row in answer.iceberg_rows[:10]:
            tbl.add_row(*[str(v) for v in row.values()])
        console.print(tbl)


# ---------- Phase 5 ------------------------------------------------------- #

@app.command()
def orchestrate() -> None:
    """Phase 5 — FinOps audit + materialized-table summary."""
    from robomesh.catalog.iceberg import list_tables
    from robomesh.orchestration.finops import run_finops_audit

    console.rule("[bold cyan]Phase 5 — Orchestration & FinOps")
    rows = run_finops_audit()
    tbl = Table(title="FinOps audit", header_style="bold magenta")
    tbl.add_column("User")
    tbl.add_column("Warehouse")
    tbl.add_column("Seconds", justify="right")
    tbl.add_column("Cost (USD)", justify="right")
    for r in rows:
        tbl.add_row(
            r.user_name,
            r.warehouse_name,
            f"{r.execution_time_seconds:.3f}",
            f"${r.estimated_compute_cost_usd:.4f}",
        )
    console.print(tbl)

    tables = list_tables()
    console.print(Panel.fit(
        f"Iceberg tables registered: [green]{len(tables)}[/]\n"
        + "\n".join(" • " + t for t in tables)
    ))


# ---------- Convenience --------------------------------------------------- #

@app.command()
def demo(
    with_vla: bool = typer.Option(
        True, "--with-vla/--no-vla",
        help="Run Phase 2.5 CV embeddings + Phase 6 closed loop "
             "(requires the ML extras for real PyTorch; falls back to "
             "the NumPy encoder otherwise).",
    ),
) -> None:
    """Run every phase end-to-end (Phase 0 → 6)."""
    generate()
    ingest()
    medallion()
    if with_vla:
        vla()
        shards()
    governance()
    semantic()
    orchestrate()
    if with_vla:
        closed_loop()
    console.rule("[bold green]RoboMesh demo complete")


@app.command(name="train-sample")
def train_sample(
    limit: int = typer.Option(4, "--limit", help="Show this many samples."),
) -> None:
    """Iterate a few samples through the training interface (Ray or torch)."""
    from robomesh.training import (
        HAS_RAY,
        RoboMeshTorchDataset,
        build_ray_dataset,
    )
    from robomesh.cv import HAS_TORCH

    console.rule("[bold cyan]Training interface — sample inspection")
    if HAS_RAY:
        ds = build_ray_dataset()
        rows = ds.take(limit) if ds is not None else []
        for row in rows:
            feats = row.pop("features", None)
            console.print({"features_dim": len(feats) if feats else None, **row})
        console.print(Panel.fit("[green]Streamed via Ray Data[/]"))
        return

    if HAS_TORCH:
        ds = RoboMeshTorchDataset()
        count = 0
        for sample in ds:
            console.print(
                {
                    "episode_id": sample["__key__"],
                    "features_shape": tuple(sample["features"].shape),
                    "metadata": {
                        k: sample["metadata"][k]
                        for k in ("robot_model_id", "failure_type_tag",
                                 "success_flag", "embedding_dim")
                    },
                }
            )
            count += 1
            if count >= limit:
                break
        console.print(Panel.fit(f"[green]Streamed {count} samples via PyTorch IterableDataset[/]"))
        return

    console.print(
        Panel.fit(
            "[yellow]Neither Ray nor PyTorch is installed.[/]\n"
            "Install the ML extras to stream training samples:\n"
            "    [cyan]pip install -r requirements-ml.txt[/]"
        )
    )


@app.command()
def doctor() -> None:
    """Print the active configuration (no secrets emitted)."""
    s = get_settings()
    # Logging rule — only emit a status enum for the salt, never the value.
    # ``valid`` means assert_masking_salt would not raise; ``placeholder``
    # means the salt is non-empty but matches a documented placeholder; and
    # ``unset`` means it is missing entirely. We deliberately do not log the
    # length to avoid hinting at the salt's strength.
    try:
        s.assert_masking_salt()
        salt_status = "valid"
    except RuntimeError:
        salt_status = "unset" if not s.masking_salt else "placeholder"

    info = {
        "data_root": str(s.data_root),
        "warehouse_root": str(s.warehouse_root),
        "catalog_uri": s.catalog_uri,
        "embedding_model": s.embedding_model,
        "demo_episodes": s.demo_episodes,
        "active_role": s.active_role,
        "masking_salt_status": salt_status,
    }
    console.print(Panel.fit(json.dumps(info, indent=2), title="RoboMesh config"))


@app.command(name="list")
def list_cmd() -> None:
    """List all Iceberg tables registered in the local catalog."""
    from robomesh.catalog.iceberg import list_tables

    for t in list_tables():
        console.print(f" • [cyan]{t}[/]")


def main() -> None:  # pragma: no cover - thin wrapper for ``python -m``
    app()


if __name__ == "__main__":
    main()
