# Migrate4HANA On-Call Runbook

> **Audience:** on-call engineer / customer-success TAM during a live customer cutover or post-cutover Continuous DQ run.
>
> **Scope:** prod environment (`migrate4hana-*-prod`). All commands shown in PowerShell since the operator workstation is Windows.
>
> **Last updated:** 2026-06-09 (Path 1 + Group D)

---

## 1. The 30-second triage

When an alarm fires you receive an SNS email (and PagerDuty page if `pagerduty_endpoint` is configured). The alarm name tells you the path:

| Alarm name pattern | First thing to check |
|---|---|
| `m4h-<fn>-errors-prod` | Per-Lambda dashboard `Migrate4HANA-<fn>` → "Recent ERROR logs" widget |
| `m4h-<fn>-p95-latency-prod` | Same dashboard, look at Duration p95 chart vs Concurrent Executions chart |
| `m4h-<fn>-throttles-prod` | Account-level concurrent-exec limit + reserved concurrency on the function |
| `m4h-key-map-throttle-prod` | **§4 — Key-Map ledger emergency.** Cutover may stall. |
| `m4h-key-map-system-errors-prod` | **§4 — Key-Map ledger emergency.** Possible AWS-side fault / corruption. |
| `m4h-dq-violation-rate-prod` | Continuous DQ — recent ruleset change or upstream data regression |
| `m4h-compliance-chain-broken-prod` | **§5 — Compliance archive emergency.** Audit chain damaged. |
| `m4h-ledger-write-failure-prod` | Compliance ledger DDB capacity or auth |

If you are not sure where to start: open **`Migrate4HANA-SLA-prod`** dashboard. The single pane shows error % + p95 + DDB throttle + DQ + Compliance for every function.

---

## 2. Lambda error rate alarm

`m4h-<fn>-errors-prod` fires when 5-min rolling errors / invocations > 1%.

**Diagnose:**
```powershell
$fn = "migrate4hana-continuous-dq-monitor-prod"   # substitute the actual fn from the alarm
aws logs tail "/aws/lambda/$fn" --since 15m --filter-pattern "ERROR" --format short
```

**Common causes + fixes:**
1. **Stale deployed code** (the classic recovery from `aws-lift-shift-ip-drift-recovery`). Compare the deployed zip size with the local zip:
   ```powershell
   aws lambda get-function-configuration --function-name $fn --query "CodeSize"
   ```
   If the local zip is larger, redeploy:
   ```powershell
   aws lambda update-function-code --function-name $fn --zip-file fileb://lambda/dist/$fn.zip
   ```
2. **ECC unreachable** — the ngrok tunnel is down or the laptop rebooted. See `memory/aws-lift-shift-ip-drift-recovery.md` for the 4-step recovery; the short form is:
   ```powershell
   .\scripts\launch-ecc-tunnel.ps1
   ```
3. **S/4 IP drifted** — `EXCEPTION_RAISED CONNECTION_FAILURE` in logs. Re-run:
   ```powershell
   .\scripts\update-s4-secret.ps1
   cd terraform/environments/prod
   terraform apply -target=module.route53 -auto-approve   # only with operator approval
   ```
4. **Secret rotation** — `AccessDeniedException` from Secrets Manager. Check the WS4 IAM role:
   ```powershell
   aws iam get-role-policy --role-name migrate4hana-ws4-lambda-prod --policy-name migrate4hana-ws4-lambda-policy
   ```

**Escalate** if errors persist > 15 min after redeploy: see §8.

---

## 3. Lambda p95 latency alarm

`m4h-<fn>-p95-latency-prod` fires when p95 duration > 30,000 ms over 3 evaluation periods.

**Diagnose:**
- Open the per-Lambda dashboard. Look at the Concurrent Executions chart. If concurrency is at the account limit, p95 climbs because invocations queue.
- Check downstream RTT: most Lambdas talk to ECC via ngrok; a slow tunnel quickly inflates p95. Test:
  ```powershell
  aws lambda invoke --function-name migrate4hana-data-migrator-prod `
    --payload (Get-Content tests/fixtures/smoke-ping.json -Raw) `
    --cli-binary-format raw-in-base64-out out.json; cat out.json
  ```

**Common fixes:**
1. Raise reserved concurrency:
   ```powershell
   aws lambda put-function-concurrency --function-name $fn --reserved-concurrent-executions 50
   ```
2. Restart the ngrok tunnel (see §2 step 2).
3. If the slow path is `pyrfc.Connection.call`, the SAP target may be under load — check ST22/SM50 from SAPGUI.

---

## 4. Key-Map ledger emergency (CRITICAL)

`m4h-key-map-throttle-prod` or `m4h-key-map-system-errors-prod` indicates the F1 cross-run guard is unstable. **This blocks every spine-routed object**: every record gets re-BAPI'd or the BAPI returns a duplicate-key error.

**Immediate actions:**

1. **Pause the active migration run.** Find any in-flight Step Functions execution:
   ```powershell
   aws stepfunctions list-executions --state-machine-arn arn:aws:states:us-east-1:<acct>:stateMachine:migrate4hana-bapi-inplace-prod --status-filter RUNNING
   aws stepfunctions stop-execution --execution-arn <arn-from-above> --cause "key-map-throttle-runbook-4"
   ```

2. **Determine throttle root cause.** Check capacity:
   ```powershell
   aws dynamodb describe-table --table-name migrate4hana-key-map-prod --query "Table.{Status:TableStatus, RCU:BillingModeSummary.BillingMode}"
   ```
   - If `PAY_PER_REQUEST`, throttle is from a partition-key hot-spot. The `tenant_obj` hash is sharded per (tenant, object) — a single tenant migrating one object in a tight loop can saturate ~3000 WCU on that partition.
   - **Mitigation:** lower batch concurrency in the orchestrator:
     ```powershell
     aws lambda update-function-configuration --function-name migrate4hana-data-migrator-prod --environment "Variables={MAX_PARALLEL=8}"
     ```

3. **If `SystemErrors > 0`** — AWS-side fault. Open an AWS Support case (Severity 1 for prod cutover) and proceed to **§6 — DR / corruption recovery**.

**Resume:** restart the paused Step Functions execution from the last successful checkpoint (the cross-run guard makes this safe — already-migrated records short-circuit on ledger hit).

---

## 5. Compliance archive emergency

`m4h-compliance-chain-broken-prod` fires when the compliance archive Lambda's `verify_chain` returned `ok=false`. The hash chain links every immutable block; a break means an archived block's `prev_hash` doesn't match the previous block's `block_hash`.

**Likely causes (in order of probability):**

1. **A new block was written with the wrong prev_hash.** Usually a deployment race — two compliance-archive invocations ran concurrently against the same `(tenant, object_type)` and computed prev_hash from a now-superseded tip.
2. **A block was tampered with.** The DDB ledger row was edited directly (this requires `aws_iam_role/migrate4hana-ws4-lambda-prod` write access — should not happen).
3. **A block is missing from DDB.** Lambda crashed after S3 PutObject but before ledger PutItem. The S3 archive exists but the chain has a gap.

**Diagnose:**
```powershell
$tenant_obj = "default#Material"   # substitute the broken (tenant, object_type)
aws dynamodb query --table-name migrate4hana-compliance-ledger-prod `
   --key-condition-expression "tenant_obj = :k" `
   --expression-attribute-values '{":k":{"S":"'$tenant_obj'"}}' `
   --query "Items[*].{chunk:chunk_idx.N, prev:prev_hash.S, hash:block_hash.S}" --output table
```

Find the block where `prev_hash != previous_row.block_hash`. That's `broken_at_chunk_idx`.

**Recovery:**
- Case 1 (race): identify the duplicate block (two rows with the same `chunk_idx`), confirm with the S3 archive that both gzipped JSONL contents are identical, then **leave both in place + add a new "chain-repair" block** that records the resolved tip. NEVER delete a block — that would break audit.
- Case 3 (gap): the S3 archive is the source of truth. Re-derive the missing ledger row from the S3 object's `Metadata['block-hash']` field and PutItem. This restores the chain without re-archiving (S3 Object Lock would refuse anyway).

**ESCALATE to legal/compliance** immediately. A broken chain in production means we cannot give the customer 7-year tamper-evident audit evidence for the affected `(tenant, object_type)` until the chain is repaired and re-attested.

---

## 6. DR / corruption recovery — see DR.md

If the F1 key-map table is corrupted mid-cutover, follow `docs/DR.md` — the corruption recovery protocol covers:
- PITR restore-to-checkpoint
- Re-derive missing key-map rows from the spine's audit ledger
- Conflict-resolution when a tenant re-keyed a record between corruption time and restore time
- Communications template for the affected customer

---

## 7. Common one-off recipes

### 7.1 Re-pull S/4 credentials after rotation

```powershell
aws secretsmanager get-secret-value --secret-id migrate4hana-s4hana-prod --query SecretString --output text | jq '.ashost'
# If the value looks wrong, run:
.\scripts\update-s4-secret.ps1
```

### 7.2 Force a continuous-DQ scan now

```powershell
aws lambda invoke --function-name migrate4hana-continuous-dq-monitor-prod `
   --payload '{"mode":"scan","objects":["Material","BusinessPartner"]}' `
   --cli-binary-format raw-in-base64-out out.json; cat out.json
```

### 7.3 Verify a compliance chain on demand

```powershell
aws lambda invoke --function-name migrate4hana-compliance-archive-prod `
   --payload '{"mode":"verify_chain","object_type":"Customer"}' `
   --cli-binary-format raw-in-base64-out out.json; cat out.json
```

### 7.4 Snowflake stage backlog check

```powershell
aws s3 ls s3://migrate4hana-snowflake-stage-prod/snowflake-stage/ --recursive --summarize | tail -2
```
If `Total Size` keeps growing without dropping, Snowpipe isn't ingesting. Check the per-tenant pipe status in Snowflake.

---

## 8. Escalation matrix

| Severity | Examples | Escalate to |
|---|---|---|
| SEV-1 | key-map throttle during active cutover; compliance chain broken; production S/4 connection lost > 30 min | Founder (Ravi) + AWS Support SEV-1 |
| SEV-2 | Sustained Lambda errors > 15 min on a single function; DQ violation rate > 25% for 2+ scans | Founder (Ravi) |
| SEV-3 | Snowflake stage backlog; non-prod alarms; expected behavior triggered by config | Backlog ticket |

**Founder contact:** ravitejadevops1992@gmail.com (see `memory/user-context-2026-06-02.md` — solo founder, single-pager arrangement).

---

## 9. Post-incident checklist

After every SEV-1 / SEV-2:
1. Write a short timeline + root cause in `docs/incidents/YYYY-MM-DD-<slug>.md`
2. If an alarm was missing or noisy, update `terraform/modules/observability/main.tf` thresholds — and the runbook
3. If an automation gap was exposed, file it as a `roadmap` task
4. If a customer was impacted, send the founder the communication draft within 24h

---

*This runbook is referenced from the `Migrate4HANA-SLA-prod` CloudWatch dashboard markdown widget.*
