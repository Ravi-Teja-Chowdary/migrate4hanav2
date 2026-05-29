# ─────────────────────────────────────────────────────────────────────────────
# Migrate4HANA — PROD-hardening infrastructure (standalone root config)
# Variables. Provide these via terraform.tfvars or -var flags.
# ─────────────────────────────────────────────────────────────────────────────

variable "region" {
  description = "AWS region (must match where your S/4HANA appliance + Lambdas live)."
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Prefix for all resource names (keeps this stack isolated from others)."
  type        = string
  default     = "m4h-prodhard"
}

variable "vpc_id" {
  description = "Existing VPC the Fargate tasks run in (must have egress to SAP + AWS services)."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnet IDs for Fargate tasks (need a NAT/endpoints route to reach SAP + S3/DDB/SNS)."
  type        = list(string)
}

variable "container_image" {
  description = "ECR image URI for the Migrate4HANA worker. Leave blank to use the ECR repo this stack creates (push the image after first apply, then re-apply)."
  type        = string
  default     = ""
}

variable "container_name" {
  description = "Container name inside the task def — MUST equal M4H_FARGATE_CONTAINER (code default 'migrate4hana')."
  type        = string
  default     = "migrate4hana"
}

variable "fargate_cpu" {
  description = "Fargate task CPU units (256/512/1024/2048/4096). The dispatcher overrides memory per job."
  type        = number
  default     = 2048
}

variable "fargate_memory" {
  description = "Default Fargate task memory (MiB). The ComputeDispatcher overrides this per job (2/4/8/16/30 GiB tiers)."
  type        = number
  default     = 8192
}

variable "fargate_row_threshold" {
  description = "Row count above which a unit of work is offloaded from Lambda to Fargate."
  type        = number
  default     = 20000
}

variable "alert_email" {
  description = "Email subscribed to the governance-gate SNS topic (gets the approval alerts)."
  type        = string
}

variable "evidence_retention_days" {
  description = "WORM (Object Lock COMPLIANCE) retention for auditor evidence packs. 2555 = 7 years."
  type        = number
  default     = 2555
}

variable "ecc_secret_arn" {
  description = "ARN of the Secrets Manager secret holding ECC RFC creds (granted to the task role). Empty = skip."
  type        = string
  default     = ""
}

variable "target_secret_arn" {
  description = "ARN of the Secrets Manager secret holding S/4HANA creds (granted to the task role). Empty = skip."
  type        = string
  default     = ""
}

variable "staging_bucket" {
  description = "Existing staging bucket the worker reads/writes (e.g. m4h-staging-a1). Empty = only the buckets this stack creates."
  type        = string
  default     = ""
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default = {
    Project   = "Migrate4HANA"
    Component = "prod-hardening"
    ManagedBy = "terraform"
  }
}
