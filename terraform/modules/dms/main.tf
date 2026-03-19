resource "aws_dms_replication_subnet_group" "sap_dms_subnet" {
  replication_subnet_group_description = "Subnet group for SAP to S/4HANA DMS"
  replication_subnet_group_id          = "sap-dms-subnet-group"
  subnet_ids                           = var.private_subnet_ids

  tags = {
    Name = "sap-dms-subnet-group"
  }
}

resource "aws_dms_replication_instance" "sap_dms_instance" {
  allocated_storage           = var.dms_storage_size
  apply_immediately           = true
  auto_minor_version_upgrade  = true
  availability_zone           = var.availability_zone
  engine_version              = "3.5.1"
  multi_az                    = var.multi_az
  publicly_accessible         = false
  replication_instance_class  = var.dms_instance_class
  replication_instance_id     = "sap-migration-dms-instance"
  replication_subnet_group_id = aws_dms_replication_subnet_group.sap_dms_subnet.id
  vpc_security_group_ids      = [var.security_group_id]

  tags = {
    Name = "SAP Migration DMS Instance"
  }
}

resource "aws_dms_endpoint" "ecc_source" {
  endpoint_id   = "ecc-source-endpoint"
  endpoint_type = "source"
  engine_name   = "oracle" # Example ECC backend
  server_name   = var.ecc_db_host
  port          = var.ecc_db_port
  database_name = var.ecc_db_name
  username      = var.ecc_db_user
  password      = var.ecc_db_password
}

resource "aws_dms_endpoint" "s4hana_target" {
  endpoint_id   = "s4hana-target-endpoint"
  endpoint_type = "target"
  engine_name   = "saphana"
  server_name   = var.s4_db_host
  port          = var.s4_db_port
  database_name = var.s4_db_name
  username      = var.s4_db_user
  password      = var.s4_db_password
}

resource "aws_dms_replication_task" "sap_delta_sync" {
  migration_type           = "full-load-and-cdc"
  replication_instance_arn = aws_dms_replication_instance.sap_dms_instance.replication_instance_arn
  replication_task_id      = "sap-migration-task"
  source_endpoint_arn      = aws_dms_endpoint.ecc_source.endpoint_arn
  target_endpoint_arn      = aws_dms_endpoint.s4hana_target.endpoint_arn
  table_mappings           = file("${path.module}/table_mappings.json")

  replication_task_settings = jsonencode({
    "Logging" = {
      "EnableLogging" = true,
      "LogComponents" = [
        { "Id" = "SOURCE_CAPTURE", "Severity" = "LOGGER_SEVERITY_DEFAULT" },
        { "Id" = "TARGET_APPLY",   "Severity" = "LOGGER_SEVERITY_DEFAULT" }
      ]
    },
    "FullLoadSettings" = {
      "MaxFullLoadSubTasks"  = 8,
      "CommitRate"           = 50000,
      "TargetTablePrepMode"  = "DO_NOTHING"
    },
    "ChangeProcessingDdlHandlingPolicy" = {
      "HandleSourceTableDropped"   = true,
      "HandleSourceTableTruncated" = true,
      "HandleSourceTableAltered"   = true
    },
    "ChangeProcessingTuning" = {
      "BatchApplyEnabled"     = true,
      "MinTransactionSize"    = 1000,
      "CommitTimeout"         = 1,
      "MemoryLimitTotal"      = 1024,
      "MemoryKeepTime"        = 60,
      "StatementCacheSize"    = 50
    },
    "StreamBufferSettings" = {
      "StreamBufferCount" = 3,
      "StreamBufferSizeInMB" = 8
    },
    "ErrorBehavior" = {
      "DataErrorPolicy"           = "LOG_ERROR",
      "DataTruncationErrorPolicy" = "LOG_ERROR",
      "DataErrorEscalationPolicy" = "SUSPEND_TABLE",
      "TableErrorPolicy"          = "SUSPEND_TABLE",
      "TableErrorEscalationPolicy" = "STOP_TASK",
      "RecoverableErrorCount"     = 5,
      "RecoverableErrorInterval"  = 5,
      "RecoverableErrorThrottling"          = true,
      "RecoverableErrorThrottlingMax"       = 1800,
      "RecoverableErrorStopRetryAfterThrottlingMax" = true,
      "ApplyErrorDeletePolicy"    = "IGNORE_RECORD",
      "ApplyErrorInsertPolicy"    = "LOG_ERROR",
      "ApplyErrorUpdatePolicy"    = "LOG_ERROR"
    },
    "TargetMetadata" = {
      "TargetSchema"       = "",
      "SupportLobs"        = true,
      "FullLobMode"        = false,
      "LobChunkSize"       = 64,
      "LimitedSizeLobMode" = true,
      "LobMaxSize"         = 32
    }
  })

  tags = {
    Name = "SAP Full Load and CDC Task"
  }
}

# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------
output "dms_task_arn" {
  value       = aws_dms_replication_task.sap_delta_sync.replication_task_arn
  description = "ARN of the DMS replication task for SAP data sync"
}

output "dms_instance_arn" {
  value       = aws_dms_replication_instance.sap_dms_instance.replication_instance_arn
  description = "ARN of the DMS replication instance"
}

output "dms_endpoint_ecc_arn" {
  value       = aws_dms_endpoint.ecc_source.endpoint_arn
  description = "ARN of the ECC source DMS endpoint"
}

output "dms_endpoint_s4_arn" {
  value       = aws_dms_endpoint.s4hana_target.endpoint_arn
  description = "ARN of the S/4HANA target DMS endpoint"
}
