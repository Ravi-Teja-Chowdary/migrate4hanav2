variable "enable" {
  description = "Whether to create the GPU VM resources (Path B — Air-Gapped LLM)"
  type        = bool
  default     = false
}

variable "vm_size" {
  description = "Azure VM size for GPU workloads"
  type        = string
  default     = "Standard_NC6s_v3"
}

variable "ssh_public_key" {
  description = "SSH public key for VM admin access"
  type        = string
}

variable "gpu_subnet_id" {
  description = "Subnet ID for the GPU VM network interface"
  type        = string
}

variable "functions_subnet_prefix" {
  description = "CIDR prefix of the functions subnet (allowed to call Ollama API)"
  type        = string
}

variable "containers_subnet_prefix" {
  description = "CIDR prefix of the containers subnet (allowed to call Ollama API)"
  type        = string
}

variable "managed_identity_id" {
  description = "Resource ID of the User-Assigned Managed Identity"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

variable "resource_group_name" {
  description = "Name of the resource group"
  type        = string
}

variable "location" {
  description = "Azure region for resources"
  type        = string
}

variable "management_ip" {
  description = "IP address allowed for SSH management access"
  type        = string
  default     = "10.0.0.1"
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}
