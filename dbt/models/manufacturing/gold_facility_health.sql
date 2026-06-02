-- Gold: per-facility health rollup with anomaly and SLA-breach counts.
select
    facility_id,
    count(*) as sample_count,
    round(avg(measured_voltage), 3) as avg_voltage,
    round(avg(temperature_c), 3) as avg_temperature_c,
    round(avg(pressure_bar), 3) as avg_pressure_bar,
    sum(case when anomaly_flag then 1 else 0 end) as anomaly_count,
    sum(case when sla_breach then 1 else 0 end) as sla_breach_count
from {{ ref('silver_plc_registers') }}
group by 1
order by 1
