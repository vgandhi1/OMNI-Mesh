"""Single-command HEAL-Mesh demo runner.

Executes every phase sequentially with a Rich progress indicator. This is the
canonical entry point used by ``make orchestrate`` when Dagster is overkill
(e.g. CI checks, demo notebooks). The same logical asset graph also lives
under ``orchestration/dagster/`` for the UI-driven experience.

Steps:
    1. Generate synthetic data (Phase 1)
    2. Bootstrap Iceberg catalog + bronze tables (Phase 1)
    3. Build the three dbt projects (Phase 2 + Phase 3 PHI masking)
    4. Semantic serialization of gold metrics (Phase 4)
    5. Vector embedding + indexing into ChromaDB (Phase 4)
    6. Sample agentic RAG query (Phase 4)
    7. Local FinOps audit (Phase 5)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from rich.console import Console

from scripts._config import PROJECT_ROOT, configure_logging, get_settings

LOG = configure_logging()
CONSOLE = Console()


def _step(title: str) -> None:
    CONSOLE.rule(f"[bold cyan]{title}")


def _run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> None:
    """Run a subprocess and stream output. Raises on non-zero exit."""
    env_final = {**os.environ, **(env or {})}
    LOG.info("exec: %s (cwd=%s)", " ".join(cmd), cwd or ".")
    result = subprocess.run(cmd, cwd=cwd, env=env_final)
    if result.returncode != 0:
        raise SystemExit(f"step failed: {' '.join(cmd)} (exit {result.returncode})")


def main() -> None:
    settings = get_settings()
    settings.assert_phi_salt()
    settings.ensure_dirs()

    project_root = str(PROJECT_ROOT)
    dbt_env = {
        "HEAL_MESH_PROJECT_ROOT": project_root,
        "HEAL_MESH_PHI_SALT": settings.phi_salt,
    }
    py = sys.executable

    _step("Phase 1 · Synthetic data generation")
    _run([py, "-m", "scripts.generate_synthetic_data"], cwd=PROJECT_ROOT)

    _step("Phase 1 · Iceberg catalog + bronze tables")
    _run([py, "-m", "scripts.bootstrap_iceberg"], cwd=PROJECT_ROOT)

    _step("Phase 1 · Cross-engine Iceberg interop verification")
    _run([py, "-m", "scripts.verify_iceberg_interop"], cwd=PROJECT_ROOT)

    for domain in ("telemetry", "commercial", "clinical"):
        _step(f"Phase 2 · dbt build [{domain}]")
        dbt_dir = PROJECT_ROOT / "domains" / domain / "dbt"
        _run(
            [
                str(PROJECT_ROOT / ".venv" / "bin" / "dbt"),
                "build",
                "--profiles-dir",
                ".",
                "--no-version-check",
            ],
            cwd=dbt_dir,
            env=dbt_env,
        )

    _step("Phase 4 · Semantic serialization of gold metrics")
    _run([py, "-m", "ai_readiness.serialization.semantic_serializer"], cwd=PROJECT_ROOT)

    _step("Phase 4 · Vector embedding pipeline")
    _run([py, "-m", "ai_readiness.embeddings.vector_pipeline"], cwd=PROJECT_ROOT)

    _step("Phase 4 · Agentic RAG sample queries")
    _run([py, "-m", "ai_readiness.rag.agentic_rag"], cwd=PROJECT_ROOT)

    _step("Phase 5 · FinOps cost audit")
    _run([py, "-m", "finops.run_audit"], cwd=PROJECT_ROOT)

    CONSOLE.rule("[bold green]HEAL-Mesh end-to-end run complete")


if __name__ == "__main__":
    main()
