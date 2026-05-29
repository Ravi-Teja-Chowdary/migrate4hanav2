# ─────────────────────────────────────────────────────────────────────────────
# Outputs — each maps to an M4H_* env var the application reads (see SETUP_GUIDE.md).
# After apply:  terraform output -json  ->  set these on the API server / Fargate task.
# ─────────────────────────────────────────────────────────────────────────────

output "env_vars" {
  description = "Copy these into the API server / orchestrator environment."
  value = {
    # Pillar 1.1 — elastic compute dispatcher
    M4H_FARGATE_CLUSTER       = aws_ecs_cluster.this.name
    M4H_FARGATE_TASKDEF       = aws_ecs_task_definition.worker.arn
    M4H_FARGATE_CONTAINER     = var.container_name
    M4H_FARGATE_SUBNETS       = join(",", var.subnet_ids)
    M4H_FARGATE_SGS           = aws_security_group.task.id
    M4H_FARGATE_ROW_THRESHOLD = tostring(var.fargate_row_threshold)
    # Pillar 3 — governance gates
    M4H_GATE_SNS_TOPIC = aws_sns_topic.gate_alerts.arn
    M4H_GATE_SECRET_ARN = aws_secretsmanager_secret.gate_secret.arn
    # Pillar 4 — crypto-audit
    M4H_AUDIT_LEDGER_TABLE = aws_dynamodb_table.audit_ledger.name
    M4H_EVIDENCE_BUCKET    = aws_s3_bucket.evidence.id
    M4H_KEYMAP_TABLE       = aws_dynamodb_table.key_map.name
    # Pillar 2 — value-map matrix bucket (set M4H_MAPPING_S3=s3://<bucket>/<key>)
    M4H_CONFIG_BUCKET = aws_s3_bucket.config.id
  }
}

output "ecr_repository_url" {
  description = "Push the worker image here, then re-apply (or set var.container_image)."
  value       = aws_ecr_repository.worker.repository_url
}

output "gate_secret_arn" {
  description = "Secrets Manager ARN of the HMAC gate secret (read it into M4H_GATE_SECRET at runtime)."
  value       = aws_secretsmanager_secret.gate_secret.arn
}

output "sns_topic_arn" {
  value = aws_sns_topic.gate_alerts.arn
}

output "evidence_bucket" {
  value = aws_s3_bucket.evidence.id
}

output "audit_ledger_table" {
  value = aws_dynamodb_table.audit_ledger.name
}

output "task_role_arn" {
  description = "Grant Step Functions / the API the ability to assume or be granted states:SendTaskSuccess as needed."
  value       = aws_iam_role.task.arn
}
