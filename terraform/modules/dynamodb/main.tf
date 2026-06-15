resource "aws_dynamodb_table" "simplification_rules" {
  name         = "sap-simplification-rules"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "rule_id"

  attribute {
    name = "rule_id"
    type = "S"
  }

  attribute {
    name = "category"
    type = "S"
  }

  global_secondary_index {
    name            = "CategoryIndex"
    hash_key        = "category"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = {
    Environment = var.environment
    Service     = "Migrate4HANA"
  }
}

# ─────────────────────────────────────────────────────────────────────────────
# Auth & wizard tables — added 2026-06-15 for the AWS-style login UX rebuild.
# Per the migrate4hana-* naming convention used elsewhere; covered by the
# Lambda + api-server IAM policies that grant DynamoDB ops on
# `arn:aws:dynamodb:*:*:table/migrate4hana-*` already.
# ─────────────────────────────────────────────────────────────────────────────
resource "aws_dynamodb_table" "m4h_users" {
  name         = "migrate4hana-users-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "email"

  attribute {
    name = "email"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = {
    Environment = var.environment
    Service     = "Migrate4HANA"
    Component   = "AuthUserStore"
  }
}

resource "aws_dynamodb_table" "m4h_clients" {
  name         = "migrate4hana-clients-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "client_id"

  attribute {
    name = "client_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = {
    Environment = var.environment
    Service     = "Migrate4HANA"
    Component   = "AuthClientStore"
  }
}

# Wizard run-state — survives page navigation in the new UI flow.
# Partition by (user_email, run_id) so a user can have many in-flight wizards.
resource "aws_dynamodb_table" "m4h_wizard_state" {
  name         = "migrate4hana-wizard-state-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "user_email"
  range_key    = "run_id"

  attribute {
    name = "user_email"
    type = "S"
  }

  attribute {
    name = "run_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = {
    Environment = var.environment
    Service     = "Migrate4HANA"
    Component   = "WizardState"
  }
}

output "users_table_name" {
  value = aws_dynamodb_table.m4h_users.name
}

output "clients_table_name" {
  value = aws_dynamodb_table.m4h_clients.name
}

output "wizard_state_table_name" {
  value = aws_dynamodb_table.m4h_wizard_state.name
}