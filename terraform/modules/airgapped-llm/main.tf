resource "aws_security_group" "airgapped_llm_sg" {
  name        = "airgapped-llm-sg"
  description = "Security group for Air-gapped Local LLM, strictly private traffic only"
  vpc_id      = var.vpc_id

  ingress {
    description = "Allow API traffic from Lambda subnets"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = var.lambda_private_subnets_cidr
  }

  egress {
    description = "Strictly no outbound internet"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.vpc_cidr] # Only internal VPC traffic allowed
  }
}

resource "aws_instance" "local_llm_gpu" {
  ami                    = var.gpu_ami_id # Amazon Linux 2 Deep Learning AMI or Custom AMI pre-loaded with Llama 3
  instance_type          = "g5.2xlarge"   # Cost-effective, single GPU mapping to InfoSec constraints
  subnet_id              = var.isolated_subnet_id
  vpc_security_group_ids = [aws_security_group.airgapped_llm_sg.id]

  iam_instance_profile = aws_iam_instance_profile.llm_profile.name

  root_block_device {
    volume_size = 500
    volume_type = "gp3"
    encrypted   = true
  }

  tags = {
    Name = "Migrate4HANA-AirGapped-LLM"
    Tier = "Secure"
  }
}

resource "aws_iam_role" "llm_role" {
  name = "airgapped-llm-role"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Action = "sts:AssumeRole", Effect = "Allow", Principal = { Service = "ec2.amazonaws.com" } }]
  })
}

resource "aws_iam_instance_profile" "llm_profile" {
  name = "airgapped-llm-profile"
  role = aws_iam_role.llm_role.name
}