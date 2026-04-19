###############################################################################
# CosmosDB Module — Variables
###############################################################################

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
}

variable "resource_group_name" {
  description = "Name of the Azure resource group"
  type        = string
}

variable "location" {
  description = "Azure region for resource deployment"
  type        = string
}

variable "cosmosdb_account_name" {
  description = "Name for the Cosmos DB account"
  type        = string
}

variable "endpoints_subnet_id" {
  description = "Subnet ID for private endpoints"
  type        = string
}

variable "log_analytics_workspace_id" {
  description = "Resource ID of the Log Analytics workspace for diagnostic settings"
  type        = string
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}
