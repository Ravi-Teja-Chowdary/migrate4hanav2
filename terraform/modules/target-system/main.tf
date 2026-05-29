###############################################################################
# Module: target-system
#
# Stands up the GREENFIELD S/4HANA target landscape for a lift-and-shift
# migration. This module assumes you are using AWS Launch Wizard for SAP
# (recommended for production) or a customer-supplied AMI for sandbox.
#
# Contains:
#   * Security groups for HANA + AppServer + ICM HTTPS
#   * IAM role for SSM + S3 staging bucket access (so transport-file-placer
#     and transport-import-executor can run tp via SSM Run Command)
#   * EFS for /usr/sap/trans (shared transport directory)
#   * SSM parameters that target-provisioner reads
#
# What this module does NOT do:
#   * It does not run SWPM. SWPM is invoked by lambda/target-provisioner
#     via SSM (sandbox mode) or by the Launch Wizard itself (prod mode).
#   * It does not configure HSR / cluster - that's a Launch Wizard concern
#     or a customer-Basis concern.
###############################################################################

variable "name_prefix"        { type = string }
variable "vpc_id"             { type = string }
variable "private_subnets"    { type = list(string) }
variable "build_sid" {
  type    = string
  default = "BLD"
}
variable "target_sid" {
  type    = string
  default = "S4H"
}
variable "tags" {
  type    = map(string)
  default = {}
}
variable "staging_bucket_arn" {
  type        = string
  description = "ARN of migrate4hana staging S3 bucket; runner needs read access"
}

###############################################################################
# IAM role for SAP hosts - SSM + S3 staging
###############################################################################
resource "aws_iam_role" "sap_host" {
  name = "${var.name_prefix}-sap-host"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect = "Allow",
      Principal = { Service = "ec2.amazonaws.com" },
      Action = "sts:AssumeRole"
    }]
  })
  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.sap_host.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "staging" {
  name = "${var.name_prefix}-staging-access"
  role = aws_iam_role.sap_host.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect = "Allow",
      Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
      Resource = [var.staging_bucket_arn, "${var.staging_bucket_arn}/*"]
    }]
  })
}

resource "aws_iam_instance_profile" "sap_host" {
  name = "${var.name_prefix}-sap-host"
  role = aws_iam_role.sap_host.name
}

###############################################################################
# Security groups
###############################################################################
resource "aws_security_group" "hana" {
  name   = "${var.name_prefix}-hana"
  vpc_id = var.vpc_id
  ingress {
    description = "HANA SQL"
    from_port   = 30013
    to_port     = 30015
    protocol    = "tcp"
    security_groups = [aws_security_group.app.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = var.tags
}

resource "aws_security_group" "app" {
  name   = "${var.name_prefix}-app"
  vpc_id = var.vpc_id
  ingress {
    description = "RFC gateway"
    from_port   = 3300
    to_port     = 3399
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]  # Tighten via your customer's CIDR list
  }
  ingress {
    description = "ICM HTTPS (idoc_xml SICF + OData)"
    from_port   = 44300
    to_port     = 44399
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = var.tags
}

###############################################################################
# EFS for /usr/sap/trans (shared transport directory between BUILD + target)
###############################################################################
resource "aws_efs_file_system" "trans" {
  creation_token   = "${var.name_prefix}-usrsaptrans"
  encrypted        = true
  performance_mode = "generalPurpose"
  throughput_mode  = "bursting"
  tags             = merge(var.tags, { Name = "${var.name_prefix}-usrsaptrans" })
}

resource "aws_efs_mount_target" "trans" {
  for_each        = toset(var.private_subnets)
  file_system_id  = aws_efs_file_system.trans.id
  subnet_id       = each.value
  security_groups = [aws_security_group.app.id]
}

###############################################################################
# SSM parameters consumed by lambda/target-provisioner
###############################################################################
resource "aws_ssm_parameter" "build_sid" {
  name  = "/migrate4hana/${var.name_prefix}/build_sid"
  type  = "String"
  value = var.build_sid
  tags  = var.tags
}
resource "aws_ssm_parameter" "target_sid" {
  name  = "/migrate4hana/${var.name_prefix}/target_sid"
  type  = "String"
  value = var.target_sid
  tags  = var.tags
}
resource "aws_ssm_parameter" "trans_efs_id" {
  name  = "/migrate4hana/${var.name_prefix}/trans_efs"
  type  = "String"
  value = aws_efs_file_system.trans.id
  tags  = var.tags
}
resource "aws_ssm_parameter" "instance_profile" {
  name  = "/migrate4hana/${var.name_prefix}/sap_instance_profile"
  type  = "String"
  value = aws_iam_instance_profile.sap_host.name
  tags  = var.tags
}

###############################################################################
# Outputs
###############################################################################
output "sap_host_iam_role_arn"     { value = aws_iam_role.sap_host.arn }
output "sap_host_instance_profile" { value = aws_iam_instance_profile.sap_host.name }
output "hana_security_group_id"    { value = aws_security_group.hana.id }
output "app_security_group_id"     { value = aws_security_group.app.id }
output "trans_efs_id"              { value = aws_efs_file_system.trans.id }
