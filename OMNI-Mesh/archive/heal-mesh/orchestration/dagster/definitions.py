"""Dagster entry-point module.

Re-exports the ``Definitions`` object from ``mesh_assets`` so that
``dagster dev -m orchestration.dagster.definitions`` discovers everything.
"""

from orchestration.dagster.assets.mesh_assets import defs, heal_mesh_end_to_end

__all__ = ["defs", "heal_mesh_end_to_end"]
