-- ============================================================================
-- HEAL-Mesh Phase 3 — Snowflake row-level security policy.
--
-- Applies the blueprint's RLS pattern to the silver/gold clinical tables that
-- are surfaced into Snowflake via Iceberg external volumes. The policy keys
-- off the caller's CURRENT_ROLE() and the row's clinical study attribute.
--
-- Rule references:
--   * authentication_authorization_rule §2 — authorization happens on the
--     server side against the validated session role; the client cannot spoof
--     an identity into the policy.
--   * secure_sql §3 — no dynamic SQL; the only "dynamic" surface is the
--     enumerated CURRENT_ROLE() return value, which is allow-listed below.
-- ============================================================================

CREATE OR REPLACE ROW ACCESS POLICY healmesh.phi_security_policy
  AS (client_domain_id STRING) RETURNS BOOLEAN ->
       CURRENT_ROLE() = 'DATA_GOVERNANCE_ADMIN'
    OR (CURRENT_ROLE() = 'CLINICAL_RESEARCHER'
        AND client_domain_id IN ('CLINICAL_STUDY_01', 'CLINICAL_STUDY_02'))
    OR (CURRENT_ROLE() = 'BUSINESS_ANALYST' AND 1 = 0);
-- Business analysts are blocked from row-level PHI by construction.

-- Attach to the silver clinical table reading the Iceberg metadata.
ALTER ICEBERG TABLE healmesh.clinical_silver.silver_ecrf_patients
  ADD ROW ACCESS POLICY healmesh.phi_security_policy ON (study_id);

-- Column policy: surface hashed surrogates to non-clinical roles, raw values
-- to clinical research roles only.
--
-- Key construction notes:
--   * We use Snowflake's keyed HMAC (HMAC_SHA256) instead of the previous
--     suffix construction SHA2(val || $HEAL_MESH_PHI_SALT, 256). Suffix-
--     only hashing is weaker than HMAC for the same reason a prefix-only
--     construction would be: it lacks the two-pass keyed cancellation that
--     HMAC relies on. SHA-256 is not vulnerable to the classic length-
--     extension attack, but the HIPAA convention is "always HMAC".
--   * The salt is sourced from a Snowflake Secret (preferred) rather than
--     a session variable. Session variables silently substitute NULL when
--     unset, which would produce SHA2(val || NULL) = NULL — masking would
--     "succeed" but emit NULLs that are easy to confuse with absent data.
--     A SECRET cannot be unset without the role catching it.
CREATE OR REPLACE MASKING POLICY healmesh.phi_email_mask
  AS (val STRING) RETURNS STRING ->
    CASE
      WHEN CURRENT_ROLE() IN ('DATA_GOVERNANCE_ADMIN', 'CLINICAL_RESEARCHER') THEN val
      -- HEX_ENCODE(HMAC_SHA256(...)) → 64-char hex digest. SYSTEM$GET_PRIVATELINK
      -- replaced by SECRETS-API binding once the Snowflake Secret is created
      -- with: CREATE SECRET healmesh.phi_salt TYPE = GENERIC_STRING SECRET_STRING = '...';
      ELSE HEX_ENCODE(
        HMAC_SHA256(val, SYSTEM$GET_SECRET('healmesh.phi_salt'))
      )
    END;

ALTER ICEBERG TABLE healmesh.clinical_bronze.ecrf_patients_bronze
  MODIFY COLUMN email SET MASKING POLICY healmesh.phi_email_mask;

-- ----------------------------------------------------------------------------
-- Compatibility shim: HMAC_SHA256 SQL UDF
--
-- Older Snowflake editions / accounts without HMAC enabled can register the
-- following Python UDF and reference ``healmesh.hmac_sha256`` from the
-- masking policy above. Hash logic is identical to ``hmac.new(key, msg,
-- sha256).hexdigest()`` in the application layer (see
-- ``robomesh/governance/masking.py``), so the cross-environment swap is
-- mechanical.
--
--   CREATE OR REPLACE FUNCTION healmesh.hmac_sha256(msg STRING, key STRING)
--     RETURNS STRING
--     LANGUAGE PYTHON
--     RUNTIME_VERSION = '3.10'
--     HANDLER = 'compute'
--   AS $$
--     import hmac, hashlib
--     def compute(msg, key):
--         if msg is None or key is None:
--             return None
--         return hmac.new(
--             key.encode('utf-8'),
--             msg.encode('utf-8'),
--             hashlib.sha256,
--         ).hexdigest()
--   $$;
-- ----------------------------------------------------------------------------
