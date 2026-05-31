# Migrate4HANA — Independent Review Brief

*Prepared for an SAP data-migration / S4 conversion specialist. The goal of this document
is an honest assessment of where the tool stands — gaps are stated deliberately so your
review is efficient. Nothing here is marketing; please challenge any claim.*

**Date:** 2026-05-31 · **Branch reviewed:** `aws-lift-and-shift` · **Build status:** working prototype on a live system pair; **full AWS prod stack provisions and tears down cleanly end-to-end** (200 resources, see §13).

> **2026-05-29 update:** four "competitive-parity" layers + a fresh light-themed Project Tracker UI
> were added (commit `0e7b7e0`). They are **self-tested deterministically but NOT yet integrated into
> the live ECC→S/4 loop** — see **§10** for what each does, **§11** for the honest head-to-head vs
> SmartShift / Syniti / Natuvion.
>
> **2026-05-31 update (commits `6e4a689` + `1ebea30`):**
> - **AWS prod stack now apply→destroy idempotent end-to-end** (200 resources). Root-cause fixes for
>   every class of stuck-state failure (secrets pending-deletion, S3 Object Lock race, WAF/tag ASCII
>   constraints, ASL placeholder ARNs, dashboard region property) are committed in source — see §13.
> - **Bedrock removed; replaced by direct Anthropic API** (`api.anthropic.com` over NAT egress, key
>   in Secrets Manager). Default model `claude-sonnet-4-6`; retry escalates to `claude-opus-4-7`. The
>   pseudonymizer (reversible PII masking) still runs and matters more now. **All Bedrock-named
>   plumbing also removed** — IAM `bedrock:InvokeModel`, both Bedrock PrivateLink VPC endpoints,
>   `BEDROCK_MODEL_ID` env var, and the misleadingly-named `bedrock-llm-router` Lambda (renamed
>   `code-analyzer`). Reason: this AWS account has no Bedrock model access.
> - **Pillars 1.1 / 1.2 / 3 AWS infra now live, not just unit-tested** (see §12 rewrite). Fargate task
>   def, ECR repo, Step Functions `waitForTaskToken` gates (4 instances), SNS gate topic, signed
>   `/api/spine/approve` webhook — all provisioned by the prod stack and survive destroy/re-apply.
> - **One-command Fargate image push** — `.\scripts\push-fargate-image.ps1` (pre-flight, ECR login,
>   build, push, verify, warn about running tasks). Required once after each `terraform apply`.
> - **Intentional regression from previous §12 claim:** **S3 Object Lock WORM removed** from the
>   evidence + audit-logs buckets (per user directive 2026-05-30) so `terraform destroy` is clean
>   during the inner-loop test cycle. Re-enable for real prod by setting `object_lock_enabled = true`
>   at bucket creation (cannot toggle on later) and restoring `aws_s3_bucket_object_lock_configuration`.
>   Inline comments in `evidence-ledger/main.tf:64-68` document the exact change.
> - **Eight SAP-functional-depth gaps closed in code** (driven by a peer SAP-expert review): CVI
>   unification, target-side TH_WPINFO/NRIV throttle, BAPI field-coverage → LTMC fallback,
>   FAGLB03/MB5B spool capture, dual-maintenance code-delta engine, cross-field DQ, cluster-table
>   aware extraction, DAG dependency resolver + KeyResolver. All seven new modules + one
>   transformation_engine extension ship with green self-tests. See **§14** for the full inventory,
>   what's verified, and what's still owed for production-completeness.

---

## 1. What it is (and is not)

Migrate4HANA is a **support-clean, highly-automated ECC → S/4HANA *data-migration* engine** for the
**greenfield / selective-data-transition** lane. It extracts master and transactional data from an
ECC source and writes it into an S/4HANA target **exclusively through SAP-released APIs** (released
BAPIs over RFC + the `API_BUSINESS_PARTNER` OData service), with end-to-end reconciliation,
idempotency, delta/CDC, connection-pool parallelism, and a governed cutover gate.

**It is explicitly NOT:**
- a Brownfield in-place conversion — it does **not** run, wrap, or bypass **SUM / DMO** or the
  **Maintenance Planner**;
- a replacement for the **Migration Cockpit (LTMC/LTMOM)** field-mapping layer — see §6;
- a data-quality / cleansing / value-mapping rules engine (§6.4);
- proven in customer production (§7).

It plays the **same lane as the S/4HANA Migration Cockpit** (data load), with substantially more
automation wrapped around the load (auto-discovery, reconciliation, idempotency, dead-letter,
cutover orchestration).

---

## 2. The environment it has been proven on

| | Source | Target |
|---|---|---|
| System | ECC (IDES-class content, SID Y01) | S/4HANA (SAP CAL free-trial appliance, best-practice content) |
| Access | pyrfc / RFC, client 800 | pyrfc/RFC client 100 + OData (HTTPS) |
| Hosting | VM on a workstation | AWS EC2 (single appliance) |

Both are **real SAP systems with real APIs and real reconciliation** — not mocks. **Caveat a
reviewer must weigh:** this is **non-production, non-customer data**, on a **single best-practice
appliance**, at **small per-object sample sizes** (typically 5 records/object for the functional
proofs; one volume test at ~1k documents). It has **not** been run against a second landscape or
customer-shaped data. See §7.

---

## 3. Architecture — the migration spine

Every object flows through one governed pipeline:

```
delta/CDC extract (ECC)
   → target config auto-discovery (company code, sales area, plants, recon accounts,
       cost/profit centers, charts, order types, structure indicators, …)
   → best-mechanism load: released BAPI (RFC) or OData, picked per object by a dispatcher
   → collision-safe key strategy (source→target mapping recorded)
   → cross-run idempotent ledger (re-run resumes, never duplicates)
   → reconciliation: read every loaded record back, tie out EXISTENCE and (where applicable) VALUE
   → dead-letter for genuine failures (reprocess via idempotent re-run)
   → support-compliance attestation
   → cutover GO / NO-GO runbook
```

Key components (paths for your review):
- `lambda/utils/unified_loader.py` — the dispatcher: `OBJECT_MECHANISM` (object → BAPI/OData/IDoc),
  `OBJECT_SOURCE_KEY` (ledger key, incl. composite keys), `_load_one` branches, serial + pooled-parallel paths.
- `lambda/utils/bapi_loader.py` — one `create_<object>` per object type (the released-API calls + the
  discovery/validation/remap logic). **This is the file to scrutinize for SAP correctness.**
- `lambda/utils/config_discovery.py` — landscape-agnostic target config (probe-validated, e.g. a
  rolled-back test PO to confirm the expense account).
- `lambda/utils/reconciler.py` — existence + value reconciliation, `RECONCILED`/`DISCREPANCY` verdict.
- `lambda/utils/key_map.py` — the durable cross-run ledger.
- `lambda/data-migrator/handler.py` — `DEFAULT_OBJECT_TABLES`: the object catalog (source table +
  fields + lane) — 127 objects.

---

## 4. Evidence — what is proven live (load + reconcile)

**25 object types are loaded into S/4 via released APIs and reconciled** (read back; `RECONCILED`,
0 missing) on the live pair:

BusinessPartner, Customer, Vendor (OData `API_BUSINESS_PARTNER`), Material, ExchangeRates,
OpenPO, OpenAR, OpenAP (FI), CostCenter, ProfitCenter, FixedAsset, Bank, InternalOrder, Equipment,
FunctionalLocation, Characteristic, Class, CostElementGroup, ProfitCenterGroup, Project/WBS,
PurchaseRequisition, Sales Order, PurchaseContract, Batch, InventoryBalance (GR mvt 561).

Production-grade behaviours demonstrated (each on the live system):
- **Auto-discovery** of a coherent target config from whatever system it connects to.
- **Collision-safe keys** — material MATNR remap; FuncLoc label reformatted to the target structure
  indicator's editing mask; Project ID sanitized against the coding mask; recorded source→target.
- **Idempotent ledger** — re-run reused records, created 0 duplicates.
- **Delta/CDC** — change-document (CDHDR) driven, not just new records.
- **Value reconciliation** — FI amounts, factor-aware exchange rates; caught a real MATNR collision.
- **Parallel load** — ~936 FI documents in ~100s, 936/936 reconciled (pyrfc releases the GIL).
- **TESTRUN-validate-and-fallback** — asset class, order type, contract-capable vendor.
- **Self-healing** — currency normalization (obsolete DEM → target local currency); MM posting-period
  auto-detection for stock postings.
- **Cutover runbook** — initial load → delta → reconcile → GO/NO-GO (verdict: GO).
- **Compliance attestation** emitted per run.

**How to verify yourself:** every run writes `runs/<id>/data-migrator/summary.json` (reconciliation
verdict, attestation, key map, discovered config, dead-letter). Commit history on `aws-lift-and-shift`
has one commit per object with the live test result quoted.

---

## 5. Support-compliance posture (the "without losing SAP support" question)

- **Every write** goes through a **released** BAPI or the released `API_BUSINESS_PARTNER` OData
  service. No raw table writes, no `SE16N` edits, no arbitrary ABAP execution, no SUM/MP bypass.
- The tool **explicitly rejects** support-breaking shortcuts; where it hit a customizing gap
  (exchange-rate types), it **packaged a transport-grade delta** rather than poke tables.
- Reconciliation is read-only (`RFC_READ_TABLE` / API reads).
- Each run emits a machine-checkable attestation of the above.

**For your review:** please sanity-check that the specific BAPIs used are the *released* variants and
that the calling conventions (commit handling, `BAPI_TRANSACTION_COMMIT`, number ranges, mandatory
fields) are idiomatic and won't create inconsistent records at scale.

---

## 6. Honest limitations — please scrutinize these hardest

### 6.1 "Harmonization" of dependent keys is a demonstration, not faithful migration
For several dependent/transactional objects the tool currently **harmonizes source business keys to
existing target-ready masters** rather than migrating them 1:1, because the source masters don't yet
exist in the target appliance:
- **Sales Order** sold-to and item material → an existing sales-ready customer/material in the target.
- **PurchaseContract** vendor → a TESTRUN-validated target vendor.
- **Batch / InventoryBalance** material+plant → a discovered target batch-managed / stocked material.
- **FunctionalLocation / Project** labels → reformatted to the target mask.

This proves the **load + reconcile mechanism** works for those object types, but it is **not** a
faithful migration of those specific records. In a real project these objects depend on the prior
faithful migration of their master data (customer, material, vendor) and on **source→target value
mapping**. Treat these object types as "mechanism proven," not "migration proven."

### 6.2 102 of the 127 catalog objects are extract-only (not loaded/reconciled)
The catalog (`DEFAULT_OBJECT_TABLES`, 127 objects) breaks down as **25 loaded+reconciled** via the
BAPI/OData spine and **102 routed to the MC/IDoc lane**, where the tool **extracts from ECC and emits
a Migration-Cockpit-staging template** — the **actual MC import and the field-level mapping are not
done by this tool**. 15 of the 102 extracts were smoke-tested live (all returned real rows); the
other ~87 are source-table descriptors not yet extract-verified. **Do not read "127" as "127
migrated."** The honest figure is **25 end-to-end + 102 extract-staged**.

### 6.3 No transformation / value-mapping rules engine (the LTMOM-equivalent)
The hardest, most labour-intensive part of a real migration — **field-level transformation rules,
value mapping (e.g. cross-chart-of-accounts, org-unit remap tables, unit/currency conversions),
and target-customizing-aware validation per object** — is **largely not built**. The tool does
targeted, per-object normalizations (currency, order type, asset class) but there is **no general
mapping/rules layer**. This is where most migration-project effort goes; a reviewer should weigh the
tool accordingly.

### 6.4 No data-quality / pre-load cleansing
No duplicate detection, completeness checks, or pre-load validation against target customizing beyond
the per-object TESTRUN checks. No reconstruction of source data quality issues.

### 6.5 Scale
Volume proven once at ~1k documents. Real migrations are 10^6–10^8 records. Throughput, restart at
scale, ledger size, and the reconciliation read-back cost at volume are **unproven**.

### 6.6 Functional coverage depth
Where loaded, objects use **minimal valid field sets** (the fields needed for a consistent create),
not the full business field complement. E.g. a sales order is header + one item + schedule line; a
contract is header + one nominal item. Real records carry far more (partners, conditions, texts,
statuses, custom Z-fields).

### 6.7 No customer pilot, no second landscape
TRL ~6. Not run outside the build appliance. The team's SAP functional/Basis depth is **engineering-
led, not consultant-led** — please flag any non-idiomatic SAP usage you spot.

---

## 7. Maturity assessment (our own, for you to confirm or correct)

- **TRL ~6** — demonstrated end-to-end in a relevant environment (real ECC + real S/4, real APIs,
  real reconciliation), at modest volume, support-clean. **Not** TRL 8–9 (operational, multi-customer).
- **Differentiator vs Migration Cockpit:** the automation *around* the load — auto-discovery,
  cross-run idempotency, existence+value reconciliation with a hard verdict, dead-letter, and a
  signed cutover gate. MC gives you the mapping UI and the load; it does not give you this
  trust/automation spine out of the box.
- **The gap vs a production product:** the mapping/rules layer (§6.3), faithful dependent-key
  migration (§6.1), real loaded breadth beyond 25 (§6.2), scale (§6.5), field depth (§6.6), and a
  pilot (§6.7).

---

## 8. Questions we'd most value your judgement on

1. Are the **released BAPIs / OData** we use the correct, supportable choices per object, and are the
   calling conventions safe at scale (commit/rollback, number ranges, mandatory fields)?
2. Is the **harmonization approach (§6.1)** an acceptable bridge for a demo, and what is the right
   design for **faithful dependent-key migration** (load order, key-mapping tables, dependency graph)?
3. How big a blocker is the **missing transformation/mapping layer (§6.3)** — would you build it, or
   lean on **LTMOM/LTMC** for mapping and keep this tool for orchestration + reconciliation?
4. Does **existence + value reconciliation with a hard verdict** meaningfully de-risk a migration in
   your experience, or do auditors require something else (e.g. SAP standard recon reports, FI/CO tie-out)?
5. For a **selective data transition** at a real customer, where would this tool genuinely save
   effort, and where would it be in the way?
6. What would you require to consider a **pilot** (object scope, volume, landscape, governance)?

---

## 9. One-paragraph honest bottom line

A genuinely strong, support-clean, architecturally-differentiated **ECC→S/4 data-migration
*orchestration + reconciliation* engine**, with **25 object types proven end-to-end** on a live
system and a **127-object catalog** routed to lanes. Its trust spine (discovery, idempotency,
reconciliation, cutover) is real and unusual. It is **not yet** a faithful, full-scope, mapping-
complete, volume-proven, pilot-validated migration product — and the largest remaining work (the
transformation/mapping layer and faithful dependent-key migration) is exactly the part real projects
spend the most on. We're seeking your read on whether the spine is worth building the rest around.

---

## 10. Competitor-grade engines — now embedded INSIDE our stages (2026-05-29; verified offline, live-proof pending)

These started as standalone modules; they are now **wired into the migrate4hana stage handler that owns
each competitor's field** — so the expertise lives *inside* the stage, not as a separate parallel spine.
**Honest status:** each integration **runs green in an offline functional test (local-AWS shim)**, but has
**not** been validated on the live ECC/S4 pair at volume; the LLM path calls **real Bedrock only when
configured** (offline → quarantine); and the ATC gate is a **mock**. Treat as **TRL 4–5 (integrated,
component-verified)** beside the **TRL ~6** live data spine of §3–4.

| Competitor field | Embedded into stage | Engine + what it does | Verified (offline) | NOT yet |
|---|---|---|---|---|
| **SmartShift** — automated code remediation | `lambda/code-analyzer` · `auto_remediate_with_ast_engine` | Deterministic 6,400-line AST first; on a parser **crash or residual parse-errors** it escalates only that program to the AI fail-safe (`llm_fallback_router.FallbackRouter`) → localized **Bedrock** fix → **mock-ATC** gate → transport `.data/.cofile` or quarantine | functional test: deterministic remediate ok + AI-failsafe path reachable (`AI-FAILSAFE` change emitted) | live run vs real ECC custom code; **real ATC**; real-Bedrock fix %; equivalence/regression testing; scale |
| **Syniti** — data quality / integrity | `lambda/data-hygiene` (was a pass-through **stub**) | Now runs the **data spine**: entity-tree FK integrity (BUT000/020/100; orphans quarantined), deterministic org-attribute self-heal vs target reference data, SHA-256 idempotency ledger | functional test: `data_spine` mode, 1 self-healed, 1 orphan quarantined, FK status reported | a general value-mapping/rules engine; DQ scorecards + cleansing library; mapping UI; live entity-tree feed at volume |
| **Natuvion** — selective carve-out | `lambda/data-migrator` extract · `_carve_out_programs` | Generates org(`BUKRS`)/time(`GJAHR`)-filtered, `OPEN CURSOR…PACKAGE SIZE`-streamed, dependency-aware (line→`BKPF`) in-system carve-out ABAP for carve-eligible tables in the run; attached to the run summary | functional test: 2 programs generated (OpenAR→BSID, OpenPO→EKKO) with org/time filters | in-system **deploy at volume** (gated); company-code/client split; consolidation harmonization content |

Engine source: `data_spine_orchestrator.py`, `lambda/code-analyzer/llm_fallback_router.py`,
`agent/in_system_agent_generator.py`. Supporting (standalone, not the primary path):
`pipeline_spine_master.py` (alt 4-phase orchestrator + `RFCThrottle` anti-DoS) and
`scripts/stress_test_generator.py` (100× Lambda fan-out, 1 % chaos — the **10M-row AWS run is still
user-executed**).

**UI (rebuilt 2026-05-29):** the old mock-driven UI was deleted and replaced by a fresh fluidic
light-theme React app that is **100 % real-backend-driven (no mock data)** — honest offline/empty states,
a **Project Tracker** (Start/End boards, progress pipeline, Completed/In-Progress/Queued kanban over the
real 28 stages, each stage tagged with its embedded engine), and a Command Center exposing every CLI
action. Verified: `npm run build` clean, dev server serves all routes; pixel/UX review still pending.

**For your review:** the §6 limitations still stand. §10 narrows two on paper — §6.3 (a first FK+self-heal
layer now runs *inside* data-hygiene) and the §4 governance gap (an ATC-style gate now runs *inside*
code-analyzer, though mock) — but **none of §10 changes the live-proven evidence in §4.** Judge these as
integrated design, not live delivery.

---

## 11. Honest head-to-head: are we competitive with SmartShift / Syniti / Natuvion?

Short answer: **competitive in *architecture and orchestration*; not yet competitive in *depth, content,
and proof* in any of the three vendors' core specialities.** Per area:

| Their speciality | Where we stand | Verdict | To become competitive |
|---|---|---|---|
| **SmartShift — automated custom-code remediation at scale** | Real 6,400-line AST engine + 4-level fixers + deterministic-first/AI-fallback **now embedded in the `code-analyzer` stage** (crash/parse-error → localized AI fix → mock-ATC gate). | **Partial.** Engine is real and the architecture is sound and now wired into the stage; our *ruleset breadth, automation %, regression/equivalence testing, real ATC, and scale proof* are far below SmartShift's mature platform. | Real ATC integration; an automated before/after **equivalence-test** harness; expand the simplification ruleset; prove auto-fix % on a large real custom-code base; CI over the fixer. |
| **Syniti — data quality, mapping, governance, reconciliation** | Strong **reconciliation** (existence+value, hard verdict) + cross-run **idempotency ledger** (now SHA-256) + **FK-integrity + deterministic self-heal now running inside the `data-hygiene` stage** (was a stub). | **Partial.** Our reconciliation/idempotency/FK-heal are genuinely strong and unusual; we still lack Syniti's **value-mapping/rules engine, DQ scorecards & cleansing library, and business-user mapping/governance UI**. | Build the general mapping/rules layer (§6.3); a DQ rule library + scorecard; a mapping UI; data-owner workflow/sign-off. |
| **Natuvion — selective data transition / carve-outs / consolidation** | Carve-out ABAP generator (org+time filters, dependency-aware, streamed) **now embedded in the `data-migrator` extract stage**; greenfield/SDT lane positioning. | **Gap→Partial.** We *generate* a governed carve-out inside extract; we have **not** proven deploy at volume, nor built company-code/client split or system-consolidation harmonization content. | Live carve-out at volume; selective company-code/time-slice split; harmonization rules for consolidation; faithful dependent-key migration (§6.1). |

**Where we already beat the field for our lane:** the **trust spine** — auto-discovery + existence/value
reconciliation with a hard GO/NO-GO + cross-run idempotency + dead-letter + support-clean attestation —
is more automated and more auditable out-of-the-box than the stock Migration Cockpit, and is a credible
differentiator none of the three give you for free in exactly this shape.

**The blunt bottom line for a reviewer:** today this is **one strong, support-clean, live-proven
orchestration+reconciliation spine (25 objects)** into which **three competitor-grade engines are now
embedded in their respective stages and verified offline** — SmartShift-class remediation in
`code-analyzer`, Syniti-class FK+self-heal+ledger in `data-hygiene`, Natuvion-class carve-out in
`data-migrator`. That moves us from "separate prototypes" to "integrated capability," but **not yet** to
"competitive in their home turf," which still needs: (1) the **general mapping/transformation + DQ layer**
(closes the Syniti gap and §6.3), (2) **real ATC + equivalence-testing + scale** for the code fixer
(closes the SmartShift gap), (3) **live, volume-proven carve-out + consolidation content** (closes the
Natuvion gap), and (4) **a customer pilot on a second, customer-shaped landscape** (§6.7). The
architecture and the in-stage wiring now exist; the depth, content, and live-at-scale proof do not yet.

---

## 12. Production-hardening pillars — current state

The four PROD-hardening pillars from the original directive. **AWS infra for all four is now
provisioned by `terraform apply` and survives destroy/re-apply** (see §13). Code and infra are live;
volume-proof on a real ECC/S4 pair is still owed.

| Pillar | Implementation | Verified | Still pending |
|---|---|---|---|
| **1.1 — Dynamic compute dispatcher (Lambda → Fargate)** | `lambda/utils/scaling.py:ComputeDispatcher` routes to Fargate with auto-scaled memory tier when est-rows > threshold, else inline/Lambda. Wired into `pipeline_spine_master.py:296` (`decision.target == "fargate"` → `fargate_routed` count in run summary). | offline: routing logic + dispatcher decision in carve-out phase. **infra: ECS cluster + Fargate task def + ECR repo are provisioned by the prod stack (`migrate4hana-prod-worker` task) and confirmed in state.** | live 10⁶-row run that actually fans out to Fargate; auto-scaling memory tier observed under load |
| **1.2 — Chunked cursor streaming (ABAP `OPEN CURSOR…PACKAGE SIZE` + OData `$top/$skiptoken`)** | `lambda/data-migrator/handler.py:628` (cursor streaming in extract); `lambda/utils/scaling.py:ODataPager` (server-side OData paging). | offline: pager test passes. **infra: live in the extract path.** | end-to-end stream of 10⁶ rows; back-pressure behaviour under realistic latency |
| **1.3 — Write-capacity isolation (DynamoDB token bucket)** | Thread-safe `TokenBucket` in `lambda/utils/key_map.py:23`; optional ledger limiter (default off) to protect DynamoDB WCU under high-concurrency loops. | 120 writes throttled to ~1.41s at 50/s burst-50. | sizing against real table WCU under a live mass load |
| **2 — Transformation / Value-Map / DQ** (closes §6.3) | `lambda/utils/transformation_engine.py` (434 LOC): JSON rule schema (FIELD_MAP / VALUE_MAP / REGEX_CLEANSE / CONST/TRIM/UPPER/PAD), cached S3-backed value-map matrix (local/inline fallback), DQ gates (MANDATORY / REGEX_VALID / MAX_LEN / ALLOWED / UNIQUE) → `DATA_QUALITY_REJECTION`. Hooked into `UnifiedLoader._load_one:423-430` (+ parallel-worker propagation), wired into `data-migrator` (env-gated `M4H_TRANSFORM_RULES`, **no-op by default**). | value-map (3000→1710) + name cleanse applied; all five DQ gates reject correctly; quarantine routes to dead-letter. | live business mapping matrices; a mapping UI; DQ scorecards/cleansing library |
| **3 — Human-in-the-loop governance gates** | `lambda/utils/governance.py` — `GateController` (HMAC-signed, file-backed, cross-process, no-double-pass) + schema-validated SNS alert payloads; signed `/api/spine/approve` (+ `/api/spine/gates`) webhook. | offline: HMAC verify + replay-block tests pass. **infra: 4 × `arn:aws:states:::lambda:invoke.waitForTaskToken` states in `lift_and_shift_pipeline.asl.json` (lines 43/201/240/282) covering ASSESS, DATA-PREP, VALIDATE, CUTOVER; `aws_sns_topic.spine_gates` provisioned; `manual-gate` Lambda persists token to `migrate4hana-gates-prod` DynamoDB table; HMAC secret in Secrets Manager (`migrate4hana/prod/gate-secret`).** | live cut-over with an actual human in the loop; SNS email subscription end-to-end |
| **4 — Cryptographic auditing** | `lambda/utils/reconciler.py:273-455` — `HashChainLedger` (SHA-256, tamper-evident, resume-safe, optional DynamoDB vault); `AggregateReconciler` (count + total + debit/credit tie-out source↔target); `EvidencePack` (hash-sealed manifest). Chain wired into the `data-migrator` run summary. `pdf_report_generator.py` exists with Unicode safety net (516 mojibake fixes applied). | chain verifies + **detects a tampered block**; aggregate tie-out flags balance VARIANCE; evidence pack hash-sealed into the chain. **Infra: `migrate4hana-audit-ledger-prod` DynamoDB table provisioned; `evidence_app` S3 bucket provisioned (encrypted + versioned + public-access-block).** | real source↔target aggregate queries at volume; multi-part compliance PDF that auditors would sign off on; **S3 Object Lock WORM is currently OFF** (see §13 — intentional for the test loop, must be re-enabled at bucket creation for real prod) |

**One honest regression** vs the 2026-05-29 §12: Pillar 4's evidence S3 bucket previously had Object
Lock COMPLIANCE 2555-day retention. It was **deliberately removed** so `terraform destroy` is clean
during the inner-loop test cycle. Re-impose for real prod with two changes (cannot toggle on after
bucket creation): `object_lock_enabled = true` on `aws_s3_bucket.evidence` + restore the
`aws_s3_bucket_object_lock_configuration` block. See `evidence-ledger/main.tf:64-77` for the exact
diff.

---

## 13. Production-ops hardening (2026-05-30 → 2026-05-31)

The architecture above is well-tested in code; this section is about whether you can **actually
deploy and operate it** without manual AWS intervention every cycle.

### 13.1 Apply → destroy is idempotent end-to-end (200 resources)

The prod stack now provisions cleanly from zero state and tears down cleanly back to zero. Every
class of stuck-state failure encountered during the certification run was fixed at root cause and
committed:

| Failure class | Root cause | Permanent fix in source |
|---|---|---|
| "Secret … is already scheduled for deletion" | Secrets Manager 30-day soft-delete reserves the name; next apply hits 400. | `recovery_window_in_days = 0` on `sap-credentials` / `s4hana-credentials` / `gate-secret` / `anthropic-api-key`. |
| Bucket non-empty / `InvalidBucketState: Versioning must be Enabled` on Object Lock | `aws_s3_bucket_object_lock_configuration` raced ahead of versioning; bucket created without `object_lock_enabled = true`. | `object_lock_enabled = true` on the bucket itself + explicit `depends_on = [aws_s3_bucket_versioning.audit_logs]` on the lock configuration. |
| Step Functions `Value is not a valid resource ARN` × 5 | `lookup()` for unbuilt Lambdas (`discovery-engine`, etc.) returned `""`, breaking schema validation. | `local.ls_fallback_arn = manual-gate ARN`; every unresolved Lambda lookup falls back to it so the state machine validates. The router is functional only once the real Lambda exists. |
| CloudWatch dashboard 12× "should have required property 'region'" | Metric widget `properties` blocks were missing `region`. | `region = var.aws_region` threaded into the cloudwatch module and added to all 4 widget property blocks. |
| WAF / tag value rejections | `"SOX,GxP"` (comma) and em-dash characters violated AWS string regex. | Replaced with `"SOX-GxP"` and ASCII hyphens. |
| CloudTrail `InvalidEventSelectorsException` | Wildcards forbidden in the function name portion of a Lambda data_resource value. | Bare prefix `"arn:aws:lambda"` (= all functions in account). |

A fresh `terraform destroy` is also clean — except for one remaining manual: the audit-logs bucket
holds CloudTrail-written objects under Object Lock GOVERNANCE that need `BypassGovernanceRetention`
to empty. Drop a one-line `force_destroy = true` if you want full hands-off destroy too (cost: a
future destroy would wipe SOX audit history without prompting).

### 13.2 Bedrock → direct Anthropic API

The user's AWS account does not have Bedrock model access. The runtime LLM path therefore goes to
`api.anthropic.com` over the Lambda's NAT egress, not via `bedrock-runtime`:

- New shared client: `lambda/code-analyzer/anthropic_client.py` (stdlib `urllib`, Secrets Manager
  fetch with module-level cache, returns `None` on any failure — never raises).
- Default model `claude-sonnet-4-6` (cheap + fast + near-Opus quality for narrow ABAP fragment
  fixes); on retry escalates to `claude-opus-4-7`.
- API key in `aws_secretsmanager_secret.anthropic_api_key` (`recovery_window_in_days = 0`).
- IAM: `secretsmanager:GetSecretValue` on the new secret for both Lambda and Fargate task. Bedrock
  permissions and the two Bedrock PrivateLink VPC endpoints have been **removed**.
- The pseudonymizer (`lambda/code-analyzer/pseudonymize.py`) — reversible PII masking before the
  prompt leaves the process — now matters more, since payload leaves AWS. It still runs unchanged.
- Compatibility-only aliases preserved: `_invoke_bedrock`, `check_bedrock_connectivity`, the
  filename `bedrock_genai_engine.py` — all documented as routing through Anthropic. The Lambda
  function itself is renamed `bedrock-llm-router` → `code-analyzer`.

Trade-off worth naming: today ABAP fragments travel over TLS to `api.anthropic.com` instead of
staying inside AWS. Pseudonymizer masks PII (emails / IPs / passwords) but not business logic. For
some compliance contexts that's a concern; flag if relevant.

### 13.3 One-command Fargate image deployment

`.\scripts\push-fargate-image.ps1` (PowerShell-only — user's environment) wraps the otherwise-manual
Docker steps required after each `terraform apply`:

1. Pre-flight: Docker running in Linux-container mode, AWS CLI authenticated, SAP NW RFC SDK zip in
   `ecs/`, ECR repo present.
2. ECR login (12h token).
3. `docker build -f ecs/Dockerfile -t migrate4hana-worker:latest .` (build context = repo root).
4. Tag + push.
5. Verify via `describe-images`.
6. Warn about any running Fargate tasks that would not auto-pull the new image.

Required because Terraform creates the ECR repo + task definition but does **not** build/push the
image (intentional — avoids burning 5-8 min on every apply for unchanged images). First run
~7-10 min total; subsequent runs with cached layers ~30-60s.

### 13.4 What's still NOT in the production loop

To keep the brief honest:

- **ECC ↔ AWS connectivity deferred.** The current prod stack runs in-AWS-only; the user's local
  ECC system is reachable from the workstation but not from VPC-attached Lambdas. Site-to-site VPN
  or AWS Client VPN is needed before stages can actually call ECC from AWS. See [[connectivity-quirks]].
- **Object Lock WORM off.** As §12 notes — intentional but a regression vs the original Pillar 4
  spec. Two-line fix when ready for prod.
- **No live large-volume run on AWS.** Code paths for Fargate dispatch + cursor streaming + token
  bucket + hash chain all exist and pass unit tests; none have been exercised against 10⁶ rows on
  the deployed stack.
- **Several Lambdas referenced by `lift_and_shift_pipeline.asl.json` are not yet built**
  (`discovery-engine`, `migration-completeness-analyzer`, `pdf_report_generator` as a separate
  function). They currently resolve to the `manual-gate` fallback ARN, so the state machine
  validates and starts but those specific tasks no-op. Each needs its own handler before
  end-to-end execution against a real source/target.

---

## 14. SAP-functional-depth gap closures (2026-05-31, peer-review driven)

A peer SAP-expert review (Gemini, Big-4-class peer read) flagged the **SAP
functional depth** as the primary vulnerability vs the engineering layer. Eight
gaps were buildable in code without a live system; this section is the
inventory. Each ships with a working module and a green self-test; production-
completeness (volume / breadth / customer-specific content) is honestly noted.

| # | Gap (Gemini's framing)                                  | Module + entry point                          | Verified self-test                                                                                       | Still owed for production |
|---|---------------------------------------------------------|----------------------------------------------|----------------------------------------------------------------------------------------------------------|---------------------------|
| 1 | **CVI** — KNA1/LFA1 overlapping number ranges + duplicate addresses | `lambda/utils/cvi_mapper.py`<br>`unify(kna1, lfa1)` | overlap detection (1 #), intra-table duplicates, exact-fingerprint fold into one BP with both roles, near-duplicate conflict quarantine (different tax IDs), deterministic round-trip | fuzzy / phonetic / edit-distance match; address harmonization across locales; per-company-code overrides |
| 2 | **SAP-side backpressure** — TH_WPINFO + NRIV lock probe | `lambda/utils/sap_workload.py`<br>`WorkloadThrottle.decide()` | GREEN/YELLOW/RED classification; batch halved on YELLOW; full pause + 10s wait on RED; NRIV-lock causes back-off | landscape-specific thresholds tuned against real WP topology; integration into the Fargate fan-out caller |
| 3 | **BAPI field-coverage trap** — extension fields (CI_/ZZ_), tax fields (J_1B*) | `lambda/utils/bapi_coverage.py`<br>`decide_load_path()` | clean record → BAPI; CI + tax field → BAPI_PLUS_LTMC_DELTA; >50% unsupported → LTMC_ONLY; LTMC staging CSV + control JSON emitted with `ltmc_load_mode = "Staging tables (Direct Transfer)"` recommendation | per-BAPI canonical field catalog (today supplied by caller); LTMC CSV column-name mapping to the actual MC migration object schema |
| 4 | **FAGLB03 / MB5B spool capture** for the auditor evidence pack | `lambda/utils/spool_capture.py`<br>`SpoolCapture.capture(report_code, params)` | end-to-end: JOB_OPEN → JOB_SUBMIT → JOB_CLOSE → BP_JOB_STATUS_GET polling → RSPO_RETURN_ABAP_SPOOLJOB fetch; SHA-256 sealed; param-validation; unknown-report rejection; dry-run mode | wiring `CapturedSpool` into `HashChainLedger.append()` so the chain seals the spool hash; report catalog expansion (FBL3N, S_ALR_87012082, etc.); selection-variant support |
| 5 | **Dual-maintenance / continuous code-sync engine** (SmartShift's actual moat) | `lambda/utils/code_delta.py`<br>`DeltaEngine.snapshot()` + `detect_delta()` + `plan_remediation()` | TADIR/REPOSRC snapshot of customer-namespace ABAP; ADDED/MODIFIED/DELETED verdicts vs baseline; remediation queue is append-only + idempotent (re-run = no-op) | optional deep source-hash on PROG via READ_REPORT (already supported, off by default); CHANGEDOCUMENT-style diff visualization; scheduler (CRON / EventBridge) for the snapshot loop |
| 6 | **Multi-field cross-validation DQ** (Syniti-class beyond FK) | `lambda/utils/transformation_engine.py`<br>new `CROSS_FIELD_VALIDATE` rule type with `{when, expect}` predicates | conditional triggers (credit-limit ↔ payment terms), prefix matching (country ↔ tax jurisdiction), set membership (plant ↔ company code), construction-time schema validation | DQ scorecards over time (Syniti's true differentiator); business-user UI for rule authoring; library of common cross-field rules per object type |
| 7 | **Cluster-table aware extraction** (RFBLG / KOCLU / EDI40 on non-HANA ECC) | `lambda/utils/cluster_table_awareness.py`<br>`preflight(table, where, on_hana)` | transparent table = GO at requested pkg; BSEG with header-keys = single-stage cluster read at PACKAGE SIZE=200; BSEG without header-keys = rewritten as 2-stage BKPF → BSEG plan; PCL1 with no WHERE = NO_GO (refuses to dump prod); HANA disables the penalty | extending catalog from current 13 entries to a fuller list; runtime DB-kind detection (today caller supplies `on_hana=True/False`) |
| 8 | **DAG dependency resolver** (faithful dependent-key migration; closes §6.1) | `lambda/utils/dependency_dag.py`<br>`DependencyDAG.from_defaults()` + `ExecutionState` + `KeyResolver` | 28-node default DAG, cycle detection, topological sort, scope-subset pulls transitive deps, `next_ready()` correctly gates downstream objects, failure propagation lists downstream blocked, `KeyResolver.resolve_record()` translates legacy keys via cross-run keymap | actual integration with the data-migrator stage loop (today modules are standalone); per-customer DAG additions / removals |

**What this changes vs the 2026-05-29 §6 limitations:**

- §6.1 ("Harmonization is demo, not faithful migration") — **closed in design**:
  `dependency_dag` + `KeyResolver` give the staged-load + cross-run key-translation pattern that
  Gemini called for. Integration into the data-migrator stage loop is the next mechanical step.
- §6.3 ("No general transformation / mapping engine") — already had `transformation_engine.py`;
  the new `CROSS_FIELD_VALIDATE` lifts it from "field-level cleansing" to "Syniti-class
  business-rule validation." The mapping UI for non-technical users is still pending.
- §6.4 ("No data quality / pre-load cleansing") — `CROSS_FIELD_VALIDATE` is the substrate; DQ
  scorecards over time + a cleansing rule library are still pending content work.
- §6.6 ("Functional coverage depth — minimal field sets") — `bapi_coverage` now FORMALLY tracks
  what the chosen BAPI cannot carry and routes the rest to LTMC instead of silently dropping it.

### Honest caveats on §14

- All eight modules are **framework-complete, content-light**. The DAG ships with a sensible
  default for SAP greenfield projects; real customer migrations will need DAG edits. The
  `bapi_coverage` module needs a per-BAPI field catalog (today supplied by the caller). The
  `spool_capture` module needs each `CapturedSpool` actually wired into the existing
  `HashChainLedger` invocation site - one-line change, not done yet to avoid touching the
  reconciliation hot path without a test pair.
- The Gemini-flagged "Anthropic-over-public-TLS compliance wall" and "WORM Object Lock
  regression" are **deliberately not addressed in this iteration** - both are acceptable for a
  POC on the user's client ECC→S4 setup and become production-blocking only at regulated-buyer
  rollout. Re-isolating the LLM to a private endpoint and restoring Object Lock at bucket
  creation are tracked but not in this commit.

### Migration Cockpit positioning pivot

The 2026-05-29 brief positioned Migrate4HANA largely as filling the gap MC leaves. In 2026 SAP
shipped **Staging Tables for Direct Transfer (RFC)** in the Migration Cockpit, which closes part
of the extraction gap we previously claimed. Our defensible value-prop is now sharper and
narrower:

- **What SAP MC Direct Transfer does well**: extraction via RFC, intermediate staging in HANA,
  in-place data correction UI, native LTMC error handling.
- **What we add that MC does not**: auto-discovery of target config; cross-run idempotent ledger
  with hash-chained audit; aggregate value-reconciliation with hard GO/NO-GO verdict per object;
  governed cutover gate with HMAC-signed approval webhook; selective carve-out ABAP generator;
  CVI/DAG/BAPI-coverage/cluster-aware preflight that prevent failures MC discovers only after
  load.

The brief should **not** sell the extraction layer alone as a differentiator anymore.
