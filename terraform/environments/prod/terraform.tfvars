###############################################################################
# Migrate4HANA — Production Environment Configuration
###############################################################################

aws_region  = "us-east-1"
environment = "prod"
alert_email = "sap-migration-oncall@company.com"

# VPC (3 AZs for high availability, different CIDR from dev/staging)
vpc_cidr             = "10.30.0.0/16"
availability_zones   = ["us-east-1a", "us-east-1b", "us-east-1c"]
private_subnet_cidrs = ["10.30.1.0/24", "10.30.2.0/24", "10.30.3.0/24"]
public_subnet_cidrs  = ["10.30.101.0/24", "10.30.102.0/24", "10.30.103.0/24"]

# VPN mandatory for production
enable_vpn_gateway = true
on_prem_cidr       = "172.16.0.0/12"

# S3
s3_staging_bucket = "migrate4hana-staging-prod"

# Lambda Layer (same layer ARN across environments)
pyrfc_layer_arn = ""

# WAF rate limiting (stricter for production)
waf_rate_limit = 1000

#S4HANA Public IP (CAL appliance — drifts on every stop/start)
s4_public_ip = "44.192.58.171"

# SAP CAL IDES EHP8 for SAP ERP 6.0 on SAP ASE (June 2021 build)
# Connect dialog shows SID=ABA (CAL naming) but it IS the full IDES appliance —
# business content lives in client 800. Hostname follows vhcal<sid>ci convention.
cal_ecc_public_ip = "44.205.3.93"
cal_ecc_hostname  = "vhcalabaci"
