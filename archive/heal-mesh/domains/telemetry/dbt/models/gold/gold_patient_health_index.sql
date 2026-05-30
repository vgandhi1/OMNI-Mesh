-- Gold: per-patient weekly health index used by the AI readiness tier.
-- Mirrors the blueprint examples (weekly_average_hrv, sleep_efficiency_score).
with weekly as (
    select
        patient_id,
        date_trunc('week', event_ts) as week_start,
        avg(heart_rate_bpm)          as avg_hr_bpm,
        avg(hrv_ms)                  as avg_hrv_ms,
        avg(spo2_pct)                as avg_spo2,
        sum(deep_sleep_min)          as total_deep_sleep_min,
        sum(steps)                   as total_steps
    from {{ ref('silver_wearable_events') }}
    group by 1, 2
),
trend as (
    select
        patient_id,
        week_start,
        avg_hr_bpm,
        avg_hrv_ms,
        avg_spo2,
        total_deep_sleep_min,
        total_steps,
        avg_hrv_ms - lag(avg_hrv_ms) over (
            partition by patient_id order by week_start
        ) as hrv_delta_vs_prev_week,
        avg_hr_bpm - lag(avg_hr_bpm) over (
            partition by patient_id order by week_start
        ) as hr_delta_vs_prev_week
    from weekly
)
select
    patient_id,
    week_start,
    avg_hr_bpm,
    avg_hrv_ms,
    avg_spo2,
    total_deep_sleep_min,
    total_steps,
    hrv_delta_vs_prev_week,
    hr_delta_vs_prev_week,
    case
        when avg_hrv_ms < 35 or hrv_delta_vs_prev_week < -10 then 'elevated'
        when avg_hrv_ms < 50 then 'moderate'
        else 'low'
    end as sleep_risk_tier,
    case
        when total_deep_sleep_min < 300 then 'poor'
        when total_deep_sleep_min < 700 then 'fair'
        else 'good'
    end as sleep_efficiency_score
from trend
