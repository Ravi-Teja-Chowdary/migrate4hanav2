# ──────────────────────────────────────────────────────────────
# Migrate4HANA — Azure input variables
# ──────────────────────────────────────────────────────────────

# ── General ───────────────────────────────────────────────────

variable "location" {
  description = "Azure region for all resources"
  type        = string
  default     = "eastus2"
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

variable "alert_email" {
  description = "E-mail address for Azure Monitor action-group alerts"
  type        = string
}

# ── Networking ────────────────────────────────────────────────

variable "vnet_address_space" {
  description = "Address space for the Migrate4HANA VNet"
  type        = list(string)
  default     = ["10.10.0.0/16"]
}

variable "subnet_prefixes" {
  description = "CIDR prefixes for each subnet"
  type = object({
    functions  = string
    containers = string
    gpu        = string
    sap        = string
    endpoints  = string
  })
  default = {
    functions  = "10.10.1.0/24"
    containers = "10.10.2.0/24"
    gpu        = "10.10.3.0/24"
    sap        = "10.10.4.0/24"
    endpoints  = "10.10.5.0/24"
  }
}

variable "sap_rfc_cidr" {
  description = "On-premises SAP network CIDR (RFC/GUI connectivity)"
  type        = string
  default     = "172.16.0.0/12"
}

variable "s4hana_vm_ip" {
  description = "Private IP of the S/4HANA target VM (blank = none)"
  type        = string
  default     = ""
}

# ── GPU VM ────────────────────────────────────────────────────

variable "enable_gpu_vm" {
  description = "Provision a GPU VM for local LLM inference"
  type        = bool
  default     = false
}

variable "gpu_vm_size" {
  description = "Azure VM size for the GPU node"
  type        = string
  default     = "Standard_NC6s_v3"
}

variable "ssh_public_key" {
  description = "SSH public key for GPU VM admin access"
  type        = string
  default     = ""
}

# ── WAF ───────────────────────────────────────────────────────

variable "enable_waf" {
  description = "Enable Azure WAF in front of the API gateway"
  type        = bool
  default     = true
}

# ── Anthropic / LLM ──────────────────────────────────────────

variable "anthropic_api_key" {
  description = "Anthropic API key for Claude model access"
  type        = string
  sensitive   = true
  default     = ""
}

variable "anthropic_model" {
  description = "Anthropic Claude model identifier"
  type        = string
  default     = "claude-opus-4-6-20250219"
}

variable "local_llm_endpoint" {
  description = "HTTP endpoint of a self-hosted LLM (blank = use Anthropic Claude)"
  type        = string
  default     = ""
}

# ── AST / Analysis ───────────────────────────────────────────

variable "ast_change_threshold" {
  description = "Max allowed AST-change percentage before flagging a migration unit"
  type        = number
  default     = 3
}

# ── SAP RFC ───────────────────────────────────────────────────

variable "pyrfc_enabled" {
  description = "Enable PyRFC-based live SAP RFC connectivity"
  type        = bool
  default     = false
}

# ── Database Migration Service (DMS) ─────────────────────────

variable "ecc_db_host" {
  description = "Hostname of the source ECC database"
  type        = string
  default     = ""
}

variable "ecc_db_port" {
  description = "Port of the source ECC database"
  type        = string
  default     = "30015"
}

variable "ecc_db_name" {
  description = "Database name on the source ECC system"
  type        = string
  default     = ""
}

variable "s4_db_host" {
  description = "Hostname of the target S/4HANA database"
  type        = string
  default     = ""
}

variable "s4_db_port" {
  description = "Port of the target S/4HANA database"
  type        = string
  default     = "30015"
}

variable "s4_db_name" {
  description = "Database name on the target S/4HANA system"
  type        = string
  default     = ""
}

# ── Compute sizing ────────────────────────────────────────────

variable "function_app_sku" {
  description = "App Service Plan SKU for Azure Functions (Elastic Premium)"
  type        = string
  default     = "EP1"
}

variable "container_app_cpu" {
  description = "vCPU allocation for Container Apps workloads"
  type        = number
  default     = 4.0
}

variable "container_app_memory" {
  description = "Memory allocation for Container Apps workloads"
  type        = string
  default     = "16Gi"
}
