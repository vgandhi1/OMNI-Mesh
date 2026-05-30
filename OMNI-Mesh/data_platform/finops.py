"""FinOps cost attribution.

Parses the dbt ``run_results.json`` artifact (written by ``omni-mesh enforce``) to
attribute per-model execution time and an estimated dollar cost to the active data
product. In production this maps to ``snowflake.account_usage.query_history``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from config.settings import get_settings

logger = logging.getLogger("omni_mesh.finops")

DEFAULT_COST_PER_SECOND = 0.05


@dataclass(frozen=True)
class FinOpsRow:
    data_product: str
    node: str
    status: str
    execution_time_s: float
    estimated_cost_usd: float


def run_audit(
    *, cost_per_second: float = DEFAULT_COST_PER_SECOND, results_path: Path | None = None
) -> list[FinOpsRow]:
    settings = get_settings()
    path = results_path or (settings.dbt_dir / "target" / "run_results.json")
    if not path.exists():
        logger.warning("no dbt run_results.json at %s; run `omni-mesh enforce` first", path)
        return []

    data = json.loads(path.read_text())
    rows: list[FinOpsRow] = []
    for result in data.get("results", []):
        seconds = float(result.get("execution_time", 0.0) or 0.0)
        rows.append(
            FinOpsRow(
                data_product=settings.profile.value,
                node=result.get("unique_id", "?"),
                status=str(result.get("status", "?")),
                execution_time_s=round(seconds, 4),
                estimated_cost_usd=round(seconds * cost_per_second, 4),
            )
        )
    rows.sort(key=lambda r: r.execution_time_s, reverse=True)
    return rows


def total_cost(rows: list[FinOpsRow]) -> float:
    return round(sum(r.estimated_cost_usd for r in rows), 4)
