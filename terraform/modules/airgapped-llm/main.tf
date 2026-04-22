# EC2 instance running Ollama + Gemma2:27B in a private subnet
# No internet egress — serves local LLM inference for sensitive ABAP analysis

locals {
  name_prefix = "${var.environment}-airgapped-llm"
}

resource "aws_instance" "ollama" {
  ami                    = var.gpu_ami_id
  instance_type          = "g6.2xlarge"
  subnet_id              = var.private_subnet_id
  vpc_security_group_ids = [aws_security_group.ollama.id]
  iam_instance_profile   = aws_iam_instance_profile.ollama.name

  user_data = base64encode(templatefile("${path.module}/userdata.sh.tpl", {
    ollama_model = var.ollama_model
  }))

  root_block_device {
    volume_size = 100
    volume_type = "gp3"
  }

  tags = {
    Name        = local.name_prefix
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_security_group" "ollama" {
  name        = "${local.name_prefix}-sg"
  description = "Allow inbound 11434 from Lambda/ECS SG only; VPC-only egress"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 11434
    to_port         = 11434
    protocol        = "tcp"
    security_groups = [var.consumer_security_group_id]
    description     = "Ollama API from Lambda/ECS"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.vpc_cidr]
    description = "VPC-only egress (no internet)"
  }

  tags = {
    Name        = "${local.name_prefix}-sg"
    Environment = var.environment
  }
}

resource "aws_iam_role" "ollama" {
  name = "${local.name_prefix}-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ollama.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ollama" {
  name = "${local.name_prefix}-profile"
  role = aws_iam_role.ollama.name
}
