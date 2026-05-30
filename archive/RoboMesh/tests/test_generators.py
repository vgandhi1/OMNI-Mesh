"""Smoke tests for the synthetic data generators."""
from __future__ import annotations

import pyarrow.parquet as pq

from robomesh.config import get_settings
from robomesh.generators import (
    generate_simulation_drops,
    generate_telemetry_drops,
    generate_teleop_drops,
)


def test_teleop_generates_three_parquet_files() -> None:
    s = get_settings()
    paths = generate_teleop_drops(s.raw_root, s.demo_episodes, s.seed)
    assert set(paths) == {"vr_trajectories", "camera_manifest", "episode_metadata"}
    for p in paths.values():
        assert p.exists()
        assert pq.read_table(p).num_rows > 0


def test_telemetry_generates_high_freq_joints() -> None:
    s = get_settings()
    paths = generate_telemetry_drops(s.raw_root, s.demo_episodes, s.seed)
    joints = pq.read_table(paths["joint_states"])
    # 500 Hz * ≥ 8s * N_JOINTS=7 * 4 episodes ≈ minimum 100k rows.
    assert joints.num_rows > 80_000
    cols = set(joints.schema.names)
    assert {"joint_torque_nm", "motor_temp_c", "joint_index"}.issubset(cols)


def test_simulation_generates_sim_to_real() -> None:
    s = get_settings()
    paths = generate_simulation_drops(s.raw_root, s.demo_episodes, s.seed)
    sim2real = pq.read_table(paths["sim_to_real"])
    assert sim2real.num_rows == s.demo_episodes
    assert "outcome_match" in sim2real.schema.names
