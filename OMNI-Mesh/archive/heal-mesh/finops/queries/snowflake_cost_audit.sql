-- ============================================================================
-- HEAL-Mesh Phase 5 — Snowflake cost audit.
-- Source verbatim from the blueprint, with a domain-attribution column added
-- so the FinOps dashboard can carve spend by data product.
-- ============================================================================

SELECT
    query_id,
    user_name,
    warehouse_name,
    -- Derive the data product from the warehouse naming convention
    --   wh_telemetry_*  / wh_commercial_* / wh_clinical_*
    CASE
        WHEN warehouse_name ILIKE 'wh_telemetry%'  THEN 'telemetry_domain'
        WHEN warehouse_name ILIKE 'wh_commercial%' THEN 'commercial_domain'
        WHEN warehouse_name ILIKE 'wh_clinical%'   THEN 'clinical_domain'
        ELSE 'shared'
    END AS data_product,
    execution_time / 1000                       AS execution_time_seconds,
    credits_used_cloud_services * 3.50          AS estimated_dollar_cost,
    bytes_scanned / POWER(1024, 3)              AS gb_scanned
FROM snowflake.account_usage.query_history
WHERE execution_time / 1000 > 300              -- flags queries running > 5 min
  AND start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())
ORDER BY estimated_dollar_cost DESC
LIMIT 100;
