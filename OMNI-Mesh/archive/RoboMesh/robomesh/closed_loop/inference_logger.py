"""Pitfall #3 — close the loop: deployed VLA inference → Bronze tier.

When a trained PyTorch VLA model is deployed in simulation (Isaac Sim) or a
test factory floor, its inference confidence scores and failure events stream
right back into the RoboMesh Bronze tier under
``simulation.bronze_live_inference``. The next training run consumes them.

This module provides:

* :class:`LiveInferenceEvent` — typed event payload.
* :class:`InferenceLogger`   — append events into an Iceberg-managed table.
* :func:`simulate_live_inference` — replay Gold episodes through a (mock)
  policy to demonstrate the closed loop without a real robot.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Iterable

import numpy as np
import pyarrow as pa

from pyiceberg.exceptions import NoSuchTableError

from robomesh.catalog.iceberg import (
    ensure_namespaces,
    read_table_arrow,
    write_managed_table,
)
from robomesh.config import get_settings
from robomesh.logging_setup import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class LiveInferenceEvent:
    """One row in ``simulation.bronze_live_inference``."""

    inference_id: str
    episode_id: str
    robot_model_id: str
    factory_site: str
    policy_family: str
    model_version: str
    ts_us: int
    action_token_id: int
    policy_confidence: float
    is_failure: bool
    failure_type_tag: str | None
    deployment_env: str  # one of: "isaac_sim", "test_floor", "prod_floor"


class InferenceLogger:
    """Buffered Iceberg appender — flush periodically or on close."""

    def __init__(self, *, flush_every: int = 64) -> None:
        ensure_namespaces(extra=["simulation"])
        self._buf: list[dict] = []
        self._flush_every = flush_every
        log.info("closed_loop.logger.init flush_every=%d", flush_every)

    def __enter__(self) -> "InferenceLogger":
        return self

    def __exit__(self, *exc) -> None:
        self.flush()

    def log(self, event: LiveInferenceEvent) -> None:
        # NEVER log the full action / raw prompt — only outcome metadata,
        # in keeping with workspace-wide logging rules.
        log.debug(
            "closed_loop.event policy=%s model=%s conf=%.3f failure=%s",
            event.policy_family, event.model_version,
            event.policy_confidence, event.is_failure,
        )
        self._buf.append(asdict(event))
        if len(self._buf) >= self._flush_every:
            self.flush()

    def flush(self) -> int:
        if not self._buf:
            return 0
        arrow = pa.Table.from_pylist(self._buf)
        # Critical: only clear the buffer *after* a successful write. If the
        # Iceberg append fails (catalog locked, disk full, schema mismatch),
        # the buffer is preserved so the caller can retry without losing
        # the events that were recorded since the last flush.
        try:
            write_managed_table(
                "simulation",
                "bronze_live_inference",
                arrow,
                overwrite=False,  # append-only — this is Bronze
            )
        except Exception:
            log.error(
                "closed_loop.flush.failed buffered_n=%d (buffer retained)",
                len(self._buf),
            )
            raise
        n = len(self._buf)
        self._buf.clear()
        log.info("closed_loop.flush n=%d", n)
        return n


def _mock_policy_score(features: np.ndarray, success_prior: bool) -> tuple[float, bool, str | None]:
    """Deterministic mock policy — returns (confidence, is_failure, tag)."""
    # Use the mean of the feature vector as a noise source so different
    # embeddings → different scores. Successful priors stay high-confidence.
    base = float(np.tanh(np.mean(features) * 4.0 + (0.4 if success_prior else -0.1)))
    confidence = 0.5 + 0.45 * base
    is_failure = confidence < 0.55
    tag = None
    if is_failure:
        # Pick a deterministic failure tag from the feature hash.
        tags = ("GRASP_FAIL", "OVER_TORQUE", "VISION_OCCLUSION",
                "PATH_PLAN_TIMEOUT", "MOTOR_OVERHEAT")
        idx = int(abs(np.sum(features) * 1000)) % len(tags)
        tag = tags[idx]
    return confidence, is_failure, tag


def simulate_live_inference(
    *,
    model_version: str = "vla_diffusion_v3",
    deployment_env: str = "isaac_sim",
    n_steps_per_episode: int = 4,
) -> int:
    """Replay Gold episodes through a mock VLA policy, streaming results to Bronze.

    Returns the number of inference events written.
    """
    from robomesh.cv.tensor_store import get_tensor_store

    store = get_tensor_store()
    gold = read_table_arrow("gold.vla_episodes_v2")
    rows = gold.to_pylist()
    log.info(
        "closed_loop.simulate episodes=%d steps=%d env=%s model=%s",
        len(rows), n_steps_per_episode, deployment_env, model_version,
    )

    total_written = 0
    rng = np.random.default_rng(get_settings().seed + 99)
    with InferenceLogger(flush_every=128) as logger:
        for row in rows:
            uri = row.get("mean_embedding_uri")
            if not uri:
                continue
            try:
                features = store.read(uri)
            except FileNotFoundError:
                continue
            now_us = int(time.time() * 1_000_000)
            for step in range(n_steps_per_episode):
                jitter = rng.normal(0.0, 0.02, size=features.shape).astype(np.float32)
                conf, is_failure, tag = _mock_policy_score(
                    features + jitter, bool(row.get("success_flag"))
                )
                event = LiveInferenceEvent(
                    inference_id=f"inf_{row['episode_id']}_{step:03d}",
                    episode_id=row["episode_id"],
                    robot_model_id=row.get("robot_model_id") or "unknown",
                    factory_site=row.get("factory_site") or "unknown",
                    policy_family=row.get("policy_family") or "unknown",
                    model_version=model_version,
                    ts_us=now_us + step * 50_000,
                    action_token_id=int(rng.integers(0, 8192)),
                    policy_confidence=float(conf),
                    is_failure=bool(is_failure),
                    failure_type_tag=tag,
                    deployment_env=deployment_env,
                )
                logger.log(event)
                total_written += 1

    log.info("closed_loop.done n_events=%d", total_written)
    return total_written


def closed_loop_summary() -> dict[str, int | float | str]:
    """Quick summary suitable for Dagster asset metadata.

    The error-status separation matters for Dagster lineage UI: returning
    ``{"n_events": 0}`` on a *broken* catalog produces a green tile that
    looks identical to "no events yet", which masks data loss. We split
    the no-table-yet case (expected on first run) from any other failure
    (catalog corruption, schema mismatch, etc.) so the dashboard surfaces
    the difference. (REVIEW_FEEDBACK.md Issue 11 follow-up.)
    """
    try:
        table = read_table_arrow("simulation.bronze_live_inference")
    except NoSuchTableError:
        return {"n_events": 0, "n_failures": 0, "status": "no_table_yet"}
    except Exception as exc:  # noqa: BLE001 — catalog/IO failures bubble up via status
        # Logging rule §2 — never echo the raw exception to callers; we log
        # only the type name on the server side.
        log.error("closed_loop.summary.error type=%s", type(exc).__name__)
        return {"n_events": -1, "n_failures": -1, "status": "error"}
    failures = sum(1 for r in table["is_failure"].to_pylist() if r)
    confidences = [c for c in table["policy_confidence"].to_pylist() if c is not None]
    mean_conf = float(np.mean(confidences)) if confidences else 0.0
    return {
        "n_events": int(table.num_rows),
        "n_failures": int(failures),
        "mean_confidence": round(mean_conf, 4),
        "status": "ok",
    }
