"""Lightweight agentic RAG interface for forward-deployed engineers.

We deliberately avoid pulling in an LLM dependency here. The "agent" extracts
recognized facility names from the natural-language prompt via *exact regex
word boundaries* (per the spec) and uses them to constrain the Chroma query
with a metadata filter. The retrieved chunks plus a brief deterministic
summary are returned as the response.

The same component is what a downstream LLM-powered orchestrator would call
to gather grounded context before generating its final response.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List

from ..config import MFGMeshConfig, get_config
from .vector_store import FactoryFailureIndex

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RagAnswer:
    summary: str
    matched_facilities: List[str]
    citations: List[dict]


class RagAssistant:
    """Conversational interface over the `factory_failure_taxonomy` index."""

    def __init__(self, index: FactoryFailureIndex | None = None, cfg: MFGMeshConfig | None = None) -> None:
        self.cfg = cfg or get_config()
        self.index = index or FactoryFailureIndex(self.cfg)

    # --- Facility extraction ------------------------------------------------

    def _match_facilities(self, prompt: str) -> List[str]:
        """Return configured facilities that appear in the prompt verbatim.

        We honor the spec by using exact regex word boundaries
        (``rf"\\b{facility_name}\\b"``) so partial matches like "tex" won't
        accidentally trigger ``Texas_Giga_01``.
        """
        matches: list[str] = []
        for facility in self.cfg.facilities:
            pattern = re.compile(rf"\b{re.escape(facility)}\b", re.IGNORECASE)
            if pattern.search(prompt):
                matches.append(facility)
            else:
                # Also accept the human "Texas" or "Berlin" prefix from the
                # configured facility name (everything before the first '_').
                short = facility.split("_", 1)[0]
                if short and re.search(rf"\b{re.escape(short)}\b", prompt, re.IGNORECASE):
                    matches.append(facility)
        # Preserve order, drop duplicates.
        seen: set[str] = set()
        return [m for m in matches if not (m in seen or seen.add(m))]

    # --- Public surface -----------------------------------------------------

    def ask(self, prompt: str, *, n_results: int = 5) -> RagAnswer:
        prompt = (prompt or "").strip()
        if not prompt:
            return RagAnswer(summary="", matched_facilities=[], citations=[])

        facilities = self._match_facilities(prompt)
        where = None
        if facilities:
            where = {"facility_id": {"$in": facilities}} if len(facilities) > 1 else {"facility_id": facilities[0]}

        citations = self.index.query(prompt, n_results=n_results, where=where)
        if not citations:
            return RagAnswer(
                summary="No matching anomaly history found for this query.",
                matched_facilities=facilities,
                citations=[],
            )

        bullets = [
            f"- [{c['metadata'].get('facility_id', '?')}] {c['document']}"
            for c in citations
        ]
        summary = (
            f"Found {len(citations)} relevant anomaly events"
            + (f" across {', '.join(facilities)}" if facilities else "")
            + ":\n"
            + "\n".join(bullets)
        )
        return RagAnswer(summary=summary, matched_facilities=facilities, citations=citations)
