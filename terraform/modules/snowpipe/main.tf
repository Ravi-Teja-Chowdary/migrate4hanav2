###############################################################################
# Snowpipe -- auto-ingest of the WS4 SnowflakeSink JSONL stage
#
# Provisions the AWS side of a Snowpipe auto-ingest pipeline:
#   - SNS topic that Snowflake subscribes to (per Snowflake docs, this is how
#     Snowpipe learns of new files in an external stage on S3)
#   - S3 event notification on the existing snowflake-stage bucket -> SNS
#     for every JSONL PUT under the tenant/object path
#   - IAM role Snowflake assumes to READ the stage bucket (Storage Integration)
#   - CloudWatch metric alarm on stale files (SNS delivery failures)
#   - Optional verifier Lambda (snowpipe-verifier) that runs on a schedule,
#     hits the Snowflake information_schema.load_history view via a REST call,
#     and publishes a "rows_loaded_recent" CloudWatch metric per tenant/object
#
# Snowflake side (customer's DBA runs manually the first time; scripts under
# `scripts/snowpipe/` show the exact SQL):
#   - CREATE STORAGE INTEGRATION m4h_stage_int  (points at this IAM role)
#   - CREATE STAGE m4h_stage USING STORAGE INTEGRATION m4h_stage_int
#   - CREATE PIPE m4h_pipe AUTO_INGEST = TRUE ... (points at m4h_stage,
#     NOTIFICATION_CHANNEL = 'arn:aws:sns:...:snowpipe-notifications')
#
# The Snowflake side scripts live outside terraform because Snowflake DDL
# is not idempotently model-able via TF; a runbook + SQL template
# (scripts/snowpipe/snowflake_side.sql) is the operator's artefact.
###############################################################################

variable "deploy_snowpipe" {
  type    = bool
  default = false
}
variable "environment" { type = string }
variable "stage_bucket_name" {
  type        = string
  description = "The existing snowflake-stage bucket provisioned by the ws4 module."
}
variable "stage_prefix" {
  type        = string
  default     = "snowflake-stage/"
  description = "Prefix under which SnowflakeSink writes JSONL batches."
}
variable "snowflake_aws_account_id" {
  type        = string
  default     = ""
  description = "The AWS account ID Snowflake uses to assume this integration role. Empty = defer to trust policy override."
}
variable "snowflake_external_id" {
  type        = string
  default     = ""
  description = "External ID Snowflake provides after CREATE STORAGE INTEGRATION. Populate on second apply."
}
variable "deploy_verifier" {
  type    = bool
  default = true
}
variable "verifier_snowflake_account" {
  type        = string
  default     = ""
  description = "Snowflake account identifier (e.g. xyz-abc-us-east-1) for the verifier Lambda."
}
variable "verifier_snowflake_user" {
  type        = string
  default     = ""
  description = "Service user the verifier authenticates as."
}
variable "verifier_secret_arn" {
  type        = string
  default     = ""
  description = "Secrets Manager ARN holding the JSON {'private_key_pem': ..., 'passphrase': ...} for the verifier user."
}

locals {
  create = var.deploy_snowpipe
}

###############################################################################
# SNS topic -- Snowpipe notifications
###############################################################################
resource "aws_sns_topic" "snowpipe_notifications" {
  count             = local.create ? 1 : 0
  name              = "migrate4hana-snowpipe-notifications-${var.environment}"
  kms_master_key_id = "alias/aws/sns"
  tags = {
    Environment = var.environment
    Purpose     = "Snowpipe auto-ingest notifications"
    ManagedBy   = "migrate4hana"
  }
}

# The S3 bucket must be allowed to publish to the topic
resource "aws_sns_topic_policy" "snowpipe_notifications" {
  count = local.create ? 1 : 0
  arn   = aws_sns_topic.snowpipe_notifications[0].arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowS3PutEvents"
        Effect    = "Allow"
        Principal = { Service = "s3.amazonaws.com" }
        Action    = "SNS:Publish"
        Resource  = aws_sns_topic.snowpipe_notifications[0].arn
        Condition = {
          ArnLike = {
            "aws:SourceArn" = "arn:aws:s3:::${var.stage_bucket_name}"
          }
        }
      },
      {
        Sid    = "AllowSnowflakeSubscribe"
        Effect = "Allow"
        Principal = { AWS = var.snowflake_aws_account_id == ""
          ? "*"
        : "arn:aws:iam::${var.snowflake_aws_account_id}:root" }
        Action = [
          "SNS:Subscribe",
          "SNS:ListSubscriptionsByTopic",
          "SNS:GetTopicAttributes",
        ]
        Resource = aws_sns_topic.snowpipe_notifications[0].arn
      }
    ]
  })
}

###############################################################################
# S3 event notification on the stage bucket -> SNS
###############################################################################
resource "aws_s3_bucket_notification" "snowpipe_stage" {
  count  = local.create ? 1 : 0
  bucket = var.stage_bucket_name

  topic {
    topic_arn     = aws_sns_topic.snowpipe_notifications[0].arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = var.stage_prefix
    filter_suffix = ".jsonl"
  }

  depends_on = [aws_sns_topic_policy.snowpipe_notifications]
}

###############################################################################
# IAM role Snowflake Storage Integration assumes
###############################################################################
resource "aws_iam_role" "snowflake_stage_integration" {
  count = local.create ? 1 : 0
  name  = "migrate4hana-snowflake-stage-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        # Snowflake fills these values after CREATE STORAGE INTEGRATION on
        # their side. Populate via variables on the second apply. Until then
        # we start with a self-referencing trust to keep the resource valid.
        AWS = var.snowflake_aws_account_id == ""
          ? "arn:aws:iam::${data.aws_caller_identity.current[0].account_id}:root"
        : "arn:aws:iam::${var.snowflake_aws_account_id}:root"
      }
      Action = "sts:AssumeRole"
      Condition = var.snowflake_external_id == "" ? {} : {
        StringEquals = {
          "sts:ExternalId" = var.snowflake_external_id
        }
      }
    }]
  })

  tags = {
    Environment = var.environment
    Purpose     = "Snowflake stage integration"
    ManagedBy   = "migrate4hana"
  }
}

data "aws_caller_identity" "current" {
  count = local.create ? 1 : 0
}

resource "aws_iam_role_policy" "snowflake_stage_integration" {
  count = local.create ? 1 : 0
  name  = "stage-read"
  role  = aws_iam_role.snowflake_stage_integration[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion"
        ]
        Resource = "arn:aws:s3:::${var.stage_bucket_name}/${var.stage_prefix}*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetBucketLocation"
        ]
        Resource = "arn:aws:s3:::${var.stage_bucket_name}"
        Condition = {
          StringLike = {
            "s3:prefix" = ["${var.stage_prefix}*"]
          }
        }
      }
    ]
  })
}

###############################################################################
# Verifier Lambda -- rows-loaded metric per tenant/object
###############################################################################
resource "aws_iam_role" "verifier" {
  count = local.create && var.deploy_verifier ? 1 : 0
  name  = "migrate4hana-snowpipe-verifier-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "verifier" {
  count = local.create && var.deploy_verifier ? 1 : 0
  name  = "publish-metrics"
  role  = aws_iam_role.verifier[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = "cloudwatch:PutMetricData"
        Resource = "*"
        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = "Migrate4HANA/Snowpipe"
          }
        }
      },
      {
        Effect = "Allow"
        Action = "secretsmanager:GetSecretValue"
        Resource = var.verifier_secret_arn == "" ? "*" : var.verifier_secret_arn
      }
    ]
  })
}

resource "aws_lambda_function" "verifier" {
  count         = local.create && var.deploy_verifier ? 1 : 0
  function_name = "migrate4hana-snowpipe-verifier-${var.environment}"
  role          = aws_iam_role.verifier[0].arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.11"
  filename      = "${path.module}/../../..//lambda/snowpipe-verifier/verifier.zip"
  source_code_hash = filebase64sha256(
    "${path.module}/../../..//lambda/snowpipe-verifier/verifier.zip"
  )
  timeout     = 60
  memory_size = 256

  environment {
    variables = {
      SNOWFLAKE_ACCOUNT = var.verifier_snowflake_account
      SNOWFLAKE_USER    = var.verifier_snowflake_user
      SECRET_ARN        = var.verifier_secret_arn
      METRIC_NAMESPACE  = "Migrate4HANA/Snowpipe"
    }
  }

  lifecycle {
    ignore_changes = [filename, source_code_hash]
  }

  tags = {
    Environment = var.environment
    ManagedBy   = "migrate4hana"
  }
}

resource "aws_cloudwatch_event_rule" "verifier_cron" {
  count               = local.create && var.deploy_verifier ? 1 : 0
  name                = "migrate4hana-snowpipe-verifier-cron-${var.environment}"
  schedule_expression = "rate(15 minutes)"
}

resource "aws_cloudwatch_event_target" "verifier_cron" {
  count     = local.create && var.deploy_verifier ? 1 : 0
  rule      = aws_cloudwatch_event_rule.verifier_cron[0].name
  target_id = "verifier"
  arn       = aws_lambda_function.verifier[0].arn
}

resource "aws_lambda_permission" "verifier_cron" {
  count         = local.create && var.deploy_verifier ? 1 : 0
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.verifier[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.verifier_cron[0].arn
}

###############################################################################
# Alarm: SNS delivery failures (Snowflake side stalled)
###############################################################################
resource "aws_cloudwatch_metric_alarm" "sns_delivery_failed" {
  count               = local.create ? 1 : 0
  alarm_name          = "migrate4hana-snowpipe-sns-delivery-failed-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "NumberOfNotificationsFailed"
  namespace           = "AWS/SNS"
  period              = 300
  statistic           = "Sum"
  threshold           = 0

  dimensions = {
    TopicName = aws_sns_topic.snowpipe_notifications[0].name
  }

  alarm_description = "Snowpipe SNS notifications failing to deliver; auto-ingest is stalled."
  treat_missing_data = "notBreaching"
}

###############################################################################
# Outputs
###############################################################################
output "snowpipe_sns_topic_arn" {
  value = local.create ? aws_sns_topic.snowpipe_notifications[0].arn : ""
}
output "snowpipe_stage_integration_role_arn" {
  value = local.create ? aws_iam_role.snowflake_stage_integration[0].arn : ""
}
output "verifier_function_arn" {
  value = local.create && var.deploy_verifier ? aws_lambda_function.verifier[0].arn : ""
}
