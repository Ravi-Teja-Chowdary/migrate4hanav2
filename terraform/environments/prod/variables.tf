###############################################################################
# Variables — Production Environment
###############################################################################

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "environment" {
  type    = string
  default = "prod"
}

variable "vpc_cidr" {
  type    = string
  default = "10.30.0.0/16"
}

variable "availability_zones" {
  type    = list(string)
  default = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

variable "private_subnet_cidrs" {
  type    = list(string)
  default = ["10.30.1.0/24", "10.30.2.0/24", "10.30.3.0/24"]
}

variable "public_subnet_cidrs" {
  type    = list(string)
  default = ["10.30.101.0/24", "10.30.102.0/24", "10.30.103.0/24"]
}

variable "enable_vpn_gateway" {
  type    = bool
  default = true
}

variable "on_prem_cidr" {
  type    = string
  default = "172.16.0.0/12"
}

variable "s3_staging_bucket" {
  type    = string
  default = "migrate4hana-staging-prod"
}

variable "pyrfc_layer_arn" {
  type    = string
  default = ""
}

variable "alert_email" {
  type = string
}

# ── GenAI ────────────────────────────────────
variable "bedrock_model_id" {
  type    = string
  default = "anthropic.claude-3-sonnet-20240229-v1:0"
}

variable "ast_change_threshold" {
  type    = number
  default = 3
}

# ── Air-gapped LLM (Ollama + Gemma2) ─────────
variable "enable_airgapped_llm" {
  type        = bool
  description = "Provision the on-prem Ollama EC2 for local LLM inference"
  default     = true
}
variable "llm_mode" {
  type        = string
  description = "GenAI routing mode: cloud, local, or dual"
  default     = "dual"
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

# ── WAF ──────────────────────────────────────
variable "waf_rate_limit" {
  type        = number
  description = "Max requests per 5-minute window per IP"
  default     = 1000
}

# ── DMS Database Credentials ─────────────────
variable "ecc_db_host" {
  type    = string
  default = ""
}
variable "ecc_db_port" {
  type    = number
  default = 3200
}
variable "ecc_db_name" {
  type    = string
  default = "ECC"
}
variable "ecc_db_user" {
  type    = string
  default = "SAPSR3"
}
# ecc_db_password removed — now fetched from Secrets Manager (see main.tf)
variable "s4_db_host" {
  type    = string
  default = ""
}
variable "s4_db_port" {
  type    = number
  default = 30015
}
variable "s4_db_name" {
  type    = string
  default = "S4H"
}
variable "s4_db_user" {
  type    = string
  default = "SAPHANADB"
}
# s4_db_password removed — now fetched from Secrets Manager (see main.tf)
