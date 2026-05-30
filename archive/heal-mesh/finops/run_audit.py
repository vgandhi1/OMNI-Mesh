"""Phase 5 — local FinOps audit runner.

In production these queries hit ``snowflake.account_usage.query_history`` and
``system.billing.usage`` respectively. Locally we simulate a minimal query log
by inspecting the dbt ``run_results.json`` artifacts produced by each domain
and printing the equivalent "long-running query" attribution per-domain.
"""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from scripts._config import PROJECT_ROOT

DOMAINS = ["telemetry", "commercial", "clinical"]
console = Console()


def _scan_dbt_run_results() -> list[dict]:
    rows: list[dict] = []
    for domain in DOMAINS:
        rr = PROJECT_ROOT / "domains" / domain / "dbt" / "target" / "run_results.json"
        if not rr.exists():
            continue
        data = json.loads(rr.read_text(encoding="utf-8"))
        for result in data.get("results", []):
            rows.append(
                {
                    "data_product": domain,
                    "node": result.get("unique_id", ""),
                    "status": result.get("status", ""),
                    "execution_time_s": round(result.get("execution_time", 0.0), 3),
                    "rows_affected": result.get("adapter_response", {}).get("rows_affected"),
                }
            )
    return rows


def main() -> None:
    rows = _scan_dbt_run_results()
    if not rows:
        console.print(
            "[yellow]No dbt run_results found - run `make dbt-all` first to populate the FinOps audit.[/yellow]"
        )
        return

    rows.sort(key=lambda r: r["execution_time_s"], reverse=True)

    table = Table(title="HEAL-Mesh local FinOps audit (top dbt nodes by runtime)")
    table.add_column("Data product")
    table.add_column("Node")
    table.add_column("Status")
    table.add_column("Exec time (s)", justify="right")
    table.add_column("Rows", justify="right")

    for r in rows[:25]:
        table.add_row(
            r["data_product"],
            r["node"],
            r["status"],
            f"{r['execution_time_s']:.2f}",
            str(r["rows_affected"] or "-"),
        )

    console.print(table)

    total_by_domain: dict[str, float] = {}
    for r in rows:
        total_by_domain[r["data_product"]] = total_by_domain.get(r["data_product"], 0.0) + r["execution_time_s"]

    spend_table = Table(title="Total dbt runtime by domain (proxy for warehouse spend)")
    spend_table.add_column("Domain")
    spend_table.add_column("Total exec time (s)", justify="right")
    spend_table.add_column("Synthetic $ cost @ $0.05/s", justify="right")
    for domain, secs in sorted(total_by_domain.items(), key=lambda kv: -kv[1]):
        spend_table.add_row(domain, f"{secs:.2f}", f"${secs * 0.05:.2f}")
    console.print(spend_table)


if __name__ == "__main__":
    main()
