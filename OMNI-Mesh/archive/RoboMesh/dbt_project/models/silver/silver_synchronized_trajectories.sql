{{ config(materialized='table', schema='silver') }}

with joints_pivoted as (
    select
        episode_id,
        robot_model_id,
        factory_site,
        ts_us,
        max(case when joint_index = 0 then joint_position end) as j0_pos,
        max(case when joint_index = 1 then joint_position end) as j1_pos,
        max(case when joint_index = 2 then joint_position end) as j2_pos,
        max(case when joint_index = 3 then joint_position end) as j3_pos,
        max(case when joint_index = 4 then joint_position end) as j4_pos,
        max(case when joint_index = 5 then joint_position end) as j5_pos,
        max(case when joint_index = 6 then joint_position end) as j6_pos,
        max(joint_torque_nm)                                    as max_joint_torque_nm,
        avg(motor_temp_c)                                       as avg_motor_temp_c
    from {{ source('bronze_raw', 'telemetry_joint_states') }}
    group by episode_id, robot_model_id, factory_site, ts_us
),
synced as (
    select
        cam.episode_id,
        jp.robot_model_id,
        jp.factory_site,
        cam.camera_id,
        cam.frame_index,
        cam.ts_us               as camera_ts_us,
        cam.video_uri,
        jp.ts_us                as joint_ts_us,
        (cam.ts_us - jp.ts_us)  as time_drift_us,
        jp.j0_pos, jp.j1_pos, jp.j2_pos, jp.j3_pos,
        jp.j4_pos, jp.j5_pos, jp.j6_pos,
        jp.max_joint_torque_nm,
        jp.avg_motor_temp_c
    from {{ source('bronze_raw', 'teleop_camera_manifest') }} as cam
    asof left join joints_pivoted as jp
      on cam.episode_id = jp.episode_id
     and cam.ts_us      >= jp.ts_us
)
select
    s.*,
    meta.failure_type_tag,
    meta.success_flag,
    meta.gripper_type,
    meta.target_object,
    meta.operator_id
from synced as s
left join {{ source('bronze_raw', 'teleop_episode_metadata') }} as meta
    using (episode_id)
