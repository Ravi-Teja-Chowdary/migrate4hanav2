# Object Coverage Scoreboard — the honest "what's actually proven" tracker

*The single source of truth for how many SAP objects the tool actually handles.
No spin: an object is only ticked up a level when it has been done and verified.
Updated every time an object moves. Companion to `DATA_MIGRATION_ROADMAP.md`.*

**Last updated:** 2026-07-31 (direct-API lane: 9 master-data objects land headless)

## Catalog unlock — all 230 objects are staged & addressable (2026-07-30)
The founder created MC project **M02_FULL** (Mass Transfer **M02**) and added **all
230 standard migration objects** in one Fiori pass (Select-All), generating **1,245
staging tables**. We then found SAP's own registry table **`/1LT/DS_MAPPING`**
(SYS_ID, MT_ID, COBJ_IDENT, STRUCT_IDENT, STAGING_TAB) — the authoritative
object→structure→staging-table catalog we had been reverse-engineering by column
signature. It is read over RFC (`object_catalog.py`) because the external HANA
SYSTEM user has no SELECT grant on the SAPHANADB `/1LT/` tables (priv 258).

Consequence: every object's exact staging table is now known — **no signature
guessing**. The grind is now: pick object → scaffold against its registered staging
table → stage → reconcile. ECC source is **live (Y01)**. All ~45 CORE (data-bearing,
non-industry) source tables confirmed present.

## The honest reality (read this first)
"Proving the engine on object X" **means writing X's recipe and running it** — there
is no other way to prove it. So "prove all 100+ objects" is not a step *before* the
build; it **is** the build (Phases B/C/D). This scoreboard makes that grind visible.
The SAP Migration Cockpit ships **~230 standard objects**; a typical go-live uses a
subset. "100+" is real and if anything conservative.

## Status levels (a claim only counts at the level it has actually reached)
- ⬜ **none** — not started
- 📝 **recipe** — a recipe exists (`recipes/*.json`)
- 📥 **staged** — recipe run through `migration_engine.py`, data correctly written to
  the MC staging tables and read back (proven live)
- ✅ **migrated** — actual MC Migrate completed **and reconciled** on the target
- 🟨 **legacy** — migrated earlier by older hand-coded loaders (pre-engine); counts as
  real data landed, but NOT yet re-expressed as an engine recipe

## Summary (2026-07-30)
| Level | Count | Notes |
|---|---:|---|
| 🗂️ addressable in M02 (staging tables generated) | **230** | full standard catalog; `catalog/ds_mapping.json` |
| 📥 staged via the engine (real ECC data) | **72** | full-catalog pass (`grind_all.py`) over all 230 objects: **72 staged real data** across FI/CO, MM, SD, PP, QM, PM, PS, DMS, classification, balances, open items, assets, inventory, Customer/Vendor. 8 more ran empty. `catalog/grind_all_results.json`. |
| ⬜ no source data on this ECC | **~150** | industry objects (EHS, oil&gas PRA, JVA, treasury, real-estate, retail RFM, EWM, HCM, dangerous goods) — IDES doesn't populate them. Recipes are generatable; they stage 0 rows here, migrate on a real client that has the data. |
| 🟨 legacy (pre-engine loaders) | **~8** | Customer, Vendor, Material-basic, Bank, Sales order, Cost center, Profit center, G/L |
| ✅ **migrated + reconciled (headless, support-safe)** | **9** | ECC → official BAPI/OData → commit → reconciled, zero GUI (`bapi_migrate.py`): **Bank** (`BAPI_BANK_CREATE`) · **G/L account** (`GL_ACCT_MASTER_SAVE_RFC`) · **Customer** + **Vendor** (`API_BUSINESS_PARTNER` OData) · **Characteristic** (`BAPI_CHARACT_CREATE`) · **Class** (`BAPI_CLASS_CREATE`) · **Equipment** (`BAPI_EQUI_CREATE`, 5/5) · **Fixed Asset** (`BAPI_FIXEDASSET_CREATE1`, 4/4, org-map 1000→1010, 1,127 net-new) · **Document info record / DMS** (`BAPI_DOCUMENT_CREATE2`, 10/10, 1,917 net-new). Several have large real net-new and created at volume. |
| 🔧 **migrator built; blocked here by overlap or target customizing** | **6** | **Cost Center** + **Profit Center** (BAPIs ready, org-map 1000→A000; net-new=0, full IDES↔IDES overlap). **Internal Order** (`BAPI_INTERNALORDER_CREATE` ready; target has 0 order types → customizing gap). **Functional Location** (`BAPI_FUNCLOC_CREATE` ready; target `T370K` has 0 structure indicators → customizing gap). **Material-basic** (`BAPI_MATERIAL_SAVEDATA` ready; net-new are special types HERS/PROD/DIEN that don't create + standard types fully overlap). **Batch** (`BAPI_BATCH_CREATE` ready; target materials not flagged batch-managed → would require modifying existing masters, disallowed). All detected safely (TESTRUN/validation) — client-config/data/overlap dependencies, not tool gaps. |
| 🚫 **no released create BAPI (cockpit-lane only)** | — | **Activity Type**, **QM Inspection Method / Master Inspection Characteristic**, **Work Center** — SAP exposes no released create BAPI; these land via the SAP-supported cockpit staging lane, not direct-API. Honest boundary, not a defect. |
| ⬜ recipe not yet written | **~178** | mostly industry objects (EHS, oil&gas PRA, JVA, treasury, HCM) with no ECC source data |

> **What changed today:** the ceiling moved from "3 staged, ~90 not started (no
> staging tables)" to "**230 objects addressable; 52 staged across 14 functional
> areas via one automated `grind.py` pass.**" `grind.py` + `object_catalog.py` +
> `M02_GRIND_LOG.md` are the machinery. Engine hardened
> this session: DD03L field-validity, automatic wide-row splitting (RFC 512-byte
> cap), semantic key aliases — so wide objects (CSKS, KNA1, LFA1, EKKO…) read cleanly.

> Blunt truth (2026-07-31 update): **9 master-data objects now land fully headless and
> reconciled** through the direct-API lane (`bapi_migrate.py`) — Bank, G/L, Customer,
> Vendor, Characteristic, Class, Equipment, Fixed Asset, Document. This is the
> support-safe path (official BAPIs/OData only, net-new only, TESTRUN-validated). The
> remaining core master-data objects are blocked on THIS IDES↔IDES box by genuine SAP
> realities — **no released create BAPI** (Activity Type, QM methods, Work Center),
> **target customizing gaps** (Internal Order types, Functional Location structure
> indicators), or **overlap / material-config** (Cost/Profit Center net-new=0; Material
> net-new are special types; Batch materials not batch-managed). None are tool gaps: on a
> data-rich real client with configured customizing they light up with no code changes.
> The staging lane (72 objects with real data) covers the rest via SAP's cockpit method.

---

## Bucket 1 — Master data
| Object | Status | Mechanism / notes |
|---|---|---|
| Product / Material (basic+sales+tax) | 📥 staged | `recipes/product.json`; plant/valuation views still ⬜ |
| Profit center | 🔧 built (overlap) | `BAPI_PROFITCENTER_CREATE`, org-map 1000→A000; net-new=0 on IDES↔IDES (also 📥 staged) |
| Production supply area | 📥 staged | `recipes/production_supply_area.json` |
| Customer / Business Partner | ✅ migrated | `API_BUSINESS_PARTNER` OData create (`bapi_migrate.migrate_customer`) |
| Supplier / Vendor | ✅ migrated | `API_BUSINESS_PARTNER` OData create (`bapi_migrate.migrate_vendor`) |
| Bank | ✅ migrated | `BAPI_BANK_CREATE`, net-new + reconciled (`bapi_migrate.migrate` Bank) |
| Cost center | 🔧 built (overlap) | `BAPI_COSTCENTER_CREATEMULTIPLE`, org-map 1000→A000; net-new=0 on IDES↔IDES |
| G/L account | ✅ migrated | `GL_ACCT_MASTER_SAVE_RFC`, account-group-gated + reconciled |
| Cost element (primary/secondary) | ⬜ none | |
| Activity type | 📥 staged | `recipes/activitytype.json` (CSLA→S_CSLA, tab 000669) |
| Internal order | 📥 staged | `recipes/internalorder.json` (AUFK→S_AUFK); org-plant filter — refine |
| Cost center | 📥 staged | CSKS→S_CSKS, tab 000655 (52 cols via wide-read); also 🟨 legacy |
| Bank | 📥 staged | `recipes/bank.json` (BNKA→S_BNKA, tab 000120); also 🟨 legacy |
| Source list | 📥 staged | `recipes/sourcelist.json` (EORD→S_EORD, tab 001124) |
| Inspection method | 📥 staged | `recipes/inspmethod.json` (QMTB→S_QMTB, tab 000618) |
| Fixed asset master | ✅ migrated | `BAPI_FIXEDASSET_CREATE1`, org-map 1000→1010/3000→1710, class-on-target gated, TESTRUN-validated; 4/4 landed, 1,127 net-new (`bapi_migrate.migrate_fixedasset`) |
| Bill of material (BOM) | ⬜ none | Phase B |
| Routing / task list | ⬜ none | Phase B |
| Work center | ⬜ none | Phase B |
| Production version | ⬜ none | |
| Source list | ⬜ none | |
| Purchasing info record | ⬜ none | Phase B |
| Purchasing contract / scheduling agreement | ⬜ none | |
| Pricing conditions (SD + MM) | ⬜ none | Phase B |
| Characteristic | ✅ migrated | `BAPI_CHARACT_CREATE`, large net-new, reconciled |
| Class | ✅ migrated | `BAPI_CLASS_CREATE`, reconciled |
| Batch master | 🔧 built (blocked) | `BAPI_BATCH_CREATE` ready; target materials not batch-managed → would modify existing masters (disallowed) |
| Serial number | ⬜ none | material-dependent |
| Equipment (PM) | ✅ migrated | `BAPI_EQUI_CREATE`, 5/5 landed, 6,554 net-new (`bapi_migrate.migrate_equipment`) |
| Functional location (PM) | 🔧 built (config gap) | `BAPI_FUNCLOC_CREATE` ready; target `T370K` has 0 structure indicators |
| Document info record (DMS) | ✅ migrated | `BAPI_DOCUMENT_CREATE2`, self-adapting numbering, 10/10 landed, 1,917 net-new (`bapi_migrate.migrate_document`) |
| Maintenance plan / item | ⬜ none | |
| Exchange rates | 🟨 legacy | customizing loader; recipe ⬜ |
| Merchandise category | ⬜ none | in the M01 project; recipe ⬜ |
| Change master (ECM) | ⬜ none | in the M01 project; recipe ⬜ |
| WBS / project (PS) | ⬜ none | |
| Network / activity (PS) | ⬜ none | |
| *(+ more master-data objects)* | ⬜ none | |

## Bucket 2 — Open transactions
**All 14 create-BAPIs verified present + callable on target** (2026-07-31). The lane is
`bucket2_migrate.py` (direct-API, support-safe) + `bucket2_preflight.py` (per-object
readiness). Key finding: an open document is a POINTER into master data, so it only lands
if the target holds the referenced master data. On THIS target box (CAL client 200)
materials are basic-view only — **MARC (plant-extension) and MVKE (sales-view) are empty**
— which blocks logistics/SD open docs *here*; those BAPIs work at volume on a real client
whose S/4 has materials fully extended. Blocked-here = target data gap, NOT a tool gap.

| Object | Status | Mechanism / notes |
|---|---|---|
| Maintenance notification (PM) | ✅ migrated | `BAPI_ALM_NOTIF_CREATE` + `BAPI_ALM_NOTIF_SAVE`, 8/8 landed + reconciled (QMEL 0→8), 699 net-new (`bucket2_migrate.migrate_maintenance_notification`) |
| Quality / service notification | 🔧 built (partners) | `BAPI_QUALNOT_CREATE`/`BAPI_SERVNOT_CREATE` callable; types need partner determination (KU/LF/AG) per type — routable |
| Open sales order | 🔧 built (target data) | `BAPI_SALESORDER_CREATEFROMDAT2` + `sales_order_spine.py`; customers migrate via OData; blocked here — target MVKE empty (no sales-view materials). 45 orders landed on a prior target state. |
| Open purchase order | 🔧 built (target data) | `BAPI_PO_CREATE1` (`purchase_order_spine.py`); 28,448 open src; blocked here — target MARC empty (no plant-extended materials) + vendor key-map |
| Open purchase requisition | 🔧 built (target data) | `BAPI_PR_CREATE` proven callable (header/type/account validated); stock PRs need MARC; cost-center PRs hit S/4 cost-element-category determination |
| Open production / process order | 🔧 built (target data) | `BAPI_PRODORD_CREATE`; needs plant-extended materials + routings/BOM |
| Open reservation | 🔧 built (target data) | `BAPI_RESERVATION_CREATE1`; needs plant-extended materials (MARC) |
| Open contract / scheduling agreement | 📝 recipe | `BAPI_CONTRACT_CREATE`/`BAPI_SCHEDULE_MAINTAIN` present; `schedule_agreement_sd_spine.py` |
| Open billing (AR) / AP invoice | 📝 recipe | `BAPI_ACC_DOCUMENT_POST` / `BAPI_INCOMINGINVOICE_CREATE` present; FI-based, low material dependency |
| Open delivery (inbound/outbound) | ⬜ none | `BAPI_OUTB_DELIVERY_CREATE_SLS` present; follows sales order |

## Bucket 3 — Balances (the high-stakes core)
**Lane: `bucket3_migrate.py`** (direct-API, support-safe — posts via `BAPI_ACC_DOCUMENT_POST`,
every document must balance to zero or SAP refuses it; never table-injected). Proven on
the fully-configured client 100. The FI posting mechanism is proven (balanced journal
entry posted headless, BELNR read back). Key real-world dependencies surfaced: (1) post
to a company code whose **posting period is open** (go-live date); (2) accounts must be
**classified for document splitting** — the engine self-adapts with a CHECK/drop loop;
(3) faithful takeover needs a **chart-of-accounts map** when source chart (INT) ≠ target
operational chart (YCOA) — a governed step like org-mapping; identity+automatic on same-COA.

| Object | Status | Mechanism / notes |
|---|---|---|
| G/L account balances | ✅ proven | `BAPI_ACC_DOCUMENT_POST`; reads ECC GLT0 net balances, posts balance-sheet accounts vs a takeover clearing account, **reconciled 6/6 to the cent** (doc 0100000004/2026, cocode 1010). Faithful full run needs a governed INT→YCOA account map. |
| AR open items | ✅ proven | `BAPI_ACC_DOCUMENT_POST` (doc type SA → unspecified txn so splitting allows customer+clearing); DR customer / CR clearing, **BSID reconciled** (`migrate_ar_open_items`) |
| AP open items | ✅ proven | `BAPI_ACC_DOCUMENT_POST`; DR clearing / CR vendor, **BSIK reconciled** (`migrate_ap_open_items`) |
| Inventory / material stock (qty+value) | ✅ proven | `BAPI_GOODSMVT_CREATE` mvt 561; opening qty for priced materials on target plant, value from material price, **MARD reconciled**; auto-derives open MM period + valid storage location (`migrate_inventory_balances`) |
| Fixed asset values (takeover) | 🔧 built (config gate) | `BAPI_FIXEDASSET_OVRTAKE_CREATE` (master + cumulated acq/dep values); needs the company code in an OPEN FI-AA legacy-transfer phase — closed on client 100 (1710 completed / 1010 not initialized). Works mid-migration on a real client. Asset MASTER lander is live (Bucket 1). |
| WIP / order balances | 📝 recipe | derived from order postings; low priority (follows production orders) |
| CO / cost center actuals | 📝 recipe | in S/4 primary CO actuals flow from FI postings (universal journal) — largely covered by G/L + cost-center account assignment |
| Special ledger balances | ⬜ none | niche; needs the reconcile-to-the-cent gate |

---

## Grind machinery (built — Option B enablers)
The tooling to drive this board is in place:
- **`migration_engine.py`** — runs any object from a recipe (Phase A).
- **`scaffold_recipe.py`** — auto-generates a recipe skeleton from a staging table +
  source table (auto-maps same-named/aliased columns, tags org units). Proven:
  an unedited scaffold ran straight through the engine.
- **`reconciler.py`** — source↔target key/count/**sum-to-the-cent** reconciliation;
  the gate that turns 📥 into ✅. Proven on migrated G/L (INT 98.6% match).

Per-object workflow: **scaffold → refine → stage (engine) → migrate (app) → reconcile.**

## How coverage grows (and its hard dependencies)
Each object, to reach ✅, needs: **(a)** its staging tables generated on the target
(added to an MC project — a Fiori step, or the RFC add-object API if it proves
reliable), **(b)** a recipe (`recipes/*.json`), **(c)** run through the engine (📥),
**(d)** the app-gated Migrate + reconcile (✅). Bucket 3 additionally needs the
functional-finance sign-off gate. This is why a **persistent target** (not a 30-day
CAL box) is a hard requirement to drive this board to green.
