# ──────────────────────────────────────────────────────────────
# Key Vault module — variables
# ──────────────────────────────────────────────────────────────

variable "resource_group_name" {
  description = "Name of the parent resource group"
  type        = string
}

variable "location" {
  description = "Azure region"
  type        = string
}

variable "environment" {
  description = "Deployment environment"
  type        = string
}

variable "tenant_id" {
  description = "Azure AD tenant ID"
  type        = string
}

variable "tags" {
  description = "Resource tags"
  type        = map(string)
  default     = {}
}
