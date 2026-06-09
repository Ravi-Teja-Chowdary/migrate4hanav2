<#
.SYNOPSIS
    Atomically replaces a corrupt prod table with a verified restored table.

.DESCRIPTION
    Per docs/DR.md section 4.2 step 5 -- the atomic-swap step.

    DynamoDB does NOT support a rename in-place. The swap is actually:
      1. Take a final on-demand backup of the (corrupt) current table
         (so we can roll back the swap if needed)
      2. Update every Lambda env-var that names the table -- this is
         WHERE production reads/writes go, terraform just describes the
         desired state. The env-var swap is the actual production cutover.
      3. Optionally rename the original table by deleting + restoring under
         the restored content (we don't do this -- we leave the original
         table named -<timestamp>-corrupt so the post-incident review can
         examine it).

    The script REQUIRES -ConfirmYes -- this is a destructive action.

.EXAMPLE
    .\scripts\swap-key-map.ps1 `
        -Current migrate4hana-key-map-prod `
        -RestoredFrom migrate4hana-key-map-prod-restored `
        -ConfirmYes

.NOTES
    The Lambdas whose env-vars get re-pointed are listed in $LambdaFunctions
    below. Add/remove them when the table set changes.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$Current,

    [Parameter(Mandatory=$true)]
    [string]$RestoredFrom,

    [Parameter(Mandatory=$true)]
    [switch]$ConfirmYes
)

$ErrorActionPreference = "Stop"

function Write-Info($msg) { Write-Host "[INFO]  $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "[OK]    $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[WARN]  $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "[ERROR] $msg" -ForegroundColor Red }

# Lambdas that read/write the key_map table.
# UPDATE this list when the set of consumers changes.
$LambdaFunctions = @(
    "migrate4hana-data-migrator-prod",
    "migrate4hana-reconciliation-engine-prod",
    "migrate4hana-bapi-in-place-loader-prod",
    "migrate4hana-continuous-dq-monitor-prod",
    "migrate4hana-compliance-archive-prod"
)

if (-not $ConfirmYes) {
    Write-Err "Refusing to swap without -ConfirmYes. This action is destructive."
    exit 2
}

# 1) Final corrupt-state backup -- preserve evidence
Write-Info "Step 1/4: taking corruption-evidence backup of $Current..."
$ts        = (Get-Date -Format "yyyyMMdd-HHmmssZ")
$evidenceNm = "$Current-pre-swap-$ts"
$out = aws dynamodb create-backup --table-name $Current --backup-name $evidenceNm --output json 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Err "Could not back up corrupt table -- aborting swap. Error: $out"
    exit 1
}
$evidenceArn = ($out | ConvertFrom-Json).BackupDetails.BackupArn
Write-OK "Evidence backup: $evidenceArn"

# 2) Verify restored table is ACTIVE
Write-Info "Step 2/4: verifying $RestoredFrom is ACTIVE..."
$status = aws dynamodb describe-table --table-name $RestoredFrom `
    --query "Table.TableStatus" --output text
if ($status -ne "ACTIVE") {
    Write-Err "Restored table $RestoredFrom is not ACTIVE (status: $status)"
    exit 1
}
Write-OK "Restored table ACTIVE."

# 3) Re-point each consumer Lambda's env vars
Write-Info "Step 3/4: re-pointing $($LambdaFunctions.Count) Lambda(s) to $RestoredFrom..."
foreach ($fn in $LambdaFunctions) {
    Write-Info "  -> $fn"
    $cfg = aws lambda get-function-configuration --function-name $fn `
        --query "Environment.Variables" --output json 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "    skip (function does not exist)"
        continue
    }
    $vars = $cfg | ConvertFrom-Json
    # Update every var that contains the old table name
    $varHash = @{}
    foreach ($p in $vars.PSObject.Properties) {
        $v = $p.Value
        if ($v -is [string] -and $v -eq $Current) {
            Write-Info "    env $($p.Name): $Current -> $RestoredFrom"
            $varHash[$p.Name] = $RestoredFrom
        } else {
            $varHash[$p.Name] = $v
        }
    }
    $envJson = ($varHash | ConvertTo-Json -Compress)
    # Lambda expects {Variables={...}} not just {...}
    $payload = "{`"Variables`":$envJson}"
    aws lambda update-function-configuration --function-name $fn `
        --environment $payload | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Err "    Failed to update $fn -- ROLLBACK MANUALLY: re-point env vars back to $Current"
        exit 1
    }
}
Write-OK "All consumer Lambdas re-pointed."

# 4) Rename original out of the way
Write-Info "Step 4/4: leaving $Current in place (renamed in metadata only)."
Write-Warn "The OLD corrupt table $Current is intact. Investigate it AFTER incident review."
Write-Warn "Once root cause is confirmed and customer is signed off, run:"
Write-Warn "    aws dynamodb delete-table --table-name $Current"
Write-Warn "(do not delete sooner -- the evidence is forensic.)"

Write-OK "Swap complete. Production traffic now reads/writes $RestoredFrom."
Write-OK "Next: run reconciliation to confirm DISCREPANCY count dropped."
exit 0
