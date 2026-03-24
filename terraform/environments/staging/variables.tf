###############################################################################
# Variables — Staging Environment
###############################################################################

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "environment" {
  type    = string
  default = "staging"
}

variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "availability_zones" {
  type    = list(string)
  default = ["us-east-1a", "us-east-1b"]
}

variable "private_subnet_cidrs" {
  type    = list(string)
  default = ["10.20.1.0/24", "10.20.2.0/24"]
}

variable "public_subnet_cidrs" {
  type    = list(string)
  default = ["10.20.101.0/24", "10.20.102.0/24"]
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
  default = "migrate4hana-staging-staging"
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

variable "local_llm_endpoint" {
  type    = string
  default = ""
}

variable "ast_change_threshold" {
  type    = number
  default = 3
}

variable "gpu_ami_id" {
  type    = string
  default = "ami-0123456789abcdef0"
}

variable "llm_model_s3_path" {
  type    = string
  default = "s3://migrate4hana-llm-models-staging/llama-3-8b/"
}

variable "llm_model_s3_bucket" {
  type    = string
  default = "migrate4hana-llm-models-staging"
}

# ── WAF ──────────────────────────────────────
variable "waf_rate_limit" {
  type        = number
  description = "Max requests per 5-minute window per IP"
  default     = 2000
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
variable "ecc_db_password" {
  type      = string
  default   = ""
  sensitive = true
}
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
variable "s4_db_password" {
  type      = string
  default   = ""
  sensitive = true
}
