"""Synthetic data generators that mimic real robotics ingest sources.

Each generator emits **Bronze**-shaped Parquet drops into
``data/raw/<domain>/...`` so the rest of the pipeline can be exercised end-to-
end without any cloud credentials.
"""

from robomesh.generators.teleop import generate_teleop_drops
from robomesh.generators.telemetry import generate_telemetry_drops
from robomesh.generators.simulation import generate_simulation_drops

__all__ = [
    "generate_teleop_drops",
    "generate_telemetry_drops",
    "generate_simulation_drops",
]
