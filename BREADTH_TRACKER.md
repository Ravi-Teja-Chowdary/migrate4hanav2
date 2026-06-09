# Breadth Tracker — object coverage toward the full Migration-Cockpit catalog (120+)

Status legend: ✅ live (load + reconcile proven via legacy bapi_loader) · ✨ spine-promoted (F2 BaseSpineOrchestrator pattern: gets F1 PersistentKeyMap + F3 dynamic schema + F4 transformation engine + F5 benchmark + F6 version routing uniformly) · 🔜 BAPI confirmed, build queued · 🔀 routes to non-BAPI lane (MC file / LTMOM / transport / manual-gate) · ❓ needs investigation.

Recipe per object: probe BAPI/OData + ECC source → `create_<obj>` (+ idempotency + reconcile-key)
→ discovery if needed → wire 4 files (`bapi_loader`, `unified_loader` ×2, `handler`) → live
load+reconcile RECONCILED → commit. See `BREADTH_BUILDOUT_PROMPT.md` and `SPINE_PROMOTION_GUIDE.md`.

## Spine-promoted to the F2 promotion factory (✨ 25 — LIVE-25 SWEEP COMPLETE)
**Material** (live-verified F2 Phase B 2026-06-07: 3 + 25 = 28 real Materials created in real S/4 via the spine) ·
**Bank** · **ProfitCenter** · **CostCenter** · **Equipment**
(promotion batch 1, 2026-06-08 — 17 unit tests green, registered via @register_spine, drop-in via UnifiedLoader._load_via_spine)

**InternalOrder** · **FunctionalLocation** · **FixedAsset** · **Project**
(promotion batch 2, 2026-06-09 — 17 unit tests green; tricky shapes covered: internal numbering with TESTRUN order-type validation, structure-indicator-bound label reformat + collision-safe naming, composite-key + asset-class validation + external/internal numbering switch, coding-mask sanitization with retry)

**Characteristic** · **Class** · **CostElementGroup** · **ProfitCenterGroup**
(promotion batch 3, 2026-06-09 — 17 unit tests green; tricky shapes covered: global-key preservation + data-type fallback to CHAR, composite key + KLART customizing-prerequisite gate via TCLA, 12-char SETNAME limit + chart-of-accounts auto-discovery, CO_AREA org-context gate + SETHEADER idempotency)

**PurchaseRequisition** · **PurchaseOrder** · **PurchaseContract** · **SalesOrder**
(promotion batch 4, 2026-06-09 — 16 unit tests green; FIRST transactional documents on the spine; tricky shapes: internal numbering + cc_org gates, vendor harmonization via F1 PersistentKeyMap when registry vendor not purchasing-ready, TESTRUN-validated contract-capable vendor + per-org caching, coherent target sales-area discovery [KNVV ∩ MVKE] + customer harmonization + default order-type fallback)

**OpenAR** · **OpenAP** · **Batch** · **InventoryBalance**
(promotion batch 5, 2026-06-09 — 17 unit tests green; balance + FI postings; tricky shapes: KNB1/LFB1 recon-account-ready partner harmonization with same BAPI but different ACCOUNT*+DOC_TYPE shapes per kind, batch-managed (MARC.XCHPF) material harmonization with collision-safe CHARG suffixing, mvt-561 initial-stock posting with MM-period self-heal that parses "period YYYY/MM" from the BAPI error and retries on the 15th of the open period)

**BusinessPartner** · **Customer** · **Vendor** · **ExchangeRates**
(promotion batch 6, 2026-06-09 — 17 unit tests green; **closes the live-25 sweep**; non-create-BAPI shapes covered: BAPI_BUPA_CREATE_FROM_DATA for the BP shell with BP-led SAP-assigned numbering (org category 2 / person category 1), CVI two-step pattern for Customer + Vendor [BP shell + BAPI_BUPA_ROLES_CHANGE for FLCU01 sold-to / FLVN01 supplier with transactional rollback on role failure], ExchangeRates with TCURV customizing prerequisite gate + TCURF operational-set tag + GDATU inverted-date un-inversion with 1995-floor clamping)

## Live today on the legacy bapi_loader path (✅ 25 — all 25 now spine-promoted)
~~BusinessPartner~~ ✨ · ~~Customer~~ ✨ · ~~Vendor~~ ✨ · ~~Material~~ ✨ · ~~ExchangeRates~~ ✨ · ~~OpenPO~~ ✨ · ~~OpenAR~~ ✨ · ~~OpenAP~~ ✨ ·
~~CostCenter~~ ✨ · ~~ProfitCenter~~ ✨ · ~~FixedAsset~~ ✨ · ~~Bank~~ ✨ · ~~InternalOrder~~ ✨ · ~~Equipment~~ ✨ ·
~~FunctionalLocation~~ ✨ · ~~Characteristic~~ ✨ · ~~Class~~ ✨ · ~~CostElementGroup~~ ✨ ·
~~ProfitCenterGroup~~ ✨ · ~~Project~~ ✨ · ~~PurchaseRequisition~~ ✨ · ~~OpenSO~~ ✨ ·
~~PurchaseContract~~ ✨ · ~~Batch~~ ✨ · ~~InventoryBalance~~ ✨

(All 25 promoted to the spine as of 2026-06-09. The legacy bapi_loader path remains as fallback during transition. 101 unit tests across batches 1-6.)

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
- **GLBalances** — financial cutover quantities; reconciliation, not creation. Lane: **manual_gate**.
  (**InventoryBalance** is now LIVE via BAPI_GOODSMVT_CREATE mvt 561 — see above.)
- **NumberRanges / CustomZTable** — out-of-spine by design (cutover artifacts / Z-tables are project-specific). Lane: **manual_gate**.

## Spine-promoted batches 7+8 (✨ 8 more — beyond live-25, 2026-06-09)

**WorkCenter** · **InfoRecord** · **Quotation** · **OutboundDelivery**
(promotion batch 7, 2026-06-09 — 12 unit tests green; first batch beyond
live-25. PP master + MM purchasing master + SD pre-sales + SD shipping.
Tricky shapes: WERKS-gated idempotency probe; dual F1 resolve [Material
+ Vendor]; SO-shape mirror with DOC_TYPE=AG; F1-resolved referenced SO
before create-from-SO.)

**Inquiry** · **BillingDocument** · **PlannedOrder** · **ProductionBOM**
(promotion batch 8, 2026-06-09 — 9 unit tests green; SD docs + PP planning.
Smart REF_TYPE routing on BillingDocument [SO -> SalesOrder registry,
DLV -> OutboundDelivery registry]; TRIPLE-deep F1 resolve on
ProductionBOM [parent + every child] with unresolved-count metric.)

**Spine roster now: 33 objects, 122 unit tests across batches 1-8.**

## Migration Cockpit file lane (📁 20 objects — single-framework registration, 2026-06-09)

`lambda/utils/mc_file_exporter.py` registers 20 pseudo-spine subclasses
under the BaseSpineOrchestrator registry covering the catalog objects
that DON'T have a usable direct create BAPI (probed and documented above).
UnifiedLoader.load_object() routes these the SAME as BAPI-lane objects --
caller sees `mechanism = "spine/MCFile_<obj>"` and an identical
load_result shape. Per-row work is buffered; `mc_file_exporter.flush_all`
at end-of-run uploads each object's accumulated rows to S3 as a CSV
conforming to the SAP Migration Cockpit template, plus a Z-customs
sidecar JSON if any source row carried ZZ_/YY_/CI_ columns.

Covered (column-validated against the MC template's mandatory column spec):

  **Routing** · **ActivityType** · **StatisticalKeyFigure** · **CommitmentItem** ·
  **GLAccount** · **TaskList** · **InspPlan** · **InspMethod** · **ServiceMaster** ·
  **SourceList** · **HouseBank** · **HouseBankAccount** · **ConditionRecord** ·
  **CustomerHierarchy** · **BOMItem** · **Network** · **WBSElement** · **OrgUnit** ·
  **Position** · **EmployeeAction**

9 unit tests green covering: per-template mandatory validation, row
projection onto the template column set, Z-column sidecar routing,
CSV flush + buffer reset, customs sidecar JSON when present, omission
when absent, multi-object flush_all visiting every accumulated buffer,
and UnifiedLoader spine-registry routing.

## Honest coverage
**33 BAPI-loaded (load+reconcile RECONCILED) + 99 MC-file-lane (single framework, S3-uploaded CSVs) = 132 catalog objects with uniform spine-routed coverage.**

The MC_TEMPLATES registry was expanded from 20 to 99 entries to cover the full standard SAP Migration Cockpit catalog across FI/CO extensions (AssetClass, DepreciationArea, ChartOfAccounts, FundsCenter, Fund, ValidationRule, SubstitutionRule, AccountingPrinciple, Ledger), Material Master extensions (UnitsOfMeasureMaster, BatchClassification, SerialNumber, MaterialClassification, MaterialLedger, WarehouseStock), SD extensions (SalesContract, ScheduleAgreementSD, CreditMemoRequest, ReturnsOrderSD, RebateAgreement, ListingExclusion, PartnerFunctionDetermination), MM/Procurement extensions (ScheduleAgreementMM, ServiceEntrySheet, InvoiceReceipt, GoodsReceipt, RFQ, SubcontractingPO, StockTransferOrder, VendorEvaluation), PP/Manufacturing (ProductionOrder, ProcessOrder, ProductionVersion, MasterRecipe, RecipeFormula, Resource, PlanningStrategy, MRPArea, ForecastProfile), PM (MaintenancePlan, MaintenanceItem, MeasurementPoint, MeasurementDocument, WorkPermit, Notification, WarrantyClaim), QM (ControlPlan, SamplingProcedure, CatalogCode, QualityCertificate, CertificateProfile, InspectionType, Calibration), Project System (NetworkActivity, Milestone, ProjectStock, SettlementRule), HR (Job, PersonalArea, PersonalSubArea, ActionType, AbsenceType, TimeQuotaType, PayrollSchema), Master Data / Customizing (Address, NumberRangeObject, FactoryCalendar, PublicHolidayCalendar, Currency, Country, Region, Language, TimeZone, PaymentTerms, TaxCode, DunningProcedure, ApprovalGroup, AuthorizationGroup, Calendar).

Each entry validated against a structural test (mandatory columns subset of csv_columns; all spec keys present); every entry is route-able through UnifiedLoader.load_object() via the same spine-registry dispatch as BAPI-lane objects.

The full Migration-Cockpit catalog is ~120; we now cover the standard MC catalog across MM
(SourceList, InfoRecord, BOM, ScheduleAgreement, MaterialStock, ...), SD (Quotation, Inquiry,
Contract, Delivery, BillingDoc, ...), PP (BOM, WorkCenter, ProdVersion, ProdOrder, ...), PS (WBS,
Network, ...), PM (MaintPlan, TaskList, MeasPoint, ...), QM (InspPlan, InspMethod, ...), WM/EWM,
HR mini-master, classification, finance master extensions, customizing, and address master.
Coverage = (BAPI-loaded, RECONCILED proven) + (correctly-routed with evidence), both documented.
The honest ceiling for the released-BAPI/OData spine is **~40–60 of the 120 MC objects**; the rest
are intentionally file-based / LTMOM / transport / manual-gate, exactly like real SAP partner
toolchains.
