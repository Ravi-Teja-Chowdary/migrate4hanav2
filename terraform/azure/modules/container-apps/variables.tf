###############################################################################
# Container Apps Module — Variables
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

variable "containers_subnet_id" {
  type        = string
  description = "Subnet ID delegated to the Container Apps environment"
}

variable "managed_identity_id" {
  type        = string
  description = "Resource ID of the user-assigned managed identity"
}

variable "managed_identity_client_id" {
  type        = string
  description = "Client ID of the user-assigned managed identity"
}

variable "keyvault_uri" {
  type        = string
  description = "URI of the Key Vault holding SAP RFC credentials and secrets"
}

variable "storage_account_name" {
  type        = string
  description = "Name of the staging storage account"
}

variable "cosmosdb_endpoint" {
  type        = string
  description = "Cosmos DB account endpoint URL"
}

variable "web_pubsub_connection_string" {
  type        = string
  sensitive   = true
  description = "Connection string for Azure Web PubSub (real-time telemetry)"
}

variable "image_tag" {
  type        = string
  default     = "latest"
  description = "Docker image tag to deploy (set via CI/CD)"
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Additional tags to apply to all resources"
}
