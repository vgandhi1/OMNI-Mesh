{{ config(materialized='table', schema='silver') }}

-- Silver layer with enforced contract: only SLA-conformant readings survive.
-- The contract itself is declared in schema.yml with `enforced: true`.

WITH bronze AS (
    SELECT * FROM {{ ref('telemetry_bronze_seed') }}
)
SELECT
    facility_id,
    line_id,
    register_id,
    plc_timestamp_ms,
    anomaly_flag,
    voltage,
    temperature_c,
    pressure_bar
FROM bronze
WHERE voltage      BETWEEN {{ var('sla_voltage_min', 12.0) }} AND {{ var('sla_voltage_max', 16.0) }}
  AND temperature_c <= {{ var('sla_temperature_max', 95.0) }}
  AND pressure_bar  <= {{ var('sla_pressure_max', 9.5) }}
