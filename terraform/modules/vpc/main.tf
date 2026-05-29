###############################################################################
# VPC Module — Network foundation for SAP migration workloads
###############################################################################

variable "environment" { type = string }
variable "vpc_cidr" { type = string }
variable "availability_zones" { type = list(string) }
variable "private_subnet_cidrs" { type = list(string) }
variable "public_subnet_cidrs" { type = list(string) }
variable "enable_vpn_gateway" { type = bool }
variable "on_prem_cidr" { type = string }

# ── VPC ──────────────────────────────────────
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "migrate4hana-${var.environment}" }
}

# ── Subnets ──────────────────────────────────
resource "aws_subnet" "private" {
  count             = length(var.private_subnet_cidrs)
  vpc_id            = aws_vpc.main.id
  cidr_block        = var.private_subnet_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]

  tags = { Name = "migrate4hana-private-${count.index}-${var.environment}" }
}

resource "aws_subnet" "public" {
  count                   = length(var.public_subnet_cidrs)
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidrs[count.index]
  availability_zone       = var.availability_zones[count.index]
  map_public_ip_on_launch = true

  tags = { Name = "migrate4hana-public-${count.index}-${var.environment}" }
}

# ── Internet Gateway ─────────────────────────
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "migrate4hana-igw-${var.environment}" }
}

# ── NAT Gateway (for Lambda in private subnet)
resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = { Name = "migrate4hana-nat-eip-${var.environment}" }
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id
  tags          = { Name = "migrate4hana-nat-${var.environment}" }
}

# ── Route Tables ─────────────────────────────
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  tags = { Name = "migrate4hana-public-rt-${var.environment}" }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }
  tags = { Name = "migrate4hana-private-rt-${var.environment}" }
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  count          = length(aws_subnet.private)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# ── VPN Gateway (for on-prem ECC connectivity)
resource "aws_vpn_gateway" "main" {
  count  = var.enable_vpn_gateway ? 1 : 0
  vpc_id = aws_vpc.main.id
  tags   = { Name = "migrate4hana-vgw-${var.environment}" }
}

# ── Security Group for Lambda ────────────────
resource "aws_security_group" "lambda" {
  name_prefix = "migrate4hana-lambda-"
  vpc_id      = aws_vpc.main.id

  # Outbound to SAP ECC (RFC port 33XX where XX = system number)
  egress {
    from_port   = 3300
    to_port     = 3399
    protocol    = "tcp"
    cidr_blocks = [var.on_prem_cidr]
    description = "SAP RFC to on-prem ECC"
  }

  # Outbound HTTPS (for AWS services)
  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTPS to AWS services"
  }

  tags = { Name = "migrate4hana-lambda-sg-${var.environment}" }
}

# ── Outputs ──────────────────────────────────
output "vpc_id" { value = aws_vpc.main.id }
output "private_subnet_ids" { value = aws_subnet.private[*].id }
output "public_subnet_ids" { value = aws_subnet.public[*].id }
output "lambda_security_group_id" { value = aws_security_group.lambda.id }
output "default_security_group_id" { value = aws_vpc.main.default_security_group_id }
