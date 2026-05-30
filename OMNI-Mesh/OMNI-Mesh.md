# **OMNI-Mesh: The Universal Full-Stack Cyber-Physical Data Mesh Platform**

### **Enterprise Reference Architecture & Polymorphic Implementation Guide**

```
                         ┌───────────────────────────────┐
                         │      OMNI_MESH_PROFILE         │
                         └───────────────┬───────────────┘
                                         │
        ┌──────────────┬─────────────────┼─────────────────┬──────────────┐
        ▼              ▼                 ▼                 ▼              ▼
  [ ROBOTICS ]  [ MANUFACTURING ]  [ HEALTH_TECH ]   [ COMMERCIAL ]  [ CLINICAL ]
  VLA Kinematics  OPC UA + PLC      HIPAA Biometrics   CLV / Churn     eCRF / PHI
   + Video        Registers                            Subscriptions   (de-identified)
        │              │                 │                 │              │
        └──────────────┴─────────────────┼─────────────────┴──────────────┘
                                         ▼
                   ┌──────────────────────────────────────────┐
                   │   Universal Apache Iceberg v2 Lakehouse   │
                   ├──────────────────────────────────────────┤
                   │   Polymorphic dbt Contracts + DQ Tests    │
                   ├──────────────────────────────────────────┤
                   │   Throttled 30Hz WebSocket Gateway        │
                   ├──────────────────────────────────────────┤
                   │   Dynamic React 18 Operator Cockpit       │
                   └──────────────────────────────────────────┘
```

> **Implementation status.** This document describes the architecture *as built*. The
> shared backend, the polymorphic dbt project (with enforced contracts), the Dagster
> graph, the VLA flywheel, the Starlette streaming gateway, and the React cockpit all
> exist and are exercised by the test suite. Where something is intentionally simulated
> (e.g. the 500Hz source is replayed from the lakehouse, not produced by real hardware)
> or not yet built (the containerized chaos stack in §6), it is called out explicitly.

## **🚀 1. Strategic Business Value**

**OMNI-Mesh** is a first-principles reference platform designed to solve the foundational bottleneck in Physical AI: **the data-scarce, high-latency gap between physical hardware and digital brains.** While traditional enterprise data architectures process tabular rows hourly, a cyber-physical environment produces chaotic, multi-modal high-frequency streams (waveforms, kinematics) combined with heavy visual fields.

By abstracting domain structures into a runtime profile matrix (ROBOTICS, MANUFACTURING, HEALTH\_TECH, COMMERCIAL, or CLINICAL), OMNI-Mesh implements a universal data architecture framework. Adding a domain is a single `ProfileSpec` registry entry plus one dbt `models/<profile>/` folder.

### **Why this is a Staff-Level Portfolio Asset:**

* **Zero Cross-Cloud Duplication:** Machine learning researchers (Databricks) and hardware analytics teams (Snowflake/BigQuery) query identical, un-replicated data objects simultaneously via **Apache Iceberg v2 open tables**.
* **Decoupled Render Streams:** High-velocity 500Hz hardware data is throttled at the API layer to a stable **30Hz WebSocket stream**, eliminating browser layout thrashing and leaving the main UI thread unblocked.
* **Audit-Hardened Edge Controls:** Directly eliminates critical enterprise data vulnerabilities, including multi-worker database time-of-check to time-of-use (TOCTOU) races, process-scoped cache leaks, loose substring-matching in RAG pipelines, and insecure fallback salts.
* **Governed Medallion:** Every Silver/Gold model is **contract-enforced** in dbt, and a custom singular test fails the build if a sensitive identifier (PHI, customer id, robot serial) ever leaks into a Gold product.

## **🏗️ 2. Repository Topography**

```
OMNI-Mesh/
├── config/                       # Unified global state & profile management
│   ├── profiles.py               # MeshProfile enum + frozen ProfileSpec REGISTRY (5 domains)
│   └── settings.py               # Frozen Settings; per-profile path isolation under <data_root>/<profile>/
├── data_platform/                # Core storage & transformation fabric
│   ├── catalog.py                # TOCTOU-safe functional Iceberg writer (write_data_product)
│   ├── governance.py             # Keyed HMAC masking & fail-closed security barriers
│   ├── generators.py             # Minimal per-profile synthetic Bronze
│   ├── medallion.py              # Export Bronze→parquet, dbt build, publish Silver/Gold to Iceberg
│   ├── finops.py                 # Per-data-product cost from dbt run_results.json
│   ├── policies.py               # Profile-aware RLS/masking SQL (snowflake|databricks|bigquery)
│   ├── ai_readiness/
│   │   ├── search.py             # Word-boundary, vocab-driven RAG with strict resource protection
│   │   └── vector_store.py       # ChromaDB client + embedding-model drift guard
│   └── vla/                      # feature_extractor, shards, closed_loop (ROBOTICS flywheel)
├── dbt/                          # One polymorphic dbt-duckdb project
│   └── models/<profile>/         # Silver + Gold + _schema.yml (contracts + DQ + no-PHI tests)
│   └── macros/                   # no_sensitive_columns generic test
├── orchestration/
│   └── definitions.py            # Profile-aware Dagster assets
├── streaming_gateway/
│   └── gateway.py                # Starlette sliding-window downsampler (500Hz ➔ 30Hz)
├── frontend_cockpit/             # React 18 + Vite + TS + Zustand + Recharts
│   └── src/{components,store,hooks}/
├── cli.py                        # Unified `omni-mesh` Typer CLI
└── tests/                        # Isolation & contract testing suite (conftest purges every cache)
```

## **🛠️ 3. Full-Stack Implementation Blueprints**

### **Phase 1: Dynamic Profiles & Schema Matrix**

Changing a single environment variable (`OMNI_MESH_PROFILE`) rewrites data boundaries, validations, masking targets, and RAG vocabulary across the entire platform. The registry is a frozen dataclass, not a class hierarchy — adding a domain is one entry.

```python
# config/profiles.py
import enum
from dataclasses import dataclass
import pyarrow as pa

class MeshProfile(enum.Enum):
    ROBOTICS = "ROBOTICS"
    MANUFACTURING = "MANUFACTURING"
    HEALTH_TECH = "HEALTH_TECH"
    COMMERCIAL = "COMMERCIAL"      # subscription CLV / churn (restored heal-mesh sub-domain)
    CLINICAL = "CLINICAL"          # de-identified eCRF / PHI (restored heal-mesh sub-domain)

@dataclass(frozen=True)
class ProfileSpec:
    profile: MeshProfile
    bronze_table: str
    silver_schema: pa.Schema
    sensitive_columns: tuple[str, ...]      # masked via governance.mask + asserted out of Gold
    rag_vocab: dict[str, tuple[str, ...]]   # metadata-field -> allowed terms (\b extraction)
    chroma_collection: str

_HEALTH_TECH = ProfileSpec(
    profile=MeshProfile.HEALTH_TECH,
    bronze_table="wearable_biometrics",
    silver_schema=pa.schema([
        ("timestamp", pa.timestamp("us")),
        ("patient_id_hashed", pa.string()),
        ("heart_rate_variability", pa.int32()),
        ("sleep_efficiency", pa.float32()),
        ("region", pa.string()),
    ]),
    sensitive_columns=("patient_id_hashed",),
    rag_vocab={"region": ("NA", "EU", "APAC")},
    chroma_collection="health_cohort_narratives",
)

REGISTRY: dict[MeshProfile, ProfileSpec] = { ... }   # one entry per domain

def get_active_profile() -> MeshProfile:
    raw = os.getenv("OMNI_MESH_PROFILE", "ROBOTICS").strip().upper()
    return MeshProfile[raw]

def active_spec() -> ProfileSpec:
    return REGISTRY[get_active_profile()]
```

### **Phase 2: Hardened Catalog & TOCTOU Prevention**

The catalog is a set of functions over a per-profile-cached `SqlCatalog`. Writes are atomic: if two workers both see a table missing, the loser of the `create_table` race reloads and appends instead of crashing. Batches are projected onto the target schema (null-filling missing columns) so an append never corrupts an existing Iceberg table.

```python
# data_platform/catalog.py
from pyiceberg.exceptions import NoSuchTableError, TableAlreadyExistsError

def write_data_product(namespace, table_name, batch, *, expected_schema=None, overwrite=False) -> int:
    catalog = get_catalog()
    ensure_namespaces([namespace])
    identifier = f"{namespace}.{table_name}"
    batch = _as_table(batch)
    if expected_schema is not None and not batch.schema.equals(expected_schema, check_metadata=False):
        batch = _align_batch(batch, expected_schema)   # enforce the structural contract

    try:
        table = catalog.load_table(identifier)
    except NoSuchTableError:
        try:
            table = catalog.create_table(identifier, schema=batch.schema)
        except TableAlreadyExistsError:           # concurrent worker beat us — recover
            table = catalog.load_table(identifier)

    aligned = _align_batch(batch, table.schema().as_arrow())
    table.overwrite(aligned) if overwrite else table.append(aligned)
    return aligned.num_rows
```

### **Phase 3: Universal Fail-Closed Compliance Masking**

If the masking salt is missing, a known placeholder, or too short, execution halts rather than processing data with un-hashed visibility. Masking is a **deterministic keyed-HMAC-SHA256** token, so masked identifiers stay valid join keys across the lakehouse; a privileged role can read plaintext.

```python
# data_platform/governance.py
import hmac, hashlib, os
from functools import lru_cache

_MIN_SALT_LEN = 16
INSECURE_DEFAULTS = frozenset({"", "local-dev-placeholder", "replace-me", "changeme",
                               "robomesh-local-dev-salt", "test", "secret", ...})

def assert_platform_secrets() -> None:
    salt = os.getenv("OMNI_MESH_MASKING_SALT", "").strip()
    if not salt:
        raise InsecureConfigurationError("CRITICAL COMPLIANCE BREACH: salt unset. Halting.")
    if salt in INSECURE_DEFAULTS or salt.startswith("replace-me"):
        raise InsecureConfigurationError("CRITICAL: salt is a known insecure placeholder.")
    if len(salt) < _MIN_SALT_LEN:
        raise InsecureConfigurationError(f"CRITICAL: salt must be >= {_MIN_SALT_LEN} chars.")

@lru_cache(maxsize=1)
def _salt_bytes() -> bytes:
    assert_platform_secrets()
    return os.getenv("OMNI_MESH_MASKING_SALT", "").strip().encode("utf-8")

def mask(plaintext, *, role=None, unmask_role=None, length=16):
    if plaintext is None or plaintext == "":
        return plaintext
    if unmask_role is not None and role == unmask_role:
        return plaintext                       # privileged read
    digest = hmac.new(_salt_bytes(), plaintext.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"masked_sha256:{digest[:length]}"
```

**Governed at the warehouse layer too.** Each dbt Silver/Gold model is `contract: enforced: true`
with explicit column `data_type`s, plus `not_null` / `unique` / `accepted_values` data tests. A
custom generic test (`dbt/macros/test_no_sensitive_columns.sql`) is attached to every Gold model
and **fails the build** if a forbidden identifier appears in the Gold schema — restoring
heal-mesh's `no_raw_phi_columns_in_gold` guard, generalized per profile:

```yaml
# dbt/models/clinical/_schema.yml
  - name: gold_study_safety
    config: { contract: { enforced: true } }
    data_tests:
      - no_sensitive_columns:
          forbidden: ["patient_id_hashed", "patient_id", "mrn", "ssn", "dob", "email", "full_name"]
```

### **Phase 4: Universal Sliding-Window Ingestion Middleware**

The gateway replays the active profile's high-frequency channel from the lakehouse, batches
`SAMPLES_PER_FRAME` (≈17) samples over a sliding window, and flushes one downsampled payload to
WebSocket clients at a stable 30Hz. Aggregation adapts to the profile. Built on **Starlette**
(FastAPI's ASGI core), which the dagster-webserver already pulls in — no extra heavyweight dep.

> The 500Hz figure describes the *downsampling ratio* (500/30 ≈ 17 samples per frame). The source
> is a finite lakehouse/synthetic array cycled with `itertools.cycle`, not a live hardware producer.
>
> The gateway (and the cockpit) cover the three high-frequency **hardware** domains in
> `_PROFILE_METRIC` below. The two batch domains — COMMERCIAL and CLINICAL — flow through the
> data platform (medallion → RAG → governance) and are not wired into the live telemetry stream;
> streaming them would require adding a `_PROFILE_METRIC` entry and a signal source.

```python
# streaming_gateway/gateway.py
from starlette.applications import Starlette
from starlette.routing import Route, WebSocketRoute

HF_HZ, RENDER_HZ = 500, 30
SAMPLES_PER_FRAME = max(1, round(HF_HZ / RENDER_HZ))   # ≈ 17
_PROFILE_METRIC = {
    MeshProfile.ROBOTICS:      ("peak_torque_nm", "max"),
    MeshProfile.MANUFACTURING: ("mean_voltage_v", "mean"),
    MeshProfile.HEALTH_TECH:   ("mean_hrv_ms",    "mean"),
}

class SlidingWindowBuffer:
    def process_frame(self, profile) -> dict:
        label, mode = _PROFILE_METRIC[profile]
        if not self._points:
            return {"profile": profile.value, "label": label, "metric_value": 0.0, "status": "idle"}
        array = np.asarray(self._points); self._points.clear()
        value = float(array.max() if mode == "max" else array.mean())
        return {"profile": profile.value, "label": label,
                "metric_value": round(value, 4), "sample_count": int(array.size), "status": "streaming"}

async def _telemetry(websocket):
    await websocket.accept()
    profile = get_active_profile()
    source = itertools.cycle(load_signal_values(profile))
    buffer = SlidingWindowBuffer()
    while True:
        await asyncio.sleep(1.0 / RENDER_HZ)               # strict 30Hz cadence
        for _ in range(SAMPLES_PER_FRAME):
            buffer.log_metric(next(source))
        await websocket.send_json(buffer.process_frame(profile))

app = Starlette(routes=[
    Route("/health", _health), Route("/profile", _profile),
    WebSocketRoute("/ws/telemetry", _telemetry),
])
```

### **Phase 5: Low-Latency Frontend Operator Canvas & Zustand Engine**

The presentation layer (`frontend_cockpit/`) decouples rapid streaming visual arrays from standard
React rendering. A Zustand store holds *low-speed* dashboard state and a *bounded 30Hz* metric
history; the camera canvas is driven via `requestAnimationFrame` off a ref (not React state) so
high-frequency repaints never trigger component re-renders. The snippets below are representative
of `src/store/cockpitStore.ts` and `src/components/CameraFeed.tsx`.

```typescript
// src/store/cockpitStore.ts (representative)
import { create } from 'zustand';

// The cockpit renders the three streaming hardware profiles (mirrors the gateway).
type AppProfile = 'ROBOTICS' | 'MANUFACTURING' | 'HEALTH_TECH';

interface UniversalUIState {
  currentProfile: AppProfile;
  primaryPanelTitle: string;
  gaugeLabel: string;
  hardwareStatus: 'AUTONOMOUS' | 'ALERT_PENDING' | 'TELEOPERATION' | 'SAFE_STOP';
  // The UI re-syncs profile + labels from each incoming frame's `profile` field.
  initializeUI: (profile: AppProfile) => void;
}
```

```typescript
// src/components/CameraFeed.tsx (representative)
// Predictive lag-compensation: extrapolate the bounding box forward by network latency,
// painted on an HTML5 Canvas via requestAnimationFrame so it never blocks the React tree.
const latencyOffsetFactor = estimatedNetworkDelayMs * 0.45;
const predictedX = currentBoundingBox.x + latencyOffsetFactor;     // dashed yellow overlay
```

### **Phase 6: Advanced Word-Boundary RAG Engine**

The RAG layer is **vocabulary-driven**: entity terms come from the active `ProfileSpec.rag_vocab`,
not a hardcoded region list, so the same engine works for every domain. It uses `\b` word
boundaries to eliminate substring errors (`"eu"` inside `"revenue"`), and the DuckDB join that
enriches results registers the Arrow table and uses **parameterized** SQL inside a `try/finally`.

```python
# data_platform/ai_readiness/search.py
import re, duckdb

def extract_filters(query: str) -> dict[str, str]:
    spec = active_spec()
    filters = {}
    for field_name, terms in spec.rag_vocab.items():
        for term in terms:
            if re.search(rf"\b{re.escape(term)}\b", query, re.IGNORECASE):
                filters[field_name] = term
                break
    return filters

def _join_lakehouse(spec, filters) -> list[dict]:
    arrow = catalog.read_table_arrow(f"{catalog.NAMESPACE_BRONZE}.{spec.bronze_table}")
    connection = duckdb.connect()
    try:
        connection.register("t", arrow)
        sql, params = "SELECT * FROM t", []
        if filters:
            sql += " WHERE " + " AND ".join(f"{c} = ?" for c in filters)  # parameterized
            params = list(filters.values())
        cursor = connection.execute(sql + " LIMIT 20", params)
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, rec)) for rec in cursor.fetchall()]
    finally:
        connection.close()                                  # release locks on every path
```

## **🧪 4. Testing & Verification Lifecycle**

Pytest runs the whole suite in one process, so every cached singleton (settings, salt, catalog,
Chroma client) is purged between tests or monkeypatched env vars would leak. The autouse fixture
also provides a valid salt and a per-test temp data root.

```python
# tests/conftest.py
import pytest

def _clear_caches() -> None:
    from config import settings
    from data_platform import catalog, governance
    from data_platform.ai_readiness import vector_store
    settings.get_settings.cache_clear()
    governance.reset_secret_cache()
    catalog.reset_catalog_cache()
    vector_store.reset_client_cache()

@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("OMNI_MESH_MASKING_SALT", "unit-test-salt-1234567890")
    monkeypatch.setenv("OMNI_MESH_DATA_ROOT", str(tmp_path / "omni"))
    monkeypatch.setenv("OMNI_MESH_PROFILE", "ROBOTICS")
    _clear_caches()
    yield
    _clear_caches()
```

## **🛠️ 5. Deployment Playbook**

The platform runs locally as a Python package with the `omni-mesh` CLI — no container stack is
required (and none is committed yet; see §6).

```bash
# Install the system core (editable)
cd OMNI-Mesh
python -m venv .venv && source .venv/bin/activate
pip install -e .                      # add: pip install -e '.[dev]' for pytest
#   optional heavy ML path (torchvision/webdataset/ray): pip install -r requirements-ml.txt

# A real masking salt is mandatory — the platform fails closed without one
export OMNI_MESH_MASKING_SALT="$(openssl rand -hex 24)"

# Select the operational profile and run the full chain (ingest -> dbt -> index -> ask)
export OMNI_MESH_PROFILE=ROBOTICS      # or MANUFACTURING | HEALTH_TECH | COMMERCIAL | CLINICAL
omni-mesh doctor                       # show config + salt status (never prints the salt)
omni-mesh demo                         # ingest -> enforce (dbt medallion) -> index -> ask

# Stream telemetry + drive the cockpit
omni-mesh gateway --host 127.0.0.1 --port 8000     # 500Hz->30Hz WebSocket
(cd frontend_cockpit && npm install && npm run dev) # VITE_GATEWAY_WS targets the gateway

# Orchestrate the whole graph
omni-mesh orchestrate                  # in-process Dagster run
dagster dev -m orchestration.definitions   # or the Dagster UI

# Verification suite (contracts + DQ tests run as part of `dbt build`)
pytest -q
```

## **📈 6. The "Chaos Engineering" Runbook (Conceptual / Planned)**

> **Not yet wired up.** The containerized chaos stack (a `docker-compose.yml` plus a Toxiproxy
> sidecar in front of the gateway) is future work — there is no compose file or Dockerfile in the
> repo today. The sequence below is the *intended* operator-resilience demonstration; until the
> stack lands, latency can be simulated by adding a delay in the gateway's send loop.

1. **Steady State:** The React Operator Cockpit shows telemetry flowing over the WebSocket gateway
   smoothly at 30Hz, with the UI layout thread unblocked.
2. **Trigger Chaos (planned):** Inject latency into the gateway via the Toxiproxy sidecar, e.g.
   `toxiproxy-cli toxic add omni-mesh-gateway -t latency -a latency=250`.
3. **Observe Automated Adaptation:**
   * **Dynamic UI:** the latency indicator flips to a red warning state.
   * **Lag Matrix:** the Canvas overlay shifts its yellow predictive bounding box further forward,
     using the velocity vector to keep the operator synchronized despite camera latency.
   * **Data Layer:** the ingest path keeps writing to Iceberg without dropping packets.

## **📊 7. Strategic Interview Presentation Matrix**

| Target Company Sector | Launch Setting Profile | Strategic Technical Talking Point |
| :---- | :---- | :---- |
| **Humanoid Robotics** | `OMNI_MESH_PROFILE=ROBOTICS` | *"The platform aligns multi-modal data at the Silver dbt layer, pairing kinematic joint states with visual camera-frame URIs before feeding the frozen-ResNet VLA flywheel (`gold.vla_episodes`) and a closed-loop inference logger."* |
| **Tesla Energy** | `OMNI_MESH_PROFILE=MANUFACTURING` | *"The ingestion manager applies atomic table-creation checks to stop concurrent TOCTOU race conditions, so multiple factory-floor IoT streams write to the same namespace simultaneously without crashing."* |
| **Oura / Wearables** | `OMNI_MESH_PROFILE=HEALTH_TECH` | *"A fail-closed keyed-HMAC tokenization barrier freezes ingestion if production secrets are missing, and a dbt build-breaking test guarantees no patient identifier ever reaches a Gold cohort table."* |
| **Subscription / SaaS** | `OMNI_MESH_PROFILE=COMMERCIAL` | *"The same engine models CLV and churn — Gold rolls up per-plan churn rate and lifetime value with the raw customer id contract-guarded out of the de-identified product."* |
| **Clinical Trials / CRO** | `OMNI_MESH_PROFILE=CLINICAL` | *"De-identified eCRF observations roll up to per-study adverse-event rates using a pre-computed age bracket — age is never derived from a raw birth date, and PHI is asserted out of Gold."* |
