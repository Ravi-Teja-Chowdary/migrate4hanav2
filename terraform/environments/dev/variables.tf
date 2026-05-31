###############################################################################
# Variables — Edit terraform.tfvars to set these
###############################################################################

variable "aws_region" {
  type        = string
  description = "AWS region for deployment"
  default     = "us-east-1"
}

variable "environment" {
  type        = string
  description = "Environment name (dev, staging, prod)"
  default     = "dev"
}

variable "vpc_cidr" {
  type        = string
  description = "CIDR block for the VPC"
  default     = "10.10.0.0/16"
}

variable "availability_zones" {
  type        = list(string)
  description = "AZs to deploy across"
  default     = ["us-east-1a", "us-east-1b"]
}

variable "private_subnet_cidrs" {
  type        = list(string)
  description = "CIDR blocks for private subnets (SAP + Lambda)"
  default     = ["10.10.1.0/24", "10.10.2.0/24"]
}

variable "public_subnet_cidrs" {
  type        = list(string)
  description = "CIDR blocks for public subnets (NAT GW, bastion)"
  default     = ["10.10.101.0/24", "10.10.102.0/24"]
}

variable "enable_vpn_gateway" {
  type        = bool
  description = "Enable VPN gateway for on-prem ECC connectivity"
  default     = false
}

variable "on_prem_cidr" {
  type        = string
  description = "CIDR block of on-premise network where ECC lives"
  default     = "172.16.0.0/12"
}

variable "s3_staging_bucket" {
  type        = string
  description = "Name of the S3 staging bucket"
  default     = "migrate4hana-staging-dev"
}

variable "pyrfc_layer_arn" {
  type        = string
  description = "ARN of the Lambda layer containing PyRFC + SAP NW RFC SDK"
  default     = "" # You'll build and publish this layer
}

variable "alert_email" {
  type        = string
  description = "Email for CloudWatch alarm notifications"
}

# ── GenAI Configuration ──────────────────────
# bedrock_model_id removed - this stack uses the direct Anthropic API (see
# prod/variables.tf for anthropic_model_id / anthropic_escalation_model).

variable "ast_change_threshold" {
  type        = number
  description = "If AST engine finds fewer changes than this, escalate to GenAI"
  default     = 3
}

# ── Air-gapped LLM (Ollama + Gemma2) ─────────
variable "enable_airgapped_llm" {
  type        = bool
  description = "Provision the on-prem Ollama EC2 for local LLM inference"
  default     = false
}
variable "llm_mode" {
  type        = string
  description = "GenAI routing mode: cloud, local, or dual"
  default     = "cloud"
}
variable "ollama_model" {
  type        = string
  description = "Ollama model name served by the air-gapped EC2"
  default     = "gemma2:27b"
}
variable "gpu_ami_id" {
  type        = string
  description = "AMI ID for GPU instance used by the Ollama server"
  default     = ""
}
