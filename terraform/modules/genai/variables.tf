variable "resource_group_name" {
  description = "Name of the resource group"
  type        = string
}

variable "location" {
  description = "Azure region for resources"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

variable "keyvault_id" {
  description = "Resource ID of the Key Vault to store the Anthropic API key"
  type        = string
}

variable "anthropic_api_key" {
  description = "Anthropic API key for Claude model access"
  type        = string
  sensitive   = true
}
