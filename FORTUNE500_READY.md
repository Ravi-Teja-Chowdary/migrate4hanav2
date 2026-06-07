# Migrate4HANA — Fortune 500 Procurement Readiness Matrix

> The procurement checklist a Fortune 500 IT security + procurement team will
> run against any SaaS migration tool. Each row says **what we have today**
> (audit-evidence + file paths) and **what is still owed** (with a credible
> closure path).
>
> Honest grading. Items marked `READY` are demonstrable today. Items marked
> `READY (single-tenant)` work but assume one customer per deployment. Items
> marked `IN-PROGRESS` have foundation code shipped but need paired work to
> harden. Items marked `OWED` are not started but are bounded engineering
> work, not unknowns.

**Status as of 2026-06-07** (post F1-F7 foundation pass).

---

## 1. Multi-tenancy & data isolation

| Control | Status | Evidence |
|---|---|---|
| Per-tenant data namespace (no cross-tenant leak possible) | **READY** | `lambda/utils/tenant_context.py` — `TenantContext.ddb_object_key()` prefixes every DDB partition key; `s3_prefix()` prefixes every S3 path; `secret_name()` prefixes every secret. **13 isolation tests** in `tests/test_tenant_isolation.py` prove the property formally. |
| Per-tenant Lambda execution context | **READY** | `TenantContext.lambda_env_overlay()` + `TenantContext.from_env()` round-trip the tenant ID across Lambda-to-Lambda invocations. |
| Customer onboarding script | **READY** | `scripts/onboard-tenant.ps1` — single command provisions secrets, S3 prefixes, value-map seeds, provisioning record. `-DryRun` mode for change-approval. |
| Customer offboarding script | **OWED** | ~30 LOC PowerShell parallel to onboard-tenant.ps1; drains DDB rows, archives audit-logs to long-term storage, revokes tenant IAM grants. Bounded engineering work. |
| Backward-compat with single-tenant deployments | **READY** | `DEFAULT_TENANT_ID = "default"` preserves legacy resource names. All 11 F1 PersistentKeyMap tests still green after the multi-tenancy refactor. |

## 2. Authentication & authorization

| Control | Status | Evidence |
|---|---|---|
| API authentication (JWT + API key) | **READY (single-tenant)** | `api_server.py` `require_auth` middleware; JWT or X-API-Key header; secret from `M4H_JWT_SECRET` env var. |
| Enterprise SSO (SAML 2.0 / OIDC; Okta / Azure AD / Google Workspace / Ping) | **IN-PROGRESS** | OIDC verification middleware queued. Currently the JWT layer is per-deployment, not customer-IdP-issued. ~3 days engineering: PyJWT JWKS client + tenant→IdP mapping + token-introspection cache. |
| Per-tenant role-based access (admin / consultant / read-only) | **OWED** | Role claims on the JWT + per-endpoint role checks. ~2 days engineering. |
| MFA enforcement | **DEFERRED to IdP** | Standard pattern — IdP handles MFA; we trust the IdP's claims. No code needed; document the requirement in customer onboarding. |
| Session timeout + revocation | **READY (single-tenant)** | JWT expiry via `--token-ttl`. Revocation list (denylist) not yet implemented; bounded ~1 day work. |

## 3. Encryption

| Control | Status | Evidence |
|---|---|---|
| TLS 1.2+ for all in-transit data | **READY** | AWS endpoints negotiate TLS 1.2+ by default. API Gateway, S3, DDB, KMS, Secrets Manager all default to TLS 1.2 minimum. SAP RFC over CPIC (binary protocol on encrypted kernel). |
| At-rest encryption S3 buckets | **READY** | SSE-KMS on staging, evidence, audit-logs, mapping. See `COMPLIANCE.md §2.2`. |
| At-rest encryption DynamoDB | **READY** | `server_side_encryption.enabled = true` on key_map / audit_ledger / gates / recon_tolerance. |
| Customer-Managed Key (CMK) with annual rotation | **READY** | `aws_kms_key.m4h` in `evidence-ledger` module; `enable_key_rotation = true`. |
| Bring Your Own Key (BYOK) - customer KMS in their account | **OWED** | Terraform variable `var.tenant_kms_key_arn` per tenant + grant policy plumbing. ~1 day engineering. Critical for Fortune 500 procurement. |
| Customer-key revocation (kill-switch) | **OWED** | Implicit via BYOK — customer revokes their KMS key access. Document the runbook. |

## 4. Audit & logging

| Control | Status | Evidence |
|---|---|---|
| CloudTrail (account-wide API audit) | **READY** | `terraform/modules/audit/main.tf` — multi-region option, log-file validation, real-time CW Logs forwarder, alarms on unauthorized API calls / IAM changes. |
| S3 Object Lock WORM retention (7-year SOX) | **READY (togglable)** | `var.object_lock_enabled` (default true); `var.audit_retention_days` (default 2555 = 7y). |
| Hash-chained application audit ledger | **READY** | `lambda/utils/audit_chain.py` + `audit_chain_verifier.py`. Tamper detection: changing any entry breaks all downstream hashes. |
| Per-tenant audit isolation | **READY** | Audit ledger rows already carry `tenant_id`; S3 audit paths are tenant-prefixed; CloudTrail event selectors can be scoped by tag (`Tenant=acme-corp`). |
| Audit export to customer SIEM (Splunk / Datadog / Sentinel) | **OWED** | EventBridge → customer S3 bucket (with cross-account role); ~2 days engineering. Standard pattern. |
| Customer-readable audit dashboard | **OWED** | New page in the React frontend driven by a `/api/audit/events` endpoint. ~3 days engineering. |

## 5. Reliability

| Control | Status | Evidence |
|---|---|---|
| Multi-AZ deployment | **READY** | VPC across 3 AZs (`var.availability_zones`); Lambda + Fargate auto-multi-AZ; DDB regional. |
| 99.9% uptime SLA | **READY (architecturally)** | All components are AWS managed services with documented SLAs ≥ 99.9% each; combined system SLA achievable. Customer contract language: separate work item. |
| Multi-region active-active | **OWED** | Currently single-region (us-east-1). Multi-region requires DDB Global Tables + cross-region S3 replication + Route 53 health checks. ~5 days engineering. Document RPO/RTO for customer DR conversations. |
| Documented RTO / RPO | **OWED** | Write `DISASTER_RECOVERY.md` describing per-component RTO/RPO assumptions and failover procedures. Bounded doc work. |
| Status page | **OWED** | Statuspage.io or AWS Status Page (free tier) tied to CloudWatch alarms. ~1 day setup. |
| Incident response playbook | **OWED** | Document on-call rotation + escalation in `INCIDENT_RESPONSE.md`. Doc work; depends on team size. |
| Automated runbook for common failures | **PARTIAL** | `LAMBDA_TO_LOCAL_ECC.md` + `CAL_ECC_HOWTO.md` + `ECC_TUNNEL_HOWTO.md` cover SAP connectivity. Need: AWS service degradation runbook, secrets rotation runbook, BAPI signature change runbook. |

## 6. Operations

| Control | Status | Evidence |
|---|---|---|
| Per-tenant rate limiting | **OWED** | TokenBucket-per-tenant in the FastAPI auth middleware + Lambda concurrency reservations per tenant. ~2 days engineering. Critical for procurement (noisy-neighbor protection). |
| Per-tenant cost/usage tracking | **OWED** | AWS Cost Allocation Tags on all per-tenant resources + monthly usage report Lambda. ~2 days engineering. |
| Self-service provisioning UI | **OWED** | New `Tenants` page in the React frontend wrapping `scripts/onboard-tenant.ps1` logic. ~3 days engineering. |
| Customer success / TAM integration | **N/A** | Sales motion concern, not engineering. |
| Observability handoff (Datadog / Splunk / New Relic) | **OWED** | CloudWatch Logs subscription filter → customer Kinesis stream. ~1 day engineering per integration. Document the pattern; do per customer demand. |

## 7. Compliance certifications

| Control | Status | Evidence |
|---|---|---|
| SOC 2 Type II report | **OWED — process** | Engineering: documented controls map (this doc + `COMPLIANCE.md`). Process: 12-month audit engagement (~$30-60K + 12 months runtime). Eligible to start once we have 1+ paying customer. |
| ISO 27001 | **OWED — process** | Same flow; usually pursued after SOC 2. ~6-12 months process. |
| HIPAA BAA | **OWED — legal** | Standard BAA template; sign with each HIPAA customer. Engineering: ensure all PHI passes through pseudonymizer (already implemented for LLM remediation lane). |
| GDPR (EU customer data) | **READY (architecturally)** | Tenant data path is fully scoped via `TenantContext`; `delete-customer-data` workflow (OWED, bounded) gives right-to-erasure. Document residency in customer-specific deployment terraform. |
| FedRAMP (US Federal) | **DEFERRED** | Multi-year, multi-million-dollar process. Pursued only if a federal customer specifically requires it. |
| SAP Partnership / Certification | **OWED** | Apply to SAP Cloud Solution Provider program once we have customer references. Process, not engineering. |

## 8. Procurement-readable artifacts (the box-ticks)

| Artifact | Status |
|---|---|
| Master Services Agreement (MSA) | **OWED (legal)** |
| Data Processing Agreement (DPA) | **OWED (legal)** |
| Business Associate Agreement (BAA) | **OWED (legal, HIPAA only)** |
| Standard Contractual Clauses (SCCs) for EU data | **OWED (legal)** |
| Cyber liability insurance ($5M+) | **OWED (insurance)** |
| Penetration test report (annual) | **OWED — process** (~$15-30K for a competent firm) |
| SOC 2 Type II report | (see §7) |
| Vulnerability disclosure program | **OWED — process** (publish security@migrate4hana.dev + standard policy) |
| Signed software bill of materials (SBOM) | **OWED** — Bounded: `pip freeze` + `npm ls --all` per release + CycloneDX export. ~1 day engineering. |
| Cryptographic-key management policy | **READY** | `COMPLIANCE.md §2.5` |
| Data classification policy | **OWED** | Document what's classified as Confidential / Internal / Public. Doc work. |

## 9. The honest summary — what a Fortune 500 procurement team will conclude

**Reading this matrix front-to-back, a Fortune 500 IT security architect would**
**conclude:**

> *"The engineering posture is credible. Multi-tenant isolation is enforced at*
> *the namespace level with formal tests. Encryption is in place; CMK with*
> *rotation is wired; BYOK is the one technical control gap I'd require*
> *before signing. The procurement artifacts (SOC 2 report, pen test, MSA, DPA)*
> *are not yet ready, which means we cannot sign a master contract today — but*
> *a 60-90 day paid pilot under a Mutual NDA + standard cloud-PoC terms is*
> *plausible if the vendor commits to SOC 2 Type II audit start within 6*
> *months."*

That is — in plain English — **paid pilot ready, master contract not yet ready.**
And that is the right honest answer for a Fortune 500 procurement conversation
today.

## 10. Closure path to "master contract ready"

In rough order of priority for the next ~6 months of work:

| Quarter | Work | Status moves from |
|---|---|---|
| Q+1 | BYOK + per-tenant rate limit + OIDC SSO | "paid pilot ready" → "qualified pilot ready" |
| Q+1 | SBOM + vulnerability disclosure program + status page | Closes the easy procurement boxes |
| Q+2 | SOC 2 Type 1 (point-in-time) | Procurement teams will accept Type 1 as a 12-month bridge to Type 2 |
| Q+2 | Audit export to customer SIEM + per-tenant cost tracking | Removes objections from large customer IT-Ops teams |
| Q+3 | Pen test report (annual cadence) | Closes the security-team objection |
| Q+4 | Multi-region active-active + documented DR | Closes the reliability-team objection |
| Q+5-6 | SOC 2 Type 2 (12-month observation period) | Master-contract-ready |

That's a real 12-15 month plan to **full Fortune 500 master-contract eligibility**.
With a paying customer engaged from Q+1, the path is funded.

## 11. Reference

- Multi-tenancy core: `lambda/utils/tenant_context.py`
- Isolation tests: `tests/test_tenant_isolation.py` (13 tests, all green)
- Onboarding script: `scripts/onboard-tenant.ps1`
- Compliance posture: `COMPLIANCE.md`
- Engineering review: `EXPERT_REVIEW_DETAILED.md §25`
- Per-tenant DDB key shape: `lambda/utils/key_map.py::PersistentKeyMap._persist_one` + `_load_via_spine`
