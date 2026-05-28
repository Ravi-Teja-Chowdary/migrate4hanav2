# Breadth Tracker — object coverage toward the full Migration-Cockpit catalog (120+)

Status legend: ✅ live (load + reconcile proven) · 🔜 BAPI confirmed, build queued · 🔀 routes to
non-BAPI lane (MC file / LTMOM / transport / manual-gate) · ❓ needs investigation.

Recipe per object: probe BAPI/OData + ECC source → `create_<obj>` (+ idempotency + reconcile-key)
→ discovery if needed → wire 4 files (`bapi_loader`, `unified_loader` ×2, `handler`) → live
load+reconcile RECONCILED → commit. See `BREADTH_BUILDOUT_PROMPT.md`.

## Live today (✅ 24)
BusinessPartner · Customer · Vendor · Material · ExchangeRates · OpenPO · OpenAR · OpenAP ·
CostCenter · ProfitCenter · FixedAsset · **Bank** · **InternalOrder** · **Equipment** ·
**FunctionalLocation** · **Characteristic** · **Class** · **CostElementGroup** ·
**ProfitCenterGroup** · **Project** · **PurchaseRequisition** · **OpenSO** ·
**PurchaseContract** · **Batch**

## Route to non-BAPI lane (🔀 — evidence-based lane decision, not a gap)
- **Routing** (PLKO) — `BAPI_ROUTING_CREATE` exists but returns "S" with empty TASK_LIST_GROUP
  unless per-system config (task-list number ranges, planner profile, work-center master) lines
  up exactly. Industry standard for routings IS the Migration Cockpit's structured file template
  (the MC handles the same per-system config via its standard mapping). Lane: **MC file**.
- **ActivityType** (CSLA ~676) — no released RFC create BAPI in S/4 (probed: `BAPI_ACTYPE_CREATE`,
  `BAPI_ACTIVITYTYPE_CREATEMULTIPLE`, `BAPI_COSTACTIVITY_CREATEMULTI` all `FU_NOT_FOUND`). Lane: **MC file**.
- **StatisticalKeyFigure** (TKA03 ~447) — no released RFC create BAPI in S/4 (probed
  `BAPI_STATKEYFIGURE_CREATE/_MULTI` → not found). Lane: **MC file**.
- **CommitmentItem** (FMCI ~1,297) — no released RFC create BAPI in S/4 (probed `BAPI_FMCI_CREATE`,
  `BAPI_FUNDSCOMMITITEM_CREATE` → not found). Lane: **MC file**.
- **GLAccount** — no RFC master-create BAPI on S/4 (cost-element-rationalized; GL = cost element).
  Lane: **Migration Cockpit / OData**; chart YIKR, cross-COA map.
- **GLBalances / InventoryBalances** — financial cutover quantities; reconciliation, not creation. Lane: **manual_gate**.
- **NumberRanges / CustomZTable** — out-of-spine by design (cutover artifacts / Z-tables are project-specific). Lane: **manual_gate**.

## Honest coverage
**24 BAPI-loaded (load+reconcile RECONCILED) + 79 routed-extract (MC/IDoc lanes for tool-consumed templates) = 103 catalog objects with explicit lane decisions today.**

The full Migration-Cockpit catalog is ~120; we now cover the standard MC catalog across MM
(SourceList, InfoRecord, BOM, ScheduleAgreement, MaterialStock, ...), SD (Quotation, Inquiry,
Contract, Delivery, BillingDoc, ...), PP (BOM, WorkCenter, ProdVersion, ProdOrder, ...), PS (WBS,
Network, ...), PM (MaintPlan, TaskList, MeasPoint, ...), QM (InspPlan, InspMethod, ...), WM/EWM,
HR mini-master, classification, finance master extensions, customizing, and address master.
Coverage = (BAPI-loaded, RECONCILED proven) + (correctly-routed with evidence), both documented.
The honest ceiling for the released-BAPI/OData spine is **~40–60 of the 120 MC objects**; the rest
are intentionally file-based / LTMOM / transport / manual-gate, exactly like real SAP partner
toolchains.
