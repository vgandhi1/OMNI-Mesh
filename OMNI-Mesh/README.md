# OMNI-Mesh

Universal **polymorphic** cyber-physical data mesh. A single codebase runs as five
domains — **ROBOTICS**, **MANUFACTURING**, **HEALTH_TECH**, **COMMERCIAL** (subscription
CLV/churn), and **CLINICAL** (de-identified eCRF/PHI) — selected by the `OMNI_MESH_PROFILE`
environment variable. This consolidates the formerly separate `MFG-Mesh`, `RoboMesh`, and
`heal-mesh` projects, which each re-implemented the same data-mesh skeleton; COMMERCIAL and
CLINICAL restore the two heal-mesh sub-domains as first-class profiles. Adding a domain is one
`ProfileSpec` registry entry plus one dbt `models/<profile>/` folder.

See [`OMNI-Mesh.md`](./OMNI-Mesh.md) for the full reference architecture.

## Built so far

**Phase 1 — backend core** (the shared skeleton the three projects duplicated):

| Module | Responsibility |
| --- | --- |
| `config/profiles.py` | `MeshProfile` enum + `ProfileSpec` registry (per-domain schema, masking targets, RAG vocab) |
| `config/settings.py` | Frozen `Settings` singleton; per-profile path isolation |
| `data_platform/governance.py` | Fail-closed salt assertion + keyed HMAC-SHA256 masking + role unmask |
| `data_platform/catalog.py` | TOCTOU-safe Iceberg writes + schema-align append |
| `data_platform/generators.py` | Minimal synthetic Bronze per profile |
| `data_platform/ai_readiness/` | ChromaDB vector store + `\b` word-boundary RAG with DuckDB join |
| `cli.py` | Unified `omni-mesh` CLI |

**Phase 2 — dbt medallion + Dagster:**

| Module | Responsibility |
| --- | --- |
| `dbt/` | One polymorphic dbt-duckdb project; `models/<profile>/` Silver+Gold, selected at build via `--select path:models/<profile>` |
| `dbt/models/<profile>/_schema.yml` | `contract: enforced: true` on every Silver/Gold model + `not_null`/`unique`/`accepted_values` data tests |
| `dbt/macros/test_no_sensitive_columns.sql` | Generic test attached to each Gold model — **fails the build** if a sensitive identifier (PHI, customer id, robot serial) leaks into Gold |
| `data_platform/medallion.py` | Export Bronze→parquet, run `dbt build`, publish Silver/Gold back into Iceberg |
| `orchestration/definitions.py` | Profile-aware Dagster assets: `bronze_ingest → bronze_parquet → dbt_medallion → semantic_index → rag_smoke` |

Run the medallion with `omni-mesh enforce`; run the whole graph in-process with
`omni-mesh orchestrate`, or interactively with `dagster dev -m orchestration.definitions`.

**Phase 3 — VLA flywheel, FinOps, governance policies:**

| Module | Responsibility |
| --- | --- |
| `data_platform/vla/feature_extractor.py` | CV embeddings → `gold.vla_episodes` (torchvision ResNet18, else numpy/SHA-256 fallback) |
| `data_platform/vla/shards.py` | Pre-shuffled WebDataset `.tar` training shards (stdlib tarfile fallback) |
| `data_platform/vla/closed_loop.py` | Score deployed-policy inference back into `bronze.live_inference` |
| `data_platform/finops.py` | Per-data-product cost attribution from dbt `run_results.json` |
| `data_platform/policies.py` | Profile-aware RLS/masking SQL for Snowflake / Databricks / BigQuery |

ML extras are optional — install `requirements-ml.txt` (torch, torchvision, webdataset,
ray) for the real ResNet/WebDataset/Ray paths; everything runs without them via fallbacks.
New commands: `omni-mesh vla` / `shards` / `closed-loop` (ROBOTICS), `finops`, `governance --dialect <cloud>`.

**Phase 4 — 500Hz→30Hz streaming gateway (`streaming_gateway/`):**

A Starlette (FastAPI's ASGI core) app that replays the active profile's high-frequency
lakehouse signal, batches it over a sliding window, and flushes a downsampled payload to
WebSocket clients at a steady 30Hz (17 samples/frame). The aggregation adapts to the profile:
ROBOTICS → peak torque (max), MANUFACTURING → mean voltage, HEALTH_TECH → mean HRV.

> The live gateway + cockpit cover the three high-frequency **hardware** domains
> (ROBOTICS / MANUFACTURING / HEALTH_TECH). The two batch domains — COMMERCIAL and CLINICAL —
> run through the data platform (medallion → RAG → governance) but are not wired into the live
> telemetry stream (they have no high-frequency signal).

```bash
omni-mesh gateway --port 8000          # then connect to ws://127.0.0.1:8000/ws/telemetry
#   GET /health   -> {"status":"ok"}
#   GET /profile  -> active metric label + decimation ratio
```

> Built on Starlette rather than FastAPI to avoid downgrading the Dagster stack's `starlette`.

**Phase 5 — operator cockpit (`frontend_cockpit/`):**

React 18 + Vite + TypeScript + Zustand + Recharts. A polymorphic operator console that
consumes the gateway WebSocket: panel titles, gauge labels, and accent colour re-sync from
each frame's `profile`. Like the gateway, it renders the three streaming hardware profiles
(ROBOTICS / MANUFACTURING / HEALTH_TECH). The Canvas camera feed animates via `requestAnimationFrame` off a ref
(not React state) with a dashed predictive bounding box extrapolated by injected latency — the
"dual-speed" decoupling. See `frontend_cockpit/README.md`.

```bash
cd frontend_cockpit && npm install && npm run dev   # http://localhost:5173
# start a gateway in another terminal: omni-mesh gateway
```

All five build phases are complete: ingest → Iceberg → dbt medallion → Dagster → VLA flywheel
→ FinOps/governance → 500Hz→30Hz gateway → React cockpit, all driven by `OMNI_MESH_PROFILE`.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export OMNI_MESH_MASKING_SALT="a-strong-32char-secret-please-change"

for P in ROBOTICS MANUFACTURING HEALTH_TECH COMMERCIAL CLINICAL; do
  export OMNI_MESH_PROFILE=$P
  omni-mesh doctor      # config + salt status (never prints the salt)
  omni-mesh ingest      # write a Bronze Iceberg table
  omni-mesh enforce     # contract-enforced Silver + Gold medallion build
  omni-mesh index       # embed chunks into ChromaDB (downloads embedding model)
  omni-mesh ask "show EU failures"
done
```

> `index` / `ask` download a sentence-transformers model on first run (needs network).
> `doctor` / `ingest` / `enforce` work fully offline.

## Tests

```bash
pytest -q       # 48 passing
```

Covers fail-closed salt handling, the Iceberg TOCTOU race-lost path, per-profile
schema conformance, word-boundary RAG extraction (so `EU` never matches `revenue`),
the full medallion build for all five profiles, and the no-PHI-in-Gold contract guard.
