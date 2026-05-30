"""Phase 5 security primitives: fail-closed secret loading and deterministic
masking utilities for sensitive identifiers (operator IDs, machine serials).

Design notes
------------
* The masking salt is required at boot. We refuse to start with an empty value
  or any of the well-known dev placeholders. This matches the spec's "fail
  closed" requirement and prevents accidentally hashing identifiers with a
  predictable salt in production.
* We use BLAKE2b with a per-process keyed digest. BLAKE2 is keyed-hash safe
  for this use case (deterministic pseudonymization, not authentication) and
  ships in the stdlib so we have no extra dependency surface.
* We never log the raw salt or the raw identifier; only the masked token
  (truncated) is ever returned to callers.
"""

from __future__ import annotations

import hashlib
import logging
import os
from functools import lru_cache
from typing import Iterable

logger = logging.getLogger(__name__)

INSECURE_DEFAULTS: frozenset[str] = frozenset(
    {
        "",
        "local-dev-placeholder",
        "replace-with-a-strong-random-secret",
        "changeme",
        "default",
        "test",
    }
)

_MIN_SALT_LEN = 16


class InsecureConfigurationError(RuntimeError):
    """Raised when the platform refuses to boot because secrets look unsafe."""


def assert_platform_secrets(env: dict[str, str] | None = None) -> None:
    """Fail-closed validation of platform secrets at boot.

    Mirrors the pattern documented in `mfg-mesh.md` Phase 5. If the masking
    salt is missing, too short, or set to a known placeholder, we raise a
    `InsecureConfigurationError` so the pipeline halts before touching data.
    """
    source = env if env is not None else os.environ
    salt = source.get("MFG_MESH_MASKING_SALT", "").strip()

    if not salt:
        raise InsecureConfigurationError(
            "CRITICAL: MFG_MESH_MASKING_SALT is not set. Halting infrastructure "
            "initialization to prevent unsalted identifier hashing."
        )
    if salt in INSECURE_DEFAULTS:
        raise InsecureConfigurationError(
            "CRITICAL: MFG_MESH_MASKING_SALT is using a known insecure default. "
            "Refusing to start."
        )
    if len(salt) < _MIN_SALT_LEN:
        raise InsecureConfigurationError(
            f"CRITICAL: MFG_MESH_MASKING_SALT must be >= {_MIN_SALT_LEN} characters."
        )
    # Intentionally do NOT log the salt value (Logging Security rule §1).
    logger.info("Platform secret check passed: masking salt is configured.")


@lru_cache(maxsize=1)
def _salt_bytes() -> bytes:
    assert_platform_secrets()
    return os.environ["MFG_MESH_MASKING_SALT"].encode("utf-8")


def mask_identifier(identifier: str, *, length: int = 12) -> str:
    """Deterministically mask a sensitive identifier.

    Returns the first `length` hex chars of BLAKE2b(identifier, key=salt).
    Two calls with the same input + salt yield the same output, which is what
    we need for joining masked records across the lakehouse without ever
    re-exposing the underlying value.
    """
    if not identifier:
        return ""
    if length <= 0 or length > 64:
        raise ValueError("mask length must be between 1 and 64 hex characters")
    digest = hashlib.blake2b(
        identifier.encode("utf-8"),
        key=_salt_bytes(),
        digest_size=32,
    ).hexdigest()
    return digest[:length]


def mask_many(identifiers: Iterable[str], *, length: int = 12) -> list[str]:
    return [mask_identifier(value, length=length) for value in identifiers]


def reset_secret_cache() -> None:
    """Test hook: clear cached salt so env changes take effect."""
    _salt_bytes.cache_clear()
