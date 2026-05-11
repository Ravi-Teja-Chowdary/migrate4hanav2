# Migrate4HANA — Lift-and-Shift Setup
## Your scenario: laptop ECC (Ameerpet) → SAP S/4HANA on AWS (SAP CAL trial)

This is the setup guide for the **greenfield / lift-and-shift** path on this branch (`aws-lift-and-shift`).
It assumes:

- **Source:** SAP ECC running on your local laptop (the Ameerpet install). Default values used below:
  `ashost=192.168.0.6, sysnr=41, client=800, user=sapuser`.
- **Target:** A brand-new SAP S/4HANA deployed in **your own AWS account** via the
  **SAP Cloud Appliance Library (CAL)** 30-day free trial.
- **Orchestrator:** Migrate4HANA running on your laptop (or on a small EC2 — either works).

The runbook (the actual phase-by-phase execution) lives in `LIFT-AND-SHIFT-RUNBOOK.md`.
This file only covers **one-time setup** — you do this once, then never again.

> **Why "greenfield" and not "brownfield"?** This branch never writes to S/4 directly. Every change
> on S/4 happens through a SAP-shipped tool (Migration Cockpit, LTMOM, IDoc inbound, CTS+/abapGit).
> That keeps your SAP support clean even though you don't have an S-user — the SAP CAL appliance
> itself is licensed to SAP CAL terms, and every artifact (transports, MC templates, IDoc XML) is
> reproducible by a SAP Basis admin without Migrate4HANA. See `MIGRATE4HANA-LIFT-AND-SHIFT.md` for
> the Two-Plane Principle.

---

## 0. The end-state you are building

```
┌─────────────────────┐                           ┌──────────────────────────────────┐
│  YOUR LAPTOP        │                           │  YOUR AWS ACCOUNT                │
│  ───────────────    │                           │  ──────────────────              │
│  • SAP ECC          │   Tailscale mesh (or      │  • Tailscale subnet-router       │
│    192.168.0.6      │◄──Site-to-Site VPN)──────►│    EC2 t4g.nano  ($3/mo)         │
│    sysnr 41         │                           │                                  │
│    client 800       │                           │  • S/4HANA 2023 (SAP CAL)        │
│  • Migrate4HANA     │                           │    EC2 (CAL provisions for you)  │
│    (api_server.py)  │                           │    Pre-configured: MC, LTMOM,    │
│  • saplogon (GUI)   │                           │    CTS+, IDoc inbound, STMS      │
└─────────────────────┘                           │                                  │
                                                  │  • S3 bucket (staging artifacts) │
                                                  │  • Secrets Manager (passwords)   │
                                                  └──────────────────────────────────┘
```

You do NOT need Step Functions / Terraform deployed to get a first end-to-end run.
The local runner (`python run_local_lift_and_shift.py`) invokes every Lambda **in-process**
and uses only the things you have logged into — no AWS API Gateway, no Lambda deploys.
The AWS resources you DO need are: the CAL-deployed S/4 EC2, the Tailscale subnet-router EC2,
and an S3 bucket for staging artifacts.

---

## 1. AWS account prep (~15 min, ~$3/month ongoing)

> **Audit note (after deep code review):** the lift-and-shift runner now auto-activates
> `local_aws_shim` which emulates AWS Secrets Manager, S3, DynamoDB, SSM, etc. against
> your local filesystem. **You can complete the full 28-stage migration without ever
> creating an S3 bucket, IAM user, or DynamoDB table.** The only AWS resources you truly
> need are: (a) the EC2 instance(s) that SAP CAL provisions for S/4HANA, and (b) the
> Tailscale t4g.nano EC2 for the network bridge. Sections 1.3 (S3) is **optional** —
> skip it for the first test run. The remaining AWS resource you need is just compute.

### 1.1. Sign up / log in to AWS
You need an AWS account with the ability to create EC2 instances and S3 buckets.
The free tier is enough for the orchestration plane; SAP CAL S/4 itself runs ~$5–10/hr
while powered on (≈$50–200/day depending on shape) — **you stop it when not migrating**.

### 1.2. Pick a region
Pick a region close to you and supported by SAP CAL. **`ap-south-1` (Mumbai)** is the
closest one for India. We'll use that throughout this doc.

```powershell
# On your laptop, after `aws configure`:
aws configure set default.region ap-south-1
```

### 1.3. Create one S3 bucket for Migrate4HANA staging
```powershell
$bucket = "m4h-staging-$((Get-Random -Maximum 999999))"
aws s3 mb "s3://$bucket" --region ap-south-1
$env:M4H_STAGING_BUCKET = $bucket
[Environment]::SetEnvironmentVariable("M4H_STAGING_BUCKET", $bucket, "User")
```

### 1.4. Decide network bridge (laptop ECC ↔ AWS VPC)

The CAL-deployed S/4 will be in an AWS VPC. The laptop ECC at 192.168.0.6 is on your
home/office LAN. They need to talk during transport import, IDoc test posts, and
delta-extract. Choose **one** of:

| Option | Cost | Effort | Recommended for |
|---|---|---|---|
| **Tailscale subnet-router on t4g.nano** | ~$3/mo | 30 min | ⭐ You (easiest) |
| AWS Site-to-Site VPN | ~$36/mo | 2–4 hr | Production-style POC |
| SAProuter both ends | $0 | 4–6 hr | SAP purists |
| Clone ECC to EC2 (skip the bridge) | ~$50/mo | 1 day | If laptop is unreliable |

**We'll use Tailscale.** It's the only one a non-network engineer can finish in an evening.

#### Tailscale bridge setup (do this once, takes 30 min)

1. Create a free Tailscale account at https://login.tailscale.com (Google/MS login is fine).
2. On your **laptop**: install Tailscale, sign in. Your laptop is now node `laptop-ecc` on
   your tailnet. Note its tailnet IP (looks like `100.x.y.z`).
3. Launch a **t4g.nano** Ubuntu 22.04 EC2 in your AWS VPC, public subnet, with a public IP:
   ```powershell
   aws ec2 run-instances --image-id resolve:ssm:/aws/service/canonical/ubuntu/server/22.04/stable/current/arm64/hvm/ebs-gp2/ami-id `
     --instance-type t4g.nano --key-name <your-key> `
     --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=m4h-tailscale-router}]'
   ```
4. SSH in, install Tailscale, advertise routes for *the CAL VPC CIDR* so the laptop can
   reach the S/4 EC2 by its private IP:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up --advertise-routes=10.0.0.0/16 --accept-dns=false
   # On the laptop, also accept the route:
   tailscale up --accept-routes
   ```
   Approve the advertised route in the Tailscale admin console (Machines → … → Edit route
   settings → tick the CIDR).
5. **Reverse direction** (so the AWS-side S/4 can call back to the laptop ECC for the
   delta-extract reconciliation lane): install Tailscale on the S/4 EC2 after SAP CAL
   provisions it (step 2 below). Or simply rely on the laptop pulling — that's how
   Migrate4HANA actually works (orchestrator pulls from ECC, pushes to S/4).
   In practice you only need: laptop → S/4. So step 4 is sufficient.

**Test:** from the laptop, `ping <s4-private-ip>` should work once the S/4 is up.

---

## 2. Deploy S/4HANA via SAP CAL trial (~2 hr, mostly waiting)

### 2.1. Sign up for SAP CAL
- Go to https://cal.sap.com
- Click **Try for free** → register with email (no S-user needed)
- Verify email; you get 30 days free

### 2.2. Pick the right appliance
In CAL → **Solutions**, search for one of:

| Appliance | Why pick it |
|---|---|
| **SAP S/4HANA 2023 FPS01, Fully-Activated Appliance** | ⭐ Default. Pre-loaded org data, MC + LTMOM + CTS+ all enabled. ~$8/hr while running. |
| SAP S/4HANA 2022 FPS02, Fully-Activated Appliance | If you want to match older release |

Click **Create Appliance**.

### 2.3. Configuration during CAL provisioning
CAL will ask:

- **Account / Region:** pick the AWS account + region you set up in §1.2 (Mumbai).
- **Instance size:** the appliance defaults are fine (m5.4xlarge or m5.8xlarge). Smaller = cheaper but slower.
- **Master password:** pick one you'll remember. This becomes the password for `DDIC`,
  `SAP*`, `BPINST`, `S4ADMIN`, OS users `s4hadm`, `sapadm`, root.
- **Time-zone / network:** accept defaults.

Click **Create**. **Wait ~60–90 min.** CAL boots EC2 instances, installs HANA, ABAP stack,
runs activation jobs. Do not refresh the page constantly; check after an hour.

When status = "Active", click the appliance:
- **Connect** tab → note:
  - `<S/4 private IP>` (inside the VPC) — this is your `target_ashost`
  - URLs for Fiori launchpad, HANA studio
  - Pre-configured users / passwords (mostly your master password)
- **Default values for Migrate4HANA target connection:**
  - `target_ashost = <private IP from CAL>`
  - `target_sysnr = 00`
  - `target_client = 100`  *(fully-activated appliance default; could also be 001/200 — check the Connect tab)*
  - `target_user = DDIC`  *(read-only for Migrate4HANA; we never write)*
  - `target_passwd = <your master password>`

### 2.4. Verify reachability from your laptop
```powershell
Test-NetConnection <S/4 private IP> -Port 3300   # RFC gateway
Test-NetConnection <S/4 private IP> -Port 8000   # ICM HTTP (for MC OData + IDoc)
Test-NetConnection <S/4 private IP> -Port 44300  # ICM HTTPS
```
All three should succeed via Tailscale.

### 2.5. Stop the appliance when not migrating
**This is critical for cost.** From the CAL Web UI: click **Suspend**. EC2 is stopped,
EBS still incurs storage (~$0.10/GB/mo, total ~$5/day storage). Resume in ~10 min when
you're ready to run another phase.

---

## 3. Prep your laptop ECC (the source side) (~30 min)

Most of this is verifying things, not changing them.

### 3.1. Confirm ECC is up
- SAP GUI logon to `192.168.0.6 / 41 / 800 / sapuser`. You should already have done
  this for the brownfield runs.

### 3.2. Create a read-only RFC user for Migrate4HANA
SAP GUI → **SU01** → create user `M4H_RFC`:
- User type: **System** (B) — service account, no dialog
- Password: pick a strong one; store in `M4H_ECC_PASSWD` env var locally
- Roles tab: assign `SAP_BC_RFC_READ_ONLY` plus `S_TABU_DIS` for `SAP*` tables.
- (If you don't want to create a role, you can reuse `sapuser` — but a dedicated user
  makes audit easier.)

### 3.3. Allow RFC from the laptop's own IP (no firewall change for localhost)
Migrate4HANA runs **on the same laptop** as ECC, so it talks 127.0.0.1-style. Nothing
to open. If you instead run Migrate4HANA from EC2, you need to expose `33xx` over
Tailscale to the EC2 — but for the simplest setup, keep both on the laptop.

### 3.4. Confirm trans directory exists
SAP GUI → **AL11** → `DIR_TRANS` → confirm `/usr/sap/trans/` is populated. Migrate4HANA
will write transport cofiles + data files here during Phase 2 (CODE) and Phase 3 (CONFIG).

---

## 4. Install Migrate4HANA on your laptop (~20 min)

You're already on the right branch (`aws-lift-and-shift`).

### 4.1. Python + Node prerequisites
```powershell
python --version   # need 3.11+
node --version     # need 18+
```

### 4.2. Python deps
```powershell
cd C:\Users\ajays\Downloads\migrate4hanav2
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 4.3. pyrfc (the RFC SDK Python binding)
**Good news: the SDK is already in this repo.** Both Windows DLLs and Linux `.so` files
are bundled under `sapnwrfc/lib/` (verified — `sapnwrfc.dll` 7 MB + `libsapnwrfc.so`
8.9 MB + ICU + headers, full SAP NW RFC SDK 7.50). You do **not** need to download
anything from SAP Service Marketplace.

The `sapnwrfc/__init__.py` loader auto-configures `SAPNWRFC_HOME` and prepends the SDK
to `PATH` / `LD_LIBRARY_PATH` on import, so all you need is:

```powershell
# Tell pyrfc where the bundled SDK is:
$env:SAPNWRFC_HOME = "C:\Users\ajays\Downloads\migrate4hanav2\sapnwrfc"
[Environment]::SetEnvironmentVariable("SAPNWRFC_HOME", $env:SAPNWRFC_HOME, "User")
pip install pyrfc
```

If `pip install pyrfc` fails to build (it requires a C++ compiler and matching Python
version), fall back to the community wheel which doesn't need a compiler:
```powershell
pip install pynwrfc
```

> **Audit note:** the bundle is mis-laid-out for the *Linux* side — all the `.so` files
> are in `sapnwrfc/lib/` instead of `nwrfcsdk-linux/lib/` where the `__init__.py` expects
> them. **This only affects building an AWS Lambda layer**, not your local Windows run.
> For local laptop runs it works as-is.

### 4.4. Frontend (optional, only if you want the UI)
```powershell
cd frontend
npm install
npm run build
cd ..
```

### 4.5. Sanity check
```powershell
python run_local_lift_and_shift.py --list-stages
```
You should see all 28 stages printed **and a `[local-shim] active. staging=…` banner**.
The runner auto-activates `local_aws_shim` (no AWS account required for stages 3, 4, 11,
etc. that don't directly read SAP — they will route through the shim and write artifacts
to `./local-staging/`).

### 4.5b. AWS-less smoke (no pyrfc needed)
Two stages have no SAP dependency and prove the shim works end-to-end:
```powershell
$env:M4H_TARGET_MODE = "basis_handover_only"
python run_local_lift_and_shift.py --only stage3 --run-id smoke-001
python run_local_lift_and_shift.py --only stage4 --run-id smoke-001
```
Expected: both print `status=success`. Inspect:
```
local-staging\m4h-local\runs\smoke-001\target-provisioner\manifest.json
```

### 4.6. Environment variables
The runner auto-sets `M4H_LOCAL_MODE=1` so you don't need to manage AWS Secrets Manager,
S3 buckets, or DynamoDB tables for a local test run. All of those are emulated by
`local_aws_shim.py` against `./local-staging/` on your filesystem and against
`connections.json` (for credentials).

You still need to set the SAP passwords (the shim reads them from env vars, not from disk):
```powershell
$env:M4H_ECC_PASSWD     = "<password for M4H_RFC user on the laptop ECC>"
$env:M4H_TARGET_PASSWD  = "<your SAP CAL master password>"
$env:M4H_TARGET_MODE    = "basis_handover_only"     # tells stage 4 the CAL provisioned the S/4
$env:SAPNWRFC_HOME      = "$PWD\sapnwrfc"            # bundled SDK
# Optional — only if you also have an AWS account for parts of the run:
$env:AWS_REGION         = "ap-south-1"
$env:M4H_STAGING_BUCKET = "<your real S3 bucket name>"   # only if running against real AWS
```

> The runner sets `S3_STAGING_BUCKET=m4h-local` automatically. The shim treats that as a
> directory name under `./local-staging/`. If you later deploy the tool to AWS, override
> `M4H_LOCAL_MODE=0` and the same Lambdas talk to real AWS APIs unchanged.

---

## 5. Configure connections.json (~5 min)

The repo already has the ECC half populated (from your earlier brownfield work):
```json
{
  "ecc": {
    "ashost": "192.168.0.6",
    "sysnr": "41",
    "client": "800",
    "user": "sapuser",
    ...
  },
  "s4hana": null
}
```

For lift-and-shift you need the **target S/4 (CAL)** block too. Easiest is via the UI:

### Option A — via the Connections page in the UI
```powershell
python api_server.py   # starts http://localhost:8001
# In a browser: http://localhost:8001 → Connections → "Lift-and-Shift Target S/4" card
```
Fill in:
- `target_ashost` = CAL S/4 private IP
- `target_sysnr` = `00`, `target_client` = `100`
- `target_user` = `DDIC`
- `mc_base_url` = `https://<S/4 IP>:44300/sap/opu/odata/sap/CA_DATA_MIGRATION_SRV`
- `idoc_endpoint` = `https://<S/4 IP>:44300/sap/bc/idoc_xml`
- `idoc_partner` = `M4H_LAPTOP_ECC`, `idoc_partner_type` = `LS`
- `transport_host_instance_id` = the SAP CAL S/4 EC2 instance id (find it in AWS console)

### Option B — write `connections.json` directly
```json
{
  "ecc": { "ashost": "192.168.0.6", "sysnr": "41", "client": "800", "user": "M4H_RFC" },
  "s4hana": null,
  "lift_and_shift_target": {
    "target_ashost": "10.0.x.y",
    "target_sysnr": "00",
    "target_client": "100",
    "target_user": "DDIC",
    "mc_base_url": "https://10.0.x.y:44300/sap/opu/odata/sap/CA_DATA_MIGRATION_SRV",
    "ltmom_user": "DDIC",
    "idoc_endpoint": "https://10.0.x.y:44300/sap/bc/idoc_xml",
    "idoc_partner": "M4H_LAPTOP_ECC",
    "idoc_partner_type": "LS",
    "transport_host_instance_id": "i-0abc123"
  }
}
```

---

## 6. SAP-side configuration on the CAL S/4 (~45 min, one-time)

Most of the Fully-Activated Appliance is pre-configured. The two things you must verify/add:

### 6.1. STMS — accept transports from your laptop ECC
SAP GUI on the S/4 (logon via the Tailscale-bridged IP) → **STMS**:
1. Domain controller is the appliance itself.
2. Click **Systems** → add an **external system** entry for the laptop ECC:
   - System: `D01` (whatever your ECC SID is — check `/nSM51` on the laptop ECC; if you
     see no SID, use `NPL` which is the Ameerpet default)
   - Description: `Laptop ECC source for lift-and-shift`
   - Communication: **External** (file-based; we'll deliver cofiles via S3 → SSM)
3. Save. Activate the system. Yes-yes-yes through the warnings.
4. **Transport routes:** add a route `NPL → S4D` (consolidation) so STMS knows transports
   coming from NPL are valid.

> If you're not comfortable with STMS, just use `basis_handover_only` mode in stage 4 and
> do the STMS step manually when the runbook tells you to. The transport import is the only
> stage that requires this.

### 6.2. Activate Migration Cockpit OData service
SAP GUI → **/IWFND/MAINT_SERVICE** → confirm `CA_DATA_MIGRATION_SRV` is in status
"published". On the Fully-Activated Appliance it usually is.

If not: Add service → find `CA_DATA_MIGRATION_SRV` → activate. Same for
`CA_DATA_MIGRATION_OBJECT_SRV`.

### 6.3. IDoc inbound user + partner profile
SAP GUI → **WE20** → Partner type LS → create `M4H_LAPTOP_ECC` with:
- Inbound parameters: `MATMAS` / `DEBMAS` / `CREMAS` etc. — whichever IDoc types you'll
  use during the data-load phase.
- Process code: standard (`MATM`, `DEBM`, `CREM`).

### 6.4. Confirm SAP CAL S/4 client setup
- **SCC4** → client 100 is "Customizing allowed, no restriction" — leave as is for the
  first run. (Production would be locked down after go-live.)

---

## 7. Quick smoke test (~10 min)

Before you start a real migration, run smoke tests in this order. **The first two
require neither pyrfc nor AWS** — they only validate the runner + shim + JSON config.

```powershell
# 0. Set the mandatory env vars for this PowerShell session
$env:M4H_TARGET_MODE   = "basis_handover_only"
$env:SAPNWRFC_HOME     = "$PWD\sapnwrfc"

# 1. Dry-run the full pipeline — verifies all 28 stages load (no SAP calls)
python run_local_lift_and_shift.py --dry-run --run-id smoke-001

# 2. Stage 3 (object-router) + Stage 4 (target-provisioner basis_handover_only)
#    These have no SAP dependency and prove the shim + filesystem staging work
python run_local_lift_and_shift.py --only stage3 --run-id smoke-001
python run_local_lift_and_shift.py --only stage4 --run-id smoke-001

# 3. Check artifacts landed locally
Get-ChildItem local-staging\m4h-local\runs\smoke-001 -Recurse

# 4. Now install pyrfc and test ECC connectivity
$env:M4H_ECC_PASSWD = "<password>"
pip install pyrfc
python -c "from real_rfc_connection import test_ecc_connection; import json,os; print(json.dumps(test_ecc_connection({'ashost':'192.168.0.6','sysnr':'41','client':'800','user':'M4H_RFC','passwd':os.environ['M4H_ECC_PASSWD']}), indent=2))"

# 5. Run Stage 1 (System Discovery — read-only on ECC, requires pyrfc)
python run_local_lift_and_shift.py --only stage1 --run-id smoke-001 --ecc-host 192.168.0.6
```

If steps 1–3 succeed without you having configured AWS creds, the shim is healthy.
If step 4 returns `{"status":"success"}`, your laptop ECC is reachable. If step 5 prints
`status=success` and you see `local-staging\m4h-local\runs\smoke-001\discovery\…`,
**you are cleared to execute the full runbook**.

---

## 8. What this setup costs you per month

| Item | Cost |
|---|---|
| Tailscale t4g.nano EC2 (always on) | ~$3/mo |
| S3 staging bucket (under 10 GB) | ~$0.25/mo |
| CloudWatch logs (orchestration plane) | ~$1/mo |
| **SAP CAL S/4 EC2 (only while running)** | ~$8/hr × hours used |

If you do the migration across 3 weekends (say 12 hr each), that's 36 × $8 = **~$290 of CAL
compute**, plus ~$10 of orchestrator infra. **Suspend the CAL appliance the moment a phase
finishes** — that's the single biggest cost lever.

---

## 9. Where to go next

You are now ready to execute the migration itself. Open **`LIFT-AND-SHIFT-RUNBOOK.md`** and
follow it phase by phase. The runbook assumes everything in this setup file is done.

If something in this setup file failed, see the **Troubleshooting** appendix at the end of
the runbook.
