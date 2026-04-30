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

The code is done. End-to-end validation now needs **environment, SAP systems, credentials, and sample workloads**. Each item below is tagged with the AWS resource it consumes so you can map cost and IAM scope.

### 1. AWS environment (operator workstation + control plane)
| Need | AWS resource it consumes |
|---|---|
| Terraform remote state | **S3 bucket** + **DynamoDB table** (per env: dev/staging/prod) |
| Identity for `terraform apply` | **IAM user/role** with admin (or scoped) policy |
| Network plumbing | **VPC**, **private subnets** (≥2 AZs), **NAT Gateway** *or* Transit Gateway |
| DNS (optional) | **Route 53 private hosted zone** |
| TLS for api_server / frontend (optional) | **ACM certificate**, **ALB** |
| Operator desktop tools | none in AWS — local: `terraform≥1.5`, `aws` CLI v2, `python 3.11`, `node 20`, `docker` |

### 2. Source SAP ECC system (the "from" side)
| Need | AWS resource it consumes |
|---|---|
| ECC 6.0 EHP7+ host (any DB) | **EC2** (your choice, BYOL) **or** on-prem reachable via **Site-to-Site VPN** / **Direct Connect** |
| RFC service user + transport access | none |
| Orchestrator command channel | **SSM agent** on the ECC host → **Systems Manager (SSM)** + VPC endpoints (`ssm`, `ssmmessages`, `ec2messages`) |
| Transport directory (`/usr/sap/trans`) | **EBS volume** attached to the ECC host |

### 3. Target greenfield S/4HANA system (the "to" side)
| Need | AWS resource it consumes |
|---|---|
| **S/4HANA 2022/2023 on HANA** (this tool does NOT install S/4) | **EC2** + **EBS** — see SAP CAL free-trial section below |
| Migration Cockpit (LTMC) OData endpoint | none — runs inside the S/4 host |
| LTMOM, CTS+, IDoc inbound | none — runs inside the S/4 host |
| Orchestrator command channel | **SSM agent** on the S/4 host (same VPC endpoints as above) |

### 4. Credentials & secrets
| Secret | AWS resource |
|---|---|
| `m4h/ecc/rfc`, `m4h/s4/rfc`, `m4h/mc/odata`, `m4h/cts/host`, `m4h/idoc/partner` | **AWS Secrets Manager** (one secret per entry) |
| Lambda → Secrets Manager fetch | **VPC endpoint** for `secretsmanager` |

### 5. SAP-shipped binaries / SDKs
| Need | AWS resource |
|---|---|
| NW RFC SDK (vendored linux variant) → Lambda layer | **Lambda layer** stored in **S3** |
| PyRFC wheel built for Amazon Linux 2 + python3.11 | built in **CodeBuild** *or* a one-shot EC2 (or local Docker), uploaded to **S3** |
| `tp` / `R3trans` | none in AWS — already on the SAP hosts |

### 6. Sample workloads / test fixtures (no AWS resources — content only)
- 1–2 **transport requests** (workbench + customising) exported from ECC
- 1 **MC migration project** with ~100–1k rows
- 1 **LTMOM custom object** with a non-trivial mapping
- 1 **IDoc type** (`MATMAS05`, `DEBMAS07`) + sample payloads
- 1 **BC set** scoped to a small config area
- 1 **delta-extract** scenario (table + date column)

### 7. Network / connectivity
| Need | AWS resource |
|---|---|
| Lambda → SAP RFC (33xx), MC OData (44300), CTS+ (3299/3300) | **Lambda in VPC** (ENIs in private subnets) |
| Lambda → AWS APIs without internet | **VPC endpoints**: `ssm`, `ssmmessages`, `ec2messages`, `secretsmanager`, `s3`, `dynamodb`, `logs`, `sns` |
| SAP host firewalling | **Security groups** scoped to SAP gateway ports |
| (optional) on-prem ECC | **Site-to-Site VPN** or **Direct Connect** |

### 8. Observability + approvals
| Need | AWS resource |
|---|---|
| Manual-gate task tokens | **DynamoDB table** (`m4h-gates-<env>`) |
| Lambda + Step Function logs | **CloudWatch Log Groups** |
| Gate notifications | **SNS topic** + subscribers (email / Slack via Lambda) |
| (optional) richer email | **SES** |

### 9. Migrate4HANA control plane (created by terraform)
| Need | AWS resource |
|---|---|
| 14 lift-and-shift lambdas | **Lambda functions** + **Lambda layers** + **IAM execution roles** |
| Pipeline orchestration | **Step Functions state machine** |
| Migration artefacts (transports, logs, runbooks) | **S3 bucket** (versioned, encrypted) |
| Pipeline triggers / schedules | **EventBridge rules** |
| api_server + frontend hosting | **ECS Fargate** *or* **EC2** (your choice) + **ALB**; static frontend can also live on **S3 + CloudFront** |

### 10. Pre-flight smoke checklist
1. `terraform plan` on `dev` → 0 errors
2. `terraform apply` → 14 lambdas, gates table, step function deployed
3. All four test suites green in CI
4. `npm run build` in `frontend/` clean
5. Save all connection entries in Connections page → secrets land in Secrets Manager
6. Trigger pipeline with one MC object → walk all manual gates → confirm DynamoDB rows + SNS emails
7. Repeat for transport lane and IDoc lane
8. Run rollback-manager against the same execution to confirm idempotency

### 11. What you *don't* need
- ❌ SUM / DMO licences — lift-and-shift bypasses them by design
- ❌ SAP Solution Manager (nice-to-have, not required)
- ❌ Direct DB access on S/4 — every write goes through SAP-shipped tools (preserves SAP support)

---

## SAP S/4HANA from SAP CAL (free 30-day trial) — AWS resources

SAP Cloud Appliance Library (CAL) deploys the **"SAP S/4HANA Fully-Activated Appliance"** as a **CloudFormation stack** in *your* AWS account. The SAP license is free for 30 days; **AWS infrastructure cost is on you** (~USD 30–60/day depending on instance choice and uptime — suspend when idle).

| Resource | Typical sizing for the trial appliance |
|---|---|
| **EC2 instance** (S/4 + HANA + Fiori on one host) | 1 × `r5.4xlarge` or `r5.8xlarge` (128–256 GB RAM); CAL picks based on the appliance template |
| **EBS volumes** | ~1 TB total (gp3) — separate volumes for `/hana/data`, `/hana/log`, `/usr/sap`, `/sapmnt`, OS root |
| **Elastic IP** | 1 (for RDP/SAPGUI access) |
| **VPC** | 1 (CAL creates a fresh VPC by default; you can pin it to an existing one) |
| **Subnet** | 1 public subnet in 1 AZ |
| **Internet Gateway** | 1 |
| **Security Group** | 1 (CAL opens 22, 3389, 3200, 3300, 8000, 8443, 44300, 50000, 50013, 50014) |
| **Key pair** | 1 (you provide; used for Linux SSH) |
| **CloudFormation stack** | 1 (created and managed by CAL — do not edit by hand) |
| **IAM role for CAL** | 1 cross-account role you create once so CAL can deploy into your account |

> **Important constraints**
> - CAL requires you to nominate an AWS region where the appliance template is published (commonly `us-east-1`, `eu-west-1`, `ap-southeast-1`).
> - The trial appliance is **single-host**, **non-HA**, **no backup automation** — fine for migration testing, not for any production-like load.
> - **Suspend the appliance from the CAL console** when not in use; otherwise EC2 + EBS bills accrue 24/7.
> - The CAL VPC is isolated by default — to let Migrate4HANA's Lambdas reach it, either (a) deploy CAL into the same VPC as the tool via "advanced mode", or (b) **VPC peer** the CAL VPC with the Migrate4HANA VPC.

---

## Migrate4HANA tool — AWS resources (separate from SAP CAL)

Everything terraform creates / the tool needs, *excluding* the S/4 system itself.

### Compute
- **AWS Lambda** — 14 functions (target-provisioner, basis-validator, sizing-advisor, object-router, MC/LTMOM/IDoc orchestrators, 4 transport sub-lambdas, bc-set-builder, delta-extractor, manual-gate)
- **Lambda layers** — NW RFC SDK + PyRFC + shared utils
- **AWS Step Functions** — 1 state machine driving the lift-and-shift pipeline
- **ECS Fargate** *or* **EC2** (small) — host for `api_server.py` (FastAPI)
- **S3 + CloudFront** *or* same ALB — hosting the React frontend

### Storage
- **S3 buckets**:
  - terraform state (per env)
  - migration artefacts (transports, logs, runbooks) — versioned + KMS-encrypted
  - lambda deployment packages + layers
  - frontend static assets (if served from S3)
- **DynamoDB tables**:
  - terraform state lock (per env)
  - `m4h-gates-<env>` — manual-gate task tokens

### Networking
- **VPC** (1) with **private subnets** (≥2 AZs) and **public subnet** (1, for NAT)
- **NAT Gateway** (1) — egress for Lambda
- **Internet Gateway** (1)
- **Application Load Balancer** (1) — fronting api_server / frontend
- **Security groups** — Lambda SG, ALB SG, SAP-host SG
- **VPC endpoints (interface)**: `ssm`, `ssmmessages`, `ec2messages`, `secretsmanager`, `logs`, `sns`, `kms`
- **VPC endpoints (gateway)**: `s3`, `dynamodb`
- **(optional)** Site-to-Site VPN or Direct Connect — only if ECC is on-prem
- **(optional)** VPC peering — to the SAP CAL VPC

### Identity & secrets
- **IAM roles**: lambda-exec (one per function or one shared), step-functions-exec, api-server-exec, terraform-deployer
- **IAM policies** scoped to `secretsmanager:GetSecretValue`, `ssm:SendCommand`, `s3:*` on the artefact bucket, `dynamodb:*` on the gates table, `states:*` on the state machine
- **AWS Secrets Manager** — 5+ secrets (`m4h/ecc/rfc`, `m4h/s4/rfc`, `m4h/mc/odata`, `m4h/cts/host`, `m4h/idoc/partner`)
- **AWS KMS** — 1 customer-managed key for S3 + Secrets Manager encryption

### Eventing & notifications
- **SNS topic** — `m4h-gates-<env>` for manual-gate emails / Slack
- **EventBridge rules** — pipeline schedule triggers
- **CloudWatch Log Groups** — one per lambda + Step Functions execution logs
- **CloudWatch Alarms** (optional) — failed executions, throttles, dead-letter depth
- **SES** (optional) — if you want richer gate emails

### Build / CI (optional, not in terraform yet)
- **CodeBuild** — to build the PyRFC wheel against Amazon Linux 2
- **CodePipeline** *or* **GitHub Actions OIDC role** — to deploy terraform on merge

---

## Two-account / two-VPC topology (recommended)

```
┌──────────────────────────────────┐         peering          ┌─────────────────────────────┐
│  Migrate4HANA AWS account        │ ◄─────────────────────► │  SAP CAL deployment         │
│  ────────────────────────────    │                         │  ─────────────────────       │
│  • Lambdas (in VPC)              │                         │  • EC2 (S/4HANA appliance)  │
│  • Step Functions                │                         │  • EBS (HANA data/log)      │
│  • S3, DynamoDB, Secrets, KMS    │                         │  • SG, EIP, IGW             │
│  • api_server (Fargate) + ALB    │                         │  • CAL CloudFormation stack │
│  • SNS, EventBridge, CloudWatch  │                         │                             │
└──────────────────────────────────┘                         └─────────────────────────────┘
            │                                                              ▲
            │  RFC 33xx / OData 44300 / CTS+ 3299                          │
            └──────────────────────────────────────────────────────────────┘
```

Single-account is also fine — just deploy CAL into the same VPC and skip the peering.

---

## Critical Review (no flattery)

### What this tool actually is, in one sentence
> An AWS-native orchestration & governance shell that coordinates SAP-shipped migration tools (Migration Cockpit, LTMOM, IDoc, CTS+/tp) for greenfield S/4HANA, with manual approval gates and a "no direct DB write" guardrail.

It is **not** an automated end-to-end ECC→S/4 migration engine. The hard SAP semantics (mapping, reconciliation, custom-code behaviour, downtime, cutover governance) are still owned by humans and SAP's own tools — this project sequences and documents them.

### Architectural reality (the uncomfortable parts)
| Component | Claim | Reality |
|---|---|---|
| `migration-cockpit-orchestrator` | "MC OData automation" | MC OData (`LTMC_MIGRATION_OBJECTS_SRV`, `LTMC_MIGRATION_RUNS_SRV`) is **not a stable, fully-documented automation surface** across S/4 releases. No CSRF/cookie/batch handling. Code already falls back to `manual_gate`. → It's really a **template + runbook + best-effort trigger**. |
| `ltmom-orchestrator` | "LTMOM orchestrator" | SAP exposes **no public LTMOM automation API**. The Lambda only emits a design runbook unless `model_already_built=true`. → It's a **manual design handoff generator**, not orchestration. |
| `transport-import-executor` | tp/CTS+ automation | RC parsing has a default-to-zero fallback; RC 4 is unconditionally treated as success; SSM failure-status not cross-checked; no `SLOG`/`ALOG`/`TPALOG` parsing. → Can declare unsafe transports successful. |
| `rollback-manager` | "rollback" | Only flips DNS + unlocks ECC. Does not address postings already made in S/4, in-flight IDocs/qRFC, batch jobs, bank files, number ranges, audit obligations. → It's an **ECC switch-back**, not a business rollback. |
| `migration-validator` | reconciliation | Uses `RFC_READ_TABLE` with `ROWCOUNT=1` to "count" — comments admit "in real SAP we'd use COUNT(*)". Finance recon caps at 50k ACDOCA rows. → **Placeholder, not enterprise reconciliation.** |
| `tests/test_no_direct_writes.py` | "blocks direct writes" | Static literal-name scan only. Misses dynamic FM names, generated ABAP in transports, IDoc payloads with side effects, custom HTTP endpoints. |
| `tests/test_orchestrators.py` | "13/13 OK" | Smoke tests with permissive `boto3.client = MagicMock` and forced `Status=Success`. **Zero real SAP, zero real AWS, zero failure-mode coverage.** Confidence is "doesn't crash on import" — not "works against ECC/S4". |

### "Lift-and-shift" labelling — drop it
In SAP language, *lift-and-shift* = SUM/DMO brownfield system conversion. This tool is **greenfield S/4HANA + selected data/config bridges**. Calling it lift-and-shift will get the project torn apart by any Basis lead or SI architect on first read. Recommended rename:

> **"AWS-native Greenfield S/4HANA Migration Orchestrator (support-preserving)"**

### Security & ops gaps (production-blocking today)
- `api_server.py` writes JWT secret to a plaintext file; ECC password lives in process memory.
- IAM in `terraform/modules/lambda/main.tf` uses `Resource = "*"` for SSM SendCommand, DynamoDB, SNS, Step Functions — far too broad for a tool that touches cutover.
- Audit evidence is split across CloudWatch / S3 / DynamoDB / SAP STAD/SM20/SLG1/STMS/SM37 with **no unified immutable run ledger**.
- No multi-tenancy. Single-customer/single-account/single-region only.

### Market — honest competitive landscape
This is **not** first-of-its-kind. Real competitors and how they compare:

| Tool / vendor | What they do | Overlap | Why they currently beat M4H |
|---|---|---|---|
| **SNP CrystalBridge / BLUEFIELD** | Selective data transition, near-zero downtime, landscape transformation | Very high | Mature IP, F500 references, deep SAP know-how, reconciliation tooling |
| **Natuvion DCS** | Data transformation, selective migration, privacy/archive | High | Enterprise methodology, governance, validation depth |
| **Syniti ADM** | Enterprise data migration, data quality, stewardship | High | SAP-endorsed partner, business-user controls, DQ depth |
| **cbs Enterprise Transformer** | S/4 transformation, harmonisation | High | Consulting + tooling combo, complex global landscapes |
| **EPI-USE Labs DSM** | Client copy, scrambling, carve-outs | Medium | Mature SAP data movement pedigree |
| **SAP Signavio + LeanIX** | Readiness, process insights | Low-medium | Owned by SAP, certified |
| **AWS Migration Hub / MGN** | Generic infra migration | Low | Not SAP-semantic |
| **Accenture myWizard, Deloitte ASCEND, Capgemini SAP Move, IBM, Infosys, TCS, Wipro factories** | SI accelerators + people + methodology | Very high | Customer trust, references, escalation paths, SAP partnership |

### The honest USP (and the killer)
**USP candidates that survive scrutiny:**
- AWS-native control plane (Step Functions + Lambda) — most competitors are on-prem Java/.NET stacks
- Hard "no direct write" guardrail enforced in CI — preserves SAP support by *design*
- Open-architecture / lower TCO than SNP/Natuvion licences (~$500K–$2M)
- Manual-gate discipline + audit trail (when finished)

**USP killer:** the tool **does not own the hard SAP migration semantics**. It coordinates tools and people who still own the actual migration. The first real custom LTMOM object, MC limitation, RC-4 transport, IDoc partner-profile issue, or finance-recon variance turns the "automated pipeline" back into manual SAP consulting work.

### Honest readiness scorecard
| Area | Readiness |
|---|---|
| Python handler importability | ✅ Solid |
| AWS orchestration skeleton | 🟡 Partial — IAM too broad, no live AWS test |
| SAP-supported write-path design | ✅ Conceptually sound |
| Real SAP execution | ❌ Unproven — no live ECC/S4 test ever run |
| Reconciliation framework | ❌ Placeholder only |
| Audit / immutable evidence | ❌ Not designed |
| Production migration readiness | ❌ Low |
| Customer go-live readiness | ❌ Not demonstrated |

### Biggest single risk
Not AWS. Not FastAPI. Not Lambda count. The risk is:

> **The first serious customer-specific MC limitation, custom LTMOM object, RC-4 transport warning, or finance-reconciliation mismatch will turn the "automated pipeline" into a manual SAP consulting engagement — and the customer will conclude the tool didn't deliver what was promised.**

### Honest positioning recommendation
Don't sell this as "automated ECC→S/4 migration". Sell it as:

> **"An AWS-native migration control tower for SAP greenfield S/4HANA programs. It coordinates SAP-standard tools (MC, LTMOM, IDoc, CTS+), enforces support-preserving guardrails, captures auditable evidence per cutover stage, and provides manual approval gates. It does not replace SAP-functional, Basis, or data-migration expertise."**

That is **defensible**, **differentiated** (no other AWS-native open-architecture variant exists at this orchestration layer), and **honest**. It positions the tool as an SI accelerator / customer control plane — a real and unfilled niche between SAP's own LTMC and the commercial heavyweights (SNP/Natuvion/Syniti).

### Must-fix before any serious customer pilot
1. Relabel: drop "lift-and-shift" everywhere; downgrade "automated" claims for MC and LTMOM.
2. Live SAP integration tests (use SAP CAL trial — that's the cheapest path).
3. Fix `tp` RC handling: 3-tier (success / warning-requires-review / failed); never default RC=0.
4. Build real reconciliation: counts, key coverage, balance totals, hash/tolerance, exception workflow.
5. Unified immutable run ledger (DynamoDB PITR + S3 Object Lock).
6. Tighten IAM (specific ARNs + SSM resource tags).
7. Move JWT + SAP creds to Secrets Manager; rotate; audit.
8. Rename test output: "13 handler smoke tests passed" not "orchestrators OK".
