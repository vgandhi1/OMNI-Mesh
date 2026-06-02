import pytest

from config.profiles import REGISTRY, MeshProfile
from data_platform import policies


@pytest.mark.parametrize("dialect", policies.DIALECTS)
def test_render_policy_covers_sensitive_columns(dialect, monkeypatch):
    # Default profile is ROBOTICS (conftest); check each sensitive column appears.
    sql = policies.render_policy(dialect)
    for column in REGISTRY[MeshProfile.ROBOTICS].sensitive_columns:
        assert column in sql


def test_snowflake_references_secret_manager():
    sql = policies.render_policy("snowflake")
    assert "SYSTEM$GET_SECRET" in sql  # salt never inlined
    assert "HMAC_SHA256" in sql


def test_unknown_dialect_raises():
    with pytest.raises(ValueError):
        policies.render_policy("oracle")


def test_health_profile_masks_patient_id(monkeypatch):
    monkeypatch.setenv("OMNI_MESH_PROFILE", "HEALTH_TECH")
    from config import settings

    settings.get_settings.cache_clear()
    sql = policies.render_policy("bigquery")
    assert "patient_id_hashed" in sql
