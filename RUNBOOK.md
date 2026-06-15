# Migrate4HANA — End-to-End RUNBOOK
## Local laptop ECC → S/4HANA, then the same pipeline from AWS

> This runbook is your **single source of truth** for executing a full lift-and-shift
> migration. Follow it top to bottom. It replaces no other doc — it just sequences them.
>
> - **Part A** — one-time pre-flight on your laptop (~30 min)
> - **Part B** — run the 28-stage pipeline locally, end-to-end, ECC → S/4HANA (~6–8 hr active)
> - **Part C** — deploy Migrate4HANA into AWS and re-run the same pipeline from there (~3–4 hr)
>
> Reference docs (open them only if a step here points at them):
> - `LIFT-AND-SHIFT-SETUP.md` — one-time infra setup details (CAL, Tailscale)
> - `LIFT-AND-SHIFT-RUNBOOK.md` — per-stage deep dive (what each handler does, failure modes)
> - `PRODUCTION_READINESS_GUIDE.md` — AWS deploy + hardening details
>
> Branch: `aws-lift-and-shift`. Confirm with `git branch --show-current`.

---

# 30-Second Triage — When something is on fire

Use this section when a run is failing in prod and you have to decide in seconds whether to
**hold the pipeline**, **roll back**, or **proceed with a warning**. Each numbered question
maps to one CloudWatch alarm and one remediation path. Stop at the first YES; the line tells
you exactly what to do next.

| # | Symptom (5-sec read) | Where to look (CloudWatch) | Decision |
|---|---|---|---|
| 1 | **Hash chain broken?** | alarm `compliance_chain_broken` (any block != `ok`) | **HOLD** — `HashChainLedger.verify()` shows `broken_at`; do not progress past the post-validate gate. Root-cause the writer that emitted a divergent block. |
| 2 | **Ledger write failure spike?** | alarm `ledger_write_failure` | **HOLD** — DDB throttled or `put_item` permission revoked. Check `key_map_throttle` next; if both fire, scale DDB on-demand or raise provisioned WCU. |
| 3 | **Cutover verdict NO_GO?** | run `evidence_pack.cutover_verdict` block (see `lambda/utils/reconciler.py::_compute_cutover_verdict`) | **HOLD** — the SAP-spool precedence rule blocks; do NOT let the tool override. Read the `reasons[]` array: missing FAGLB03/MB5B, LTMC pending, or balance variance — each has a separate remediation. |
| 4 | **Lambda error rate > 1%?** | alarm `lambda_error_rate` | **TRIAGE** — open the most-recent failed invocation; if dead-letters are typed (`DATA_QUALITY_REJECTION` / `MISSING_DEPENDENCY` / `BAPI_FAILURE`), the spine is doing its job — those are quarantined, not pipeline-failures. If the alarm is from `Errors` metric (untyped), pull the stack trace. |
| 5 | **Lambda p95 latency > 1.5s?** | alarm `lambda_p95_latency` | **PROCEED** with warning — heavy SAP number-range contention; backpressure with `WorkloadThrottle`. Set `M4H_BAPI_CONCURRENCY=8` and resume. |
| 6 | **DQ violation rate spike?** | alarm `dq_violation_rate` | **TRIAGE** — open the value-maps; a recently-edited `value-maps/matrix.json` likely dropped a key. `git log --oneline value-maps/` shows the last edit. |
| 7 | **Lambda throttles > 0?** | alarm `lambda_throttles` | **PROCEED** with warning — concurrency cap reached; raise reserved concurrency or backoff. |
| 8 | **WAF block spike on the API?** | alarm `waf_blocked_requests` | **TRIAGE** — UI traffic blocked by WAF rate-rule; if legitimate, raise the rate; if attack-shaped, leave the rule. |
| 9 | **Unauthorized API call?** | alarm `unauthorized_api_calls` (CloudTrail-driven) | **HOLD** — likely IAM drift or compromised credential. Lock the run via the cutover gate before progressing. |
| 10 | **None of the above firing but a run feels stuck?** | look at the Step Functions execution `…__post_data_prep` task token | **TRIAGE** — a gate is waiting on a human. Read `gates.json` for the pending HMAC-signed gate; the `approve_url` from `build_gate_alert()` is your `/api/spine/approve` POST target. |

**Three numbers a triager memorizes:**

- **SAP-spool precedence > tool ledger.** If FAGLB03 or MB5B is missing, the verdict is NO_GO. The tool cannot override.
- **`load_one()` never raises.** Any per-record failure becomes a typed `LoadResult` dead-letter. A crashing record does NOT take down the batch.
- **DR for the key-map is 3 commands.** `backup-key-map.ps1` → `restore-key-map.ps1` → `swap-key-map.ps1` (atomic). See `docs/DR.md` and the scripts' `.SYNOPSIS` blocks.

If none of the above resolves it within 30 seconds, escalate to the §Part-B per-stage runbook (`LIFT-AND-SHIFT-RUNBOOK.md`) — that doc covers per-handler failure modes in depth.

---

# Part A — Pre-flight (one-time, on your laptop)

Do this once. Subsequent runs only need the env vars (§A.6) re-set in a new shell.

## A.1. Confirm prerequisites

```powershell
git branch --show-current     # must be: aws-lift-and-shift
python --version              # 3.7 works locally (see note); 3.10+ recommended
node --version                # 18+
docker --version              # optional, only needed for Part C (AWS deploy)
aws --version                 # optional, only needed for Part C
```

**Python version note (Windows reality on this branch):**
- The bundled SAP NW RFC SDK ships only **pyrfc 2.8.31 wheels**, which are pinned to
  **Python 3.7**. pyrfc ≥ 3.0 needs Visual Studio C++ build tools to compile — usually a
  non-starter on a laptop.
- The Lambda handlers all use `from __future__ import annotations`, so 3.7 syntax is
  sufficient. Newer boto3 (≥ 1.34) refuses to install on 3.7 — pin to **boto3 1.33.13**
  instead (last release that supports 3.7).
- For the AWS-hosted side (Part C), the Lambda runtime in Terraform is Python 3.11 — that
  runs the same source, just packaged via `scripts/deploy.sh`. Your **local** Python
  version doesn't have to match the Lambda runtime.

## A.2. Confirm SAP source + target reachability

```powershell
# Source: your laptop ECC (currently 192.168.0.5 per connections.json)
Test-NetConnection 192.168.0.5 -Port 3341    # sysnr 41 → gateway 33<sysnr> = 3341

# Target S/4HANA (replace <S4_IP> with the real IP — connections.json is still a placeholder)
Test-NetConnection <S4_IP> -Port 3300        # sysnr 00 → RFC gateway
Test-NetConnection <S4_IP> -Port 8000        # ICM HTTP (MC OData + IDoc inbound)
Test-NetConnection <S4_IP> -Port 44300       # ICM HTTPS
```

All four ports must return `TcpTestSucceeded : True`. If not, fix network (Tailscale /
VPN / firewall) before continuing. See `LIFT-AND-SHIFT-SETUP.md §1.4` for the
Tailscale bridge.

## A.3. Python dependencies

**Use your existing system Python 3.7** (the one that has pyrfc 2.8.31 already
installed — verify with `pip show pyrfc`). Do **not** create a 3.10+ venv; pyrfc won't
build there without Visual Studio C++ tools.

```powershell
cd C:\Users\ajays\Downloads\migrate4hanav2

# Pinned boto3 — last release that supports Python 3.7. requirements.txt asks for
# >= 1.34 which won't install on 3.7, so install these explicitly:
py -3.7 -m pip install "boto3==1.33.13" "botocore==1.33.13"

# Then the rest of requirements.txt — but skip the boto3/pyrfc/fastapi pins that won't
# install on 3.7. Install on demand only what each stage needs:
py -3.7 -m pip install "requests>=2.31.0" "reportlab>=4.0" "ollama" --upgrade
```

**Verify the import works:**
```powershell
python -c "import boto3, pyrfc; print('boto3', boto3.__version__, '| pyrfc', pyrfc.__version__)"
# Expected: boto3 1.33.13 | pyrfc 2.8.31
```

> `fastapi` / `pydantic v2` / `locust` won't install on 3.7. **That's fine** — they're
> only needed for the optional `api_server.py` (which you can run from Python 3.10 in a
> separate shell if you want the UI) and for load tests. The 28-stage runner doesn't
> need them.

## A.4. Point pyrfc at the bundled SAP NW RFC SDK

The SDK is committed under `sapnwrfc/` — no SAP Service Marketplace download required.

```powershell
$env:SAPNWRFC_HOME = "$PWD\sapnwrfc"
[Environment]::SetEnvironmentVariable("SAPNWRFC_HOME", $env:SAPNWRFC_HOME, "User")
```

## A.5. Update `connections.json` with the **real** S/4HANA target

The target block today is a dummy placeholder (`vhcals4hci.dummy.nodomain`). Fix it:

```powershell
# Easiest: use the UI
python api_server.py     # http://localhost:8001 → Connections → "Lift-and-Shift Target S/4"
```

Fill in (replace `<S4_IP>`, `<i-...>` with your values):

| Field | Value |
|---|---|
| `target_ashost` | `<S4_IP>` |
| `target_sysnr` | `00` |
| `target_client` | `100` |
| `target_user` | `DDIC` (read-only — runner never writes via this account) |
| `mc_base_url` | `https://<S4_IP>:44300/sap/opu/odata/sap/CA_DATA_MIGRATION_SRV` |
| `idoc_endpoint` | `https://<S4_IP>:44300/sap/bc/idoc_xml` |
| `idoc_partner` | `M4H_LAPTOP_ECC` |
| `idoc_partner_type` | `LS` |
| `transport_host_instance_id` | `<i-0abc123>` (S/4 EC2 instance id; leave blank if not on EC2) |

Or edit `connections.json` directly using the schema in `LIFT-AND-SHIFT-SETUP.md §5`.

## A.6. Set the per-session env vars

**Run these every time you open a new PowerShell.** Or persist them via
`[Environment]::SetEnvironmentVariable(...,"User")`.

```powershell
$env:M4H_ECC_PASSWD     = "<password for sapuser / M4H_RFC on the laptop ECC>"
$env:M4H_TARGET_PASSWD  = "<S/4 master password>"
$env:M4H_TARGET_MODE    = "basis_handover_only"     # CAL/already-provisioned S/4
$env:SAPNWRFC_HOME      = "$PWD\sapnwrfc"
$env:ECC_CLIENT         = "800"
```

## A.7. Pre-flight smoke (no SAP, no AWS — proves the runner)

```powershell
.\.venv\Scripts\Activate.ps1

# 1) Dry-run all 28 stages — verifies every handler imports
python run_local_lift_and_shift.py --dry-run --run-id smoke-001

# 2) Run two stages that don't touch SAP (validate shim + filesystem staging)
python run_local_lift_and_shift.py --only stage3 --run-id smoke-001
python run_local_lift_and_shift.py --only stage4 --run-id smoke-001

# 3) Confirm artifacts landed
Get-ChildItem local-staging\m4h-local\runs\smoke-001 -Recurse | Select-Object FullName
```

Expected: both stages print `status=success`. You see
`local-staging\m4h-local\runs\smoke-001\target-provisioner\manifest.json`.

## A.8. Live RFC smoke (proves ECC connectivity)

```powershell
python -c "from real_rfc_connection import test_ecc_connection; import json,os; print(json.dumps(test_ecc_connection({'ashost':'192.168.0.5','sysnr':'41','client':'800','user':'sapuser','passwd':os.environ['M4H_ECC_PASSWD']}), indent=2))"
```

Expected: `"status": "success"` with a system info block.

## A.9. Live RFC smoke (proves S/4HANA connectivity)

```powershell
python -c "from pyrfc import Connection; c=Connection(ashost='<S4_IP>',sysnr='00',client='100',user='DDIC',passwd='$env:M4H_TARGET_PASSWD'); print(c.call('RFC_PING'))"
```

Expected: `{}`. Anything else (timeout, auth fail) — fix before Part B.

**Pre-flight complete when A.7 + A.8 + A.9 all pass.**

---

# Part B — Local end-to-end migration (28 stages, 3 manual gates)

> **What this does:** the 28 Lambda handlers run **in-process** on your laptop via
> `run_local_lift_and_shift.py`. `local_aws_shim.py` emulates AWS Secrets Manager / S3 /
> DynamoDB / SSM against `./local-staging/`. The pipeline **only writes to S/4HANA
> through SAP-shipped tools** (CTS+/tp, Migration Cockpit, LTMOM, IDoc inbound) —
> support is preserved.

## B.0. Decide your run-id and stick with it

```powershell
$RUNID = "RUN-$(Get-Date -Format yyyyMMdd-HHmm)"
echo "Run id: $RUNID"
```

All artifacts will land under `local-staging\m4h-local\runs\$RUNID\`.

## B.1. PHASE 0 — ASSESS (~20–40 min)

```powershell
python run_local_lift_and_shift.py --from-stage stage1 --through stage3 `
    --run-id $RUNID --ecc-host 192.168.0.5
```

Stages run:
- **stage1** `discovery-engine` — reads DD02L/DD03L/REPOSRC/TFDIR/T000/T001/USR02, emits inventory.
- **stage2** `sizing-advisor` — ST03N + DBA stats → HANA sizing recommendation.
- **stage3** `object-router` — DAG of migration objects per lane (MC / LTMOM / IDoc / Skip).

**Pause point:** open `local-staging\m4h-local\runs\$RUNID\object-router\routing.json`
and eyeball lane assignments. Edit + re-upload if anything mis-routed.

## B.2. PHASE 1 — PROVISION (~30 min)

```powershell
python run_local_lift_and_shift.py --from-stage stage4 --through stage5 --run-id $RUNID `
    --target-host <S4_IP>
```

- **stage4** `target-provisioner` (mode=`basis_handover_only`) — no-op; CAL provisioned.
- **gate1** auto-approved in local mode.
- **stage5** `basis-validator` — 5 checks against S/4 (SCC4, STMS, ICM endpoints, HANA/ABAP versions).

**Acceptance:** 5 green checks. If any fail, fix per `LIFT-AND-SHIFT-RUNBOOK.md` §
"Gate 1" and re-run stage5.

## B.3. PHASE 2 — CODE (~1–2 hr)

```powershell
python run_local_lift_and_shift.py --from-stage stage6 --through stage9c --run-id $RUNID
```

- **stage6** extract Z* programs/includes/classes/FMs/DDIC from ECC.
- **stage7** AST + GenAI remediation (`M4H_BEDROCK_ENABLED=1` to enable Claude rewrites; otherwise deterministic AST fixes only).
- **stage8** package remediated objects into a CTS+ transport (cofile `K…` + data file `R…`).
- **stage9a** copy cofile + data into `/usr/sap/trans/{cofiles,data}/` on target.
- **stage9b** trigger `tp import` (the **first write to S/4**, via SAP-shipped `tp`).
- **stage9c** verify activation status via RFC.

**If SSM is unavailable:** the shim writes `local-staging\_ssm_manual\local-ssm-<id>.sh`
— `scp` it to the S/4 host and run by hand. Or do STMS → Import Queue manually, then:

```powershell
New-Item local-staging\m4h-local\runs\$RUNID\transports\code\imported.flag -Force
```

**Pause point:** open the verifier report. Any Z-program syntax errors → add the pattern
to `lambda/code-analyzer/rules/*.json`, re-run Phase 2 with a new transport.

## B.4. PHASE 3 — CONFIG (~1–2 hr)

```powershell
python run_local_lift_and_shift.py --from-stage stage10 --through stage12c --run-id $RUNID
```

Same pattern as Phase 2 but for customizing tables / BC Sets.

**Watch out for:**
- CAL Fully-Activated Appliance has its **own** customizing pre-loaded — expect conflicts.
  First run: let the appliance win; skip conflicting BC Set entries.
- **BC Set activation (`SCPR20`) is manual via Fiori.** The runner emits a `manual_gate`
  with the BC Set names — activate them in SAP GUI `/nSCPR20`, then resume.

## B.5. PHASE 4 — DATA-PREP (~1–3 hr)

```powershell
python run_local_lift_and_shift.py --from-stage stage13 --through stage15 --run-id $RUNID
```

- **stage13** extract source tables per object (KNA1/KNVV/ADRC, LFA1/LFB1, MARA/MARC/MARD/MBEW, EKKO/EKPO, …).
- **stage14** BP dedup via AWS Entity Resolution **or** local fallback (`$env:M4H_DEDUP_MODE="local"`).
- **stage15** generate per-lane templates (MC XML / LTMOM CSV / IDoc XML).

## B.6. PHASE 5 — DATA-LOAD (parallel, ~2–4 hr small data; days for real volume)

Open **three** PowerShell windows. In each, re-activate venv + re-set §A.6 env vars, then:

```powershell
# Window 1 — MC lane
python run_local_lift_and_shift.py --only stage16 --run-id $RUNID

# Window 2 — LTMOM lane
python run_local_lift_and_shift.py --only stage17 --run-id $RUNID

# Window 3 — IDoc lane
python run_local_lift_and_shift.py --only stage18 --run-id $RUNID
```

**Honest caveats:**
- **MC OData is partial.** Some objects (activations, deferred postings) need a click in Fiori.
  When the orchestrator hits one, it emits `status=manual_gate` with the exact instruction
  ("Open Fiori → Migrate Your Data → project M4H_<run-id> → Customer → Start Production Run").
  Click, return to terminal, press Enter — runner resumes monitoring.
- **LTMOM has no API.** Stage 17 emits a design doc + clicks for a Basis admin. If your
  routing has no LTMOM-lane objects, it's a no-op.
- **IDoc is the genuinely headless lane.** Posts to `https://<S4>:44300/sap/bc/idoc_xml`,
  monitors DOCNUMs via `IDOC_INBOUND_SINGLE` + EDIDC reads.

## B.7. PHASE 6 — VALIDATE (~30 min)

```powershell
python run_local_lift_and_shift.py --from-stage stage19 --through stage21 --run-id $RUNID
```

- **stage19** reconciliation: counts, balance sums, key coverage, sample hash compare.
- **stage20** DITL test script generation from ST03N top-100 t-codes.
- **stage21** 85-check GO-LIVE scorecard.

**⛔ Gate 2 — Pre-Cutover (real human gate):**
Review `scorecard.html`. Get UAT sign-off. Auto-approved in local mode (warning printed).

## B.8. PHASE 7 — CUTOVER (~30 min smoke; 4–12 hr real)

> **Critical ordering:** ECC-lock (stage22) **must** precede delta-extract (stage23).
> The runner enforces this — don't `--only` your way around it.

```powershell
python run_local_lift_and_shift.py --from-stage stage22 --through stage26 --run-id $RUNID
```

- **stage22** ECC lock (SM02 system message + SCC4 client lock + SU10 mass user lock).
- **stage23** delta extract (changes since Phase-4 timestamp, via ERDAT/AEDAT or full re-read).
- **stage24** delta load via MC.
- **stage25** final reconciliation against locked ECC — **binding for go/no-go**.
- **⛔ Gate 3** Final go-live. Auto-approved locally; real run requires business sign-off.
- **stage26** re-point integrations (CPI / PI-PO / custom RFC destinations) from ECC → S/4.

## B.9. PHASE 8 — RUN

```powershell
python run_local_lift_and_shift.py --only stage27 --run-id $RUNID
```

Generates `local-staging\m4h-local\runs\$RUNID\report\migration-report.pdf` —
executive summary combining discovery, scorecard, recon, test results, transport list, etc.

## B.10. Rollback (if anything goes wrong **before** gate 3)

```powershell
python -c "from importlib import import_module; m=import_module('rollback-manager.handler'.replace('-','_')); print(m.lambda_handler({'run_id':'$RUNID','action':'switch_back'},None))"
```

Unlocks ECC, re-points integrations back, tags S/4 as "do not use". **After gate 3 +
business hours, real rollback is a forward-fix project**, not a switch.

---

# Part C — Deploy Migrate4HANA into AWS, then run the pipeline from there

> **When to do this:** after a successful Part B (local) run proves the pipeline against
> your specific ECC + S/4. The AWS deployment runs the **same Lambdas** at scale, with
> Step Functions orchestration, real Secrets Manager, real S3, real DMS — no shim.

## C.1. AWS prerequisites

```powershell
aws --version                  # AWS CLI v2 required
aws sts get-caller-identity    # confirms creds work
terraform -version             # >= 1.5.0
docker --version               # required for the ECS container build
```

You need IAM permissions to create: VPC, Lambda, ECS, ECR, Step Functions, S3, DynamoDB,
Secrets Manager, KMS, IAM roles, CloudWatch, WAF. Admin or a scoped deployer role.

## C.2. Pick environment + region

```powershell
$ENV   = "dev"                           # dev | staging | prod
$REGION = "ap-south-1"                   # match your S/4HANA region
aws configure set default.region $REGION
```

## C.3. Terraform state backend (one-time per AWS account)

Uncomment the `backend "s3" {…}` block in `terraform/environments/$ENV/main.tf`, then:

```powershell
# Bootstrap the state bucket + lock table (run once, ever)
aws s3 mb s3://migrate4hana-tfstate-$ENV --region $REGION
aws s3api put-bucket-versioning --bucket migrate4hana-tfstate-$ENV --versioning-configuration Status=Enabled
aws dynamodb create-table --table-name migrate4hana-tflock --attribute-definitions AttributeName=LockID,AttributeType=S --key-schema AttributeName=LockID,KeyType=HASH --billing-mode PAY_PER_REQUEST --region $REGION
```

## C.4. Fill in `terraform.tfvars`

```powershell
notepad terraform\environments\$ENV\terraform.tfvars
```

Required fields per `variables.tf`: `aws_region`, `environment`, `vpc_cidr`,
`availability_zones`, subnet CIDRs, `ecc_vpn_cidr` (your on-prem CIDR for the
VPN/Tailscale bridge to your laptop ECC — `192.168.0.0/24` if home network).

## C.5. Provision infrastructure

```powershell
cd terraform\environments\$ENV
terraform init
terraform plan -out tfplan
terraform apply tfplan
```

**Expected output:** ~14 modules created. Note these outputs:

```powershell
terraform output -raw ecr_repository_url     # for the ECS image push
terraform output -raw state_machine_arn      # Step Functions ARN
terraform output -raw staging_bucket         # S3 staging bucket name
terraform output -raw secrets_kms_key_arn    # KMS key for secrets
```

## C.6. Push secrets to AWS Secrets Manager

```powershell
# ECC creds
aws secretsmanager create-secret --name m4h/$ENV/ecc/rfc --secret-string (@{
    ashost='192.168.0.5'; sysnr='41'; client='800'; user='sapuser'; passwd=$env:M4H_ECC_PASSWD
} | ConvertTo-Json -Compress)

# S/4 creds
aws secretsmanager create-secret --name m4h/$ENV/s4/rfc --secret-string (@{
    ashost='<S4_IP>'; sysnr='00'; client='100'; user='DDIC'; passwd=$env:M4H_TARGET_PASSWD
} | ConvertTo-Json -Compress)
```

Repeat for `m4h/$ENV/mc/odata`, `m4h/$ENV/cts/host`, `m4h/$ENV/idoc/partner` —
schema in `STATUS.md §4`.

## C.7. Build + push the ECS worker image (stages 1, 5, 12, 12A)

```powershell
$ECR = terraform output -raw ecr_repository_url
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ECR

cd ..\..\..                                  # back to repo root
docker build -f ecs\Dockerfile -t migrate4hana-worker:latest .
docker tag migrate4hana-worker:latest "${ECR}:latest"
docker push "${ECR}:latest"
```

The Terraform task definition uses `lifecycle { ignore_changes = [container_image] }`
— the placeholder `alpine:latest` image is replaced once the real image lands in ECR.

## C.8. Package + deploy Lambdas

```powershell
# scripts/deploy.sh is bash; from PowerShell, run it via WSL or Git Bash:
bash scripts/deploy.sh
```

This: (a) pip-installs deps into each `lambda/<name>/` dir, (b) builds the React
frontend, (c) `terraform plan` + `terraform apply` to deploy the Lambda code.

**Alternative (CI/CD):** push to `aws-lift-and-shift` branch — `.github/workflows/deploy.yml`
runs the same flow via OIDC federation (no static AWS keys needed).

## C.9. Verify the deployment

```powershell
$SM = terraform output -raw state_machine_arn

aws stepfunctions describe-state-machine --state-machine-arn $SM --query 'status'
# Expected: "ACTIVE"

aws lambda list-functions --query "Functions[?starts_with(FunctionName,'m4h-')].FunctionName" --output table
# Expected: ~14 lift-and-shift lambdas listed
```

## C.10. Trigger the pipeline from AWS

Smoke run (Phase 0 only — assessment):

```powershell
aws stepfunctions start-execution `
  --state-machine-arn $SM `
  --input (@{ mode='assess'; ecc_client='800'; run_id="aws-$(Get-Date -Format yyyyMMdd-HHmm)" } | ConvertTo-Json -Compress)
```

Full migration (all 28 stages, 3 manual gates):

```powershell
aws stepfunctions start-execution `
  --state-machine-arn $SM `
  --input (@{ mode='full'; ecc_client='800'; execute=$true; run_id="aws-$(Get-Date -Format yyyyMMdd-HHmm)" } | ConvertTo-Json -Compress)
```

## C.11. Monitor execution

```powershell
$EXEC_ARN = "<paste arn from start-execution output>"

# State Machine progress
aws stepfunctions describe-execution --execution-arn $EXEC_ARN --query 'status'

# Live Lambda logs
aws logs tail /aws/lambda/m4h-discovery-engine --follow

# Manual gates (DynamoDB)
aws dynamodb scan --table-name "m4h-gates-$ENV" --query 'Items[?gate_status.S==`pending`]'
```

**Web UI:** browse to the ALB DNS name from `terraform output alb_dns_name`. The Pipeline
page shows real-time progress via the WebSocket telemetry channel.

## C.12. Approve manual gates

When `gate1` / `gate2` / `gate3` fire, an SNS email is sent and the entry in
`m4h-gates-$ENV` flips to `pending`. Approve via:

```powershell
aws dynamodb update-item `
  --table-name "m4h-gates-$ENV" `
  --key (@{ run_id=@{ S=$RUNID }; gate=@{ S='gate2' } } | ConvertTo-Json -Compress) `
  --update-expression "SET gate_status = :s, approver = :a, approved_at = :t" `
  --expression-attribute-values (@{ ':s'=@{ S='approved' }; ':a'=@{ S='choudary1231@gmail.com' }; ':t'=@{ S=(Get-Date -Format o) } } | ConvertTo-Json -Compress)
```

Or click **Approve** in the **Gates** page of the UI.

## C.13. Cost-control reminders

- **CAL S/4 EC2** is ~$8/hr while running. Suspend it from the CAL Web UI between phases.
- **DMS replication instance** (only used in Phase 5/7 delta) — stop when idle.
- **NAT Gateway + VPC endpoints** are 24/7 (~$50/mo); leave them up while the project is active.
- For dev/test, `terraform destroy` in `environments/dev` removes everything except the
  state bucket and lock table.

---

# Troubleshooting quick reference

| Symptom | Most likely cause | Fix |
|---|---|---|
| `pyrfc.RFCError: Connection failed` | ECC down or `M4H_ECC_PASSWD` wrong | SAP GUI to confirm; re-set env var |
| `RFC_READ_TABLE: AUTHORIZATION FAILURE` | RFC user missing `S_TABU_DIS` | SU01 → add `SAP_BC_RFC_READ_ONLY` + `S_TABU_DIS` |
| `MC OData returns 401` | `mc_user` lacks `/IWFND/RT_GW_USER` role | Use `DDIC` for first run, then create scoped user |
| `Transport import RC=12` | Pre-req object missing on target | Add pattern to `lambda/code-analyzer/rules/*.json`, rebuild from stage 6 |
| `IDoc status 51 — Application error` | Partner profile (`WE20`) doesn't accept the type | Add inbound parameter on target, re-post via `BD87` |
| `BC Set activation failed` | Customizing key already exists with different value | Decide who wins; first run let the CAL appliance win |
| `ModuleNotFoundError: pyrfc` | SDK env var not set | `$env:SAPNWRFC_HOME = "$PWD\sapnwrfc"`; reinstall pyrfc |
| `[local-shim] active. staging=…` everywhere | Normal in local mode | To run against real AWS: `$env:M4H_LOCAL_MODE="0"` |
| `Stage 27 PDF says skipped in local mode` | No upstream JSON yet — stub used | Real PDF lands once stages 1–26 produce artifacts |
| Want a fresh start | Stale artifacts | New `--run-id` (old run kept under `local-staging\…\runs\<old-id>\`); or `Remove-Item local-staging -Recurse -Force` |

Full troubleshooting appendix: `LIFT-AND-SHIFT-RUNBOOK.md` "Troubleshooting appendix" section.

---

# What "done" looks like

**Local (Part B):**
- All 28 stages report `status=success`
- `local-staging\m4h-local\runs\$RUNID\report\migration-report.pdf` exists and opens
- Stage 21 scorecard shows Grade A or B
- Stage 25 final recon shows source == target counts within tolerance

**AWS (Part C):**
- Step Functions execution status: `SUCCEEDED`
- All 3 manual gates approved with audit trail in `m4h-gates-$ENV`
- Migration report PDF in S3: `s3://<staging_bucket>/runs/<run-id>/report/`
- CloudWatch shows no `ERROR` lines in any lambda log group
- Business signs off on UAT

At that point your laptop ECC is locked (read-only), your S/4HANA holds the migrated
data/code/config, and every change on S/4 was made through SAP-shipped tools — SAP
support is fully preserved.
