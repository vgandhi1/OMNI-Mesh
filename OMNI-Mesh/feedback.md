# OMNI-Mesh — High-Level Review (2nd pass)

A re-review of `OMNI-Mesh/` (docs, backend core, dbt, orchestration, gateway, frontend)
compared against the three projects it consolidates and replaces: `heal-mesh/`,
`MFG-Mesh/`, and `RoboMesh/`.

> This update supersedes the first review. Two of the earlier top findings have been
> resolved; the recent expansion to **five** profiles introduced new consistency gaps
> that are now the highest-priority items.

## Verdict

`OMNI-Mesh` remains a strong consolidation, and it has gotten meaningfully better since the
first pass. The core thesis — collapse the near-identical per-project "data-mesh skeletons"
into **one polymorphic codebase switched by `OMNI_MESH_PROFILE`** — is executed cleanly, the
shared core is genuinely generic, and the per-domain differences are isolated to a single
`ProfileSpec` registry. It also still goes beyond all three predecessors with the
**500Hz→30Hz streaming gateway** and the **React operator cockpit**.

The main thing holding it back now is **internal consistency**: the registry grew from 3 to 5
profiles, but the gateway, the frontend, and the docs were not all updated in lockstep.

## Resolved since the last review

- **dbt contracts + data-quality tests are back (was the #1 gap).** Every profile now has a
  `dbt/models/<profile>/_schema.yml` with `contract: enforced: true` plus
  `not_null` / `unique` / `accepted_values` tests. Crucially, heal-mesh's marquee
  "no raw PHI in gold" guard is restored and generalized as the
  `dbt/macros/test_no_sensitive_columns.sql` generic test, wired into `gold_study_safety`
  (and available to every gold model). This was the most important regression and it's
  now genuinely fixed.
- **Commercial + clinical domains restored (was the #3 gap).** `COMMERCIAL`
  (subscription CLV / churn) and `CLINICAL` (de-identified eCRF / PHI) are now first-class
  `MeshProfile`s with full schemas, synthetic generators, RAG vocab, and dbt silver/gold
  models. `config/profiles.py` now carries all five domains, so OMNI-Mesh actually covers
  what heal-mesh's three sub-domains did.

## Current issues (highest-value first)

1. **The streaming gateway crashes for the two new profiles.** `streaming_gateway/gateway.py`
   still defines `_PROFILE_METRIC` with only ROBOTICS / MANUFACTURING / HEALTH_TECH, and then
   indexes it directly: `label, mode = _PROFILE_METRIC[profile]` (lines ~66 and ~137). Under
   `OMNI_MESH_PROFILE=COMMERCIAL` or `CLINICAL`, both `GET /profile` and the
   `/ws/telemetry` stream raise `KeyError`. (`_SIGNAL_SOURCES.get(...)` and
   `_synthetic_signal` already fall back safely — only `_PROFILE_METRIC` is unguarded.)
   Add metric entries for the two new profiles (e.g. COMMERCIAL → mean monthly_revenue,
   CLINICAL → mean adverse-event rate) or make the lookup fall back to a default.

2. **The frontend cockpit was not extended to 5 profiles.** `frontend_cockpit/src/types.ts`
   still types `MeshProfile` as the original three, and `src/config/profiles.ts` defines
   `PROFILE_UI` / `PROFILES` for only those three. A COMMERCIAL/CLINICAL frame would hit an
   undefined `PROFILE_UI[frame.profile]` in the store. (Lower blast radius today only because
   issue #1 stops the gateway from ever emitting those frames.) Mirror all five profiles in
   the UI config to keep frontend and backend in sync.

3. **Test coverage doesn't lock the registry/gateway in lockstep.** `tests/test_profiles.py`
   correctly parametrizes over `list(MeshProfile)` (all five), which is why the schema side
   stays consistent. But `tests/test_gateway.py` only exercises the original three profiles,
   so the `_PROFILE_METRIC` KeyError in issue #1 slips through. A single parametrized test
   asserting `build_frame(p, [...])` returns a label for **every** `MeshProfile` would have
   caught it and would prevent the next profile addition from regressing.

4. **Doc drift (was #2) — now largely reconciled.** `README.md` and `OMNI-Mesh.md` now
   document all five profiles, the chaos/`docker-compose` stack is explicitly marked
   "Not yet wired up" (so it no longer promises infra that isn't in the repo), and both docs
   now state that the live gateway + cockpit cover only the three high-frequency hardware
   profiles. Remaining gap: there is still no actual `docker-compose.yml` / `Dockerfile` /
   `Makefile`, so the chaos runbook stays conceptual until that stack is added.

5. **Unused OpenTelemetry dependencies (was #4).** `opentelemetry-api` / `opentelemetry-sdk`
   are still declared in `pyproject.toml` but have no usage anywhere in the source tree
   (only inside `.venv`). heal-mesh had a real `otel.py`. Either wire up spans around the
   Dagster/dbt/gateway boundaries or drop the dead dependencies.

6. **Minor (unchanged):** the "500Hz" stream is replay-simulated — a finite lakehouse/synthetic
   array is cycled and `SAMPLES_PER_FRAME` points are logged per tick; the *downsampling* is
   real but there is no true high-frequency producer. And `mask()` truncates the HMAC to 16
   hex chars (64 bits) by default — fine at demo scale, slight collision risk as a strict
   join key at volume; `mask("")` returns `""`. All acceptable, just flagging.

## Suggested priorities

1. Fix the gateway `_PROFILE_METRIC` gap for COMMERCIAL/CLINICAL (and add the parametrized
   all-profiles gateway test from issue #3).
2. Extend the frontend `MeshProfile` type + `PROFILE_UI` / `PROFILES` to all five profiles.
3. (Docs reconciled.) If the chaos runbook matters, ship the actual docker-compose / toxiproxy
   stack; otherwise the conceptual framing now in `OMNI-Mesh.md` is fine.
4. Drop unused OTel deps or wire up real spans.

## Net

The data-platform core is now in good shape — the governance/contract story that the first
review flagged is genuinely restored, and the domain coverage matches the predecessors. The
remaining work is consistency plumbing: the gateway, the cockpit, the tests, and the docs all
need to catch up to the fact that OMNI-Mesh is now a **five-profile** platform, not three.
