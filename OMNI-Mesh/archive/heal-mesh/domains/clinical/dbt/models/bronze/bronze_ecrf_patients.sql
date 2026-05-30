{{ config(materialized='view') }}

-- Bronze: the raw eCRF rows. This view is only readable by roles with
-- explicit PHI access (see governance/policies/bigquery_column_security.sql
-- and authentication_authorization_rule).
select
    patient_id,
    mrn,
    first_name,
    last_name,
    email,
    dob,
    sex_at_birth,
    study_id,
    consent_signed,
    region,
    enrolled_ts
from {{ source('clinical_raw', 'ecrf_patients') }}
