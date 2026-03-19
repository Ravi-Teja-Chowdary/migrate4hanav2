variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "region" {
  description = "AWS region for Management API endpoint construction"
  type        = string
  default     = "us-east-1"
}
