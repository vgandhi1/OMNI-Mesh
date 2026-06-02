-- Silver: cleaned robot trajectory signals with a derived peak-joint feature.
select
    timestamp,
    robot_id,
    robot_model_id,
    joint_positions,
    list_max(joint_positions) as peak_joint_pos,
    camera_frame_uri,
    failure_type_tag,
    success_flag
from {{ source('robotics_bronze', 'robot_signals') }}
where robot_id is not null
