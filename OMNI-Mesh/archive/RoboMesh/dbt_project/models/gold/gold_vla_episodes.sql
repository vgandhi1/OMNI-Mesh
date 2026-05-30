{{ config(materialized='table', schema='gold') }}

with traj as (
    select
        episode_id,
        any_value(robot_model_id)   as robot_model_id,
        any_value(factory_site)     as factory_site,
        any_value(gripper_type)     as gripper_type,
        any_value(target_object)    as target_object,
        any_value(operator_id)      as operator_id,
        any_value(failure_type_tag) as failure_type_tag,
        any_value(success_flag)     as success_flag,
        count(*)                    as n_camera_frames,
        max(max_joint_torque_nm)    as peak_torque_nm,
        avg(avg_motor_temp_c)       as mean_motor_temp_c
    from {{ ref('silver_synchronized_trajectories') }}
    group by episode_id
),
policy as (
    select
        episode_id,
        any_value(policy_family) as policy_family,
        avg(policy_confidence)   as mean_policy_confidence,
        min(policy_confidence)   as min_policy_confidence,
        count(*)                 as n_policy_steps
    from {{ source('bronze_raw', 'simulation_policy_rollouts') }}
    group by episode_id
),
sim as (
    select
        episode_id,
        trajectory_l2_error_m,
        joint_angle_max_drift_rad,
        outcome_match
    from {{ source('bronze_raw', 'simulation_sim_to_real') }}
)
select
    t.episode_id,
    t.robot_model_id,
    t.factory_site,
    t.gripper_type,
    t.target_object,
    t.operator_id,
    t.failure_type_tag,
    t.success_flag,
    t.n_camera_frames,
    t.peak_torque_nm,
    t.mean_motor_temp_c,
    p.policy_family,
    p.mean_policy_confidence,
    p.min_policy_confidence,
    p.n_policy_steps,
    s.trajectory_l2_error_m,
    s.joint_angle_max_drift_rad,
    s.outcome_match
from traj t
left join policy p using (episode_id)
left join sim    s using (episode_id)
