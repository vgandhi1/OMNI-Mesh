"""Domain 3 — Policy Evaluation & Simulation Domain.

Produces (a) per-step policy confidence logs from policy rollouts and
(b) sim-to-real comparison rows linking simulated trajectories to real ones.
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

POLICY_HZ = 20.0
POLICY_FAMILIES = ("vla_diffusion_v2", "openpi_0", "rt_2_x", "lerobot_a1")


def _policy_rollouts(rng: np.random.Generator, eps, raw_dir: Path) -> Path:
    rows: list[dict] = []
    for ep, ts in iter_episode_slices(eps, rng, hz=POLICY_HZ):
        policy = str(rng.choice(POLICY_FAMILIES))
        # Confidence drifts downward on failures.
        base_conf = float(rng.uniform(0.78, 0.96))
        n = ts.size
        drift = np.linspace(
            0.0,
            (-0.35 if not ep.success_flag else 0.05),
            n,
        ) + rng.normal(0, 0.02, n)
        conf = np.clip(base_conf + drift, 0.05, 0.99)
        for i in range(n):
            rows.append(
                {
                    "episode_id": ep.episode_id,
                    "policy_family": policy,
                    "ts_us": int(ts[i]),
                    "action_token_id": int(rng.integers(0, 8192)),
                    "policy_confidence": float(conf[i]),
                    "is_synthetic": bool(rng.random() > 0.65),
                    "sim_env": "IsaacSim-2025.2",
                }
            )
    table = pa.Table.from_pylist(rows)
    out = raw_dir / "policy_rollouts.parquet"
    pq.write_table(table, out, compression="zstd")
    log.info("simulation.policy_rollouts rows=%d path=%s", table.num_rows, out.name)
    return out


def _sim_to_real(rng: np.random.Generator, eps, raw_dir: Path) -> Path:
    rows: list[dict] = []
    for ep in eps:
        # 1 sim/real comparison row per episode is enough for the demo.
        rows.append(
            {
                "episode_id": ep.episode_id,
                "robot_model_id": ep.robot_model_id,
                "sim_trajectory_id": f"sim_{ep.episode_id}",
                "real_trajectory_id": f"real_{ep.episode_id}",
                "trajectory_l2_error_m": float(abs(rng.normal(0.08, 0.05))),
                "joint_angle_max_drift_rad": float(abs(rng.normal(0.05, 0.03))),
                "policy_family": str(rng.choice(POLICY_FAMILIES)),
                "outcome_match": bool(ep.success_flag and rng.random() > 0.2),
            }
        )
    table = pa.Table.from_pylist(rows)
    out = raw_dir / "sim_to_real.parquet"
    pq.write_table(table, out, compression="zstd")
    log.info("simulation.sim_to_real rows=%d path=%s", table.num_rows, out.name)
    return out


def generate_simulation_drops(raw_root: Path, n_episodes: int, seed: int) -> dict[str, Path]:
    raw_dir = domain_raw_dir(raw_root, "simulation")
    rng = make_rng(seed + 2)
    eps = synth_episodes(rng, n_episodes)
    return {
        "policy_rollouts": _policy_rollouts(rng, eps, raw_dir),
        "sim_to_real": _sim_to_real(rng, eps, raw_dir),
    }
