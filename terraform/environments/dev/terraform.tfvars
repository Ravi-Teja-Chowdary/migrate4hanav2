###############################################################################
# Migrate4HANA — Dev Environment Configuration
# Fill in your values below
###############################################################################

aws_region  = "us-east-1"
environment = "dev"
alert_email = "your-email@company.com"

# VPC
vpc_cidr             = "10.10.0.0/16"
availability_zones   = ["us-east-1a", "us-east-1b"]
private_subnet_cidrs = ["10.10.1.0/24", "10.10.2.0/24"]
public_subnet_cidrs  = ["10.10.101.0/24", "10.10.102.0/24"]

# On-prem connectivity (enable when VPN/Direct Connect is set up)
enable_vpn_gateway = false
on_prem_cidr       = "172.16.0.0/12"

# S3
s3_staging_bucket = "migrate4hana-staging-dev"

# Lambda Layer for PyRFC (build this first — see scripts/setup-pyrfc.sh)
pyrfc_layer_arn = ""
