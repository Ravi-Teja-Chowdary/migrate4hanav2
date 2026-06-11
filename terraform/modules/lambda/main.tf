###############################################################################
# Lambda Module — Migration engine functions
###############################################################################

variable "environment" { type = string }
variable "s3_staging_bucket" { type = string }
variable "s3_staging_arn" { type = string }
variable "vpc_id" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "secrets_arn" { type = string }
variable "gates_table_name" {
  type        = string
  default     = ""
  description = "DynamoDB table name for manual-gate persistence (empty = use S3 fallback)"
}
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
  type        = string
  default     = ""
  description = "ARN of the AWS Entity Resolution matching workflow for BP dedup"
}
variable "anthropic_secret_arn" {
  type        = string
  default     = ""
  description = "ARN of the Secrets Manager secret holding the Anthropic API key. Empty disables the Anthropic path (Lambdas then rely on Bedrock if configured)."
}
variable "anthropic_model_id" {
  type        = string
  default     = "claude-sonnet-4-6"
  description = "Default Claude model for ABAP remediation via direct Anthropic API"
}
variable "anthropic_escalation_model" {
  type        = string
  default     = "claude-opus-4-7"
  description = "Claude model used on retry when the default fix fails the ATC gate"
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
    description   = string
    handler       = string
    runtime       = string
    timeout       = number
    memory        = number
    source_dir    = string
    layers        = list(string)
    architectures = optional(list(string), ["x86_64"])
  }))
}

# ── Wave 6/7/8 plumbing: audit ledger, reconciliation, evidence WORM bucket ──
variable "events_table_name" {
  type        = string
  default     = ""
  description = "DynamoDB table name for hash-chained run-events ledger (Wave 7)"
}
variable "recon_tolerance_table_name" {
  type        = string
  default     = ""
  description = "DynamoDB table name for reconciliation tolerance policy (Wave 8)"
}
variable "evidence_bucket_name" {
  type        = string
  default     = ""
  description = "S3 bucket (Object Lock COMPLIANCE) for immutable evidence (Wave 7)"
}
variable "kms_key_arn" {
  type        = string
  default     = ""
  description = "Customer-managed KMS key ARN for at-rest encryption (Wave 6)"
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
        Resource = compact([
          var.secrets_arn,
          var.anthropic_secret_arn,
        ])
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
      # NOTE: bedrock:InvokeModel removed - this stack uses the direct Anthropic
      # API (api.anthropic.com via NAT egress, key in Secrets Manager). To
      # re-enable Bedrock later, restore this block and the bedrock_runtime
      # VPC endpoint in modules/vpc-endpoints.
      # Lambda-to-Lambda chained invocation (two-plane orchestrators).
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = "arn:aws:lambda:*:*:function:migrate4hana-*"
      },
      # Step Functions task-token completion (manual gate self-recovery).
      # Scoped to migrate4hana state machines in this account/region.
      {
        Effect   = "Allow"
        Action   = ["states:SendTaskSuccess", "states:SendTaskFailure", "states:SendTaskHeartbeat"]
        Resource = "arn:aws:states:*:*:stateMachine:migrate4hana-*"
      },
      # DynamoDB - migrate4hana tables only (gates, run-events, recon-tolerance,
      # mc-compatibility-matrix). Indexes covered by the trailing /index/* arn.
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem",
          "dynamodb:Query", "dynamodb:Scan", "dynamodb:BatchGetItem",
          "dynamodb:BatchWriteItem", "dynamodb:ConditionCheckItem"
        ]
        Resource = [
          "arn:aws:dynamodb:*:*:table/m4h-*",
          "arn:aws:dynamodb:*:*:table/m4h-*/index/*",
          "arn:aws:dynamodb:*:*:table/migrate4hana-*",
          "arn:aws:dynamodb:*:*:table/migrate4hana-*/index/*"
        ]
      },
      # SSM Run Command - only against EC2 instances explicitly tagged as
      # Migrate4HANA SAP hosts. Tag-condition prevents this Lambda role from
      # running shell on every SSM-managed instance in the account.
      {
        Effect = "Allow"
        Action = ["ssm:SendCommand"]
        Resource = [
          "arn:aws:ssm:*:*:document/AWS-RunShellScript",
          "arn:aws:ssm:*:*:document/AWS-RunPowerShellScript",
          "arn:aws:ec2:*:*:instance/*"
        ]
        Condition = {
          StringEquals = {
            "aws:ResourceTag/Migrate4HANAHost" = "true"
          }
        }
      },
      # Read-only SSM polling for command results - safe to leave broad
      # because we only get back our own command invocations.
      {
        Effect = "Allow"
        Action = [
          "ssm:GetCommandInvocation",
          "ssm:DescribeInstanceInformation",
          "ssm:ListCommandInvocations"
        ]
        Resource = "*"
      },
      # Wave 6 - KMS data-key operations (only the customer-managed CMK).
      # Empty arn list collapses to deny when kms_key_arn is unset.
      {
        Effect = "Allow"
        Action = [
          "kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*",
          "kms:GenerateDataKey*", "kms:DescribeKey"
        ]
        Resource = var.kms_key_arn != "" ? [var.kms_key_arn] : ["arn:aws:kms:*:*:key/__none__"]
      },
      # Wave 7 - immutable evidence bucket. Object Lock is enforced at the
      # bucket level (COMPLIANCE) so PutObject is sufficient; we never need
      # DeleteObject from Lambda code.
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject", "s3:GetObject", "s3:GetObjectRetention",
          "s3:PutObjectLegalHold", "s3:GetObjectLegalHold",
          "s3:ListBucket"
        ]
        Resource = var.evidence_bucket_name != "" ? [
          "arn:aws:s3:::${var.evidence_bucket_name}",
          "arn:aws:s3:::${var.evidence_bucket_name}/*"
        ] : ["arn:aws:s3:::__none__"]
      }
    ]
  })
}

# ── SNS Publish - migrate4hana topics only ──
resource "aws_iam_role_policy" "lambda_sns_publish" {
  name = "migrate4hana-lambda-sns-publish"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = "arn:aws:sns:*:*:migrate4hana-*"
      }
    ]
  })
}

# Attach WebSocket telemetry broadcast policy (gated by a deterministic bool so
# `terraform plan` can resolve the count without waiting on the websocket-telemetry
# module's apply-time outputs).
variable "enable_telemetry_broadcast" {
  type        = bool
  default     = true
  description = "Attach the WebSocket telemetry broadcast policy to the Lambda role."
}

resource "aws_iam_role_policy_attachment" "telemetry_broadcast" {
  count      = var.enable_telemetry_broadcast ? 1 : 0
  role       = aws_iam_role.lambda.name
  policy_arn = var.telemetry_broadcast_policy_arn
}

# ── Lambda Functions ─────────────────────────
# WARNING (2026-06-10): this archive_file zips ONLY each handler's source_dir.
# Most handlers `from logger import ...`, `from validation import ...`, etc. —
# those modules live in lambda/utils/. Without bundling them every freshly-
# applied Lambda lands as ~6 KB and crashes at cold start with
# `Runtime.ImportModuleError: No module named 'logger'`. Run
# `scripts/package-lambdas-with-utils.ps1 -Env prod` AFTER terraform apply
# to re-zip every affected Lambda with utils alongside the handler. A proper
# fix (build-step that pre-stages each Lambda's source_dir with utils, or a
# shared utils layer) is tracked separately.
data "archive_file" "lambda" {
  for_each    = var.lambda_functions
  type        = "zip"
  source_dir  = each.value.source_dir
  output_path = "${path.module}/dist/${each.key}.zip"
}

# ── PROD-hardening inputs (optional; default "" => the pillar stays a no-op) ──
variable "transform_rules" {
  type    = string
  default = ""
}
variable "mapping_s3" {
  type    = string
  default = ""
}
variable "gate_sns_topic" {
  type    = string
  default = ""
}
variable "gate_secret_arn" {
  type    = string
  default = ""
}
variable "audit_ledger_table" {
  type    = string
  default = ""
}
variable "key_map_table" {
  type    = string
  default = ""
}
variable "evidence_bucket" {
  type        = string
  default     = ""
  description = "Tool-facing evidence bucket (M4H_EVIDENCE_BUCKET). Falls back to evidence_bucket_name if empty."
}
variable "fargate_cluster" {
  type    = string
  default = ""
}
variable "fargate_taskdef" {
  type    = string
  default = ""
}
variable "fargate_sgs" {
  type    = string
  default = ""
}
variable "fargate_row_threshold" {
  type    = number
  default = 20000
}

variable "dead_letter_threshold_pct" {
  description = "Dirty-data SLO. data-migrator computes dead_letter_pct from per-object load.failed_count / load.attempted (plus CVI conflicts). When the rate exceeds this threshold, SFN's DataQualitySloChoice halts at ManualGate_DataQuality. Set to 0 to disable the gate."
  type        = number
  default     = 5.0
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

  architectures = each.value.architectures
  layers        = compact(each.value.layers) # drop empty ARNs so apply is clean without the pyrfc layer

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
        # ── Two-plane orchestrator function names (lift-and-shift mode) ──
        # Retooled handlers chain to these via boto3.client('lambda').invoke().
        # Names follow the convention migrate4hana-<key>-<env>.
        MC_ORCHESTRATOR_FN            = "migrate4hana-migration-cockpit-orchestrator-${var.environment}"
        LTMOM_ORCHESTRATOR_FN         = "migrate4hana-ltmom-orchestrator-${var.environment}"
        IDOC_ORCHESTRATOR_FN          = "migrate4hana-idoc-orchestrator-${var.environment}"
        TRANSPORT_ARTIFACT_BUILDER_FN = "migrate4hana-transport-artifact-builder-${var.environment}"
        TRANSPORT_FILE_PLACER_FN      = "migrate4hana-transport-file-placer-${var.environment}"
        TRANSPORT_IMPORT_EXECUTOR_FN  = "migrate4hana-transport-import-executor-${var.environment}"
        TRANSPORT_IMPORT_VERIFIER_FN  = "migrate4hana-transport-import-verifier-${var.environment}"
        BC_SET_BUILDER_FN             = "migrate4hana-bc-set-builder-${var.environment}"
        CUTOVER_ORCHESTRATOR_FN       = "migrate4hana-cutover-orchestrator-${var.environment}"
        OBJECT_ROUTER_FN              = "migrate4hana-object-router-${var.environment}"
        DELTA_EXTRACTOR_FN            = "migrate4hana-delta-extractor-${var.environment}"
        BASIS_VALIDATOR_FN            = "migrate4hana-basis-validator-${var.environment}"
        TARGET_PROVISIONER_FN         = "migrate4hana-target-provisioner-${var.environment}"
        GATES_TABLE                   = var.gates_table_name
        # Wave 7 — hash-chained immutable ledger
        EVENTS_TABLE_NAME     = var.events_table_name
        S3_EVIDENCE_BUCKET    = var.evidence_bucket_name
        EVIDENCE_COLLECTOR_FN = "migrate4hana-evidence-collector-${var.environment}"
        # Wave 8 — reconciliation framework
        TOLERANCE_TABLE_NAME     = var.recon_tolerance_table_name
        RECONCILIATION_ENGINE_FN = "migrate4hana-reconciliation-engine-${var.environment}"
        MANUAL_GATE_FN           = "migrate4hana-manual-gate-${var.environment}"
      },
      var.telemetry_ws_endpoint != "" ? {
        TELEMETRY_WS_ENDPOINT          = var.telemetry_ws_endpoint
        TELEMETRY_WS_CONNECTIONS_TABLE = var.telemetry_ws_connections_table
      } : {},
      var.entity_resolution_workflow_arn != "" ? {
        ENTITY_RESOLUTION_WORKFLOW_ARN = var.entity_resolution_workflow_arn
      } : {},
      {
        AST_CHANGE_THRESHOLD = tostring(var.ast_change_threshold)
        LLM_MODE             = var.llm_mode
        OLLAMA_MODEL         = var.ollama_model
        # Direct Anthropic API (Bedrock is not used on this account)
        M4H_ANTHROPIC_SECRET_ARN   = var.anthropic_secret_arn
        ANTHROPIC_MODEL_ID         = var.anthropic_model_id
        ANTHROPIC_ESCALATION_MODEL = var.anthropic_escalation_model
      },
      var.ollama_url != "" ? { OLLAMA_URL = var.ollama_url } : {},
      {
        # ── PROD-hardening pillars (Pillars 1/2/3/4). Empty => the pillar stays
        #    a no-op, so existing behaviour is unchanged until these are populated.
        M4H_TRANSFORM_RULES       = var.transform_rules
        M4H_MAPPING_S3            = var.mapping_s3
        M4H_GATE_SNS_TOPIC        = var.gate_sns_topic
        M4H_GATE_SECRET_ARN       = var.gate_secret_arn
        M4H_AUDIT_LEDGER_TABLE    = var.audit_ledger_table
        M4H_KEYMAP_TABLE          = var.key_map_table
        M4H_EVIDENCE_BUCKET       = var.evidence_bucket != "" ? var.evidence_bucket : var.evidence_bucket_name
        M4H_FARGATE_CLUSTER       = var.fargate_cluster
        M4H_FARGATE_TASKDEF       = var.fargate_taskdef
        M4H_FARGATE_SUBNETS       = join(",", var.private_subnet_ids)
        M4H_FARGATE_SGS           = var.fargate_sgs
        M4H_FARGATE_ROW_THRESHOLD = tostring(var.fargate_row_threshold)
        # Dead-letter SLO gate (added 2026-06-10). data-migrator emits
        # data_quality.slo_breach when dirty-data rate exceeds this pct.
        # The SFN's DataQualitySloChoice halts the pipeline at
        # ManualGate_DataQuality when slo_breach=true. Set to "0" to
        # disable the gate.
        M4H_DEAD_LETTER_THRESHOLD_PCT = tostring(var.dead_letter_threshold_pct)
      }
    )
  }

  tags = {
    Component = "MigrationEngine"
    Stage     = each.key
  }
}

# Explicitly own each Lambda's log group so we can enforce 30-day retention.
# Without this, Lambda autocreates a group with "Never expire" the first time
# the function runs, which busts the UI's 30-day promise + costs money.
resource "aws_cloudwatch_log_group" "lambda" {
  for_each          = var.lambda_functions
  name              = "/aws/lambda/migrate4hana-${each.key}-${var.environment}"
  retention_in_days = 30

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
