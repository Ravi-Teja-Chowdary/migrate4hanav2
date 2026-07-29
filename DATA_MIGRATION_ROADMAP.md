# migrate4hana — Data-Coverage Roadmap: the Three Buckets

*Focused planning reference for **data-object coverage** — the path from a proven
master-data automator to a complete three-bucket migration platform. This is the
engineering deep-dive on the "object breadth" dimension; the broader 8-tier product
roadmap (connectivity, discovery, provisioning, code-remediation, SaaS, cutover) lives
in `ROADMAP.md`. This doc supersedes that roadmap's Tier-1 "object scaffolder" concept
with the concrete, proven mechanism found on 2026-07-29: the HANA staging lane.*

**Created:** 2026-07-29 · **Branch:** `aws-lift-and-shift`
**Status legend:** ✅ proven live · 🟡 partial / simulated · ⬜ not started

---

## 1. The goal — the three buckets

A real ECC→S/4 go-live moves three buckets of data. "Every damn thing" = all three,
reconciled, in a sequenced cutover.

| Bucket | What it is | Status today |
|---|---|---|
| **1. Master data** | Customers, vendors, materials, G/L accounts, cost/profit centers, banks, assets, BOMs, pricing… | ✅ ~8 objects live; 🟡 materials+sales (MC simulate); ⬜ the rest |
| **2. Open transactions** | Open sales orders, open POs, open deliveries, open AR/AP invoices | 🟡 sales-order headers only |
| **3. Balances (the hard one)** | G/L balances, AR/AP open items, inventory stock (qty+value), fixed-asset values, WIP | ⬜ not built |

**Bucket 3 is what a go-live is judged on** — the books must tie to the cent, stock must
match the warehouse, assets must reconcile. Highest risk, highest value, built last.

---

## 2. Why it's achievable (no fundamental wall)

- **SAP provides a supported mechanism for every bucket.** The Migration Cockpit ships
  delivered objects for G/L balances, AR/AP open items, inventory, and fixed-asset values;
  released BAPIs sit behind each (`BAPI_ACC_DOCUMENT_POST`, `BAPI_GOODSMVT_CREATE`, asset
  takeover, …).
- **The hard, general plumbing is already built** (this repo, proven live): RFC layer ·
  Basis Kit (incl. class-L **staging loaders** `Z_M4H_STAGING_LOAD/CLEAR`) · OData (BP +
  gateway self-heal) · **HANA staging lane** (the same pipe every Cockpit object uses) ·
  **org_mapper** (governed org-unit mapping) · **preflight_harmonizer** (mismatch detector +
  decision checklist, 8 objects) · reconciliation engine · AWS stack.
- Remaining work = **"add objects on top of proven plumbing,"** not new plumbing.

**Honest caveats:** Bucket 3 is financial and unforgiving (reconcile to the cent, balance
D=C, respect cutover periods). It's a **sustained months-long grind**, object by object.

---

## 3. The strategic multiplier — a universal Cockpit-object engine (Phase A)

The single highest-leverage move: **generalize the material staging lane built on
2026-07-29 into one config-driven engine.** Given any Migration Cockpit object, the engine:

1. auto-discovers its `/1LT/DS*` staging tables (by structure introspection),
2. maps source ECC data → staging columns via a **declarative recipe** (source table, field
   map, org/value transforms via `org_mapper` + harmonizer),
3. loads via the kit staging FMs, drives Prepare → Simulate → Migrate,
4. **reconciles** source vs target and emits a per-object proof.

After Phase A, **every new object is a recipe (config), not code** — the multiplier that
turns "100+ objects" into a checklist. This is the concrete realization of the older
`ROADMAP.md` "object scaffolder framework," now grounded in the proven MC staging mechanism.
Build it first, build it well.

---

## 4. The phased plan

Order is **non-negotiable**: master data → open transactions → balances. You cannot post an
AR open item before its customer exists, or a stock balance before its material+plant exist.
The Phase E dependency engine enforces this.

### Phase A — Universal staging engine  ⬜  *(the multiplier — do first)*
- **Goal:** one engine that runs any Cockpit object from a recipe.
- **Deliverables:** recipe format + object registry; generic staging-table discovery/typing;
  generic source→staging mapper (reuse `org_mapper`); run-driver (handles what's automatable
  vs the SAP-app-gated Simulate/Migrate click); generic reconciler hook.
- **Done when:** the material Product object is re-expressed as a recipe and runs through the
  generic engine end-to-end (matching today's hand-built result), and a *second* object runs
  from a recipe with **zero new code**.

### Phase B — Finish Bucket 1 (master-data breadth)  ⬜
- **Objects:** fixed-asset master, BOM, routings, work centers, pricing conditions, purchasing
  info records, source lists, characteristics/classes, batches, serial numbers, equipment/
  functional locations, plus **material plant + valuation views** (valuation needs Material
  Ledger startup — a config prereq the harmonizer flags).
- **Mechanism:** Cockpit objects via the Phase A engine + org/value mapping.
- **Done when:** each object migrates faithfully on a fresh target and reconciles by count +
  key fields; the harmonizer lists every config/org decision.

### Phase C — Bucket 2 (open transactions)  ⬜
- **Objects:** open POs, open sales orders, open deliveries, open purchase requisitions.
- **New logic:** "select only OPEN documents as of cutover" + reference integrity to
  already-migrated master data.
- **Done when:** open documents land with correct references and open quantities/values
  reconcile to the source open list.

### Phase D — Bucket 3 (balances — the core)  ⬜  *(highest stakes)*
Build in this sub-order; each must reconcile to the cent before the next starts:
- **D1 — G/L balances:** opening balances posted against a **data-migration clearing account**
  (Cockpit "FI-GL balances" / `BAPI_ACC_DOCUMENT_POST`).
- **D2 — AR/AP open items:** posted as open items referencing migrated customers/vendors.
- **D3 — Inventory stock:** quantities **and** values into migrated materials' plants
  (`BAPI_GOODSMVT_CREATE` mvt 561 / Cockpit stock object).
- **D4 — Fixed assets incl. values:** asset master + takeover values (asset takeover BAPI).
- **Cross-cutting for D:** period/fiscal-year/open-period control; debits=credits gate;
  reconciliation to the source **trial balance / stock report / AR-AP aging** with **zero
  tolerance**.
- **Done when:** target trial balance = source trial balance; stock = stock; aging = aging.

### Phase E — Cutover orchestration + validation  ⬜
- **Goal:** one sequenced, resumable cutover with sign-off gates and end-to-end proof.
- **Deliverables:** dependency-sequencing engine (master → open → balances); period-close
  handling; per-object sign-off gates (reuse the existing HMAC governance gates); a single
  **end-to-end reconciliation report** (trial balance, stock, aging, object counts).
- **Done when:** a full three-bucket migration runs in order on a fresh target and produces a
  reconciliation report that ties out.

---

## 5. Requirements & non-negotiables

1. **Persistent target system.** Months of work; a 30-day CAL box resets. Use a longer CAL
   lease or a stable cloud S/4 that survives across the build.
2. **Functional SAP finance gate for Bucket 3 (the one human-expert insistence).** The
   *technical* load I can build and prove; whether the *financial result is correct* (right
   clearing account, right period, ties to the trial balance) needs one functional
   consultant's eyes before any customer is told "your books migrated."
3. **Config prerequisites are the customer's to flip** — Material Ledger (valuation), FI-AA
   (assets), tax config, etc. The tool **detects and lists** them (harmonizer already does);
   it never silently assumes them.
4. **Fresh-target discipline** — migrate objects **complete** via the Cockpit; never "load
   basic first, extend later" (that created materials the Cockpit refuses to extend — see the
   2026-07-29 finding in the review docs).

---

## 6. Risk register (honest)

| Risk | Severity | Mitigation |
|---|---|---|
| Bucket 3 financial correctness (tie to the cent) | **High** | Reconcile-to-source gate per object; functional consultant review |
| Cutover sequencing / period control errors | High | Phase E dependency engine + period checks; dry-run on fresh target |
| SAP run-step is app-gated (S/4 2025 Cockpit) | Medium | Automate all staging via RFC; accept ~2 human clicks per run (constant, not per-record) |
| Breadth fatigue (100+ objects) | Medium | Phase A engine makes each object a recipe, not a build |
| Target instability (CAL resets) | Medium | Persistent target (req. #1) |
| Reverse-engineering SAP internals is fragile | Medium | Stay on supported Cockpit/BAPI lanes (lesson: the MATMAS-probe incident that broke the kit group) |

---

## 7. Current proven baseline (as of 2026-07-29)

Client 200 (this appliance), read-back verified: Customers 700 · Vendors 2,416 ·
Materials-Basic 24,011 · Banks 19,059 · Sales orders 14,700 · Profit centers 307 ·
Cost centers 1,768 · G/L accounts 1,818. Materials **sales + tax** proven through the MC lane
in **simulation** (MG172 cleared) — actual Migrate landing pending a fresh target.
Infrastructure per §2 is live. Full evidenced state: `EXPERT_REVIEW_BRIEF.md` /
`EXPERT_REVIEW_DETAILED.md`.

---

## 8. Immediate next step

**Phase A — the universal staging engine.** It is the multiplier that makes B, C, and D fast.
Kick off on the founder's signal. First milestone = re-express the material Product object as a
recipe running through the generic engine, then prove a second object from a recipe with zero
new code.

*Relationship to `ROADMAP.md`: this doc is the detailed build plan for the object-breadth
dimension (its Tier 1). The other tiers there — connectivity, auto-discovery, target
provisioning, code remediation, SaaS, cutover automation — proceed independently.*
