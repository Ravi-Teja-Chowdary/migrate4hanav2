# Migrate4HANA — Disaster Recovery Plan

> **Audience:** founder (Ravi) + on-call.
>
> **Scope:** Tier-0 data stores — the ones whose corruption breaks an active customer cutover. Everything else (S3 staging, CloudWatch logs, lambda code) is rebuildable from git + a re-run.
>
> **Last updated:** 2026-06-09

---

## 1. Tier-0 inventory

| Resource | What it holds | Loss cost | RPO target | RTO target |
|---|---|---|---|---|
| `migrate4hana-key-map-prod` (DDB) | F1 cross-run guard — **every (object, source_key) → target_key mapping migrated to date** | Every replay re-creates BAPI rows that already exist → duplicate-key errors or duplicated entities | 5 min | 30 min |
| `migrate4hana-compliance-ledger-prod` (DDB) | Hash-chained per-chunk archive proofs | Audit chain breaks → 7-year compliance evidence is no longer tamper-evident | 5 min | 60 min |
| `migrate4hana-compliance-archive-prod` (S3 + Object Lock COMPLIANCE) | The actual archived legacy data | Customer loses legal-discovery / audit-response capability | 0 (S3 has 11 9s + Object Lock makes it immutable for 10y) | n/a |
| `migrate4hana-dq-findings-prod` (DDB) | Continuous DQ post-cutover signals | Lose the trend history; current scans still work | 1 hour | 4 hours |
| `migrate4hana-evidence-prod` (S3 + Object Lock) | WS1/WS2 evidence WORM | Audit evidence lost | 0 | n/a |

The compliance-archive S3 bucket is the only Tier-0 resource we cannot lose by ANY mechanism within the retention horizon — Object Lock COMPLIANCE mode prevents deletion even by AWS root. The DDB tables are the recoverable ones.

---

## 2. Backup strategy

### 2.1 Point-In-Time Recovery (PITR) — always on

Every Tier-0 DDB table has `point_in_time_recovery { enabled = true }` baked into terraform. PITR gives 35-day continuous recovery to any second.

**Verify:**
```powershell
aws dynamodb describe-continuous-backups --table-name migrate4hana-key-map-prod `
  --query "ContinuousBackupsDescription.PointInTimeRecoveryDescription"
```
Output must contain `"PointInTimeRecoveryStatus": "ENABLED"`. If not, **STOP**: every cutover is at risk until PITR is on.

### 2.2 On-demand snapshots — at cutover boundaries

PITR alone is good but not enough at the cutover boundary. The cutover boundary is when the legacy SAP is decommissioned and S/4 becomes the system of record — at that exact moment, the F1 ledger is the *only* artifact that tells us what was migrated.

**Operator MUST take an on-demand snapshot:**
- 1 hour BEFORE cutover-cutoff
- Immediately AFTER the cutover Step Functions execution succeeds
- Once every 6 hours during a multi-day phased cutover

Use the included script:
```powershell
.\scripts\backup-key-map.ps1 -Table migrate4hana-key-map-prod -Tag pre-cutover-acme
```
The script tags the backup with the run-id + a human-readable label so the restore script can find it later.

### 2.3 Cross-region replication — defense-in-depth

Set `M4H_KEY_MAP_CROSS_REGION=us-west-2` in the prod environment to enable DynamoDB Global Tables replication. (Disabled by default — adds ~$30/mo/table and a write-amplification cost.) Recommended for any customer over $1M ARR.

---

## 3. Corruption taxonomy

| Class | What "corrupted" actually means | Detection signal |
|---|---|---|
| **C1 — Logical** | Some rows have wrong `target_key` (e.g. operator ran a migration with the wrong tenant_id, mappings registered against the wrong customer) | Reconciler `verify_key` returns DISCREPANCY for a contiguous block of rows |
| **C2 — Partial loss** | Some rows are missing (Lambda crashed after S3 PutObject but before DDB PutItem) | F1 ledger-hit short-circuit fails for a record the audit log says was loaded; or `verify_chain` ok=false |
| **C3 — Schema break** | A field was renamed/dropped under us (DDB allows this — schemaless) | Lambda throws KeyError on resolve / parse |
| **C4 — Total loss** | Table dropped (operator typo, account compromise) | `ResourceNotFoundException` on every DDB call |
| **C5 — Tamper** | A row was edited directly via DDB console / API | `lineage_hash` mismatch on resolve |

The MOST likely cause in practice is **C1 wrong-tenant or C2 partial loss during a Lambda timeout.** C4 has only happened once in tests (an `-auto-approve` typo on a destroy plan; we now require explicit operator approval for any destroy targeting key_map).

---

## 4. The headline question — corruption MID-CUTOVER

> **Q:** What happens if `migrate4hana-key-map-prod` gets corrupted mid-customer-cutover?

The answer depends on which class of corruption it is. The cutover does NOT auto-abort — it keeps running. Each spine-routed BAPI call proceeds as normal because the F1 ledger short-circuit is *advisory*, not gating: if `key_map.resolve()` returns `None` (or a wrong value), the spine still calls the BAPI. The BAPI is the source of truth.

### 4.1 Behaviour by corruption class

| Class | What happens NEXT | Operator action |
|---|---|---|
| C1 — Logical | Spine re-attempts BAPI for records whose `resolve()` returns a wrong target. The S/4 side returns a **duplicate-key error** or creates a wrong target if no key-conflict check exists. Reconciler will flag DISCREPANCY post-run. | **§4.2 — Stop, restore, replay.** |
| C2 — Partial loss | Same as C1 from the spine's perspective. The "missing" records get re-BAPI'd; SAP typically rejects them with `OBJECT_ALREADY_EXISTS`. Dead-letters accumulate. | **§4.3 — Continue + heal afterwards.** Safe to ride out and rebuild the key_map from BAPI duplicate-key responses. |
| C3 — Schema break | Spine crashes on the next resolve. Step Functions execution fails. | **§4.4 — Fix the code, restore.** |
| C4 — Total loss | First `resolve()` raises `ResourceNotFoundException`. Lambda errors land in the alarm. | **§4.5 — Emergency PITR restore.** |
| C5 — Tamper | Spine continues with the tampered (wrong) target. Same downstream effect as C1. | **§4.2 — Stop, restore, replay.** |

### 4.2 C1 / C5 recovery — Stop, restore, replay

This is the most aggressive recovery path. Use only when reconciliation shows widespread DISCREPANCY (>5% of rows).

```powershell
# 1. Stop the active run immediately
$exec = aws stepfunctions list-executions `
  --state-machine-arn arn:aws:states:us-east-1:<acct>:stateMachine:migrate4hana-bapi-inplace-prod `
  --status-filter RUNNING --query "executions[0].executionArn" --output text
aws stepfunctions stop-execution --execution-arn $exec --cause "DR-runbook-4.2"

# 2. Identify the corruption window (when did wrong mappings start landing?)
# Find the run_id of the contaminated writes:
aws dynamodb scan --table-name migrate4hana-key-map-prod `
  --filter-expression "run_id = :r" `
  --expression-attribute-values '{":r":{"S":"<contaminated-run-id>"}}' `
  --query "Count"

# 3. Restore PITR to T-just-before-contamination (e.g. T-30min)
.\scripts\restore-key-map.ps1 -Table migrate4hana-key-map-prod `
  -ToTimestamp "2026-06-09T13:45:00Z" -RestoreAs migrate4hana-key-map-prod-restored

# 4. Verify the restored table looks right (spot-check 20 known mappings)
.\scripts\backup-key-map.ps1 -Table migrate4hana-key-map-prod-restored -VerifyOnly

# 5. Atomic swap -- operator approval REQUIRED before this step
.\scripts\swap-key-map.ps1 -Current migrate4hana-key-map-prod `
  -RestoredFrom migrate4hana-key-map-prod-restored -ConfirmYes

# 6. Replay the migration runs that landed inside the corruption window
# The ledger short-circuit will skip already-good rows; only the
# contaminated ones get re-BAPI'd. This is exactly the cross-run-guard
# scenario the spine was designed for.
```

### 4.3 C2 recovery — Heal in place

Partial loss is the most common form. The compliance audit ledger has every record that was archived; the BAPI dead-letter queue has every record SAP rejected. Reconstruct missing key_map rows from both:

```powershell
# 1. Identify which (object, source_key) pairs reconcile FAILED for
aws lambda invoke --function-name migrate4hana-reconciliation-engine-prod `
  --payload '{"mode":"emit_missing_keymap"}' --cli-binary-format raw-in-base64-out missing.json
cat missing.json | jq '.results[] | select(.in_s4=="yes" and .in_keymap=="no")'

# 2. The compliance archive has the per-row hashes -- correlate:
aws lambda invoke --function-name migrate4hana-compliance-archive-prod `
  --payload '{"mode":"extract_keymap_hints","object_type":"Customer"}' `
  --cli-binary-format raw-in-base64-out hints.json

# 3. Replay rebuild via the dedicated heal-keymap script
.\scripts\heal-key-map.ps1 -Missing missing.json -Hints hints.json `
  -Table migrate4hana-key-map-prod -DryRun
# When dry-run output looks sane, drop -DryRun.
```

### 4.4 C3 recovery — Fix the code, restore

The schema is implicit (DDB is schemaless). If a lambda commit dropped a field the spine relies on:

1. `git revert` the offending commit.
2. `aws lambda update-function-code` to redeploy the working version.
3. C1 / C2 may also apply if rows were written under the bad code — follow §4.2 or §4.3 for those rows.

### 4.5 C4 recovery — Emergency PITR restore

Table is gone. Every Lambda alarms on `ResourceNotFoundException`. Step Functions execution fails.

```powershell
# 1. PITR restore -- the latest recoverable point is typically ~5 min back
aws dynamodb restore-table-to-point-in-time `
  --source-table-name migrate4hana-key-map-prod `
  --target-table-name migrate4hana-key-map-prod-recovered `
  --use-latest-restorable-time

# 2. Wait for table state ACTIVE (usually 5-15 min for a typical migration table)
aws dynamodb describe-table --table-name migrate4hana-key-map-prod-recovered `
  --query "Table.TableStatus"

# 3. Re-attach PITR + SSE + deletion protection (these are NOT restored automatically)
aws dynamodb update-continuous-backups --table-name migrate4hana-key-map-prod-recovered `
  --point-in-time-recovery-specification PointInTimeRecoveryEnabled=true
aws dynamodb update-table --table-name migrate4hana-key-map-prod-recovered `
  --deletion-protection-enabled

# 4. Re-point Lambda env vars (this is the truth source for the table name)
# Update terraform variable + apply, OR for emergency, update env vars directly:
aws lambda update-function-configuration `
  --function-name migrate4hana-data-migrator-prod `
  --environment "Variables={M4H_KEYMAP_TABLE=migrate4hana-key-map-prod-recovered, ...}"

# 5. Once the run is stable, atomic-swap the names back so terraform stays the source of truth.
```

---

## 5. Conflict resolution — when restored ≠ current

After a PITR restore, some legitimate writes may have landed AFTER the restore point but BEFORE the corruption event. We need to merge those forward.

**Source of truth ordering (highest to lowest):**
1. **BAPI duplicate-key responses** (`OBJECT_ALREADY_EXISTS` returned by SAP) — SAP is the system of record. If SAP says the record exists, it does, regardless of what key_map says.
2. **Compliance ledger row** (`migrate4hana-compliance-ledger-prod`) — every archived row was a real row at archive time.
3. **F1 key_map row** — second-class truth: derived from #1 and #2.

The heal script (`scripts/heal-key-map.ps1`) implements this ordering. NEVER hand-edit key_map rows without consulting the BAPI response history — you'll inject the same kind of corruption the restore was trying to fix.

---

## 6. RTO / RPO commitments

| Scenario | RPO | RTO |
|---|---|---|
| Mid-cutover Lambda crash, recoverable by PITR | 5 min (PITR continuous) | 30 min (decision + restore + swap) |
| Tenant-wide logical corruption | 5 min | 2 hours (restore + reconcile + replay) |
| Cross-region failover | 30 sec (global tables) | 60 min |
| Compliance chain repair | 0 (S3 immutable) | 4 hours (repair + re-attest) |

These are commitments to the founder for prod SLA. Communicate them to the customer at contract time. They are NOT verified by quarterly drill yet — see §8.

---

## 7. Communication template — customer notification

> Subject: [SEV-1] Migrate4HANA — temporary cutover pause
>
> Hi <customer>,
>
> At <UTC time> we detected an issue with the cross-run guard table for your active migration run (`<run-id>`). We paused the run immediately. The S/4 records loaded BEFORE the pause are valid and recoverable — the compliance archive holds tamper-evident proof.
>
> Recovery ETA: <RTO from §6>.
>
> What this means for you:
> - No data was lost — Object Lock + PITR protect the legacy archive and the mapping ledger.
> - Already-migrated records will NOT be re-loaded — the cross-run guard ensures idempotency.
> - Records in-flight at pause time will be re-attempted on resume.
>
> We will send you a post-incident report within 24 hours of resolution.
>
> — Ravi

---

## 8. Drill schedule

Drill the following procedures quarterly in a copy of prod (`migrate4hana-key-map-staging-drill`):

- Q1: PITR restore + atomic swap (§4.5)
- Q2: C2 heal-in-place (§4.3)
- Q3: Compliance chain repair (RUNBOOK §5)
- Q4: Cross-region failover (only if Global Tables enabled)

Each drill writes a one-page report to `docs/incidents/drill-YYYY-QN.md`. If the actual RTO exceeds the §6 target, file a follow-up to close the gap.

---

## 9. Operator approvals (who can do what)

Per `memory/user-context-2026-06-02.md` — solo founder, single operator. The "approvals" below are self-checks Ravi performs at decision points; for v1.0 they're a discipline, not a gate.

- ANY destructive PITR action (delete original table, force-rebuild from snapshot): explicit "yes I confirm" required (`-ConfirmYes` flag on every script).
- ANY operation that writes to a customer's prod tenant: requires the tenant_id passed explicitly, no shortcuts.
- ANY restore that overwrites a Tier-0 table: take an on-demand snapshot FIRST.

When the team grows past 1 person, convert §9 into IAM SCPs.

---

*This DR plan is referenced from the Group D observability alarms — when `m4h-key-map-throttle-prod` or `m4h-key-map-system-errors-prod` fires, the alarm message links here.*
