###############################################################################
# Migrate4HANA — Audit Module
# CloudTrail + S3 audit log bucket for SOX, GxP, and enterprise compliance
###############################################################################

variable "environment" {
  type = string
}

variable "region" {
  type = string
}

# ─────────────────────────────────────────────
# Governance toggles (F6)
# ─────────────────────────────────────────────
# Object Lock enables WORM (write-once-read-many) for SOX/SOC2 audit retention.
# Default true keeps existing prod behavior. Dev/staging sandboxes that need
# fast tfdestroy cycles can flip this to false at terraform.tfvars level.
# IMPORTANT: Object Lock on/off is a CREATION-time bucket attribute. Changing
# this on an existing bucket triggers replacement — be deliberate.
variable "object_lock_enabled" {
  type        = bool
  default     = true
  description = "Enable S3 Object Lock + 7-year GOVERNANCE retention on the audit-logs bucket. true = SOX-defensible, false = bucket can be emptied/destroyed cleanly."
}

# Optional Customer-Managed KMS key (CMK) for audit-logs bucket encryption.
# Empty string = use AWS-managed s3 key (default aws:kms). Pass the CMK ARN
# to gain key-policy control, key rotation visibility, and CloudTrail key-usage
# events for compliance.
variable "kms_key_arn" {
  type        = string
  default     = ""
  description = "ARN of a customer-managed KMS key to encrypt audit-logs bucket. Empty = AWS-managed aws/s3 key."
}

# Days of audit-log retention before the lifecycle policy expires objects.
# SOX = 2555 (7 years). GxP / SOC2 / GDPR may need longer; tune per regime.
variable "audit_retention_days" {
  type        = number
  default     = 2555
  description = "Days to retain audit logs before lifecycle expiration. 2555 = ~7 years (SOX default)."
}

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
}

# ─────────────────────────────────────────────
# S3 Bucket for Audit Logs (immutable, versioned)
# ─────────────────────────────────────────────
resource "aws_s3_bucket" "audit_logs" {
  bucket = "migrate4hana-audit-logs-${var.environment}-${local.account_id}"

  # Object Lock can only be turned ON at bucket creation. The conditional Lock
  # Configuration resource below only creates the WORM retention rule when this
  # bucket-level attribute is true.
  object_lock_enabled = var.object_lock_enabled

  tags = {
    Name        = "migrate4hana-audit-logs-${var.environment}"
    Component   = "Compliance"
    Environment = var.environment
    ObjectLock  = var.object_lock_enabled ? "enabled-WORM" : "disabled-destroyable"
  }
}

resource "aws_s3_bucket_versioning" "audit_logs" {
  bucket = aws_s3_bucket.audit_logs.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "audit_logs" {
  bucket = aws_s3_bucket.audit_logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      # Use the CMK when one is supplied; else fall back to the AWS-managed s3 key.
      # CMK = explicit rotation visibility, key-policy control, CloudTrail key events.
      kms_master_key_id = var.kms_key_arn != "" ? var.kms_key_arn : null
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "audit_logs" {
  bucket = aws_s3_bucket.audit_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "audit_logs" {
  bucket = aws_s3_bucket.audit_logs.id

  rule {
    id     = "archive-audit-logs"
    status = "Enabled"

    filter {}   # apply to all objects (required by aws provider v5)

    transition {
      days          = 90
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 365
      storage_class = "GLACIER"
    }

    # Configurable per-environment via var.audit_retention_days. SOX default = 7y.
    expiration {
      days = var.audit_retention_days
    }
  }
}

# S3 Object Lock for WORM compliance (prevents deletion). Only meaningful when
# the bucket itself was created with object_lock_enabled=true; gated by the
# same toggle so dev/staging sandboxes can opt out cleanly.
# Versioning must land FIRST — the explicit depends_on prevents that race.
resource "aws_s3_bucket_object_lock_configuration" "audit_logs" {
  count  = var.object_lock_enabled ? 1 : 0
  bucket = aws_s3_bucket.audit_logs.id

  rule {
    default_retention {
      mode = "GOVERNANCE"
      days = var.audit_retention_days
    }
  }

  depends_on = [aws_s3_bucket_versioning.audit_logs]
}

# ─────────────────────────────────────────────
# S3 Bucket Policy for CloudTrail
# ─────────────────────────────────────────────
resource "aws_s3_bucket_policy" "audit_logs" {
  bucket = aws_s3_bucket.audit_logs.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AWSCloudTrailAclCheck"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:GetBucketAcl"
        Resource  = aws_s3_bucket.audit_logs.arn
      },
      {
        Sid       = "AWSCloudTrailWrite"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.audit_logs.arn}/AWSLogs/${local.account_id}/*"
        Condition = {
          StringEquals = { "s3:x-amz-acl" = "bucket-owner-full-control" }
        }
      }
    ]
  })
}

# ─────────────────────────────────────────────
# CloudTrail — Comprehensive audit trail
# ─────────────────────────────────────────────
resource "aws_cloudtrail" "migration_audit" {
  name                          = "migrate4hana-audit-${var.environment}"
  s3_bucket_name                = aws_s3_bucket.audit_logs.id
  include_global_service_events = true
  is_multi_region_trail         = false
  enable_logging                = true
  enable_log_file_validation    = true

  # Log CloudWatch Logs for real-time alerting
  cloud_watch_logs_group_arn = "${aws_cloudwatch_log_group.audit.arn}:*"
  cloud_watch_logs_role_arn  = aws_iam_role.cloudtrail_cw.arn

  # Track all Lambda invocations
  event_selector {
    read_write_type           = "All"
    include_management_events = true

    data_resource {
      type = "AWS::Lambda::Function"
      # CloudTrail Lambda data-events only accept either exact function ARNs or
      # the bare prefix "arn:aws:lambda" (= all functions in the account). Wildcards
      # in the function-name portion are rejected with InvalidEventSelectorsException.
      values = ["arn:aws:lambda"]
    }
  }

  # Track S3 data access on staging bucket
  event_selector {
    read_write_type           = "All"
    include_management_events = false

    data_resource {
      type   = "AWS::S3::Object"
      values = ["arn:aws:s3:::migrate4hana-staging-${var.environment}/"]
    }
  }

  tags = {
    Name        = "migrate4hana-audit-${var.environment}"
    Component   = "Compliance"
    Compliance  = "SOX-GxP"
    Environment = var.environment
  }
}

# ─────────────────────────────────────────────
# CloudWatch Log Group for CloudTrail
# ─────────────────────────────────────────────
resource "aws_cloudwatch_log_group" "audit" {
  name              = "/migrate4hana/audit/${var.environment}"
  retention_in_days = 365

  tags = {
    Component   = "Compliance"
    Environment = var.environment
  }
}

# ─────────────────────────────────────────────
# IAM Role for CloudTrail → CloudWatch Logs
# ─────────────────────────────────────────────
resource "aws_iam_role" "cloudtrail_cw" {
  name = "migrate4hana-cloudtrail-cw-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "cloudtrail.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Component   = "Compliance"
    Environment = var.environment
  }
}

resource "aws_iam_role_policy" "cloudtrail_cw" {
  name = "cloudtrail-to-cloudwatch"
  role = aws_iam_role.cloudtrail_cw.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ]
      Resource = "${aws_cloudwatch_log_group.audit.arn}:*"
    }]
  })
}

# ─────────────────────────────────────────────
# CloudWatch Metric Filters — SOX-relevant events
# ─────────────────────────────────────────────

# Detect unauthorized API calls
resource "aws_cloudwatch_log_metric_filter" "unauthorized_api_calls" {
  name           = "migrate4hana-unauthorized-calls-${var.environment}"
  log_group_name = aws_cloudwatch_log_group.audit.name
  pattern        = "{ ($.errorCode = \"*UnauthorizedAccess*\") || ($.errorCode = \"AccessDenied*\") }"

  metric_transformation {
    name      = "UnauthorizedAPICalls"
    namespace = "Migrate4HANA/Compliance"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "unauthorized_api_calls" {
  alarm_name          = "migrate4hana-unauthorized-api-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "UnauthorizedAPICalls"
  namespace           = "Migrate4HANA/Compliance"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  alarm_description   = "SOX Alert: > 5 unauthorized API calls in 5 min"

  tags = {
    Compliance  = "SOX"
    Environment = var.environment
  }
}

# Detect Secrets Manager access (credential reads)
resource "aws_cloudwatch_log_metric_filter" "secrets_access" {
  name           = "migrate4hana-secrets-access-${var.environment}"
  log_group_name = aws_cloudwatch_log_group.audit.name
  pattern        = "{ ($.eventSource = \"secretsmanager.amazonaws.com\") && ($.eventName = \"GetSecretValue\") }"

  metric_transformation {
    name      = "SecretsManagerAccess"
    namespace = "Migrate4HANA/Compliance"
    value     = "1"
  }
}

# Detect IAM changes
resource "aws_cloudwatch_log_metric_filter" "iam_changes" {
  name           = "migrate4hana-iam-changes-${var.environment}"
  log_group_name = aws_cloudwatch_log_group.audit.name
  pattern        = "{ ($.eventSource = \"iam.amazonaws.com\") && (($.eventName = \"CreateRole\") || ($.eventName = \"DeleteRole\") || ($.eventName = \"AttachRolePolicy\") || ($.eventName = \"PutRolePolicy\")) }"

  metric_transformation {
    name      = "IAMPolicyChanges"
    namespace = "Migrate4HANA/Compliance"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "iam_changes" {
  alarm_name          = "migrate4hana-iam-changes-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "IAMPolicyChanges"
  namespace           = "Migrate4HANA/Compliance"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "SOX Alert: IAM role/policy change detected"

  tags = {
    Compliance  = "SOX"
    Environment = var.environment
  }
}

# Detect pipeline execution events
resource "aws_cloudwatch_log_metric_filter" "pipeline_executions" {
  name           = "migrate4hana-pipeline-exec-${var.environment}"
  log_group_name = aws_cloudwatch_log_group.audit.name
  pattern        = "{ ($.eventSource = \"states.amazonaws.com\") && ($.eventName = \"StartExecution\") }"

  metric_transformation {
    name      = "PipelineExecutions"
    namespace = "Migrate4HANA/Compliance"
    value     = "1"
  }
}

# ─────────────────────────────────────────────
# Outputs
# ─────────────────────────────────────────────
output "cloudtrail_arn" {
  value       = aws_cloudtrail.migration_audit.arn
  description = "CloudTrail ARN"
}

output "audit_bucket_name" {
  value       = aws_s3_bucket.audit_logs.id
  description = "S3 bucket for audit logs"
}

output "audit_log_group" {
  value       = aws_cloudwatch_log_group.audit.name
  description = "CloudWatch log group for audit events"
}
