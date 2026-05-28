# Breadth Tracker — object coverage toward the full Migration-Cockpit catalog (120+)

Status legend: ✅ live (load + reconcile proven) · 🔜 BAPI confirmed, build queued · 🔀 routes to
non-BAPI lane (MC file / LTMOM / transport / manual-gate) · ❓ needs investigation.

Recipe per object: probe BAPI/OData + ECC source → `create_<obj>` (+ idempotency + reconcile-key)
→ discovery if needed → wire 4 files (`bapi_loader`, `unified_loader` ×2, `handler`) → live
load+reconcile RECONCILED → commit. See `BREADTH_BUILDOUT_PROMPT.md`.

## Live today (✅ 17)
BusinessPartner · Customer · Vendor · Material · ExchangeRates · OpenPO · OpenAR · OpenAP ·
CostCenter · ProfitCenter · FixedAsset · **Bank** · **InternalOrder** · **Equipment** · **FunctionalLocation** · **Characteristic** · **Class**

## Queued — clean released BAPI confirmed on this S/4 (🔜)
| Object | BAPI | ECC source | Notes |
|---|---|---|---|
| Batch | BAPI_BATCH_CREATE | MCH1 (~1,775) | needs material+batch |
| CostElementGroup | BAPI_COSTELEMENTGRP_CREATE | SETLEAF cls 0102 (~1,422) | CO group/hierarchy |
| ProfitCenterGroup | BAPI_PROFITCENTERGRP_CREATE | SETLEAF cls 0106 (~543) | CO group/hierarchy |
| WBS/Project | BAPI_PROJECTDEF_CREATE | PROJ | PS |
| Routing | BAPI_ROUTING_CREATE | PLKO | PP (structured) |
| PurchaseContract | BAPI_CONTRACT_CREATE | EKKO BSTYP='K' | MM (items) |
| PurchaseRequisition | BAPI_PR_CREATE | EBAN | MM (open docs) |
| OpenSO (Sales Order) | BAPI_SALESORDER_CREATEFROMDAT2 | VBAK | SD (open docs) |

## Need investigation (❓ — probed FM name not RFC-callable; find the right FM/route)
ActivityType (CSLA ~676) · StatisticalKeyFigure (TKA03 ~447) · CommitmentItem (FMCI ~1,297)

## Route to non-BAPI lane (🔀)
- **GLAccount** — no RFC master-create BAPI on S/4 → Migration Cockpit / OData lane (chart YIKR; cross-COA map).
- GLBalances / InventoryBalances / NumberRanges / CustomZTable — manual_gate by design (object-router).

## Honest ceiling
~40–60 of the ~120 MC objects fit the released-BAPI/OData spine; the rest are intentionally
file-based (MC) / LTMOM / transport / manual-gate. Coverage = (BAPI-loaded) + (correctly-routed),
both documented.
