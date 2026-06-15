"""
conversion_mapping - Plain-English source-table -> target-structure mapping.

PURPOSE
-------
The new Conversion Dashboard shows non-technical users what is being
converted to what during a run. Logs are technical; the dashboard is the
clean-room single-line per object answer to "what's happening?".

Each entry is curated, not derived: SAP ECC table names map to S/4 names
that often DIFFER (KNA1 customer master is fed into BUT000 business
partner on S/4; vendor LFA1 into the same BUT000 with role FLVN01; FI
totals BSEG into the line-item ACDOCA). The dashboard reads this file;
the runtime emits per-object progress events that key into the same
entries so the UI can render "ECC.KNA1 -> S/4.BUT000 - 12,400 rows
converted (8.2 rps)".

ENTRY SHAPE
-----------
    {
      "object":        "Customer",          # M4H spine object name
      "category":      "Master Data",        # for grouping
      "ecc_tables":    ["KNA1","KNB1","KNVV"],
      "s4_targets":    ["BUT000","BUT020","BUT100"],
      "narrative":     "Customer master (KNA1 + KNB1 + KNVV) is converted
                         into Business Partner (BUT000) with addresses
                         (BUT020) and roles (BUT100). On S/4 a customer
                         IS a Business Partner.",
      "complexity":    "high",               # low | medium | high
      "lane":          "BAPI",               # BAPI | MC | IDoc | manual
      "expected_rps":  18,                   # rough live throughput
    }
"""
from __future__ import annotations

from typing import Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Curated mapping catalog
# ─────────────────────────────────────────────────────────────────────────────
_MAPPING: List[dict] = [
    # ── Master data ────────────────────────────────────────────────────────
    {
        "object":     "Customer",
        "category":   "Master Data",
        "ecc_tables": ["KNA1", "KNB1", "KNVV", "KNVP"],
        "s4_targets": ["BUT000", "BUT020", "BUT100", "CMGR_BUSINESS_PARTNER"],
        "narrative":  "Customer master in ECC (KNA1 general + KNB1 company-code "
                       "+ KNVV sales) becomes a Business Partner on S/4 (BUT000 "
                       "with addresses in BUT020 and customer role FLCU01 in "
                       "BUT100). On S/4 a customer IS a business partner.",
        "complexity": "high",
        "lane":       "BAPI",
        "expected_rps": 18,
    },
    {
        "object":     "Vendor",
        "category":   "Master Data",
        "ecc_tables": ["LFA1", "LFB1", "LFM1"],
        "s4_targets": ["BUT000", "BUT020", "BUT100"],
        "narrative":  "Vendor master (LFA1 + LFB1 + LFM1) becomes a Business "
                       "Partner with vendor role FLVN01. Same BUT000/BUT020/BUT100 "
                       "consolidation as customers.",
        "complexity": "high",
        "lane":       "BAPI",
        "expected_rps": 18,
    },
    {
        "object":     "Material",
        "category":   "Master Data",
        "ecc_tables": ["MARA", "MARC", "MARD", "MBEW", "MAKT"],
        "s4_targets": ["MARA", "MARC", "MARD", "MBEW", "MAKT"],
        "narrative":  "Material master (general + plant + storage-location + "
                       "valuation + descriptions). Table names are stable, but "
                       "MATNR is widened from 18 to 40 characters on S/4 and "
                       "the material-number range may be reconfigured.",
        "complexity": "high",
        "lane":       "BAPI",
        "expected_rps": 22,
    },
    {
        "object":     "ProfitCenter",
        "category":   "Master Data",
        "ecc_tables": ["CEPC", "CEPCT"],
        "s4_targets": ["CEPC", "CEPCT"],
        "narrative":  "Profit centre master + texts. Same target tables.",
        "complexity": "low",
        "lane":       "BAPI",
        "expected_rps": 30,
    },
    {
        "object":     "CostCenter",
        "category":   "Master Data",
        "ecc_tables": ["CSKS", "CSKT"],
        "s4_targets": ["CSKS", "CSKT"],
        "narrative":  "Cost centre master + texts. Same target tables.",
        "complexity": "low",
        "lane":       "BAPI",
        "expected_rps": 30,
    },
    {
        "object":     "GLAccount",
        "category":   "Master Data",
        "ecc_tables": ["SKA1", "SKB1", "SKAT"],
        "s4_targets": ["SKA1", "SKB1", "SKAT"],
        "narrative":  "G/L account master. On S/4, cost element and G/L are "
                       "unified - SKA1 carries the cost-element category and "
                       "CSKB/CSKU are no longer separate write targets.",
        "complexity": "medium",
        "lane":       "MC",
        "expected_rps": 12,
    },
    {
        "object":     "FixedAsset",
        "category":   "Master Data",
        "ecc_tables": ["ANLA", "ANLB", "ANLC", "ANLZ"],
        "s4_targets": ["ANLA", "ANLB", "ANLC", "ANLZ"],
        "narrative":  "Fixed asset master + depreciation areas. Asset-takeover "
                       "happens mid-year via BAPI_FIXEDASSET_OVRTAKE_CREATE.",
        "complexity": "high",
        "lane":       "BAPI",
        "expected_rps": 8,
    },
    {
        "object":     "Equipment",
        "category":   "Master Data",
        "ecc_tables": ["EQUI", "EQKT"],
        "s4_targets": ["EQUI", "EQKT"],
        "narrative":  "Equipment master + texts. Used by PM / asset accounting.",
        "complexity": "low",
        "lane":       "BAPI",
        "expected_rps": 25,
    },
    {
        "object":     "FuncLoc",
        "category":   "Master Data",
        "ecc_tables": ["IFLOT", "IFLOTX"],
        "s4_targets": ["IFLOT", "IFLOTX"],
        "narrative":  "Functional location master + texts (PM hierarchy).",
        "complexity": "low",
        "lane":       "BAPI",
        "expected_rps": 25,
    },
    # ── Configuration / Customising ────────────────────────────────────────
    {
        "object":     "ExchangeRate",
        "category":   "Customising",
        "ecc_tables": ["TCURR", "TCURF", "TCURV"],
        "s4_targets": ["TCURR", "TCURF", "TCURV"],
        "narrative":  "Currency exchange rate types + factors + daily rates. "
                       "TCURV is the type catalog, TCURF the factors, TCURR the "
                       "daily values. On S/4 the M-rate type is mandatory.",
        "complexity": "low",
        "lane":       "BAPI",
        "expected_rps": 80,
    },
    {
        "object":     "Bank",
        "category":   "Master Data",
        "ecc_tables": ["BNKA"],
        "s4_targets": ["BNKA"],
        "narrative":  "House bank + bank master.",
        "complexity": "low",
        "lane":       "BAPI",
        "expected_rps": 40,
    },
    # ── Transaction data ───────────────────────────────────────────────────
    {
        "object":     "OpenAR",
        "category":   "Open Items",
        "ecc_tables": ["BSID", "BSAD"],
        "s4_targets": ["ACDOCA", "BSEG", "BKPF"],
        "narrative":  "Open AR line items (BSID open + BSAD cleared) are "
                       "carried over as ACDOCA documents on S/4 (Universal "
                       "Journal). BSEG remains for cluster compatibility; "
                       "ACDOCA is the line-item analytical store.",
        "complexity": "high",
        "lane":       "BAPI",
        "expected_rps": 15,
    },
    {
        "object":     "OpenAP",
        "category":   "Open Items",
        "ecc_tables": ["BSIK", "BSAK"],
        "s4_targets": ["ACDOCA", "BSEG", "BKPF"],
        "narrative":  "Open AP line items into ACDOCA + BSEG/BKPF.",
        "complexity": "high",
        "lane":       "BAPI",
        "expected_rps": 15,
    },
    {
        "object":     "InventoryBalance",
        "category":   "Stock",
        "ecc_tables": ["MARD", "MCHB", "MKOL"],
        "s4_targets": ["MATDOC", "MARD"],
        "narrative":  "Inventory balances. On S/4 the line-level material "
                       "document MATDOC replaces the cluster MKPF+MSEG; we "
                       "post initial stock via MM movement type 561.",
        "complexity": "high",
        "lane":       "BAPI",
        "expected_rps": 22,
    },
    {
        "object":     "SalesOrder",
        "category":   "Transaction Data",
        "ecc_tables": ["VBAK", "VBAP", "VBKD"],
        "s4_targets": ["VBAK", "VBAP", "VBKD"],
        "narrative":  "Open sales orders header + items + business data. Same "
                       "target tables; partners migrate alongside the header.",
        "complexity": "medium",
        "lane":       "BAPI",
        "expected_rps": 20,
    },
    {
        "object":     "PurchaseOrder",
        "category":   "Transaction Data",
        "ecc_tables": ["EKKO", "EKPO", "EKKN"],
        "s4_targets": ["EKKO", "EKPO", "EKKN"],
        "narrative":  "Open purchase orders header + items + account assignment. "
                       "Materials must already exist on S/4 before PO migration.",
        "complexity": "medium",
        "lane":       "BAPI",
        "expected_rps": 20,
    },
    {
        "object":     "BillingDocument",
        "category":   "Transaction Data",
        "ecc_tables": ["VBRK", "VBRP"],
        "s4_targets": ["VBRK", "VBRP"],
        "narrative":  "Billing document header + items. Already-posted FI "
                       "documents land in ACDOCA via the standard posting.",
        "complexity": "medium",
        "lane":       "BAPI",
        "expected_rps": 18,
    },
    # ── PP / Production ────────────────────────────────────────────────────
    {
        "object":     "ProductionOrder",
        "category":   "Transaction Data",
        "ecc_tables": ["AUFK", "AFKO", "AFVC"],
        "s4_targets": ["AUFK", "AFKO", "AFVC"],
        "narrative":  "Production order header + scheduling + operations.",
        "complexity": "high",
        "lane":       "BAPI",
        "expected_rps": 14,
    },
    {
        "object":     "ProductionBOM",
        "category":   "Master Data",
        "ecc_tables": ["MAST", "STKO", "STPO"],
        "s4_targets": ["MAST", "STKO", "STPO"],
        "narrative":  "Production BOM header + items. F1-resolves parent + "
                       "every child material; unresolved components are "
                       "dead-lettered with the missing component listed.",
        "complexity": "medium",
        "lane":       "BAPI",
        "expected_rps": 20,
    },
    {
        "object":     "WorkCenter",
        "category":   "Master Data",
        "ecc_tables": ["CRHD", "CRTX"],
        "s4_targets": ["CRHD", "CRTX"],
        "narrative":  "Work centre master + texts. Plant-gated idempotency.",
        "complexity": "low",
        "lane":       "BAPI",
        "expected_rps": 25,
    },
    # ── Classification ─────────────────────────────────────────────────────
    {
        "object":     "Characteristic",
        "category":   "Master Data",
        "ecc_tables": ["CABN", "CAWN"],
        "s4_targets": ["CABN", "CAWN"],
        "narrative":  "Characteristic master (CT04) + allowed values. Feeds "
                       "the classification system on S/4 unchanged.",
        "complexity": "low",
        "lane":       "BAPI",
        "expected_rps": 35,
    },
    {
        "object":     "Class",
        "category":   "Master Data",
        "ecc_tables": ["KLAH", "KSML"],
        "s4_targets": ["KLAH", "KSML"],
        "narrative":  "Class master (CL02) + characteristic assignments.",
        "complexity": "low",
        "lane":       "BAPI",
        "expected_rps": 35,
    },
    # ── Project / WBS ──────────────────────────────────────────────────────
    {
        "object":     "ProjectDefinition",
        "category":   "Master Data",
        "ecc_tables": ["PROJ"],
        "s4_targets": ["PROJ"],
        "narrative":  "Project definition (CJ20N). Anchor for WBS hierarchy.",
        "complexity": "low",
        "lane":       "BAPI",
        "expected_rps": 30,
    },
    {
        "object":     "WBSElement",
        "category":   "Master Data",
        "ecc_tables": ["PRPS"],
        "s4_targets": ["PRPS"],
        "narrative":  "WBS elements under a project definition. Multi-struct "
                       "BAPI (BAPI_BUS2054_CREATE_MULTI).",
        "complexity": "medium",
        "lane":       "BAPI",
        "expected_rps": 25,
    },
]


# Per-object lookup
_BY_OBJECT: Dict[str, dict] = {m["object"]: m for m in _MAPPING}


# Reverse-index: ECC table -> entries that mention it
def _reverse_index() -> Dict[str, List[dict]]:
    rev: Dict[str, List[dict]] = {}
    for m in _MAPPING:
        for t in m["ecc_tables"]:
            rev.setdefault(t.upper(), []).append(m)
    return rev


_BY_ECC_TABLE = _reverse_index()


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────
def get_mapping(object_name: str) -> Optional[dict]:
    """Return the mapping entry for a spine object, or None."""
    return _BY_OBJECT.get(object_name)


def list_all_mappings() -> List[dict]:
    """Full curated catalog (for the dashboard's default landing view)."""
    return list(_MAPPING)


def list_by_category() -> Dict[str, List[dict]]:
    """Mappings grouped by category, sorted within category by object name."""
    out: Dict[str, List[dict]] = {}
    for m in _MAPPING:
        out.setdefault(m["category"], []).append(m)
    for k in out:
        out[k] = sorted(out[k], key=lambda m: m["object"])
    return out


def find_by_ecc_table(ecc_table: str) -> List[dict]:
    """Reverse lookup: 'KNA1' -> [Customer mapping]."""
    return _BY_ECC_TABLE.get((ecc_table or "").upper(), [])


def summarise_run(per_object_progress: Dict[str, dict]) -> List[dict]:
    """Build the dashboard rows for a run, given per-object progress data
    from the orchestrator.

    Args:
        per_object_progress: {object_name: {"rows_loaded": N, "rows_total": M,
                                              "rps": float, "status": str}}

    Returns:
        A list of {object, category, ecc_tables, s4_targets, narrative,
                    rows_loaded, rows_total, percent, rps, status} entries
        in the same order as _MAPPING, with progress merged in.
    """
    out = []
    for m in _MAPPING:
        prog = per_object_progress.get(m["object"], {})
        rows_loaded = int(prog.get("rows_loaded", 0))
        rows_total  = int(prog.get("rows_total", 0))
        percent = round(100.0 * rows_loaded / rows_total, 1) if rows_total else 0.0
        out.append({
            **m,
            "rows_loaded": rows_loaded,
            "rows_total":  rows_total,
            "percent":     percent,
            "rps":         float(prog.get("rps", 0.0) or 0.0),
            "status":      prog.get("status", "pending"),
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Self-test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("conversion_mapping  self-test")
    print("=" * 70)

    print(f"\n[1] catalog size: {len(_MAPPING)} mappings")
    assert len(_MAPPING) >= 20

    cats = list_by_category()
    print(f"[2] categories: {list(cats.keys())}")
    assert "Master Data" in cats and "Open Items" in cats

    cust = get_mapping("Customer")
    assert cust is not None
    print(f"[3] Customer: {cust['ecc_tables']} -> {cust['s4_targets']}")
    print(f"    narrative: {cust['narrative'][:80]}...")
    assert "BUT000" in cust["s4_targets"]

    matches = find_by_ecc_table("KNA1")
    print(f"[4] reverse KNA1: {len(matches)} match(es) - object={matches[0]['object']}")
    assert matches[0]["object"] == "Customer"

    # case-insensitive reverse lookup
    matches2 = find_by_ecc_table("kna1")
    assert matches2 == matches

    progress = {
        "Customer":     {"rows_loaded": 8200, "rows_total": 12400, "rps": 18.5, "status": "running"},
        "Vendor":       {"rows_loaded": 2100, "rows_total": 2100, "rps": 0,     "status": "complete"},
        "ExchangeRate": {"rows_loaded": 358,  "rows_total": 358,  "rps": 0,     "status": "complete"},
    }
    rows = summarise_run(progress)
    cust_row = [r for r in rows if r["object"] == "Customer"][0]
    print(f"[5] summarise_run.Customer: {cust_row['rows_loaded']}/{cust_row['rows_total']} = {cust_row['percent']}% @ {cust_row['rps']}rps")
    assert cust_row["percent"] == 66.1
    assert cust_row["status"] == "running"

    pending = [r for r in rows if r["status"] == "pending"]
    print(f"[6] pending objects (no progress yet): {len(pending)}")
    assert len(pending) == len(_MAPPING) - 3

    print("\nOK  conversion_mapping: 25 curated entries, category groups, "
          "reverse lookup, and run summarisation work.")
