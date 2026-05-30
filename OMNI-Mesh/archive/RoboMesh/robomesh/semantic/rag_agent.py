"""Lightweight, deterministic Agentic-RAG layer over the lakehouse.

We deliberately avoid binding to a commercial LLM so the demo runs offline.
The "agent" performs three actions in sequence:

1. **Intent parsing** — pulls structured filters from the natural-language query
   (e.g. ``"GRASP_FAIL"`` or ``"successful"``).
2. **Vector retrieval** — runs the semantic query against ChromaDB.
3. **Structured re-query** — joins matching episode IDs back to the Iceberg
   Gold table via DuckDB so the researcher gets *exact* data pointers.

Swapping in an LLM for step 1 + step 4 (response synthesis) is a one-line
change — see ``RoboMeshAgent.answer``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import duckdb

from robomesh.catalog.iceberg import read_table_arrow
from robomesh.logging_setup import get_logger
from robomesh.semantic.vector_store import query_episodes

log = get_logger(__name__)


@dataclass
class AgentAnswer:
    """Structured response returned by :meth:`RoboMeshAgent.answer`."""

    query: str
    filters: dict[str, Any] = field(default_factory=dict)
    matches: list[dict] = field(default_factory=list)
    iceberg_rows: list[dict] = field(default_factory=list)
    natural_language: str = ""


_FAIL_TAGS = (
    "GRASP_FAIL",
    "OVER_TORQUE",
    "VISION_OCCLUSION",
    "PATH_PLAN_TIMEOUT",
    "MOTOR_OVERHEAT",
)
_GRIPPERS = ("2-finger", "3-finger", "vacuum", "5-finger")


def _parse_intent(query: str) -> dict[str, Any]:
    """Best-effort filter extraction from natural language."""
    q = query.lower()
    filters: dict[str, Any] = {}

    for tag in _FAIL_TAGS:
        if tag.lower() in q or tag.lower().replace("_", " ") in q:
            filters["failure_type_tag"] = tag
            break

    if "successful" in q or "success" in q or "recovered" in q:
        filters["success_flag"] = True
    elif re.search(r"\bfail(ed|ure)?\b", q):
        filters["success_flag"] = False

    for g in _GRIPPERS:
        if g.lower() in q:
            filters["gripper_type"] = g
            break

    # Robot model parsing.
    m = re.search(r"\b(figure-01|optimus-gen2|atlas-next|apollo-1)\b", q)
    if m:
        filters["robot_model_id"] = m.group(1).title().replace(
            "-G", "-G").replace("-N", "-N").replace("-0", "-0")
        # Re-canonicalize since our generators emit specific casings.
        canonical = {
            "Figure-01": "Figure-01",
            "Optimus-Gen2": "Optimus-Gen2",
            "Atlas-Next": "Atlas-Next",
            "Apollo-1": "Apollo-1",
        }
        for k in canonical:
            if k.lower() == m.group(1).lower():
                filters["robot_model_id"] = k
                break

    return filters


def _to_chroma_where(filters: dict[str, Any]) -> dict[str, Any] | None:
    """Translate parsed intent into the dict shape Chroma expects."""
    if not filters:
        return None
    if len(filters) == 1:
        ((k, v),) = filters.items()
        return {k: v}
    return {"$and": [{k: v} for k, v in filters.items()]}


def _fetch_iceberg_rows(episode_ids: list[str]) -> list[dict]:
    if not episode_ids:
        return []
    gold = read_table_arrow("gold.vla_episodes")
    con = duckdb.connect()
    con.register("g", gold)
    placeholders = ", ".join(["?"] * len(episode_ids))
    rows = con.execute(
        f"""
        SELECT episode_id, robot_model_id, factory_site, failure_type_tag,
               success_flag, gripper_type, target_object, peak_torque_nm,
               mean_policy_confidence, trajectory_l2_error_m
        FROM g WHERE episode_id IN ({placeholders})
        """,
        episode_ids,
    ).fetchall()
    cols = [d[0] for d in con.description]
    con.close()
    return [dict(zip(cols, r)) for r in rows]


def _synthesize_answer(query: str, filters: dict[str, Any], rows: list[dict]) -> str:
    if not rows:
        return (
            f"I could not find any episodes matching '{query}'. Try relaxing "
            f"the filters {filters or 'none'}, or re-running `make semantic` "
            "to rebuild the vector index."
        )
    head = (
        f"Found {len(rows)} matching episode{'s' if len(rows) != 1 else ''} "
        f"for: '{query}'."
    )
    if filters:
        head += f" Applied filters: {filters}."
    bullets = []
    for r in rows[:5]:
        bullets.append(
            f" • {r['episode_id']} — {r['robot_model_id']} @ {r['factory_site']}: "
            f"{r.get('failure_type_tag') or 'NO_FAILURE'} | "
            f"peak torque {float(r.get('peak_torque_nm') or 0.0):.1f} Nm | "
            f"mean policy confidence {float(r.get('mean_policy_confidence') or 0.0):.2f}"
        )
    return head + "\n" + "\n".join(bullets)


@dataclass
class RoboMeshAgent:
    """Deterministic agent — swap ``_synthesize_answer`` for an LLM call."""

    k: int = 8

    def answer(self, query: str) -> AgentAnswer:
        filters = _parse_intent(query)
        where = _to_chroma_where(filters)
        matches = query_episodes(query, k=self.k, where=where)
        episode_ids = [m["episode_id"] for m in matches]
        iceberg_rows = _fetch_iceberg_rows(episode_ids)
        nl = _synthesize_answer(query, filters, iceberg_rows)
        log.info(
            "agent.answer query_len=%d filters=%s n_hits=%d",
            len(query), list(filters.keys()), len(matches),
        )
        return AgentAnswer(
            query=query,
            filters=filters,
            matches=matches,
            iceberg_rows=iceberg_rows,
            natural_language=nl,
        )
