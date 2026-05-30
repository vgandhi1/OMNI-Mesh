// HEAL-Mesh — GCP infrastructure stub for the clinical domain.

terraform {
  required_providers {
    google = { source = "hashicorp/google", version = "~> 5.0" }
  }
}

provider "google" {
  project = var.project
  region  = var.region
}

variable "project" { type = string }
variable "region"  { type = string, default = "us-central1" }

resource "google_storage_bucket" "clinical" {
  name                        = "healmesh-clinical-secure"
  location                    = upper(var.region)
  uniform_bucket_level_access = true
  versioning { enabled = true }
  encryption { default_kms_key_name = google_kms_crypto_key.clinical.id }
}

resource "google_kms_key_ring" "heal_mesh" {
  name     = "heal-mesh"
  location = var.region
}

resource "google_kms_crypto_key" "clinical" {
  name     = "clinical"
  key_ring = google_kms_key_ring.heal_mesh.id
  rotation_period = "7776000s" // 90 days
}

resource "google_bigquery_dataset" "clinical_bronze" {
  dataset_id    = "clinical_bronze"
  location      = upper(var.region)
  default_encryption_configuration {
    kms_key_name = google_kms_crypto_key.clinical.id
  }
}
