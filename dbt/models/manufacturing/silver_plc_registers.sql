-- Silver: PLC registers with an SLA-breach flag (voltage/temperature/pressure).
select
    timestamp,
    facility_id,
    register_id,
    measured_voltage,
    temperature_c,
    pressure_bar,
    anomaly_flag,
    (
        measured_voltage < 12.0
        or measured_voltage > 16.0
        or temperature_c > 95.0
        or pressure_bar > 9.5
    ) as sla_breach
from {{ source('manufacturing_bronze', 'plc_registers') }}
where facility_id is not null
