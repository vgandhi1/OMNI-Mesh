{{ config(materialized='view', schema='bronze') }}

-- This view is a placeholder for the upstream Iceberg bronze table. In
-- production it would point at the Iceberg REST catalog through an external
-- DuckDB extension; for the local reference platform we let the Dagster
-- bronze asset materialize a parquet snapshot at the path below and read it
-- back here. This keeps the dbt project runnable independently for CI.

SELECT *
FROM read_parquet('{{ env_var("MFG_MESH_BRONZE_PARQUET", "../.mfg_mesh/dbt_bronze_snapshot.parquet") }}')
