# Demo Quickstart — 30 Minutes from Cold Machine to Live Demo

*PowerShell-only. Tested on Windows 10/11. Designed so you can run this from a fresh
machine and have a working demo on a real SAP ECC + S/4HANA pair in under 30
minutes.*

*If you get stuck, search this doc for the exact error message. Most common
failures have a "**If you see X, do Y**" entry.*

---

## Before you start — what you need

### Software on your laptop

| Tool | Why | Install command |
|---|---|---|
| **AWS CLI v2** | Talk to AWS | Download from https://aws.amazon.com/cli/ |
| **Terraform 1.5+** | Build the AWS infrastructure | Download from https://www.terraform.io/downloads |
| **Docker Desktop** | Build the Fargate worker image | Download from https://www.docker.com/products/docker-desktop/ — **switch to Linux containers mode** |
| **Python 3.11+** | Run local scripts + the API server | https://www.python.org/downloads/ |
| **Node.js 18+** | Run the React UI | https://nodejs.org/ |
| **PowerShell 7** (optional but nicer) | `winget install Microsoft.PowerShell` |

### Accounts you need

| Account | Where to get it | Cost |
|---|---|---|
| **AWS account** with admin access | https://aws.amazon.com/ | Free tier covers most of the demo; ~$5-20 if you run for a day |
| **Anthropic API key** | https://console.anthropic.com/ | ~$5 free credit; ~$0.07 per code-remediation |
| **SAP NW RFC SDK 7.50** zip | https://support.sap.com (S-user account) — proprietary | Free with S-user |
| **SAP IDES ECC system** | Already on your laptop (Y01 at `10.68.159.204`) | Already paid for |
| **SAP CAL S/4HANA trial** | https://www.sapcal.com/ — 30-day free trial | Free for 30 days, then ~$10/h |

### What you have on hand (verified 2026-05-23)

- ECC source: `10.68.159.204` system Y01 sysnr 41 client 800 user `sapuser`
- S/4 target: AWS-hosted CAL appliance (IP changes each restart; check
  `connections.json`) client 100 user `SAP*`
- Repo: `C:\Users\ajays\Downloads\migrate4hanav2\`
- pyrfc layer pre-built at `layer-build\pyrfc-layer.zip`
- SAP NW RFC SDK at `ecs\nwrfc750P_6-70002752_linux64bit.zip`

---

## Step 0 — Verify your setup (5 minutes)

Open PowerShell and run each of these. **Every line should succeed before you continue.**

```powershell
# Move to the repo
cd C:\Users\ajays\Downloads\migrate4hanav2

# AWS CLI is configured?
aws sts get-caller-identity
# EXPECT: JSON with your account ID and ARN.
# IF YOU SEE: "Unable to locate credentials" → run `aws configure` and paste your access key/secret.

# Terraform is installed?
terraform version
# EXPECT: Terraform v1.5.x or higher.

# Docker is running and in Linux mode?
docker info | Select-String "OSType"
# EXPECT: OSType: linux
# IF YOU SEE: "OSType: windows" → right-click the Docker tray icon → "Switch to Linux containers"
# IF YOU SEE: "cannot connect to Docker daemon" → start Docker Desktop, wait for the whale icon to settle

# SAP RFC SDK zip is present?
Test-Path .\ecs\nwrfc750P_6-70002752_linux64bit.zip
# EXPECT: True

# pyrfc Lambda layer was pre-built?
Test-Path .\layer-build\pyrfc-layer.zip
# EXPECT: True
# IF FALSE: run `python layer-build\build_pyrfc_layer.py` first (~5 min, needs Docker)

# ECC system is reachable?
Test-NetConnection -ComputerName 10.68.159.204 -Port 3241
# EXPECT: TcpTestSucceeded: True
# IF FALSE: your VMware ECC VM is paused or the IP changed. Start the VM, check the new IP.
#           See [[connectivity-quirks]] memory for the recovery pattern.
```

**Time check**: you should be ~5 minutes in. If you're stuck on any line above,
stop and fix it before continuing — every later step depends on these.

---

## Step 1 — Deploy the AWS stack (8 minutes)

This stands up the full 200-resource AWS infrastructure: VPC, Lambdas,
DynamoDB, S3, KMS, Step Functions, the works.

```powershell
cd .\terraform\environments\prod\

# Initialize Terraform (downloads providers; one-time per machine)
terraform init
# EXPECT: "Terraform has been successfully initialized!"

# Apply (this is the big one)
terraform apply -auto-approve
# EXPECT: 5-8 minutes of resource creation messages, then:
#   "Apply complete! Resources: 200 added, 0 changed, 0 destroyed."
# IF YOU SEE: "Secret already scheduled for deletion" → 30-day soft-delete from a prior run.
#             Fix: aws secretsmanager delete-secret --secret-id <name> --force-delete-without-recovery
#             Then re-apply.
# IF YOU SEE: "BucketAlreadyExists" → another AWS account is using that bucket name.
#             Edit terraform/environments/prod/main.tf bucket name suffix and re-apply.

# Confirm the stack came up
terraform output
# EXPECT: ~15 output values — staging bucket name, state machine ARN, etc.
```

**What you just built**: 200 cloud resources, including:
- 1 VPC with private + public subnets across 3 AZs
- 37 Lambda functions
- 1 ECS Fargate cluster + task definition + ECR repository
- 5 DynamoDB tables (key-map, audit-ledger, gates, run-events, recon-tolerance)
- 4 S3 buckets (staging, evidence, audit-logs, mapping)
- 4 Secrets Manager secrets
- 1 KMS Customer Master Key
- 2 Step Functions state machines
- 1 CloudWatch dashboard + alarms
- 1 WAFv2 WebACL
- 1 SNS topic + email subscription

**Time check**: ~13 minutes total. If apply fails, the error message tells you
what to fix; the most common ones are in §EXPERT_REVIEW_BRIEF.md:§13.

---

## Step 2 — Push the Fargate worker image (5-8 minutes)

The AWS stack created an empty container registry. We need to push the
worker image into it so the heavy migration stages have something to run.

```powershell
cd ..\..\..\
# (back to repo root)

# One command does everything: pre-flight checks, ECR login, build, push, verify.
.\scripts\push-fargate-image.ps1
# EXPECT:
#   ==> Pre-flight checks
#   docker: linux containers OK
#   AWS account: <your account>
#   SAP SDK: nwrfc750P_*.zip (XX MB)
#   ==> Verifying ECR repository exists
#   ==> Logging in to ECR
#   ==> Building image (this takes 5-8 min the first time)
#   ==> Tagging + pushing to <your-account>.dkr.ecr.us-east-1.amazonaws.com/migrate4hana/worker:latest
#   ==> Verifying push landed in ECR
#   Pushed: tag=latest size=~450MB
#   Done in ~6 minutes
# IF YOU SEE: "Docker daemon not reachable" → start Docker Desktop.
# IF YOU SEE: "ECR repository not found" → terraform apply didn't include the ecs module.
#             Run `terraform state list | Select-String ecr` to confirm.
# IF YOU SEE: "no basic auth credentials" → ECR token expired (12h). Re-run the script.
```

**Time check**: ~20 minutes total.

---

## Step 3 — Load the Anthropic API key (1 minute)

The code-remediation Lambda needs the Anthropic API key. We seed it into
Secrets Manager so all Lambdas can pick it up at runtime.

```powershell
# Replace sk-ant-... with your real Anthropic API key
aws secretsmanager put-secret-value `
  --secret-id migrate4hana/prod/anthropic-api-key `
  --secret-string '{\"api_key\":\"sk-ant-YOUR-KEY-HERE\"}'
# EXPECT: JSON output with VersionId and the secret ARN.
# IF YOU SEE: "ResourceNotFoundException" → terraform apply didn't create the secret.
#             Run: aws secretsmanager list-secrets --query "SecretList[?Name=='migrate4hana/prod/anthropic-api-key']"
#             If empty, re-run terraform apply.
```

---

## Step 4 — Confirm the email subscriptions (1 minute)

Terraform created two SNS topics with pending email subscriptions:
- `migrate4hana-alerts-prod` — pipeline failure alerts
- `migrate4hana-spine-gates-prod` — human-approval gate notifications

Check your inbox (`var.alert_email` you provided to Terraform). Click the
"Confirm subscription" link in **both** emails.

If you don't see them within a minute, check Spam. If still nothing:

```powershell
# Re-trigger the subscription
aws sns list-subscriptions --query "Subscriptions[?starts_with(TopicArn, 'arn:aws:sns:us-east-1:')]"
# Look for SubscriptionArn: "PendingConfirmation" — re-confirm by:
aws sns subscribe --topic-arn <TopicArn> --protocol email --notification-endpoint <your-email>
```

---

## Step 5 — Start the local UI + API (3 minutes)

The React UI talks to a local FastAPI backend (`api_server.py`). Both need to
be running for the demo.

Open **two PowerShell windows**.

**Window 1 — start the backend API:**

```powershell
cd C:\Users\ajays\Downloads\migrate4hanav2
# Install Python deps the first time (one-time, ~2 min)
pip install fastapi uvicorn boto3 pyrfc

# Start the API
python api_server.py
# EXPECT:
#   INFO: Uvicorn running on http://0.0.0.0:8000
#   INFO: Application startup complete.
# LEAVE THIS RUNNING.
```

**Window 2 — start the React UI:**

```powershell
cd C:\Users\ajays\Downloads\migrate4hanav2\frontend
# Install deps the first time (one-time, ~3 min)
npm install

# Start the dev server
npm run dev
# EXPECT:
#   VITE v5.x.x  ready in XXX ms
#   ➜  Local:   http://localhost:5173/
# LEAVE THIS RUNNING.
```

Open your browser to **http://localhost:5173/**. You should see the
Migrate4HANA Dashboard.

**If the UI loads but says "Offline" or pages don't load data:** the backend
isn't reachable. Check Window 1 for errors. Most common cause: port 8000
already in use → change `api_server.py`'s port + the `frontend/src/lib/api.js`
base URL together.

---

## Step 6 — Wire up your SAP connections (3 minutes)

In the UI, click **Setup → Connections** in the left sidebar.

You'll see two cards: **Source (SAP ECC)** and **Target (SAP S/4HANA)**.

For each card, click "Edit" (or use the API):

**Source (ECC):**
- Host: `10.68.159.204`
- System number: `41`
- Client: `800`
- User: `sapuser`
- Password: (yours)

**Target (S/4HANA):**
- Host: (your current CAL appliance IP — check the AWS CAL console)
- System number: `00`
- Client: `100`
- User: `SAP*`
- Password: (yours)

After saving, the cards turn from grey to green and the status badge says
**connected**. Both must be green before you trigger a run.

**If a card stays grey or shows "Connection refused":**
- Confirm the IP is current (CAL IPs change on restart)
- Confirm the SAP system is running (RDP into the CAL appliance, check
  Windows Services → SAP* services should be "Running")
- For ECC: see [[connectivity-quirks]] memory — the VM may have paused, or
  SAP didn't auto-start after VMware boot

---

## Step 7 — Trigger a demo migration (10 minutes)

Now the fun part. In the UI, click **Execute → Migration Pipeline**.

You'll see the **28 pipeline stages** laid out. At the top: two big buttons:
- **Run Assess** — discovery + readiness only (~3 min, safe to run anytime)
- **Run Full** — the whole migration (~10 min on small fixtures)

Click **Run Assess** first to verify connectivity:

```
EXPECT (sequentially):
  Stage 1 - Discovery        ✓ completed in 12s
  Stage 2 - Readiness Check  ✓ completed in 28s
  Stage 3 - Sizing           ✓ completed in 4s
  Stage 4 - Object Routing   ✓ completed in 6s
  Stage 5 - (skipped in assess mode)
  ...
```

**If a stage fails red:** click on it to see the error detail. Most common:
- **"ECC connection failed"** → re-check Connections page
- **"Pyrfc not importable"** → the Lambda's pyrfc layer attach failed; re-run
  `terraform apply`
- **"Secret not found"** → step 3 didn't complete; re-run step 3

Once Assess goes green end-to-end, click **Run Full** for the real demo:

```
EXPECT:
  Stages 1-7  : ASSESS phase    → 2 min
  Stages 8-11 : PROVISION phase → 1 min (uses Fargate)
  Stages 12-15: CODE phase      → 2 min (your AST engine + AI fallback)
  [WAIT-GATE] : ASSESS Approval → email alert + Gates page badge ◄── click "Approve"
  Stages 16-19: CONFIG phase    → 1 min
  Stages 20-22: DATA-PREP phase → 1 min
  [WAIT-GATE] : DATA-PREP Approval ◄── approve
  Stages 23-25: DATA-LOAD phase → 2 min (loads BP/Customer/Vendor/Material to S/4)
  Stages 26-28: VALIDATE phase  → 1 min
  [WAIT-GATE] : VALIDATE Approval ◄── approve
  [WAIT-GATE] : CUTOVER Approval  ◄── approve (or reject for demo)
```

**This is the demo arc**. The 4 approval gates are where you, the operator,
demonstrate human oversight. You can pause, inspect, approve or reject.

---

## Step 8 — Show the audit + reports (2 minutes)

After the run completes, click **Results → Runs & Reports**.

You'll see the run listed with:
- A **grade** (typically A through F based on reconciliation completeness)
- A **score** (0-100)
- A **recommendation** (GO / GO_WITH_WARNINGS / NO_GO)

Click the run, then click **PDF Report** to download the full audit PDF.

The PDF contains:
- Run summary
- Per-object load counts + reconciliation verdict
- The cryptographic audit chain (every block, every hash)
- The captured SAP balance reports (FAGLB03 / MB5B) with their SHA-256s
- The cutover verdict + the precedence rule that produced it
- Per-stage timing breakdown

**This PDF is what you hand the auditor.** It's the Big-4-readable artefact.

---

## Step 9 — Tear it all down (3 minutes)

When you're done demoing, kill the infrastructure to stop the AWS clock:

```powershell
cd C:\Users\ajays\Downloads\migrate4hanav2\terraform\environments\prod
terraform destroy -auto-approve
# EXPECT: 5-10 minutes of teardown, then "Destroy complete!"
# IF IT FAILS on the audit-logs bucket "BucketNotEmpty":
#   - The bucket has Object Lock GOVERNANCE retention on log files.
#   - Empty it first with the bypass-governance helper:

python -c "
import boto3
s3 = boto3.client('s3', region_name='us-east-1')
bucket = 'migrate4hana-audit-logs-prod-' + boto3.client('sts').get_caller_identity()['Account']
paginator = s3.get_paginator('list_object_versions')
for page in paginator.paginate(Bucket=bucket):
    objs = [{'Key': v['Key'], 'VersionId': v['VersionId']}
            for v in (page.get('Versions') or []) + (page.get('DeleteMarkers') or [])]
    if objs:
        s3.delete_objects(Bucket=bucket, Delete={'Objects': objs, 'Quiet': True},
                          BypassGovernanceRetention=True)
"

# Then re-run destroy
terraform destroy -auto-approve
```

Confirm everything is gone:

```powershell
aws lambda list-functions --query "length(Functions[?starts_with(FunctionName, 'migrate4hana-')])"
# EXPECT: 0
```

---

## Cost expectations

For a typical demo session (~3-4 hours, single run):

| Cost driver | Typical |
|---|---|
| Lambda invocations | <$1 |
| Fargate task-hours | <$1 |
| DynamoDB on-demand | <$1 |
| S3 PUT + storage | <$1 |
| KMS | <$1 |
| NAT data | <$2 |
| Anthropic API | <$1 (depends on code-remediation hits) |
| CloudWatch + WAF | <$2 |
| **Per demo total** | **~$5-10** |

If you forget to `terraform destroy` and leave it running for a day:
- NAT gateway: ~$1.10/day
- Idle resources: ~$2-3/day

A week of forgetting costs ~$15-20. Not catastrophic but worth a calendar
reminder.

---

## Pre-demo checklist (the day before)

Print this. Tick each item.

- [ ] **Laptop**: Docker is running, Linux container mode.
- [ ] **Network**: confirm both ECC + S/4 are reachable (Step 0).
- [ ] **AWS**: `aws sts get-caller-identity` returns your account.
- [ ] **AWS**: previous demo torn down (`terraform destroy` clean).
- [ ] **Anthropic**: API key is current and has credit.
- [ ] **Email**: SNS confirmations were clicked (in case you re-deploy).
- [ ] **UI**: `npm run dev` boots without errors.
- [ ] **API**: `python api_server.py` boots without errors.
- [ ] **Browser**: clear cache; first load can be slow.
- [ ] **Demo data**: fixtures are in place (check `tests/fixtures/`).
- [ ] **Slide deck**: `PITCH_DECK.md` printed or ready.
- [ ] **Audit PDF**: have a sample run's PDF ready in case live demo flakes.
- [ ] **Fallback**: a screen-recording of a clean run, just in case. Click
      **Run Full** end-to-end NOW, record it, store the .mp4 in `tests/demos/`.

---

## When something goes wrong mid-demo (don't panic)

The single biggest demo killer is the SAP ECC VM having paused / lost
network. Symptoms: anything that uses pyrfc returns "Connection refused"
or hangs.

**The 90-second recovery dance:**

1. **In the browser**: keep talking. "While the network re-stabilises, let
   me show you the audit trail from yesterday's run..." then click on a
   previous run from **Runs & Reports**.
2. **In Window 3 PowerShell**: `Test-NetConnection 10.68.159.204 -Port 3241`.
   If False: switch to the VMware window, hit "Resume" on the ECC VM, wait
   30s for SAP to come up.
3. **In Window 1 (api_server)**: hit Ctrl-C and re-launch. The connection
   pool needs a refresh after the source flaps.
4. **In the browser**: refresh the Connections page. Should go green again.

If the AWS Lambda layer broke (pyrfc import error in CloudWatch logs):
your fallback is the **pre-recorded demo video** in `tests/demos/`. Pivot
to that gracefully: "Let me show you a recent clean run we captured for
documentation purposes."

---

## You're ready

If you got through Step 8 in under 30 minutes, you have a demo-ready
deployment. Practice the whole thing 2-3 times before the real demo. Time
each run; you should be able to do Steps 0-8 in 25 minutes by the third
practice.

*Next read: `UI_DEMO_GUIDE.md` for what to actually say while clicking
through each UI page.*
