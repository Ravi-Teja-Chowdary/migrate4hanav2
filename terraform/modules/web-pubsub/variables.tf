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

variable "sku" {
  description = "SKU for Web PubSub (Free_F1 for dev, Standard_S1 for prod)"
  type        = string
  default     = "Standard_S1"
}

variable "function_app_url" {
  description = "Function App URL for event handler (connect/disconnect events)"
  type        = string
}

variable "managed_identity_principal_id" {
  description = "Principal ID of the Managed Identity to grant Web PubSub access"
  type        = string
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}
