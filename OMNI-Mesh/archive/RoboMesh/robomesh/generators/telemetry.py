"""Domain 2 — Edge & Factory Telemetry Domain.

Produces 500 Hz joint kinematics + 10 Hz network/health telemetry that
mirrors what would land in GCS from a fleet of K3s edge nodes.
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

JOINT_HZ = 500.0
HEALTH_HZ = 10.0
N_JOINTS = 7


def _joint_states(rng: np.random.Generator, eps, raw_dir: Path) -> Path:
    rows: list[dict] = []
    for ep, ts in iter_episode_slices(eps, rng, hz=JOINT_HZ):
        n = ts.size
        # Smooth sinusoidal motion + noise gives realistic joint signals.
        t_sec = (ts - ts[0]) / 1_000_000.0
        for j in range(N_JOINTS):
            phase = rng.uniform(0, 2 * np.pi)
            amp = rng.uniform(0.3, 1.2)
            pos = amp * np.sin(2 * np.pi * 0.4 * t_sec + phase)
            vel = np.gradient(pos, edge_order=2)
            # Inject a torque spike on failure episodes to make Phase 4
            # semantic summaries interesting.
            base_torque = 25 + 30 * np.abs(vel) + rng.normal(0, 3, n)
            if (
                ep.failure_type_tag in ("OVER_TORQUE", "GRASP_FAIL")
                and j == int(rng.integers(0, N_JOINTS))
            ):
                spike_idx = int(n * 0.6)
                base_torque[spike_idx : spike_idx + 20] += rng.uniform(60, 110)
            for i in range(n):
                rows.append(
                    {
                        "episode_id": ep.episode_id,
                        "robot_model_id": ep.robot_model_id,
                        "factory_site": ep.factory_site,
                        "joint_index": j,
                        "ts_us": int(ts[i]),
                        "joint_position": float(pos[i]),
                        "joint_velocity": float(vel[i]),
                        "joint_torque_nm": float(base_torque[i]),
                        "motor_temp_c": float(45 + 0.15 * abs(base_torque[i])
                                              + rng.normal(0, 0.5)),
                    }
                )
    table = pa.Table.from_pylist(rows)
    out = raw_dir / "joint_states.parquet"
    pq.write_table(table, out, compression="zstd")
    log.info("telemetry.joint_states rows=%d path=%s", table.num_rows, out.name)
    return out


def _network_health(rng: np.random.Generator, eps, raw_dir: Path) -> Path:
    rows: list[dict] = []
    for ep, ts in iter_episode_slices(eps, rng, hz=HEALTH_HZ):
        for t in ts:
            rows.append(
                {
                    "episode_id": ep.episode_id,
                    "robot_model_id": ep.robot_model_id,
                    "factory_site": ep.factory_site,
                    "ts_us": int(t),
                    "network_latency_ms": float(max(1.0, rng.normal(18.0, 5.0))),
                    "packet_loss_pct": float(max(0.0, rng.normal(0.4, 0.3))),
                    "cpu_pct": float(min(100.0, max(0.0, rng.normal(42.0, 8.0)))),
                    "mem_pct": float(min(100.0, max(0.0, rng.normal(57.0, 6.0)))),
                    "k3s_node": f"node-{rng.integers(1, 12):02d}",
                    # NOTE (Phase 3 — masking): factory blueprints are PROPRIETARY;
                    # cell-level masking lives in robomesh.governance.masking.
                    "factory_blueprint_cell": f"bay-{rng.integers(1, 9)}-rack-{rng.integers(1, 12):02d}",
                }
            )
    table = pa.Table.from_pylist(rows)
    out = raw_dir / "network_health.parquet"
    pq.write_table(table, out, compression="zstd")
    log.info("telemetry.network_health rows=%d path=%s", table.num_rows, out.name)
    return out


def generate_telemetry_drops(raw_root: Path, n_episodes: int, seed: int) -> dict[str, Path]:
    raw_dir = domain_raw_dir(raw_root, "telemetry")
    rng = make_rng(seed + 1)
    eps = synth_episodes(rng, n_episodes)
    return {
        "joint_states": _joint_states(rng, eps, raw_dir),
        "network_health": _network_health(rng, eps, raw_dir),
    }
