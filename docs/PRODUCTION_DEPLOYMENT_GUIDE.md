# Production Deployment Guide — enterprise-hardening pass 2026-07-03

Deployment steps for the additions shipped in the enterprise-hardening pass.
Assumes the base migrate4hana stack (see `LIFT-AND-SHIFT-SETUP.md`) is
already deployed.

## What this guide covers

- `mc-project-provisioner` Lambda — auto-creates MC projects via the SAP-released
  OData services under Note 2462327.
- `snowpipe-verifier` Lambda + `terraform/modules/snowpipe/` — provisions the AWS
  side of Snowpipe auto-ingest; the Snowflake DDL runs inside Snowflake
  (`scripts/snowpipe/snowflake_side.sql`).
- Salesforce sink hardening — real REST upsert with OAuth2 + DDB sync tracker.
- Transport-import-executor `dry_run` + already-imported pre-check.

## What this guide does NOT cover (deliberately refused)

The following prompt items were **not implemented** because they would put
the customer's SAP system outside SAP support coverage:

- Custom RFC call to `STMS_IMPORT_REQUESTS` / `STMS_IMPORT_REQUEST`. These
  are internal SAP FMs, not in the released customer-callable set. The
  SAP-canonical import path (`tp import`) is already used by the existing
  `transport-import-executor` via SSM.
- Custom Z-programs calling `TH_ENABLE_WP_TYPE` / `TH_DISABLE_WP_TYPE` to
  freeze work processes at cutover. These are internal SAP kernel FMs;
  programmatically manipulating WPs can corrupt the distributed lock
  table. The SAP-doctrine cutover path (SM02 + SU10 + RZ04 by a Basis
  user) is what our `cutover-orchestrator` runbook emits.
- Custom RFC calls to `LTR_*` / `LTMC_*` / `DMC_*` MC project-provisioning
  FMs. Same reason — not released. We use only the OData service under
  SAP Note 2462327 for MC project auto-setup.

The tool's default posture stays "SAP-safe first, automate only what SAP
sanctions." If a customer's Basis team explicitly authorises calling one of
the above, that's a per-engagement addendum; the shipping code will not.

---

## 1. Deploy the mc-project-provisioner Lambda

```powershell
# 1.1 Zip the Lambda
cd lambda\mc-project-provisioner
Compress-Archive -Path handler.py, ..\utils\logger.py -DestinationPath mc-project-provisioner.zip -Force
cd ..\..

# 1.2 Upload + register (parallel to the other lambdas — same VPC/subnets/role scope)
aws lambda create-function `
    --function-name migrate4hana-mc-project-provisioner-prod `
    --runtime python3.11 `
    --role  arn:aws:iam::<acct>:role/migrate4hana-lambda-role-prod `
    --handler handler.lambda_handler `
    --zip-file fileb://lambda/mc-project-provisioner/mc-project-provisioner.zip `
    --timeout 300 --memory-size 512 `
    --environment 'Variables={S3_STAGING_BUCKET=migrate4hana-staging-prod,COMPLIANCE_LEDGER_TABLE=migrate4hana-compliance-ledger-prod,MC_ODATA_TIMEOUT_S=30}'
```

### Wiring into Step Functions

Add a state before the existing `MigrationCockpitOrchestrator` map state:

```json
"McProjectProvisioner": {
  "Type": "Task",
  "Resource": "arn:aws:states:::lambda:invoke",
  "Parameters": {
    "FunctionName": "migrate4hana-mc-project-provisioner-prod",
    "Payload": {
      "run_id.$":            "$$.Execution.Name",
      "project_id.$":        "$.mc_project_id",
      "objects.$":           "$.mc_object_list",
      "target_creds_arn.$":  "$.target_creds_arn",
      "staging_bucket.$":    "$.staging_bucket",
      "template_prefix.$":   "$.mc_template_prefix"
    }
  },
  "ResultSelector": {"provisioner.$": "$.Payload"},
  "ResultPath": "$.mc_project",
  "Next": "MigrationCockpitOrchestrator"
}
```

### Environment variables

| Var | Default | Description |
|---|---|---|
| `S3_STAGING_BUCKET` | `migrate4hana-staging-prod` | Where runbooks + audit blobs land |
| `COMPLIANCE_LEDGER_TABLE` | `migrate4hana-compliance-ledger-prod` | Hash-chain audit table |
| `TARGET_SECRETS_ARN` | — | Fallback secret if event doesn't carry it |
| `M4H_ODATA_INSECURE` | unset | Set to `1` for lab systems with self-signed TLS |
| `MC_ODATA_TIMEOUT_S` | `30` | Per-call OData timeout (seconds) |

### Verify

```powershell
aws lambda invoke `
    --function-name migrate4hana-mc-project-provisioner-prod `
    --cli-binary-format raw-in-base64-out `
    --payload file://scripts\mc-project-provisioner-payload.json `
    out.json
Get-Content out.json | ConvertFrom-Json
```

Expected shape:
```json
{
  "status": "created" | "manual_gate" | "failed",
  "project_id": "M4H_...",
  "objects_bound": [...],
  "objects_deferred": [...],
  "runbook_s3_uri": "s3://.../project-runbook.md",
  "audit_block": {"block_hash": "...", "prev_hash": "...", "written": true}
}
```

## 2. Deploy the Snowpipe module

### 2.1 First-pass Terraform

```hcl
module "snowpipe" {
  source                    = "../../modules/snowpipe"
  deploy_snowpipe           = true
  environment               = "prod"
  stage_bucket_name         = module.ws4.snowflake_stage_bucket_name
  stage_prefix              = "snowflake-stage/"
  deploy_verifier           = true
  verifier_snowflake_account = "myacct-us-east-1"
  verifier_snowflake_user    = "M4H_VERIFIER"
  verifier_secret_arn        = aws_secretsmanager_secret.snowflake_verifier.arn
}
```

Run `terraform apply`. This provisions:
- SNS topic + policy
- S3 event notification (stage bucket → SNS)
- IAM role Snowflake assumes (loose trust on first apply)
- Verifier Lambda + EventBridge 15-min schedule
- CloudWatch alarm on SNS delivery failures

### 2.2 Snowflake side — DBA runs once

Execute `scripts/snowpipe/snowflake_side.sql` in Snowflake. Fill in the
two ARN placeholders from `terraform output`. Then run
`DESC STORAGE INTEGRATION m4h_stage_int` and copy the
`STORAGE_AWS_IAM_USER_ARN` + `STORAGE_AWS_EXTERNAL_ID` back into
`terraform.tfvars`:

```hcl
snowflake_aws_account_id = "..."   # from STORAGE_AWS_IAM_USER_ARN
snowflake_external_id    = "..."   # from STORAGE_AWS_EXTERNAL_ID
```

Re-run `terraform apply` to tighten the trust policy.

### 2.3 Verify

```powershell
# Trigger a test write via the SnowflakeSink
python -c "
import boto3
from lambda.utils.sink_router import SnowflakeSink, SinkRouter
s3 = boto3.client('s3')
snow = SnowflakeSink(s3_client=s3, stage_bucket='migrate4hana-snowflake-stage-prod')
snow.write_one('Material','MAT001',{'MAKTX':'Test'},tenant_id='acme')
snow.flush()
"

# Confirm CloudWatch metric appeared within 15 minutes
aws cloudwatch get-metric-statistics `
    --namespace 'Migrate4HANA/Snowpipe' `
    --metric-name RowsLoaded `
    --dimensions 'Name=Tenant,Value=acme' 'Name=ObjectType,Value=Material' `
    --start-time (Get-Date).AddHours(-1).ToString('yyyy-MM-ddTHH:mm:ssZ') `
    --end-time (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssZ') `
    --period 300 --statistics Sum
```

## 3. Salesforce sink live-upsert

Salesforce sink now supports real REST upserts. The sink accepts
`instance_url` + `oauth_creds` + `http_client` + `dynamodb_client` at
construction time. Configure via env vars:

```
M4H_SALESFORCE_INSTANCE_URL      = "https://acme.my.salesforce.com"
M4H_SALESFORCE_OAUTH_SECRET_ARN  = "arn:aws:secretsmanager:...:sf-client-cred"
M4H_SALESFORCE_SYNC_TABLE        = "salesforce_sync_status"
```

The secret payload:
```json
{
  "client_id":     "<connected-app-consumer-key>",
  "client_secret": "<connected-app-consumer-secret>",
  "token_url":     "https://acme.my.salesforce.com/services/oauth2/token"
}
```

### DDB table (create once)

```hcl
resource "aws_dynamodb_table" "salesforce_sync_status" {
  name         = "salesforce_sync_status"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "tenant_id"
  range_key    = "external_id"

  attribute { name = "tenant_id"   type = "S" }
  attribute { name = "external_id" type = "S" }
  attribute { name = "last_status" type = "S" }

  global_secondary_index {
    name            = "by_tenant_status"
    hash_key        = "tenant_id"
    range_key       = "last_status"
    projection_type = "ALL"
  }

  point_in_time_recovery { enabled = true }
  server_side_encryption { enabled = true }
}
```

### Retry FAILED rows

```powershell
python -c "
from lambda.utils.sink_router import SalesforceSink
sink = SalesforceSink(
    instance_url  = '...',
    oauth_creds   = {...},
    http_client   = <urllib3 pool>,
    dynamodb_client = boto3.client('dynamodb'))
print(sink.retry_failed(tenant_id='acme'))
"
```

## 4. Transport-import-executor dry-run

Add `dry_run: true` to any invocation payload to validate prerequisites
without invoking `tp`:

```json
{
  "run_id":       "test-dr-1",
  "transport_id": "M4HK900123",
  "target_sid":   "S4H",
  "target_client":"100",
  "dry_run":      true,
  "target_bastion_instance_id": "i-abc123",
  "target_rfc_creds": {"ashost":"vhcalabaci","sysnr":"00","client":"800","user":"ATH","passwd":"..."}
}
```

Returns:
- `dry_run_ok` — every pre-check passed; safe to re-invoke without `dry_run`
- `dry_run_blocked` — at least one pre-check failed; the `prechecks` block
  tells you which. Common causes: `staging_path_present.ok=false` (files
  not staged in `/usr/sap/trans`), `ssm_reachable.ok=false` (bastion stopped)
- `already_imported` — E070 shows the transport is already in the target
  client; nothing to do

## 5. Ops handoff

- **On-call runbook:** `docs/OPERATOR_RUNBOOK_v2.md` (also updated this pass)
- **Sink alerts:** `SINKROUTER_ADMIN_GUIDE.md`
- **Content refresh:** `CONTENT_GENERATION_WORKFLOW.md`
- **Slack:** `#migrate4hana-ops` (per `EXPERT_REVIEW_BRIEF.md`)
