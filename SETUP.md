# Migrate4HANA — End-to-End Setup Guide

This guide covers two ways to run Migrate4HANA against your local-laptop ECC system:

1. **Local run** — pipeline executes on your workstation, hitting the ECC over LAN
2. **AWS run** — full cloud deployment (18 Lambdas + 4 ECS Fargate tasks + Step Functions) reaching back to your laptop ECC over a network bridge

---

## Part A — Local end-to-end run (no AWS)

You already have:
- `connections.json` — saved: `ashost=192.168.0.6, sysnr=41, client=800, user=sapuser` ✅
- `nwrfcsdk-linux/` and `sapnwrfc/lib/` — Linux + Windows SDK bundled ✅
- `run_local_pipeline.py` — runs all 17 stages locally against your real ECC ✅
- `api_server.py` + `frontend/` — UI workflow (FastAPI + React+Vite) ✅
- `real_rfc_connection.py` — pyrfc-based extractor with field-discovery and `--limit` for fast tests ✅

The tool is designed for exactly this scenario: no AWS, no S/4HANA target needed. You can run the **ECC-only** assessment + remediation modes end-to-end on your laptop.

### A.1 Verify ECC pre-requisites (on the SAP side)

In your Ameerpet ECC:
```abap
SU01 → user "sapuser" must have:
    Profile: SAP_ALL  (easiest for a personal lab)
    OR explicitly: S_RFC, S_TABU_DIS, S_DEVELOP (display)
SE16 → confirm RFC_READ_TABLE exists and runs (it does in any ECC)
SMGW → "gw/acl_mode = 0" or your laptop IP allowed (for RFC inbound)
SICF → /default_host/sap/bc/* services active (only if you'll later test OData)
```
Test from a Windows cmd: `telnet 192.168.0.6 3341` (port = 33<sysnr> = 3341 for sysnr 41). If this connects, RFC will reach.

### A.2 Install Python 3.10 and pyrfc

```powershell
# Use Python 3.10 — pyrfc has wheels for 3.10, not 3.13.
py -3.10 --version    # If missing, install from python.org
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
py -3.10 -m pip install --upgrade pip wheel
py -3.10 -m pip install -r requirements.txt
```

If `pip install pyrfc` fails on Windows (it sometimes needs MSVC Build Tools 2019+), the fastest fix is to install **Microsoft C++ Build Tools** (workload: "Desktop development with C++") and retry. The bundled `sapnwrfc/lib/sapnwrfc.dll` is auto-detected by `sapnwrfc/__init__.py` — you do **not** need to set `SAPNWRFC_HOME` manually.

### A.3 Smoke-test the RFC connection

```powershell
$env:M4H_ECC_PASSWD = "your-sapuser-password"
py -3.10 -c "import sapnwrfc; from pyrfc import Connection; c = Connection(ashost='192.168.0.6', sysnr='41', client='800', user='sapuser', passwd='$env:M4H_ECC_PASSWD'); print(c.call('STFC_CONNECTION', REQUTEXT='hello')); c.close()"
```
You should see `{'ECHOTEXT': 'hello', 'RESPTEXT': '...your SAP system info...'}`. If that works, the entire stack works.

### A.4 Run the pipeline (CLI)

**Option A — Smoke run (recommended first):**
```powershell
$env:M4H_ECC_PASSWD = "your-password"
py -3.10 run_local_pipeline.py --limit 50
```
This runs all 5 phases against ECC but extracts only 50 programs/customers/vendors — completes in ~2-5 minutes, writes to `test-output/run_<timestamp>/`.

**Option B — Assess-only (Phases 1-2, full data, no S/4 needed):**
```powershell
py -3.10 run_local_pipeline.py --assess-only
```

**Option C — ECC-only Full (everything that can run without S/4):**
```powershell
py -3.10 run_local_pipeline.py --mode ecc_full
```
This runs Stages 1-9 (Discovery, Maintenance Planner, Readiness Check, SI-Check, Code Analysis with auto-fix, BP prep, Data Assessment, Config Assessment, Pre-Conversion Gate) + Completeness Analyzer + PDF report.

### A.5 Run with the Web UI

```powershell
# Terminal 1 — backend
py -3.10 api_server.py        # http://localhost:8000

# Terminal 2 — frontend
cd frontend
npm install
npm run dev                    # http://localhost:5173
```
Then in the browser:
1. Open http://localhost:5173 → click **Get Token** (auth handshake).
2. **Connections** page → ECC fields are already pre-filled from `connections.json`. Enter the password → **Test Connection** (this caches the password in server memory for the session).
3. **Pipeline** page → click **Run Assess Only** for the first run, **Run ECC Full** for the complete pipeline, or **Run & Generate Report** for full + PDF.
4. Watch live progress in **Telemetry** / **Pipeline** pages.
5. **Report** page → download the consolidated PDF when done.

### A.6 View the outputs

```
test-output/run_<timestamp>/
├── discovery/summary.json
├── maintenance-planner/summary.json
├── readiness-check/summary.json
├── simplification-check/summary.json
├── code-analyzer/{transformed_programs/, fix_summary.json}
├── data-migrator/{customers, vendors, finance_docs}.json
├── config-replicator/, role-migrator/, integration-mapper/
├── migration-completeness-analyzer/scorecard.json
└── consolidated-report-volN.pdf   (one PDF per volume)
```

### A.7 What you do NOT need (for local run)

- ❌ AWS account
- ❌ S/4HANA target (the `--mode ecc_full` and `--assess-only` paths don't need it)
- ❌ SAP CAL
- ❌ Bedrock / Ollama (LLM is optional; pipeline gracefully degrades if absent)
- ❌ Any SAP licensed tools — this is pure read-only assessment via released BAPIs

### A.8 Common first-run gotchas

| Symptom | Fix |
|---|---|
| `pyrfc` install fails: `error: Microsoft Visual C++ 14.0 or greater required` | Install MSVC Build Tools 2019+ ("Desktop dev with C++") |
| `RFC_COMMUNICATION_FAILURE` / "partner not reached" | ECC VM not running, or laptop firewall blocking 3341. `ping 192.168.0.6` then `telnet 192.168.0.6 3341` |
| `RFC_LOGON_FAILURE` | Wrong password or user locked. Unlock in SU01. |
| `OSError: cannot load library 'libsapnwrfc'` (Linux/WSL) | `import sapnwrfc` before `from pyrfc import Connection` (already done in run_local_pipeline.py) |
| UI shows "ECC password not in memory" | You must click **Test Connection** every time the API server restarts |
| Frontend `npm install` fails | Ensure Node 18+ (`node -v`) |

### A.9 Recommended local-run sequence

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1; py -3.10 -m pip install -r requirements.txt
$env:M4H_ECC_PASSWD = "your-password"; py -3.10 run_local_pipeline.py --limit 25
```

If that completes successfully, you have a working end-to-end run. Then scale up to `--assess-only` (real volumes, ~15-30 min) and finally `--mode ecc_full` (~1-2 hrs depending on your ECC size).

---

## Part B — AWS end-to-end run (full cloud deployment)

This branch is fully wired for AWS: 14 Terraform modules, 18 Lambdas, 4 ECS Fargate tasks, Step Functions state machine, DMS, DynamoDB, Bedrock-PrivateLink, WebSocket telemetry, WAF, CloudTrail+S3-WORM.

### B.1 The 5 hard prerequisites

Do these BEFORE touching Terraform.

| # | Prereq | Why | How |
|---|---|---|---|
| 1 | AWS account with admin or PowerUser+IAM | Terraform creates IAM roles, VPCs, Lambda, ECS, DMS, Bedrock | `aws configure` with creds; ~$200-500 budget for a full E2E test (DMS + ECS + GPU EC2 if airgapped LLM) |
| 2 | **Network path: AWS VPC → your laptop ECC (192.168.0.6)** | Lambdas/ECS in private subnets must reach RFC port 3341 | See "Network options" below — this is the hardest piece |
| 3 | **An S/4HANA target system** | Phases 3-5 (SUM, code-deployer, data-loader, validator) require it | SAP CAL 30-day free trial → deploy "S/4HANA 2023 Fully-Activated Appliance" on AWS directly into the same VPC |
| 4 | Docker installed locally | Builds the pyrfc Lambda layer + ECS worker image | Docker Desktop |
| 5 | Terraform 1.5+, AWS CLI v2, Node.js 18+, jq | Deployment toolchain | `winget install hashicorp.terraform aws.awscli OpenJS.NodeJS jq` |

### B.2 Network options for "AWS → my laptop ECC"

Pick one:

| Option | Cost | Difficulty | Best for |
|---|---|---|---|
| **A. AWS Site-to-Site VPN** to your home router (if it supports IPsec) | ~$36/mo | Medium | If your router is OPNsense/pfSense/Mikrotik |
| **B. Tailscale Subnet Router on a tiny EC2 + on your laptop** | $0 + EC2 t4g.nano (~$3/mo) | **Easiest** ✅ | Your situation — bridges AWS VPC to your home LAN with zero firewall changes |
| **C. SAProuter on a public EC2** + saprouttab to your laptop | ~$15/mo (NAT/EIP) | Medium | If you want SAP-native routing |
| **D. Move ECC into AWS** (clone the VM into an EC2) | ~$80-200/mo for r5.xlarge | Easy after cloning | Cleanest E2E test — but defeats "use my laptop ECC" |

**Strong recommendation: Option B (Tailscale).** 10 minutes of setup, no firewall changes on your laptop, and the AWS subnet router becomes a route-target in the VPC route tables. You add `100.64.0.0/10` → tailscale ENI — and Lambda/ECS can reach 192.168.0.6:3341 transparently.

### B.3 The deployment sequence (8 steps, ~2 hours first time)

#### Step 1 — Configure AWS CLI and Terraform vars

```powershell
aws configure                   # access key, secret, region us-east-1
cd terraform\environments\dev
notepad terraform.tfvars
```
Edit it to:
```hcl
aws_region        = "us-east-1"
environment       = "dev"
alert_email       = "you@email.com"
vpc_cidr          = "10.10.0.0/16"
availability_zones   = ["us-east-1a","us-east-1b"]
private_subnet_cidrs = ["10.10.1.0/24","10.10.2.0/24"]
public_subnet_cidrs  = ["10.10.101.0/24","10.10.102.0/24"]
enable_vpn_gateway = false        # we'll use Tailscale instead
on_prem_cidr       = "192.168.0.0/24"   # your home LAN
s3_staging_bucket  = "migrate4hana-staging-dev-<your-account-id>"
pyrfc_layer_arn    = ""           # filled by setup-pyrfc.sh in step 2
```

#### Step 2 — Build & publish the pyrfc Lambda layer (the linchpin)

The bundled SAP NW RFC SDK in `nwrfcsdk-linux/` is auto-detected by the script:
```bash
# Use WSL/Git Bash since the script is bash:
cd scripts
chmod +x setup-pyrfc.sh
./setup-pyrfc.sh
```
This Docker-builds an Amazon Linux 2 layer containing pyrfc + libsapnwrfc.so, validates it imports inside a Lambda container, publishes it to AWS, and **auto-writes the ARN into `terraform.tfvars`**. Expected output:
```
✓ pyrfc 3.x imported successfully
Layer ARN: arn:aws:lambda:us-east-1:<acct>:layer:migrate4hana-pyrfc:1
✓ Updated pyrfc_layer_arn in terraform.tfvars
```

#### Step 3 — Stand up the network bridge (Tailscale, Option B)

```powershell
# On your laptop:
# 1. Install Tailscale, sign in, ensure 192.168.0.6 is reachable

# 2. Launch a t4g.nano in your AWS account (any subnet for now), SSH in, install Tailscale subnet router:
#    curl -fsSL https://tailscale.com/install.sh | sh
#    sudo tailscale up --advertise-routes=192.168.0.0/24 --accept-routes
#    Approve the route in https://login.tailscale.com/admin/machines
```
Add a route in your VPC route tables: `192.168.0.0/24 → eni-of-tailscale-ec2`.

Test from any EC2 in the VPC: `nc -vz 192.168.0.6 3341` should connect.

#### Step 4 — Apply Terraform (creates all 14 modules)

```powershell
cd terraform\environments\dev
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```
First-time apply: **~15 minutes**. Creates VPC, subnets, NAT GW, S3, DynamoDB, 18 Lambdas, ECS cluster + ECR, Step Functions state machine, CloudWatch alarms, DMS replication instance (slow!), VPC endpoints for Bedrock, WebSocket API, WAF, CloudTrail.

Capture outputs:
```powershell
$STATE_MACHINE = terraform output -raw state_machine_arn
$ECR_URL       = terraform output -raw ecr_repository_url
$S3_BUCKET     = terraform output -raw s3_staging_bucket
```

#### Step 5 — Build & push the ECS Fargate worker image

Stages 1 (discovery-engine), 5 (code-analyzer), 12 + 12A (data-loader parallel) run on Fargate via `ecs/Dockerfile`:
```powershell
cd ..\..\..
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin $ECR_URL
docker build -f ecs/Dockerfile -t migrate4hana-worker:latest .
docker tag migrate4hana-worker:latest "$ECR_URL`:latest"
docker push "$ECR_URL`:latest"
```

#### Step 6 — Populate Secrets Manager with SAP credentials

```powershell
aws secretsmanager put-secret-value `
  --secret-id migrate4hana/dev/sap-credentials `
  --secret-string '{\"host\":\"192.168.0.6\",\"sysnr\":\"41\",\"client\":\"800\",\"user\":\"sapuser\",\"passwd\":\"YOURPWD\"}'

aws secretsmanager put-secret-value `
  --secret-id migrate4hana/dev/s4hana-credentials `
  --secret-string '{\"host\":\"<S4-host>\",\"sysnr\":\"00\",\"client\":\"100\",\"user\":\"DDIC\",\"passwd\":\"YOURPWD\"}'
```

#### Step 7 — Smoke-test connectivity from inside the VPC

The single most important test before kicking off Step Functions:
```powershell
aws lambda invoke `
  --function-name migrate4hana-dev-maintenance-planner `
  --payload '{"metadata":{"run_id":"smoke-001"},"input":{"mode":"assess","ecc_client":"800","ping":true}}' `
  --cli-binary-format raw-in-base64-out `
  out.json
cat out.json
```
Expected: `{"statusCode":200,"body":{"sap_connected":true,...}}`. If you get `RFC_COMMUNICATION_FAILURE`, the Tailscale route isn't working — fix that before continuing.

#### Step 8 — Run the pipeline end-to-end

**Phase 1-2 only (assessment, safe, no S/4 needed)** — recommended first:
```powershell
aws stepfunctions start-execution `
  --state-machine-arn $STATE_MACHINE `
  --name "assess-$(Get-Date -Format yyyyMMdd-HHmmss)" `
  --input '{\"mode\":\"assess\",\"ecc_client\":\"800\",\"execute\":false}'
```

**Full 17-stage execution** (requires S/4HANA target alive):
```powershell
aws stepfunctions start-execution `
  --state-machine-arn $STATE_MACHINE `
  --name "full-$(Get-Date -Format yyyyMMdd-HHmmss)" `
  --input '{\"mode\":\"full\",\"ecc_client\":\"800\",\"execute\":true}'
```

Watch in real-time:
- AWS Console → Step Functions → state machine → execution graph (visual stage-by-stage)
- CloudWatch Logs → `/aws/lambda/migrate4hana-dev-*`
- ECS Console → cluster → tasks (for stages 1, 5, 12, 12A)
- S3 → `migrate4hana-staging-dev-<acct>/run-<id>/` for all stage outputs
- DynamoDB → `migrate4hana-idempotency`, `migrate4hana-state`

#### Step 9 — UI on top (optional polish)

Build & host the React UI on S3+CloudFront, OR run locally pointed at the AWS state machine:
```powershell
cd frontend
npm install
$env:VITE_API_URL = "https://<your-api-gw-url>"   # if you front Step Fns with API GW
npm run build
# Or for local dev pointing at the deployed Step Functions:
npm run dev
```

### B.4 Cost expectations for a full E2E test

| Resource | ~Cost (24-hr test) |
|---|---|
| VPC, 2 NAT gateways | ~$2 |
| Lambda invocations (18 fns × few invocations) | <$0.10 |
| ECS Fargate (4 tasks × ~30 min) | ~$1 |
| DMS replication instance (dms.t3.medium) | ~$2 |
| S3 + DynamoDB | <$0.50 |
| CloudWatch logs/alarms | <$0.50 |
| Step Functions transitions | <$0.10 |
| **(Optional) GPU EC2 g5.2xlarge for airgapped LLM** | **~$30/day** ← skip for first test |
| **(Optional) S/4HANA from SAP CAL on AWS** | ~$30-50/day for the appliance EC2 |
| **Total without S/4 + GPU** | **~$5-10/day** |
| **Total with S/4 + no GPU** | **~$40-60/day** |

`terraform destroy` cleans everything except S3 (set `force_destroy=true` if you want it gone too).

### B.5 What a successful full E2E run looks like

After a successful `mode:full` run you should see:
1. ✅ Step Functions execution status = `SUCCEEDED` (all 17 stages green)
2. ✅ S3: `s3://.../run-<id>/scorecard.json` with `migration_status: SUCCESS`
3. ✅ S3: `consolidated-report-vol1.pdf` (multi-volume)
4. ✅ DynamoDB `migration_state` table shows phase=COMPLETE
5. ✅ CloudWatch dashboard: zero red alarms
6. ✅ Validator stage confirms BP counts ECC↔S/4 reconciled

### B.6 Recommended AWS-run sequence

1. Run **B.3 Steps 1–4** today → you'll have the AWS skeleton up.
2. Set up **Tailscale (Step 3)** in parallel — this unblocks everything.
3. Run **Step 7 smoke test** to prove RFC works from Lambda → your laptop ECC.
4. Run **Step 8 assess-only** (no S/4 needed) — this is your first real E2E AWS pipeline run end-to-end.
5. Only *then* spin up SAP CAL S/4HANA in the same VPC for the full 17-stage run.

---

## Reference

| Path | Purpose |
|---|---|
| `run_local_pipeline.py` | CLI entry point for local end-to-end run |
| `api_server.py` | FastAPI backend for the React UI (port 8000) |
| `frontend/` | React + Vite UI (port 5173) |
| `real_rfc_connection.py` | pyrfc wrapper used by all stages |
| `sapnwrfc/`, `nwrfcsdk-linux/` | Bundled SAP NW RFC SDK (Windows + Linux) |
| `connections.json` | Persisted ECC/S4 connection params (no passwords) |
| `lambda/` | 18 Lambda handlers + ECS-targeted stages |
| `ecs/` | Fargate worker image source |
| `terraform/environments/dev/` | Terraform root for dev env |
| `terraform/modules/` | 14 reusable Terraform modules |
| `scripts/setup-pyrfc.sh` | Builds + publishes the pyrfc Lambda layer |
| `scripts/deploy.sh` | Packages Lambdas, builds frontend, runs Terraform |
