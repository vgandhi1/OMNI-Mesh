"""Tests for the Phase 1 OPC UA simulator."""

from __future__ import annotations

from mfg_mesh.edge.opc_ua_simulator import OpcUaSimulator, SensorReading


def test_simulator_emits_expected_fields():
    sim = OpcUaSimulator(facilities=["F1"], lines_per_facility=1, registers_per_line=2, seed=1)
    reading = sim.emit_one()
    assert isinstance(reading, SensorReading)
    assert reading.facility_id == "F1"
    assert reading.register_id.endswith(("00", "01", "02", "03"))
    assert {"voltage", "temperature_c", "pressure_bar"}.issubset(reading.sensor_payload.keys())
    assert reading.plc_timestamp_ms > 0


def test_simulator_is_deterministic_with_seed():
    a = OpcUaSimulator(facilities=["F1", "F2"], lines_per_facility=2, registers_per_line=4, seed=42).batch(50)
    b = OpcUaSimulator(facilities=["F1", "F2"], lines_per_facility=2, registers_per_line=4, seed=42).batch(50)
    assert [r.to_dict() for r in a] == [r.to_dict() for r in b]


def test_simulator_introduces_schema_drift_after_threshold():
    sim = OpcUaSimulator(
        facilities=["F1"],
        lines_per_facility=1,
        registers_per_line=1,
        anomaly_rate=0.0,
        schema_drift_after=5,
        seed=7,
    )
    readings = sim.batch(12)
    assert all("skin_conductance_us" not in r.sensor_payload for r in readings[:5])
    assert any("skin_conductance_us" in r.sensor_payload for r in readings[5:])


def test_anomaly_rate_bounds_validated():
    import pytest

    with pytest.raises(ValueError):
        OpcUaSimulator(facilities=["F1"], anomaly_rate=1.5)
