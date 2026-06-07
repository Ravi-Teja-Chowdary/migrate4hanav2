# ───────────────────────────────────────────────────────────────────────
# VM-side SAP gateway back-verify forwarder — port range edition
# ───────────────────────────────────────────────────────────────────────
# Run THIS script INSIDE the Windows ECC VM (admin PowerShell). Copy to
# C:\forwarder.ps1 (or run from this path directly).
#
# Why a range?
#   SAP gateway picks the back-verify target port from the LAST TWO DIGITS
#   of the partner's TCP port. With ngrok TCP giving us a random port every
#   restart, those two digits change every session — sapgw00 one day,
#   sapgw92 the next, sapgw47 the day after. Binding the whole 3300–3399
#   range catches whichever number SAP picks.
#
# Companion piece in the VM's hosts file:
#   192.168.100.<VM-IP>   0.tcp.in.ngrok.io
#   192.168.100.<VM-IP>   myecc.hanamasters.com    myecc
# Both names must resolve to the VM's OWN non-loopback IP so SAP's
# back-verify loops back to the VM (where this forwarder catches it on
# whatever sapgwXX it picked) rather than to the laptop.
#
# Forward target stays 127.0.0.1:3341 = the real SAP dispatcher gateway
# (sapgw41 for sysnr 41). Change the $BackendPort if your sysnr differs.
# ───────────────────────────────────────────────────────────────────────

param(
    [int]$StartPort   = 3300,
    [int]$EndPort     = 3399,
    [int]$BackendPort = 3341,
    [string]$BackendHost = "127.0.0.1"
)

$ErrorActionPreference = "Stop"

# Build N TcpListeners up front. Skip any port we can't bind to (the real SAP
# gateway port — typically the BackendPort itself — is in this range and SAP
# already holds it; that's expected, not an error).
$listeners = @()
$skipped   = @()
for ($p = $StartPort; $p -le $EndPort; $p++) {
    if ($p -eq $BackendPort) { $skipped += $p; continue }   # the real SAP gw
    try {
        $l = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Any, $p)
        $l.Start()
        $listeners += $l
    } catch {
        $skipped += $p
    }
}
Write-Host ("Forwarder listening on 0.0.0.0:{0}-{1} (skipped: {2}) -> {3}:{4}" `
    -f $StartPort, $EndPort, ($skipped -join ","), $BackendHost, $BackendPort) -ForegroundColor Green
Write-Host "(Ctrl+C to stop)"

# Bidirectional pump for one accepted connection (sequential — SAP back-verify
# is one connection at a time, and complexity of true multi-threaded async
# isn't worth it for this single-purpose tool)
function Forward-One {
    param($client, $port)
    $remote = $client.Client.RemoteEndPoint
    Write-Host ("$(Get-Date -Format 'HH:mm:ss')  :{0} accept from $remote" -f $port)
    try {
        $backend = New-Object System.Net.Sockets.TcpClient
        $backend.Connect($BackendHost, $BackendPort)
    } catch {
        Write-Host ("  backend connect failed: $($_.Exception.Message)")
        $client.Close(); return
    }
    $cs = $client.GetStream(); $bs = $backend.GetStream()
    $buf = New-Object byte[] 8192
    $sw  = [Diagnostics.Stopwatch]::StartNew()
    try {
        while ($client.Connected -and $backend.Connected -and $sw.Elapsed.TotalSeconds -lt 60) {
            $any = $false
            if ($cs.DataAvailable) {
                $n = $cs.Read($buf, 0, 8192)
                if ($n -gt 0) { $bs.Write($buf, 0, $n); $bs.Flush(); $any = $true }
            }
            if ($bs.DataAvailable) {
                $n = $bs.Read($buf, 0, 8192)
                if ($n -gt 0) { $cs.Write($buf, 0, $n); $cs.Flush(); $any = $true }
            }
            if (-not $any) { Start-Sleep -Milliseconds 5 }
        }
    } finally {
        $client.Close(); $backend.Close()
        Write-Host ("  :{0} closed (elapsed: {1}s)" -f $port, [int]$sw.Elapsed.TotalSeconds)
    }
}

# Main loop: round-robin Pending() check across listeners; accept first one
# that has a pending connection. Sequential service is fine — SAP back-verify
# is rare and brief.
while ($true) {
    $accepted = $false
    foreach ($l in $listeners) {
        if ($l.Pending()) {
            $client = $l.AcceptTcpClient()
            $port = ([System.Net.IPEndPoint]$l.LocalEndpoint).Port
            Forward-One -client $client -port $port
            $accepted = $true
            break
        }
    }
    if (-not $accepted) { Start-Sleep -Milliseconds 20 }
}
