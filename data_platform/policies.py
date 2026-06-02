"""Polymorphic row-/column-level security policy renderer.

Generates governance SQL (Snowflake / Databricks Unity Catalog / BigQuery) for the
active profile, driven by ``ProfileSpec.sensitive_columns``. This replaces the three
projects' hand-written, per-domain RLS files with one profile-aware generator: the
masking secret is always referenced from a secret manager (never inlined).
"""

from __future__ import annotations

from config.profiles import active_spec

DIALECTS = ("snowflake", "databricks", "bigquery")
_SILVER_TABLE = "silver"  # logical silver tier name for the active profile


def _snowflake(profile: str, columns: tuple[str, ...]) -> str:
    schema = f"omni_{profile.lower()}_silver"
    lines = [
        f"-- Snowflake masking policies for OMNI-Mesh profile {profile}",
        "USE ROLE DATA_GOVERNANCE_ADMIN;",
    ]
    for column in columns:
        lines += [
            "",
            f"CREATE OR REPLACE MASKING POLICY {schema}.mask_{column}",
            "  AS (val STRING) RETURNS STRING ->",
            "    CASE",
            "      WHEN CURRENT_ROLE() IN ('DATA_GOVERNANCE_ADMIN', 'SECURITY_OPERATIONS') THEN val",
            "      ELSE HEX_ENCODE(HMAC_SHA256(val, SYSTEM$GET_SECRET('omni_mesh.masking_salt')))",
            "    END;",
            f"ALTER TABLE {schema}.{_SILVER_TABLE}",
            f"  MODIFY COLUMN {column} SET MASKING POLICY {schema}.mask_{column};",
        ]
    return "\n".join(lines) + "\n"


def _databricks(profile: str, columns: tuple[str, ...]) -> str:
    schema = f"omni.{profile.lower()}_silver"
    masked = ",\n".join(
        f"    CASE WHEN is_account_group_member('security_operations') "
        f"THEN {c} ELSE NULL END AS {c}"
        for c in columns
    )
    passthrough = "    -- non-sensitive columns pass through unchanged"
    return (
        f"-- Databricks Unity Catalog dynamic view for OMNI-Mesh profile {profile}\n"
        f"CREATE OR REPLACE VIEW {schema}.silver_secure AS\n"
        f"SELECT\n{masked},\n{passthrough}\n"
        f"FROM {schema}.silver\n"
        f"WHERE is_account_group_member('data_governance_admins')\n"
        f"   OR is_account_group_member('security_operations');\n"
    )


def _bigquery(profile: str, columns: tuple[str, ...]) -> str:
    dataset = f"omni_{profile.lower()}_silver"
    tags = "\n".join(
        f"  ALTER COLUMN {c} SET OPTIONS "
        f"(policy_tags=['projects/_/locations/us/taxonomies/_/policyTags/omni-mesh-sensitive'])"
        + ("," if i < len(columns) - 1 else ";")
        for i, c in enumerate(columns)
    )
    return (
        f"-- BigQuery column-level security for OMNI-Mesh profile {profile}\n"
        f"ALTER TABLE `omni.{dataset}.silver`\n{tags}\n"
    )


_RENDERERS = {"snowflake": _snowflake, "databricks": _databricks, "bigquery": _bigquery}


def render_policy(dialect: str) -> str:
    """Render governance SQL for ``dialect`` and the active profile."""
    key = dialect.lower()
    if key not in _RENDERERS:
        raise ValueError(f"Unknown dialect {dialect!r}. Expected one of: {', '.join(DIALECTS)}")
    spec = active_spec()
    return _RENDERERS[key](spec.profile.value, spec.sensitive_columns)
