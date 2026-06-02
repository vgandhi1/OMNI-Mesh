-- Gold: per-region cohort summary (de-identified surrogates only).
select
    region,
    count(distinct patient_id_hashed) as patient_count,
    round(avg(heart_rate_variability), 2) as avg_hrv,
    round(avg(sleep_efficiency), 3) as avg_sleep_efficiency,
    sum(case when heart_rate_variability < 35 then 1 else 0 end) as low_hrv_readings
from {{ ref('silver_wearable_biometrics') }}
group by 1
order by 1
