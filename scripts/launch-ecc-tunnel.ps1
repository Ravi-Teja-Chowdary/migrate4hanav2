#requires -Version 5.1
<#
.SYNOPSIS
    Open a reverse SSH tunnel so AWS Lambdas can reach the laptop's local ECC.

.DESCRIPTION
    The Migrate4HANA Lambdas live in an AWS VPC. They cannot reach the user's
    laptop ECC (192.168.100.x host-only VMnet) directly. This script opens a
    reverse SSH tunnel from the laptop to the AWS-side bastion:

        laptop  --ssh-->  bastion (in migrate4hana VPC)
                    └── back-channel: bastion:3341 forwards to laptop:3341 -> ECC

    Once running, any AWS Lambda calling pyrfc.Connection(ashost="<bastion-private-ip>",
    sysnr="41", ...) actually reaches the laptop's ECC at 192.168.100.129:3341.

.PARAMETER EccHost
    The local ECC IP as seen from the laptop. Default 192.168.100.129
    (host-only VMnet adapter per [[connectivity-quirks]] memory).

.PARAMETER EccSysnr
    SAP system number; the gateway port is 33<sysnr> (e.g. sysnr=41 -> port 3341).

.PARAMETER SshKeyPath
    Path to the .pem private key for the AWS key pair attached to the bastion
    (default key pair name 'migrate4hana-key', see terraform variable
    bastion_key_pair_name).

.PARAMETER Region / Environment
    AWS region + terraform environment (default us-east-1 / prod).

.PARAMETER Persistent
    If set, the tunnel auto-reconnects when it drops. Otherwise the script
    exits on the first disconnect.

.EXAMPLE
    .\scripts\launch-ecc-tunnel.ps1 -SshKeyPath .\migrate4hana-key.pem -Persistent
    # The standard demo invocation. Keeps the tunnel up until Ctrl-C.
#>
[CmdletBinding()]
param(
    [string]$EccHost = "192.168.100.148",
    [int]$EccSysnr = 41,
    [Parameter(Mandatory=$true)]
    [string]$SshKeyPath,
    [string]$Region = "us-east-1",
    [string]$Environment = "prod",
    [switch]$Persistent
)

$ErrorActionPreference = "Stop"

function Write-Step { param([string]$m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Fail { param([string]$m) Write-Host "`nERROR: $m" -ForegroundColor Red; exit 1 }

# ── Pre-flight ────────────────────────────────────────────────────────────────
Write-Step "Pre-flight checks"

if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    Fail "ssh client not found. On Windows 10/11 install OpenSSH client via Settings -> Apps -> Optional features -> OpenSSH Client."
}
if (-not (Test-Path $SshKeyPath)) { Fail "SSH key not found at $SshKeyPath" }
if (-not (Get-Command aws -ErrorAction SilentlyContinue)) { Fail "aws CLI not found" }

# Check ECC is actually reachable locally before we bother with the tunnel
$eccPort = 3300 + $EccSysnr
Write-Host "  Probing local ECC at ${EccHost}:${eccPort} ..."
$probe = Test-NetConnection $EccHost -Port $eccPort -InformationLevel Quiet
if (-not $probe) {
    Fail "Cannot reach ECC at ${EccHost}:${eccPort}. Is the VM running and SAP started? See [[connectivity-quirks]] in HOW-TO-RUN.md"
}
Write-Host "  Local ECC reachable: OK"

# ── Resolve bastion public IP from terraform output ───────────────────────────
Write-Step "Resolve bastion public IP from terraform output"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoRoot  = Resolve-Path (Join-Path $scriptDir "..")
$tfDir     = Join-Path $repoRoot "terraform\environments\$Environment"

if (-not (Test-Path $tfDir)) { Fail "terraform env dir not found: $tfDir" }
Push-Location $tfDir
try {
    $bastionPublic  = (terraform output -raw bastion_public_ip 2>$null).Trim()
    $bastionPrivate = (terraform output -raw bastion_private_ip 2>$null).Trim()
} finally {
    Pop-Location
}

if (-not $bastionPublic) {
    Fail @"
Bastion is not provisioned. To provision it:
  1. Confirm your AWS key pair exists (default name 'migrate4hana-key'):
       aws ec2 describe-key-pairs --key-names migrate4hana-key --region us-east-1
  2. (Optional) Override the key pair name in terraform/environments/prod/terraform.tfvars:
       bastion_key_pair_name = "your-key-name"
  3. Re-apply terraform: cd terraform\environments\prod ; terraform apply -auto-approve
  4. Re-run this script with -SshKeyPath pointing at your .pem file.
"@
}

Write-Host "  Bastion public IP:  $bastionPublic"
Write-Host "  Bastion private IP: $bastionPrivate (use this in connections.json / Secrets Manager)"

# ── Open the tunnel ───────────────────────────────────────────────────────────
Write-Step "Open reverse SSH tunnel (Ctrl-C to stop)"
Write-Host "  Tunnel: bastion (0.0.0.0:${eccPort}) -> laptop (${EccHost}:${eccPort}) -> ECC"
Write-Host "  Test from laptop: nc -v ${bastionPublic} ${eccPort}  # should accept TCP"
Write-Host "  From inside a Lambda: pyrfc.Connection(ashost='$bastionPrivate', sysnr='$EccSysnr', ...)"
Write-Host ""

$sshArgs = @(
    "-i",  $SshKeyPath,
    "-o",  "StrictHostKeyChecking=accept-new",
    "-o",  "ServerAliveInterval=30",
    "-o",  "ServerAliveCountMax=3",
    "-o",  "ExitOnForwardFailure=yes",
    "-N",
    "-R",  "0.0.0.0:${eccPort}:${EccHost}:${eccPort}",
    "ec2-user@$bastionPublic"
)

while ($true) {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] starting ssh -R ..." -ForegroundColor Yellow
    & ssh @sshArgs
    $exit = $LASTEXITCODE
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] ssh exited with code $exit" -ForegroundColor Yellow
    if (-not $Persistent) {
        if ($exit -ne 0) { Fail "ssh failed; re-run with -Persistent to auto-reconnect" }
        Write-Host "  (Tunnel ended cleanly.)"
        break
    }
    Write-Host "  -Persistent set; reconnecting in 5 seconds ..." -ForegroundColor Yellow
    Start-Sleep -Seconds 5
}
