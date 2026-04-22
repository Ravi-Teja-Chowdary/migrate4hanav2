variable "environment" {
  description = "Deployment environment (dev/staging/prod)"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID where the instance will be deployed"
  type        = string
}

variable "vpc_cidr" {
  description = "VPC CIDR block for egress restriction"
  type        = string
}

variable "private_subnet_id" {
  description = "Private subnet ID for the Ollama EC2 instance"
  type        = string
}

variable "consumer_security_group_id" {
  description = "Security group ID of the Lambda/ECS consumers (allowed on port 11434)"
  type        = string
}

variable "gpu_ami_id" {
  description = "AMI ID for GPU instance (Amazon Linux 2 with CUDA drivers)"
  type        = string
}

variable "ollama_model" {
  description = "Ollama model to pull and serve"
  type        = string
  default     = "gemma2:27b"
}
