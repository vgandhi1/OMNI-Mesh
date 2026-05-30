"""Universal fail-closed compliance masking.

Merges the strongest guarantees from all three source projects:
- MFG-Mesh ``assert_platform_secrets`` (empty / insecure-default / min-length checks)
- OMNI-Mesh.md Phase 3 keyed HMAC-SHA256 tokenization barrier
- RoboMesh role-based unmask (``role == unmask_role`` returns plaintext)

If the masking salt is missing or a known placeholder, execution halts rather than
processing data with un-hashed visibility.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from functools import lru_cache

logger = logging.getLogger("omni_mesh.governance")

_MIN_SALT_LEN = 16
INSECURE_DEFAULTS = frozenset(
    {
        "",
        "local-dev-placeholder",
        "replace-me",
        "replace-me-with-a-secret-from-secret-manager",
        "changeme",
        "change-me",
        "please-change-me-in-production",
        "robomesh-local-dev-salt",
        "test",
        "secret",
    }
)


class InsecureConfigurationError(RuntimeError):
    """Raised when the masking salt is unset or insecure (fail-closed)."""


def _read_salt() -> str:
    return os.getenv("OMNI_MESH_MASKING_SALT", "").strip()


def assert_platform_secrets() -> None:
    """Crash unless a strong masking salt is configured."""
    salt = _read_salt()
    if not salt:
        raise InsecureConfigurationError(
            "CRITICAL COMPLIANCE BREACH: OMNI_MESH_MASKING_SALT is unset. "
            "Halting execution to prevent data leaks."
        )
    if salt in INSECURE_DEFAULTS or salt.startswith("replace-me"):
        raise InsecureConfigurationError(
            "CRITICAL COMPLIANCE BREACH: OMNI_MESH_MASKING_SALT is a known insecure placeholder."
        )
    if len(salt) < _MIN_SALT_LEN:
        raise InsecureConfigurationError(
            f"CRITICAL: OMNI_MESH_MASKING_SALT must be >= {_MIN_SALT_LEN} characters."
        )


@lru_cache(maxsize=1)
def _salt_bytes() -> bytes:
    assert_platform_secrets()
    return _read_salt().encode("utf-8")


def reset_secret_cache() -> None:
    """Clear the cached salt (test isolation hook)."""
    _salt_bytes.cache_clear()


def salt_status() -> str:
    """Human-readable status for ``omni-mesh doctor`` — never returns the salt."""
    try:
        assert_platform_secrets()
        return "valid"
    except InsecureConfigurationError:
        return "unset" if not _read_salt() else "placeholder/insecure"


def mask(
    plaintext: str | None,
    *,
    role: str | None = None,
    unmask_role: str | None = None,
    length: int = 16,
) -> str | None:
    """Return a deterministic keyed-HMAC token for ``plaintext``.

    Deterministic (same input + salt -> same token) so masked identifiers remain
    valid join keys across the lakehouse. When ``role`` matches ``unmask_role`` the
    plaintext is returned unchanged (privileged read).
    """
    if plaintext is None:
        return None
    if plaintext == "":
        return ""
    if unmask_role is not None and role == unmask_role:
        return plaintext
    digest = hmac.new(_salt_bytes(), plaintext.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"masked_sha256:{digest[:length]}"
