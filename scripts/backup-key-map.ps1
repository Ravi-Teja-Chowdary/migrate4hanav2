<#
.SYNOPSIS
    Takes an on-demand DynamoDB backup of a Tier-0 table (key_map, ledger, etc.).

.DESCRIPTION
    Per docs/DR.md section 2.2: operator MUST snapshot at cutover boundaries.
    This script:
      1. Confirms PITR is on (warn but don't block if off)
      2. Creates the on-demand backup
      3. Tags the backup with a human-readable label + run-id timestamp
      4. Verifies the backup status reached AVAILABLE

    With -VerifyOnly: skips backup creation, just spot-checks that 20 rows
    in the table look like valid key_map rows (object, source_key,
    target_key, run_id, written_at fields all present).

.EXAMPLE
    .\scripts\backup-key-map.ps1 -Table migrate4hana-key-map-prod -Tag pre-cutover-acme

.EXAMPLE
    .\scripts\backup-key-map.ps1 -Table migrate4hana-key-map-prod-restored -VerifyOnly

.NOTES
    Requires AWS CLI v2 + AWS credentials with dynamodb:CreateBackup,
    dynamodb:DescribeBackup, dynamodb:Scan permissions.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$Table,

    [string]$Tag = "manual",

    [switch]$VerifyOnly
)

$ErrorActionPreference = "Stop"

function Write-Info($msg) { Write-Host "[INFO]  $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "[OK]    $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[WARN]  $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "[ERROR] $msg" -ForegroundColor Red }


function Test-PITR {
    param([string]$T)
    $resp = aws dynamodb describe-continuous-backups --table-name $T `
        --query "ContinuousBackupsDescription.PointInTimeRecoveryDescription.PointInTimeRecoveryStatus" `
        --output text 2>$null
    return ($resp -eq "ENABLED")
}


function Verify-KeyMapShape {
    param([string]$T)
    Write-Info "Spot-checking 20 rows from $T..."
    $resp = aws dynamodb scan --table-name $T --limit 20 --output json | ConvertFrom-Json
    $required = @("object", "source_key", "target_key", "run_id", "written_at")
    $bad = 0
    foreach ($item in $resp.Items) {
        foreach ($f in $required) {
            if (-not $item.PSObject.Properties.Name -contains $f) {
                $bad++
                Write-Warn "  Row missing required field '$f': $($item | ConvertTo-Json -Compress)"
                break
            }
        }
    }
    if ($bad -eq 0) {
        Write-OK "All 20 spot-checked rows have the expected key_map shape."
        return $true
    } else {
        Write-Err "$bad of 20 rows are malformed -- table may be corrupted."
        return $false
    }
}


# ─── Main ─────────────────────────────────────────────────────────────────
Write-Info "Target table: $Table"

if ($VerifyOnly) {
    $ok = Verify-KeyMapShape -T $Table
    if ($ok) { exit 0 } else { exit 2 }
}

# Check PITR -- warn but proceed
if (Test-PITR -T $Table) {
    Write-OK "PITR is ENABLED on $Table (continuous backup baseline)"
} else {
    Write-Warn "PITR is NOT enabled on $Table. This on-demand backup is your ONLY recovery point."
}

# Construct a backup name -- AWS allows: backup-name a-zA-Z0-9._-
$ts        = (Get-Date -Format "yyyyMMdd-HHmmssZ")
$safeTag   = $Tag -replace "[^a-zA-Z0-9._-]", "-"
$backupNm  = "$Table-$safeTag-$ts"

Write-Info "Creating on-demand backup: $backupNm"
$createOut = aws dynamodb create-backup --table-name $Table --backup-name $backupNm --output json 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Err "create-backup failed: $createOut"
    exit 1
}

$backupArn = ($createOut | ConvertFrom-Json).BackupDetails.BackupArn
Write-Info "Backup ARN: $backupArn"

# Poll until AVAILABLE (typically 30s-2min)
$waited = 0
do {
    Start-Sleep -Seconds 15
    $waited += 15
    $status = aws dynamodb describe-backup --backup-arn $backupArn `
        --query "BackupDescription.BackupDetails.BackupStatus" --output text
    Write-Info "  Backup status after ${waited}s: $status"
} while ($status -eq "CREATING" -and $waited -lt 600)

if ($status -eq "AVAILABLE") {
    Write-OK "Backup AVAILABLE: $backupArn"
    Write-OK "Restore later with: .\scripts\restore-key-map.ps1 -FromBackup `"$backupArn`""
    exit 0
} else {
    Write-Err "Backup did not reach AVAILABLE within 10min. Final status: $status"
    exit 1
}
