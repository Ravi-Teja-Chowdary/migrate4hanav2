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

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
}

# ─────────────────────────────────────────────
# S3 Bucket for Audit Logs (immutable, versioned)
# ─────────────────────────────────────────────
resource "aws_s3_bucket" "audit_logs" {
  bucket = "migrate4hana-audit-logs-${var.environment}-${local.account_id}"

  # Object Lock can only be turned ON at bucket creation. Required because the
  # aws_s3_bucket_object_lock_configuration resource below sets GOVERNANCE mode.
  object_lock_enabled = true

  tags = {
    Name        = "migrate4hana-audit-logs-${var.environment}"
    Component   = "Compliance"
    Environment = var.environment
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
      sse_algorithm = "aws:kms"
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

    # SOX requires 7 years retention; GxP may require longer
    expiration {
      days = 2555 # ~7 years
    }
  }
}

# S3 Object Lock for WORM compliance (prevents deletion). Object Lock requires
# versioning to be enabled FIRST — the explicit depends_on prevents the race
# where Terraform applies the lock config before versioning lands.
resource "aws_s3_bucket_object_lock_configuration" "audit_logs" {
  bucket = aws_s3_bucket.audit_logs.id

  rule {
    default_retention {
      mode = "GOVERNANCE"
      days = 2555
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
