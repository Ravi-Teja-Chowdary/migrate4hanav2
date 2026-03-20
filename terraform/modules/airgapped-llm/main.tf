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

  user_data = base64encode(<<-USERDATA
#!/bin/bash
set -e
exec > /var/log/llm-bootstrap.log 2>&1

# ── Configuration ──
MODEL_S3_PATH="${var.model_s3_path}"
MODEL_LOCAL_PATH="/opt/llm/models/llama-3-8b"
SERVE_PORT=8000

# ── Install vLLM inference server ──
pip install vllm>=0.4.0

# ── Download model from S3 (via VPC endpoint, no internet) ──
mkdir -p $MODEL_LOCAL_PATH
aws s3 cp $MODEL_S3_PATH $MODEL_LOCAL_PATH --recursive

# ── Start vLLM OpenAI-compatible server ──
nohup python -m vllm.entrypoints.openai.api_server \
  --model $MODEL_LOCAL_PATH \
  --host 0.0.0.0 \
  --port $SERVE_PORT \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.90 \
  --dtype float16 \
  > /var/log/vllm-server.log 2>&1 &

# ── Health check loop ──
for i in $(seq 1 60); do
  if curl -s http://localhost:$SERVE_PORT/health | grep -q ok; then
    echo "vLLM server healthy on port $SERVE_PORT"
    break
  fi
  echo "Waiting for vLLM server... ($i/60)"
  sleep 10
done
USERDATA
  )

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

resource "aws_iam_role_policy" "llm_s3_access" {
  name = "airgapped-llm-s3-model-access"
  role = aws_iam_role.llm_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::${var.model_s3_bucket}",
          "arn:aws:s3:::${var.model_s3_bucket}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_instance_profile" "llm_profile" {
  name = "airgapped-llm-profile"
  role = aws_iam_role.llm_role.name
}

# ── Outputs ──────────────────────────────────
output "instance_id" {
  value       = aws_instance.local_llm_gpu.id
  description = "EC2 instance ID of the air-gapped LLM GPU instance"
}

output "private_ip" {
  value       = aws_instance.local_llm_gpu.private_ip
  description = "Private IP of the air-gapped LLM instance (use for LOCAL_LLM_ENDPOINT)"
}

output "llm_endpoint" {
  value       = "http://${aws_instance.local_llm_gpu.private_ip}:8000/v1/completions"
  description = "Full HTTP endpoint for the local LLM inference server"
}