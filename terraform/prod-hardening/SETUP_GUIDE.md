# Migrate4HANA — PROD-Hardening Infrastructure Setup Guide

This standalone Terraform stack provisions everything the production-hardening pillars need
at runtime. Apply it on its own, then set the outputs as environment variables on your API
server / orchestrator. Nothing here touches the proven data-migration spine — it only *enables*
the new capabilities (which stay no-ops until these env vars are present).

---

## 1. What gets created & why

| Resource | Pillar | Env var the code reads |
|---|---|---|
| **ECS cluster** (`*-cluster`) | 1.1 elastic compute | `M4H_FARGATE_CLUSTER` |
| **Fargate task definition** (`*-worker`) | 1.1 | `M4H_FARGATE_TASKDEF` |
| **Security group** (task egress) | 1.1 | `M4H_FARGATE_SGS` |
| **ECR repo** (`*-worker`) | 1.1 | (image source) |
| **CloudWatch log group** | 1.1 | (task logs) |
| **SNS topic** (`*-gate-alerts`) + email sub | 3 governance | `M4H_GATE_SNS_TOPIC` |
| **Secrets Manager secret** (`*-gate-secret`) | 3 | `M4H_GATE_SECRET` (read from `*_ARN`) |
| **DynamoDB `*-audit-ledger`** | 4 crypto-audit | `M4H_AUDIT_LEDGER_TABLE` |
| **DynamoDB `*-key-map`** | 4 / ledger | `M4H_KEYMAP_TABLE` |
| **S3 `*-evidence-<acct>`** (Object Lock, WORM) | 4 | `M4H_EVIDENCE_BUCKET` |
| **S3 `*-config-<acct>`** (value-map matrix) | 2 transform | `M4H_MAPPING_S3` (=`s3://<bucket>/<key>`) |
| **IAM task + execution roles** | all | (assumed by the task) |

Step Functions `TaskToken` wait-states are wired into your **existing** pipeline state machine
(snippet in §6), not recreated here, to avoid colliding with `terraform/modules/step-functions`.

---

## 2. Prerequisites

- **Terraform ≥ 1.3** and **AWS CLI v2**, authenticated to the target account/region
  (`aws sts get-caller-identity` should succeed).
- An existing **VPC** + **private subnets** that can reach **both** your SAP systems
  (ECC RFC `33xx`, S/4 OData `443xx`) **and** AWS services (S3/DynamoDB/SNS/Secrets Manager) —
  via a NAT gateway or VPC endpoints. (The repo's `terraform/modules/vpc` + `vpc-endpoints`
  can provide these if you don't already have them.)
- Region **must match** your S/4HANA appliance + Lambdas (same region as `m4h-staging-a1`).
- (Optional) ARNs of your existing **ECC** / **S/4** credential secrets to grant the task role.
- **Docker** installed (to build & push the worker image).

---

## 3. Apply (two-pass: infra → image → re-apply)

```bash
cd terraform/prod-hardening

cat > terraform.tfvars <<'EOF'
region          = "us-east-1"
vpc_id          = "vpc-xxxxxxxx"
subnet_ids      = ["subnet-aaaa", "subnet-bbbb"]
alert_email     = "migrations@yourcorp.com"
staging_bucket  = "m4h-staging-a1"
# ecc_secret_arn    = "arn:aws:secretsmanager:...:ecc"
# target_secret_arn = "arn:aws:secretsmanager:...:s4"
EOF

terraform init
terraform plan
terraform apply        # creates everything; task def uses the ECR repo's :latest tag
```

**Confirm the SNS email subscription** — AWS sends a confirmation link to `alert_email`; click it,
or no gate alerts will be delivered.

---

## 4. Build & push the worker image, then finalize

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=us-east-1
REPO=$(terraform output -raw ecr_repository_url)

aws ecr get-login-password --region $REGION \
  | docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"

# from the repo root — minimal worker image (see Dockerfile sketch in §7)
docker build -t "$REPO:latest" .
docker push "$REPO:latest"

# re-apply so the task definition points at the pushed image (or set var.container_image)
terraform apply
```

---

## 5. Wire the outputs into your environment

```bash
terraform output -json env_vars
```

Set those on the **API server** and pass them into the **Fargate task** (already injected by the
task def). On the API host, also resolve the gate secret into `M4H_GATE_SECRET`:

```bash
export M4H_GATE_SECRET=$(aws secretsmanager get-secret-value \
  --secret-id "$(terraform output -raw gate_secret_arn)" --query SecretString --output text)

export M4H_FARGATE_CLUSTER=...    # from env_vars output
export M4H_FARGATE_TASKDEF=...
export M4H_FARGATE_SUBNETS=...    # comma-separated
export M4H_FARGATE_SGS=...
export M4H_GATE_SNS_TOPIC=...
export M4H_AUDIT_LEDGER_TABLE=...
export M4H_EVIDENCE_BUCKET=...
export M4H_KEYMAP_TABLE=...
```

With these present, the code activates automatically:
`ComputeDispatcher` offloads >threshold objects to Fargate; `HashChainLedger` writes to the audit
vault; `EvidencePack.write(...)` lands a WORM-locked manifest in the evidence bucket;
`GateController` signs/verifies gates with the real secret; SNS alerts publish.

---

## 6. Step Functions governance gates (Pillar 3 wiring)

Insert a `TaskToken` wait-state after **ASSESS**, **DATA-PREP**, and **VALIDATE** in your existing
state machine (`terraform/modules/step-functions`). Pattern (DATA-PREP shown):

```json
"GateAfterDataPrep": {
  "Type": "Task",
  "Resource": "arn:aws:states:::lambda:invoke.waitForTaskToken",
  "Parameters": {
    "FunctionName": "m4h-gate-open",
    "Payload": {
      "run_id.$": "$.run_id",
      "gate": "post_data_prep",
      "taskToken.$": "$$.Task.Token",
      "metrics.$": "$.data_prep.metrics"
    }
  },
  "TimeoutSeconds": 86400,
  "Next": "DataLoadPhase"
}
```

- `m4h-gate-open` is a ~30-line Lambda that calls
  `governance.GateController.create_gate(run_id, gate, metrics, task_token)` (persists the token +
  returns the HMAC signature) and publishes the alert via `governance.publish_alert(build_gate_alert(...))`.
- A human approves by POSTing to **`/api/spine/approve`** `{gate_id, signature, decided_by}`.
  The API verifies the HMAC, then resumes the machine with the stored token:
  `boto3.client("stepfunctions").send_task_success(taskToken=..., output=...)`.
- IAM: the task role already has `states:SendTaskSuccess`; grant the **API host** the same on the
  state-machine ARN.

> Tell me to generate `m4h-gate-open` (the glue Lambda) + the `/api/spine/approve → send_task_success`
> patch and I'll add them — they're small and complete the loop.

---

## 7. Worker image (Dockerfile sketch)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
# SAP NW RFC SDK + pyrfc must be layered in per your licensed SDK; boto3/faker/pyarrow:
RUN pip install --no-cache-dir boto3 faker pyarrow
COPY . /app
# the worker reads M4H_TASK_PAYLOAD (JSON) injected by the dispatcher and runs the stage
ENTRYPOINT ["python", "-c", "import os,json; from ecs.entrypoint import main; main(json.loads(os.environ.get('M4H_TASK_PAYLOAD','{}')))"]
```

(Adjust to your real entrypoint; `ecs/entrypoint.py` already exists in the repo.)

---

## 8. Pillar 2 — load the value-map matrix

```bash
# example matrix: legacy -> target company codes, etc.
aws s3 cp company_code_map.json \
  "s3://$(terraform output -raw env_vars | jq -r .M4H_CONFIG_BUCKET)/mappings/matrix.json"

export M4H_MAPPING_S3="s3://<config-bucket>/mappings/matrix.json"
export M4H_TRANSFORM_RULES="/app/config/transform_rules.json"   # ship rules in the image or a path
```

---

## 9. Verification checklist

- **1.1 Fargate**: `aws ecs list-task-definitions` shows `*-worker`; a run with an object whose
  `est_rows > threshold` shows `"compute": {"target":"fargate"}` in the spine result and an ECS task starts.
- **3 Gates**: `GET /api/spine/gates` lists a pending gate; a forged signature is refused; a valid
  one returns `resume:true`; the email subscription is **Confirmed** in the SNS console.
- **4 Audit**: items appear in `*-audit-ledger`; `HashChainLedger.verify()` returns `ok:true`; an
  evidence object in `*-evidence-*` has an Object-Lock retention date (`aws s3api get-object-retention`).
- **2 Transform**: with `M4H_TRANSFORM_RULES` set, a record failing a DQ gate is dead-lettered as
  `DATA_QUALITY_REJECTION` instead of hitting the BAPI.

---

## 10. Cost & teardown caveats

- DynamoDB tables are **PAY_PER_REQUEST**; SNS/Secrets/ECR are near-zero idle. Fargate bills only
  while a task runs. CloudWatch logs retain 90 days.
- **WORM teardown:** the evidence bucket uses **COMPLIANCE** Object Lock — objects **cannot be
  deleted until retention expires**, so `terraform destroy` will fail on a non-empty evidence bucket
  by design. That is the point (regulatory immutability). To tear down a *test* stack, set
  `evidence_retention_days` very low up front, or create the test evidence bucket without Object Lock.
- Rotate the gate secret via Secrets Manager; the HMAC fence picks up the new value on the next read.
```
