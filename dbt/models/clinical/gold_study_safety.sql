-- Gold: per-study safety rollup (de-identified cohort metrics only).
select
    study_id,
    count(distinct patient_id_hashed) as patient_count,
    count(*) as observation_count,
    sum(case when adverse_event_flag then 1 else 0 end) as adverse_event_count,
    round(avg(case when adverse_event_flag then 1.0 else 0.0 end), 4) as adverse_event_rate
from {{ ref('silver_ecrf_observations') }}
group by 1
order by 1
