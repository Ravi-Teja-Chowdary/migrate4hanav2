# ──────────────────────────────────────────────────────────────
# VNet module — variables
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

variable "vnet_address_space" {
  description = "VNet address space"
  type        = list(string)
}

variable "subnet_prefixes" {
  description = "CIDR prefix for each subnet"
  type = object({
    functions  = string
    containers = string
    gpu        = string
    sap        = string
    endpoints  = string
  })
}

variable "sap_rfc_cidr" {
  description = "On-premises SAP network CIDR"
  type        = string
}

variable "s4hana_vnet_id" {
  description = "Resource ID of the S/4HANA VNet for peering (blank = no peering)"
  type        = string
  default     = ""
}

variable "tags" {
  description = "Resource tags"
  type        = map(string)
  default     = {}
}
