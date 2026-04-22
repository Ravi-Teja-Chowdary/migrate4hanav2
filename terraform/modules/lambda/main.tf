###############################################################################
# Lambda Module — Migration engine functions
###############################################################################

variable "environment" { type = string }
variable "s3_staging_bucket" { type = string }
variable "s3_staging_arn" { type = string }
variable "vpc_id" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "secrets_arn" { type = string }
variable "telemetry_ws_endpoint" {
  type    = string
  default = ""
}
variable "telemetry_ws_connections_table" {
  type    = string
  default = ""
}
variable "telemetry_broadcast_policy_arn" {
  type    = string
  default = ""
}
variable "entity_resolution_workflow_arn" {
  type    = string
  default = ""
  description = "ARN of the AWS Entity Resolution matching workflow for BP dedup"
}
variable "bedrock_model_id" {
  type        = string
  default     = "anthropic.claude-3-sonnet-20240229-v1:0"
  description = "Bedrock foundation model ID for GenAI code analysis"
}
variable "ast_change_threshold" {
  type        = number
  default     = 3
  description = "If AST engine finds fewer changes than this, escalate to GenAI"
}
variable "llm_mode" {
  type        = string
  default     = "cloud"
  description = "GenAI routing mode: cloud, local, or dual"
}
variable "ollama_url" {
  type        = string
  default     = ""
  description = "Base URL of the on-prem Ollama server (e.g. http://10.0.2.123:11434). Empty disables local LLM path."
}
variable "ollama_model" {
  type        = string
  default     = "gemma2:27b"
  description = "Ollama model name to request from the air-gapped LLM server"
}
variable "lambda_functions" {
  type = map(object({
    description = string
    handler     = string
    runtime     = string
    timeout     = number
    memory      = number
    source_dir  = string
    layers      = list(string)
  }))
}

# ── IAM Role ─────────────────────────────────
resource "aws_iam_role" "lambda" {
  name = "migrate4hana-lambda-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "lambda" {
  name = "migrate4hana-lambda-policy"
  role = aws_iam_role.lambda.id

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
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          var.s3_staging_arn,
          "${var.s3_staging_arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = var.secrets_arn
      },
      {
        Effect = "Allow"
        Action = [
          "ec2:CreateNetworkInterface",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DeleteNetworkInterface"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "entityresolution:StartMatchingJob",
          "entityresolution:GetMatchingJob",
          "entityresolution:ListMatchingJobs"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = "arn:aws:bedrock:*::foundation-model/*"
      }
    ]
  })
}

# ── SNS Publish permission for SUM Orchestrator alerts ──
resource "aws_iam_role_policy" "lambda_sns_publish" {
  name = "migrate4hana-lambda-sns-publish"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sns:Publish"
        ]
        Resource = "*"
      }
    ]
  })
}

# Attach WebSocket telemetry broadcast policy (conditional)
resource "aws_iam_role_policy_attachment" "telemetry_broadcast" {
  count      = var.telemetry_broadcast_policy_arn != "" ? 1 : 0
  role       = aws_iam_role.lambda.name
  policy_arn = var.telemetry_broadcast_policy_arn
}

# ── Lambda Functions ─────────────────────────
data "archive_file" "lambda" {
  for_each    = var.lambda_functions
  type        = "zip"
  source_dir  = each.value.source_dir
  output_path = "${path.module}/dist/${each.key}.zip"
}

resource "aws_lambda_function" "migration" {
  for_each = var.lambda_functions

  function_name = "migrate4hana-${each.key}-${var.environment}"
  description   = each.value.description
  role          = aws_iam_role.lambda.arn
  handler       = each.value.handler
  runtime       = each.value.runtime
  timeout       = each.value.timeout
  memory_size   = each.value.memory

  filename         = data.archive_file.lambda[each.key].output_path
  source_code_hash = data.archive_file.lambda[each.key].output_base64sha256

  layers = each.value.layers

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = merge(
      {
        S3_STAGING_BUCKET = var.s3_staging_bucket
        SECRETS_ARN       = var.secrets_arn
        ENVIRONMENT       = var.environment
      },
      var.telemetry_ws_endpoint != "" ? {
        TELEMETRY_WS_ENDPOINT          = var.telemetry_ws_endpoint
        TELEMETRY_WS_CONNECTIONS_TABLE  = var.telemetry_ws_connections_table
      } : {},
      var.entity_resolution_workflow_arn != "" ? {
        ENTITY_RESOLUTION_WORKFLOW_ARN = var.entity_resolution_workflow_arn
      } : {},
      {
        BEDROCK_MODEL_ID      = var.bedrock_model_id
        AST_CHANGE_THRESHOLD  = tostring(var.ast_change_threshold)
        LLM_MODE              = var.llm_mode
        OLLAMA_MODEL          = var.ollama_model
      },
      var.ollama_url != "" ? { OLLAMA_URL = var.ollama_url } : {}
    )
  }

  tags = {
    Component = "MigrationEngine"
    Stage     = each.key
  }
}

resource "aws_security_group" "lambda" {
  name_prefix = "migrate4hana-lambda-"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "migrate4hana-lambda-${var.environment}" }
}

# ── Outputs ──────────────────────────────────
output "function_arns" {
  value = { for k, v in aws_lambda_function.migration : k => v.arn }
}

output "function_names" {
  value = { for k, v in aws_lambda_function.migration : k => v.function_name }
}

output "security_group_id" {
  value       = aws_security_group.lambda.id
  description = "Security group attached to the migration Lambdas (VPC-attached)"
}
