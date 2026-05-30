"""Generate prose episode summaries from the Gold layer."""
from __future__ import annotations

from typing import Iterator

import pyarrow as pa

from robomesh.catalog.iceberg import read_table_arrow
from robomesh.logging_setup import get_logger

log = get_logger(__name__)


_TEMPLATE_SUCCESS = (
    "Episode {episode_id}: robot model {robot_model_id} at site {factory_site} "
    "completed a {duration:.1f}s task picking {target_object} with a {gripper_type} "
    "gripper, operated by {operator_id}. Peak joint torque was {peak_torque:.1f} Nm "
    "(motor temperature averaged {motor_temp:.1f}C). Policy {policy_family} held a "
    "mean confidence of {mean_conf:.2f} with a minimum of {min_conf:.2f} across "
    "{n_steps} action steps. Sim-to-real trajectory L2 error was {l2_err:.3f} m."
)

_TEMPLATE_FAILURE = (
    "Episode {episode_id}: robot model {robot_model_id} at site {factory_site} "
    "encountered a {failure_type} event during a {duration:.1f}s manipulation of "
    "{target_object} using a {gripper_type} gripper (operator {operator_id}). "
    "Peak torque spiked to {peak_torque:.1f} Nm while motor temperature reached "
    "{motor_temp:.1f}C. Policy {policy_family} confidence collapsed from {mean_conf:.2f} "
    "to a minimum of {min_conf:.2f} across {n_steps} action steps; sim-to-real "
    "trajectory diverged by {l2_err:.3f} m."
)


def _row_to_text(row: dict) -> str:
    common = dict(
        episode_id=row["episode_id"],
        robot_model_id=row["robot_model_id"],
        factory_site=row.get("factory_site") or "unknown-site",
        gripper_type=row.get("gripper_type") or "unknown",
        target_object=row.get("target_object") or "unknown_object",
        operator_id=row.get("operator_id") or "unknown_operator",
        peak_torque=float(row.get("peak_torque_nm") or 0.0),
        motor_temp=float(row.get("mean_motor_temp_c") or 0.0),
        policy_family=row.get("policy_family") or "unknown_policy",
        mean_conf=float(row.get("mean_policy_confidence") or 0.0),
        min_conf=float(row.get("min_policy_confidence") or 0.0),
        n_steps=int(row.get("n_policy_steps") or 0),
        l2_err=float(row.get("trajectory_l2_error_m") or 0.0),
        duration=float(row.get("episode_duration_sec") or 0.0),
    )
    if bool(row.get("success_flag")):
        return _TEMPLATE_SUCCESS.format(**common)
    return _TEMPLATE_FAILURE.format(
        failure_type=row.get("failure_type_tag") or "UNKNOWN_FAILURE", **common
    )


def build_episode_summaries() -> list[dict]:
    """Read the Gold table, emit one dict per episode containing prose + metadata."""
    log.info("summary.build start")
    table: pa.Table = read_table_arrow("gold.vla_episodes")
    rows = table.to_pylist()
    out: list[dict] = []
    for row in rows:
        out.append(
            {
                "episode_id": row["episode_id"],
                "robot_model_id": row["robot_model_id"],
                "failure_type_tag": row.get("failure_type_tag"),
                "success_flag": bool(row.get("success_flag")),
                "gripper_type": row.get("gripper_type"),
                "policy_family": row.get("policy_family"),
                "text": _row_to_text(row),
            }
        )
    log.info("summary.build done n_summaries=%d", len(out))
    return out


def iter_summary_texts(summaries: list[dict]) -> Iterator[str]:
    for s in summaries:
        yield s["text"]
