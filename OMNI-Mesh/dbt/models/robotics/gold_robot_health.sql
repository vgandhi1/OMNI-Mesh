-- Gold: per robot-model success/failure rollup for the VLA flywheel.
select
    robot_model_id,
    count(*) as episode_count,
    sum(case when success_flag then 1 else 0 end) as success_count,
    sum(case when not success_flag then 1 else 0 end) as failure_count,
    round(avg(case when success_flag then 1.0 else 0.0 end), 3) as success_rate
from {{ ref('silver_robot_signals') }}
group by 1
order by 1
