###############################################################################
# Migrate4HANA — Evidence Ledger Module (Waves 6 / 7 / 8 / 10)
#
# Provisions:
#   1. KMS CMK for at-rest encryption of all migrate4hana data
#   2. S3 bucket with Object Lock COMPLIANCE for hash-chained evidence
#   3. m4h-run-events-<env>           — append-only event ledger (Wave 7)
#   4. m4h-recon-tolerance-<env>      — reconciliation tolerance policy (Wave 8)
#   5. m4h-mc-compatibility-matrix-<env> — MC OData per-release matrix (Wave 10)
###############################################################################

variable "environment" { type = string }
variable "retention_years" {
  type        = number
  default     = 7
  description = "Object Lock COMPLIANCE retention in years (SOX = 7)"
}

data "aws_caller_identity" "current" {}

locals {
  account_id      = data.aws_caller_identity.current.account_id
  evidence_bucket = "migrate4hana-evidence-${var.environment}-${local.account_id}"
}

# ── Wave 6 — KMS Customer-Managed Key ────────
resource "aws_kms_key" "m4h" {
  description             = "Migrate4HANA CMK (${var.environment})"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnableRootAccess"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${local.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "AllowAWSServices"
        Effect    = "Allow"
        Principal = { Service = ["dynamodb.amazonaws.com", "s3.amazonaws.com", "logs.amazonaws.com"] }
        Action    = ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:DescribeKey"]
        Resource  = "*"
      }
    ]
  })

  tags = {
    Component   = "EvidenceLedger"
    Environment = var.environment
    Compliance  = "SOX,GxP"
  }
}

resource "aws_kms_alias" "m4h" {
  name          = "alias/migrate4hana-${var.environment}"
  target_key_id = aws_kms_key.m4h.key_id
}

# ── Wave 7 — Evidence Bucket (Object Lock COMPLIANCE) ────────
resource "aws_s3_bucket" "evidence" {
  bucket              = local.evidence_bucket
  object_lock_enabled = true

  tags = {
    Component   = "EvidenceLedger"
    Environment = var.environment
    Compliance  = "SOX,GxP"
  }
}

resource "aws_s3_bucket_versioning" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_object_lock_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  rule {
    default_retention {
      mode = "COMPLIANCE"
      days = var.retention_years * 365
    }
  }
  depends_on = [aws_s3_bucket_versioning.evidence]
}

resource "aws_s3_bucket_server_side_encryption_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.m4h.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "evidence" {
  bucket                  = aws_s3_bucket.evidence.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_intelligent_tiering_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  name   = "ArchiveAccessTiering"

  tiering {
    access_tier = "ARCHIVE_ACCESS"
    days        = 90
  }
  tiering {
    access_tier = "DEEP_ARCHIVE_ACCESS"
    days        = 180
  }
}

# ── Wave 7 — Hash-chained run-events ledger ──
resource "aws_dynamodb_table" "run_events" {
  name         = "m4h-run-events-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "run_id"
  range_key    = "seq"

  attribute {
    name = "run_id"
    type = "S"
  }
  attribute {
    name = "seq"
    type = "N"
  }

  stream_enabled   = true
  stream_view_type = "NEW_IMAGE"

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.m4h.arn
  }

  tags = {
    Component   = "EvidenceLedger"
    Environment = var.environment
  }
}

# ── Wave 8 — Reconciliation tolerance policy ──
resource "aws_dynamodb_table" "recon_tolerance" {
  name         = "m4h-recon-tolerance-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "object_class"
  range_key    = "recon_type"

  attribute {
    name = "object_class"
    type = "S"
  }
  attribute {
    name = "recon_type"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.m4h.arn
  }

  tags = {
    Component   = "Reconciliation"
    Environment = var.environment
  }
}

# ── Wave 10 — Migration Cockpit compatibility matrix ──
resource "aws_dynamodb_table" "mc_compat" {
  name         = "m4h-mc-compatibility-matrix-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "release"
  range_key    = "object_id"

  attribute {
    name = "release"
    type = "S"
  }
  attribute {
    name = "object_id"
    type = "S"
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.m4h.arn
  }

  tags = {
    Component   = "MigrationCockpit"
    Environment = var.environment
  }
}

output "kms_key_arn" {
  value       = aws_kms_key.m4h.arn
  description = "Customer-managed KMS key for migrate4hana"
}

output "evidence_bucket_name" {
  value       = aws_s3_bucket.evidence.id
  description = "S3 bucket for hash-chained evidence (Object Lock COMPLIANCE)"
}

output "events_table_name" {
  value       = aws_dynamodb_table.run_events.name
  description = "DynamoDB table for run-events ledger"
}

output "recon_tolerance_table_name" {
  value       = aws_dynamodb_table.recon_tolerance.name
  description = "DynamoDB table for reconciliation tolerance policy"
}

output "mc_compat_table_name" {
  value       = aws_dynamodb_table.mc_compat.name
  description = "DynamoDB table for MC OData compatibility matrix"
}
