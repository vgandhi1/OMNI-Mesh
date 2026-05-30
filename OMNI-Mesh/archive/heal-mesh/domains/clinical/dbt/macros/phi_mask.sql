{#-
    Phase 3 — PHI cryptographic masking macro.

    Hashes a single column value with a keyed construction using the salt
    configured in ``HEAL_MESH_PHI_SALT``. Real deployments must pull the salt
    from a secret manager (AWS Secrets Manager, GCP Secret Manager, Vault)
    and rotate it on a defined cadence.

    Cryptographic construction by target adapter
    --------------------------------------------

    * ``snowflake`` → ``HMAC_SHA256(value, salt)`` (or a SQL UDF wrapper of
      the same). This is a true keyed HMAC, the production-grade
      construction. Snowflake exposes ``HMAC_SHA256`` via external functions
      / Snowflake-Crypto packages; teams that have not enabled it should
      register a one-line SQL UDF backed by JavaScript or Python that calls
      ``hmac.new(key, msg, sha256)`` (see ``governance/snowflake_hmac_udf.sql``).
    * ``duckdb`` (local demo) → ``sha256(salt || sha256(salt || value))``.
      DuckDB has **no native HMAC primitive**, which is a documented
      local-environment constraint. We approximate keyed hashing via a
      salted double-SHA: putting the salt as the *prefix* of the inner hash
      avoids the length-extension concern of the previous suffix
      construction (``sha256(value || salt)``), and the outer salted
      re-hash mirrors HMAC's two-pass shape. This is **only acceptable for
      the laptop demo** — production targets must be routed to Snowflake's
      ``HMAC_SHA256`` (or BigQuery's AEAD-keyed equivalent).

    Why not just ``sha256(value || salt)`` everywhere?
    --------------------------------------------------

    Suffix-only constructions (``H(m || k)``) are weaker than HMAC for the
    same reason that prefix-only constructions are: they do not provide
    the two-pass cancellation that HMAC's ``H((K^opad) || H((K^ipad) || m))``
    relies on for security in the random-oracle model. SHA-256 specifically
    is not vulnerable to the classic length-extension attack that broke
    SHA-1/MD5 suffix constructions, but the convention in HIPAA-bound
    pipelines is "always use HMAC" so the choice does not depend on which
    hash primitive is in use today.

    Rule references
    ---------------
    * authentication_authorization_rule §1, §2 — we never expose raw PHI
      to downstream domains; only the masked surrogate may cross domain
      boundaries.
    * logging_rule §1 — the macro fails fast if the salt is missing so we
      never silently emit predictable hashes.
-#}
{% macro phi_mask(column_name) -%}
    {%- set salt = var('phi_salt', '') -%}
    {%- if not salt or salt.startswith('replace-me') -%}
        {{ exceptions.raise_compiler_error(
            "HEAL_MESH_PHI_SALT is unset or still using the placeholder value. "
            "Configure a real salt via your secret manager before building the clinical models."
        ) }}
    {%- endif -%}
    {%- set adapter_type = target.type | lower -%}
    {%- if adapter_type == 'snowflake' -%}
        {#- Production: native keyed HMAC. -#}
        hex_encode(hmac_sha256(cast({{ column_name }} as varchar), '{{ salt }}'))
    {%- else -%}
        {#- DuckDB / local demo: salted double-SHA. NOT a true HMAC; see macro
            docstring for why this is acceptable for the demo only. -#}
        sha256('{{ salt }}' || sha256('{{ salt }}' || cast({{ column_name }} as varchar)))
    {%- endif -%}
{%- endmacro %}
