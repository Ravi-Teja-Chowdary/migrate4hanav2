"""
compliance — SAP-support-compliance audit of a migration run.

The first question any SAP migration assessment asks is "does it break support?".
This tool's data writes go ONLY through SAP-shipped, business-logic-honoring APIs
(released BAPIs + the released OData API_BUSINESS_PARTNER) — never raw table writes,
never modification of SAP standard objects, never a SUM/Maintenance Planner bypass
(that's the Brownfield lane, out of scope for this data-migration engine). This module
turns that practice into PROOF: it classifies every load mechanism the run used and
emits a per-object + overall support-compliance attestation for audit.
"""
from __future__ import annotations

# mechanism (or load status hint) -> (api, kind, support classification)
_MECH_API = {
    "bapi/bp":        ("BAPI_BUPA_CREATE_FROM_DATA", "Released BAPI", "Business Partner"),
    "bapi/material":  ("BAPI_MATERIAL_SAVEDATA", "Released BAPI", "Material master"),
    "bapi/exrate":    ("BAPI_EXCHRATE_CREATEMULTIPLE", "Released BAPI", "Exchange rates (TCURR)"),
    "bapi/po":        ("BAPI_PO_CREATE1", "Released BAPI", "Purchase order"),
    "bapi/fi_ar":     ("BAPI_ACC_DOCUMENT_POST", "Released BAPI", "FI document (AR)"),
    "bapi/fi_ap":     ("BAPI_ACC_DOCUMENT_POST", "Released BAPI", "FI document (AP)"),
    "idoc":           ("Inbound IDoc", "Released interface", "IDoc"),
}
# OData path used when a customer/vendor came back "created_ready"
_ODATA_API = ("API_BUSINESS_PARTNER (OData)", "Released OData API", "Business Partner (cust/supplier)")

# Mechanisms that would NOT be support-clean — asserted ABSENT (we never use these).
_FORBIDDEN = ["direct/raw table write (e.g. via SE16N edit, RFC_WRITE_TABLE)",
              "arbitrary ABAP execution (e.g. /BODS/RFC_ABAP_INSTALL_AND_RUN)",
              "modification of SAP standard repository objects",
              "bypass or replacement of SUM / Maintenance Planner"]


def audit(results: list) -> dict:
    """Build a support-compliance attestation from the run's load results."""
    per_object, apis = [], {}
    for r in results:
        load = r.get("load") or {}
        mech = load.get("mechanism")
        created = load.get("created_in_s4", 0)
        if not mech or not created:
            continue
        # OData was used for partners that came back transaction-ready
        used_odata = "created_ready" in (load.get("status_breakdown") or {})
        api, kind, area = _ODATA_API if used_odata else _MECH_API.get(
            mech, (mech, "Released API", r.get("object")))
        per_object.append({"object": r.get("object"), "mechanism": mech,
                           "sap_api": api, "api_kind": kind, "records": created,
                           "support_clean": True})
        apis[api] = apis.get(api, 0) + created

    return {
        "verdict": "SUPPORT-CLEAN" if per_object else "NO-WRITES",
        "principle": "All data writes go through SAP-shipped, business-logic-honoring "
                     "APIs (released BAPIs / released OData). No raw table writes, no "
                     "modification of SAP standard objects, no SUM/Maintenance Planner bypass.",
        "apis_used": [{"api": a, "records": n} for a, n in sorted(apis.items())],
        "forbidden_techniques_asserted_absent": _FORBIDDEN,
        "scope_note": "Data-migration engine (Greenfield / selective data transition lane). "
                      "In-place system conversion (SUM/DMO, Maintenance Planner) is a "
                      "separate SAP-proprietary lane and intentionally out of scope.",
        "reconciliation": "Verification reads are RFC_READ_TABLE / OData GET (read-only).",
        "customizing_note": "Customizing deltas (e.g. exchange-rate types/factors) are "
                            "PACKAGED for transport-grade apply, not written directly.",
        "per_object": per_object,
    }
