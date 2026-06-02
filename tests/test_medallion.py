"""Integration test: Bronze (Iceberg) -> dbt Silver/Gold -> back to Iceberg.

Runs a real ``dbt build`` against the polymorphic project for the ROBOTICS profile
(the default set by conftest), so it requires dbt-core + dbt-duckdb to be installed.
"""

import pytest

from config.profiles import REGISTRY, MeshProfile
from data_platform import catalog, generators, medallion


def _build_profile(profile: MeshProfile) -> dict[str, int]:
    spec = REGISTRY[profile]
    catalog.ensure_namespaces()
    batch = generators.make_bronze_batch(profile, n=24)
    catalog.write_data_product(
        catalog.NAMESPACE_BRONZE, spec.bronze_table, batch, expected_schema=spec.silver_schema
    )
    return medallion.run_medallion()


def test_medallion_builds_and_publishes_to_iceberg():
    spec = REGISTRY[MeshProfile.ROBOTICS]
    catalog.ensure_namespaces()
    batch = generators.make_bronze_batch(MeshProfile.ROBOTICS, n=12)
    catalog.write_data_product(
        catalog.NAMESPACE_BRONZE, spec.bronze_table, batch, expected_schema=spec.silver_schema
    )

    published = medallion.run_medallion()

    assert any(k == "silver.silver_robot_signals" for k in published)
    assert any(k == "gold.gold_robot_health" for k in published)

    gold = catalog.read_table_arrow("gold.gold_robot_health")
    assert gold.num_rows >= 1
    assert "robot_model_id" in gold.column_names
    assert "success_rate" in gold.column_names


@pytest.mark.parametrize(
    "profile, silver, gold",
    [
        (MeshProfile.COMMERCIAL, "silver_subscription_events", "gold_account_health"),
        (MeshProfile.CLINICAL, "silver_ecrf_observations", "gold_study_safety"),
    ],
)
def test_restored_health_subdomains_build(profile, silver, gold, monkeypatch):
    """The two heal-mesh sub-domains restored as profiles build + publish cleanly."""
    monkeypatch.setenv("OMNI_MESH_PROFILE", profile.value)
    from config import settings

    settings.get_settings.cache_clear()
    catalog.reset_catalog_cache()

    published = _build_profile(profile)

    assert f"silver.{silver}" in published
    assert f"gold.{gold}" in published


def test_clinical_gold_contains_no_raw_phi(monkeypatch):
    """The contract-enforced PHI guard keeps per-patient identifiers out of gold."""
    monkeypatch.setenv("OMNI_MESH_PROFILE", MeshProfile.CLINICAL.value)
    from config import settings

    settings.get_settings.cache_clear()
    catalog.reset_catalog_cache()

    _build_profile(MeshProfile.CLINICAL)

    gold = catalog.read_table_arrow("gold.gold_study_safety")
    forbidden = {"patient_id_hashed", "patient_id", "mrn", "ssn", "dob", "email", "full_name"}
    assert forbidden.isdisjoint(gold.column_names)
    assert "study_id" in gold.column_names
    assert "adverse_event_rate" in gold.column_names
