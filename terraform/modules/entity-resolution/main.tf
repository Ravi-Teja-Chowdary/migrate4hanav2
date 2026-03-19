###############################################################################
# AWS Entity Resolution — ML-powered Business Partner Deduplication
# Used by the data-hygiene Lambda for production-grade name/address matching
# when local Levenshtein+Soundex is insufficient.
###############################################################################

# -----------------------------------------------------------------------------
# S3 bucket for Entity Resolution input/output datasets
# -----------------------------------------------------------------------------
resource "aws_s3_bucket" "er_data" {
  bucket = "migrate4hana-entity-resolution-${var.environment}"

  tags = {
    Component = "EntityResolution"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "er_data" {
  bucket = aws_s3_bucket.er_data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "er_data" {
  bucket = aws_s3_bucket.er_data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "er_data" {
  bucket = aws_s3_bucket.er_data.id

  rule {
    id     = "expire-matching-output"
    status = "Enabled"

    expiration {
      days = 90
    }
  }
}

# -----------------------------------------------------------------------------
# Glue Database & Tables for Entity Resolution schema mapping
# -----------------------------------------------------------------------------
resource "aws_glue_catalog_database" "bp_matching" {
  name = "migrate4hana_bp_matching_${var.environment}"
}

resource "aws_glue_catalog_table" "customers" {
  database_name = aws_glue_catalog_database.bp_matching.name
  name          = "customers_kna1"

  table_type = "EXTERNAL_TABLE"

  parameters = {
    "classification" = "json"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.er_data.id}/input/customers/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }

    columns {
      name = "KUNNR"
      type = "string"
    }
    columns {
      name = "NAME1"
      type = "string"
    }
    columns {
      name = "STCD1"
      type = "string"
    }
    columns {
      name = "ORT01"
      type = "string"
    }
    columns {
      name = "PSTLZ"
      type = "string"
    }
    columns {
      name = "STRAS"
      type = "string"
    }
    columns {
      name = "LAND1"
      type = "string"
    }
  }
}

resource "aws_glue_catalog_table" "vendors" {
  database_name = aws_glue_catalog_database.bp_matching.name
  name          = "vendors_lfa1"

  table_type = "EXTERNAL_TABLE"

  parameters = {
    "classification" = "json"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.er_data.id}/input/vendors/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }

    columns {
      name = "LIFNR"
      type = "string"
    }
    columns {
      name = "NAME1"
      type = "string"
    }
    columns {
      name = "STCD1"
      type = "string"
    }
    columns {
      name = "ORT01"
      type = "string"
    }
    columns {
      name = "PSTLZ"
      type = "string"
    }
    columns {
      name = "STRAS"
      type = "string"
    }
    columns {
      name = "LAND1"
      type = "string"
    }
  }
}

# -----------------------------------------------------------------------------
# IAM Role for Entity Resolution
# -----------------------------------------------------------------------------
resource "aws_iam_role" "entity_resolution" {
  name = "migrate4hana-entity-resolution-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "entityresolution.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "entity_resolution" {
  name = "entity-resolution-access"
  role = aws_iam_role.entity_resolution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.er_data.arn,
          "${aws_s3_bucket.er_data.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetTable",
          "glue:GetPartitions",
          "glue:BatchGetPartition"
        ]
        Resource = [
          "arn:aws:glue:*:*:catalog",
          "arn:aws:glue:*:*:database/${aws_glue_catalog_database.bp_matching.name}",
          "arn:aws:glue:*:*:table/${aws_glue_catalog_database.bp_matching.name}/*"
        ]
      }
    ]
  })
}

# -----------------------------------------------------------------------------
# Entity Resolution Schema Mapping — Customers
# -----------------------------------------------------------------------------
resource "aws_entityresolution_schema_mapping" "customers" {
  schema_name = "migrate4hana-customers-${var.environment}"
  description = "SAP KNA1 customer master schema for BP deduplication"

  mapped_input_fields {
    field_name = "KUNNR"
    type       = "UNIQUE_ID"
  }
  mapped_input_fields {
    field_name = "NAME1"
    type       = "ORGANIZATION_NAME"
  }
  mapped_input_fields {
    field_name = "STCD1"
    type       = "UNIQUE_ID"
    group_name = "tax_id"
  }
  mapped_input_fields {
    field_name = "ORT01"
    type       = "ADDRESS_CITY"
  }
  mapped_input_fields {
    field_name = "PSTLZ"
    type       = "ADDRESS_POSTALCODE"
  }
  mapped_input_fields {
    field_name = "STRAS"
    type       = "ADDRESS_STREET"
  }
  mapped_input_fields {
    field_name = "LAND1"
    type       = "ADDRESS_COUNTRY"
  }
}

# -----------------------------------------------------------------------------
# Entity Resolution Schema Mapping — Vendors
# -----------------------------------------------------------------------------
resource "aws_entityresolution_schema_mapping" "vendors" {
  schema_name = "migrate4hana-vendors-${var.environment}"
  description = "SAP LFA1 vendor master schema for BP deduplication"

  mapped_input_fields {
    field_name = "LIFNR"
    type       = "UNIQUE_ID"
  }
  mapped_input_fields {
    field_name = "NAME1"
    type       = "ORGANIZATION_NAME"
  }
  mapped_input_fields {
    field_name = "STCD1"
    type       = "UNIQUE_ID"
    group_name = "tax_id"
  }
  mapped_input_fields {
    field_name = "ORT01"
    type       = "ADDRESS_CITY"
  }
  mapped_input_fields {
    field_name = "PSTLZ"
    type       = "ADDRESS_POSTALCODE"
  }
  mapped_input_fields {
    field_name = "STRAS"
    type       = "ADDRESS_STREET"
  }
  mapped_input_fields {
    field_name = "LAND1"
    type       = "ADDRESS_COUNTRY"
  }
}

# -----------------------------------------------------------------------------
# Entity Resolution Matching Workflow
# -----------------------------------------------------------------------------
resource "aws_entityresolution_matching_workflow" "bp_dedup" {
  workflow_name = "migrate4hana-bp-dedup-${var.environment}"
  description   = "Deduplicates SAP Customers (KNA1) and Vendors (LFA1) before CVI/BP conversion"
  role_arn      = aws_iam_role.entity_resolution.arn

  input_source_config {
    input_source_arn = "arn:aws:glue:${var.region}:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_database.bp_matching.name}/${aws_glue_catalog_table.customers.name}"
    schema_name      = aws_entityresolution_schema_mapping.customers.schema_name
  }

  input_source_config {
    input_source_arn = "arn:aws:glue:${var.region}:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_database.bp_matching.name}/${aws_glue_catalog_table.vendors.name}"
    schema_name      = aws_entityresolution_schema_mapping.vendors.schema_name
  }

  output_source_config {
    output_s3_path = "s3://${aws_s3_bucket.er_data.id}/output/"

    output {
      name = "KUNNR"
    }
    output {
      name = "LIFNR"
    }
    output {
      name = "NAME1"
    }
    output {
      name = "ORT01"
    }
  }

  resolution_techniques {
    resolution_type = "ML_MATCHING"
  }
}

data "aws_caller_identity" "current" {}

# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------
output "matching_workflow_arn" {
  value       = aws_entityresolution_matching_workflow.bp_dedup.arn
  description = "ARN of the Entity Resolution matching workflow"
}

output "er_bucket_name" {
  value       = aws_s3_bucket.er_data.id
  description = "S3 bucket for Entity Resolution input/output"
}
