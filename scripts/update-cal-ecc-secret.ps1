#requires -Version 5.1
<#
.SYNOPSIS
    Point Migrate4HANA Lambdas at the SAP CAL ECC IDES appliance + open its
    security group to Lambda's NAT EIP.

.DESCRIPTION
    For Lambda -> CAL ECC we need:
      1. The sap-credentials secret pointing at the current CAL ECC public IP
         (via the Route 53 private-zone hostname so the kernel back-verify
         doesn't try to dial an unreachable laptop IP)
      2. ECC's CAL security group allowing Lambda's NAT EIP on RFC ports
      3. (Optional) Route 53 A record for vhcalerphci.dummy.nodomain
         - handled by `terraform apply` once cal_ecc_public_ip is in tfvars

    This script does (1) and (2). Run AFTER `terraform apply` so the NAT EIP
    is available via `terraform output -raw nat_gateway_public_ip`.

.PARAMETER CalEccPublicIp
    Current public IP of the CAL ECC appliance. Required.

.PARAMETER CalEccHostname
    Kernel-internal hostname of the ECC appliance. Default 'vhcalerphci' for
    IDES EHP8. Override if your CAL console shows a different one.

.PARAMETER EccSysnr / EccClient / EccUser / EccSid
    SAP ECC connection details. Defaults match SAP CAL IDES EHP8.

.PARAMETER CalEccSecurityGroupId
    Security group on the CAL ECC appliance. Look it up in EC2 console
    (the CAL appliance launches its own SG distinct from S/4's). REQUIRED
    unless you've already opened 0.0.0.0/0 for testing - then pass "" to skip.

.PARAMETER Region / Environment
    AWS region + terraform environment.

.EXAMPLE
    .\scripts\update-cal-ecc-secret.ps1 -CalEccPublicIp 13.220.66.158
    # Skips SG narrowing (user has 0.0.0.0/0 open for testing).

.EXAMPLE
    .\scripts\update-cal-ecc-secret.ps1 -CalEccPublicIp 13.220.66.158 -CalEccSecurityGroupId sg-0abc123
    # Also locks SG down to Lambda NAT EIP only.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$CalEccPublicIp,
    [string]$CalEccHostname = "vhcalabaci",
    [int]$EccSysnr = 0,
    [string]$EccClient = "800",      # IDES content client (per CAL Getting Started Guide)
    [string]$EccUser = "IDADMIN",    # IDES migration-scenario user (password 'ides123')
    [string]$EccSid = "ABA",
    [string]$CalEccSecurityGroupId = "",
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

# ── Pre-flight: confirm CAL ECC is reachable from the laptop ─────────────────
$eccPort = 3300 + $EccSysnr
Write-Step "Probe CAL ECC at ${CalEccPublicIp}:$eccPort (from laptop, sanity-check)"
$probe = Test-NetConnection $CalEccPublicIp -Port $eccPort -InformationLevel Quiet
if (-not $probe) {
    Write-Host "  WARNING: laptop cannot reach ${CalEccPublicIp}:$eccPort - is the CAL appliance running and SAP started?" -ForegroundColor Yellow
    Write-Host "  Continuing anyway (Lambda may still reach it from inside AWS)" -ForegroundColor Yellow
} else {
    Write-Host "  CAL ECC reachable from laptop: OK"
}

# ── Open CAL ECC security group to Lambda NAT EIP (if SG provided) ───────────
if ($CalEccSecurityGroupId) {
    Write-Step "Authorise Lambda NAT EIP $natIp/32 in CAL ECC SG $CalEccSecurityGroupId"
    $ipPerms = @"
[{"IpProtocol":"tcp","FromPort":3300,"ToPort":3399,"IpRanges":[{"CidrIp":"$natIp/32","Description":"Migrate4HANA Lambda NAT - RFC gateway"}]},
 {"IpProtocol":"tcp","FromPort":3200,"ToPort":3299,"IpRanges":[{"CidrIp":"$natIp/32","Description":"Migrate4HANA Lambda NAT - RFC dispatcher"}]},
 {"IpProtocol":"tcp","FromPort":4800,"ToPort":4899,"IpRanges":[{"CidrIp":"$natIp/32","Description":"Migrate4HANA Lambda NAT - Message server"}]}]
"@
    aws ec2 authorize-security-group-ingress --region $Region `
        --group-id $CalEccSecurityGroupId `
        --ip-permissions $ipPerms 2>&1 | ForEach-Object {
        if ($_ -match "InvalidPermission.Duplicate") {
            Write-Host "  (Rule already exists - that's fine)" -ForegroundColor Yellow
        } elseif ($_ -match "An error occurred") {
            Write-Host "  ERROR: $_" -ForegroundColor Red
        } else {
            Write-Host "  $_"
        }
    }
} else {
    Write-Host "`n==> SG narrowing skipped (no -CalEccSecurityGroupId provided)" -ForegroundColor Yellow
    Write-Host "  Make sure CAL ECC's SG allows Lambda NAT EIP $natIp on ports 3300/3200" -ForegroundColor Yellow
    Write-Host "  (0.0.0.0/0 is fine for testing; lock it down before any real client demo)" -ForegroundColor Yellow
}

# ── Prompt for ECC password ──────────────────────────────────────────────────
Write-Step "Provide CAL ECC password (input hidden)"
# Cheat-sheet (from SAP CAL Getting Started Guide):
#   IDADMIN (on client 800)        -> ides123
#   DDIC / SAP*  (any client)      -> your master password
#   Other IDES users               -> see online IDES documentation
if ($EccUser -eq "IDADMIN") {
    Write-Host "  (For user IDADMIN on client 800, the password is 'ides123')" -ForegroundColor DarkGray
} elseif ($EccUser -eq "DDIC" -or $EccUser -eq "SAP*") {
    Write-Host "  (For DDIC/SAP*, use your CAL master password)" -ForegroundColor DarkGray
}
$secPwd = Read-Host -Prompt "ECC password for user '$EccUser'" -AsSecureString
$bstr   = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secPwd)
$pwd    = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
if (-not $pwd) { Fail "Empty password - refusing to write" }

# ── Update the secret ────────────────────────────────────────────────────────
# Use the kernel-internal hostname (resolved via Route 53 private zone inside
# the VPC) so the SAP gateway's back-verify gets a name it can also resolve.
$ashost = "${CalEccHostname}.dummy.nodomain"
$secretBody = @{
    ashost    = $ashost
    sysnr     = "$EccSysnr".PadLeft(2, '0')
    client    = $EccClient
    user      = $EccUser
    passwd    = $pwd
    lang      = "EN"
    sid       = $EccSid
    public_ip = $CalEccPublicIp
    _note     = "CAL ECC IDES; hostname resolved via Route 53 private zone in VPC; A record points at $CalEccPublicIp"
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
Write-Host ""
Write-Host "REMINDER: did you also run 'terraform apply' with cal_ecc_public_ip=$CalEccPublicIp ?" -ForegroundColor Yellow
Write-Host "  That creates the Route 53 private A record for $ashost."
Write-Host "  Without it, Lambda will fail to resolve the hostname."
Write-Host ""
Write-Host "NEXT STEPS:" -ForegroundColor Yellow
Write-Host "  1. (Optional) Trigger the data-migrator Lambda to test ECC -> S/4 end-to-end:"
Write-Host "       aws lambda invoke --region $Region ``"
Write-Host "           --function-name migrate4hana-data-migrator-$Environment ``"
Write-Host "           --payload file://payload.json ``"
Write-Host "           cal-ecc-test.json"
Write-Host "  2. Inspect output:  Get-Content cal-ecc-test.json | ConvertFrom-Json | ConvertTo-Json -Depth 6"
