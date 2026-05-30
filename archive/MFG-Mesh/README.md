# MFG-Mesh

> [!IMPORTANT]
> **ARCHIVED / LEGACY.** This project has been consolidated into **[OMNI-Mesh](../../OMNI-Mesh)**,
> a single polymorphic codebase that runs this domain (and the others) via the
> `OMNI_MESH_PROFILE` environment variable. The `MANUFACTURING` profile in OMNI-Mesh supersedes
> MFG-Mesh. This repo is kept read-only for history and reference only — new work should happen
> in OMNI-Mesh.

> High-fidelity Industrial IT/OT Data Platform & Governance Engine — runnable reference implementation of the blueprint described in [`mfg-mesh.md`](./mfg-mesh.md).

MFG-Mesh demonstrates a unified data lakehouse that ingests high-frequency factory floor sensor data (simulating OPC UA / PLCs), enforces strict automated data-quality SLAs, handles real-time schema evolution without breaking history, and serves pre-computed features directly to manufacturing AI models through an agentic RAG layer.

## Architecture

```
Factory Floor (OT)            Edge Gateway Tiers              Unified Cloud Lakehouse (IT)
┌─────────────────┐           ┌───────────────────┐           ┌────────────────────────────┐
│ PLCs / SCADA    │ ──MQTT──► │ Rust Edge Gateway │ ──gRPC──► │ Apache Kafka / Flink       │
│ (OPC UA Sim)    │           │ (Local Buffer)    │           │ (Real-time Streaming)      │
└─────────────────┘           └───────────────────┘           └──────────────┬─────────────┘
                                                                             │ dbt Mesh / Iceberg
                                                                             ▼
                                                              ┌────────────────────────────┐
                                                              │ Medallion Lakehouse Engine │
                                                              │ (Bronze ➔ Silver ➔ Gold)   │
                                                              └──────────────┬─────────────┘
                                                                             ▼
                                                              ┌────────────────────────────┐
                                                              │ Feature Serving & RAG Tier │
                                                              └────────────────────────────┘
```

## Repository Layout

| Path | Purpose |
| --- | --- |
| `mfg_mesh/edge/` | Phase 1 — OPC UA simulator + optional Kafka transport |
| `mfg_mesh/lakehouse/` | Phase 2 — Iceberg catalog bootstrap, hardened ingest, schema evolution |
| `mfg_mesh/quality/` | Phase 3 — Silver/Gold contract enforcement (DuckDB on Iceberg) |
| `mfg_mesh/orchestration/` | Phase 3 — Dagster software-defined assets with SLA metadata |
| `mfg_mesh/rag/` | Phase 4 — Failure-event chunker, ChromaDB store, agentic assistant |
| `mfg_mesh/security.py` | Phase 5 — Fail-closed masking salt + deterministic pseudonymization |
| `dbt_mfg_mesh/` | dbt Mesh project with `enforced: true` silver contracts |
| `scripts/run_demo.py` | End-to-end demo across all 5 phases |
| `tests/` | Pytest suite for simulator, lakehouse, quality, RAG, security |

## Quick Start

```bash
python3 -m venv .venv && source .venv/bin/activate
make install            # core demo + test dependencies
cp .env.example .env    # then edit MFG_MESH_MASKING_SALT to a real secret
make demo               # runs Phase 1 → Phase 5 against local Iceberg + Chroma
make test               # run the test suite
```

For the full toolchain (Dagster UI, dbt Mesh, sentence-transformer embeddings, Kafka):

```bash
make install-full
```

### Optional: Streaming mode

The default demo writes telemetry directly into Iceberg. To exercise the
Kafka path:

```bash
docker compose up -d redpanda
export MFG_MESH_KAFKA_ENABLED=true
python -c "from mfg_mesh.edge.kafka_transport import publish_readings; \
           from mfg_mesh.edge.opc_ua_simulator import OpcUaSimulator; \
           publish_readings(OpcUaSimulator(facilities=['Texas_Giga_01']).batch(200))"
```

### Dagster UI

```bash
make dagster-dev   # browse the asset graph at http://localhost:3000
```

### dbt Mesh

```bash
make dbt-build     # silver+gold transformations with enforced contracts
```

## CLI

After installing, the `mfg-mesh` command exposes the platform:

```
mfg-mesh status            # show catalog/Iceberg state
mfg-mesh ingest --count 500
mfg-mesh enforce
mfg-mesh index
mfg-mesh ask "What voltage anomalies preceded slowdowns in Texas?"
```

## Phase-by-Phase Mapping

* **Phase 1 — IT/OT Edge ingestion**: [`mfg_mesh/edge/opc_ua_simulator.py`](mfg_mesh/edge/opc_ua_simulator.py), [`mfg_mesh/edge/kafka_transport.py`](mfg_mesh/edge/kafka_transport.py)
* **Phase 2 — Iceberg medallion + schema evolution**: [`mfg_mesh/lakehouse/`](mfg_mesh/lakehouse/)
* **Phase 3 — Dagster + dbt SLA enforcement**: [`mfg_mesh/orchestration/assets.py`](mfg_mesh/orchestration/assets.py), [`dbt_mfg_mesh/`](dbt_mfg_mesh/), [`mfg_mesh/quality/contracts.py`](mfg_mesh/quality/contracts.py)
* **Phase 4 — Agentic RAG troubleshooting**: [`mfg_mesh/rag/`](mfg_mesh/rag/)
* **Phase 5 — FinOps & defensive hardening**: [`mfg_mesh/security.py`](mfg_mesh/security.py) + try/finally patterns throughout `mfg_mesh/quality/contracts.py`

## License

Apache-2.0
