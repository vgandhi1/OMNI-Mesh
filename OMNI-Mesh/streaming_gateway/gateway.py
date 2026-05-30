"""Throttled adaptive telemetry gateway.

Ingests high-frequency (500Hz) hardware signals replayed from the active profile's
lakehouse, batches them over a sliding window, and flushes a downsampled analytical
payload to WebSocket clients at a stable 30Hz — eliminating browser layout thrashing
while keeping the operator synchronized. The aggregation adapts to the profile:

    ROBOTICS       -> peak (max)  actuator torque
    MANUFACTURING  -> mean        bus-line voltage
    HEALTH_TECH    -> mean        heart-rate variability
"""

from __future__ import annotations

import asyncio
import itertools
import logging

import numpy as np
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from config.profiles import MeshProfile, active_spec, get_active_profile
from data_platform import catalog

logger = logging.getLogger("omni_mesh.gateway")

HF_HZ = 500
RENDER_HZ = 30
SAMPLES_PER_FRAME = max(1, round(HF_HZ / RENDER_HZ))  # ~17 high-freq samples per frame
FRAME_INTERVAL_S = 1.0 / RENDER_HZ

# profile -> (metric label, aggregation mode)
_PROFILE_METRIC = {
    MeshProfile.ROBOTICS: ("peak_torque_nm", "max"),
    MeshProfile.MANUFACTURING: ("mean_voltage_v", "mean"),
    MeshProfile.HEALTH_TECH: ("mean_hrv_ms", "mean"),
}

# profile -> ordered (namespace, table, column) candidates for the HF signal.
_SIGNAL_SOURCES = {
    MeshProfile.ROBOTICS: [("silver", "silver_robot_signals", "peak_joint_pos")],
    MeshProfile.MANUFACTURING: [
        ("silver", "silver_plc_registers", "measured_voltage"),
        ("bronze", "plc_registers", "measured_voltage"),
    ],
    MeshProfile.HEALTH_TECH: [
        ("silver", "silver_wearable_biometrics", "heart_rate_variability"),
        ("bronze", "wearable_biometrics", "heart_rate_variability"),
    ],
}


class SlidingWindowBuffer:
    """Buffers extreme real-time samples and downsamples to one render frame."""

    def __init__(self) -> None:
        self._points: list[float] = []

    def log_metric(self, value: float) -> None:
        self._points.append(float(value))

    def process_frame(self, profile: MeshProfile) -> dict:
        label, mode = _PROFILE_METRIC[profile]
        if not self._points:
            return {
                "profile": profile.value,
                "label": label,
                "metric_value": 0.0,
                "sample_count": 0,
                "status": "idle",
            }
        array = np.asarray(self._points, dtype=np.float64)
        self._points.clear()
        value = float(array.max() if mode == "max" else array.mean())
        return {
            "profile": profile.value,
            "label": label,
            "metric_value": round(value, 4),
            "sample_count": int(array.size),
            "status": "streaming",
        }


def build_frame(profile: MeshProfile, values: list[float]) -> dict:
    """Pure-function helper (used by tests): downsample ``values`` to one frame."""
    buffer = SlidingWindowBuffer()
    for value in values:
        buffer.log_metric(value)
    return buffer.process_frame(profile)


def _synthetic_signal(profile: MeshProfile, n: int = 256) -> list[float]:
    rng = np.random.default_rng(7)
    if profile == MeshProfile.ROBOTICS:
        return list(np.abs(rng.normal(2.0, 0.6, n)))
    if profile == MeshProfile.MANUFACTURING:
        return list(rng.normal(14.5, 0.4, n))
    return list(rng.normal(55.0, 12.0, n))


def load_signal_values(profile: MeshProfile) -> list[float]:
    """Replay buffer source: the profile's HF channel from the lakehouse (or synthetic)."""
    for namespace, table, column in _SIGNAL_SOURCES.get(profile, []):
        try:
            arrow = catalog.read_table_arrow(f"{namespace}.{table}")
        except Exception:
            continue
        if column in arrow.column_names:
            values = [float(v) for v in arrow.column(column).to_pylist() if v is not None]
            if values:
                return values

    # ROBOTICS Bronze stores joint_positions as a list; derive a peak per row.
    if profile == MeshProfile.ROBOTICS:
        try:
            arrow = catalog.read_table_arrow(f"bronze.{active_spec().bronze_table}")
            derived = [
                float(max(row)) for row in arrow.column("joint_positions").to_pylist() if row
            ]
            if derived:
                return derived
        except Exception:
            pass

    return _synthetic_signal(profile)


async def _health(request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def _profile(request) -> JSONResponse:
    profile = get_active_profile()
    label, mode = _PROFILE_METRIC[profile]
    return JSONResponse(
        {
            "profile": profile.value,
            "metric_label": label,
            "aggregation": mode,
            "hf_hz": HF_HZ,
            "render_hz": RENDER_HZ,
            "samples_per_frame": SAMPLES_PER_FRAME,
        }
    )


async def _telemetry(websocket: WebSocket) -> None:
    await websocket.accept()
    profile = get_active_profile()
    values = load_signal_values(profile)
    source = itertools.cycle(values) if values else None
    buffer = SlidingWindowBuffer()
    try:
        while True:
            # Enforce a strict 30Hz transmission cadence to keep the UI thread free.
            await asyncio.sleep(FRAME_INTERVAL_S)
            if source is not None:
                for _ in range(SAMPLES_PER_FRAME):
                    buffer.log_metric(next(source))
            await websocket.send_json(buffer.process_frame(profile))
    except (WebSocketDisconnect, RuntimeError):
        logger.info("telemetry client disconnected")


app = Starlette(
    routes=[
        Route("/health", _health),
        Route("/profile", _profile),
        WebSocketRoute("/ws/telemetry", _telemetry),
    ]
)
