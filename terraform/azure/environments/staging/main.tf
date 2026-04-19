# ──────────────────────────────────────────────────────────────
# Migrate4HANA — STAGING environment
# ──────────────────────────────────────────────────────────────

module "migrate4hana" {
  source = "../../"

  environment          = "staging"
  location             = "eastus2"
  alert_email          = var.alert_email
  enable_gpu_vm        = true
  enable_waf           = true
  ssh_public_key       = var.ssh_public_key
  gpu_vm_size          = "Standard_NC6s_v3"
  openai_model_name    = "gpt-4"
  openai_model_version = "turbo-2024-04-09"
  function_app_sku     = "EP1"
  container_app_cpu    = 4.0
  container_app_memory = "16Gi"
  pyrfc_enabled        = true

  ecc_db_host = var.ecc_db_host
  ecc_db_name = var.ecc_db_name
  s4_db_host  = var.s4_db_host
  s4_db_name  = var.s4_db_name
}

variable "alert_email" {
  description = "E-mail for Azure Monitor alerts"
  type        = string
}

variable "ssh_public_key" {
  description = "SSH public key for GPU VM"
  type        = string
}

variable "ecc_db_host" {
  type    = string
  default = ""
}

variable "ecc_db_name" {
  type    = string
  default = ""
}

variable "s4_db_host" {
  type    = string
  default = ""
}

variable "s4_db_name" {
  type    = string
  default = ""
}

output "resource_group" {
  value = module.migrate4hana.resource_group_name
}

output "function_app_url" {
  value = module.migrate4hana.function_app_url
}

output "orchestrator_url" {
  value = module.migrate4hana.orchestrator_url
}

output "gpu_vm_ip" {
  value = module.migrate4hana.gpu_vm_private_ip
}
