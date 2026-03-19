###############################################################################
# S3 Staging Module — Migration data staging & results storage
###############################################################################

variable "environment" { type = string }
variable "bucket_name" { type = string }

resource "aws_s3_bucket" "staging" {
  bucket = var.bucket_name
  tags   = { Name = "migrate4hana-staging-${var.environment}" }
}

resource "aws_s3_bucket_versioning" "staging" {
  bucket = aws_s3_bucket.staging.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "staging" {
  bucket = aws_s3_bucket.staging.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "staging" {
  bucket                  = aws_s3_bucket.staging.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "staging" {
  bucket = aws_s3_bucket.staging.id

  rule {
    id     = "archive-old-migrations"
    status = "Enabled"

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 90
      storage_class = "GLACIER"
    }

    expiration {
      days = 365
    }

    filter {
      prefix = "migrations/"
    }
  }
}

# Folder structure in the bucket
# migrations/{run-id}/
#   ├── discovery/          # Stage 1 outputs
#   │   ├── programs.json
#   │   ├── tables.json
#   │   ├── org-structure.json
#   │   ├── roles.json
#   │   └── integrations.json
#   ├── code-analysis/      # Stage 2 outputs
#   │   ├── issues.json
#   │   └── remediated/
#   ├── data/               # Stage 3 data exports
#   │   ├── finance/
#   │   ├── materials/
#   │   └── bp-conversion/
#   ├── config/             # Stage 4 config dumps
#   ├── roles/              # Stage 5 role exports
#   ├── integrations/       # Stage 6 mapping
#   └── reports/            # Final migration report

output "bucket_name" { value = aws_s3_bucket.staging.id }
output "bucket_arn" { value = aws_s3_bucket.staging.arn }
