-- ============================================================================
-- HEAL-Mesh Phase 3 — Databricks Unity Catalog grants & dynamic views.
--
-- Mirrors the same RLS contract that lives in Snowflake (see
-- snowflake_row_level_security.sql) but using Unity Catalog primitives:
-- principal grants on the bronze/silver tables and a dynamic view that
-- enforces the same role-based access controls for analyst consumers.
-- ============================================================================

-- 1) Coarse grants. Default-deny per authentication_authorization_rule §5;
--    every grant below is explicit.
GRANT USAGE ON CATALOG healmesh                       TO `clinical_researchers`;
GRANT USAGE ON SCHEMA  healmesh.clinical_silver       TO `clinical_researchers`;
GRANT SELECT ON TABLE  healmesh.clinical_silver.silver_ecrf_patients
                                                      TO `clinical_researchers`;

GRANT USAGE ON CATALOG healmesh                       TO `business_analysts`;
GRANT USAGE ON SCHEMA  healmesh.clinical_gold         TO `business_analysts`;
GRANT SELECT ON TABLE  healmesh.clinical_gold.gold_patient_cohort
                                                      TO `business_analysts`;

-- 2) Dynamic view that re-applies row/column masking for non-clinical roles.
CREATE OR REPLACE VIEW healmesh.clinical_silver.ecrf_patients_secure AS
SELECT
    patient_id,
    CASE WHEN is_member('clinical_researchers') THEN mrn_hash       ELSE NULL END AS mrn_hash,
    CASE WHEN is_member('clinical_researchers') THEN first_name_hash ELSE NULL END AS first_name_hash,
    CASE WHEN is_member('clinical_researchers') THEN last_name_hash  ELSE NULL END AS last_name_hash,
    CASE WHEN is_member('clinical_researchers') THEN email_hash      ELSE NULL END AS email_hash,
    birth_year,
    sex_at_birth,
    study_id,
    consent_signed,
    region,
    enrolled_ts
FROM healmesh.clinical_silver.silver_ecrf_patients
WHERE
       is_member('data_governance_admins')
    OR (is_member('clinical_researchers') AND study_id IN ('CLINICAL_STUDY_01','CLINICAL_STUDY_02'))
    OR (is_member('business_analysts')    AND FALSE);

GRANT SELECT ON VIEW healmesh.clinical_silver.ecrf_patients_secure
                                                      TO `business_analysts`;
