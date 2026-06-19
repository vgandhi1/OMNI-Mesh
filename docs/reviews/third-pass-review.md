# OMNI-Mesh — Review (3rd pass)

Latest review of the `OMNI-Mesh/` codebase: gaps, issues, and improvement opportunities.
Prior passes live in [`docs/reviews/`](./docs/reviews/).

## Resolved since the prior passes

- **Gateway covers all five profiles.** `streaming_gateway/gateway.py` `_PROFILE_METRIC` now has
  entries for ROBOTICS / MANUFACTURING / HEALTH_TECH / COMMERCIAL / CLINICAL plus a
  `_DEFAULT_METRIC` fallback (`.get(profile, _DEFAULT_METRIC)`), so a new profile can no longer
  `KeyError`. A parametrized `test_every_profile_builds_a_labeled_frame` locks it to the registry.
- **Frontend covers all five profiles.** `frontend_cockpit/src/types.ts` and `config/profiles.ts`
  (`PROFILE_UI` / `PROFILES`) now list all five domains.
- **Docs reconciled.** `docs/ARCHITECTURE.md` is honest ("as built", simulated vs. not-built called
  out); README and the architecture doc document all five profiles.
- **Logging is clean.** All log statements emit counts/IDs/identifiers only — no payloads, rows, or
  salts (compliant with the logging rules).

## Issues

### 1. Security — `.env.example` salt bypasses the fail-closed guard
The shipped placeholder is `OMNI_MESH_MASKING_SALT=replace-with-a-strong-32char-secret`. The guard
in `data_platform/governance.py` only rejects exact `INSECURE_DEFAULTS` and the `replace-me` prefix:

```python
if salt in INSECURE_DEFAULTS or salt.startswith("replace-me"):
    raise InsecureConfigurationError(...)
```

`replace-with-a-strong-32char-secret` does not start with `replace-me`, is not in the set, and is
35 chars (> 16) — so it **passes** as a "valid" salt. A user who runs `cp .env.example .env` and
forgets to edit it operates on a publicly-known placeholder, defeating the purpose of the guard.
**Fix:** broaden the prefix check to `"replace-"` (or add the literal placeholder to
`INSECURE_DEFAULTS`), and add a regression test — the suite does not currently cover this string.

### 2. `requirements.txt` ↔ `pyproject.toml` drift
`requirements.txt` still lists `opentelemetry-api` / `opentelemetry-sdk` (not in `pyproject.toml`
and unused anywhere in source), and folds `pytest` / `pytest-cov` into runtime deps while
`pyproject` keeps them under `[dev]`. Two diverging sources of truth. Make `pyproject.toml`
authoritative (delete or generate `requirements.txt`), and drop the dead OTel deps unless spans are
actually implemented.

### 3. No CI / lint / type-check / format automation
No `.github/`, `.gitlab-ci.yml`, `ruff`/`mypy`/`black`, or `.pre-commit-config.yaml`. The docs and
`CLAUDE.md` lean on "loop until tests pass," but nothing runs pytest, `dbt build`, or the frontend
`tsc` on push/PR. Biggest gap for a portfolio-grade reference platform.

### 4. The cockpit has zero tests
`frontend_cockpit/package.json` defines only `dev`/`build`/`preview` — no test runner. The store's
`ingestFrame` reducer and the `useTelemetry` reconnect logic warrant a couple of Vitest tests.

## Smaller gaps / drift

- **`.env.example` comment is stale** — lists only `ROBOTICS | MANUFACTURING | HEALTH_TECH`
  (missing `COMMERCIAL | CLINICAL`).
- **`orchestration/definitions.py` docstring** names only three of five profiles.
- **README "48 passing"** is a hardcoded count that drifts; prefer "the suite covers …" with no number.
- **No Python dependency lockfile** — only ranges (the committed `package-lock.json` on the frontend
  is good; the Python side has no `uv.lock`/pip-tools lock for reproducibility).

## Code smells (low priority)

- **`ProfileSwitcher` is a no-op for the live stream.** Clicking a pill calls `initializeUI`, but the
  next gateway frame re-syncs `currentProfile` to the server's profile, so labels flash then snap
  back. Make it a read-only legend, or wire real switching (e.g. gateway accepts `?profile=`).
- **`get_settings_count()`** returns a hardcoded `64` despite its name — make it a module constant
  (e.g. `DEMO_INGEST_ROWS`).
- **`_synthetic_signal` doesn't branch for COMMERCIAL/CLINICAL** (falls through to the HEALTH_TECH
  distribution ≈ 55), so an empty lakehouse yields a nonsensical "mean_monthly_revenue" ≈ 55. Only
  matters before any ingest.
- **`no_sensitive_columns` macro** matches `table_name` without `table_schema`; safe today due to
  per-profile DuckDB isolation, but `and lower(table_schema) = lower('{{ model.schema }}')` hardens it.
- **`mask()`** truncates the HMAC to 16 hex chars (64-bit) and returns `""` for empty input —
  acceptable at demo scale, flagged for completeness.
- **`publish_to_iceberg`** uses unqualified `SELECT * FROM "{name}"`; safe due to per-profile
  isolation, minor.

## Highest-value improvements, in order

1. Fix the `.env.example` / salt-guard bypass (**security**) and add a regression test.
2. Add CI (pytest + `dbt build` smoke + frontend `tsc`) and a `ruff`/`mypy` config.
3. Reconcile `requirements.txt` with `pyproject.toml`; drop the dead OTel deps (or implement OTel
   spans, since the architecture pitches observability).
4. Add a handful of frontend tests; make the profile switcher honest (legend) or functional.

## Net

The data-platform core is solid and the five-profile consistency gaps from earlier passes are
closed. Remaining work is mostly **engineering hygiene** (a real security fix for the salt
placeholder, CI, dependency single-source-of-truth, and frontend tests) rather than architecture.
