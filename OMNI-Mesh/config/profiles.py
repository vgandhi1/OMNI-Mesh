"""Polymorphic profile schema engine.

A single environment variable, ``OMNI_MESH_PROFILE``, rewrites the active data
contracts, masking targets, and RAG vocabulary across the whole platform. Each
domain that used to be its own project (MFG-Mesh, RoboMesh, heal-mesh) is now a
``ProfileSpec`` entry in :data:`REGISTRY`.
"""

from __future__ import annotations

import enum
import os
from dataclasses import dataclass

import pyarrow as pa

# --- Domain vocabularies (distilled from the three source projects) ----------
ROBOT_MODELS: tuple[str, ...] = ("Figure-01", "Optimus-Gen2", "Atlas-Next", "Apollo-1")
FAILURE_TAGS: tuple[str, ...] = (
    "GRASP_FAIL",
    "OVER_TORQUE",
    "VISION_OCCLUSION",
    "PATH_PLAN_TIMEOUT",
    "MOTOR_OVERHEAT",
)
FACILITIES: tuple[str, ...] = ("Texas_Giga_01", "Berlin_Giga_02")
REGIONS: tuple[str, ...] = ("NA", "EU", "APAC")
# Commercial (CLV / churn) and clinical (eCRF / PHI) vocabularies — the two
# heal-mesh sub-domains restored as first-class OMNI-Mesh profiles.
PLAN_TIERS: tuple[str, ...] = ("FREE", "PRO", "ENTERPRISE")
STUDY_IDS: tuple[str, ...] = ("ONC-204", "CARD-118", "NEU-330")
AGE_BRACKETS: tuple[str, ...] = ("18-29", "30-45", "46-65", "66+")


class MeshProfile(enum.Enum):
    """The operational domains OMNI-Mesh can run as.

    ROBOTICS / MANUFACTURING / HEALTH_TECH are the original consolidation; COMMERCIAL
    (subscription CLV / churn) and CLINICAL (de-identified eCRF / PHI) restore the two
    heal-mesh sub-domains that the first cut dropped.
    """

    ROBOTICS = "ROBOTICS"
    MANUFACTURING = "MANUFACTURING"
    HEALTH_TECH = "HEALTH_TECH"
    COMMERCIAL = "COMMERCIAL"
    CLINICAL = "CLINICAL"


@dataclass(frozen=True)
class ProfileSpec:
    """Everything domain-specific the shared core needs to stay generic."""

    profile: MeshProfile
    bronze_table: str
    silver_schema: pa.Schema
    # Columns the generator masks via governance.mask (documentation + tests).
    sensitive_columns: tuple[str, ...]
    # metadata-field -> allowed terms, used for \b word-boundary RAG extraction.
    rag_vocab: dict[str, tuple[str, ...]]
    chroma_collection: str


_ROBOTICS = ProfileSpec(
    profile=MeshProfile.ROBOTICS,
    bronze_table="robot_signals",
    silver_schema=pa.schema(
        [
            ("timestamp", pa.timestamp("us")),
            ("robot_id", pa.string()),
            ("robot_model_id", pa.string()),
            ("joint_positions", pa.list_(pa.float32())),
            ("camera_frame_uri", pa.string()),
            ("failure_type_tag", pa.string()),
            ("success_flag", pa.bool_()),
        ]
    ),
    sensitive_columns=("robot_id",),
    rag_vocab={
        "failure_type_tag": FAILURE_TAGS,
        "robot_model_id": ROBOT_MODELS,
    },
    chroma_collection="robotics_episodes",
)

_MANUFACTURING = ProfileSpec(
    profile=MeshProfile.MANUFACTURING,
    bronze_table="plc_registers",
    silver_schema=pa.schema(
        [
            ("timestamp", pa.timestamp("us")),
            ("facility_id", pa.string()),
            ("register_id", pa.string()),
            ("measured_voltage", pa.float32()),
            ("temperature_c", pa.float32()),
            ("pressure_bar", pa.float32()),
            ("anomaly_flag", pa.bool_()),
        ]
    ),
    sensitive_columns=("register_id",),
    rag_vocab={
        "facility_id": FACILITIES,
    },
    chroma_collection="manufacturing_faults",
)

_HEALTH_TECH = ProfileSpec(
    profile=MeshProfile.HEALTH_TECH,
    bronze_table="wearable_biometrics",
    silver_schema=pa.schema(
        [
            ("timestamp", pa.timestamp("us")),
            ("patient_id_hashed", pa.string()),
            ("heart_rate_variability", pa.int32()),
            ("sleep_efficiency", pa.float32()),
            ("region", pa.string()),
        ]
    ),
    sensitive_columns=("patient_id_hashed",),
    rag_vocab={
        "region": REGIONS,
    },
    chroma_collection="health_cohort_narratives",
)


_COMMERCIAL = ProfileSpec(
    profile=MeshProfile.COMMERCIAL,
    bronze_table="subscription_events",
    silver_schema=pa.schema(
        [
            ("timestamp", pa.timestamp("us")),
            ("customer_id_hashed", pa.string()),
            ("plan_tier", pa.string()),
            ("region", pa.string()),
            ("monthly_revenue", pa.float32()),
            ("tenure_months", pa.int32()),
            ("churned_flag", pa.bool_()),
        ]
    ),
    sensitive_columns=("customer_id_hashed",),
    rag_vocab={
        "plan_tier": PLAN_TIERS,
        "region": REGIONS,
    },
    chroma_collection="commercial_accounts",
)

_CLINICAL = ProfileSpec(
    profile=MeshProfile.CLINICAL,
    bronze_table="ecrf_observations",
    silver_schema=pa.schema(
        [
            ("timestamp", pa.timestamp("us")),
            ("patient_id_hashed", pa.string()),
            ("study_id", pa.string()),
            ("age_bracket", pa.string()),
            ("region", pa.string()),
            ("adverse_event_flag", pa.bool_()),
        ]
    ),
    sensitive_columns=("patient_id_hashed",),
    rag_vocab={
        "study_id": STUDY_IDS,
        "region": REGIONS,
    },
    chroma_collection="clinical_ecrf_narratives",
)


REGISTRY: dict[MeshProfile, ProfileSpec] = {
    MeshProfile.ROBOTICS: _ROBOTICS,
    MeshProfile.MANUFACTURING: _MANUFACTURING,
    MeshProfile.HEALTH_TECH: _HEALTH_TECH,
    MeshProfile.COMMERCIAL: _COMMERCIAL,
    MeshProfile.CLINICAL: _CLINICAL,
}


def get_active_profile() -> MeshProfile:
    """Resolve the active profile from ``OMNI_MESH_PROFILE`` (default ROBOTICS)."""
    raw = os.getenv("OMNI_MESH_PROFILE", "ROBOTICS").strip().upper()
    try:
        return MeshProfile[raw]
    except KeyError as exc:
        valid = ", ".join(p.name for p in MeshProfile)
        raise ValueError(f"Unknown OMNI_MESH_PROFILE={raw!r}. Expected one of: {valid}") from exc


def active_spec() -> ProfileSpec:
    """Return the :class:`ProfileSpec` for the active profile."""
    return REGISTRY[get_active_profile()]


def get_silver_schema() -> pa.Schema:
    """Blueprint-compatibility accessor (OMNI-Mesh.md Phase 1)."""
    return active_spec().silver_schema
