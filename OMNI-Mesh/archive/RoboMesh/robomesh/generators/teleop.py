"""Domain 1 — Human Demonstration Domain (Teleop).

Produces 50 Hz haptic/VR controller trajectories plus 30 fps camera-frame
manifests pointing at (mocked) MP4 URIs. Output: one Parquet file per
sub-stream so the Bronze ingest can register them as separate Iceberg tables.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from robomesh.generators._common import (
    domain_raw_dir,
    iter_episode_slices,
    make_rng,
    synth_episodes,
)
from robomesh.logging_setup import get_logger

log = get_logger(__name__)

VR_HZ = 50.0
CAM_FPS = 30.0


def _vr_trajectories(rng: np.random.Generator, eps, raw_dir: Path) -> Path:
    rows: list[dict] = []
    for ep, ts in iter_episode_slices(eps, rng, hz=VR_HZ):
        n = ts.size
        # 6-DoF end-effector pose + 3-axis haptic force.
        pose = rng.normal(0.0, 0.15, size=(n, 6)).cumsum(axis=0)
        force = rng.normal(0.0, 1.5, size=(n, 3))
        for i in range(n):
            rows.append(
                {
                    "episode_id": ep.episode_id,
                    "operator_id": ep.operator_id,
                    "robot_model_id": ep.robot_model_id,
                    "ts_us": int(ts[i]),
                    "pose_x": float(pose[i, 0]),
                    "pose_y": float(pose[i, 1]),
                    "pose_z": float(pose[i, 2]),
                    "pose_rx": float(pose[i, 3]),
                    "pose_ry": float(pose[i, 4]),
                    "pose_rz": float(pose[i, 5]),
                    "force_x": float(force[i, 0]),
                    "force_y": float(force[i, 1]),
                    "force_z": float(force[i, 2]),
                }
            )
    table = pa.Table.from_pylist(rows)
    out = raw_dir / "vr_trajectories.parquet"
    pq.write_table(table, out, compression="zstd")
    log.info("teleop.vr_trajectories rows=%d path=%s", table.num_rows, out.name)
    return out


def _camera_manifest(rng: np.random.Generator, eps, raw_dir: Path) -> Path:
    rows: list[dict] = []
    cameras = ("cam_overhead", "cam_wrist_left", "cam_wrist_right")
    for ep, ts in iter_episode_slices(eps, rng, hz=CAM_FPS):
        for i, t in enumerate(ts):
            for c in cameras:
                rows.append(
                    {
                        "episode_id": ep.episode_id,
                        "camera_id": c,
                        "frame_index": i,
                        "ts_us": int(t),
                        "video_uri": (
                            f"s3://mind-robotics-teleop/raw/"
                            f"{ep.episode_id}/{c}_{i:05d}.mp4"
                        ),
                        "resolution": "1920x1080",
                        "fps": CAM_FPS,
                    }
                )
    table = pa.Table.from_pylist(rows)
    out = raw_dir / "camera_manifest.parquet"
    pq.write_table(table, out, compression="zstd")
    log.info("teleop.camera_manifest rows=%d path=%s", table.num_rows, out.name)
    return out


def _episode_metadata(eps, raw_dir: Path) -> Path:
    table = pa.Table.from_pylist(
        [
            {
                "episode_id": ep.episode_id,
                "robot_model_id": ep.robot_model_id,
                "factory_site": ep.factory_site,
                "started_at_us": int(ep.started_at.timestamp() * 1_000_000),
                "duration_sec": ep.duration_sec,
                "gripper_type": ep.gripper_type,
                "target_object": ep.target_object,
                "operator_id": ep.operator_id,
                "failure_type_tag": ep.failure_type_tag,
                "success_flag": ep.success_flag,
            }
            for ep in eps
        ]
    )
    out = raw_dir / "episode_metadata.parquet"
    pq.write_table(table, out, compression="zstd")
    log.info("teleop.episode_metadata rows=%d path=%s", table.num_rows, out.name)
    return out


def generate_teleop_drops(raw_root: Path, n_episodes: int, seed: int) -> dict[str, Path]:
    """Materialize all Teleop-domain Bronze drops.

    Returns a mapping ``{table_name: parquet_path}``.
    """
    raw_dir = domain_raw_dir(raw_root, "teleop")
    rng = make_rng(seed)
    eps = synth_episodes(rng, n_episodes)
    return {
        "vr_trajectories": _vr_trajectories(rng, eps, raw_dir),
        "camera_manifest": _camera_manifest(rng, eps, raw_dir),
        "episode_metadata": _episode_metadata(eps, raw_dir),
    }
