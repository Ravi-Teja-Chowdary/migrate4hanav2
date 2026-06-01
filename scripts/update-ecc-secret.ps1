#requires -Version 5.1
<#
.SYNOPSIS
    Update the migrate4hana/<env>/sap-credentials secret so Lambdas talk to the
    laptop ECC via the bastion's reverse-SSH tunnel.

.DESCRIPTION
    Patches the Secrets Manager secret value:
       ashost  -> bastion's PRIVATE IP (Lambda inside the VPC reaches it directly)
       sysnr   -> ECC system number
       client  -> ECC client (default 800)
       user    -> ECC user
       passwd  -> ECC password (prompted, never echoed)

    After this script + an active SSH tunnel, the deployed data-migrator Lambda
    can call pyrfc.Connection() and reach the laptop's ECC.

.PARAMETER EccSysnr / EccClient / EccUser
    SAP ECC connection details.

.PARAMETER Region / Environment
    AWS region + terraform environment (default us-east-1 / prod).

.PARAMETER BastionPrivateIp
    Override the bastion private IP. Default = read from terraform output.

.EXAMPLE
    .\scripts\update-ecc-secret.ps1
    # Prompts for ECC password; patches the secret using terraform-resolved
    # bastion private IP.
#>
[CmdletBinding()]
param(
    [int]$EccSysnr = 41,
    [string]$EccClient = "800",
    [string]$EccUser = "sapuser",
    [string]$Region = "us-east-1",
    [string]$Environment = "prod",
    [string]$BastionPrivateIp = ""
)

$ErrorActionPreference = "Stop"

function Write-Step { param([string]$m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Fail { param([string]$m) Write-Host "`nERROR: $m" -ForegroundColor Red; exit 1 }

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoRoot  = Resolve-Path (Join-Path $scriptDir "..")
$tfDir     = Join-Path $repoRoot "terraform\environments\$Environment"

# ── Resolve bastion private IP ────────────────────────────────────────────────
Write-Step "Resolve bastion private IP"
if (-not $BastionPrivateIp) {
    Push-Location $tfDir
    try {
        $BastionPrivateIp = (terraform output -raw bastion_private_ip 2>$null).Trim()
    } finally { Pop-Location }
}
if (-not $BastionPrivateIp) {
    Fail "Bastion private IP not found. Pass -BastionPrivateIp, or provision the bastion first (see scripts/launch-ecc-tunnel.ps1 for hints)."
}
Write-Host "  Bastion private IP: $BastionPrivateIp"

# ── Prompt for ECC password ───────────────────────────────────────────────────
Write-Step "Provide ECC password (input hidden)"
$secPwd = Read-Host -Prompt "ECC password for user '$EccUser'" -AsSecureString
$bstr   = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secPwd)
$pwd    = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
if (-not $pwd) { Fail "Empty password — refusing to write" }

# ── Build the secret payload ──────────────────────────────────────────────────
$secretBody = @{
    ashost = $BastionPrivateIp
    sysnr  = "$EccSysnr"
    client = $EccClient
    user   = $EccUser
    passwd = $pwd
    lang   = "EN"
    # Audit trail so future-you knows why ashost is a bastion IP
    _note  = "Pointed at bastion ${BastionPrivateIp}:33${EccSysnr} - tunnel must be UP. See scripts/launch-ecc-tunnel.ps1"
} | ConvertTo-Json -Compress

$secretId = "migrate4hana/$Environment/sap-credentials"

Write-Step "Update Secrets Manager: $secretId"
aws secretsmanager put-secret-value `
    --region $Region `
    --secret-id $secretId `
    --secret-string $secretBody `
    --output text --query "[ARN,VersionId]"

if ($LASTEXITCODE -ne 0) { Fail "Secrets Manager update failed" }

Write-Host "`n  Secret updated. Lambdas will pick up the new value on their next cold-start."
Write-Host "  To force a fresh fetch immediately: redeploy the data-migrator function"
Write-Host "  (or simply wait for the next invocation - the cache is per-execution-env)."
Write-Host ""
Write-Host "NEXT STEPS:" -ForegroundColor Yellow
Write-Host "  1. Make sure the SSH tunnel is running:"
Write-Host "       .\scripts\launch-ecc-tunnel.ps1 -SshKeyPath .\migrate4hana-bastion -Persistent"
Write-Host "  2. Trigger the data-migrator Lambda; it should reach ECC via the tunnel."
