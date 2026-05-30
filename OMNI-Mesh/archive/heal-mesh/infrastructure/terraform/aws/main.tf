// HEAL-Mesh — AWS infrastructure stub.
// This is intentionally minimal; production deployments should layer
// KMS, bucket policies, VPC endpoints, and CloudTrail logging on top.

terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = var.region
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "domain_buckets" {
  type = map(string)
  default = {
    telemetry  = "healmesh-telemetry-domain"
    commercial = "healmesh-commercial-domain"
    clinical   = "healmesh-clinical-secure"
  }
}

resource "aws_s3_bucket" "domain" {
  for_each = var.domain_buckets
  bucket   = each.value
}

resource "aws_s3_bucket_versioning" "domain" {
  for_each = aws_s3_bucket.domain
  bucket   = each.value.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "domain" {
  for_each = aws_s3_bucket.domain
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.heal_mesh.arn
    }
  }
}

resource "aws_kms_key" "heal_mesh" {
  description             = "HEAL-Mesh data-mesh CMK"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}

resource "aws_glue_catalog_database" "heal_mesh" {
  for_each = var.domain_buckets
  name     = "${each.key}_domain"
}
