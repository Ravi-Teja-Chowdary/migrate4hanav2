###############################################################################
# APIM Module — Variables
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

variable "sku_name" {
  type        = string
  default     = "Developer_1"
  description = "APIM SKU (Developer_1 for dev/test, Consumption_0 for low-cost dev, Standard_1 for prod)"
}

variable "publisher_name" {
  type        = string
  default     = "Migrate4HANA"
  description = "Publisher name shown in the APIM developer portal"
}

variable "publisher_email" {
  type        = string
  description = "Publisher contact email for the APIM instance"
}

variable "function_app_url" {
  type        = string
  description = "Base URL of the orchestrator / stage functions app (backend)"
}

variable "function_app_key_secret_uri" {
  type        = string
  default     = ""
  description = "Key Vault Secret URI for the function app host key (used in named value)"
}

variable "keyvault_id" {
  type        = string
  default     = ""
  description = "Resource ID of the Key Vault (for named value Key Vault references)"
}

variable "managed_identity_id" {
  type        = string
  default     = ""
  description = "Resource ID of user-assigned managed identity for Key Vault access"
}

variable "allowed_origins" {
  type        = list(string)
  default     = ["https://migrate4hana.azurewebsites.net"]
  description = "Allowed CORS origins for the API"
}

variable "rate_limit_calls" {
  type        = number
  default     = 100
  description = "Number of API calls allowed per rate-limit period"
}

variable "rate_limit_period" {
  type        = number
  default     = 60
  description = "Rate-limit renewal period in seconds"
}

variable "jwt_openid_config_url" {
  type        = string
  default     = ""
  description = "OpenID Connect metadata endpoint for JWT validation (e.g. Azure AD)"
}

variable "jwt_audiences" {
  type        = list(string)
  default     = []
  description = "Required audiences (aud claim) for JWT validation"
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Additional tags to apply to all resources"
}
