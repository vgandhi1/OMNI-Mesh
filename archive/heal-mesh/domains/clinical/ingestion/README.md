# Clinical Domain · Ingestion

In production this directory holds the secure sync jobs that land eCRF / EHR
metadata into the Iceberg bronze table
`clinical_domain.ecrf_patients_bronze` inside the locked-down clinical bucket.

Typical artifacts:

| File | Purpose |
| --- | --- |
| `ecrf_secure_sync.py` | mTLS-authenticated sync from the eCRF vendor |
| `hl7_fhir_loader.py` | HL7 FHIR resource ingest with PHI tagging |
| `consent_audit_check.py` | Pre-load consent verification (drops rows without active consent) |

In the local reference implementation the equivalent step is the
`scripts/generate_synthetic_data.py` eCRF row generator. All PHI columns are
masked downstream by `domains/clinical/dbt/macros/phi_mask.sql`.
