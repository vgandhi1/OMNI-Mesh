"""Silver layer — time-synchronized multimodal trajectories.

This solves the **multimodal alignment challenge** described in Phase 2 of
``docs/RoboMesh.md``: we forward-fill the 500 Hz joint kinematics onto the
30 fps camera frame index using a SQL window-function pattern that mimics the
PySpark / dbt implementation a production deployment would use.

We use DuckDB for the heavy SQL because it ships with native Arrow I/O so we
can stay in-memory end-to-end with no Spark cluster.
"""
from __future__ import annotations

import duckdb
import pyarrow as pa

from robomesh.catalog.iceberg import read_table_arrow, write_managed_table
from robomesh.logging_setup import get_logger

log = get_logger(__name__)


# Silver model declared as SQL so it is portable between DuckDB ↔ Spark ↔ Snowflake.
_SILVER_TRAJECTORY_SQL = """
WITH joints_pivoted AS (
    SELECT
        episode_id,
        robot_model_id,
        factory_site,
        ts_us,
        MAX(CASE WHEN joint_index = 0 THEN joint_position END) AS j0_pos,
        MAX(CASE WHEN joint_index = 1 THEN joint_position END) AS j1_pos,
        MAX(CASE WHEN joint_index = 2 THEN joint_position END) AS j2_pos,
        MAX(CASE WHEN joint_index = 3 THEN joint_position END) AS j3_pos,
        MAX(CASE WHEN joint_index = 4 THEN joint_position END) AS j4_pos,
        MAX(CASE WHEN joint_index = 5 THEN joint_position END) AS j5_pos,
        MAX(CASE WHEN joint_index = 6 THEN joint_position END) AS j6_pos,
        MAX(joint_torque_nm)                                    AS max_joint_torque_nm,
        AVG(motor_temp_c)                                       AS avg_motor_temp_c
    FROM joints
    GROUP BY episode_id, robot_model_id, factory_site, ts_us
),
-- For each camera frame, find the nearest joint sample using ASOF JOIN.
-- This is the canonical pattern for high-vs-low frequency multimodal sync.
synced AS (
    SELECT
        cam.episode_id,
        jp.robot_model_id,
        jp.factory_site,
        cam.camera_id,
        cam.frame_index,
        cam.ts_us                     AS camera_ts_us,
        cam.video_uri,
        jp.ts_us                      AS joint_ts_us,
        (cam.ts_us - jp.ts_us)        AS time_drift_us,
        jp.j0_pos, jp.j1_pos, jp.j2_pos, jp.j3_pos,
        jp.j4_pos, jp.j5_pos, jp.j6_pos,
        jp.max_joint_torque_nm,
        jp.avg_motor_temp_c
    FROM cameras AS cam
    ASOF LEFT JOIN joints_pivoted AS jp
      ON cam.episode_id = jp.episode_id
     AND cam.ts_us      >= jp.ts_us
),
enriched AS (
    SELECT
        s.*,
        meta.failure_type_tag,
        meta.success_flag,
        meta.gripper_type,
        meta.target_object,
        meta.operator_id
    FROM synced AS s
    LEFT JOIN episodes AS meta USING (episode_id)
)
SELECT * FROM enriched
ORDER BY episode_id, camera_id, frame_index;
"""


def build_silver_layer() -> str:
    """Materialize ``silver.synchronized_trajectories`` from Bronze tables."""
    log.info("silver.build start")
    joints = read_table_arrow("telemetry.bronze_joint_states")
    cameras = read_table_arrow("teleop.bronze_camera_manifest")
    episodes = read_table_arrow("teleop.bronze_episode_metadata")

    log.info(
        "silver.inputs joint_rows=%d cam_rows=%d episodes=%d",
        joints.num_rows, cameras.num_rows, episodes.num_rows,
    )

    con = duckdb.connect()
    con.register("joints", joints)
    con.register("cameras", cameras)
    con.register("episodes", episodes)
    out: pa.Table = con.execute(_SILVER_TRAJECTORY_SQL).arrow()
    con.close()

    full = write_managed_table("silver", "synchronized_trajectories", out)
    log.info("silver.build done table=%s rows=%d", full, out.num_rows)
    return full
