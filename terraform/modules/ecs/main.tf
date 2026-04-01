###############################################################################
# ECS Module — Fargate Compute for Heavy Migration Stages
#
# Stages 1 (Discovery), 5 (Code Analyzer), 12 (Data Loader),
# and 12A (Reconciliation) run here instead of Lambda to avoid
# the 15-minute execution limit and memory constraints.
#
# A single flexible Task Definition is used. The Step Functions
# orchestrator passes STAGE_TARGET via ContainerOverrides to select
# which handler runs inside the unified Docker image.
###############################################################################

# ── Variables ────────────────────────────────
variable "environment" { type = string }
variable "aws_region" {
  type    = string
  default = "us-east-1"
}
variable "vpc_id" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "secrets_arn" { type = string }
variable "s3_staging_bucket" { type = string }
variable "s3_staging_arn" { type = string }
variable "bedrock_model_id" {
  type    = string
  default = "anthropic.claude-3-sonnet-20240229-v1:0"
}
variable "image_tag" {
  type        = string
  default     = "latest"
  description = "Docker image tag to deploy (set via CI/CD)"
}

# ── ECR Repository ───────────────────────────
resource "aws_ecr_repository" "migration_worker" {
  name                 = "migrate4hana/worker"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = { Name = "migrate4hana-worker-${var.environment}" }
}

resource "aws_ecr_lifecycle_policy" "worker" {
  repository = aws_ecr_repository.migration_worker.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

# ── ECS Cluster ──────────────────────────────
resource "aws_ecs_cluster" "migration" {
  name = "migrate4hana-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = { Name = "migrate4hana-cluster-${var.environment}" }
}

# ── CloudWatch Log Group ─────────────────────
resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/migrate4hana-${var.environment}"
  retention_in_days = 30

  tags = { Component = "ECS" }
}

# ── Execution Role (ECR pull + CloudWatch logs) ──
resource "aws_iam_role" "ecs_execution" {
  name = "migrate4hana-ecs-execution-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution_managed" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ── Task Role (application-level access) ─────
resource "aws_iam_role" "ecs_task" {
  name = "migrate4hana-ecs-task-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "ecs_task" {
  name = "migrate4hana-ecs-task-policy"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # Secrets Manager — SAP RFC credentials
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = var.secrets_arn
      },
      # DynamoDB — idempotency tracking + country rules
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:BatchWriteItem"
        ]
        Resource = "arn:aws:dynamodb:${var.aws_region}:*:table/migrate4hana-*"
      },
      # Bedrock — GenAI code analysis (Stage 5)
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = "arn:aws:bedrock:*::foundation-model/*"
      },
      # S3 — staging bucket for migration data
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
      # Step Functions — callback (send_task_success/failure/heartbeat)
      {
        Effect = "Allow"
        Action = [
          "states:SendTaskSuccess",
          "states:SendTaskFailure",
          "states:SendTaskHeartbeat"
        ]
        Resource = "*"
      },
      # CloudWatch Logs
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "${aws_cloudwatch_log_group.ecs.arn}:*"
      }
    ]
  })
}

# ── Fargate Task Definition (4 vCPU / 16 GB) ─
# BOOTSTRAP NOTE: The initial image is a placeholder (alpine:latest) so that
# terraform apply can succeed BEFORE the real Docker image is pushed to ECR.
# The CI/CD pipeline (deploy.yml) will register a new revision with the real
# migrate4hana-worker image after build+push.  The lifecycle block below
# prevents subsequent `terraform apply` runs from reverting the image back
# to the placeholder.
resource "aws_ecs_task_definition" "migration_heavy" {
  family                   = "migrate4hana-heavy-${var.environment}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 4096   # 4 vCPU
  memory                   = 16384  # 16 GB
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "migration-worker"
    image     = "alpine:latest"   # Placeholder — CI/CD deploys real image
    essential = true

    environment = [
      { name = "S3_STAGING_BUCKET", value = var.s3_staging_bucket },
      { name = "SECRETS_ARN",       value = var.secrets_arn },
      { name = "ENVIRONMENT",       value = var.environment },
      { name = "BEDROCK_MODEL_ID",  value = var.bedrock_model_id },
      { name = "AWS_DEFAULT_REGION", value = var.aws_region },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "migration"
      }
    }
  }])

  # After CI/CD pushes the real image and registers a new task revision,
  # we do NOT want `terraform apply` to revert container_definitions back
  # to the placeholder.  Terraform manages infra; CI/CD manages the image.
  lifecycle {
    ignore_changes = [container_definitions]
  }

  tags = { Component = "MigrationEngine-Heavy" }
}

# ── Security Group ───────────────────────────
resource "aws_security_group" "ecs" {
  name_prefix = "migrate4hana-ecs-"
  vpc_id      = var.vpc_id

  # Outbound: SAP RFC (3200-3299), HTTPS (443), DNS
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "migrate4hana-ecs-${var.environment}" }
}

# ── Outputs ──────────────────────────────────
output "cluster_arn" {
  value = aws_ecs_cluster.migration.arn
}

output "task_definition_arn" {
  value = aws_ecs_task_definition.migration_heavy.arn
}

output "task_role_arn" {
  value = aws_iam_role.ecs_task.arn
}

output "execution_role_arn" {
  value = aws_iam_role.ecs_execution.arn
}

output "security_group_id" {
  value = aws_security_group.ecs.id
}

output "ecr_repository_url" {
  value = aws_ecr_repository.migration_worker.repository_url
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.ecs.name
}
