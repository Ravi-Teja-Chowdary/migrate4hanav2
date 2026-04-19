# ──────────────────────────────────────────────────────────────
# Migrate4HANA — PRODUCTION environment
# ──────────────────────────────────────────────────────────────

module "migrate4hana" {
  source = "../../"

  environment          = "prod"
  location             = "southindia"
  alert_email          = var.alert_email
  enable_gpu_vm        = true
  enable_waf           = true
  ssh_public_key       = var.ssh_public_key
  gpu_vm_size          = "Standard_NC24ads_A100_v4"
  function_app_sku     = "EP2"
  container_app_cpu    = 4.0
  container_app_memory = "16Gi"
  pyrfc_enabled        = true

  ecc_db_host = var.ecc_db_host
  ecc_db_name = var.ecc_db_name
  s4_db_host  = var.s4_db_host
  s4_db_name  = var.s4_db_name

  vnet_address_space = ["10.20.0.0/16"]
  subnet_prefixes = {
    functions  = "10.20.1.0/24"
    containers = "10.20.2.0/24"
    gpu        = "10.20.3.0/24"
    sap        = "10.20.4.0/24"
    endpoints  = "10.20.5.0/24"
  }
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
  type = string
}

variable "ecc_db_name" {
  type = string
}

variable "s4_db_host" {
  type = string
}

variable "s4_db_name" {
  type = string
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

output "apim_gateway_url" {
  value = module.migrate4hana.apim_gateway_url
}

output "waf_endpoint" {
  value = module.migrate4hana.waf_frontend_endpoint
}

output "gpu_vm_ip" {
  value = module.migrate4hana.gpu_vm_private_ip
}
