-- Silver: de-identified eCRF observations. Raw PHI (name, DOB, MRN) is stripped at
-- ingest; only the hashed surrogate, study, pre-computed age bracket, and region
-- survive — so age is never derived from a raw birth date downstream.
select
    timestamp,
    patient_id_hashed,
    study_id,
    age_bracket,
    region,
    adverse_event_flag
from {{ source('clinical_bronze', 'ecrf_observations') }}
where patient_id_hashed is not null
