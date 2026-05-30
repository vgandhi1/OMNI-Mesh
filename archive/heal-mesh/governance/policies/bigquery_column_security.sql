-- ============================================================================
-- HEAL-Mesh Phase 3 — BigQuery column-level access using policy tags.
--
-- The clinical PHI bronze table lives in BigQuery (per the blueprint). Every
-- PHI column is tagged with the ``healmesh-phi`` policy tag, and access to
-- that tag is granted only to the clinical research group.
-- ============================================================================

-- 1) Create the taxonomy + tag (run once per project).
-- bq mk --location=US --taxonomy --display_name=healmesh_phi healmesh_taxonomy
-- bq mk --policy_tag --display_name=phi_pii --taxonomy=healmesh_taxonomy

-- 2) Attach the policy tag to PHI columns.
ALTER TABLE `healmesh.clinical_bronze.ecrf_patients`
  ALTER COLUMN mrn        SET OPTIONS (policy_tags=['projects/_/locations/us/taxonomies/_/policyTags/healmesh-phi']),
  ALTER COLUMN first_name SET OPTIONS (policy_tags=['projects/_/locations/us/taxonomies/_/policyTags/healmesh-phi']),
  ALTER COLUMN last_name  SET OPTIONS (policy_tags=['projects/_/locations/us/taxonomies/_/policyTags/healmesh-phi']),
  ALTER COLUMN email      SET OPTIONS (policy_tags=['projects/_/locations/us/taxonomies/_/policyTags/healmesh-phi']),
  ALTER COLUMN dob        SET OPTIONS (policy_tags=['projects/_/locations/us/taxonomies/_/policyTags/healmesh-phi']);

-- 3) Authorize the clinical research group to use the tag.
-- gcloud data-catalog taxonomies iam-policies set \
--   --taxonomy=healmesh_taxonomy --member=group:clinical-research@healmesh.example \
--   --role=roles/datacatalog.categoryFineGrainedReader

-- 4) Authorized view for the AI-readiness service account - only de-identified columns.
CREATE OR REPLACE VIEW `healmesh.clinical_gold.gold_patient_cohort_authorized` AS
SELECT
    patient_id,
    age_bracket,
    sex_at_birth,
    region,
    study_id,
    enrolled_ts
FROM `healmesh.clinical_gold.gold_patient_cohort`;

GRANT `roles/bigquery.dataViewer`
  ON TABLE `healmesh.clinical_gold.gold_patient_cohort_authorized`
  TO 'serviceAccount:ai-readiness@healmesh.iam.gserviceaccount.com';
