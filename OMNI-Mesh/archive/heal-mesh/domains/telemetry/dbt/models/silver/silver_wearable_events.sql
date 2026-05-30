-- Silver: standardized, deduplicated wearable telemetry.
-- * timestamps coerced to UTC TIMESTAMP
-- * per-(patient, minute) deduplication using a stable row hash
-- * obvious physiological outliers nulled out instead of dropped so they can
--   be inspected via the data-quality dashboards
with deduped as (
    select
        patient_id,
        device_id,
        cast(date_trunc('minute', event_ts) as timestamp) as event_ts,
        heart_rate_bpm,
        hrv_ms,
        spo2_pct,
        deep_sleep_min,
        steps,
        sleep_pattern_hint,
        row_number() over (
            partition by patient_id, date_trunc('minute', event_ts)
            order by event_ts desc
        ) as rn
    from {{ ref('bronze_wearable_events') }}
)
select
    patient_id,
    device_id,
    event_ts,
    case when heart_rate_bpm between 30 and 220 then heart_rate_bpm end as heart_rate_bpm,
    case when hrv_ms between 1 and 250 then hrv_ms end                   as hrv_ms,
    case when spo2_pct between 70 and 100 then spo2_pct end              as spo2_pct,
    case when deep_sleep_min between 0 and 480 then deep_sleep_min end   as deep_sleep_min,
    steps,
    sleep_pattern_hint
from deduped
where rn = 1
