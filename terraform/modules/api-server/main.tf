# ──────────────────────────────────────────────────────────────────────────
# api-server module — Fargate + ALB hosting for api_server.py
# ──────────────────────────────────────────────────────────────────────────
# Pushes api_server.py into a public-facing ALB-fronted Fargate service so a
# customer browser can reach it via the CloudFront distribution defined in
# the ui-hosting module. The Fargate task gets the same IAM permissions as
# the migration Lambdas (Secrets / S3 / DynamoDB / SFN / Lambda invoke) so
# pipeline triggers work identically to the local dev flow.
#
# Inputs:
#   environment, vpc_id, private_subnet_ids, public_subnet_ids
#   ecs_cluster_arn — reuse the existing module.ecs cluster
#   staging_bucket, key_map_table, lambda_arns (for IAM grants + env vars)
#   image_tag — set by the deploy script after a docker push; defaults to "latest"
#
# Outputs:
#   alb_dns_name       — internal-only DNS; CloudFront points here as origin
#   ecr_repository_url — where the deploy script docker-pushes the image
#   service_name       — for `aws ecs update-service --force-new-deployment`
# ──────────────────────────────────────────────────────────────────────────

variable "environment" { type = string }
variable "vpc_id" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "public_subnet_ids" { type = list(string) }
variable "ecs_cluster_arn" { type = string }
variable "staging_bucket" { type = string }

variable "key_map_table" {
  type    = string
  default = ""
}

variable "users_table" {
  type        = string
  default     = ""
  description = "DynamoDB table name for migrate4hana-users-<env> (auth user store)"
}

variable "clients_table" {
  type        = string
  default     = ""
  description = "DynamoDB table name for migrate4hana-clients-<env> (auth client store)"
}

variable "wizard_state_table" {
  type        = string
  default     = ""
  description = "DynamoDB table name for migrate4hana-wizard-state-<env> (wizard run state)"
}

variable "anthropic_secret_arn" {
  type    = string
  default = ""
}

variable "jwt_secret_arn" {
  type        = string
  default     = ""
  description = "Secrets Manager ARN for HS256 JWT signing key. Required in prod (api_server.py _ensure_jwt_secret fails closed if missing)."
}

variable "root_user_secret_arn" {
  type        = string
  default     = ""
  description = "Secrets Manager ARN for the JSON secret {M4H_ROOT_EMAIL, M4H_ROOT_PASSWORD} used by ensure_root_user() on first start."
}

variable "host_aliases" {
  type        = map(any)
  default     = {}
  description = <<-EOT
    Server-side SAP host aliases. The wizard user enters a friendly host
    (typically a private VMware IP like 192.168.100.170); connection_validator
    rewrites it to the actual reachable tunnel target before calling pyrfc.
    Each alias value is an object with any subset of {ashost, gwhost, gwserv,
    sysnr}. See lambda/utils/connection_validator.py::_resolve_host_alias.

    Example:
      host_aliases = {
        "192.168.100.170" = {
          ashost = "0.tcp.ap.ngrok.io"
          gwhost = "0.tcp.ap.ngrok.io"
          gwserv = "17291"
        }
      }
  EOT
}

variable "image_tag" {
  type    = string
  default = "latest"
}

variable "cpu" {
  type    = string
  default = "1024"
}

variable "memory" {
  type    = string
  default = "2048"
}

variable "desired_count" {
  type    = number
  default = 1
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "alb_idle_timeout" {
  type    = number
  default = 120
}

# Each environment writes to its own image repo so prod and dev can diverge.
resource "aws_ecr_repository" "api_server" {
  name                 = "migrate4hana-api-server-${var.environment}"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name        = "migrate4hana-api-server-${var.environment}"
    Component   = "ApiServer"
    Environment = var.environment
  }
}

# Lifecycle policy: keep the last 10 images; the rest are pruned on push.
resource "aws_ecr_lifecycle_policy" "api_server" {
  repository = aws_ecr_repository.api_server.name
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

# ── CloudWatch log group ───────────────────────────────────────────────────
resource "aws_cloudwatch_log_group" "api_server" {
  name              = "/migrate4hana/api-server/${var.environment}"
  retention_in_days = var.log_retention_days

  tags = {
    Component   = "ApiServer"
    Environment = var.environment
  }
}

# ── Task IAM roles ─────────────────────────────────────────────────────────
# Execution role: ECR pull + CloudWatch log write. Task role: app-level
# permissions (Secrets / S3 / DynamoDB / SFN / Lambda invoke).
data "aws_iam_policy_document" "ecs_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "migrate4hana-api-server-execution-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ECS injects the container's `secrets` block via the execution role, not the
# task role. Grant read on the secrets we source env vars from. Scoped to the
# specific ARNs so a compromised execution role cannot enumerate other secrets.
#
# No `count` guard here: the guarded version broke `terraform destroy` because
# count depended on other resources' ARN attributes (unknown at destroy plan
# time). Both ARNs are always populated by prod/main.tf, so we always create.
# `compact()` filters empties for the hypothetical case where a caller passes
# only one — never happens in this stack today.
data "aws_iam_policy_document" "execution_secrets" {
  statement {
    effect  = "Allow"
    actions = ["secretsmanager:GetSecretValue"]
    resources = compact([
      var.root_user_secret_arn,
      var.jwt_secret_arn,
    ])
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  name   = "migrate4hana-api-server-exec-secrets-${var.environment}"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secrets.json
}

# The count-guarded version briefly landed in state as .execution_secrets[0].
# `moved` teaches Terraform to renumber it in state instead of destroy+recreate.
moved {
  from = aws_iam_role_policy.execution_secrets[0]
  to   = aws_iam_role_policy.execution_secrets
}

resource "aws_iam_role" "task" {
  name               = "migrate4hana-api-server-task-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

# Same permissions surface as the Lambda role so api_server.py can do
# everything the Lambdas can (read secrets, write artifacts, kick SFN).
data "aws_iam_policy_document" "task_policy" {
  # Secrets - scoped to migrate4hana-prefixed secrets only. Wildcard suffix
  # covers Secrets Manager's appended 6-character random suffix.
  statement {
    effect  = "Allow"
    actions = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [
      "arn:aws:secretsmanager:*:*:secret:migrate4hana-*",
      "arn:aws:secretsmanager:*:*:secret:m4h-*",
    ]
  }
  statement {
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:DeleteObject"]
    resources = [
      "arn:aws:s3:::${var.staging_bucket}",
      "arn:aws:s3:::${var.staging_bucket}/*",
    ]
  }
  # DynamoDB - migrate4hana / m4h-prefixed tables and their indexes only.
  statement {
    effect = "Allow"
    actions = [
      "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
      "dynamodb:Query", "dynamodb:Scan", "dynamodb:DeleteItem",
      "dynamodb:BatchGetItem", "dynamodb:BatchWriteItem",
      "dynamodb:DescribeTable",
    ]
    resources = [
      "arn:aws:dynamodb:*:*:table/migrate4hana-*",
      "arn:aws:dynamodb:*:*:table/migrate4hana-*/index/*",
      "arn:aws:dynamodb:*:*:table/m4h-*",
      "arn:aws:dynamodb:*:*:table/m4h-*/index/*",
    ]
  }
  # Step Functions - migrate4hana state machines + their executions only.
  statement {
    effect = "Allow"
    actions = [
      "states:StartExecution", "states:StopExecution", "states:DescribeExecution",
      "states:GetExecutionHistory", "states:ListExecutions", "states:DescribeStateMachine",
      "states:SendTaskSuccess", "states:SendTaskFailure", "states:SendTaskHeartbeat",
    ]
    resources = [
      "arn:aws:states:*:*:stateMachine:migrate4hana-*",
      "arn:aws:states:*:*:execution:migrate4hana-*:*",
    ]
  }
  # ListStateMachines is an account-level operation with no resource ARN; keep
  # in its own statement so the wildcard surface is narrow and explicit.
  statement {
    effect    = "Allow"
    actions   = ["states:ListStateMachines"]
    resources = ["*"]
  }
  statement {
    effect  = "Allow"
    actions = ["lambda:InvokeFunction", "lambda:GetFunction"]
    resources = [
      "arn:aws:lambda:*:*:function:migrate4hana-*",
      "arn:aws:lambda:*:*:function:m4h-*",
    ]
  }
  statement {
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.api_server.arn}:*"]
  }
  # The UI's Logs page reads from CloudWatch via the api-server. Allow tailing
  # any migrate4hana-* log group (Lambdas + Step Functions + ECS).
  statement {
    effect = "Allow"
    actions = [
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
      "logs:FilterLogEvents",
      "logs:GetLogEvents",
      "logs:StartLiveTail",
    ]
    resources = ["*"]
  }
  # ECS Exec (`aws ecs execute-command`) session channels. Required so ops
  # can `aws ecs execute-command --interactive` into a running task for
  # live diagnostics (verified pyrfc, poke the venv, tail /proc, etc).
  statement {
    effect = "Allow"
    actions = [
      "ssmmessages:CreateControlChannel",
      "ssmmessages:CreateDataChannel",
      "ssmmessages:OpenControlChannel",
      "ssmmessages:OpenDataChannel",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "migrate4hana-api-server-task-${var.environment}"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task_policy.json
}

# ── Security groups ────────────────────────────────────────────────────────
resource "aws_security_group" "alb" {
  name        = "migrate4hana-api-alb-${var.environment}"
  description = "Public ingress for api-server ALB"
  vpc_id      = var.vpc_id

  ingress {
    description = "HTTP from anywhere (CloudFront origin)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # SG descriptions must match AWS regex: only ASCII letters/digits/safe punct.
  # No arrows, no smart quotes — caught the hard way on first deploy.

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "migrate4hana-api-alb-${var.environment}" }
}

resource "aws_security_group" "task" {
  name        = "migrate4hana-api-task-${var.environment}"
  description = "Fargate task - accepts ALB to port 8000 only"
  vpc_id      = var.vpc_id

  ingress {
    description     = "ALB to Fargate"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "migrate4hana-api-task-${var.environment}" }
}

# ── ALB ────────────────────────────────────────────────────────────────────
resource "aws_lb" "api" {
  name               = "m4h-api-${var.environment}"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.public_subnet_ids

  idle_timeout = var.alb_idle_timeout

  tags = {
    Name        = "m4h-api-${var.environment}"
    Component   = "ApiServer"
    Environment = var.environment
  }
}

resource "aws_lb_target_group" "api" {
  name        = "m4h-api-tg-${var.environment}"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    path                = "/api/health"
    port                = "traffic-port"
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  deregistration_delay = 30

  tags = {
    Component   = "ApiServer"
    Environment = var.environment
  }
}

resource "aws_lb_listener" "api_http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

# ── ECS task definition + service ──────────────────────────────────────────
resource "aws_ecs_task_definition" "api_server" {
  family                   = "migrate4hana-api-server-${var.environment}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name      = "api-server"
    image     = "${aws_ecr_repository.api_server.repository_url}:${var.image_tag}"
    essential = true
    portMappings = [{
      containerPort = 8000
      protocol      = "tcp"
    }]
    environment = [
      { name = "AWS_REGION", value = "us-east-1" },
      { name = "M4H_EVIDENCE_BUCKET", value = var.staging_bucket },
      { name = "S3_STAGING_BUCKET", value = var.staging_bucket },
      { name = "M4H_KEYMAP_TABLE", value = var.key_map_table },
      { name = "M4H_ANTHROPIC_SECRET_ARN", value = var.anthropic_secret_arn },
      { name = "M4H_JWT_SECRET_ARN", value = var.jwt_secret_arn },
      { name = "M4H_HOST_ALIASES", value = jsonencode(var.host_aliases) },
      # ── 2026-06-15 UI rebuild: auth store, client store, wizard state ──
      { name = "M4H_USERS_TABLE", value = var.users_table },
      { name = "M4H_CLIENTS_TABLE", value = var.clients_table },
      { name = "M4H_WIZARD_STATE_TABLE", value = var.wizard_state_table },
      { name = "M4H_ENV", value = var.environment },
      { name = "PYTHONUNBUFFERED", value = "1" },
    ]
    # Secrets sourced from Secrets Manager JSON keys. ECS injects these as
    # environment variables at container start (indistinguishable from
    # `environment` entries from the app's perspective). Bootstraps the root
    # user on first login via lambda/utils/auth_users.py::ensure_root_user.
    secrets = var.root_user_secret_arn != "" ? [
      { name = "M4H_ROOT_EMAIL", valueFrom = "${var.root_user_secret_arn}:M4H_ROOT_EMAIL::" },
      { name = "M4H_ROOT_PASSWORD", valueFrom = "${var.root_user_secret_arn}:M4H_ROOT_PASSWORD::" },
    ] : []
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.api_server.name
        "awslogs-region"        = "us-east-1"
        "awslogs-stream-prefix" = "api-server"
      }
    }
    healthCheck = {
      command     = ["CMD-SHELL", "curl -fsS http://localhost:8000/api/health || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 30
    }
  }])

  tags = {
    Component   = "ApiServer"
    Environment = var.environment
  }
}

resource "aws_ecs_service" "api_server" {
  name                   = "migrate4hana-api-server-${var.environment}"
  cluster                = var.ecs_cluster_arn
  task_definition        = aws_ecs_task_definition.api_server.arn
  desired_count          = var.desired_count
  launch_type            = "FARGATE"
  enable_execute_command = true

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.task.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api-server"
    container_port   = 8000
  }

  health_check_grace_period_seconds = 60

  # The deploy script bumps image_tag (or just `aws ecs update-service
  # --force-new-deployment`), so don't fight terraform on rollouts.
  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }

  depends_on = [aws_lb_listener.api_http]

  tags = {
    Component   = "ApiServer"
    Environment = var.environment
  }
}

# ── Auto-roll on task def change ───────────────────────────────────────────
# The service has `ignore_changes = [task_definition]` so `deploy-ui-aws.ps1`
# can push new images without terraform fighting it. That means a plain
# `terraform apply` that only changes the task def (env vars, secrets, IAM)
# would leave the service pinned to the old revision — the exact failure
# mode that produced the 2026-07-04 JWT-gate incident. This null_resource
# closes the gap: whenever terraform replaces the task def (new revision
# arn), it fires a force-new-deployment. Rev-change-only trigger, so image
# pushes from the deploy script don't cause a redundant second roll.
resource "null_resource" "roll_on_taskdef_change" {
  triggers = {
    task_definition_arn = aws_ecs_task_definition.api_server.arn
  }

  provisioner "local-exec" {
    interpreter = ["pwsh", "-NoProfile", "-Command"]
    command     = <<-EOT
      aws ecs update-service `
        --cluster ${var.ecs_cluster_arn} `
        --service ${aws_ecs_service.api_server.name} `
        --task-definition ${aws_ecs_task_definition.api_server.family} `
        --force-new-deployment `
        --region us-east-1 `
        --query 'service.deployments[0].{status:status,taskDef:taskDefinition}' `
        --output json
    EOT
  }

  depends_on = [aws_ecs_service.api_server]
}

# ── Auto-scaling ───────────────────────────────────────────────────────────
# Scale the Fargate service from 1 → N tasks based on average CPU. Required
# for multi-tenant traffic: one task can comfortably serve a handful of
# concurrent customers, but a fleet of customers hitting it simultaneously
# saturates uvicorn's single worker. AppAutoScaling kicks new tasks in at
# 60% CPU and scales down conservatively (5 min cooldown) so we don't
# thrash during a long-running migration.
variable "autoscale_min" {
  type        = number
  default     = 1
  description = "Minimum running tasks for the api-server service."
}

variable "autoscale_max" {
  type        = number
  default     = 4
  description = "Maximum tasks under load. Bump for production multi-tenant."
}

variable "autoscale_target_cpu" {
  type        = number
  default     = 60
  description = "Target average CPU utilisation (%) that triggers scale-out."
}

resource "aws_appautoscaling_target" "api_server" {
  max_capacity       = var.autoscale_max
  min_capacity       = var.autoscale_min
  resource_id        = "service/${replace(var.ecs_cluster_arn, "/^.*cluster\\//", "")}/${aws_ecs_service.api_server.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "api_server_cpu" {
  name               = "migrate4hana-api-server-cpu-${var.environment}"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.api_server.resource_id
  scalable_dimension = aws_appautoscaling_target.api_server.scalable_dimension
  service_namespace  = aws_appautoscaling_target.api_server.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = var.autoscale_target_cpu
    scale_in_cooldown  = 300 # 5 min — don't yank capacity mid-request
    scale_out_cooldown = 60  # 1 min — react to load fast
  }
}

# ── Outputs ────────────────────────────────────────────────────────────────
output "alb_dns_name" {
  description = "Public DNS of the api-server ALB. Used as the CloudFront origin."
  value       = aws_lb.api.dns_name
}

output "alb_arn" {
  value = aws_lb.api.arn
}

output "ecr_repository_url" {
  description = "Where to docker-push the api-server image."
  value       = aws_ecr_repository.api_server.repository_url
}

output "service_name" {
  description = "ECS service name (for `update-service --force-new-deployment`)."
  value       = aws_ecs_service.api_server.name
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.api_server.name
}
