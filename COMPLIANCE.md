# Migrate4HANA Compliance & Governance Posture

> This document maps Migrate4HANA's production governance controls to common
> regulatory regimes (SOX, SOC 2, GDPR, GxP, ISO 27001). Each control names the
> exact terraform resource or runtime artifact that implements it, the regime
> requirements it satisfies, and how an auditor can verify it.

**Last reviewed:** 2026-06-07
**Maintainer:** Migrate4HANA engineering
**Applicability:** `prod` environment by default; `dev`/`staging` may override individual toggles for cost or iteration speed (documented per control).

---

## 1. Audit logging & retention

### 1.1 CloudTrail — comprehensive API audit

**Control.** All AWS API calls in the Migrate4HANA account are logged via CloudTrail with log-file validation enabled. Lambda invocations, S3 object-level access on the staging bucket, and IAM/Secrets Manager events are all captured. Logs flow to (a) the WORM-protected `audit-logs` S3 bucket and (b) a CloudWatch Logs group for real-time metric filters & alarms.

**Where it lives.**
- `terraform/modules/audit/main.tf` — `aws_cloudtrail.migration_audit`
- `terraform/modules/audit/main.tf` — `aws_cloudwatch_log_group.audit` (CW Logs forwarder, 365 days)
- Metric filters: `unauthorized_api_calls`, `secrets_access`, `iam_changes`, `pipeline_executions`
- Alarms: `unauthorized_api_calls` (> 5 / 5 min), `iam_changes` (> 0 / 5 min — any IAM mutation pages on call)

**Satisfies.**
- **SOX 404** — IT general controls / change management evidence
- **SOC 2 CC6.1 / CC7.2** — logical access monitoring + system monitoring
- **GDPR Art. 32** — accountability (demonstrate controls)
- **ISO 27001 A.12.4.1** — event logging

**How to verify.**
```bash
aws cloudtrail describe-trails --region us-east-1 \
    --trail-name-list migrate4hana-audit-prod
aws cloudtrail get-trail-status --name migrate4hana-audit-prod
aws cloudwatch describe-alarms \
    --alarm-name-prefix migrate4hana-
```

### 1.2 S3 Object Lock — WORM retention on audit logs

**Control.** The `audit-logs` bucket uses S3 Object Lock in GOVERNANCE mode with a default retention of 2555 days (~7 years). Objects cannot be deleted or modified within the retention period, even by an IAM principal with `s3:DeleteObject` — only an explicit `s3:BypassGovernanceRetention` call can override, and that call is itself logged by CloudTrail.

**Where it lives.**
- `terraform/modules/audit/main.tf`
  - `aws_s3_bucket.audit_logs` — `object_lock_enabled = var.object_lock_enabled` (creation-time)
  - `aws_s3_bucket_object_lock_configuration.audit_logs` — gated by the same toggle, `mode = "GOVERNANCE"`, `days = var.audit_retention_days`

**Toggleability.** `var.object_lock_enabled` (default `true`). Dev/staging may set `object_lock_enabled = false` in `terraform.tfvars` to allow `terraform destroy` cycles. **NOT recommended in prod**; flipping false on an existing bucket triggers replacement.

**Satisfies.**
- **SOX 802** — 7-year retention of accounting-control records
- **SEC Rule 17a-4** — WORM media for financial records
- **SOC 2 CC7.4** — system records integrity

**How to verify.**
```bash
aws s3api get-bucket-versioning --bucket migrate4hana-audit-logs-prod-<acct>
aws s3api get-object-lock-configuration --bucket migrate4hana-audit-logs-prod-<acct>
# Expect: ObjectLockConfiguration.Rule.DefaultRetention.Mode = GOVERNANCE, Days = 2555
```

### 1.3 Lifecycle — IA → Glacier → expire

**Control.** Audit-log objects transition:
- Day 0–90: S3 STANDARD
- Day 91–365: S3 STANDARD_IA (cost optimization)
- Day 366–retention end: S3 GLACIER
- Day `audit_retention_days` (default 2555): expired

**Where it lives.** `terraform/modules/audit/main.tf` — `aws_s3_bucket_lifecycle_configuration.audit_logs`

**Toggleability.** `var.audit_retention_days` per environment. GxP and certain SOC 2 reports require longer windows (10+ years); set in `terraform.tfvars`.

### 1.4 Hash-chained ledger — application-level audit

**Control.** Every record write through `UnifiedLoader` produces an audit entry in the `migrate4hana-audit-ledger-prod` DynamoDB table. Entries form a SHA-256 hash chain so tampering with any entry breaks all subsequent hashes — a stronger property than what S3 versioning + Object Lock alone provide.

**Where it lives.**
- Table: `terraform/environments/prod/main.tf` — `aws_dynamodb_table.audit_ledger`
- Writer: `lambda/utils/audit_chain.py` (HashChainLedger)
- Verification: `lambda/utils/audit_chain_verifier.py`

**Satisfies.**
- **SOX** — application-level evidence of every data mutation
- **SOC 2 CC7.4** — system records integrity (defense-in-depth alongside S3 Object Lock)

---

## 2. Encryption

### 2.1 In transit

**Control.** All AWS service calls go over TLS 1.2+. Internal SAP RFC connections from Lambda → SAP go over the SAP-encrypted CPIC protocol (Unicode kernel ≥ 7.42).

**Where it lives.** AWS endpoint defaults; no explicit terraform required. SAP encryption is on by the kernel default.

### 2.2 At rest — S3 buckets

| Bucket | SSE | Notes |
|---|---|---|
| `migrate4hana-staging-prod` | SSE-KMS (CMK) | Migration data; KMS key from `evidence-ledger` module |
| `migrate4hana-evidence-bucket` | SSE-KMS (CMK) | Read-back artifacts; same CMK |
| `migrate4hana-audit-logs-prod-<acct>` | SSE-KMS (AWS-managed by default; togglable to CMK via `var.audit_kms_key_arn`) | Object Lock + 7-year retention |
| `migrate4hana-mapping-prod-<acct>` | SSE-KMS | Value-map matrices |

**Where it lives.**
- CMK: `terraform/modules/evidence-ledger/main.tf` — `aws_kms_key.m4h` (key rotation **enabled**, deletion window 30 days)
- Audit bucket SSE: `terraform/modules/audit/main.tf` — `aws_s3_bucket_server_side_encryption_configuration.audit_logs` (uses `var.kms_key_arn` when set)

### 2.3 At rest — DynamoDB

All migration-state tables (`key_map`, `audit_ledger`, `gates`, `recon_tolerance`) have `server_side_encryption.enabled = true` (AWS-managed by default; can be promoted to CMK in a follow-up by adding `kms_master_key_arn`).

### 2.4 At rest — Secrets Manager

Every secret (`sap-credentials`, `s4hana-credentials`, `gate-secret`, `anthropic-api-key`) is encrypted with SSE-KMS. Each secret has `recovery_window_in_days = 0` per `[[terraform-destroyable-conventions]]` so a recreate doesn't leave a 30-day ghost.

### 2.5 KMS key rotation

**Control.** The Migrate4HANA CMK rotates annually (AWS-managed rotation, `enable_key_rotation = true`).

**Where it lives.** `terraform/modules/evidence-ledger/main.tf` — `aws_kms_key.m4h`

**Satisfies.**
- **SOC 2 CC6.7** — cryptographic key management
- **PCI DSS 3.6** — annual key rotation (if scope applies)
- **NIST SP 800-57** — periodic rekeying

**Verify.**
```bash
aws kms get-key-rotation-status --key-id alias/migrate4hana-prod
# Expect: KeyRotationEnabled = true
```

---

## 3. Access control

### 3.1 Network isolation

- Lambda functions run inside a VPC (`module.vpc.private_subnet_ids`), egress only via NAT EIP.
- No Lambda has a public IP.
- Outbound calls allowed: AWS service endpoints (via VPC Endpoints where available — STS, KMS, Secrets Manager, S3, DynamoDB), api.anthropic.com (via NAT), and explicitly-permitted SAP gateway IPs.

**Where it lives.**
- `terraform/modules/vpc/` — VPC + subnets + NAT
- `terraform/modules/vpc-endpoints/` — interface + gateway endpoints
- Lambda VPC config: `terraform/modules/lambda/main.tf` per function

### 3.2 IAM — current state (shared Lambda role)

**Control.** All Migrate4HANA Lambdas currently share the role `migrate4hana-lambda-prod`. The role's inline policy follows least-privilege within the migrate4hana resource scope:

- DynamoDB: limited to `arn:aws:dynamodb:*:*:table/m4h-*` and `migrate4hana-*` (+ indexes)
- Secrets Manager: limited to listed secret ARNs (sap-credentials, s4hana-credentials, anthropic-api-key)
- S3: limited to the staging bucket ARN
- Lambda invoke: limited to `arn:aws:lambda:*:*:function:migrate4hana-*`
- Step Functions: limited to `arn:aws:states:*:*:stateMachine:migrate4hana-*`
- SSM Run Command: tag-conditioned to instances tagged as Migrate4HANA SAP hosts

**Where it lives.** `terraform/modules/lambda/main.tf` — `aws_iam_role.lambda` + `aws_iam_role_policy.lambda`

### 3.3 IAM — known gap (per-function split, deferred)

**Gap.** Sharing a role across ~40 Lambdas violates strict least-privilege (a code-execution bug in one function gives that bug the union of all functions' permissions).

**Mitigation in place today.** All Lambdas in the role are migrate4hana-owned code; the role grants no privileges outside the migrate4hana resource namespace. Blast radius is bounded to the project's own AWS resources.

**Planned remediation (P1).** Split into per-function roles. Migration plan:

1. **Phase A (1-2 days).** Generate a baseline of "actually used IAM actions" per Lambda by enabling IAM Access Analyzer on the shared role for 7 days.
2. **Phase B (2-3 days).** Refactor `terraform/modules/lambda/main.tf` so each `lambda_functions` entry gets its own `aws_iam_role` + scoped inline policy generated from the Access Analyzer baseline.
3. **Phase C (1 day).** Roll out function-by-function, verify each via the existing wave1 + persistent_key_map + transformation_ruleset tests.
4. **Phase D (1 day).** Delete the shared role and revoke its policies.

**Why not tonight.** This is a 5–7 person-day refactor that requires careful per-function permission elicitation. Doing it in a single session risks dropping a privilege a Lambda actually needs and breaking production. Tracked as a follow-up.

### 3.4 S3 bucket public-access block

All Migrate4HANA buckets have `aws_s3_bucket_public_access_block` set with all four flags `true`: `block_public_acls`, `block_public_policy`, `ignore_public_acls`, `restrict_public_buckets`. No public read or write is possible regardless of bucket policy intent.

### 3.5 Secrets Manager — rotation policy

Secrets are not on automatic rotation today (`sap-credentials` and `s4hana-credentials` are tied to SAP user passwords that need coordinated rotation with the SAP system). **Manual quarterly rotation procedure** documented separately.

`anthropic-api-key` and `gate-secret` are good candidates for automated rotation; both will be enrolled in `aws_secretsmanager_secret_rotation` in the per-function IAM phase above.

---

## 4. Data integrity & reconciliation

### 4.1 Reconciliation engine

After every migration object load, `lambda/reconciliation-engine/handler.py` reads back from S/4HANA and compares against the source extract. Discrepancies are flagged as `RECONCILIATION_FAILED` and dead-lettered; the run cannot reach `success` status until reconciliation passes.

**Where it lives.** `lambda/reconciliation-engine/handler.py` + `lambda/utils/reconciler.py`

### 4.2 Hash-chain verification

A standalone verifier (`lambda/utils/audit_chain_verifier.py`) recomputes every audit-ledger entry's hash and confirms the chain is unbroken. Run on demand for audit evidence:
```bash
python lambda/utils/audit_chain_verifier.py --run-id <RUN>
```

### 4.3 Data quality gates (F4)

The `TransformationEngine` (see `VALUE_MAPPING_GUIDE.md`) enforces field-level data-quality gates before any BAPI call. Rejected records become dead-letter entries with explicit reasons — no silent data loss possible.

---

## 5. Change management

### 5.1 Infrastructure-as-code

Every AWS resource is declared in Terraform under `terraform/`. No manual console changes are expected to be drift-free; any drift is detectable via `terraform plan`.

### 5.2 CI gates

- All code changes pass the `tests/test_fixes_wave1.py` regression suite + the F1/F4 unit tests (37 total tonight).
- Code remediation (ABAP via Claude) is gated by SAP's ATC quality check before any transport ships.
- Pillar 3 — Spine approval gates require HMAC-signed approval (Secrets Manager `gate-secret`) before sensitive stages execute.

### 5.3 Deployment

- Lambda code: `deploy-data-migrator.ps1` + `deploy-orchestrator.ps1` (versioned via `aws lambda update-function-code`; the previous version is retained and can be rolled back via `update-function-code --revision-id`).
- Terraform infra: `terraform apply` with state in S3 (or local during initial bring-up).

---

## 6. Privacy (GDPR)

### 6.1 PII identification

The pseudonymizer module (`lambda/utils/pseudonymizer.py`) scrubs identifying fields (name, email, phone, address, SSN-equivalent) before any payload leaves the VPC for LLM remediation (Claude API).

**Where it lives.** `lambda/utils/pseudonymizer.py`; invoked from `lambda/code-analyzer/handler.py`.

### 6.2 Data residency

All Migrate4HANA AWS resources live in `us-east-1` by default. For EU customer data, deploy a separate environment with `aws_region = "eu-west-1"` (or similar) in `terraform.tfvars`; the architecture is region-clean.

### 6.3 Right to erasure

Customer-specific data lives in the staging bucket under `runs/<run_id>/`. Object-level deletion is possible (no Object Lock on staging — only audit-logs is WORM). A documented `delete-customer-data` runbook (TODO) will codify the per-run object deletion workflow.

---

## 7. Environment toggles summary

| Variable | Default | Description |
|---|---|---|
| `object_lock_enabled` | `true` | Bucket-level WORM enable. False for fast-tfdestroy dev sandboxes. |
| `audit_retention_days` | `2555` (7y) | Per-regime override (GxP, SEC 17a-4, etc.) |
| `audit_kms_key_arn` | `""` (AWS-managed) | Set to CMK ARN for explicit rotation visibility. |
| `enable_vpn_gateway` | `true` (prod), `false` (dev) | VPN to on-prem ECC. |
| `s4_public_ip` | `""` | CAL S/4 IP (drifts; sync via `scripts/sync-ips.ps1`). |
| `cal_ecc_public_ip` | `""` | CAL ECC IP (drifts). |
| `llm_mode` | `"cloud"` | LLM routing: `cloud` / `local` / `dual`. |

---

## 8. Auditor onboarding checklist

If you are an auditor or compliance engineer reviewing Migrate4HANA, the fastest path to evidence is:

1. **Read this document.** Each control names the exact code location.
2. **Run `terraform plan`** in `terraform/environments/prod/` and confirm no drift.
3. **Sample CloudTrail logs** for the last 30 days:
   ```bash
   aws logs filter-log-events \
       --log-group-name /migrate4hana/audit/prod \
       --start-time $(date -d '30 days ago' +%s)000 \
       --max-items 50
   ```
4. **Verify Object Lock** on the audit-logs bucket (§1.2).
5. **Verify KMS rotation** (§2.5).
6. **Verify hash-chain integrity** (§4.2).
7. **Review the IAM gap** (§3.3) and confirm the planned remediation timeline.

Outstanding items are flagged in §3.3 (per-function IAM split), §3.5 (automated secrets rotation for low-risk secrets), and §6.3 (right-to-erasure runbook).

---

## 9. Change log

| Date | Change | Rationale |
|---|---|---|
| 2026-06-07 | Initial publication. F6 governance toggles added: `object_lock_enabled`, `audit_retention_days`, `audit_kms_key_arn`. | First codified SOX/SOC2 posture document; toggles enable dev/staging cost savings without compromising prod defaults. |
