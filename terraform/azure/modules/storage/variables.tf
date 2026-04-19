###############################################################################
# Storage Module — Variables
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

variable "storage_account_name" {
  description = "Globally unique name for the storage account (3-24 chars, lowercase alphanumeric only)"
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]{3,24}$", var.storage_account_name))
    error_message = "Storage account name must be 3-24 lowercase alphanumeric characters."
  }
}

variable "allowed_subnet_ids" {
  description = "List of subnet IDs allowed through network rules (functions and container-apps subnets)"
  type        = list(string)
}

variable "endpoints_subnet_id" {
  description = "Subnet ID for private endpoints"
  type        = string
}

variable "private_dns_zone_id" {
  description = "Private DNS zone ID for blob storage (privatelink.blob.core.windows.net)"
  type        = string
  default     = ""
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}
