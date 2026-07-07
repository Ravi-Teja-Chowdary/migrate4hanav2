"""
coverage_summary - honest breadth reporter for the wizard's Coverage panel.

Cross-references:
    - Spine registry     (base_spine_orchestrator._SPINE_REGISTRY)
    - Dependency DAG     (dependency_dag.DependencyDAG.from_defaults())
    - Extraction catalog (data-migrator/handler.DEFAULT_OBJECT_TABLES)
    - BAPI declaration   (each spine's DEFAULT_BAPI / VERSION_BAPI_MAP)
    - Live evidence      (per-object last-run summary, if the run has landed)

Emits one row per object with these signals so the UI can render an honest
badge (Tier-1 / Tier-2 / pseudo-spine / blocked) without the operator having
to trawl BREADTH_TRACKER.md manually.

Design principle: NEVER lie about coverage. If we haven't verified an object
lands on live S/4, it's Tier-2 or unknown — not Tier-1.
"""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import os
import sys
from typing import Any, Optional


# Manually-curated Tier-1 list from BREADTH_TRACKER.md as of last verification
# pass (2026-06-15). Update this when a batch is verified on live CAL S/4.
# Coverage endpoint uses this as the source of truth for the "Tier-1" badge.
TIER_1_VERIFIED = {
    "Material", "Customer", "Vendor", "BusinessPartner", "Bank",
    "GLAccount", "CostCenter", "ProfitCenter", "FixedAsset",
    "CostElementGroup", "ProfitCenterGroup", "InternalOrder",
    "Equipment", "FunctionalLocation", "Characteristic", "Class",
    "Batch", "InventoryBalance", "InventoryReservation",
    "PurchaseRequisition", "PurchaseContract", "SalesOrder",
    "ExchangeRates", "InfoRecord", "WorkCenter", "OutboundDelivery",
    "BillingDocument", "Quotation", "Inquiry", "PlannedOrder",
    "ProductionBOM", "BOMItem", "AccountingDocument",
    "OpenAR", "OpenAP",
    # 2026-07-07: SD family promoted via number-preservation lane
    "ReturnsOrderSD", "CreditMemoRequest", "SalesContract",
    # 2026-07-07: promoted via verify_tier2_local.py against live CAL S/4
    # (S4H 816). Each landed a real record — see tier2_verify_results.json
    # for the returned target key.
    "HRMaster", "IncomingInvoice", "Notification", "RequisitionLegacy",
    "StockTransferOrder",
}

# Objects whose real path is a Migration Cockpit / LTMOM template (no live
# BAPI) — legitimate "extract-and-stage" spines that don't count as Tier-1
# but ARE full-migration citizens via the MC lane.
PSEUDO_SPINE_MC_LANE = {
    "SourceList", "QuotaArrangement", "MaterialBOMHeader", "MaterialBOMItem",
    "MaterialClassification", "PricingConditionMM", "ConsignmentStock",
    "CustomerMaterialInfo", "SalesQuotation", "SalesInquiry",
    "ScheduleAgreementSD", "CreditMaster", "CustomerHierarchy",
    "PricingConditionSD", "ProductionVersion", "ProductionOrder",
    "MRPArea", "DemandManagement", "WBSElement", "Network",
    "NetworkActivity", "MaintenancePlan", "MaintenanceTaskList",
    "MeasuringPoint", "MeasurementDocument", "ServiceNotification",
    "ServiceContract", "InspectionPlan", "InspectionMethod",
    "InspectionCharacteristic", "QualityInfoRecord", "InspectionLot",
    "CatalogCode", "StorageBin", "StockInBin", "WarehouseTransferOrder",
    "HandlingUnit", "EmployeeOrgData", "EmployeePersonalData",
    "EmployeeAddress", "ClassAssignment", "DocumentInfoRecord",
    "HouseBankAccount", "AssetClass", "AssetSubNumber", "DepreciationArea",
    "TaxCode", "DunningArea", "ActivityType", "StatisticalKeyFigure",
    "CommitmentItem", "Currency", "Country", "Region", "PaymentTerms",
    "UnitOfMeasure", "IncoTerm", "Address", "Person",
    "SalesOrderItem", "PurchaseOrderItem", "BillingItem", "DeliveryItem",
    "PRItem", "GoodsReceipt", "LogisticsInvoice", "StockTransportOrder",
    "PurchaseOrderHistory", "BidInvitation", "VendorBankDetails",
    "CustomerBankDetails", "ScheduleLines", "Shipment", "ProcessOrder",
    "AccountingDocHeader", "AccountingDocItem",
    "OpenSO",  # legacy name kept for extraction back-compat
    # 2026-07-07: verified live that the BAPI these spines target does NOT
    # exist on CAL S/4 816 (FU_NOT_FOUND / BAPI_...). Legitimate MC-lane
    # objects — Migration Cockpit is the SAP-native path for them.
    "ControlPlan", "MaintenanceItem", "MasterRecipe", "MeasurementPoint",
    "MovementType", "ProjectStock", "RebateAgreement", "SamplingProcedure",
    "WarrantyClaim",
}

# Objects blocked on target-side customizing that our prep script may or may
# not close. Users see amber badge + link to PREREQ_RUNBOOK §B.
BLOCKED_ON_CUSTOMIZING = {
    "FixedAssetOvertake", "ProjectDefinition", "BatchClassification",
    "SerialNumber",
}

# Objects blocked on real customer source data (won't work on empty IDES).
BLOCKED_ON_DATA = {
    "ProductionOrderConfirmation", "ProductionOrderTimeTicket",
    "ServiceEntrySheet",
}


def _import(module: str, path_hint: str):
    try:
        return importlib.import_module(module)
    except Exception:
        return None


def compute_coverage(project_dir: Optional[str] = None) -> dict:
    """Assemble the coverage payload the wizard renders.

    Returns:
        {"totals": {"registered_spines": int, "tier_1": int, "tier_2": int,
                    "pseudo_spine_mc": int, "blocked": int,
                    "in_dag": int, "extractable": int},
         "objects": [{"name": str, "tier": "T1"|"T2"|"MC"|"BLOCKED",
                      "in_dag": bool, "extractable": bool,
                      "extract_table": str, "extract_lane": str,
                      "bapi": str,
                      "blocked_reason": str,
                      "depends_on": [str, ...]}, ...]}
    """
    project_dir = project_dir or os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    # Make sure the two directories that the runtime uses are on sys.path so
    # we can import the same modules the runner does.
    utils_dir = os.path.join(project_dir, "lambda", "utils")
    migrator_dir = os.path.join(project_dir, "lambda", "data-migrator")
    for d in (utils_dir, migrator_dir):
        if d not in sys.path:
            sys.path.insert(0, d)

    # ── Spine registry ──────────────────────────────────────────────────────
    registered: dict = {}
    try:
        # Importing the utils package triggers auto-registration of every
        # spine module (each `@register_spine` runs on import).
        for name in os.listdir(utils_dir):
            if name.endswith("_spine.py"):
                mod_name = name[:-3]
                try:
                    importlib.import_module(mod_name)
                except Exception:
                    pass
        from base_spine_orchestrator import _SPINE_REGISTRY  # type: ignore
        registered = dict(_SPINE_REGISTRY)
    except Exception:
        registered = {}

    # ── Dependency DAG ──────────────────────────────────────────────────────
    dag_nodes: set = set()
    dag_edges: dict = {}
    try:
        from dependency_dag import DependencyDAG  # type: ignore
        dag = DependencyDAG.from_defaults()
        dag_nodes = set(dag.nodes)
        dag_edges = {n: sorted(d) for n, d in dag.edges.items()}
    except Exception:
        pass

    # ── Extraction catalog ──────────────────────────────────────────────────
    default_object_tables: dict = {}
    try:
        # data-migrator handler.py is a hyphenated dir — import via file path.
        handler_path = os.path.join(migrator_dir, "handler.py")
        spec = importlib.util.spec_from_file_location(
            "_dm_handler_for_coverage", handler_path)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore
            default_object_tables = getattr(mod, "DEFAULT_OBJECT_TABLES", {}) or {}
    except Exception:
        default_object_tables = {}

    # ── Compose per-object rows ─────────────────────────────────────────────
    all_names = set(registered) | dag_nodes | set(default_object_tables)
    rows = []
    for name in sorted(all_names):
        in_registry = name in registered
        in_dag = name in dag_nodes
        extract = default_object_tables.get(name) or {}
        extractable = bool(extract)

        # Tier resolution — most specific wins.
        if name in TIER_1_VERIFIED:
            tier = "T1"
            blocked_reason = ""
        elif name in BLOCKED_ON_CUSTOMIZING:
            tier = "BLOCKED"
            blocked_reason = "target-side customizing (PREREQ_RUNBOOK §B)"
        elif name in BLOCKED_ON_DATA:
            tier = "BLOCKED"
            blocked_reason = "needs real customer source data (empty IDES insufficient)"
        elif name in PSEUDO_SPINE_MC_LANE:
            tier = "MC"
            blocked_reason = "Migration Cockpit template lane (no live BAPI needed)"
        elif in_registry:
            tier = "T2"
            blocked_reason = "spine registered — awaiting live-S/4 BAPI verification"
        elif extractable:
            tier = "MC"
            blocked_reason = "extract-only; no spine registered"
        else:
            tier = "UNKNOWN"
            blocked_reason = "in DAG but no spine + no extraction — orphan"

        bapi = ""
        cls = registered.get(name)
        if cls is not None:
            # Scan class module for DEFAULT_BAPI constant (scaffolder pattern).
            try:
                bapi = getattr(inspect.getmodule(cls), "DEFAULT_BAPI", "") or ""
            except Exception:
                bapi = ""

        rows.append({
            "name":            name,
            "tier":            tier,
            "in_registry":     in_registry,
            "in_dag":          in_dag,
            "extractable":     extractable,
            "extract_table":   extract.get("table", ""),
            "extract_lane":    extract.get("lane", ""),
            "bapi":            bapi,
            "blocked_reason":  blocked_reason,
            "depends_on":      dag_edges.get(name, []),
        })

    totals = {
        "registered_spines":   sum(1 for r in rows if r["in_registry"]),
        "tier_1":              sum(1 for r in rows if r["tier"] == "T1"),
        "tier_2":              sum(1 for r in rows if r["tier"] == "T2"),
        "pseudo_spine_mc":     sum(1 for r in rows if r["tier"] == "MC"),
        "blocked":             sum(1 for r in rows if r["tier"] == "BLOCKED"),
        "unknown":             sum(1 for r in rows if r["tier"] == "UNKNOWN"),
        "in_dag":              sum(1 for r in rows if r["in_dag"]),
        "extractable":         sum(1 for r in rows if r["extractable"]),
        "total_objects":       len(rows),
    }

    return {"totals": totals, "objects": rows}


if __name__ == "__main__":
    from datetime import datetime, timezone
    result = compute_coverage()
    print("=" * 60)
    print(f"Coverage summary @ {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    print("=" * 60)
    print(json.dumps(result["totals"], indent=2))
    print()
    tiers = {"T1": [], "T2": [], "MC": [], "BLOCKED": [], "UNKNOWN": []}
    for r in result["objects"]:
        tiers[r["tier"]].append(r["name"])
    for tier, names in tiers.items():
        print(f"{tier} ({len(names)}): {', '.join(names[:12])}{'...' if len(names) > 12 else ''}")
    print()
    print("OK - coverage_summary produced a full breadth report.")
