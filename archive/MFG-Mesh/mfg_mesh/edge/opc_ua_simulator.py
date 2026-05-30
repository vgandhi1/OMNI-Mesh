"""High-fidelity OPC UA telemetry simulator.

Generates messages shaped to match the spec:
  * `register_id` (e.g. CELL_WELD_TEMP_04)
  * `plc_timestamp_ms` (Unix epoch, millisecond resolution)
  * `sensor_payload` (numerical voltage / pressure / temperature)

We deliberately *inject* a small percentage of out-of-SLA values and the
occasional "new" sensor column so that downstream phases (data quality + schema
evolution) have something interesting to react to.
"""

from __future__ import annotations

import logging
import math
import random
import time
from dataclasses import asdict, dataclass, field
from typing import Iterator, List, Sequence

logger = logging.getLogger(__name__)


REGISTER_FAMILIES: tuple[str, ...] = (
    "CELL_WELD_TEMP",
    "PLC_ARM_VOLTAGE",
    "BATTERY_PRESSURE",
    "ROBOT_TORQUE",
)


@dataclass(frozen=True)
class SensorReading:
    """A single PLC register sample."""

    facility_id: str
    line_id: str
    register_id: str
    plc_timestamp_ms: int
    sensor_payload: dict[str, float]
    anomaly_flag: bool = False
    new_register_marker: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        # Iceberg / Arrow prefers JSON-like primitive maps.
        d["sensor_payload"] = dict(self.sensor_payload)
        return d


@dataclass
class OpcUaSimulator:
    """Deterministic-but-jittery telemetry generator.

    Args:
        facilities: Logical facility IDs (e.g. ``Texas_Giga_01``).
        lines_per_facility: How many lines each facility runs in parallel.
        registers_per_line: How many physical registers each line exposes.
        anomaly_rate: Fraction of readings that breach SLA thresholds.
        schema_drift_after: Inject a *new* register column after this many
            readings. Used to validate Phase 2 schema evolution.
        seed: Optional deterministic seed.
    """

    facilities: Sequence[str]
    lines_per_facility: int = 2
    registers_per_line: int = 4
    anomaly_rate: float = 0.05
    schema_drift_after: int | None = 200
    seed: int | None = None

    _counter: int = field(default=0, init=False, repr=False)
    _rng: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        if not 0.0 <= self.anomaly_rate <= 1.0:
            raise ValueError("anomaly_rate must be within [0, 1]")
        if self.lines_per_facility <= 0 or self.registers_per_line <= 0:
            raise ValueError("lines/registers per facility must be positive")

    # ------------------------------------------------------------------ utils

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _pick_register(self, register_idx: int) -> str:
        family = REGISTER_FAMILIES[register_idx % len(REGISTER_FAMILIES)]
        return f"{family}_{register_idx:02d}"

    def _payload(self, anomaly: bool, drift: bool) -> dict[str, float]:
        # Nominal centerlines with small Gaussian noise.
        voltage = self._rng.gauss(14.5, 0.2)
        temperature = self._rng.gauss(72.0, 3.0)
        pressure = self._rng.gauss(6.5, 0.5)
        if anomaly:
            # Bias one of the channels well past the SLA threshold.
            channel = self._rng.choice(["voltage", "temperature", "pressure"])
            if channel == "voltage":
                voltage = self._rng.choice([11.8, 16.6])
            elif channel == "temperature":
                temperature = self._rng.uniform(96.0, 110.0)
            else:
                pressure = self._rng.uniform(9.6, 11.0)
        payload = {
            "voltage": round(voltage, 3),
            "temperature_c": round(temperature, 3),
            "pressure_bar": round(pressure, 3),
        }
        if drift:
            # Simulate a new firmware push exposing skin conductance probes.
            payload["skin_conductance_us"] = round(self._rng.uniform(0.4, 1.2), 3)
        return payload

    # --------------------------------------------------------------- public API

    def emit_one(self) -> SensorReading:
        self._counter += 1
        facility = self.facilities[self._counter % len(self.facilities)]
        line_idx = (self._counter // len(self.facilities)) % self.lines_per_facility
        line_id = f"Line_{line_idx + 1:02d}"
        register_idx = self._counter % self.registers_per_line
        register_id = self._pick_register(register_idx)

        anomaly = self._rng.random() < self.anomaly_rate
        drift = (
            self.schema_drift_after is not None
            and self._counter > self.schema_drift_after
        )

        payload = self._payload(anomaly=anomaly, drift=drift)
        return SensorReading(
            facility_id=facility,
            line_id=line_id,
            register_id=register_id,
            plc_timestamp_ms=self._now_ms(),
            sensor_payload=payload,
            anomaly_flag=anomaly,
            new_register_marker=drift,
        )

    def stream(self, count: int) -> Iterator[SensorReading]:
        for _ in range(count):
            yield self.emit_one()

    def batch(self, count: int) -> List[SensorReading]:
        return list(self.stream(count))

    def reset(self) -> None:
        self._counter = 0
        self._rng = random.Random(self.seed)
