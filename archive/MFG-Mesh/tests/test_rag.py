"""Phase 4 RAG agent tests (using deterministic facility extraction)."""

from __future__ import annotations

from mfg_mesh.edge.opc_ua_simulator import OpcUaSimulator
from mfg_mesh.config import get_config
from mfg_mesh.lakehouse.ingest import run_bronze_ingest
from mfg_mesh.rag.agent import RagAssistant
from mfg_mesh.rag.chunker import build_failure_chunks
from mfg_mesh.rag.vector_store import FactoryFailureIndex


def _seed_bronze_with_anomalies():
    cfg = get_config()
    sim = OpcUaSimulator(
        facilities=cfg.facilities,
        lines_per_facility=2,
        registers_per_line=3,
        anomaly_rate=0.5,
        schema_drift_after=None,
        seed=99,
    )
    run_bronze_ingest(sim.batch(80))


def test_chunker_produces_well_formed_text():
    _seed_bronze_with_anomalies()
    chunks = build_failure_chunks()
    assert chunks, "expected at least one anomaly chunk"
    first = chunks[0]
    assert "Facility" in first.text and "Line" in first.text
    assert first.chunk_id and len(first.chunk_id) == 24


def test_rag_assistant_constrains_by_facility_via_word_boundaries():
    _seed_bronze_with_anomalies()
    index = FactoryFailureIndex()
    index.upsert(build_failure_chunks())

    assistant = RagAssistant(index=index)
    answer = assistant.ask("What anomalies appeared in Texas last shift?")
    assert "Texas_Giga_01" in answer.matched_facilities
    # A prompt without a facility token should not narrow the filter.
    broad = assistant.ask("Show me line slowdowns this month")
    assert broad.matched_facilities == []
