# HEAL-Mesh Phase 3 — Federated Governance & HIPAA Hardening

This directory contains the cross-cloud governance artifacts that implement
the blueprint's Phase 3 requirements:

| File | Purpose | Target platform |
| --- | --- | --- |
| `../domains/clinical/dbt/macros/phi_mask.sql` | SHA-256 + salt PHI masking macro reused by every clinical silver/gold model | dbt-mesh (portable) |
| `policies/snowflake_row_level_security.sql` | Row-access + column-masking policies | Snowflake |
| `policies/databricks_unity_catalog.sql` | Unity Catalog grants + dynamic view | Databricks |
| `policies/bigquery_column_security.sql` | Policy-tag-based column-level access controls | BigQuery |

## Role contract

The blueprint defines three principal personas; the artifacts above implement
them consistently across all three warehouses.

| Role | Bronze PHI | Silver hashed PHI | Gold aggregates | Notes |
| --- | --- | --- | --- | --- |
| `DATA_GOVERNANCE_ADMIN` | read | read | read | break-glass auditor |
| `CLINICAL_RESEARCHER`   | read (per consented study) | read | read | restricted to active studies |
| `BUSINESS_ANALYST`      | denied | denied | read | only de-identified aggregates |
| `AI_PIPELINE_SA`        | denied | read (hashes only) | read | service account |

## Salt management

`HEAL_MESH_PHI_SALT` must come from a managed secret store. The included dbt
macro refuses to render if the placeholder value is still in use, which
prevents accidental "predictable hash" deployments. Rotate the salt on the
cadence defined by your HIPAA program; rotation will invalidate all derived
surrogate keys so plan a coordinated re-hash + re-index for the downstream
vector store.

## Verifying the contract

The clinical dbt project ships a singular test
(`tests/no_raw_phi_columns_in_gold.sql`) that fails CI if any raw PHI column
ever appears in a gold artifact. Run it with:

```bash
cd domains/clinical/dbt
../../../.venv/bin/dbt test --select test_type:singular --profiles-dir .
```
