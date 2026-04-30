# Migrate4HANA — Status

## Wave 4 — Gap closure (committed on `aws-lift-and-shift`)

| Wave | Deliverable | Status |
|---|---|---|
| A | Terraform staging + prod replicated to match dev (14 lambdas, gates table, target_system module) | ✅ |
| B | `Gates.jsx` manual-approval UI + route + nav | ✅ |
| C | Connections page target S/4 card + `/api/connections/lift-and-shift-target` endpoint | ✅ |
| D | `test_manual_gate.py` (3/3) + `test_orchestrators.py` (13/13) | ✅ |
| — | Frontend MUI deps added; `vite build` clean (3613 modules) | ✅ |

**Test results:** imports 31/31 · no-direct-writes 0 violations · manual-gate 3/3 · orchestrators 13/13.

**One item remains BLOCKED, not pending:** `gap-orchestrator-polish` — end-to-end run needs a real SAP sandbox (ECC + greenfield S/4HANA target with CTS+, MC OData, IDoc inbound, etc.). That's an environmental dependency, not code work.

Codebase is now feature-complete for v1 lift-and-shift; remaining work is integration testing in a real SAP landscape.

---

## What's needed to test Migrate4HANA comprehensively

The code is done. End-to-end validation now needs **environment, SAP systems, credentials, and sample workloads**. Group them as below — anything you can't supply means that lane stays "code-tested only".

### 1. AWS environment
- AWS account with admin (or scoped) IAM for terraform apply
- S3 bucket + DynamoDB table for terraform remote state (per env: dev/staging/prod)
- VPC with private subnets + NAT (or Transit Gateway) reachable from SAP hosts
- Route 53 private zone (optional, for friendly hostnames)
- ACM cert if you want HTTPS on the api_server / frontend
- Tools on the operator workstation:
  - `terraform >= 1.5`
  - `aws` CLI v2 (configured via SSO or access keys)
  - `python 3.11`, `pip`, `node 20`, `npm`
  - `docker` (only if you containerise the api_server)

### 2. Source SAP ECC system (the "from" side)
- ECC 6.0 EHP7+ on any DB (HANA/Oracle/DB2/MSSQL) — reachable from the AWS VPC
- Service user (`M4H_RFC`) with: `S_RFC`, `S_TABU_DIS`, `S_BTCH_*`, `S_TRANSPRT`, `S_DATASET`, `S_DEVELOP` (display)
- Transport directory (`/usr/sap/trans`) accessible to the SSM-managed orchestrator host
- SAP host with **SSM Agent** installed (Linux preferred) so Lambda → SSM → `tp` / `R3trans` works
- SAP kernel + `tp` / `R3trans` binaries on PATH for that host

### 3. Target greenfield S/4HANA system (the "to" side)
- S/4HANA 2022/2023 on HANA — installed and patched (this tool does NOT install S/4)
- Same RFC service user pattern, plus access to:
  - **Migration Cockpit** (`LTMC` / Fiori "Migrate Your Data") with OData endpoint enabled
  - **LTMOM** (`LTMOM` tcode) for custom mapping objects
  - **CTS+** target client for transport import
  - **IDoc inbound** partner profiles (for the IDoc lane)
- BC sets + simplification list relevant to your S/4 release
- SSM-managed S/4 host (same as ECC side) for `tp import`, BC set activation

### 4. Credentials & secrets (stored in AWS Secrets Manager)
- `m4h/ecc/rfc` — `{ ashost, sysnr, client, user, passwd, lang }`
- `m4h/s4/rfc` — same shape for S/4
- `m4h/mc/odata` — `{ base_url, user, passwd }` for Migration Cockpit OData
- `m4h/cts/host` — SSM target id + transport user
- `m4h/idoc/partner` — partner profile + port
- (optional) `m4h/db/*` for direct delta extracts

### 5. SAP-shipped binaries / SDKs
- **NW RFC SDK** — already vendored in repo (`nwrfcsdk-windows/`, `nwrfcsdk-linux/`); Lambda layer built from the linux variant
- **SAPCAR**, **SAPGUI** (operator desktop only)
- **`tp` / `R3trans`** on the SSM hosts (ship with NetWeaver kernel)
- **PyRFC** wheel matching Lambda's `python3.11` + `manylinux` (build inside an Amazon Linux 2 container)

### 6. Sample workloads / test fixtures
- 1–2 **transport requests** (workbench + customising) exported from ECC for the transport lane
- 1 **MC migration project** (e.g., GL accounts or business partners) with ~100–1k rows
- 1 **LTMOM custom object** with a non-trivial field mapping
- 1 **IDoc type** (e.g., `MATMAS05`, `DEBMAS07`) with sample payloads
- 1 **BC set** scoped to a small config area
- 1 **delta-extract** scenario (table + date column)

### 7. Network / connectivity
- Bidirectional reachability: Lambda (in VPC) → ECC RFC (33xx), S/4 RFC (33xx), MC OData (44300/HTTPS), CTS+ (3299/3300), SSM endpoints
- VPC endpoints for `ssm`, `ssmmessages`, `ec2messages`, `secretsmanager`, `s3`, `dynamodb`, `logs`, `sns`
- Security groups whitelisting SAP gateway ports

### 8. Observability + approvals
- SNS topic + at least 2 subscribers (email/Slack) for manual-gate notifications
- CloudWatch log groups (auto-created by the lambda module)
- SES or Slack webhook if you want richer gate notifications
- Operator accounts in the frontend with their name set in the Gates page (persisted to localStorage)

### 9. Pre-flight smoke checklist (before first real run)
1. `terraform plan` on `dev` → 0 errors
2. `terraform apply` → all 14 lambdas, gates table, step function deploy
3. `tests/test_imports.py` + `tests/test_no_direct_writes.py` + `tests/test_manual_gate.py` + `tests/test_orchestrators.py` green in CI
4. `npm run build` in `frontend/` clean (already verified locally)
5. Connections page: save ECC + S/4 + MC + LTMOM + IDoc + CTS+ entries; secrets land in Secrets Manager
6. Trigger pipeline with a single MC object → walk through all manual gates → confirm DynamoDB rows + SNS emails
7. Repeat for transport lane and IDoc lane
8. Run rollback-manager against the same execution to confirm idempotency

### 10. What you *don't* need
- ❌ SUM / DMO licences — lift-and-shift bypasses them by design
- ❌ SAP Solution Manager (nice-to-have, not required)
- ❌ Direct DB access on S/4 — every write goes through SAP-shipped tools (this preserves SAP support)

> **Rule of thumb:** anything that talks to SAP must go through MC, LTMOM, IDoc, CTS+, or RFC-with-standard-BAPIs. Custom SQL writes against S/4 are blocked by `tests/test_no_direct_writes.py` and will fail CI.
