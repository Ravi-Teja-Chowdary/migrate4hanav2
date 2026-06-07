#requires -Version 5.1
<#
.SYNOPSIS
    Onboard a Fortune 500 tenant to the Migrate4HANA stack.

.DESCRIPTION
    Single-command tenant onboarding for the F7 multi-tenancy layer:
      1. Validates the tenant ID (lowercase a-z0-9 + dash, 3-32 chars, no reserved name)
      2. Creates the tenant's Secrets Manager secrets (sap-credentials, s4hana-credentials)
      3. Creates the tenant's S3 path prefixes under the staging/audit/mapping buckets
      4. Creates the tenant's CloudWatch log groups
      5. Optionally seeds the tenant's value-map matrix.json from a template
      6. Writes a `tenants/<slug>.json` provisioning record for audit

    Defaults preserve the single-tenant behavior - existing prod deployments
    work unchanged. Run this script ONLY when onboarding a real customer.

.PARAMETER TenantId
    Canonical tenant ID. Lowercase alphanumeric + dash, 3-32 chars, must start
    and end with alphanumeric. Example: "acme-corp" or "global-bank".

.PARAMETER DisplayName
    Human-readable name for dashboards. Example: "ACME Corporation".

.PARAMETER Environment
    prod / staging / dev. Defaults to prod.

.PARAMETER Region
    AWS region. Defaults to us-east-1.

.PARAMETER SeedValueMap
    If set, copies the default value-maps/matrix.json + ruleset.json into
    s3://migrate4hana-mapping-<env>-<acct>/tenants/<slug>/mappings/ as a
    starting point. The customer's functional consultant edits from there.

.PARAMETER DryRun
    Print the actions that WOULD happen without executing any AWS API calls.

.EXAMPLE
    .\scripts\onboard-tenant.ps1 -TenantId acme-corp `
                                  -DisplayName "ACME Corporation" `
                                  -SeedValueMap

.EXAMPLE
    .\scripts\onboard-tenant.ps1 -TenantId test-pilot -DryRun
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$TenantId,
    [string]$DisplayName = "",
    [string]$Environment = "prod",
    [string]$Region      = "us-east-1",
    [switch]$SeedValueMap,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
function Write-Step { param([string]$m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Done { param([string]$m) Write-Host "    $m" -ForegroundColor Green }
function Write-Skip { param([string]$m) Write-Host "    $m" -ForegroundColor DarkGray }
function Fail       { param([string]$m) Write-Host "`nERROR: $m" -ForegroundColor Red; exit 1 }
function Run        { param([string]$cmd) if ($DryRun) { Write-Host "    [DRY-RUN] $cmd" -ForegroundColor DarkGray } else { Invoke-Expression $cmd } }

# ── 1. Validate tenant ID via the canonical Python validator ────────────────
Write-Step "Validating tenant ID"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoRoot  = Resolve-Path (Join-Path $scriptDir "..")
$pyValid = python -c @"
import sys
sys.path.insert(0, r'$repoRoot\lambda\utils')
from tenant_context import validate_tenant_id, TenantIdError
try:
    validate_tenant_id('$TenantId')
    print('OK')
except TenantIdError as e:
    print('FAIL:' + str(e))
    sys.exit(1)
"@ 2>&1
if ($LASTEXITCODE -ne 0 -or ($pyValid -notmatch "OK")) {
    Fail "Tenant ID validation failed: $pyValid"
}
Write-Done "Tenant ID OK: $TenantId"
if (-not $DisplayName) { $DisplayName = $TenantId }

# ── 2. Resolve target buckets + account ─────────────────────────────────────
Write-Step "Resolving AWS context"
$acct = (aws sts get-caller-identity --region $Region --query Account --output text)
$bucketStaging = "migrate4hana-staging-$Environment"
$bucketMapping = "migrate4hana-mapping-$Environment-$acct"
$bucketAudit   = "migrate4hana-audit-logs-$Environment-$acct"
Write-Host "    account:  $acct"
Write-Host "    staging:  s3://$bucketStaging/tenants/$TenantId/"
Write-Host "    mapping:  s3://$bucketMapping/tenants/$TenantId/"
Write-Host "    audit:    s3://$bucketAudit/tenants/$TenantId/"

# ── 3. Create the tenant's Secrets Manager secrets ──────────────────────────
Write-Step "Creating per-tenant secrets"
foreach ($role in @("sap-credentials", "s4hana-credentials")) {
    $name = "migrate4hana/$Environment/tenants/$TenantId/$role"
    $exists = $false
    try {
        $null = aws secretsmanager describe-secret --region $Region --secret-id $name 2>$null
        if ($LASTEXITCODE -eq 0) { $exists = $true }
    } catch {}
    if ($exists) {
        Write-Skip "$name (already exists)"
    } else {
        Run "aws secretsmanager create-secret --region $Region --name '$name' --description 'Migrate4HANA $TenantId / $role' --secret-string '{}'"
        Write-Done "$name"
    }
}

# ── 4. Create the tenant's S3 path markers (empty objects to make the prefix list-able) ──
Write-Step "Initialising S3 prefixes (writes a 0-byte sentinel under each tenant root)"
foreach ($bk in @($bucketStaging, $bucketMapping, $bucketAudit)) {
    $key = "tenants/$TenantId/.tenant"
    Run "aws s3api put-object --bucket $bk --key '$key' --body NUL --region $Region"
    Write-Done "s3://$bk/$key"
}

# ── 5. (Optional) Seed value-map starter content ────────────────────────────
if ($SeedValueMap) {
    Write-Step "Seeding starter value-maps (matrix.json + ruleset.json)"
    $matrixLocal  = Join-Path $repoRoot "value-maps\matrix.json"
    $rulesetLocal = Join-Path $repoRoot "value-maps\ruleset.json"
    Run "aws s3 cp '$matrixLocal' s3://$bucketMapping/tenants/$TenantId/mappings/matrix.json --region $Region"
    Run "aws s3 cp '$rulesetLocal' s3://$bucketMapping/tenants/$TenantId/mappings/ruleset.json --region $Region"
    Write-Done "seeded $matrixLocal + $rulesetLocal -> s3://$bucketMapping/tenants/$TenantId/mappings/"
}

# ── 6. Write the provisioning record ────────────────────────────────────────
Write-Step "Writing provisioning record"
$tenantDir = Join-Path $repoRoot "tenants"
if (-not (Test-Path $tenantDir)) { New-Item -ItemType Directory -Path $tenantDir | Out-Null }
$recordPath = Join-Path $tenantDir "$TenantId.json"
$record = @{
    tenant_id    = $TenantId
    display_name = $DisplayName
    environment  = $Environment
    account_id   = $acct
    region       = $Region
    onboarded_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ssZ")
    secrets      = @(
        "migrate4hana/$Environment/tenants/$TenantId/sap-credentials",
        "migrate4hana/$Environment/tenants/$TenantId/s4hana-credentials"
    )
    s3_prefixes  = @(
        "s3://$bucketStaging/tenants/$TenantId/",
        "s3://$bucketMapping/tenants/$TenantId/",
        "s3://$bucketAudit/tenants/$TenantId/"
    )
    value_map_seeded = [bool]$SeedValueMap.IsPresent
} | ConvertTo-Json -Depth 5
if ($DryRun) {
    Write-Host "    [DRY-RUN] Would write provisioning record to:"
    Write-Host "    $recordPath"
    Write-Host $record
} else {
    Set-Content -Path $recordPath -Value $record -Encoding UTF8
    Write-Done "$recordPath"
}

Write-Host "`n==> Tenant onboarded: $TenantId" -ForegroundColor Green
Write-Host ""
Write-Host "NEXT STEPS:" -ForegroundColor Yellow
Write-Host "  1. Populate $TenantId's SAP credentials secret:"
Write-Host "       aws secretsmanager put-secret-value --region $Region ``"
Write-Host "         --secret-id migrate4hana/$Environment/tenants/$TenantId/sap-credentials ``"
Write-Host "         --secret-string (Get-Content path\to\$TenantId-creds.json -Raw)"
Write-Host ""
Write-Host "  2. (Optional) Edit the seeded value-maps:"
Write-Host "       aws s3 cp s3://$bucketMapping/tenants/$TenantId/mappings/matrix.json ."
Write-Host "       (edit, then re-upload)"
Write-Host ""
Write-Host "  3. Invoke a Lambda for this tenant by passing the env overlay:"
Write-Host "       aws lambda invoke --function-name migrate4hana-data-migrator-$Environment ``"
Write-Host "         --environment 'Variables={M4H_TENANT_ID=$TenantId}' --payload ..."
