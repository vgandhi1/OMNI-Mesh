-- Gold: analytics-ready cohort metadata. Only opaque IDs and aggregated tiers
-- cross the domain boundary — raw PHI never escapes the clinical domain.
-- Cross-domain enrichment with telemetry happens at the AI-readiness tier,
-- where both gold tables are joined via the opaque ``patient_id`` key.
--
-- ``age_bracket`` is consumed straight from silver where it was computed
-- against the real ``dob`` before generalization. Re-deriving it here from
-- ``birth_year`` (which is January 1 of the patient's birth year) would
-- introduce a systematic +0/+1 error around January each year.
-- (REVIEW_FEEDBACK.md Issue 5.)
select
    p.patient_id,
    p.age_bracket,
    p.sex_at_birth,
    p.region,
    p.study_id,
    p.enrolled_ts
from {{ ref('silver_ecrf_patients') }} p
