###############################################################################
# Functions Module — Variables
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

variable "sku" {
  type        = string
  default     = "EP1"
  description = "SKU for the Premium Elastic plan (EP1, EP2, EP3)"
}

variable "functions_subnet_id" {
  type        = string
  description = "Subnet ID for VNet integration of the function app"
}

variable "managed_identity_id" {
  type        = string
  description = "Resource ID of the user-assigned managed identity"
}

variable "managed_identity_client_id" {
  type        = string
  description = "Client ID of the user-assigned managed identity"
}

variable "storage_account_name" {
  type        = string
  description = "Name of the primary staging storage account"
}

variable "storage_account_key" {
  type        = string
  sensitive   = true
  description = "Access key for the primary staging storage account"
}

variable "cosmosdb_endpoint" {
  type        = string
  description = "Cosmos DB account endpoint URL"
}

variable "cosmosdb_key" {
  type        = string
  sensitive   = true
  description = "Cosmos DB primary key"
}

variable "keyvault_uri" {
  type        = string
  description = "URI of the Key Vault holding SAP RFC credentials and secrets"
}

variable "web_pubsub_connection_string" {
  type        = string
  sensitive   = true
  description = "Connection string for Azure Web PubSub (real-time telemetry)"
}

variable "anthropic_api_key_secret_uri" {
  type        = string
  description = "Key Vault Secret URI for the Anthropic API key (used in KV reference)"
}

variable "local_llm_host" {
  type        = string
  default     = ""
  description = "Ollama API endpoint for air-gapped GPU VM (e.g., http://10.0.5.4:11434)"
}

variable "local_llm_model" {
  type        = string
  default     = "gemma4:26b"
  description = "Ollama model name for air-gapped LLM inference"
}

variable "ast_change_threshold" {
  type        = number
  default     = 3
  description = "If AST engine finds fewer changes than this, escalate to GenAI"
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Additional tags to apply to all resources"
}
