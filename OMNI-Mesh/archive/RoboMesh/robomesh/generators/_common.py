"""Shared helpers for the synthetic data generators."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import numpy as np

ROBOT_MODELS = ("Figure-01", "Optimus-Gen2", "Atlas-Next", "Apollo-1")
GRIPPER_TYPES = ("2-finger", "3-finger", "vacuum", "5-finger")
FACTORY_SITES = ("austin-tx", "fremont-ca", "stuttgart-de", "yokohama-jp")
OBJECT_IDS = (
    "target_block_03",
    "engine_bolt_m12",
    "pcb_assembly_42",
    "wire_harness_07",
    "battery_cell_21",
)
FAILURE_TAXONOMY = (
    "GRASP_FAIL",
    "OVER_TORQUE",
    "VISION_OCCLUSION",
    "PATH_PLAN_TIMEOUT",
    "MOTOR_OVERHEAT",
    "NO_FAILURE",
)


@dataclass(frozen=True)
class EpisodeMeta:
    """High-level descriptor for one robot episode used by all 3 generators."""

    episode_id: str
    robot_model_id: str
    factory_site: str
    started_at: datetime
    duration_sec: float
    gripper_type: str
    target_object: str
    operator_id: str
    failure_type_tag: str
    success_flag: bool


def make_rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def synth_episodes(rng: np.random.Generator, n: int) -> list[EpisodeMeta]:
    """Generate ``n`` deterministic episode descriptors."""
    base = datetime(2026, 5, 1, 9, 0, 0, tzinfo=timezone.utc)
    episodes: list[EpisodeMeta] = []
    for i in range(n):
        # Random hour offset within a month for variety.
        offset = timedelta(
            hours=float(rng.integers(0, 24 * 30)),
            minutes=float(rng.integers(0, 60)),
            seconds=float(rng.integers(0, 60)),
        )
        # ~70 % success / 30 % failure split (realistic for RL eval).
        success = bool(rng.random() > 0.30)
        failure = "NO_FAILURE" if success else str(
            rng.choice(FAILURE_TAXONOMY[:-1])
        )
        episodes.append(
            EpisodeMeta(
                episode_id=f"EP_{9000 + i:05d}",
                robot_model_id=str(rng.choice(ROBOT_MODELS)),
                factory_site=str(rng.choice(FACTORY_SITES)),
                started_at=base + offset,
                duration_sec=float(rng.uniform(8.0, 22.0)),
                gripper_type=str(rng.choice(GRIPPER_TYPES)),
                target_object=str(rng.choice(OBJECT_IDS)),
                operator_id=f"op_{int(rng.integers(1000, 1100)):04d}",
                failure_type_tag=failure,
                success_flag=success,
            )
        )
    return episodes


def domain_raw_dir(raw_root: Path, domain: str) -> Path:
    out = raw_root / domain
    out.mkdir(parents=True, exist_ok=True)
    return out


def iter_episode_slices(
    eps: Iterable[EpisodeMeta], rng: np.random.Generator, hz: float
) -> Iterable[tuple[EpisodeMeta, np.ndarray]]:
    """Yield (episode, monotonically increasing timestamp array @ given Hz)."""
    for ep in eps:
        n = max(2, int(ep.duration_sec * hz))
        start_us = int(ep.started_at.timestamp() * 1_000_000)
        # Add tiny jitter to mimic real sensor drift but keep monotonicity.
        jitter = rng.normal(0.0, 50.0, size=n).cumsum().astype(np.int64)
        step_us = int(1_000_000 / hz)
        ts = start_us + np.arange(n, dtype=np.int64) * step_us + jitter
        ts = np.maximum.accumulate(ts)  # enforce monotonic
        yield ep, ts
