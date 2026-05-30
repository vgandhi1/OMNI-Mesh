-- ============================================================================
-- HEAL-Mesh Phase 5 — Databricks system-table cost audit.
-- Joins billable usage with cluster/job metadata to attribute spend per
-- domain (telemetry / shared / etc).
-- ============================================================================

SELECT
    u.usage_date,
    u.workspace_id,
    j.run_name,
    -- Tag-based domain attribution. Job tags are set by the Dagster runner
    -- when it submits Spark jobs:  heal_mesh.domain=telemetry
    COALESCE(j.tags['heal_mesh.domain'], 'shared') AS data_product,
    SUM(u.usage_quantity)                          AS dbu_hours,
    SUM(u.usage_quantity) * 0.55                   AS estimated_dollar_cost
FROM system.billing.usage u
LEFT JOIN system.lakeflow.jobs j USING (workspace_id, job_id)
WHERE u.usage_date >= CURRENT_DATE() - INTERVAL 7 DAYS
GROUP BY u.usage_date, u.workspace_id, j.run_name, j.tags
ORDER BY estimated_dollar_cost DESC
LIMIT 100;
