# migrate4hana — Migration Decision Checklist

_Generated 2026-07-29 11:30 · 6 auto-handled · **12 need a human**_

This is the honest gap between your ECC data and the new S/4 system. Everything under 🧭 is a **business decision**; the rest we handle.


## 🧭 Decisions only you can make (org mapping)

_The old and new systems have different org structures. Pick a mapping for each — nothing loads into these areas until you do._

- ⛔ **decide** — **plant: 226 source values have no target equivalent**  
  The source uses 226 plant(s) that don't exist on the target. Each needs a mapping decision (old plant → new plant) or the org unit created on the target. Affects: material.
  
  _e.g._ `0002, 0005, 0006, 0007, 0008, 1000, 1100, 1200, 1300, 1400, 1500, 1600, 1901, 2000, 2010`
  
  → _DECIDE: map each source plant to a target plant_

- ⛔ **decide** — **purchasing org: 92 source values have no target equivalent**  
  The source uses 92 purchasing org(s) that don't exist on the target. Each needs a mapping decision (old purchasing org → new purchasing org) or the org unit created on the target. Affects: vendor.
  
  _e.g._ `0005, 0006, 1, 1000, 1100, 2, 2000, 2200, 2222, 2300, 2400, 2500, 2700, 2800, 2820`
  
  → _DECIDE: map each source purchasing org to a target purchasing org_

- ⛔ **decide** — **sales org: 65 source values have no target equivalent**  
  The source uses 65 sales org(s) that don't exist on the target. Each needs a mapping decision (old sales org → new sales org) or the org unit created on the target. Affects: customer, material, sales_order.
  
  _e.g._ `0005, 0006, 1000, 1020, 1030, 2000, 2200, 2220, 2222, 2300, 2400, 2500, 2700, 2800, 2820`
  
  → _DECIDE: map each source sales org to a target sales org_

- ⛔ **decide** — **controlling area: 38 source values have no target equivalent**  
  The source uses 38 controlling area(s) that don't exist on the target. Each needs a mapping decision (old controlling area → new controlling area) or the org unit created on the target. Affects: cost_center, profit_center.
  
  _e.g._ `1000, 2000, 2200, 2600, 2800, 2801, 4100, 4200, 4300, 4400, 4500, 4700, 5000, 5100, 5400`
  
  → _DECIDE: map each source controlling area to a target controlling area_

- ⛔ **decide** — **distribution channel: 22 source values have no target equivalent**  
  The source uses 22 distribution channel(s) that don't exist on the target. Each needs a mapping decision (old distribution channel → new distribution channel) or the org unit created on the target. Affects: customer, sales_order.
  
  _e.g._ `12, 14, 16, 20, 22, 24, 30, 40, BD, C1, C2, CB, L1, R1, R2`
  
  → _DECIDE: map each source distribution channel to a target distribution channel_

- ⛔ **decide** — **division: 15 source values have no target equivalent**  
  The source uses 15 division(s) that don't exist on the target. Each needs a mapping decision (old division → new division) or the org unit created on the target. Affects: customer, sales_order.
  
  _e.g._ `04, 05, 07, 08, 14, 17, 18, 28, A1, OO, R1, S1, S3, XL, Z1`
  
  → _DECIDE: map each source division to a target division_

- ⛔ **decide** — **chart of accounts: 12 ECC charts (5609 accounts) not on target**  
  These ECC charts of accounts don't exist on the target, so their accounts can't migrate into a native chart. Decide: create the chart on the target, or map its accounts into a target operational chart (e.g. YCOA) with an account-level translation.
  
  _e.g._ `INT1(1203), CAUS(1156), INTA(1101), CAGB(544), CACA(540), CAAU(354), PCEC(262), CONS(221), BANK(158), ACIA(49), CA20(11), PCG(10)`
  
  → _DECIDE: map each source chart of accounts to a target chart_


## 🔧 Config switches

_Settings the target is missing. Class-C/G ones we flip automatically; the rest need a basis person._

- ⛔ **decide** — **order type: 96 source values not defined on target**  
  The source uses 96 order type(s) the target doesn't define (target has: ['01', 'AA', 'AD1', 'AD2', 'AD3', 'AD9', 'AE', 'AEBO', 'AEBQ', 'AF', 'AFLV', 'AG']…). Each carries its own config (number ranges / account determination), so this is a decision: create it on the target or map to an existing one.
  
  _e.g._ `CBBO, CBDC, CBDD, CBEM, CBOD, CBOR, CBRL, CBRO, CBRP, CBSM, CMOR, CRMR, DOUR, ECO1, ECO2`
  
  → _DECIDE: define each source order type on target, or map to an existing one_

- ⛔ **decide** — **customer account group: 56 source values not defined on target**  
  The source uses 56 customer account group(s) the target doesn't define (target has: ['0001', '0002', '0003', '0004', '0005', '0006', '0007', '0012', '0020', '0100', '0110', '0120']…). Each carries its own config (number ranges / account determination), so this is a decision: create it on the target or map to an existing one.
  
  _e.g._ `3500, BR01, BR02, CPB1, CPB2, DEBL, PLNT, RE, TM1, XLSO, Z001, ZAG1, ZAG2, ZAPO, ZARG`
  
  → _DECIDE: define each source customer account group on target, or map to an existing one_

- ⛔ **decide** — **vendor account group: 19 source values not defined on target**  
  The source uses 19 vendor account group(s) the target doesn't define (target has: ['0001', '0002', '0003', '0004', '0005', '0006', '0007', '0012', '0100', 'CPD', 'CPDL', 'DARL']…). Each carries its own config (number ranges / account determination), so this is a decision: create it on the target or map to an existing one.
  
  _e.g._ `0010, 0020, 0099, 0999, AGNT, BR01, HRTP, LIFA, PLNT, TM1, TM2, VEND, ZAPO, ZARG, ZH02`
  
  → _DECIDE: define each source vendor account group on target, or map to an existing one_

- ⛔ **decide** — **T134: 16 customizing rows missing on target**  
  T134 (delivery class X) has 16 entries in ECC not present on the target. Material type carries number ranges + account refs.
  
  _e.g._ `AEM, BLG, BLGA, COMP, CONU, DOCU, PLM, XLMT, YCON, ZHT1`
  
  → _DECIDE: create these material types on target, or skip those materials_

- ✅ auto — **12 charts overlap — accounts migrate into their native chart**  
  Handled by run_client200_glaccounts.py (GL_ACCT_MASTER_SAVE_RFC): account number + all language texts preserved; GLACCOUNT_TYPE derived from balance-sheet + cost-element category; account-group number ranges auto-widened (governed T077S). Accounts whose group account number references a group chart not on the target are skipped (that group chart is a separate migration).
  
  _e.g._ `CACN, CAES, CAFR, CAIN, CAJP, CAKR, CANA, CARU, CATW, GKR, IKR, INT`
  
  → _auto-migrated via GL_ACCT_MASTER_SAVE_RFC into native charts_

- ✅ auto — **T006: 1 customizing rows missing on target**  
  T006 (delivery class C) has 1 entries in ECC not present on the target. Base unit of measure.
  
  _e.g._ `C`
  
  → _auto-apply 1 rows via Basis Kit (class C)_


## 🧹 Data-quality fixes

_Real source values the pickier target rejects. Auto-handled faithfully (relax a rule, or blank an optional field)._

- ✅ auto — **33 customer records carry a region code the target rejects**  
  Region blanked at load (optional address field); the record still lands.
  
  _e.g._ `AU/AC, GB/CE, GB/GM, GB/LO, SA/00`
  
  → _auto-handled at load: blank invalid REGION_

- ✅ auto — **12 vendor records carry a region code the target rejects**  
  Region blanked at load (optional address field); the record still lands.
  
  _e.g._ `CA/NF, CA/NN, GB/CE, GB/LO, GB/YK, IN/MA, SA/00`
  
  → _auto-handled at load: blank invalid REGION_

- ✅ auto — **8 banks carry a region code the target rejects**  
  Region blanked at load (optional address field); key preserved.
  
  _e.g._ `CA/PQ, CA/PQ, DE/BR, GB/LO, GB/LO, SG/25, SG/25, SG/25`
  
  → _auto-handled at load: blank invalid REGION_

- ✅ auto — **7 banks carry a malformed SWIFT/BIC**  
  SWIFT must be 8 or 11 chars; blanked at load, key preserved.
  
  _e.g._ `CA0001=88888, CA0001000371=77777, DE67292200=DGSG DE 6K, SG0234467=SIG, SG345-234-55=123445, SG345-456-88=123446, US232444545=PBNKUS250`
  
  → _auto-handled at load: blank invalid SWIFT_


## 🚧 SAP limitations we route around

_Not fixable from outside — we take the supported path instead._

- ⛔ **decide** — **Sales & valuation views not loadable via the standard BAPI**  
  BAPI_MATERIAL_SAVEDATA ignores TAXCLASSIFICATIONS (MG172) so the sales view can't be set from outside; the valuation view needs Material Ledger production-startup (CKMSTART), a transaction. Materials migrate as the client-level Basic view; these two views are a separate, post-basic step.
  
  → _ACCEPT: Basic view migrates now; sales/valuation views are a follow-on_


> 6 auto-fixable items detected. Re-run with `--apply` to flip the safe config switches.
