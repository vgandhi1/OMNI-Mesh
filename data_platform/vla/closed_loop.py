"""Closed-loop: score deployed-policy inference on VLA episodes and log the
outcomes back into the Bronze tier (``bronze.live_inference``), so production
behaviour feeds the next training round — the Phase 6 pattern from RoboMesh.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass

import numpy as np
import pyarrow as pa

from data_platform import catalog

logger = logging.getLogger("omni_mesh.vla.closed_loop")

_FAILURE_TAGS = ("GRASP_FAIL", "OVER_TORQUE", "VISION_OCCLUSION", "PATH_PLAN_TIMEOUT", "MOTOR_OVERHEAT")
LIVE_TABLE = "live_inference"

# Explicit schema so an all-None failure_type_tag isn't inferred as a null column
# (which pyiceberg rejects).
_LIVE_SCHEMA = pa.schema(
    [
        ("inference_id", pa.string()),
        ("episode_id", pa.string()),
        ("robot_model_id", pa.string()),
        ("model_version", pa.string()),
        ("ts_us", pa.int64()),
        ("policy_confidence", pa.float64()),
        ("is_failure", pa.bool_()),
        ("failure_type_tag", pa.string()),
        ("deployment_env", pa.string()),
    ]
)


@dataclass(frozen=True)
class LiveInferenceEvent:
    inference_id: str
    episode_id: str
    robot_model_id: str
    model_version: str
    ts_us: int
    policy_confidence: float
    is_failure: bool
    failure_type_tag: str | None
    deployment_env: str


def _mock_policy_score(feature: np.ndarray) -> tuple[float, bool, str | None]:
    """Deterministic mock policy: confidence from the feature signal."""
    base = float(np.tanh(np.mean(feature) * 4.0))
    confidence = float(min(0.99, max(0.01, 0.5 + 0.45 * base)))
    is_failure = confidence < 0.55
    tag = _FAILURE_TAGS[int(abs(np.sum(feature) * 1000)) % len(_FAILURE_TAGS)] if is_failure else None
    return confidence, is_failure, tag


class InferenceLogger:
    """Buffered append-only writer for live inference events."""

    def __init__(self, *, flush_every: int = 64) -> None:
        self._buffer: list[dict] = []
        self._flush_every = flush_every

    def log(self, event: LiveInferenceEvent) -> None:
        self._buffer.append(asdict(event))
        if len(self._buffer) >= self._flush_every:
            self.flush()

    def flush(self) -> int:
        if not self._buffer:
            return 0
        arrow = pa.Table.from_pylist(self._buffer, schema=_LIVE_SCHEMA)
        catalog.ensure_namespaces([catalog.NAMESPACE_BRONZE])
        written = catalog.write_data_product(catalog.NAMESPACE_BRONZE, LIVE_TABLE, arrow)
        self._buffer.clear()
        return written


def run_closed_loop(*, model_version: str = "vla_diffusion_v3", deployment_env: str = "isaac_sim") -> int:
    """Score every VLA gold episode and append the inference events to Bronze."""
    gold = catalog.read_table_arrow("gold.vla_episodes")
    rows = gold.to_pylist()
    if not rows:
        return 0

    logger_ = InferenceLogger()
    for i, row in enumerate(rows):
        feature = np.asarray(row["vla_feature_vector"], dtype=np.float32)
        confidence, is_failure, tag = _mock_policy_score(feature)
        logger_.log(
            LiveInferenceEvent(
                inference_id=f"inf-{i:06d}",
                episode_id=row["episode_id"],
                robot_model_id=row["robot_model_id"],
                model_version=model_version,
                ts_us=int(time.time() * 1_000_000) + i,
                policy_confidence=confidence,
                is_failure=is_failure,
                failure_type_tag=tag,
                deployment_env=deployment_env,
            )
        )
    written = logger_.flush()
    logger.info("closed loop: logged %d inference events", written)
    return len(rows)
