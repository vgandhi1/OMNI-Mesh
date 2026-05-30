# Iceberg REST Catalog · Architecture notes

The HEAL-Mesh blueprint calls for a centralized, external REST catalog so that
Databricks, Snowflake, BigQuery, Trino, and DuckDB can all read the same
Iceberg tables without copying data between clouds.

## Recommended catalog implementations

| Catalog | Hosting | Strengths |
| --- | --- | --- |
| Apache Polaris | Self-host or managed | Open source, OSS-governed, vendor-neutral |
| Tabular.io | Managed SaaS | Zero-ops, built by the Iceberg creators |
| AWS Glue (Iceberg) | AWS managed | Native IAM, lowest friction for AWS-heavy stacks |
| Unity Catalog | Databricks managed | Tight Databricks/Unity integration |
| BigLake Metastore | GCP managed | Tight BigQuery/Spanner integration |

## Cross-cloud connectivity matrix

```
                          ┌─────────────────────────────┐
                          │   Iceberg REST Catalog       │
                          │   (Polaris / Tabular / Glue) │
                          └──────┬────────┬──────────────┘
                                 │        │
       ┌─────────────────────────┘        └──────────────────┐
       ▼                                                      ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Databricks  │  │   Snowflake  │  │   BigQuery   │  │ DuckDB/Trino │
│   (Spark)    │  │  External    │  │   BigLake    │  │  (local)     │
│              │  │   Volumes    │  │              │  │              │
└──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘
        │                │                  │                  │
        └────────────────┴──────────────────┴──────────────────┘
                                 │
                                 ▼
                  Same Iceberg metadata + Parquet files
                  (s3:// or gs:// — zero data movement)
```

In the local reference implementation the REST catalog is replaced by a
PyIceberg SQL catalog backed by SQLite under `data/lakehouse/catalog.db`,
which exposes the same `load_table()` / `create_namespace()` interface that
the production catalogs implement.
