# ═════════════════════════════════════════════════════════════════════════════
# Migrate4HANA — PROD-hardening infrastructure (standalone, applyable on its own)
#
#   cd terraform/prod-hardening
#   terraform init && terraform apply
#
# Provisions exactly what Pillars 1.1 (elastic Fargate compute), 3 (governance
# gates: SNS + signed approval), and 4 (crypto-audit: WORM evidence + hash-chain
# vault) need at runtime. See SETUP_GUIDE.md for the env-var mapping + apply steps.
# ═════════════════════════════════════════════════════════════════════════════

terraform {
  required_version = ">= 1.3.0"
  required_providers {
    aws    = { source = "hashicorp/aws", version = ">= 5.0" }
    random = { source = "hashicorp/random", version = ">= 3.4" }
  }
}

provider "aws" {
  region = var.region
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  prefix     = var.name_prefix
  account_id = data.aws_caller_identity.current.account_id
  # If no image is supplied, default to the ECR repo this stack creates (push then re-apply).
  image = var.container_image != "" ? var.container_image : "${aws_ecr_repository.worker.repository_url}:latest"
}

# ─────────────────────────────────────────────────────────────────────────────
# Pillar 1.1 — ECR repo for the worker image
# ─────────────────────────────────────────────────────────────────────────────
resource "aws_ecr_repository" "worker" {
  name                 = "${local.prefix}-worker"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration { scan_on_push = true }
  tags = var.tags
}

# ─────────────────────────────────────────────────────────────────────────────
# Pillar 4 — DynamoDB audit hash-chain vault (HashChainLedger -> M4H_AUDIT_LEDGER_TABLE)
#   PK run_id (S), SK seq (N): one immutable, hash-chained block per verifiable action.
# ─────────────────────────────────────────────────────────────────────────────
resource "aws_dynamodb_table" "audit_ledger" {
  name         = "${local.prefix}-audit-ledger"
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

  point_in_time_recovery { enabled = true }
  server_side_encryption { enabled = true }
  tags = var.tags
}

# DynamoDB cross-run key-map ledger (KeyMap persistence; TokenBucket sizes to its WCU)
resource "aws_dynamodb_table" "key_map" {
  name         = "${local.prefix}-key-map"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "object"
  range_key    = "source_key"

  attribute {
    name = "object"
    type = "S"
  }
  attribute {
    name = "source_key"
    type = "S"
  }

  point_in_time_recovery { enabled = true }
  server_side_encryption { enabled = true }
  tags = var.tags
}

# ─────────────────────────────────────────────────────────────────────────────
# Pillar 4 — WORM evidence bucket (EvidencePack -> M4H_EVIDENCE_BUCKET)
#   Object Lock (COMPLIANCE) makes the auditor evidence pack immutable for retention.
# ─────────────────────────────────────────────────────────────────────────────
resource "aws_s3_bucket" "evidence" {
  bucket              = "${local.prefix}-evidence-${local.account_id}"
  object_lock_enabled = true   # MUST be set at creation
  tags                = var.tags
}

resource "aws_s3_bucket_versioning" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  versioning_configuration { status = "Enabled" }   # required for Object Lock
}

resource "aws_s3_bucket_object_lock_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  rule {
    default_retention {
      mode = "COMPLIANCE"
      days = var.evidence_retention_days
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "aws:kms" }
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

# ─────────────────────────────────────────────────────────────────────────────
# Pillar 2 — config/mapping bucket (value-map matrix -> M4H_MAPPING_S3)
#   Business users upload the JSON mapping matrix here; the engine caches it.
# ─────────────────────────────────────────────────────────────────────────────
resource "aws_s3_bucket" "config" {
  bucket = "${local.prefix}-config-${local.account_id}"
  tags   = var.tags
}

resource "aws_s3_bucket_versioning" "config" {
  bucket = aws_s3_bucket.config.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_public_access_block" "config" {
  bucket                  = aws_s3_bucket.config.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ─────────────────────────────────────────────────────────────────────────────
# Pillar 3 — governance gate secret (HMAC) + SNS approval topic
# ─────────────────────────────────────────────────────────────────────────────
resource "random_password" "gate_secret" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "gate_secret" {
  name                    = "${local.prefix}-gate-secret"
  description             = "HMAC secret for Migrate4HANA spine approval gates (M4H_GATE_SECRET)"
  recovery_window_in_days = 7
  tags                    = var.tags
}

resource "aws_secretsmanager_secret_version" "gate_secret" {
  secret_id     = aws_secretsmanager_secret.gate_secret.id
  secret_string = random_password.gate_secret.result
}

resource "aws_sns_topic" "gate_alerts" {
  name              = "${local.prefix}-gate-alerts"
  kms_master_key_id = "alias/aws/sns"
  tags              = var.tags
}

resource "aws_sns_topic_subscription" "gate_email" {
  topic_arn = aws_sns_topic.gate_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ─────────────────────────────────────────────────────────────────────────────
# Pillar 1.1 — ECS cluster, security group, log group, Fargate task definition
# ─────────────────────────────────────────────────────────────────────────────
resource "aws_ecs_cluster" "this" {
  name = "${local.prefix}-cluster"
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
  tags = var.tags
}

resource "aws_security_group" "task" {
  name        = "${local.prefix}-task-sg"
  description = "Migrate4HANA Fargate tasks — egress to SAP (RFC/OData) + AWS services"
  vpc_id      = var.vpc_id

  egress {
    description = "all egress (SAP RFC 33xx, OData 443xx, AWS endpoints)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = var.tags
}

resource "aws_cloudwatch_log_group" "task" {
  name              = "/ecs/${local.prefix}-worker"
  retention_in_days = 90
  tags              = var.tags
}

# Task execution role — pull image + write logs
resource "aws_iam_role" "task_execution" {
  name = "${local.prefix}-task-exec"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "task_execution" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Allow the execution role to read the gate secret for container 'secrets' injection
resource "aws_iam_role_policy" "task_execution_secrets" {
  name = "${local.prefix}-exec-secrets"
  role = aws_iam_role.task_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [aws_secretsmanager_secret.gate_secret.arn]
    }]
  })
}

# Task role — the application's runtime permissions
resource "aws_iam_role" "task" {
  name = "${local.prefix}-task"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = var.tags
}

resource "aws_iam_role_policy" "task" {
  name = "${local.prefix}-task-policy"
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        Sid    = "S3Buckets"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = compact([
          aws_s3_bucket.evidence.arn, "${aws_s3_bucket.evidence.arn}/*",
          aws_s3_bucket.config.arn, "${aws_s3_bucket.config.arn}/*",
          var.staging_bucket != "" ? "arn:aws:s3:::${var.staging_bucket}" : "",
          var.staging_bucket != "" ? "arn:aws:s3:::${var.staging_bucket}/*" : "",
        ])
      },
      {
        Sid      = "DynamoDBLedgers"
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query", "dynamodb:BatchWriteItem", "dynamodb:UpdateItem"]
        Resource = [aws_dynamodb_table.audit_ledger.arn, aws_dynamodb_table.key_map.arn]
      },
      {
        Sid      = "SNSPublish"
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = [aws_sns_topic.gate_alerts.arn]
      },
      {
        Sid      = "StepFunctionsResume"
        Effect   = "Allow"
        Action   = ["states:SendTaskSuccess", "states:SendTaskFailure", "states:SendTaskHeartbeat"]
        Resource = ["*"]
      },
      {
        Sid      = "GateSecret"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [aws_secretsmanager_secret.gate_secret.arn]
      },
      ],
      # Optional SAP credential secrets, granted only if provided
      var.ecc_secret_arn != "" || var.target_secret_arn != "" ? [{
        Sid      = "SapCredsRead"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = compact([var.ecc_secret_arn, var.target_secret_arn])
      }] : []
    )
  })
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.prefix}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.fargate_cpu)
  memory                   = tostring(var.fargate_memory)
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name      = var.container_name
    image     = local.image
    essential = true
    environment = [
      { name = "M4H_AUDIT_LEDGER_TABLE", value = aws_dynamodb_table.audit_ledger.name },
      { name = "M4H_KEYMAP_TABLE", value = aws_dynamodb_table.key_map.name },
      { name = "M4H_EVIDENCE_BUCKET", value = aws_s3_bucket.evidence.id },
      { name = "M4H_GATE_SNS_TOPIC", value = aws_sns_topic.gate_alerts.arn },
      { name = "S3_STAGING_BUCKET", value = var.staging_bucket },
      { name = "AWS_REGION", value = var.region },
    ]
    secrets = [
      { name = "M4H_GATE_SECRET", valueFrom = aws_secretsmanager_secret.gate_secret.arn },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.task.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "worker"
      }
    }
  }])
  tags = var.tags
}
