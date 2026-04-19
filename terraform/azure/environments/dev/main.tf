# ──────────────────────────────────────────────────────────────
# Migrate4HANA — DEV environment
# ──────────────────────────────────────────────────────────────

module "migrate4hana" {
  source = "../../"

  environment          = "dev"
  location             = "eastus2"
  alert_email          = var.alert_email
  enable_gpu_vm        = false
  enable_waf           = false
  openai_model_name    = "gpt-4"
  openai_model_version = "turbo-2024-04-09"
  function_app_sku     = "EP1"
  container_app_cpu    = 4.0
  container_app_memory = "16Gi"
  pyrfc_enabled        = false
}

variable "alert_email" {
  description = "E-mail for Azure Monitor alerts"
  type        = string
}

output "resource_group" {
  value = module.migrate4hana.resource_group_name
}

output "function_app_url" {
  value = module.migrate4hana.function_app_url
}

output "keyvault_uri" {
  value = module.migrate4hana.keyvault_uri
}

output "cosmosdb_endpoint" {
  value = module.migrate4hana.cosmosdb_endpoint
}
