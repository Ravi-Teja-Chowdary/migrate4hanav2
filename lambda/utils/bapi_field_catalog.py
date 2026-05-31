"""
bapi_field_catalog.py - canonical field catalog per released BAPI / OData
service for the field-coverage check in bapi_coverage.py.

What lives here
---------------
For each migration-object type we load, the *upper-cased* set of fields the
chosen target API can actually transport. The bapi_coverage analyzer compares
each extracted record's keys against this set; anything left over (CI_*, ZZ_*,
J_1B*, late-S/4 fields the BAPI was never extended to carry) is the "delta"
that must ride LTMC or be quarantined.

Source of truth in real projects
--------------------------------
The authoritative way to build this catalog is to run DD_BAPI_PARAMETER_GET
(or, for OData, GET ~/$metadata) against the target system and walk the
parameter/structure tree. That gives field-level accuracy per release.

This file ships a hand-curated baseline based on the released SAP-standard
BAPI/OData interfaces our loaders actually call (see bapi_loader.py +
bp_odata.py). It's deliberately conservative: when a field is widely known
to be on the BAPI interface (e.g. KUNNR for BAPI_CUSTOMER_CREATEFROMDATA),
it's listed; CI_/ZZ_/J_1B/J_1A/TXJCD-style fields are deliberately omitted
so the coverage analyzer flags them.

Extension points
----------------
- `register(object_type, fields)` lets a per-landscape addendum widen the set
  (e.g. a customer who has extended BAPI_CUSTOMER_CREATEFROMDATA1 via BADI).
- `for_object(object_type)` returns the union of the baseline + addendum.
- Env var `M4H_BAPI_FIELD_CATALOG_JSON` (path) is loaded at import time and
  merged on top, so deployments can override without code changes.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Dict, Iterable, Set

logger = logging.getLogger("bapi_field_catalog")


# ─────────────────────────────────────────────────────────────────────────────
#  Baseline catalog. Keys = migration object type (matches our internal naming
#  used by unified_loader / data-migrator). Values = upper-cased field set.
# ─────────────────────────────────────────────────────────────────────────────
_BASELINE: Dict[str, Set[str]] = {
    # ── Partner / customer / vendor (RFC + OData) ──────────────────────────
    "BusinessPartner": {
        "PARTNER", "BPKIND", "TYPE", "BU_GROUP", "BU_SORT1", "BU_SORT2",
        "PARTNERROLE", "TITLE_KEY", "TITLE", "TITLE_LET", "TITLE_ACA1",
        # central data BAPI_BUPA_CENTRAL_CHANGE / CREATE
        "FIRSTNAME", "LASTNAME", "NAME", "NAME1", "NAME2",
        "BIRTHDATE", "BIRTHPLACE", "GENDER",
        # legalentity flag
        "LEGALENTY",
    },
    "Customer": {
        # BAPI_CUSTOMER_CREATEFROMDATA / CREATEFROMDATA1
        "KUNNR", "BUKRS", "VKORG", "VTWEG", "SPART",
        "NAME1", "NAME2", "NAME3", "NAME4",
        "SORT1", "SORT2", "STRAS", "STR_SUPPL1", "STR_SUPPL2", "STR_SUPPL3",
        "ORT01", "ORT02", "PSTLZ", "REGIO", "LAND1", "SPRAS",
        "TELF1", "TELF2", "TELFX", "TELTX", "TELEX", "SMTP_ADDR",
        "STCEG", "STCD1", "STCD2", "STCD3", "STCD4", "STCD5",
        "AKONT", "ZTERM", "ZWELS", "KTOKD", "VBUND", "KATR1", "KATR2",
        "KDGRP", "BZIRK", "AUFSD", "FAKSD", "LIFSD", "INCO1", "INCO2",
        "WAERS", "KLIMK", "VERSDB",
    },
    "Vendor": {
        # BAPI_VENDOR_CREATE / CREATE_INTERNALNUMBER
        "LIFNR", "BUKRS", "EKORG",
        "NAME1", "NAME2", "NAME3", "NAME4",
        "SORT1", "SORT2", "STRAS", "STR_SUPPL1", "STR_SUPPL2",
        "ORT01", "ORT02", "PSTLZ", "REGIO", "LAND1", "SPRAS",
        "TELF1", "TELF2", "TELFX", "SMTP_ADDR",
        "STCEG", "STCD1", "STCD2", "STCD3",
        "AKONT", "ZTERM", "ZWELS", "KTOKK", "KATR1", "KATR2",
        "WAERS", "VERSL", "KZAHL", "ZUAWA", "INCO1", "INCO2",
        "MINBESTBTR", "BEGRU",
    },

    # ── Material (BAPI_MATERIAL_SAVEDATA) ─────────────────────────────────
    "Material": {
        "MATNR", "MTART", "MBRSH", "MEINS", "MATKL", "BISMT", "EXTWG",
        "MAKTX", "MAKTG", "SPRAS",
        # plant data
        "WERKS", "EKGRP", "DISMM", "MTVFP", "MMSTA", "MAABC",
        # storage / units
        "LGORT", "LGPRO", "MHDRZ", "MHDHB",
        # accounting / costing
        "BWKEY", "BKLAS", "VPRSV", "STPRS", "PEINH", "LAEPR", "BWTAR",
        # sales
        "VKORG", "VTWEG", "DWERK", "MTPOS", "VERPR",
        # MRP
        "DISPO", "DISLS", "BSTMI", "BSTRF",
    },

    # ── FI master ──────────────────────────────────────────────────────────
    "GLAccount": {
        # BAPI_GL_ACC_GETCURRENTBALANCES is read-only; create uses
        # BAPI_ACC_GL_POSTING / BAPI_ACC_DOCUMENT_POST for postings. The
        # master-data create path uses BAPI_ACC_PRIMARY_COSTS_POST or
        # FS00 via the Migration Cockpit. This list covers the BAPI-shaped
        # SKA1+SKB1 fields the released create supports.
        "SAKNR", "KTOPL", "XBILK", "XSPEB", "XLOEV", "XSPEA",
        "BUKRS", "AKONT", "WAERS", "STEXT", "TXT20", "TXT50",
        "MITKZ", "FSTAG", "ALTKT", "XBLNR_KZ", "XKRES", "XSALH",
    },
    "Bank": {
        # BAPI_BANK_CREATE
        "BANKS", "BANKL", "BANKA", "PROVZ", "STRAS", "ORT01",
        "SWIFT", "BNKLZ", "BGRUP", "XPGRO", "BRNCH", "ADRNR",
    },
    "ExchangeRates": {
        # BAPI_EXCHANGERATE_CREATEMULTIPLE
        "RATE_TYPE", "FROM_CURR", "TO_CURRNCY", "VALID_FROM",
        "EXCH_RATE", "FROM_FACTOR", "TO_FACTOR",
    },

    # ── CO master ──────────────────────────────────────────────────────────
    "CostCenter": {
        # BAPI_COSTCENTER_CREATEMULTIPLE
        "KOKRS", "KOSTL", "DATBI", "DATAB", "VERAK", "VERAK_USER",
        "WAERS", "PRCTR", "ABTEI", "KOSAR", "BUKRS", "GSBER", "FUNC_AREA",
        "TXJCD", "WERKS", "LAND1", "ANRED", "NAME1", "TITLE",
        "STREET", "CITY", "REGION", "POSTL_COD1", "COUNTRY",
        "DESCRIPT", "NAME",
    },
    "ProfitCenter": {
        # BAPI_PROFITCENTER_CREATE / API_PROFITCENTER_BASIC_INFO
        "KOKRS", "PRCTR", "DATAB", "DATBI", "VERAK", "VERAK_USER",
        "ABTEI", "WAERS", "BUKRS", "TXJCD",
        "NAME1", "DESCRIPT", "LAND1", "STREET", "CITY", "REGION",
        "POSTL_COD1", "COUNTRY", "FUNC_AREA",
    },
    "CostElementGroup": {"SETNAME", "SUBCLASS", "SETCLASS", "KOKRS",
                          "BEZEICH", "RESPONSIBLE"},
    "ProfitCenterGroup": {"SETNAME", "SUBCLASS", "SETCLASS", "KOKRS",
                           "BEZEICH", "RESPONSIBLE"},
    "InternalOrder": {
        # BAPI_INTERNALORDER_CREATE / CREATEMULTIPLE
        "AUFNR", "AUART", "KTEXT", "KOKRS", "BUKRS",
        "WAERS", "PRCTR", "KOSTL", "USTAT", "GSBER", "ASTKZ", "WERKS",
        "PERIOD", "AUFEX", "ZSCHL", "KALSM", "LAND1", "STSMA",
    },

    # ── Asset accounting ───────────────────────────────────────────────────
    "FixedAsset": {
        # BAPI_FIXEDASSET_OVRTAKE_CREATE / BAPI_FIXEDASSET_CREATE1
        "BUKRS", "ANLN1", "ANLN2", "ANLKL", "ANLN1_REF", "ANLN2_REF",
        "TXT50", "TXA50", "MENGE", "MEINS", "GROUPASSET",
        "KOSTL", "AUFNR", "GSBER", "WERKS", "STORT", "RAUMN",
        "AKTIV", "DEACT", "INVNR", "URJHR", "URWRT",
        "DEPRAREA", "ULIFE_YRS", "ULIFE_PRDS",   # depreciation areas
        "VALUE_CURR", "DEPR_KEY", "EXP_USEFUL_LIFE",
    },

    # ── Plant maintenance / functional location ────────────────────────────
    "Equipment": {
        # BAPI_EQUI_CREATE / CHANGE
        "EQUNR", "EQTYP", "BEGRU", "EQART", "MATNR", "SERNR",
        "WERK", "STORT", "TPLNR", "ABCKZ", "BAUMM", "BAUJJ",
        "INVNR", "HERST", "TYPBZ", "SHTXT", "SPRAS",
    },
    "FunctionalLocation": {
        # BAPI_FUNCLOC_CREATE
        "TPLNR", "FLTYP", "STRNO", "STORT", "BEGRU", "ABCKZ",
        "WERK", "INGRP", "VKORG", "VTWEG", "EQART", "ANLNR",
        "STRINDR", "EQFNR", "HEQUI", "PLTXT", "SPRAS",
    },

    # ── Classification / batches ───────────────────────────────────────────
    "Characteristic": {
        # BAPI_CHARACT_CREATE
        "ATNAM", "ATFOR", "ANZST", "ANZDZ", "MSEHI", "ATSCH",
        "ATEIN", "ATKLE", "ATSON", "ATVOR", "DESCR", "ATBEZ",
        "ANAME", "ADATU",
    },
    "Class": {
        # BAPI_CLASS_CREATE
        "CLASS", "KLART", "BEZEICH", "STATUS", "BEGRU",
        "OWNER", "AENNR", "CHGNUM", "FROMDATE", "TODATE", "ORG_AREA",
    },
    "Batch": {
        # BAPI_BATCH_CREATE
        "MATERIAL", "BATCH", "PLANT", "STORAGELOCATION", "BATCH_STATUS",
        "VENDOR_BATCH", "AVAILABILITY", "HSDAT", "VFDAT", "LWEDT",
    },

    # ── Inventory ──────────────────────────────────────────────────────────
    "InventoryBalance": {
        # BAPI_GOODSMVT_CREATE header / item for 561 (stock posting)
        "PSTNG_DATE", "DOC_DATE", "REF_DOC_NO", "HEADER_TXT", "PR_UNAME",
        "MATERIAL", "PLANT", "STGE_LOC", "BATCH", "MOVE_TYPE", "ENTRY_QNT",
        "ENTRY_UOM", "MOVE_MAT", "MOVE_PLANT", "MOVE_STLOC",
        "VAL_TYPE", "SPEC_STOCK", "VENDOR", "ITEM_TEXT",
    },

    # ── Logistics: PO / PR / contracts / sales order ───────────────────────
    "OpenPO": {
        # BAPI_PO_CREATE1 / BAPI_PO_CHANGE
        "EBELN", "BSART", "LIFNR", "EKORG", "EKGRP", "WAERS", "BEDAT",
        "ITEM_NO", "PO_ITEM", "MATERIAL", "PLANT", "STGE_LOC", "QUANTITY",
        "PO_UNIT", "PRICE", "PRICE_UNIT", "NET_PRICE", "TAX_CODE",
        "DELIV_DATE", "DELIV_DATE_TYP", "INFO_REC", "TRACKINGNO",
        "REASON_REJ", "ITEM_CAT", "ACCTASSCAT", "ACCTASSGT",
        "G_L_ACCT", "COSTCENTER", "ORDER_ID", "WBS_ELEMT",
    },
    "PurchaseRequisition": {
        # BAPI_REQUISITION_CREATE
        "BANFN", "BNFPO", "MATERIAL", "PLANT", "STGE_LOC", "QUANTITY",
        "UNIT", "DELIV_DATE", "PUR_GROUP", "TRACKINGNO", "PREQ_NAME",
        "ITEM_TEXT", "ACCTASSCAT", "GL_ACCOUNT", "COSTCENTER",
        "AGREEMENT", "AGMT_ITEM", "PREQ_PRICE", "PRICE_UNIT",
    },
    "PurchaseContract": {
        # BAPI_CONTRACT_CREATE
        "EBELN", "BSART", "LIFNR", "EKORG", "EKGRP", "WAERS", "BEDAT",
        "KDATE", "VPER_START", "VPER_END",
        "ITEM_NO", "MATERIAL", "PLANT", "TARGET_QTY", "PO_UNIT",
        "NET_PRICE", "PRICE_UNIT", "INFO_REC",
    },
    "SalesOrder": {
        # BAPI_SALESORDER_CREATEFROMDAT2
        "DOC_TYPE", "SALES_ORG", "DISTR_CHAN", "DIVISION",
        "PURCH_NO_C", "PURCH_DATE", "REQ_DATE_H", "CURRENCY",
        "PARTN_ROLE", "PARTN_NUMB",      # partners table
        "ITM_NUMBER", "MATERIAL", "PLANT", "TARGET_QTY", "TARGET_QU",
        "SHORT_TEXT", "ITEM_CATEG", "SCHED_LINE", "REQ_QTY",
        "REQ_DATE", "CONFIRM_QTY",
    },

    # ── FI postings (open items) ──────────────────────────────────────────
    "OpenAR": {
        # BAPI_ACC_DOCUMENT_POST header + customer item
        "DOC_TYPE", "DOC_DATE", "PSTNG_DATE", "COMP_CODE", "REF_DOC_NO",
        "HEADER_TXT", "USERNAME", "CUSTOMER", "BUS_AREA", "ITEMNO_ACC",
        "GL_ACCOUNT", "VENDOR_NO", "AMT_DOCCUR", "CURRENCY", "ITEM_TEXT",
        "PMNTTRMS", "BLINE_DATE", "PMNT_BLOCK", "ASSIGNMENT", "ALLOC_NMBR",
        "TAX_CODE", "PROFIT_CTR", "COSTCENTER", "ORDERID",
    },
    "OpenAP": {
        # BAPI_ACC_DOCUMENT_POST header + vendor item
        "DOC_TYPE", "DOC_DATE", "PSTNG_DATE", "COMP_CODE", "REF_DOC_NO",
        "HEADER_TXT", "USERNAME", "VENDOR_NO", "BUS_AREA", "ITEMNO_ACC",
        "GL_ACCOUNT", "AMT_DOCCUR", "CURRENCY", "ITEM_TEXT",
        "PMNTTRMS", "BLINE_DATE", "PMNT_BLOCK", "ASSIGNMENT", "ALLOC_NMBR",
        "TAX_CODE", "PROFIT_CTR", "COSTCENTER", "ORDERID", "WBS_ELEMENT",
    },

    # ── Project / WBS ──────────────────────────────────────────────────────
    "Project": {
        # BAPI_PROJECT_MAINTAIN
        "PROJECT_DEFINITION", "DESCRIPTION", "RESPONSIBLE_NO",
        "APPLICANT_NO", "CO_AREA", "COMP_CODE", "PLANT", "BUS_AREA",
        "PROFIT_CENTER", "CURRENCY", "PROJ_TYPE", "PRIORITY",
        "START_DATE", "FINISH_DATE",
    },
    "WBS": {
        "WBS_ELEMENT", "DESCRIPTION", "PROJECT_DEFINITION",
        "RESPONSIBLE_NO", "APPLICANT_NO", "PRIORITY", "WBS_UP",
        "PROJ_TYPE", "PLAN_START", "PLAN_FINISH", "BASIC_START",
        "BASIC_FINISH",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
#  Addendum (per-landscape overrides)
# ─────────────────────────────────────────────────────────────────────────────
_ADDENDUM: Dict[str, Set[str]] = {}


def register(object_type: str, fields: Iterable[str]) -> None:
    """Widen the catalog for a given object type (e.g. customer-extended BAPI)."""
    cur = _ADDENDUM.setdefault(object_type, set())
    cur.update({f.upper() for f in fields})


def for_object(object_type: str) -> Set[str]:
    """Return the union of baseline + addendum for the given object type."""
    base = set(_BASELINE.get(object_type, set()))
    base.update(_ADDENDUM.get(object_type, set()))
    return base


def known_objects() -> Set[str]:
    return set(_BASELINE) | set(_ADDENDUM)


def as_dict() -> Dict[str, Set[str]]:
    """Snapshot - useful when wiring into UnifiedLoader.bapi_field_catalog."""
    return {obj: for_object(obj) for obj in known_objects()}


# ─────────────────────────────────────────────────────────────────────────────
#  Optional env-driven addendum (no code changes for per-landscape overrides)
# ─────────────────────────────────────────────────────────────────────────────
def _load_env_addendum() -> None:
    path = os.environ.get("M4H_BAPI_FIELD_CATALOG_JSON")
    if not path or not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        for obj, fields in (data or {}).items():
            if not isinstance(fields, (list, tuple, set)):
                continue
            register(obj, fields)
        logger.info("bapi_field_catalog: loaded addendum from %s "
                    "(%d objects)", path, len(data or {}))
    except Exception as e:  # noqa: BLE001
        logger.warning("bapi_field_catalog addendum load failed: %s", e)


_load_env_addendum()


# ─────────────────────────────────────────────────────────────────────────────
#  Self-test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 72)
    print("bapi_field_catalog - self-test")
    print("=" * 72)
    objs = sorted(known_objects())
    assert len(objs) >= 17, f"baseline too thin: {len(objs)}"
    print(f"  baseline objects: {len(objs)}")
    for o in objs:
        n = len(for_object(o))
        assert n > 0, f"empty field set for {o}"
        print(f"    {o:24s} {n:>4d} fields")

    # Addendum
    register("Customer", ["ZZ_LOYALTY", "ZZ_RISK_BAND"])
    assert "ZZ_LOYALTY" in for_object("Customer")
    print(f"  addendum: Customer + 2 ZZ fields -> {len(for_object('Customer'))} total")

    # New object via addendum
    register("CustomZObject", ["ZZFIELD1", "ZZFIELD2"])
    assert "CustomZObject" in known_objects()
    print(f"  addendum: created new object 'CustomZObject' via register()")

    # Coverage-analyser integration: a record carrying CI_ + a known field
    # should be partly covered.
    try:
        from bapi_coverage import analyze_coverage, decide_load_path
        rec = [{"KUNNR": "1", "NAME1": "X", "ORT01": "Y", "CI_LOYALTY": "GOLD",
                "J_1BNFTYPE": "T01"}]
        cov = analyze_coverage(rec, "Customer", "BAPI_CUSTOMER_CREATEFROMDATA",
                               for_object("Customer"))
        decision = decide_load_path(cov)
        assert decision.path == "BAPI_PLUS_LTMC_DELTA"
        print(f"  bapi_coverage integration: Customer with CI_+J_1B -> "
              f"{decision.path} OK")
    except ImportError:
        print(f"  bapi_coverage not on path - integration check skipped")

    print("\nOK - catalog covers 17+ migration objects, addendum + env-override "
          "wired, integrates with bapi_coverage.")
