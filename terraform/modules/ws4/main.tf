###############################################################################
# WS4 -- Continuous Data Quality, Compliance Archive, Onboarding Bundle
#
# Bundles the three Lambdas + their persistence backing into one opt-in
# module so existing prod stacks see ZERO net-new resources until
# var.deploy_ws4 = true.
#
# When enabled, provisions (~16 resources):
#   - 3 Lambda functions:
#       * continuous-dq-monitor (cron + webhook)
#       * compliance-archive   (extract / extract_all / verify_chain)
#       * onboarding-bundle    (Client VPN tarball generator)
#   - 1 dedicated IAM role with restrictive policies
#   - 2 DynamoDB tables (PITR + SSE):
#       * dq-findings        hash=tenant_obj  range=ts
#       * compliance-ledger  hash=tenant_obj  range=ts
#   - 2 S3 buckets:
#       * compliance-archive WORM (Object Lock COMPLIANCE, 10-year default)
#       * snowflake-stage    (30-day lifecycle for Snowpipe ingest)
#   - 1 EventBridge schedule (daily DQ scan cron)
#   - 1 KMS key alias reuse (shared with the rest of the stack)
#   - 4 CloudWatch log groups with 30-day retention
#
# Tear-down: `terraform destroy -target=module.ws4`. The compliance
# archive bucket is Object Lock so its CONTENT survives even destroy
# until each object's retention expires -- the bucket itself can only
# be deleted once all objects are past retention.
#
# Wired in prod/main.tf via:
#   module "ws4" {
#     source = "../../modules/ws4"
#     deploy_ws4         = var.deploy_ws4
#     environment        = local.environment
#     vpc_id             = module.vpc.vpc_id
#     private_subnet_ids = module.vpc.private_subnet_ids
#     secrets_arn        = module.target_system.secrets_arn
#     kms_key_arn        = module.audit.kms_key_arn
#   }
###############################################################################

variable "deploy_ws4" {
  type    = bool
  default = false
}
variable "environment" { type = string }
variable "vpc_id" {
  type    = string
  default = ""
}
variable "private_subnet_ids" {
  type    = list(string)
  default = []
}
variable "secrets_arn" {
  type        = string
  default     = ""
  description = "S/4 / ECC connection secret reachable from the dq-monitor + compliance-archive Lambdas."
}
variable "kms_key_arn" {
  type        = string
  default     = ""
  description = "Customer-managed KMS key (shared with main stack). Empty = AES256 SSE only."
}
variable "compliance_retention_days" {
  type        = number
  default     = 3650 # 10 years
  description = "Object Lock retention floor (COMPLIANCE mode -- irrevocable for the configured horizon)."
}
variable "dq_scan_cron" {
  type        = string
  default     = "cron(0 6 * * ? *)" # 06:00 UTC daily
  description = "EventBridge schedule expression for the continuous DQ monitor scan."
}
variable "dq_scan_objects" {
  type        = list(string)
  default     = ["Material", "BusinessPartner", "PurchaseOrder", "SalesOrder", "Customer"]
  description = "Object types scanned on each DQ cron firing. Edit per-tenant via runtime input."
}
variable "vpn_endpoint_id" {
  type        = string
  default     = ""
  description = "Client VPN Endpoint ID feeding the onboarding-bundle .ovpn template. Optional."
}
variable "lambda_runtime" {
  type    = string
  default = "python3.11"
}
variable "lambda_memory" {
  type    = number
  default = 512
}
variable "lambda_timeout" {
  type    = number
  default = 300
}

locals {
  prefix      = "migrate4hana"
  archive_bkt = "${local.prefix}-compliance-archive-${var.environment}"
  stage_bkt   = "${local.prefix}-snowflake-stage-${var.environment}"
  dq_tbl      = "${local.prefix}-dq-findings-${var.environment}"
  ledger_tbl  = "${local.prefix}-compliance-ledger-${var.environment}"
  event_bus   = "${local.prefix}-data-fabric"
}

# ─────────────────────────────────────────────────────────────────────────────
# DynamoDB -- DQ findings + Compliance ledger
# ─────────────────────────────────────────────────────────────────────────────
resource "aws_dynamodb_table" "dq_findings" {
  count        = var.deploy_ws4 ? 1 : 0
  name         = local.dq_tbl
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "tenant_obj"
  range_key    = "ts"

  attribute {
    name = "tenant_obj"
    type = "S"
  }
  attribute {
    name = "ts"
    type = "N"
  }

  point_in_time_recovery {
    enabled = true
  }
  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn != "" ? var.kms_key_arn : null
  }
  deletion_protection_enabled = true

  tags = {
    Environment = var.environment
    Pillar      = "WS4-DQ-Monitor"
  }
}

resource "aws_dynamodb_table" "compliance_ledger" {
  count        = var.deploy_ws4 ? 1 : 0
  name         = local.ledger_tbl
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "tenant_obj"
  range_key    = "ts"

  attribute {
    name = "tenant_obj"
    type = "S"
  }
  attribute {
    name = "ts"
    type = "N"
  }

  point_in_time_recovery {
    enabled = true
  }
  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn != "" ? var.kms_key_arn : null
  }
  deletion_protection_enabled = true

  tags = {
    Environment = var.environment
    Pillar      = "WS4-Compliance-Archive"
  }
}

# ─────────────────────────────────────────────────────────────────────────────
# S3 -- Compliance archive (Object Lock COMPLIANCE) + Snowflake stage
# ─────────────────────────────────────────────────────────────────────────────
resource "aws_s3_bucket" "compliance_archive" {
  count               = var.deploy_ws4 ? 1 : 0
  bucket              = local.archive_bkt
  object_lock_enabled = true
  force_destroy       = false

  tags = {
    Environment = var.environment
    Pillar      = "WS4-Compliance-Archive"
    Retention   = "${var.compliance_retention_days}d-COMPLIANCE"
  }
}

resource "aws_s3_bucket_versioning" "compliance_archive" {
  count  = var.deploy_ws4 ? 1 : 0
  bucket = aws_s3_bucket.compliance_archive[0].id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_object_lock_configuration" "compliance_archive" {
  count      = var.deploy_ws4 ? 1 : 0
  bucket     = aws_s3_bucket.compliance_archive[0].id
  depends_on = [aws_s3_bucket_versioning.compliance_archive]

  rule {
    default_retention {
      mode = "COMPLIANCE"
      days = var.compliance_retention_days
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "compliance_archive" {
  count  = var.deploy_ws4 ? 1 : 0
  bucket = aws_s3_bucket.compliance_archive[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.kms_key_arn != "" ? "aws:kms" : "AES256"
      kms_master_key_id = var.kms_key_arn != "" ? var.kms_key_arn : null
    }
  }
}

resource "aws_s3_bucket_public_access_block" "compliance_archive" {
  count                   = var.deploy_ws4 ? 1 : 0
  bucket                  = aws_s3_bucket.compliance_archive[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket" "snowflake_stage" {
  count         = var.deploy_ws4 ? 1 : 0
  bucket        = local.stage_bkt
  force_destroy = true

  tags = {
    Environment = var.environment
    Pillar      = "WS4-Multi-Cloud-Sink"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "snowflake_stage" {
  count  = var.deploy_ws4 ? 1 : 0
  bucket = aws_s3_bucket.snowflake_stage[0].id

  rule {
    id     = "expire-staged-batches"
    status = "Enabled"

    filter {
      prefix = "snowflake-stage/"
    }

    expiration {
      days = 30 # Snowpipe should have ingested long before this
    }
  }
}

resource "aws_s3_bucket_public_access_block" "snowflake_stage" {
  count                   = var.deploy_ws4 ? 1 : 0
  bucket                  = aws_s3_bucket.snowflake_stage[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ─────────────────────────────────────────────────────────────────────────────
# IAM role -- dedicated, scoped to WS4 resources only
# ─────────────────────────────────────────────────────────────────────────────
resource "aws_iam_role" "ws4_lambda" {
  count = var.deploy_ws4 ? 1 : 0
  name  = "${local.prefix}-ws4-lambda-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = { Pillar = "WS4" }
}

resource "aws_iam_role_policy" "ws4_lambda" {
  count = var.deploy_ws4 ? 1 : 0
  name  = "${local.prefix}-ws4-lambda-policy"
  role  = aws_iam_role.ws4_lambda[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem",
          "dynamodb:Query", "dynamodb:Scan", "dynamodb:BatchWriteItem",
          "dynamodb:ConditionCheckItem", "dynamodb:DescribeTable"
        ]
        Resource = [
          aws_dynamodb_table.dq_findings[0].arn,
          aws_dynamodb_table.compliance_ledger[0].arn,
          # Allow the WS4 lambdas to update the key_map table too -- the
          # compliance archive registers per-row hashes back into F1 so
          # the operator can prove "the migrated row matches the archived row".
          "arn:aws:dynamodb:*:*:table/${local.prefix}-key-map-${var.environment}",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject", "s3:GetObject", "s3:ListBucket",
          "s3:PutObjectRetention", "s3:GetObjectRetention",
          "s3:PutObjectLegalHold", "s3:GetObjectLegalHold"
        ]
        Resource = [
          aws_s3_bucket.compliance_archive[0].arn,
          "${aws_s3_bucket.compliance_archive[0].arn}/*",
          aws_s3_bucket.snowflake_stage[0].arn,
          "${aws_s3_bucket.snowflake_stage[0].arn}/*"
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = compact([var.secrets_arn])
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*",
          "kms:GenerateDataKey*", "kms:DescribeKey"
        ]
        Resource = var.kms_key_arn != "" ? [var.kms_key_arn] : ["arn:aws:kms:*:*:key/__none__"]
      },
      {
        Effect = "Allow"
        Action = [
          "events:PutEvents"
        ]
        Resource = "arn:aws:events:*:*:event-bus/${local.event_bus}"
      },
      # VPC ENI lifecycle (Lambdas attach to private subnets)
      {
        Effect = "Allow"
        Action = [
          "ec2:CreateNetworkInterface",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DeleteNetworkInterface"
        ]
        Resource = "*"
      }
    ]
  })
}

# ─────────────────────────────────────────────────────────────────────────────
# Lambda functions
# ─────────────────────────────────────────────────────────────────────────────
locals {
  ws4_functions = var.deploy_ws4 ? {
    "continuous-dq-monitor" = {
      description = "WS4 pillar 1 -- continuous post-cutover DQ scan + webhook"
      source_dir  = "${path.module}/../../../lambda/continuous-dq-monitor"
      env_extra = {
        DQ_FINDINGS_TABLE = aws_dynamodb_table.dq_findings[0].name
        DEFAULT_OBJECTS   = join(",", var.dq_scan_objects)
      }
    }
    "compliance-archive" = {
      description = "WS4 pillar 2 -- immutable hash-chained WORM archive"
      source_dir  = "${path.module}/../../../lambda/compliance-archive"
      env_extra = {
        COMPLIANCE_ARCHIVE_BUCKET = aws_s3_bucket.compliance_archive[0].id
        COMPLIANCE_LEDGER_TABLE   = aws_dynamodb_table.compliance_ledger[0].name
        RETENTION_DAYS            = tostring(var.compliance_retention_days)
      }
    }
    "onboarding-bundle" = {
      description = "WS3 helper -- per-tenant VPN onboarding tarball generator"
      source_dir  = "${path.module}/../../../lambda/onboarding-bundle"
      env_extra = {
        VPN_ENDPOINT_ID         = var.vpn_endpoint_id
        ONBOARDING_BUNDLE_BUCKET = aws_s3_bucket.snowflake_stage[0].id
      }
    }
  } : {}
}

data "archive_file" "ws4" {
  for_each    = local.ws4_functions
  type        = "zip"
  source_dir  = each.value.source_dir
  output_path = "${path.module}/dist/${each.key}.zip"
}

resource "aws_security_group" "ws4_lambda" {
  count       = var.deploy_ws4 && var.vpc_id != "" ? 1 : 0
  name_prefix = "${local.prefix}-ws4-lambda-"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Pillar = "WS4" }
}

resource "aws_lambda_function" "ws4" {
  for_each = local.ws4_functions

  function_name = "${local.prefix}-${each.key}-${var.environment}"
  description   = each.value.description
  role          = aws_iam_role.ws4_lambda[0].arn
  handler       = "handler.lambda_handler"
  runtime       = var.lambda_runtime
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory

  filename         = data.archive_file.ws4[each.key].output_path
  source_code_hash = data.archive_file.ws4[each.key].output_base64sha256

  dynamic "vpc_config" {
    for_each = var.vpc_id != "" ? [1] : []
    content {
      subnet_ids         = var.private_subnet_ids
      security_group_ids = [aws_security_group.ws4_lambda[0].id]
    }
  }

  environment {
    variables = merge(
      {
        ENVIRONMENT          = var.environment
        SECRETS_ARN          = var.secrets_arn
        M4H_EVENT_BUS_NAME   = local.event_bus
        M4H_SNOWFLAKE_STAGE_BUCKET = aws_s3_bucket.snowflake_stage[0].id
      },
      each.value.env_extra
    )
  }

  tags = {
    Environment = var.environment
    Pillar      = "WS4"
    Function    = each.key
  }
}

resource "aws_cloudwatch_log_group" "ws4" {
  for_each          = local.ws4_functions
  name              = "/aws/lambda/${local.prefix}-${each.key}-${var.environment}"
  retention_in_days = 30
  kms_key_id        = var.kms_key_arn != "" ? var.kms_key_arn : null
}

# ─────────────────────────────────────────────────────────────────────────────
# EventBridge schedule -- daily DQ scan + custom bus for SinkRouter fan-out
# ─────────────────────────────────────────────────────────────────────────────
resource "aws_cloudwatch_event_bus" "data_fabric" {
  count = var.deploy_ws4 ? 1 : 0
  name  = local.event_bus
  tags  = { Pillar = "WS4" }
}

resource "aws_cloudwatch_event_rule" "dq_daily_scan" {
  count               = var.deploy_ws4 ? 1 : 0
  name                = "${local.prefix}-dq-daily-scan-${var.environment}"
  description         = "Daily continuous DQ scan against live S/4"
  schedule_expression = var.dq_scan_cron
}

resource "aws_cloudwatch_event_target" "dq_daily_scan" {
  count = var.deploy_ws4 ? 1 : 0
  rule  = aws_cloudwatch_event_rule.dq_daily_scan[0].name
  arn   = aws_lambda_function.ws4["continuous-dq-monitor"].arn

  input = jsonencode({
    mode    = "scan"
    objects = var.dq_scan_objects
  })
}

resource "aws_lambda_permission" "dq_daily_scan" {
  count         = var.deploy_ws4 ? 1 : 0
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ws4["continuous-dq-monitor"].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.dq_daily_scan[0].arn
}

# ─────────────────────────────────────────────────────────────────────────────
# Outputs -- consumed by prod/main.tf wiring + Group D dashboards
# ─────────────────────────────────────────────────────────────────────────────
output "dq_monitor_function_name" {
  value       = var.deploy_ws4 ? aws_lambda_function.ws4["continuous-dq-monitor"].function_name : ""
  description = "Name of the continuous DQ monitor Lambda."
}

output "compliance_archive_function_name" {
  value       = var.deploy_ws4 ? aws_lambda_function.ws4["compliance-archive"].function_name : ""
  description = "Name of the compliance archive Lambda."
}

output "onboarding_bundle_function_name" {
  value       = var.deploy_ws4 ? aws_lambda_function.ws4["onboarding-bundle"].function_name : ""
  description = "Name of the onboarding bundle Lambda."
}

output "compliance_archive_bucket" {
  value       = var.deploy_ws4 ? aws_s3_bucket.compliance_archive[0].id : ""
  description = "WORM bucket holding immutable per-tenant compliance archives."
}

output "snowflake_stage_bucket" {
  value       = var.deploy_ws4 ? aws_s3_bucket.snowflake_stage[0].id : ""
  description = "Snowflake/SinkRouter staging bucket."
}

output "dq_findings_table" {
  value       = var.deploy_ws4 ? aws_dynamodb_table.dq_findings[0].name : ""
  description = "DQ findings DDB table name."
}

output "compliance_ledger_table" {
  value       = var.deploy_ws4 ? aws_dynamodb_table.compliance_ledger[0].name : ""
  description = "Compliance archive hash-chained ledger table name."
}

output "ws4_function_names" {
  value       = var.deploy_ws4 ? [for k, v in aws_lambda_function.ws4 : v.function_name] : []
  description = "Full list of WS4 Lambda function names (for dashboard wiring)."
}

output "event_bus_name" {
  value       = var.deploy_ws4 ? aws_cloudwatch_event_bus.data_fabric[0].name : ""
  description = "Data Fabric custom event bus -- SinkRouter EventBusSink publishes here."
}

output "iam_role_arn" {
  value       = var.deploy_ws4 ? aws_iam_role.ws4_lambda[0].arn : ""
  description = "IAM role ARN for WS4 Lambdas (for cross-resource policy refs)."
}
