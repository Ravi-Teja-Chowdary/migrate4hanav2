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

variable "model_name" {
  description = "OpenAI model name for deployment"
  type        = string
  default     = "gpt-4"
}

variable "model_version" {
  description = "OpenAI model version"
  type        = string
  default     = "turbo-2024-04-09"
}

variable "tokens_per_minute_capacity" {
  description = "Token capacity in thousands per minute"
  type        = number
  default     = 120
}

variable "subnet_id" {
  description = "Subnet ID for private endpoint and network ACLs"
  type        = string
}

variable "managed_identity_principal_id" {
  description = "Principal ID of the User-Assigned Managed Identity to grant OpenAI access"
  type        = string
}

variable "log_analytics_workspace_id" {
  description = "Log Analytics workspace ID for diagnostic settings"
  type        = string
}

variable "endpoints_subnet_id" {
  description = "Subnet ID for private endpoints"
  type        = string
  default     = ""
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}
