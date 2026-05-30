{{ config(materialized='table', schema='gold') }}

-- Gold facility health rollup. Mirrors the Python `build_gold_aggregates`
-- pipeline so dbt + Dagster produce identical analytics whether you invoke
-- them via dbt Mesh or the Dagster asset graph.

WITH silver AS (
    SELECT * FROM {{ ref('telemetry_silver') }}
)
SELECT
    facility_id,
    COUNT(*)                           AS sample_count,
    AVG(voltage)                       AS avg_voltage,
    AVG(temperature_c)                 AS avg_temperature_c,
    AVG(pressure_bar)                  AS avg_pressure_bar,
    SUM(CAST(anomaly_flag AS INTEGER)) AS anomaly_count,
    MAX(plc_timestamp_ms)              AS latest_sample_ms
FROM silver
GROUP BY facility_id
ORDER BY facility_id
