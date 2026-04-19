###############################################################################
# Data Migration Module — Variables
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

variable "data_factory_name" {
  description = "Name for the Azure Data Factory instance"
  type        = string
}

# --- ECC Source (Oracle) ---
variable "ecc_db_host" {
  description = "Hostname of the ECC source database (Oracle)"
  type        = string
}

variable "ecc_db_port" {
  description = "Port of the ECC source database"
  type        = number
  default     = 1521
}

variable "ecc_db_name" {
  description = "Database/service name of the ECC source"
  type        = string
}

# --- S/4HANA Target (HANA) ---
variable "s4_db_host" {
  description = "Hostname of the S/4HANA target database (SAP HANA)"
  type        = string
}

variable "s4_db_port" {
  description = "Port of the S/4HANA target database"
  type        = number
  default     = 30015
}

variable "s4_db_name" {
  description = "Database name of the S/4HANA target"
  type        = string
}

# --- Key Vault ---
variable "keyvault_id" {
  description = "Resource ID of the Azure Key Vault storing DB credential secrets"
  type        = string
}

variable "keyvault_uri" {
  description = "URI of the Azure Key Vault (e.g., https://myvault.vault.azure.net/)"
  type        = string
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}
