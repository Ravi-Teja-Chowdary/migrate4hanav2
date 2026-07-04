# Operator runbook v2 — 2026-07-03 enterprise-hardening pass

Updates the existing `RUNBOOK.md` with the automation surface added in the
enterprise-hardening pass. Covers the new automated Basis touchpoints,
what alerts to expect, and how to recover.

## Contents

1. [MC project provisioning](#1-mc-project-provisioning)
2. [Transport imports (dry-run + already-imported)](#2-transport-imports)
3. [Cutover ECC lock](#3-cutover-ecc-lock)
4. [Sink health](#4-sink-health-salesforce--snowflake)
5. [Alarm cheat sheet](#5-alarm-cheat-sheet)

---

## 1. MC project provisioning

### What automates

The `mc-project-provisioner` Lambda auto-creates the MC project and binds
each migration object to its staging S3 URI via the SAP-released OData
services (`/sap/opu/odata4/sap/api_migrationcockpit_*`).

### Expected states

| Status | Meaning | Action |
|---|---|---|
| `created` | OData succeeded; every object bound | ✅ proceed to `MigrationCockpitOrchestrator` |
| `manual_gate` | OData failed or partial; runbook produced | Basis lead: read `runs/<run_id>/mc/project-runbook.md` in S3 and create the project manually in Fiori "Migrate Your Data" |
| `failed` | Cred load or transport-level error | Check secret ARN + VPC egress + TLS cert; re-invoke |

### If OData returns 404 / service_not_found

- The target's MC OData service is not activated. Options:
  - **Option A** (SAP-supported): activate via SICF at
    `/sap/opu/odata4/sap/api_migrationcockpit_project`
  - **Option B** (fallback): use the manual runbook — the Fiori app
    exists on every S/4 release since 1610

### If OData returns 401 / unauthorised

- Grant the service user `S_RFC` + `SAP_MC_MIG_PROJECT_ADMIN` role
- The provisioner does NOT retry silently on 401; it fails cleanly

### Chain the run through the audit ledger

Every provisioning call writes a block to `compliance-ledger`. Verify:

```powershell
aws dynamodb query `
    --table-name migrate4hana-compliance-ledger-prod `
    --key-condition-expression 'chain_id = :c' `
    --expression-attribute-values '{":c":{"S":"run:<run_id>"}}' `
    --scan-index-forward=false --max-items 5
```

Look for `block_type = mc_project_provisioner` with a chained
`prev_hash`/`block_hash`.

## 2. Transport imports

### Dry-run first

Any transport-import invocation can now run with `dry_run: true`:

```powershell
aws lambda invoke `
    --function-name migrate4hana-transport-import-executor-prod `
    --cli-binary-format raw-in-base64-out `
    --payload '{"run_id":"dr-1","transport_id":"M4HK900123","target_sid":"S4H","target_client":"100","dry_run":true,"target_bastion_instance_id":"i-abc"}' `
    out.json
```

Dry-run checks:
- `already_imported` — E070 read via `RFC_READ_TABLE` (SAP-released)
- `staging_path_present` — SSM `ls` in `/usr/sap/trans/data|cofiles`
- `ssm_reachable` — trivial `echo` via SSM to catch stopped bastions

### Result codes

| Status | Meaning |
|---|---|
| `dry_run_ok` | All pre-checks passed; safe to re-invoke without `dry_run` |
| `dry_run_blocked` | See `prechecks` for which check failed |
| `already_imported` | Skip — the transport is already in the target client |
| `success` / `warning_requires_review` / `failed` | Live `tp` invoked; see `tp_return_code` |

### Handling `already_imported`

The tool short-circuits. No `tp` is invoked. The block is logged as
`skipped` in the run summary. Do NOT force a re-import — the E070 check
is defensive; if it wrongly says "imported", investigate the target's
E070C table (import history) before overriding.

## 3. Cutover ECC lock

**Unchanged from v1** — deliberately runbook-driven, not automated.

The `cutover-orchestrator` Lambda emits the SM02 / SU10 / RZ04 / SMQR /
SMQS runbook and awaits `manual_lock_confirmed = true`. This is the
SAP-doctrine approach; freezing WPs programmatically would put the ECC
outside SAP support coverage.

Optional acceleration: the customer may pre-load a `m4h_mass_lock.sh`
script on the ECC host that runs the SU10 mass-lock idempotently, and
authorise the Lambda to invoke it via SSM. Then set
`auto_lock: true` in the event. The script itself is customer-owned.

## 4. Sink health — Salesforce & Snowflake

### 4.1 Salesforce sync

- Live upsert PATCHes `External_Id__c`; DDB `salesforce_sync_status` tracks
  every attempt with `last_status`, `attempt_count`, and the full payload
  cached in `payload_json`.
- `SalesforceSink.retry_failed(tenant_id=...)` re-drives PENDING/FAILED
  rows. Safe to call repeatedly — upsert is idempotent.

Check FAILED-row count for a tenant:

```powershell
aws dynamodb query `
    --table-name salesforce_sync_status `
    --index-name by_tenant_status `
    --key-condition-expression 'tenant_id = :t AND last_status = :s' `
    --expression-attribute-values '{":t":{"S":"acme"},":s":{"S":"FAILED"}}' `
    --select COUNT
```

### 4.2 Snowpipe

- Verifier runs every 15 minutes; emits `RowsLoaded` (per tenant/object)
  + `PipeStuckSeconds` (global).
- If `PipeStuckSeconds > 900`, the pipe is stalled. Escalate to Snowflake
  DBA to inspect `SYSTEM$PIPE_STATUS('m4h_pipe')`.
- If the SNS delivery-failed alarm fires, check the topic subscription in
  Snowflake — usually the STORAGE INTEGRATION lost its external ID.

## 5. Alarm cheat sheet

| Alarm | Trigger | First response |
|---|---|---|
| `mc-project-provisioner-error-rate` | any 5xx in 5m | Check credential secret ARN + OData reachability |
| `mc-project-provisioner-http-401`  | 401 rate > 0 | Rotate service-user password; grant role |
| `transport-import-executor-tp-rc8` | tp returned RC ≥ 8 | Basis lead: STMS_QUEUE → inspect logs, do not retry |
| `salesforce-sync-fail-rate->5%` | rolling 15m | `retry_failed()` after fixing SF issue |
| `snowpipe-sns-delivery-failed` | any 5m | Check Snowflake STORAGE INTEGRATION trust |
| `snowpipe-pipe-stuck-seconds`  | > 900s | Snowflake DBA: `SYSTEM$PIPE_STATUS('m4h_pipe')` |
| `snowpipe-verifier-failed`     | any 5m | Check JWT keypair rotation; secret ARN |
| `cutover-orchestrator-manual-gate-pending` | > 30m | Escalate to on-call Basis lead |

## Contacts

- On-call rotation: PagerDuty `migrate4hana-oncall`
- Escalation: SAP Basis lead + AWS TAM
- Slack: `#migrate4hana-ops`
