"""Typer-based CLI entrypoint for MFG-Mesh.

Examples
--------
$ mfg-mesh status
$ mfg-mesh simulate --count 100
$ mfg-mesh ingest --count 500
$ mfg-mesh enforce
$ mfg-mesh ask "What voltage anomalies hit Texas this week?"
"""

from __future__ import annotations

import logging

import typer
from rich.console import Console
from rich.table import Table

from .config import get_config
from .edge.opc_ua_simulator import OpcUaSimulator
from .lakehouse.catalog import get_catalog
from .lakehouse.ingest import run_bronze_ingest
from .quality.contracts import build_gold_aggregates, enforce_silver_contract
from .rag.agent import RagAssistant
from .rag.chunker import build_failure_chunks
from .rag.vector_store import FactoryFailureIndex
from .security import assert_platform_secrets

app = typer.Typer(help="MFG-Mesh: industrial IT/OT lakehouse reference platform.", add_completion=False)
console = Console()
logger = logging.getLogger(__name__)


def _bootstrap() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    assert_platform_secrets()


@app.command()
def status() -> None:
    """Print platform configuration and lakehouse table status."""
    _bootstrap()
    cfg = get_config()
    table = Table(title="MFG-Mesh status", show_lines=False)
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="white")
    table.add_row("Warehouse", str(cfg.warehouse_dir))
    table.add_row("Catalog DB", str(cfg.catalog_db))
    table.add_row("Chroma dir", str(cfg.chroma_dir))
    table.add_row("Facilities", ", ".join(cfg.facilities))
    table.add_row("Kafka enabled", str(cfg.kafka_enabled))
    console.print(table)

    cat = get_catalog(cfg)
    namespaces = [".".join(n) for n in cat.list_namespaces()]
    tables = []
    for ns in namespaces:
        for ident in cat.list_tables(ns):
            tables.append(".".join(ident))
    nstable = Table(title="Iceberg objects")
    nstable.add_column("Namespaces", style="green")
    nstable.add_column("Tables", style="magenta")
    nstable.add_row("\n".join(namespaces) or "(none)", "\n".join(tables) or "(none)")
    console.print(nstable)


@app.command()
def simulate(count: int = typer.Option(100, help="Number of readings to emit.")) -> None:
    """Run the OPC UA simulator standalone (no ingest)."""
    _bootstrap()
    cfg = get_config()
    sim = OpcUaSimulator(facilities=cfg.facilities, lines_per_facility=cfg.lines_per_facility, registers_per_line=cfg.registers_per_line, seed=0)
    readings = sim.batch(count)
    console.print(f"Generated [bold]{len(readings)}[/bold] readings. Sample:")
    console.print(readings[0])


@app.command()
def ingest(count: int = typer.Option(500, help="Telemetry rows to push through bronze.")) -> None:
    """Generate telemetry and append to the bronze Iceberg table."""
    _bootstrap()
    cfg = get_config()
    sim = OpcUaSimulator(facilities=cfg.facilities, lines_per_facility=cfg.lines_per_facility, registers_per_line=cfg.registers_per_line, seed=1)
    readings = sim.batch(count)
    result = run_bronze_ingest(readings)
    console.print(f"Bronze ingest complete: [bold]{result['rows_written']}[/bold] rows -> {result['table']}")


@app.command()
def enforce() -> None:
    """Apply silver SLA contracts and refresh gold aggregates."""
    _bootstrap()
    silver = enforce_silver_contract()
    gold = build_gold_aggregates()
    console.print(
        f"Silver: rows_out=[bold]{silver.rows_out}[/bold] violations=[bold red]{silver.contract_violations}[/bold red] table={silver.table}"
    )
    console.print(f"Gold:   rows_out=[bold]{gold['rows_written']}[/bold] table={gold['table']}")


@app.command("index")
def reindex() -> None:
    """Build failure chunks and (re)populate the ChromaDB index."""
    _bootstrap()
    chunks = build_failure_chunks()
    idx = FactoryFailureIndex()
    upserted = idx.upsert(chunks)
    console.print(f"Indexed [bold]{upserted}[/bold] chunks. Collection size: {idx.count()}")


@app.command()
def ask(question: str = typer.Argument(..., help="Natural-language troubleshooting question.")) -> None:
    """Run an agentic RAG query."""
    _bootstrap()
    assistant = RagAssistant()
    answer = assistant.ask(question)
    console.print(f"[bold]Matched facilities:[/bold] {', '.join(answer.matched_facilities) or '(none)'}")
    console.print(answer.summary)


if __name__ == "__main__":
    app()
