#requires -Version 5.1
<#
.SYNOPSIS
    Functional-consultant workflow for editing Migrate4HANA value-mapping
    matrix.json and ruleset.json in S3.

.DESCRIPTION
    Without this script, you'd be editing JSON directly in the S3 console (slow,
    error-prone, no validation). This script supports a clean pull -> edit ->
    validate -> push cycle:

      .\scripts\manage-value-maps.ps1 -Action pull
          Downloads s3://migrate4hana-mapping-prod-905418407458/mappings/
          to value-maps\ in your repo.

      (Edit value-maps\matrix.json or value-maps\ruleset.json in any text editor.)

      .\scripts\manage-value-maps.ps1 -Action validate
          Parses both files locally and prints a summary (table counts, rule
          counts, syntax errors). Does NOT touch S3.

      .\scripts\manage-value-maps.ps1 -Action push
          Validates (must pass), then uploads to S3, then sets the Lambda
          M4H_TRANSFORM_RULES env var so the engine picks up the new ruleset.

      .\scripts\manage-value-maps.ps1 -Action diff
          Compares local files vs S3 contents and prints what would change.

.PARAMETER Action
    pull | push | validate | diff

.PARAMETER MappingBucket
    Override the mapping bucket (defaults to migrate4hana-mapping-prod-905418407458).

.PARAMETER Region
    AWS region (default us-east-1).

.PARAMETER Environment
    prod | staging | dev (drives the Lambda function name suffix).

.EXAMPLE
    .\scripts\manage-value-maps.ps1 -Action pull
    .\scripts\manage-value-maps.ps1 -Action validate
    .\scripts\manage-value-maps.ps1 -Action push
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("pull","push","validate","diff")]
    [string]$Action,
    [string]$MappingBucket = "migrate4hana-mapping-prod-905418407458",
    [string]$Region        = "us-east-1",
    [string]$Environment   = "prod"
)

$ErrorActionPreference = "Stop"
function Write-Step { param([string]$m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Done { param([string]$m) Write-Host "    $m" -ForegroundColor Green }
function Write-Skip { param([string]$m) Write-Host "    $m" -ForegroundColor DarkGray }
function Fail       { param([string]$m) Write-Host "`nERROR: $m" -ForegroundColor Red; exit 1 }

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoRoot  = Resolve-Path (Join-Path $scriptDir "..")
$localDir  = Join-Path $repoRoot "value-maps"
$matrixLocal  = Join-Path $localDir "matrix.json"
$rulesetLocal = Join-Path $localDir "ruleset.json"
$matrixS3     = "s3://$MappingBucket/mappings/matrix.json"
$rulesetS3    = "s3://$MappingBucket/mappings/ruleset.json"

if (-not (Test-Path $localDir)) { New-Item -ItemType Directory $localDir | Out-Null }

# ── validate helper ──────────────────────────────────────────────────────────
function Test-MatrixFile {
    param([string]$path)
    if (-not (Test-Path $path)) {
        Write-Host "    matrix.json: MISSING ($path)" -ForegroundColor Red
        return $false
    }
    try {
        $j = Get-Content $path -Raw | ConvertFrom-Json
    } catch {
        Write-Host "    matrix.json: JSON parse error - $($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
    $tables = $j.PSObject.Properties.Name | Where-Object { $_ -notmatch '^_' }
    $totalEntries = 0
    foreach ($t in $tables) {
        $entries = $j.$t.PSObject.Properties.Name | Where-Object { $_ -notmatch '^_' }
        $totalEntries += $entries.Count
        Write-Host ("    {0,-24} {1,4} entries" -f $t, $entries.Count)
    }
    Write-Host ("    -> {0} tables, {1} entries total" -f $tables.Count, $totalEntries) -ForegroundColor Green
    return $true
}

function Test-RulesetFile {
    param([string]$path)
    if (-not (Test-Path $path)) {
        Write-Host "    ruleset.json: MISSING ($path)" -ForegroundColor Red
        return $false
    }
    try {
        $j = Get-Content $path -Raw | ConvertFrom-Json
    } catch {
        Write-Host "    ruleset.json: JSON parse error - $($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
    if (-not $j.object_rules) {
        Write-Host "    ruleset.json: missing 'object_rules' key" -ForegroundColor Red
        return $false
    }
    foreach ($obj in $j.object_rules.PSObject.Properties.Name) {
        $rules = $j.object_rules.$obj
        $tCount = if ($rules.transforms) { $rules.transforms.Count } else { 0 }
        $dqCount = if ($rules.dq_rules) { $rules.dq_rules.Count } else { 0 }
        Write-Host ("    {0,-16} {1,2} transforms  {2,2} DQ gates" -f $obj, $tCount, $dqCount)
    }
    Write-Host "    -> ruleset OK" -ForegroundColor Green
    return $true
}

# ── action: pull ─────────────────────────────────────────────────────────────
if ($Action -eq "pull") {
    Write-Step "Pulling matrix.json from $matrixS3"
    aws s3 cp $matrixS3 $matrixLocal --region $Region 2>&1 | ForEach-Object {
        if ($_ -match "does not exist") {
            Write-Host "    (not present in S3 yet - local matrix.json kept as-is)" -ForegroundColor Yellow
        } else {
            Write-Host "    $_"
        }
    }
    Write-Step "Pulling ruleset.json from $rulesetS3"
    aws s3 cp $rulesetS3 $rulesetLocal --region $Region 2>&1 | ForEach-Object {
        if ($_ -match "does not exist") {
            Write-Host "    (not present in S3 yet - local ruleset.json kept as-is)" -ForegroundColor Yellow
        } else {
            Write-Host "    $_"
        }
    }
    Write-Step "Local files now at:"
    Write-Host "    $matrixLocal"
    Write-Host "    $rulesetLocal"
    Write-Host ""
    Write-Host "Edit them in any editor, then run with -Action validate or -Action push." -ForegroundColor DarkGray
    exit 0
}

# ── action: validate ─────────────────────────────────────────────────────────
if ($Action -eq "validate") {
    Write-Step "Validating matrix.json"
    $okM = Test-MatrixFile $matrixLocal
    Write-Step "Validating ruleset.json"
    $okR = Test-RulesetFile $rulesetLocal
    if ($okM -and $okR) {
        Write-Host "`nValidation: PASS" -ForegroundColor Green
        exit 0
    } else {
        Write-Host "`nValidation: FAIL" -ForegroundColor Red
        exit 1
    }
}

# ── action: diff ─────────────────────────────────────────────────────────────
if ($Action -eq "diff") {
    foreach ($pair in @(@($matrixLocal,$matrixS3,"matrix.json"), @($rulesetLocal,$rulesetS3,"ruleset.json"))) {
        $local = $pair[0]; $s3 = $pair[1]; $name = $pair[2]
        Write-Step "diff: $name"
        $tmp = New-TemporaryFile
        aws s3 cp $s3 $tmp.FullName --region $Region --quiet 2>&1 | Out-Null
        if (-not (Test-Path $tmp) -or (Get-Item $tmp).Length -eq 0) {
            Write-Host "    S3 has no $name yet - local will be NEW" -ForegroundColor Yellow
        } else {
            $localHash = (Get-FileHash $local).Hash
            $s3Hash    = (Get-FileHash $tmp).Hash
            if ($localHash -eq $s3Hash) {
                Write-Done "no changes"
            } else {
                Write-Host "    DIFFERS (local hash $localHash; s3 hash $s3Hash)" -ForegroundColor Yellow
            }
        }
        Remove-Item $tmp -ErrorAction SilentlyContinue
    }
    exit 0
}

# ── action: push ─────────────────────────────────────────────────────────────
if ($Action -eq "push") {
    Write-Step "Pre-push validation"
    $okM = Test-MatrixFile $matrixLocal
    $okR = Test-RulesetFile $rulesetLocal
    if (-not ($okM -and $okR)) {
        Fail "Validation failed - fix errors above before pushing."
    }

    Write-Step "Uploading matrix.json -> $matrixS3"
    aws s3 cp $matrixLocal $matrixS3 --region $Region --content-type application/json
    Write-Step "Uploading ruleset.json -> $rulesetS3"
    aws s3 cp $rulesetLocal $rulesetS3 --region $Region --content-type application/json

    Write-Step "Activating engine: setting M4H_TRANSFORM_RULES on the data-migrator Lambda"
    $fn = "migrate4hana-data-migrator-$Environment"
    $curr = aws lambda get-function-configuration --region $Region --function-name $fn `
        --query "Environment.Variables" --output json | ConvertFrom-Json

    $vars = @{}
    $curr.PSObject.Properties | ForEach-Object { $vars[$_.Name] = $_.Value }
    $vars["M4H_TRANSFORM_RULES"] = $rulesetS3
    $envStr = "Variables={" + (($vars.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ",") + "}"

    aws lambda update-function-configuration `
        --region $Region --function-name $fn `
        --environment $envStr --output text --query "LastUpdateStatus" | Out-Null

    Write-Done "uploaded + Lambda env updated"
    Write-Host ""
    Write-Host "Lambda will use the new ruleset on its next cold start." -ForegroundColor DarkGray
    Write-Host "To force pickup immediately: re-run .\deploy-data-migrator.ps1" -ForegroundColor DarkGray
    exit 0
}
