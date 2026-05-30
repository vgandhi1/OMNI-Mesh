"""Streaming gateway tests: downsample math + profile labels + live WebSocket frame."""

from starlette.testclient import TestClient

from config.profiles import MeshProfile
from data_platform import catalog, generators
from streaming_gateway.gateway import (
    SAMPLES_PER_FRAME,
    app,
    build_frame,
    load_signal_values,
)


def test_robotics_downsamples_with_max():
    frame = build_frame(MeshProfile.ROBOTICS, [0.1, 0.9, 0.3])
    assert frame["metric_value"] == 0.9
    assert frame["label"] == "peak_torque_nm"
    assert frame["sample_count"] == 3


def test_manufacturing_downsamples_with_mean():
    frame = build_frame(MeshProfile.MANUFACTURING, [10.0, 20.0])
    assert frame["metric_value"] == 15.0
    assert frame["label"] == "mean_voltage_v"


def test_empty_window_is_idle():
    frame = build_frame(MeshProfile.HEALTH_TECH, [])
    assert frame["status"] == "idle"
    assert frame["metric_value"] == 0.0


def test_decimation_ratio():
    # 500Hz throttled to 30Hz -> ~17 high-frequency samples per render frame.
    assert SAMPLES_PER_FRAME == 17


def test_health_endpoint():
    client = TestClient(app)
    assert client.get("/health").json()["status"] == "ok"


def test_profile_endpoint_reports_metric():
    client = TestClient(app)
    body = client.get("/profile").json()
    assert body["profile"] == "ROBOTICS"  # conftest default
    assert body["samples_per_frame"] == SAMPLES_PER_FRAME


def test_signal_values_prefers_lakehouse():
    catalog.ensure_namespaces()
    batch = generators.make_bronze_batch(MeshProfile.MANUFACTURING, n=10)
    # write to the manufacturing bronze table name used by the gateway source list
    catalog.write_data_product(catalog.NAMESPACE_BRONZE, "plc_registers", batch)
    # default profile is ROBOTICS in conftest; switch to MANUFACTURING for this check
    import os

    os.environ["OMNI_MESH_PROFILE"] = "MANUFACTURING"
    try:
        values = load_signal_values(MeshProfile.MANUFACTURING)
    finally:
        os.environ["OMNI_MESH_PROFILE"] = "ROBOTICS"
    assert len(values) == 10


def test_websocket_streams_a_frame():
    client = TestClient(app)
    with client.websocket_connect("/ws/telemetry") as ws:
        frame = ws.receive_json()
    assert {"profile", "label", "metric_value", "status"} <= set(frame)
    assert frame["profile"] == "ROBOTICS"
