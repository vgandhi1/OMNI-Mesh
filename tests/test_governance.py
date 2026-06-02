import pytest

from data_platform import governance


@pytest.mark.parametrize("bad", ["", "replace-me", "changeme", "short"])
def test_insecure_salt_fails_closed(bad, monkeypatch):
    monkeypatch.setenv("OMNI_MESH_MASKING_SALT", bad)
    governance.reset_secret_cache()
    with pytest.raises(governance.InsecureConfigurationError):
        governance.assert_platform_secrets()


def test_valid_salt_passes():
    # The autouse fixture sets a strong salt.
    governance.assert_platform_secrets()
    assert governance.salt_status() == "valid"


def test_mask_is_deterministic_and_tagged():
    first = governance.mask("line-42")
    second = governance.mask("line-42")
    assert first == second
    assert first.startswith("masked_sha256:")
    assert governance.mask("line-43") != first


def test_role_based_unmask():
    out = governance.mask("classified", role="SECURITY_OPERATIONS", unmask_role="SECURITY_OPERATIONS")
    assert out == "classified"
    masked = governance.mask("classified", role="ML_RESEARCHER", unmask_role="SECURITY_OPERATIONS")
    assert masked.startswith("masked_sha256:")
