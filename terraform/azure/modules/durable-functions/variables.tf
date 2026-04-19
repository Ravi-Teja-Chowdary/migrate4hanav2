###############################################################################
# Durable Functions Module — Variables
###############################################################################

variable "environment" {
  type        = string
  description = "Deployment environment (dev, staging, prod)"
}

variable "resource_group_name" {
  type        = string
  description = "Name of the Azure resource group"
}

variable "location" {
  type        = string
  description = "Azure region for all resources"
}

variable "functions_subnet_id" {
  type        = string
  description = "Subnet ID for VNet integration of the orchestrator function app"
}

variable "managed_identity_id" {
  type        = string
  description = "Resource ID of the user-assigned managed identity"
}

variable "managed_identity_client_id" {
  type        = string
  description = "Client ID of the user-assigned managed identity"
}

variable "service_plan_id" {
  type        = string
  default     = ""
  description = "Existing App Service Plan ID to share. If empty, a new plan is created."
}

variable "sku" {
  type        = string
  default     = "EP1"
  description = "SKU for the Elastic Premium plan (used only when service_plan_id is empty)"
}

variable "function_app_url" {
  type        = string
  description = "Base URL of the stage functions app (e.g. https://migrate4hana-func-dev.azurewebsites.net)"
}

variable "container_app_urls" {
  type        = map(string)
  description = "Map of container app name to internal URL (e.g. {discovery-engine = 'https://...' })"
}

variable "storage_connection_string" {
  type        = string
  sensitive   = true
  description = "Connection string for the Azure Storage account used by Durable Functions"
}

variable "keyvault_uri" {
  type        = string
  description = "URI of the Key Vault holding SAP RFC credentials and secrets"
}

variable "application_insights_connection_string" {
  type        = string
  sensitive   = true
  description = "Application Insights connection string for monitoring"
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Additional tags to apply to all resources"
}
