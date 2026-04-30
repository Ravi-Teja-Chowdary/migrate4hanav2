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
