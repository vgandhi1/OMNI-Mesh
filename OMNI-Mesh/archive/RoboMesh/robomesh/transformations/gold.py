"""Gold layer — VLA-ready feature store.

Per-episode aggregations partitioned on ``robot_model_id`` and
``failure_type_tag``, joined with policy confidence stats from the
simulation domain. This is what a model trainer would consume.
"""
from __future__ import annotations

import duckdb
import pyarrow as pa

from robomesh.catalog.iceberg import read_table_arrow, write_managed_table
from robomesh.logging_setup import get_logger

log = get_logger(__name__)


_GOLD_VLA_EPISODES_SQL = """
WITH per_episode_traj AS (
    SELECT
        episode_id,
        ANY_VALUE(robot_model_id)   AS robot_model_id,
        ANY_VALUE(factory_site)     AS factory_site,
        ANY_VALUE(gripper_type)     AS gripper_type,
        ANY_VALUE(target_object)    AS target_object,
        ANY_VALUE(operator_id)      AS operator_id,
        ANY_VALUE(failure_type_tag) AS failure_type_tag,
        ANY_VALUE(success_flag)     AS success_flag,
        COUNT(*)                    AS n_camera_frames,
        MAX(max_joint_torque_nm)    AS peak_torque_nm,
        AVG(avg_motor_temp_c)       AS mean_motor_temp_c,
        (MAX(camera_ts_us) - MIN(camera_ts_us)) / 1e6 AS episode_duration_sec,
        MAX(ABS(time_drift_us))     AS max_align_drift_us
    FROM trajectories
    GROUP BY episode_id
),
per_episode_policy AS (
    SELECT
        episode_id,
        ANY_VALUE(policy_family)    AS policy_family,
        AVG(policy_confidence)      AS mean_policy_confidence,
        MIN(policy_confidence)      AS min_policy_confidence,
        COUNT(*)                    AS n_policy_steps
    FROM policy
    GROUP BY episode_id
),
sim_real AS (
    SELECT
        episode_id,
        trajectory_l2_error_m,
        joint_angle_max_drift_rad,
        outcome_match
    FROM sim
)
SELECT
    t.episode_id,
    t.robot_model_id,
    t.factory_site,
    t.gripper_type,
    t.target_object,
    t.operator_id,
    t.failure_type_tag,
    t.success_flag,
    t.episode_duration_sec,
    t.n_camera_frames,
    t.peak_torque_nm,
    t.mean_motor_temp_c,
    t.max_align_drift_us,
    p.policy_family,
    p.mean_policy_confidence,
    p.min_policy_confidence,
    p.n_policy_steps,
    s.trajectory_l2_error_m,
    s.joint_angle_max_drift_rad,
    s.outcome_match,
    -- VLA token vector: a compact, model-ready per-episode signature.
    [
        t.peak_torque_nm / 150.0,
        t.mean_motor_temp_c / 100.0,
        COALESCE(p.mean_policy_confidence, 0.0),
        COALESCE(p.min_policy_confidence, 0.0),
        COALESCE(s.trajectory_l2_error_m, 0.0),
        COALESCE(s.joint_angle_max_drift_rad, 0.0),
        CASE WHEN t.success_flag THEN 1.0 ELSE 0.0 END
    ] AS vla_feature_vector
FROM per_episode_traj t
LEFT JOIN per_episode_policy p USING (episode_id)
LEFT JOIN sim_real            s USING (episode_id)
ORDER BY t.robot_model_id, t.failure_type_tag, t.episode_id;
"""


def build_gold_layer() -> str:
    log.info("gold.build start")
    trajectories = read_table_arrow("silver.synchronized_trajectories")
    policy = read_table_arrow("simulation.bronze_policy_rollouts")
    sim = read_table_arrow("simulation.bronze_sim_to_real")
    log.info(
        "gold.inputs traj_rows=%d policy_rows=%d sim_rows=%d",
        trajectories.num_rows, policy.num_rows, sim.num_rows,
    )

    con = duckdb.connect()
    con.register("trajectories", trajectories)
    con.register("policy", policy)
    con.register("sim", sim)
    out: pa.Table = con.execute(_GOLD_VLA_EPISODES_SQL).arrow()
    con.close()

    full = write_managed_table("gold", "vla_episodes", out)
    log.info("gold.build done table=%s rows=%d", full, out.num_rows)
    return full
