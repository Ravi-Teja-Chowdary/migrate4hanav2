# Migrate4HANA — Independent Review Brief

*Prepared for an SAP data-migration / S4 conversion specialist. The goal of this document
is an honest assessment of where the tool stands — gaps are stated deliberately so your
review is efficient. Nothing here is marketing; please challenge any claim.*

**Date:** 2026-05-29 · **Branch reviewed:** `aws-lift-and-shift` · **Build status:** working prototype on a live system pair.

> **2026-05-29 update:** four new "competitive-parity" layers and a light-themed Project Tracker UI were
> added (commit `0e7b7e0`). They are **self-tested deterministically but NOT yet integrated into the
> live ECC→S/4 loop** — see **§10** for exactly what each does and its maturity, and **§11** for an
> honest head-to-head read vs SmartShift / Syniti / Natuvion. Read §10–11 as "newly built, integration
> + live-proof pending," not as additions to the §4 live-proven evidence.

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

## 10. Competitive-parity layers added 2026-05-29 (built + self-tested; live integration pending)

These were added to give the tool an explicit answer to "how do you compare to SmartShift / Syniti /
Natuvion in their core areas." **Honest status up front:** each module is **standard-library, runs its
own self-test green, and is architecturally production-shaped — but none is yet wired into the live
`unified_loader` spine of §3–4, none has touched the live ECC/S4 pair, and the AI + 10M-scale paths
have not been exercised against real Bedrock / real volume.** They are credible engineering, at roughly
**TRL 4 (component validated in isolation)**, sitting beside a **TRL ~6** live spine.

| Layer | File | What it does (deterministically) | Verified | NOT yet |
|---|---|---|---|---|
| **Natuvion — selective carve-out** | `agent/in_system_agent_generator.py` | Generates parameterized in-system ABAP: org (`BUKRS`) + time (`GJAHR`) pushed into the `WHERE`; `OPEN CURSOR … FETCH … PACKAGE SIZE` streaming (anti-`TSV_TNEW_PAGE_ALLOC_FAILED`); dependency-aware header co-extract (line table → `BKPF`); ABAP-injection-safe identifier validation. Deploys via the proven `RPY_PROGRAM_INSERT`+`RZL_SUBMIT` agent. | ABAP emitted + validated; injection guard tested | Run live at volume; multi-table carve graph; client/CoCode split |
| **Syniti — data spine** | `data_spine_orchestrator.py` | Entity-tree FK integrity (`BUT000/BUT020/BUT100`; orphans quarantined); deterministic self-heal of org attributes (PRCTR/BUKRS/…) against target reference data (remap → default); append-only **SHA-256 idempotency ledger** with `reused_from_ledger` score + instant resume. Zero runtime AI. | Self-test: orphan quarantined, 3 PRCTRs healed, resume run 100 % reused | A general value-mapping/rules engine; DQ rule library; live wiring |
| **SmartShift — AI fail-safe** | `lambda/code-analyzer/llm_fallback_router.py` | Wraps the real 6,400-line AST engine in a strict try/catch; on a parser crash/parse-error it localises the offending block (lines + exact error), builds a compact **Bedrock** fix-only prompt, splices + re-validates, then routes through a **mock-ATC** governance gate → PASS = transport `.data/.cofile`, FAIL = quarantine. LLM is injectable. | Self-test: deterministic→transport, AI-fallback→fixed→transport, no-AI→quarantine | Real Bedrock call; **real ATC** (the gate is a mock); wiring to `code-deployer`'s human-approval gate |
| **Master orchestrator** | `pipeline_spine_master.py` | Sequences Natuvion→Syniti→SmartShift→Governance; `RFCThrottle` (bounded concurrency + paced interval = anti-DoS on the SAP gateway); identical local/cloud state-machine payload; writes live `progress.json` for the UI; per-phase return codes. | Self-test: 4-phase run rc=0, GO verdict, progress emitted | Drive the *live* loaders (today runs on fixtures); Step Functions parity test |
| **Stress generator** | `scripts/stress_test_generator.py` | 100× Lambda fan-out, Faker+deterministic SAP rows → S3 Parquet; 1 % chaos injection (bad dates / orphan FK / dup keys) to exercise the assessor + ledger. Added a `lambda_handler`; fixed two real bugs (FieldSpec hint, local Parquet path). | Local self-test: workers write Parquet, ~1 % chaos | The actual 10M-row AWS run (user-executed, guided) |
| **UI — Project Tracker** | `frontend/` (light theme) + `/api/spine/progress` | Fluidic light theme (`#F8FAFC`, slate/indigo); Start/End connectivity boards (ECC→S/4 RISE), progress pipeline, kanban (Completed / In-Progress + spinner & RC / Queued); polls the orchestrator's live progress. | `npm run build` clean; dev server serves all modules | Pixel/UX review; live data binding under a real run |

**For your review:** the §6 limitations still stand. §10 narrows two of them on paper — §6.3 (a *first* deterministic self-heal/FK layer exists, though not a general mapping engine) and the §4 governance gap (an ATC-style gate now exists, though mock) — but **none of §10 changes the live-proven evidence in §4.** Please judge these as design, not delivery.

---

## 11. Honest head-to-head: are we competitive with SmartShift / Syniti / Natuvion?

Short answer: **competitive in *architecture and orchestration*; not yet competitive in *depth, content,
and proof* in any of the three vendors' core specialities.** Per area:

| Their speciality | Where we stand | Verdict | To become competitive |
|---|---|---|---|
| **SmartShift — automated custom-code remediation at scale** | Real 6,400-line AST engine + 4-level fixers + deterministic-first/AI-fallback wrapper + governance gate. | **Partial.** Engine is real and the architecture is sound; our *ruleset breadth, automation %, regression/equivalence testing, and scale proof* are far below SmartShift's mature platform. | Real ATC integration; an automated before/after **equivalence-test** harness; expand the simplification ruleset; prove auto-fix % on a large real custom-code base; CI over the fixer. |
| **Syniti — data quality, mapping, governance, reconciliation** | Strong **reconciliation** (existence+value, hard verdict) + cross-run **idempotency ledger** (now SHA-256) + new **FK-integrity + deterministic self-heal**. | **Partial.** Our reconciliation/idempotency are genuinely strong and unusual; we lack Syniti's **value-mapping/rules engine, DQ scorecards & cleansing library, and business-user mapping/governance UI**. | Build the general mapping/rules layer (§6.3); a DQ rule library + scorecard; a mapping UI; data-owner workflow/sign-off. |
| **Natuvion — selective data transition / carve-outs / consolidation** | New carve-out ABAP generator (org+time filters, dependency-aware, streamed) on the supported in-system agent; greenfield/SDT lane positioning. | **Gap→Partial.** We can *generate* a governed carve-out; we have **not** proven it at volume, nor built company-code/client split or system-consolidation harmonization content. | Live carve-out at volume; selective company-code/time-slice split; harmonization rules for consolidation; faithful dependent-key migration (§6.1). |

**Where we already beat the field for our lane:** the **trust spine** — auto-discovery + existence/value
reconciliation with a hard GO/NO-GO + cross-run idempotency + dead-letter + support-clean attestation —
is more automated and more auditable out-of-the-box than the stock Migration Cockpit, and is a credible
differentiator none of the three give you for free in exactly this shape.

**The blunt bottom line for a reviewer:** today this is **one strong, support-clean, live-proven
orchestration+reconciliation spine (25 objects)** plus **five newly-built, self-tested-but-not-yet-live
components** that *sketch* parity with the three vendors. To be genuinely competitive with any one of
them in their home turf, the priorities are (1) the **mapping/transformation + DQ layer** (closes the
Syniti gap and §6.3), (2) **ATC + equivalence-testing + scale** for the code fixer (closes the SmartShift
gap), (3) **live, volume-proven carve-out + consolidation content** (closes the Natuvion gap), and (4)
**a customer pilot on a second, customer-shaped landscape** (§6.7). The architecture to hang all of this
on now exists; the depth, content, and proof do not yet.
