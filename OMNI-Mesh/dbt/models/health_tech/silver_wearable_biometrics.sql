-- Silver: wearable biometrics with physiological outliers nulled (not dropped).
select
    timestamp,
    patient_id_hashed,
    case when heart_rate_variability between 5 and 200 then heart_rate_variability end
        as heart_rate_variability,
    case when sleep_efficiency between 0.0 and 1.0 then sleep_efficiency end
        as sleep_efficiency,
    region
from {{ source('health_bronze', 'wearable_biometrics') }}
where patient_id_hashed is not null
