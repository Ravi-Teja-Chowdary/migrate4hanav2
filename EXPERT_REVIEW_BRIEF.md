# Migrate4HANA — Independent Review Brief

*Prepared for an SAP data-migration / S4 conversion specialist. The goal of this document
is an honest assessment of where the tool stands — gaps are stated deliberately so your
review is efficient. Nothing here is marketing; please challenge any claim.*

**Date:** 2026-05-28 · **Branch reviewed:** `aws-lift-and-shift` · **Build status:** working prototype on a live system pair.

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
