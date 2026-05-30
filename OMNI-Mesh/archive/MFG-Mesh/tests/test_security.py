"""Phase 5 fail-closed secret loading tests."""

from __future__ import annotations

import os

import pytest

from mfg_mesh.security import (
    InsecureConfigurationError,
    assert_platform_secrets,
    mask_identifier,
    reset_secret_cache,
)


def _set_salt(value: str | None) -> None:
    reset_secret_cache()
    if value is None:
        os.environ.pop("MFG_MESH_MASKING_SALT", None)
    else:
        os.environ["MFG_MESH_MASKING_SALT"] = value


def test_assert_platform_secrets_raises_on_missing():
    _set_salt(None)
    with pytest.raises(InsecureConfigurationError):
        assert_platform_secrets()


def test_assert_platform_secrets_raises_on_placeholder():
    _set_salt("local-dev-placeholder")
    with pytest.raises(InsecureConfigurationError):
        assert_platform_secrets()


def test_assert_platform_secrets_raises_on_short_salt():
    _set_salt("tiny")
    with pytest.raises(InsecureConfigurationError):
        assert_platform_secrets()


def test_assert_platform_secrets_passes_when_valid():
    _set_salt("a-strong-salt-value-" + "z" * 24)
    assert_platform_secrets()


def test_mask_identifier_is_deterministic_and_non_reversible():
    _set_salt("a-strong-salt-value-" + "z" * 24)
    a = mask_identifier("operator-42")
    b = mask_identifier("operator-42")
    c = mask_identifier("operator-43")
    assert a == b
    assert a != c
    assert "operator-42" not in a
    assert len(a) == 12
