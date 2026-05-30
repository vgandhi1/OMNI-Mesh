{{ config(materialized='view') }}

-- Bronze: 1:1 view over the raw Iceberg-backed wearable events parquet drop.
-- We deliberately preserve the source schema so contract violations surface in
-- the silver layer, not here.
select
    patient_id,
    device_id,
    event_ts,
    heart_rate_bpm,
    hrv_ms,
    spo2_pct,
    deep_sleep_min,
    steps,
    sleep_pattern_hint
from {{ source('telemetry_raw', 'wearable_events') }}
