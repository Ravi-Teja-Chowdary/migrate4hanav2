# Object Coverage Scoreboard — the honest "what's actually proven" tracker

*The single source of truth for how many SAP objects the tool actually handles.
No spin: an object is only ticked up a level when it has been done and verified.
Updated every time an object moves. Companion to `DATA_MIGRATION_ROADMAP.md`.*

**Last updated:** 2026-07-30

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
| 📥 staged via the engine | **3** | Product, Profit Center, Production Supply Area |
| 🟨 legacy (pre-engine loaders) | **~8** | Customer, Vendor, Material-basic, Bank, Sales order, Cost center, Profit center, G/L |
| ✅ **migrated + reconciled via the engine** | **0** | the app-gated Migrate + reconcile is not yet run on a persistent target |
| ⬜ not started | **~90+** | the grind ahead |

> Blunt truth: **zero objects are fully migrated-and-reconciled through the new engine
> yet.** Staging is proven on 3; the actual Migrate step is app-gated and needs a
> persistent target. Everything below ⬜ is honest work remaining.

---

## Bucket 1 — Master data
| Object | Status | Mechanism / notes |
|---|---|---|
| Product / Material (basic+sales+tax) | 📥 staged | `recipes/product.json`; plant/valuation views still ⬜ |
| Profit center | 📥 staged | `recipes/profit_center.json` (also 🟨 legacy) |
| Production supply area | 📥 staged | `recipes/production_supply_area.json` |
| Customer / Business Partner | 🟨 legacy | via OData API_BUSINESS_PARTNER; recipe ⬜ |
| Supplier / Vendor | 🟨 legacy | recipe ⬜ |
| Bank | 🟨 legacy | governed T005 key fix; recipe ⬜ |
| Cost center | 🟨 legacy | recipe ⬜ |
| G/L account | 🟨 legacy | via GL_ACCT_MASTER_SAVE_RFC; recipe ⬜ |
| Cost element (primary/secondary) | ⬜ none | |
| Activity type | ⬜ none | |
| Internal order | ⬜ none | |
| Fixed asset master | ⬜ none | Phase B |
| Bill of material (BOM) | ⬜ none | Phase B |
| Routing / task list | ⬜ none | Phase B |
| Work center | ⬜ none | Phase B |
| Production version | ⬜ none | |
| Source list | ⬜ none | |
| Purchasing info record | ⬜ none | Phase B |
| Purchasing contract / scheduling agreement | ⬜ none | |
| Pricing conditions (SD + MM) | ⬜ none | Phase B |
| Characteristic | ⬜ none | |
| Class | ⬜ none | |
| Batch master | ⬜ none | |
| Serial number | ⬜ none | |
| Equipment (PM) | ⬜ none | |
| Functional location (PM) | ⬜ none | |
| Maintenance plan / item | ⬜ none | |
| Exchange rates | 🟨 legacy | customizing loader; recipe ⬜ |
| Merchandise category | ⬜ none | in the M01 project; recipe ⬜ |
| Change master (ECM) | ⬜ none | in the M01 project; recipe ⬜ |
| WBS / project (PS) | ⬜ none | |
| Network / activity (PS) | ⬜ none | |
| *(+ more master-data objects)* | ⬜ none | |

## Bucket 2 — Open transactions
| Object | Status | Mechanism / notes |
|---|---|---|
| Open sales order | 🟨 legacy | header-level demo only; recipe ⬜ |
| Open purchase order | ⬜ none | Phase C |
| Open purchase requisition | ⬜ none | Phase C |
| Open delivery (inbound/outbound) | ⬜ none | Phase C |
| Open contract / scheduling agreement | ⬜ none | |
| Open production / process order | ⬜ none | |
| Open maintenance order | ⬜ none | |
| Open quality / service notification | ⬜ none | |
| Open billing (AR invoice) | ⬜ none | |
| Open AP invoice | ⬜ none | |
| Open reservation | ⬜ none | |
| *(+ more open-item objects)* | ⬜ none | |

## Bucket 3 — Balances (the high-stakes core)
| Object | Status | Mechanism / notes |
|---|---|---|
| G/L account balances | ⬜ none | Phase D1 — post to migration clearing acct |
| G/L / AR open items | ⬜ none | Phase D2 |
| AP open items | ⬜ none | Phase D2 |
| Inventory / material stock (qty+value) | ⬜ none | Phase D3 — BAPI_GOODSMVT_CREATE mvt 561 |
| Fixed asset values (takeover) | ⬜ none | Phase D4 |
| WIP / order balances | ⬜ none | |
| CO / cost center actuals | ⬜ none | |
| Special ledger balances | ⬜ none | |
| *(+ more balance objects)* | ⬜ none | needs the reconcile-to-the-cent gate |

---

## How coverage grows (and its hard dependencies)
Each object, to reach ✅, needs: **(a)** its staging tables generated on the target
(added to an MC project — a Fiori step, or the RFC add-object API if it proves
reliable), **(b)** a recipe (`recipes/*.json`), **(c)** run through the engine (📥),
**(d)** the app-gated Migrate + reconcile (✅). Bucket 3 additionally needs the
functional-finance sign-off gate. This is why a **persistent target** (not a 30-day
CAL box) is a hard requirement to drive this board to green.
