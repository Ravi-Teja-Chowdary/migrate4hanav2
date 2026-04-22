output "private_ip" {
  description = "Private IP of the Ollama EC2 instance"
  value       = aws_instance.ollama.private_ip
}

output "instance_id" {
  description = "EC2 instance ID of the Ollama server"
  value       = aws_instance.ollama.id
}

output "security_group_id" {
  description = "Security group ID of the Ollama instance"
  value       = aws_security_group.ollama.id
}
