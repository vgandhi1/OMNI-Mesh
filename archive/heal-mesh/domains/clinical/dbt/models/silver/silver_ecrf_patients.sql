-- Silver: cleansed eCRF data with PHI columns cryptographically masked.
-- The dbt contract on this model is what guarantees that no raw PHI string
-- ever appears in the gold layer or the AI tier downstream.
--
-- Age bracket is computed HERE — while the real ``dob`` is still in scope —
-- using DuckDB's ``age(timestamp_a, timestamp_b)`` which returns an interval
-- that properly accounts for the month/day of birth. After this CTE the
-- raw ``dob`` is discarded; only the (non-PHI) ``birth_year`` and bracketed
-- ``age_bracket`` cross the silver boundary. Computing the bracket from the
-- year-truncated ``birth_year`` would produce a systematic +0/+1 error
-- depending on where in the calendar the query runs.
-- (REVIEW_FEEDBACK.md Issue 5.)
with computed as (
    select
        patient_id,                              -- already an opaque surrogate
        {{ phi_mask('mrn') }}         as mrn_hash,
        {{ phi_mask('first_name') }}  as first_name_hash,
        {{ phi_mask('last_name') }}   as last_name_hash,
        {{ phi_mask('email') }}       as email_hash,
        cast(date_trunc('year', dob) as date) as birth_year,  -- generalize DOB → birth year
        cast(extract('year' from age(current_date, dob)) as integer) as age_years,
        sex_at_birth,
        study_id,
        consent_signed,
        region,
        cast(enrolled_ts as timestamp) as enrolled_ts
    from {{ ref('bronze_ecrf_patients') }}
    where consent_signed = true
)

select
    patient_id,
    mrn_hash,
    first_name_hash,
    last_name_hash,
    email_hash,
    birth_year,
    case
        when age_years < 30 then '<30'
        when age_years < 45 then '30-45'
        when age_years < 60 then '45-60'
        else '60+'
    end as age_bracket,
    sex_at_birth,
    study_id,
    consent_signed,
    region,
    enrolled_ts
from computed
