# Connecting AWS-Deployed Migrate4HANA to a Local Windows ECC

> **This is the canonical, working runbook (validated 2026-06-02 with a 19,575-row
> Customer extract from a local IDES EHP8 ECC).**
> The previous approaches in `ECC_TUNNEL_HOWTO.md` (bastion + reverse SSH) and
> `CAL_ECC_HOWTO.md` (SAP CAL IDES) are superseded by this one.

This runbook explains how to make a Lambda running in AWS reach a SAP ECC system
running inside a VMware/host-only VM on a developer laptop. It's intended for
dev/proof use — for real customer engagements, replace ngrok with a proper
SAProuter or VPN.

---

## 1. Architecture

```
┌────────────────────┐                              ┌────────────────────┐
│  AWS account       │                              │  Developer laptop  │
│                    │                              │                    │
│  ┌─────────────┐   │                              │  ┌──────────────┐  │
│  │  Lambda     │───┼─── HTTPS / TCP via NAT ──────┼──│  ngrok edge  │  │
│  │ data-migrator   │                              │  │ (0.tcp.in.   │  │
│  └─────────────┘   │                              │  │  ngrok.io)   │  │
│        │           │                              │  └──────┬───────┘  │
│        │ resolves  │                              │         │ tunnel   │
│        ▼           │                              │         ▼          │
│  Route 53          │                              │  ┌──────────────┐  │
│  private zone      │                              │  │ ngrok agent  │  │
│  vhcalabaci.       │                              │  │ on laptop    │  │
│  dummy.nodomain    │                              │  └──────┬───────┘  │
│                    │                              │         │ host-    │
│  Secret:           │                              │         │ only net │
│  sap-credentials   │                              │         ▼          │
│                    │                              │  ┌──────────────┐  │
└────────────────────┘                              │  │  Windows VM  │  │
                                                    │  │  192.168.    │  │
                                                    │  │  100.144     │  │
                                                    │  │              │  │
                                                    │  │  SAP IDES    │  │
                                                    │  │  Y01 / 41    │  │
                                                    │  │              │  │
                                                    │  │  Python      │  │
                                                    │  │  forwarder   │  │
                                                    │  │  :3300 -> :3341  │
                                                    │  │  (loops back │  │
                                                    │  │  to SAP for  │  │
                                                    │  │  back-verify)│  │
                                                    │  └──────────────┘  │
                                                    └────────────────────┘
```

**Why every piece exists** (each one solves an issue we hit):

| Component | Why |
|---|---|
| **ngrok TCP tunnel** | Lambda has no network path to the laptop; ngrok punches a public TCP forwarder through. |
| **`gwhost` / `gwserv` on pyrfc** | ngrok assigns a random external port; pyrfc derives the SAP gateway port from `sysnr`. We override with `gwhost`/`gwserv` so pyrfc connects to ngrok's port instead of `33<sysnr>`. |
| **Hosts entry: `192.168.100.10 0.tcp.in.ngrok.io`** (inside VM) | SAP gateway does `NiHLGetNodeAddr` on the ashost it receives. The VM has no internet → external DNS fails. The hosts entry makes the lookup succeed. |
| **Hosts entry: `192.168.100.144 myecc.hanamasters.com`** (inside VM) | SAP refuses to start if its own hostname resolves to `127.0.0.1` (SAP Note 1054467 — DP_FATAL_ERROR). Must point at a real non-loopback address. |
| **Python TCP forwarder on VM `:3300 -> :3341`** | SAP gateway *back-verifies* by connecting to its own `myecc.hanamasters.com:sapgw00` (port 3300). That maps via hosts to the VM's own IP. We forward `:3300` → `:3341` (the real gateway) so the back-verify succeeds. (Windows Server 2008 R2 `netsh portproxy` is broken on loopback — Python is required.) |
| **Route 53 private zone** | Just hygiene — the secret can use a hostname instead of a raw ngrok address. |

---

## 2. Prerequisites

### AWS side
- Migrate4HANA deployed (`terraform apply` from `terraform/environments/prod/`)
- Lambda layer with `pyrfc` + SAP NW RFC SDK already attached
- `migrate4hana/prod/sap-credentials` secret exists (created by an earlier secret-update script — even with placeholder values)
- AWS CLI v2 installed on laptop
- AWS CLI configured: `aws configure set cli_binary_format raw-in-base64-out` (one-time, prevents `Lambda invoke` payload encoding issues)

### Local side
- Windows laptop with a VMware/VirtualBox VM running Windows Server 2008 R2 + SAP ECC IDES (or equivalent)
- SAP is **already started** (`sapcontrol -nr 41 -function GetProcessList` shows GREEN inside the VM)
- VM is reachable from laptop on the host-only network: `Test-NetConnection 192.168.100.144 -Port 3341` returns `True`
- ngrok account (free tier is fine): https://dashboard.ngrok.com — grab your authtoken
- ngrok agent installed on laptop, version ≥ 3.20.0: `winget install ngrok.ngrok` then `ngrok update` if needed

---

## 3. One-time setup

### 3.1 Inside the Windows VM — edit hosts file

Open `C:\Windows\System32\drivers\etc\hosts` (Notepad **as Administrator**) and ensure it contains these two lines:

```
192.168.100.144   myecc.hanamasters.com    myecc
192.168.100.10    0.tcp.in.ngrok.io
```

**Critical:** the `myecc.hanamasters.com` line MUST point at the VM's own non-loopback IP. **Never use `127.0.0.1`** — SAP refuses to start with hostname → loopback (`DP_FATAL_ERROR DpMsAttach`, SAP Note 1054467).

The second IP is your laptop's host-only-network IP; adjust if yours differs.

### 3.2 Inside the Windows VM — install the Python TCP forwarder

Save the following as `C:\forwarder.ps1`:

```powershell
$listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Any, 3300)
$listener.Start()
Write-Host "Forwarder listening on 0.0.0.0:3300 -> 127.0.0.1:3341"

while ($true) {
    $client = $listener.AcceptTcpClient()
    $remote = $client.Client.RemoteEndPoint
    Write-Host "$(Get-Date -Format 'HH:mm:ss')  Accepted from $remote"

    try {
        $backend = New-Object System.Net.Sockets.TcpClient
        $backend.Connect('127.0.0.1', 3341)
    } catch {
        Write-Host "  Backend connect to :3341 FAILED: $($_.Exception.Message)"
        $client.Close(); continue
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
        Write-Host "  Closed $remote (elapsed: $([int]$sw.Elapsed.TotalSeconds)s)"
    }
}
```

> **Why Python-style PowerShell instead of `netsh portproxy`?**
> On Windows Server 2008 R2, `netsh interface portproxy` registers the rule but
> never actually binds (silent failure). This PowerShell forwarder is the
> reliable workaround. If `netsh portproxy` works on your Windows version, you
> can use it instead.

### 3.3 SAP profile parameters (one-time)

Inside the VM, edit `D:\usr\sap\Y01\SYS\profile\Y01_DVEBMGS41_myecc` (path varies — replace `Y01` and `41` with your SID/sysnr) and ensure these lines appear **once each** (remove any duplicates — duplicates print a warning but the second value wins):

```
gw/sim_mode               = 1
gw/reject_invalid_connect = 0
gw/acl_mode               = 0
gw/reg_no_conn_info       = 1
```

Restart SAP for the changes to take effect:

```cmd
stopsap r3
startsap r3
```

> These params don't single-handedly fix back-verify (we still need the port-forwarder loop), but they ensure the gateway is permissive on ACL and partner-info checks.

### 3.4 Lambda handler (one-time patch)

The data-migrator handler needs to honor `gwhost` / `gwserv` from the secret so it can connect through ngrok's random port. Confirm this code is in `lambda/data-migrator/handler.py` (it was added 2026-06-02):

```python
def _ecc(secret_id: str):
    sec = json.loads(SECRETS.get_secret_value(SecretId=secret_id)["SecretString"])
    from pyrfc import Connection
    kwargs = {
        "ashost": sec["ashost"],
        "sysnr":  sec.get("sysnr", "00"),
        "client": sec["client"],
        "user":   sec["user"],
        "passwd": sec.get("passwd") or sec.get("password"),
        "lang":   sec.get("lang", "EN"),
    }
    for opt in ("gwhost", "gwserv", "saprouter"):
        if sec.get(opt):
            kwargs[opt] = sec[opt]
    return Connection(**kwargs)
```

Push if you haven't already:

```powershell
Compress-Archive -Path lambda\data-migrator\* -DestinationPath data-migrator.zip -Force
aws lambda update-function-code `
    --region us-east-1 `
    --function-name migrate4hana-data-migrator-prod `
    --zip-file fileb://data-migrator.zip
```

### 3.5 ngrok authentication (one-time)

```powershell
ngrok config add-authtoken <YOUR_AUTHTOKEN>
ngrok version  # must be >= 3.20.0
```

---

## 4. Per-session startup (every time you want to test)

You'll have **three windows running at once**: one ngrok, one VM-side forwarder, and one laptop-side PowerShell for invoking Lambda.

### Step 1 — Make sure local ECC is up

From laptop PowerShell:

```powershell
Test-NetConnection 192.168.100.144 -Port 3341 -InformationLevel Quiet
```

Must return `True`. If `False`:
- Boot the VM if not running
- Inside the VM: `startsap r3`, wait ~2 minutes
- Recheck

### Step 2 — Start ngrok (laptop window 1)

```powershell
ngrok tcp 192.168.100.144:3341
```

Note the forwarding line:
```
Forwarding   tcp://0.tcp.in.ngrok.io:18429 -> 192.168.100.144:3341
```

The host (`0.tcp.in.ngrok.io`) and port (`18429`) change on every ngrok restart. Write them down. **Leave this window open.**

### Step 3 — Start the Python forwarder (VM window)

Open a PowerShell **as Administrator** inside the VM and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
C:\forwarder.ps1
```

You should see:
```
Forwarder listening on 0.0.0.0:3300 -> 127.0.0.1:3341
```

**Leave this window open** too.

### Step 4 — Update the AWS secret with the current ngrok address (laptop window 2)

```powershell
.\scripts\update-ngrok-ecc-secret.ps1 -NgrokHost 0.tcp.in.ngrok.io -NgrokPort 18429
# password prompt: enter your local ECC user password (typically for sapuser / DDIC / etc.)
# If your local user/client differs, add: -EccUser DDIC -EccClient 000
```

### Step 5 — Smoke test from laptop window 2

```powershell
$payload = @{
    run_id         = "ngrok-smoke-001"
    ecc_secret_id  = "migrate4hana/prod/sap-credentials"
    object_spec    = @{
        object       = "Customer"
        source_table = "KNA1"
        fields       = @("KUNNR","NAME1","LAND1","ORT01","STRAS")
        lane         = "MC"
    }
} | ConvertTo-Json -Depth 4 -Compress
$payload | Out-File -Encoding ASCII payload.json

aws lambda invoke `
    --region us-east-1 `
    --function-name migrate4hana-data-migrator-prod `
    --cli-binary-format raw-in-base64-out `
    --payload file://payload.json `
    ngrok-smoke.json

Get-Content ngrok-smoke.json | ConvertFrom-Json | ConvertTo-Json -Depth 6
```

**Expected — success:**
```json
{
  "run_id": "ngrok-smoke-001",
  "status": "ok",
  "object": "Customer",
  "lane": "MC",
  "row_count": 19575,
  "artifacts": {
    "mc_csv": "s3://migrate4hana-staging-prod/runs/ngrok-smoke-001/data-migrator/mc/Customer.csv"
  }
}
```

Watch the **forwarder window in the VM** — you'll see `Accepted from 127.0.0.1:XXXXX` lines each time SAP does its back-verify. That's the visual proof.

You can also watch live tunnel traffic in your browser at **http://127.0.0.1:4040** (ngrok's web inspector).

---

## 5. Drift handling — what changes between sessions

ngrok free tier gives you a **random port every time you restart**. So on every new session:

1. Note the new port from the ngrok window (Step 2)
2. Re-run `update-ngrok-ecc-secret.ps1 -NgrokPort <new-port>` (Step 4)
3. That's it — no Lambda redeploy, no other changes

The Lambda picks up the new secret value on its next cold start (or in any case within ~1 invocation).

To avoid the port drift entirely, you can pay for ngrok Personal ($8/mo) which gives you reserved TCP addresses with fixed ports.

---

## 6. Troubleshooting — symptoms we hit and what fixed them

### `RFC_COMMUNICATION_FAILURE: partner '<ngrok host>' unknown` (during smoke test)

The VM can't resolve the ngrok hostname. Cause: the hosts entry `192.168.100.10 0.tcp.in.ngrok.io` is missing inside the VM. Add it (3.1).

### `RFC_COMMUNICATION_FAILURE: partner 'myecc.hanamasters.com:sapgw00' not reached`

SAP gateway is back-verifying and the connection is refused. Causes (in order of likelihood):

- The **Python forwarder isn't running** inside the VM. Start it (3.2).
- The forwarder is running but `netstat -ano | findstr ":3300"` shows nothing — the forwarder script crashed. Re-run it.
- The hosts entry for `myecc.hanamasters.com` is missing or wrong. Must be `192.168.100.144` (VM's own IP), not `127.0.0.1`, not the laptop IP.

### SAP refuses to start: `DP_FATAL_ERROR => DpMsAttach: local hostname '<x>' is resolved to loopback address`

You pointed `myecc.hanamasters.com` at `127.0.0.1` in the VM hosts file. Change it to the VM's own non-loopback IP (typically `192.168.100.144`). Restart SAP.

### Lambda returns `Could not parse payload into json: Unexpected character ((CTRL-CHAR, code 153))`

AWS CLI v2 default. Add `--cli-binary-format raw-in-base64-out` to your `aws lambda invoke` command, or set it once globally: `aws configure set cli_binary_format raw-in-base64-out`.

### Lambda returns `No module named 'logger'` or similar

Your deployment zip is missing the `lambda/utils/` content. Bundle it at the deployment root (alongside `handler.py`). For the data-migrator the wrapped `try/except` makes this silent (logger becomes a no-op); other Lambdas (e.g. orchestrator) fail hard. See `deploy-orchestrator.ps1` for the pattern.

### Lambda returns `AccessDeniedException ... secretsmanager:GetSecretValue`

The Lambda's IAM role doesn't allow reading that secret. Add an inline policy. For the S/4 secret, `scripts/grant-s4-secret-read.ps1` already does this.

### `Get-Content payload.json` shows JSON with leading whitespace on continuation lines

PowerShell wrapped the long line during paste and interpreted wraps as literal newlines. **Don't paste long JSON into PowerShell directly** — build payload.json from PowerShell hashtables using `ConvertTo-Json -Compress` (see `invoke-orchestrator.ps1` for the safe pattern).

### `netsh interface portproxy show all` shows the rule but `netstat` doesn't show it listening

Windows Server 2008 R2 portproxy is unreliable on loopback. Use the Python TCP forwarder script (3.2) instead.

---

## 7. Shutdown / cleanup

After a session:

```powershell
# 1. Stop the smoke-test artifacts (optional, just for tidiness)
Remove-Item .\payload.json, .\ngrok-smoke.json -ErrorAction SilentlyContinue

# 2. Close the ngrok window (Ctrl+C in it)
# 3. Close the VM-side forwarder window (Ctrl+C in it)
# 4. (Optional) Shut down the VM if you won't use it again today
```

The AWS secret will still hold the now-dead ngrok address; that's harmless until the next session, when you'll re-run `update-ngrok-ecc-secret.ps1`.

---

## 8. When to graduate away from ngrok

ngrok is for dev and proof. **Do not use it for a real customer engagement** or a production demo. For real:

- **Real customer with existing ECC**: SAProuter from their network to a Migrate4HANA SAProuter in the VPC, plus IPsec/Direct Connect for the database path. Days–weeks of planning, but it's how SNP and SAP themselves do it.
- **Cloud-hosted customer ECC**: peer the VPCs, open security groups for the relevant ports, skip ngrok entirely.
- **POC where customer wants minimal change**: Migrate4HANA Lambda + VPN to a small "jump" VPC + the customer's existing VPN endpoint. Slower than ngrok but enterprise-defensible.

ngrok's role is to keep dev iteration fast. Once you have a paying customer, replace it.

---

## 9. Reference — scripts and files this runbook touches

| File | Purpose |
|---|---|
| `lambda/data-migrator/handler.py` | Has the `_ecc()` function with `gwhost`/`gwserv` support |
| `scripts/update-ngrok-ecc-secret.ps1` | Updates `sap-credentials` with current ngrok host:port |
| `C:\forwarder.ps1` (inside VM) | Python-style PowerShell TCP forwarder for back-verify loopback |
| `C:\Windows\System32\drivers\etc\hosts` (inside VM) | Hostname mappings for SAP + ngrok |
| `D:\usr\sap\Y01\SYS\profile\Y01_DVEBMGS41_myecc` (inside VM) | SAP profile with permissive `gw/*` params |
| `terraform/environments/prod/main.tf` | Route 53 private zone (optional, just hygiene) |

---

## 10. Validation log — what worked, when

| Date | Result | Notes |
|---|---|---|
| 2026-06-02 | ✓ 19,575 Customer rows from KNA1 via Lambda → ngrok → IDES → S3 CSV | First end-to-end success after ~6 hours of debugging back-verify quirks |
