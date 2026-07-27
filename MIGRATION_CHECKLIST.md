# migrate4hana — Migration Decision Checklist

_Generated 2026-07-27 12:17 · 3 auto-handled · **4 need a human**_

This is the honest gap between your ECC data and the new S/4 system. Everything under 🧭 is a **business decision**; the rest we handle.


## 🧭 Decisions only you can make (org mapping)

_The old and new systems have different org structures. Pick a mapping for each — nothing loads into these areas until you do._

- ⛔ **decide** — **plant: 226 source values have no target equivalent**  
  The source uses 226 plant(s) that don't exist on the target (target only has: ['0001', '0003', '1010', '1011', '1012', '1020', '1710', '1711', '1712', '1720', 'FOBP', 'FORP']…). Each needs a mapping decision (old plant → new plant) or the org unit created on the target.
  
  _e.g._ `0002, 0005, 0006, 0007, 0008, 1000, 1100, 1200, 1300, 1400, 1500, 1600, 1901, 2000, 2010`
  
  → _DECIDE: map each source plant to a target plant_

- ⛔ **decide** — **sales org: 64 source values have no target equivalent**  
  The source uses 64 sales org(s) that don't exist on the target (target only has: ['0001', '0003', '1010', '1710', 'FOBP', 'FORP']…). Each needs a mapping decision (old sales org → new sales org) or the org unit created on the target.
  
  _e.g._ `0005, 0006, 1000, 1020, 1030, 2000, 2200, 2220, 2222, 2300, 2400, 2500, 2700, 2800, 2820`
  
  → _DECIDE: map each source sales org to a target sales org_


## 🔧 Config switches

_Settings the target is missing. Class-C/G ones we flip automatically; the rest need a basis person._

- ⛔ **decide** — **T134: 16 customizing rows missing on target**  
  T134 (delivery class X) has 16 entries in ECC not present on the target. Material type carries number ranges + account refs.
  
  _e.g._ `AEM, BLG, BLGA, COMP, CONU, DOCU, PLM, XLMT, YCON, ZHT1`
  
  → _DECIDE: create these material types on target, or skip those materials_

- ✅ auto — **T006: 1 customizing rows missing on target**  
  T006 (delivery class C) has 1 entries in ECC not present on the target. Base unit of measure.
  
  _e.g._ `C`
  
  → _auto-apply 1 rows via Basis Kit (class C)_


## 🧹 Data-quality fixes

_Real source values the pickier target rejects. Auto-handled faithfully (relax a rule, or blank an optional field)._

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


## Auto-applied this run

- `T006`: 0 applied, 1 failed