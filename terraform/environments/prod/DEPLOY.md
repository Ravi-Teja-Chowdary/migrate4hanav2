# Migrate4HANA — One-Roof Deployment

This is the **single root** for the whole platform. One `terraform init` / `apply` brings the
entire AWS stack up; one `terraform destroy` tears it down. Local state by default — no
pre-existing backend bucket, no bootstrap.

```powershell
cd terraform\environments\prod
terraform init
terraform apply        # everything up
# ... use it ...
terraform destroy      # everything down
```

`terraform validate` passes clean. With the shipped defaults, `apply` runs with **zero required
input** — VPC/subnets are created in-stack; optional/licensed pieces default to off.

---

## What comes up (one apply)
VPC (+ endpoints, optional VPN GW) · S3 staging · **all ~28 Lambda stages** · ECS/Fargate cluster
+ task def + ECR · Step Functions pipeline (+ lift-and-shift state machine) · evidence-ledger
(KMS + WORM S3 + DDB) · CloudWatch dashboards/alarms · WAF · CloudTrail audit · WebSocket
telemetry · Secrets Manager (SAP creds placeholders) · DynamoDB (rules, gates) · target-system
(SG/EFS/SSM) · **PROD-hardening (Pillars 2/3/4):** gate SNS topic + HMAC secret, audit
hash-chain DDB vault, key-map DDB, value-map matrix bucket — all wired into the functions as
`M4H_*` env vars.

## What is intentionally OFF / optional (so apply is clean)
| Thing | Default | To enable |
|---|---|---|
| SAP NW RFC SDK Lambda layer | `pyrfc_layer_arn=""` (layer omitted via `compact()`) | build+publish the licensed SDK layer, set `pyrfc_layer_arn` |
| Fargate worker **image** | ECR repo created empty | build+push your image, then heavy stages run |
| Air-gapped LLM (GPU EC2) | `enable_airgapped_llm=false` | set `true` + `gpu_ami_id` |
| Entity Resolution (ML BP dedup) | excluded — `aws_entityresolution_*` not in hashicorp/aws (verified v5.100.0) | switch module to hashicorp/awscc provider, or manage via CLI |
| DMS | removed (off-architecture for SAP) | n/a — data moves via BAPI/OData/MC only |
| Email alerts | `alert_email=migrations@example.com` | set your address in `terraform.tfvars` |

> The stack **applies and stands up** without any of the above; the SAP-RFC stages stay inert
> until you supply the layer + image + SAP creds + network reachability. That's an external
> prerequisite no tool can conjure — not a stack defect.

---

## Optional overrides — `terraform.tfvars`
```hcl
aws_region           = "us-east-1"
alert_email          = "migrations@yourcorp.com"
pyrfc_layer_arn      = "arn:aws:lambda:us-east-1:<acct>:layer:pyrfc:1"  # when you have it
enable_airgapped_llm = false
transform_rules      = "s3://migrate4hana-mapping-prod-<acct>/rules/transform_rules.json"
```

## After apply — make the SAP-RFC + Fargate paths live (PowerShell)
```powershell
# 1. push the Fargate worker image to the ECR repo this stack created
$ECR = terraform output -raw ecr_repository_url           # e.g. <acct>.dkr.ecr.us-east-1.amazonaws.com/migrate4hana/worker
$Registry = $ECR.Substring(0, $ECR.LastIndexOf('/'))      # strip "/migrate4hana/worker" -> registry host
aws ecr get-login-password | docker login --username AWS --password-stdin $Registry
docker build -f ..\..\..\ecs\Dockerfile -t "${ECR}:latest" ..\..\..
docker push "${ECR}:latest"

# 2. put real SAP creds into the secrets the stack created
$EccPwd = Read-Host -AsSecureString "ECC password"        # read securely; not echoed
$ptr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($EccPwd)
$pwd = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
$json = @{ ashost = "..."; sysnr = "00"; client = "100"; user = "..."; passwd = $pwd } | ConvertTo-Json -Compress
aws secretsmanager put-secret-value `
  --secret-id migrate4hana/prod/sap-credentials `
  --secret-string $json

# 3. upload the value-map matrix (Pillar 2)
$Mapping = terraform output -raw mapping_bucket
aws s3 cp company_code_map.json "s3://$Mapping/mappings/matrix.json"

# 4. confirm the gate-alert email subscription (AWS sends a click-to-confirm link)

# 5. start a run
Invoke-Expression (terraform output -raw start_migration_command)
```

## Governance gates (Pillar 3) — Step Functions wiring
Insert a `TaskToken` wait-state after ASSESS / DATA-PREP / VALIDATE in the pipeline state
machine; a small `m4h-gate-open` Lambda calls `governance.GateController.create_gate(...)` +
`publish_alert(...)`, and the signed **`/api/spine/approve`** webhook resumes it via
`states:send_task_success`. (Ask me to generate that glue Lambda + the resume patch — it's small.)

---

## Teardown caveats
- `terraform destroy` removes everything **except** objects under WORM Object Lock. The
  evidence-ledger + any COMPLIANCE-locked evidence objects **cannot be deleted until retention
  expires** — that immutability is the regulatory point. For a throwaway test, lower the
  evidence retention before apply, or empty/disable Object Lock on that bucket first.
- S3 buckets with versioned objects may need `force_destroy`/manual empty before destroy.

## Remote state (optional, for teams)
Local state ships by default. For shared/remote state, add an S3 backend block to `main.tf`
(`backend "s3" {...}`) and create the state bucket + lock table once before `init`.

## Known follow-up
Runtime IAM for the Lambda role to call the *new* hardening resources (SNS publish, the audit/
key-map DDB tables, the gate secret, ECS `run_task`, `states:SendTaskSuccess`) — the infra comes
up regardless; tighten these grants before exercising those paths in anger.
