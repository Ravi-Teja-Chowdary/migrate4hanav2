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
  type    = string
  default = "migrations@example.com" # override in terraform.tfvars to receive alerts
}

# Pillar 2 — path/URI to the transformation ruleset JSON (empty => engine stays no-op)
variable "transform_rules" {
  type    = string
  default = ""
}

# ── GenAI ────────────────────────────────────
# Direct Anthropic API (replaces Bedrock when the AWS account does not have
# model access). Set anthropic_api_key in terraform.tfvars - it is loaded into
# Secrets Manager and read by the code-analyzer Lambda at runtime.
variable "anthropic_api_key" {
  type        = string
  description = "Anthropic API key for Claude code remediation. Leave empty to skip seeding the secret (e.g. on initial apply); set later via `aws secretsmanager put-secret-value`."
  default     = ""
  sensitive   = true
}

variable "anthropic_model_id" {
  type        = string
  description = "Default Claude model for ABAP remediation. claude-sonnet-4-6 is the cheap/fast default; the router escalates to anthropic_escalation_model on retry."
  default     = "claude-sonnet-4-6"
}

variable "anthropic_escalation_model" {
  type        = string
  description = "Claude model used on retry when the default model's fix fails the ATC gate. Defaults to the most capable available."
  default     = "claude-opus-4-7"
}

variable "ast_change_threshold" {
  type    = number
  default = 3
}

# ── Air-gapped LLM (Ollama + Gemma2) ─────────
variable "enable_airgapped_llm" {
  type        = bool
  description = "Provision the on-prem Ollama EC2 for local LLM inference (needs gpu_ami_id)"
  default     = false # off by default so `apply` is clean without a GPU AMI; set true + gpu_ami_id to enable
}
variable "llm_mode" {
  type        = string
  description = "GenAI routing mode: cloud, local, or dual. PINNED to 'cloud' (Bedrock-only) for the end-to-end pipeline test; local/dual will be re-enabled once the cloud loop is certified."
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

# ─────────────────────────────────────────────
# Bastion (reverse-SSH tunnel for Lambda -> laptop ECC)
# Empty = bastion is NOT provisioned. Set this to the name of an EXISTING
# AWS key pair (visible in EC2 console -> Key Pairs). The user keeps the
# .pem locally for SSH access; terraform just references the name.
# Default 'migrate4hana-key' is the user's existing key pair.
# Set to "" in terraform.tfvars to skip provisioning the bastion entirely.
# ─────────────────────────────────────────────
variable "bastion_key_pair_name" {
  type        = string
  default     = "migrate4hana-key"
  description = "Name of an existing AWS EC2 key pair for the bastion. Empty = no bastion provisioned."
}

variable "ssh_allowed_cidrs" {
  type        = list(string)
  default     = ["0.0.0.0/0"]
  description = "Source IP CIDRs allowed inbound SSH. Tighten to your home /32 for production."
}

# ─────────────────────────────────────────────
# S/4HANA CAL appliance public IP (drifts on every stop/start of the CAL VM).
# Empty = no Route 53 private zone created. Set this to enable Lambda's DNS
# resolution of vhcals4hci.dummy.nodomain.
# ─────────────────────────────────────────────
variable "s4_public_ip" {
  type        = string
  default     = ""
  description = "Current public IP of the SAP CAL S/4HANA appliance. Update on every CAL restart."
}
