<#
.SYNOPSIS
    Restores a Tier-0 DynamoDB table from PITR or from an on-demand backup.

.DESCRIPTION
    Per docs/DR.md section 4 -- the corruption recovery procedure.

    Two modes:
      -ToTimestamp     PITR: restore the source table state at the given UTC instant
      -FromBackup      Backup: restore from an on-demand backup ARN

    Restores to a NEW table name (so the operator can verify before swapping
    the production reference). Restored tables do NOT inherit PITR, SSE-KMS,
    or deletion-protection -- this script re-applies them.

.EXAMPLE
    .\scripts\restore-key-map.ps1 `
        -Table migrate4hana-key-map-prod `
        -ToTimestamp "2026-06-09T13:45:00Z" `
        -RestoreAs migrate4hana-key-map-prod-restored

.EXAMPLE
    .\scripts\restore-key-map.ps1 `
        -FromBackup "arn:aws:dynamodb:us-east-1:123:table/x/backup/y" `
        -RestoreAs migrate4hana-key-map-prod-restored

.NOTES
    PITR has a 35-day window. Backups have no expiry. Restore TIME is
    O(table size) -- typical 1M-row key_map restore is 5-15 minutes.
#>

[CmdletBinding(DefaultParameterSetName="PITR")]
param(
    [Parameter(Mandatory=$true)]
    [string]$RestoreAs,

    [Parameter(ParameterSetName="PITR", Mandatory=$true)]
    [string]$Table,

    [Parameter(ParameterSetName="PITR", Mandatory=$true)]
    [string]$ToTimestamp,

    [Parameter(ParameterSetName="Backup", Mandatory=$true)]
    [string]$FromBackup,

    [string]$KmsKeyArn = ""
)

$ErrorActionPreference = "Stop"

function Write-Info($msg) { Write-Host "[INFO]  $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "[OK]    $msg" -ForegroundColor Green }
function Write-Err($msg)  { Write-Host "[ERROR] $msg" -ForegroundColor Red }

Write-Info "Restoring to: $RestoreAs"

# Safety: confirm the target table name does not already exist
$exists = aws dynamodb describe-table --table-name $RestoreAs --query "Table.TableName" --output text 2>$null
if ($exists -eq $RestoreAs) {
    Write-Err "Target table $RestoreAs already exists. Delete it or pick a different name."
    exit 1
}

if ($PSCmdlet.ParameterSetName -eq "PITR") {
    Write-Info "Mode: PITR restore of $Table to $ToTimestamp"
    $out = aws dynamodb restore-table-to-point-in-time `
        --source-table-name $Table `
        --target-table-name $RestoreAs `
        --restore-date-time $ToTimestamp `
        --output json 2>&1
} else {
    Write-Info "Mode: Restore from backup $FromBackup"
    $out = aws dynamodb restore-table-from-backup `
        --backup-arn $FromBackup `
        --target-table-name $RestoreAs `
        --output json 2>&1
}

if ($LASTEXITCODE -ne 0) {
    Write-Err "restore command failed: $out"
    exit 1
}

Write-Info "Restore initiated. Waiting for table to become ACTIVE..."

$waited = 0
do {
    Start-Sleep -Seconds 30
    $waited += 30
    $status = aws dynamodb describe-table --table-name $RestoreAs `
        --query "Table.TableStatus" --output text 2>$null
    Write-Info "  Status after ${waited}s: $status"
} while (($status -eq "CREATING" -or $status -eq "UPDATING") -and $waited -lt 1800)

if ($status -ne "ACTIVE") {
    Write-Err "Restore did not reach ACTIVE within 30min. Final status: $status"
    exit 1
}

Write-OK "Restored table is ACTIVE: $RestoreAs"

# Re-attach PITR -- restore does NOT preserve this
Write-Info "Re-enabling PITR on the restored table..."
aws dynamodb update-continuous-backups --table-name $RestoreAs `
    --point-in-time-recovery-specification PointInTimeRecoveryEnabled=true | Out-Null

# Re-attach deletion protection -- also not preserved
Write-Info "Re-enabling deletion protection on the restored table..."
aws dynamodb update-table --table-name $RestoreAs --deletion-protection-enabled | Out-Null

if ($KmsKeyArn -ne "") {
    Write-Info "Re-applying customer-managed KMS key: $KmsKeyArn"
    aws dynamodb update-table --table-name $RestoreAs `
        --sse-specification "Enabled=true,SSEType=KMS,KMSMasterKeyId=$KmsKeyArn" | Out-Null
}

# Spot-check the restored shape
$itemCount = aws dynamodb describe-table --table-name $RestoreAs `
    --query "Table.ItemCount" --output text
Write-OK "Restored table $RestoreAs has $itemCount items (eventual -- updates lag a few hours)."

Write-OK "Next step: .\scripts\backup-key-map.ps1 -Table $RestoreAs -VerifyOnly"
Write-OK "If verify passes: .\scripts\swap-key-map.ps1 -Current $Table -RestoredFrom $RestoreAs -ConfirmYes"
exit 0
