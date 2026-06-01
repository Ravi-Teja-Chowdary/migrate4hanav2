###############################################################################
# Migrate4HANA — SSH Reverse-Tunnel Bastion
#
# A small t3.micro in the Migrate4HANA VPC's public subnet that lets the
# user's laptop expose its local SAP ECC over a reverse-SSH tunnel:
#
#   Laptop:  ssh -R 0.0.0.0:3341:192.168.100.129:3341 ec2-user@<bastion-public-ip>
#   AWS Lambda: pyrfc.Connection(ashost="<bastion-private-ip>", sysnr="41")
#                          ↓
#                    bastion:3341
#                          ↓ (reverse tunnel back through laptop)
#                    laptop's host-only-VMnet ECC at 192.168.100.129:3341
#
# Key requirement: sshd must have `GatewayPorts yes` so the reverse-tunneled
# port binds to 0.0.0.0 (default is 127.0.0.1, which Lambda can't reach).
# Handled in user_data.
###############################################################################

variable "environment"      { type = string }
variable "vpc_id"           { type = string }
variable "public_subnet_id" { type = string }
variable "private_subnet_ids" {
  type        = list(string)
  description = "Subnets that Lambdas live in; SG opens these CIDRs inward on the tunneled ports"
}
variable "ssh_public_key" {
  type        = string
  description = "OpenSSH-format public key for the laptop user. Generate with: ssh-keygen -t ed25519 -C migrate4hana-bastion"
}
variable "ssh_allowed_cidrs" {
  type        = list(string)
  default     = ["0.0.0.0/0"]
  description = "Source IP CIDRs allowed inbound SSH (port 22). Default open-to-internet; tighten to your home /32 for production."
}
variable "tunneled_ports" {
  type        = list(number)
  default     = [3341, 3300, 3200]
  description = "Ports the SG opens from the Lambda subnets to the bastion (ECC RFC 3341 + S/4 RFC 3300/3200 if also tunneled)"
}

# ─────────────────────────────────────────────
# SSH key pair
# ─────────────────────────────────────────────
resource "aws_key_pair" "bastion" {
  key_name   = "migrate4hana-bastion-${var.environment}"
  public_key = var.ssh_public_key
  tags = {
    Name      = "migrate4hana-bastion-${var.environment}"
    Component = "ConnectivityBastion"
  }
}

# ─────────────────────────────────────────────
# Security group
#   inbound: SSH 22 from the user's IP(s)
#   inbound: tunneled ports from Lambda subnets (so Lambda can reach the
#            reverse-tunneled local services)
#   outbound: all (so SSH can reach back to user + general egress)
# ─────────────────────────────────────────────
resource "aws_security_group" "bastion" {
  name        = "migrate4hana-bastion-${var.environment}"
  description = "Migrate4HANA reverse-SSH-tunnel bastion"
  vpc_id      = var.vpc_id

  ingress {
    description = "SSH from user laptop"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.ssh_allowed_cidrs
  }

  dynamic "ingress" {
    for_each = var.tunneled_ports
    content {
      description = "Reverse-tunneled SAP port ${ingress.value} from VPC Lambdas"
      from_port   = ingress.value
      to_port     = ingress.value
      protocol    = "tcp"
      cidr_blocks = ["10.0.0.0/8"] # wide enough to catch any private subnet
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name      = "migrate4hana-bastion-${var.environment}"
    Component = "ConnectivityBastion"
  }
}

# ─────────────────────────────────────────────
# AMI — Amazon Linux 2023 (latest)
# ─────────────────────────────────────────────
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-*-kernel-*-x86_64"]
  }
}

# ─────────────────────────────────────────────
# EC2 instance
# ─────────────────────────────────────────────
resource "aws_instance" "bastion" {
  ami                         = data.aws_ami.al2023.id
  instance_type               = "t3.micro"
  key_name                    = aws_key_pair.bastion.key_name
  vpc_security_group_ids      = [aws_security_group.bastion.id]
  subnet_id                   = var.public_subnet_id
  associate_public_ip_address = true

  # User data: enable GatewayPorts so reverse-tunneled ports bind to 0.0.0.0
  # (default sshd config binds them to 127.0.0.1, which is invisible to other
  # network hosts including Lambdas in this VPC).
  user_data = <<-EOF
              #!/bin/bash
              set -euo pipefail
              # Allow reverse-tunneled ports to bind to all interfaces
              if ! grep -q "^GatewayPorts yes" /etc/ssh/sshd_config; then
                  echo "GatewayPorts clientspecified" >> /etc/ssh/sshd_config
              fi
              # Keep idle SSH sessions alive (tunnel won't drop on idle)
              if ! grep -q "^ClientAliveInterval" /etc/ssh/sshd_config; then
                  echo "ClientAliveInterval 60" >> /etc/ssh/sshd_config
                  echo "ClientAliveCountMax 30" >> /etc/ssh/sshd_config
              fi
              systemctl restart sshd
              # Mark the instance as configured (visible in instance metadata)
              echo "migrate4hana-bastion-ready" > /var/log/m4h-bastion-init.done
              EOF

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  tags = {
    Name      = "migrate4hana-bastion-${var.environment}"
    Component = "ConnectivityBastion"
  }
}

# ─────────────────────────────────────────────
# Elastic IP — so the bastion's public IP doesn't drift on stop/start
# ─────────────────────────────────────────────
resource "aws_eip" "bastion" {
  instance = aws_instance.bastion.id
  domain   = "vpc"
  tags = {
    Name      = "migrate4hana-bastion-${var.environment}"
    Component = "ConnectivityBastion"
  }
}

# ─────────────────────────────────────────────
# Outputs
# ─────────────────────────────────────────────
output "public_ip" {
  value       = aws_eip.bastion.public_ip
  description = "Bastion public IP — use in: ssh ec2-user@<this>"
}

output "private_ip" {
  value       = aws_instance.bastion.private_ip
  description = "Bastion private IP — Lambda reaches the tunneled ECC via <this>:3341"
}

output "security_group_id" {
  value       = aws_security_group.bastion.id
  description = "Attach to Lambda's outbound rules if not already in 10.0.0.0/8"
}

output "ssh_command_hint" {
  value = "ssh -i <your-private-key> -R 0.0.0.0:3341:192.168.100.129:3341 ec2-user@${aws_eip.bastion.public_ip}"
  description = "Copy-paste hint for the reverse-tunnel command"
}
