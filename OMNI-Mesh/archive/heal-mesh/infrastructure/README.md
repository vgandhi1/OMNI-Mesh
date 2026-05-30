# HEAL-Mesh — Infrastructure stubs

This directory is **not** required to run the local demo; it documents the
production-equivalent infrastructure that the local code is modeling.

## Cloud storage (Phase 1)

| Domain | Production bucket | Local equivalent |
| --- | --- | --- |
| Telemetry  | `s3://healmesh-telemetry-domain/`  | `data/lakehouse/warehouse/telemetry_domain.db/` |
| Commercial | `s3://healmesh-commercial-domain/` | `data/lakehouse/warehouse/commercial_domain.db/` |
| Clinical   | `s3://healmesh-clinical-secure/`   | `data/lakehouse/warehouse/clinical_domain.db/` |

The clinical bucket is provisioned with:
* SSE-KMS using a domain-specific CMK,
* deny-by-default bucket policy that allows only the
  `arn:aws:iam::*:role/clinical-research-*` and
  `arn:aws:iam::*:role/heal-mesh-pipeline-*` principals,
* object lock with a HIPAA-compliant retention window.

## Iceberg REST catalog (Phase 1)

We recommend [Apache Polaris](https://polaris.apache.org/) or
[Tabular.io](https://tabular.io). Both speak the open Iceberg REST spec, which
means Databricks, Snowflake, BigQuery, Trino, and DuckDB can all read from
them with zero data copies.

Terraform stubs for AWS (Glue catalog + S3) and GCP (BigLake metastore + GCS)
live under `terraform/` — they are placeholders to make the layout obvious;
fill them in for your real account.

## Networking & secrets

* PHI salt comes from AWS Secrets Manager (`arn:aws:secretsmanager:::secret:heal-mesh/phi-salt`)
  injected as `HEAL_MESH_PHI_SALT` at runtime; never baked into images.
* All cross-cloud traffic uses Private Link / VPC-SC. Public egress is blocked
  for the clinical workload.
* Cluster IAM roles follow least-privilege per the
  `authentication_authorization_rule` policy.
