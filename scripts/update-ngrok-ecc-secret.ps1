#requires -Version 5.1
<#
.SYNOPSIS
    Point Lambda's sap-credentials at the laptop ECC via ngrok TCP tunnel.

.DESCRIPTION
    Writes the secret with both ashost AND gwhost/gwserv so pyrfc connects
    to the ngrok edge (random port) rather than deriving the sapgw<NN> port
    from sysnr. Requires the handler's _ecc() to honour gwhost/gwserv.

.PARAMETER NgrokHost
    Public hostname ngrok prints, e.g. '0.tcp.ngrok.io'.

.PARAMETER NgrokPort
    The random TCP port ngrok assigned, e.g. 18429.

.PARAMETER EccSysnr / EccClient / EccUser
    Local ECC details. Sysnr default 41 (matches your laptop ECC Y01/DVEBMGS41).

.PARAMETER Region / Environment
    Defaults: us-east-1 / prod.

.EXAMPLE
    .\scripts\update-ngrok-ecc-secret.ps1 -NgrokHost 0.tcp.ngrok.io -NgrokPort 18429
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$NgrokHost,
    [Parameter(Mandatory = $true)] [int]   $NgrokPort,
    [int]$EccSysnr   = 41,
    [string]$EccClient = "800",
    [string]$EccUser   = "SAPUSER",
    [string]$EccSid    = "Y01",
    [string]$Region    = "us-east-1",
    [string]$Environment = "prod"
)
$ErrorActionPreference = "Stop"
function Write-Step { param([string]$m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Fail { param([string]$m) Write-Host "`nERROR: $m" -ForegroundColor Red; exit 1 }

Write-Step "Sanity-check ngrok edge reachable from laptop"
$probe = Test-NetConnection $NgrokHost -Port $NgrokPort -InformationLevel Quiet
if (-not $probe) {
    Write-Host "  WARNING: cannot reach ${NgrokHost}:${NgrokPort} from laptop — is ngrok still running?" -ForegroundColor Yellow
} else {
    Write-Host "  ngrok edge reachable: OK"
}

Write-Step "Provide ECC password (input hidden)"
$secPwd = Read-Host -Prompt "ECC password for user '$EccUser'" -AsSecureString
$bstr   = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secPwd)
$pwd    = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
if (-not $pwd) { Fail "Empty password — refusing to write" }

# Both ashost and gwhost set to the ngrok edge; gwserv overrides the sysnr-derived port.
$secretBody = @{
    ashost = $NgrokHost
    sysnr  = "$EccSysnr".PadLeft(2, '0')
    client = $EccClient
    user   = $EccUser
    passwd = $pwd
    lang   = "EN"
    sid    = $EccSid
    gwhost = $NgrokHost
    gwserv = "$NgrokPort"
    _note  = "Routed via ngrok TCP tunnel ${NgrokHost}:${NgrokPort} -> laptop ECC; ngrok edge required"
} | ConvertTo-Json -Compress

$secretId = "migrate4hana/$Environment/sap-credentials"
Write-Step "Update Secrets Manager: $secretId"
aws secretsmanager put-secret-value --region $Region `
    --secret-id $secretId --secret-string $secretBody `
    --output text --query "[ARN,VersionId]"
if ($LASTEXITCODE -ne 0) { Fail "Secrets Manager update failed" }

Write-Host "`n  Secret updated. Lambda picks up on next cold-start (~minutes) or you can force a fresh fetch by redeploying."
Write-Host "  NGROK MUST STAY RUNNING for Lambda to reach ECC." -ForegroundColor Yellow
