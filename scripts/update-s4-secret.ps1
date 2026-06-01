#requires -Version 5.1
<#
.SYNOPSIS
    Update the migrate4hana/<env>/s4hana-credentials secret + open S/4's
    security group to Lambda's NAT gateway IP.

.DESCRIPTION
    For Lambda -> S/4HANA we need:
      1. The credentials secret pointing at the current CAL public IP
      2. S/4's security group allowing Lambda's NAT EIP on RFC + HTTPS ports
      3. (Optional) Route 53 private hosted zone for hostname resolution
         - handled by `terraform apply` after you set s4_public_ip in tfvars

    This script does (1) and (2). Run AFTER `terraform apply` so the NAT
    EIP is available via terraform output.

.PARAMETER S4PublicIp
    Current public IP of the SAP CAL S/4HANA appliance. Required.

.PARAMETER S4Sysnr / S4Client / S4User
    S/4 connection details. Defaults match the CAL appliance shape.

.PARAMETER S4SecurityGroupId
    Security group on the S/4 CAL appliance. Default matches the user's
    existing CAL appliance SG.

.PARAMETER Region / Environment
    AWS region + terraform environment.

.EXAMPLE
    .\scripts\update-s4-secret.ps1 -S4PublicIp 44.199.212.89
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$S4PublicIp,
    [int]$S4Sysnr = 0,
    [string]$S4Client = "100",
    [string]$S4User = "MIGRATE_ADMI",
    [string]$S4SecurityGroupId = "sg-069323230a6ec4c55",
    [string]$Region = "us-east-1",
    [string]$Environment = "prod"
)

$ErrorActionPreference = "Stop"
function Write-Step { param([string]$m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Fail { param([string]$m) Write-Host "`nERROR: $m" -ForegroundColor Red; exit 1 }

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoRoot  = Resolve-Path (Join-Path $scriptDir "..")
$tfDir     = Join-Path $repoRoot "terraform\environments\$Environment"

# ── Resolve Lambda's NAT EIP ─────────────────────────────────────────────────
Write-Step "Resolve Lambda NAT EIP from terraform output"
Push-Location $tfDir
try {
    $natIp = (terraform output -raw nat_gateway_public_ip 2>$null).Trim()
} finally { Pop-Location }
if (-not $natIp) {
    Fail "nat_gateway_public_ip output missing. Run 'terraform apply' first."
}
Write-Host "  Lambda NAT EIP: $natIp"

# ── Pre-flight: confirm S/4 is reachable from the laptop on its public IP ────
Write-Step "Probe S/4HANA at ${S4PublicIp}:3300 (from laptop, sanity-check)"
$probe = Test-NetConnection $S4PublicIp -Port 3300 -InformationLevel Quiet
if (-not $probe) {
    Write-Host "  WARNING: laptop cannot reach ${S4PublicIp}:3300 - is the CAL appliance running?" -ForegroundColor Yellow
    Write-Host "  Continuing anyway (Lambda may still reach it after SG update)" -ForegroundColor Yellow
} else {
    Write-Host "  S/4 reachable from laptop: OK"
}

# ── Open S/4 security group to Lambda NAT EIP ────────────────────────────────
Write-Step "Authorise Lambda NAT EIP $natIp/32 in S/4 security group $S4SecurityGroupId"
$ipPerms = @"
[{"IpProtocol":"tcp","FromPort":3300,"ToPort":3300,"IpRanges":[{"CidrIp":"$natIp/32","Description":"Migrate4HANA Lambda NAT - RFC gateway"}]},
 {"IpProtocol":"tcp","FromPort":3200,"ToPort":3200,"IpRanges":[{"CidrIp":"$natIp/32","Description":"Migrate4HANA Lambda NAT - RFC dispatcher"}]},
 {"IpProtocol":"tcp","FromPort":44300,"ToPort":44301,"IpRanges":[{"CidrIp":"$natIp/32","Description":"Migrate4HANA Lambda NAT - HTTPS OData"}]}]
"@
aws ec2 authorize-security-group-ingress --region $Region `
    --group-id $S4SecurityGroupId `
    --ip-permissions $ipPerms 2>&1 | ForEach-Object {
    if ($_ -match "InvalidPermission.Duplicate") {
        Write-Host "  (Rule already exists - that's fine)" -ForegroundColor Yellow
    } elseif ($_ -match "An error occurred") {
        Write-Host "  ERROR: $_" -ForegroundColor Red
    } else {
        Write-Host "  $_"
    }
}

# ── Prompt for S/4 password ──────────────────────────────────────────────────
Write-Step "Provide S/4HANA password (input hidden)"
$secPwd = Read-Host -Prompt "S/4 password for user '$S4User'" -AsSecureString
$bstr   = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secPwd)
$pwd    = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
if (-not $pwd) { Fail "Empty password - refusing to write" }

# ── Update the secret ────────────────────────────────────────────────────────
# We use the hostname (resolved via Route 53 private zone inside the VPC) so
# pyrfc's internal gateway-allocate step gets a consistent name. The DNS A
# record was created by terraform from var.s4_public_ip.
$secretBody = @{
    ashost = "vhcals4hci.dummy.nodomain"
    sysnr  = "$S4Sysnr".PadLeft(2, '0')
    client = $S4Client
    user   = $S4User
    passwd = $pwd
    lang   = "EN"
    sid    = "S4H"
    public_ip = $S4PublicIp
    _note  = "Hostname resolved via Route 53 private zone in VPC; A record points at $S4PublicIp"
} | ConvertTo-Json -Compress

$secretId = "migrate4hana/$Environment/s4hana-credentials"

Write-Step "Update Secrets Manager: $secretId"
aws secretsmanager put-secret-value `
    --region $Region `
    --secret-id $secretId `
    --secret-string $secretBody `
    --output text --query "[ARN,VersionId]"

if ($LASTEXITCODE -ne 0) { Fail "Secrets Manager update failed" }

Write-Host "`n  Secret updated."
Write-Host ""
Write-Host "REMINDER: did you also run 'terraform apply' with -var s4_public_ip=$S4PublicIp ?" -ForegroundColor Yellow
Write-Host "  That creates the Route 53 private zone Lambda needs to resolve vhcals4hci.dummy.nodomain."
Write-Host "  If not, add to terraform.tfvars:"
Write-Host "      s4_public_ip = `"$S4PublicIp`""
Write-Host "  And run: cd terraform\environments\prod ; terraform apply -auto-approve"
