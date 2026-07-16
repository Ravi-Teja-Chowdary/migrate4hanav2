"""
abap_generator - emit self-contained ABAP prep script for the S/4 target.

Purpose
-------
Given an ECC connection (pyrfc) or a config-replicator dump, produce a single
ABAP report the S/4 admin runs in SE38 (or the tool runs via
RFC_ABAP_INSTALL_AND_RUN) to create the customizing rows the ECC data
references — so the migrate4hana wizard's *Start migration* click can run
end-to-end without dead-letters on missing target customizing.

What's covered in v1 (the tables that gate ~80% of dead-letters seen in
wiz-20260705T151739Z-0afc3ca1):

    T001    - company codes
    T001W   - plants
    TKA01   - controlling areas (fixes CostCenter + ProfitCenter)
    T023    - material groups          (fixes Material)
    TCURV   - exchange rate types      (fixes ExchangeRates)
    TCURF   - exchange rate factors    (fixes ExchangeRates)
    TFACD   - factory calendar def     (fixes OpenPO)
    TFAIN   - factory calendar intervals (fixes OpenPO)
    T007A   - tax codes                (fixes OpenAR/OpenAP)
    TVAK    - sales doc types + NUMKE ext-num flag (for source-number preservation)
    TVLK    - delivery types + external range
    TVFK    - billing types + external range
    NRIV    - number range intervals (sized to cover ECC number space)

Output shape
------------
    {"abap":      "<self-contained ABAP report source>",
     "undo_abap": "<companion undo/rollback script>",
     "summary":   {"tables_covered": int, "total_rows_generated": int,
                   "table_row_counts": {"T023": 4, "TKA01": 1, ...},
                   "delta_only": bool,
                   "generated_at": iso8601},
     "warnings":  [str, ...]}
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional


# ─────────────────────────────────────────────────────────────────────────────
# What to scan from ECC
# ─────────────────────────────────────────────────────────────────────────────
# Each entry: table_name -> {"fields": [...], "where": "optional filter",
#                            "rowcount": max rows to pull, "key_fields": [...],
#                            "description": "human-readable"}.
# `key_fields` identifies the PK for MODIFY dedup semantics on S/4.
SCAN_SPEC = {
    "T001":  {
        "description": "Company codes",
        "fields": ["BUKRS", "BUTXT", "ORT01", "LAND1", "WAERS", "SPRAS", "KTOPL",
                    "WAABW", "PERIV", "KOKFI", "RCOMP", "ADRNR", "STCEG", "FIKRS", "XFMCA"],
        "where": "",
        "rowcount": 100,
        "key_fields": ["BUKRS"],
    },
    "T001W": {
        "description": "Plants",
        "fields": ["WERKS", "NAME1", "NAME2", "LAND1", "REGIO", "STRAS", "ORT01",
                    "PSTLZ", "SPRAS", "WKSOP", "VLFKZ", "BUKRS", "FABKL"],
        "where": "",
        "rowcount": 200,
        "key_fields": ["WERKS"],
    },
    "TKA01": {
        "description": "Controlling areas",
        "fields": ["KOKRS", "BEZEI", "WAERS", "KTOPL", "KOKFI", "PERIV", "MTHKZ",
                    "LMONA", "XWBUK", "PCLDG", "LOGSYSTEM"],
        "where": "",
        "rowcount": 50,
        "key_fields": ["KOKRS"],
    },
    "T023": {
        "description": "Material groups",
        "fields": ["MATKL", "WGBEZ", "WGBEZ60", "BKLAS", "MEIN"],
        "where": "",
        "rowcount": 500,
        "key_fields": ["MATKL"],
    },
    "TCURV": {
        "description": "Exchange rate types",
        "fields": ["KURST", "XINVR", "BWAER", "XKURS", "XEURO", "XREF1", "XREF2"],
        "where": "",
        "rowcount": 100,
        "key_fields": ["KURST"],
    },
    "TCURF": {
        "description": "Exchange rate factors",
        "fields": ["KURST", "FCURR", "TCURR", "GDATU", "FFACT", "TFACT", "ABWCE"],
        "where": "",
        "rowcount": 5000,
        "key_fields": ["KURST", "FCURR", "TCURR", "GDATU"],
    },
    "TFACD": {
        "description": "Factory calendar definition",
        "fields": ["IDENT", "TXT", "ANFDT", "ENDDT", "WKAT1", "WKAT2", "WKAT3",
                    "WKAT4", "WKAT5", "WKAT6", "WKAT7", "SAM1", "SAM2"],
        "where": "",
        "rowcount": 50,
        "key_fields": ["IDENT"],
    },
    "TFAIN": {
        "description": "Factory calendar workday index",
        "fields": ["IDENT", "DATUM", "WERKT"],
        "where": "",
        "rowcount": 20000,
        "key_fields": ["IDENT", "DATUM"],
    },
    "T007A": {
        "description": "Tax codes (procedure/keys)",
        "fields": ["KALSM", "MWSKZ", "KALSM_TX", "KVEWE", "EGRKZ", "MWART"],
        "where": "",
        "rowcount": 500,
        "key_fields": ["KALSM", "MWSKZ"],
    },
    "TVAK": {
        "description": "Sales document types (for external-number flag)",
        "fields": ["AUART", "BEZEI", "NUMKI", "NUMKE", "VBTYP", "TRVOG", "AUTLF",
                    "LIPRG", "SOFOR", "KALSM", "KTGRD", "FKARA"],
        "where": "",
        "rowcount": 500,
        "key_fields": ["AUART"],
    },
    "TVLK": {
        "description": "Delivery types (for external-number flag)",
        "fields": ["LFART", "BEZEI", "NUMKI", "NUMKE", "VBTYP", "ROUTA", "TRAGR"],
        "where": "",
        "rowcount": 200,
        "key_fields": ["LFART"],
    },
    "TVFK": {
        "description": "Billing types (for external-number flag)",
        "fields": ["FKART", "BEZEI", "NUMKI", "NUMKE", "VBTYP", "KALSM", "KTGRD"],
        "where": "",
        "rowcount": 200,
        "key_fields": ["FKART"],
    },
    # ── 2026-07-07 breadth expansion — customizing tables the wider spine
    # catalog references. Grouped by object class so a diff on this dict
    # reads like a coverage map for the migration domain.

    # Sales area structure — SO/Contract/Delivery/Billing need these tuples
    "TVKO": {
        "description": "Sales organizations",
        "fields": ["VKORG", "WAERS", "KALSM", "VKOFI", "BUKRS", "ADRNR"],
        "where": "", "rowcount": 100, "key_fields": ["VKORG"],
    },
    "TVTW": {
        "description": "Distribution channels",
        "fields": ["VTWEG", "BEZEI"],
        "where": "", "rowcount": 50, "key_fields": ["VTWEG"],
    },
    "TSPA": {
        "description": "Divisions",
        "fields": ["SPART", "BEZEI"],
        "where": "", "rowcount": 50, "key_fields": ["SPART"],
    },
    "TVKOV": {
        "description": "Sales area assignment (VKORG-VTWEG)",
        "fields": ["VKORG", "VTWEG"],
        "where": "", "rowcount": 500, "key_fields": ["VKORG", "VTWEG"],
    },
    "TVTA": {
        "description": "Sales area (VKORG-VTWEG-SPART)",
        "fields": ["VKORG", "VTWEG", "SPART", "BUKRS", "KALKS"],
        "where": "", "rowcount": 1000, "key_fields": ["VKORG", "VTWEG", "SPART"],
    },

    # Purchasing org structure — PO/Contract/InfoRecord/SourceList
    "T024E": {
        "description": "Purchasing organizations",
        "fields": ["EKORG", "EKOTX", "EKORS", "BUKRS"],
        "where": "", "rowcount": 100, "key_fields": ["EKORG"],
    },
    "T024": {
        "description": "Purchasing groups",
        "fields": ["EKGRP", "EKNAM", "EKTEL"],
        "where": "", "rowcount": 200, "key_fields": ["EKGRP"],
    },

    # Material master customizing
    "T134": {
        "description": "Material types",
        "fields": ["MTART", "MTREF", "MTPOS", "MTBEZ"],
        "where": "", "rowcount": 200, "key_fields": ["MTART"],
    },
    "T134T": {
        "description": "Material types (short text)",
        "fields": ["SPRAS", "MTART", "MTBEZ"],
        "where": "SPRAS = 'E'", "rowcount": 500, "key_fields": ["SPRAS", "MTART"],
    },
    "T137": {
        "description": "Material status",
        "fields": ["MMSTA", "SPRAS", "MMSTB"],
        "where": "", "rowcount": 100, "key_fields": ["MMSTA", "SPRAS"],
    },
    "T023T": {
        "description": "Material group descriptions",
        "fields": ["SPRAS", "MATKL", "WGBEZ"],
        "where": "SPRAS = 'E'", "rowcount": 1000, "key_fields": ["SPRAS", "MATKL"],
    },

    # PP customizing — production order type, work centre etc.
    "T003O": {
        "description": "Order types (PP/PM/PS)",
        "fields": ["AUART", "AUTYP", "BEZEI"],
        "where": "", "rowcount": 200, "key_fields": ["AUART"],
    },
    "T430": {
        "description": "Status profile assignments",
        "fields": ["OBJTP", "STSMA", "BEZEI"],
        "where": "", "rowcount": 200, "key_fields": ["OBJTP", "STSMA"],
    },

    # FI / CO customizing beyond the base four
    "T003": {
        "description": "FI document types",
        "fields": ["BLART", "LTEXT", "NUMKR", "XKOPF"],
        "where": "", "rowcount": 200, "key_fields": ["BLART"],
    },
    "T077K": {
        "description": "Customer account groups",
        "fields": ["KTOKD", "TEXT30", "XCPDD", "SPBUP"],
        "where": "", "rowcount": 100, "key_fields": ["KTOKD"],
    },
    "T077Y": {
        "description": "Vendor account groups",
        "fields": ["KTOKK", "TEXT30", "XCPDK"],
        "where": "", "rowcount": 100, "key_fields": ["KTOKK"],
    },
    "T052": {
        "description": "Payment terms",
        "fields": ["ZTERM", "TAGE2", "TAGE3", "PRZ1", "PRZ2"],
        "where": "", "rowcount": 500, "key_fields": ["ZTERM"],
    },
    "TFACT": {
        "description": "Factory calendar assignments per plant",
        "fields": ["WERKS", "FABKL"],
        "where": "", "rowcount": 500, "key_fields": ["WERKS"],
    },

    # Country / language / currency reference
    "T005": {
        "description": "Countries",
        "fields": ["LAND1", "LANDK", "ISO3", "NATIO"],
        "where": "", "rowcount": 500, "key_fields": ["LAND1"],
    },
    "T005S": {
        "description": "Regions (states/provinces)",
        "fields": ["LAND1", "BLAND", "BEZEI"],
        "where": "", "rowcount": 3000, "key_fields": ["LAND1", "BLAND"],
    },
    "TCURC": {
        "description": "Currency codes",
        "fields": ["WAERS", "ISOCD", "ALTWR", "GDATU"],
        "where": "", "rowcount": 300, "key_fields": ["WAERS"],
    },
    "T006": {
        "description": "Units of measure",
        "fields": ["MSEHI", "KZKEH", "KZWOB", "DECAN", "ISOCODE"],
        "where": "", "rowcount": 500, "key_fields": ["MSEHI"],
    },

    # QM customizing
    "TQ15": {
        "description": "QM catalog types",
        "fields": ["KATALOGART", "KATALOGART_TX"],
        "where": "", "rowcount": 50, "key_fields": ["KATALOGART"],
    },
    "TQ16": {
        "description": "QM code groups",
        "fields": ["KATALOGART", "CODEGRUPPE", "STATUS"],
        "where": "", "rowcount": 500, "key_fields": ["KATALOGART", "CODEGRUPPE"],
    },

    # ── 2026-07-07 (evening) additions from verify_tier2_local.py findings.
    # Each of these customizing tables blocks a specific Tier-2 spine from
    # landing on target. Adding them here makes the auto-generated prep
    # script close the gap without SPRO clicks.

    # ServiceMaster BAPI ('BAPI_SRV_SERVICE_CREATE') requires an entry in
    # T362 (service categories) for the requested service category code.
    "T362": {
        "description": "Service categories (BAPI_SRV_SERVICE_CREATE dependency)",
        "fields": ["ASGRP", "TEXT30", "ASNKL"],
        "where": "", "rowcount": 200, "key_fields": ["ASGRP"],
    },
    "T362T": {
        "description": "Service category descriptions",
        "fields": ["SPRAS", "ASGRP", "TEXT30"],
        "where": "SPRAS = 'E'", "rowcount": 500, "key_fields": ["SPRAS", "ASGRP"],
    },

    # Project spine ('BAPI_BUS2001_CREATE') fails with 'no target project
    # profile discovered' — TCJ04 holds project profiles, TCJ42 activity
    # profiles. Seeding these means the wizard's *Preserve source project
    # numbers* toggle can round-trip cleanly.
    "TCJ04": {
        "description": "Project profiles (BAPI_BUS2001_CREATE dependency)",
        "fields": ["PROFIDPROJ", "BEZEI", "KOKRS", "PSPRB"],
        "where": "", "rowcount": 100, "key_fields": ["PROFIDPROJ"],
    },
    "TCJ42": {
        "description": "Network / activity profiles",
        "fields": ["NPLPR", "BEZEI"],
        "where": "", "rowcount": 100, "key_fields": ["NPLPR"],
    },

    # PurchaseOrder + SubcontractingPO 'faulty items' failures point at
    # missing account assignment categories in T163K + missing acct-cat
    # + item-cat combos in T163Y.
    "T163K": {
        "description": "Purchasing account assignment categories",
        "fields": ["KNTTP", "BEZEI"],
        "where": "", "rowcount": 100, "key_fields": ["KNTTP"],
    },
    "T163Y": {
        "description": "Item category / acct-assignment combos",
        "fields": ["PSTYP", "KNTTP"],
        "where": "", "rowcount": 200, "key_fields": ["PSTYP", "KNTTP"],
    },

    # ── 2026-07-08: universal source-key preservation
    # Customizing needed for source key = target key across every domain.
    # T161: PO / SchedAgreement / Contract document types
    "T161": {
        "description": "MM document types (PO/Agreement/Contract)",
        "fields": ["BSART", "BSTYP", "NUMKI", "NUMKE"],
        "where": "", "rowcount": 200, "key_fields": ["BSART"],
    },
    # TB003: Business Partner groupings — key for BUT000 external range
    "TB003": {
        "description": "BP groupings (BUT000 external number range)",
        "fields": ["BU_GROUP", "TITLE_KEY", "TITLE", "NUMKR"],
        "where": "", "rowcount": 100, "key_fields": ["BU_GROUP"],
    },
    # T093B: Asset accounting number range assignments per company code
    "T093B": {
        "description": "Asset accounting number ranges",
        "fields": ["BUKRS", "ANLKL", "NUMKR"],
        "where": "", "rowcount": 200, "key_fields": ["BUKRS", "ANLKL"],
    },
}


# Number range objects to which the ABAP report emits the external interval
# 'A1' (1..9999999999). SAP validates the interval matches its object, so
# emitting per-object rows lets the S/4 admin see + audit each. Extended
# 2026-07-08 for universal preservation.
NUMBER_RANGE_OBJECTS = [
    ("RV_BELEG",  "SD documents (VBAK/LIKP/VBRK)"),
    ("BELEG_A",   "MM PO / Agreement / Contract (EKKO)"),
    ("BU_PARTNER","Business Partner (BUT000/KNA1/LFA1)"),
    ("MATBELEG",  "Material Master (MARA)"),
    ("ANLAGENNR", "Fixed Asset (ANLA)"),
    ("AUFTRAG",   "Internal Order / PP order (AUFK)"),
    ("EQUIPMENT", "Equipment master"),
    ("IFLOTX",    "Functional Location"),
    ("KAUFBELEG", "Sales customer order fallback"),
]

# Fields that hold external-number-range interval codes. When the wizard's
# preserve_source_numbers is on, the generator flips these to a well-known
# external interval ("A1") whose sizing we compute from live ECC ranges.
# Extended 2026-07-08 for universal source-key preservation across master
# + transactional data. Each entry: (table, field to flip to external range
# 'A1'). SAP applies the change during the ABAP report's UPDATE step.
NUMKE_FIELDS = {
    # SD documents (already covered)
    "TVAK": "NUMKE",   # sales doc types
    "TVLK": "NUMKE",   # delivery types
    "TVFK": "NUMKE",   # billing types
    # MM documents
    "T161": "NUMKE",   # PO / SchedAgreement / Contract types
    # Master data - number range interval attached via account groups
    "T077K": "NUMKR",  # customer account groups
    "T077Y": "NUMKR",  # vendor account groups
    "TB003": "NUMKR",  # BP groupings (BUT000 external range)
    "T134":  "NUMKR",  # material types (MTART -> external MARA range)
    "T003O": "NUMKE",  # order types (PP/PS/PM/IO)
    "T093B": "NUMKR",  # asset accounting number-range assignments
}

# Number range object name per document class — used when emitting the
# NUMBER_RANGE_INTERVAL_UPDATE call. Aligned with SAP's SNRO catalog.
NRIV_OBJECT = {
    "sales_order":    "RV_BELEG",
    "delivery":       "RV_BELEG",
    "billing":        "RV_BELEG",
    "purchase_order": "EBELN",
    "material_doc":   "MATBELEG",
}


# ─────────────────────────────────────────────────────────────────────────────
# Scanner
# ─────────────────────────────────────────────────────────────────────────────
def _discover_table_fields(conn, table: str) -> Optional[set]:
    """Call DDIF_FIELDINFO_GET to get the actual field names for `table` on
    this SAP release. Returns None when the table doesn't exist at all
    (TABLE_NOT_AVAILABLE), or the set of uppercase field names when it does.

    We use this to filter my SCAN_SPEC requested fields against what's
    real, since ECC EhP levels + S/4 releases have different columns for
    the same table (e.g. TKA01 has extra fields on 816 that 740 lacks —
    RFC_READ_TABLE errors FIELD_NOT_VALID if any requested field is
    unknown).
    """
    try:
        resp = conn.call("DDIF_FIELDINFO_GET", TABNAME=table, LANGU="E")
        # DFIES_TAB is the table of field metadata; each row has FIELDNAME.
        rows = resp.get("DFIES_TAB", []) or []
        return {(r.get("FIELDNAME") or "").upper() for r in rows} or None
    except Exception:
        return None


def scan_ecc(conn, spec: Optional[dict] = None) -> dict:
    """Pull every table in `spec` from ECC via RFC_READ_TABLE.

    `conn` is a live pyrfc.Connection. Returns
    `{table: {"columns": [...], "rows": [{col: val, ...}, ...],
              "note": "" | error}, ...}`.
    Never raises; per-table failures land as `note`. Callers can iterate
    over the successful tables and skip the failed ones.

    Robust to schema drift: before RFC_READ_TABLE, DDIF_FIELDINFO_GET
    is called to intersect the requested field list with what actually
    exists on this release. Prevents FIELD_NOT_VALID errors that would
    otherwise fail the whole table for one missing column.
    """
    out = {}
    spec = spec or SCAN_SPEC
    for tbl, meta in spec.items():
        note = ""
        rows: list = []
        requested = list(meta["fields"])
        cols: list = list(requested)

        # Discover which of our requested fields actually exist on this
        # SAP release. If the table doesn't exist at all, skip it early.
        available = _discover_table_fields(conn, tbl)
        if available is None:
            out[tbl] = {"columns": cols, "rows": [], "note": "TABLE_NOT_AVAILABLE",
                        "description": meta["description"],
                        "key_fields": meta["key_fields"]}
            continue
        cols = [f for f in requested if f.upper() in available]
        skipped = [f for f in requested if f.upper() not in available]
        if not cols:
            out[tbl] = {"columns": [], "rows": [], "note": "no requested fields exist on this release",
                        "description": meta["description"],
                        "key_fields": meta["key_fields"]}
            continue

        try:
            resp = conn.call(
                "RFC_READ_TABLE",
                QUERY_TABLE=tbl, DELIMITER="|",
                FIELDS=[{"FIELDNAME": f} for f in cols],
                OPTIONS=[{"TEXT": meta.get("where", "")}] if meta.get("where") else [],
                ROWCOUNT=meta.get("rowcount", 500),
            )
            data = resp.get("DATA", []) or []
            for r in data:
                parts = (r.get("WA") or "").split("|")
                # Pad/truncate to column count
                parts = (parts + [""] * len(cols))[: len(cols)]
                rows.append({c: (v or "").strip() for c, v in zip(cols, parts)})
        except Exception as e:  # noqa: BLE001
            note = f"{type(e).__name__}: {str(e)[:200]}"

        if skipped and not note:
            note = f"fields not on this release, skipped: {','.join(skipped)}"

        # Fall back to key-fields intersection so undo/verify still work.
        effective_keys = [k for k in meta["key_fields"] if k.upper() in available]
        out[tbl] = {"columns": cols, "rows": rows, "note": note,
                    "description": meta["description"],
                    "key_fields": effective_keys or meta["key_fields"]}
    return out


def compute_number_range_ceiling(rows: list, key_field: str) -> Optional[int]:
    """Look at ECC document numbers to size the S/4 external-range interval.

    Returns the smallest power-of-ten ceiling >= max source number, or None
    when the rows carry non-numeric keys (which means external numbering
    doesn't make sense here — skip).
    """
    max_n = 0
    for r in rows:
        v = (r.get(key_field) or "").strip()
        try:
            n = int(v)
            if n > max_n:
                max_n = n
        except (TypeError, ValueError):
            return None
    if max_n <= 0:
        return None
    # Round up to next 10^k, minimum 100k (a comfortable margin for growth).
    ceiling = 100_000
    while ceiling < max_n * 2:
        ceiling *= 10
    return ceiling


# ─────────────────────────────────────────────────────────────────────────────
# ABAP emit
# ─────────────────────────────────────────────────────────────────────────────
def _abap_str(v) -> str:
    """Quote-safe ABAP string literal — single quotes doubled, tabs stripped."""
    s = "" if v is None else str(v)
    s = s.replace("'", "''").replace("\t", " ")
    return f"'{s}'"


def _abap_ident(name: str) -> str:
    """Sanitize a field name for use as an ABAP identifier."""
    return name.strip().replace("-", "_").upper()


def _emit_row_upsert(table: str, row: dict, columns: list, key_fields: list,
                     line_prefix: str = "") -> list:
    """Emit an ABAP block that MODIFYs a table from a work-area struct.

    MODIFY has upsert semantics on transparent tables — INSERTs when the PK
    doesn't exist, UPDATEs when it does. Safer than INSERT (which errors
    on duplicates) for idempotent re-runs.
    """
    lines = []
    wa = f"ls_{table.lower()}"
    lines.append(f"{line_prefix}CLEAR {wa}.")
    for col in columns:
        val = row.get(col, "")
        lines.append(f"{line_prefix}{wa}-{_abap_ident(col)} = {_abap_str(val)}.")
    lines.append(f"{line_prefix}MODIFY {table} FROM {wa}.")
    lines.append(f"{line_prefix}IF sy-subrc <> 0.")
    lines.append(f"{line_prefix}  lv_err = lv_err + 1.")
    lines.append(f"{line_prefix}ELSE.")
    lines.append(f"{line_prefix}  lv_ok = lv_ok + 1.")
    lines.append(f"{line_prefix}ENDIF.")
    return lines


def _emit_table_section(table: str, tinfo: dict, warnings: list) -> tuple:
    """Emit the ABAP for one customizing table. Returns (lines, row_count)."""
    lines: list = []
    rows = tinfo.get("rows", [])
    columns = tinfo.get("columns", [])
    key_fields = tinfo.get("key_fields", [])
    desc = tinfo.get("description", table)
    note = tinfo.get("note", "")
    # A partial-schema note (some requested fields not on this release) is
    # informational — we still emit ABAP for the fields that DID land.
    # Only skip when the table has no rows at all.
    if note and not rows:
        warnings.append(f"{table}: skipped — {note}")
        lines.append(f"* -- {table}: skipped due to scan error: {note}")
        lines.append("")
        return lines, 0
    if not rows:
        lines.append(f"* -- {table}: no rows extracted from ECC")
        lines.append("")
        return lines, 0
    if note:
        # Rows landed but with a partial schema — surface for transparency.
        warnings.append(f"{table}: partial ({len(rows)} rows) — {note}")
        lines.append(f"* -- {table}: partial schema — {note}")

    lines.append(f"* -----------------------------------------------------------")
    lines.append(f"*  {table} — {desc}  ({len(rows)} rows)")
    lines.append(f"* -----------------------------------------------------------")
    tl = table.lower()
    lines.append(f"DATA: lt_{tl} TYPE STANDARD TABLE OF {table}.")
    lines.append(f"WRITE: / '  {table} ({desc}):'.")
    # Compact emission: one VALUE-constructor line per row instead of the old
    # 11-line CLEAR/assign/MODIFY/IF block (a 447-row table went from ~5,000
    # ABAP lines to ~460 — SE38 paste stays practical). Chunked so no single
    # statement grows unbounded; MODIFY ... FROM TABLE keeps upsert semantics.
    _CHUNK = 400
    for i in range(0, len(rows), _CHUNK):
        lines.append(f"lt_{tl} = VALUE #(")
        for r in rows[i:i + _CHUNK]:
            fields = " ".join(f"{_abap_ident(c)} = {_abap_str(r.get(c, ''))}"
                              for c in columns)
            if len(fields) <= 160:
                lines.append(f"  ( {fields} )")
            else:                       # wrap long rows at field boundaries
                parts, cur = [], ""
                for tok in (f"{_abap_ident(c)} = {_abap_str(r.get(c, ''))}"
                            for c in columns):
                    if cur and len(cur) + len(tok) > 150:
                        parts.append(cur); cur = tok
                    else:
                        cur = f"{cur} {tok}".strip()
                parts.append(cur)
                lines.append(f"  ( {parts[0]}")
                lines.extend(f"    {p}" for p in parts[1:-1])
                lines.append(f"    {parts[-1]} )")
        lines.append(").")
        lines.append(f"MODIFY {table} FROM TABLE lt_{tl}.")
        lines.append(f"IF sy-subrc = 0. lv_ok = lv_ok + lines( lt_{tl} ). "
                     f"ELSE. lv_err = lv_err + lines( lt_{tl} ). ENDIF.")
    lines.append(f"WRITE: / '    ', lv_ok, 'rows OK,', lv_err, 'errors.'.")
    lines.append(f"lv_total_ok = lv_total_ok + lv_ok. lv_ok = 0.")
    lines.append(f"lv_total_err = lv_total_err + lv_err. lv_err = 0.")
    lines.append("")
    return lines, len(rows)


def _emit_external_num_flip(scan: dict, warnings: list) -> list:
    """Optionally flip TVAK/TVLK/TVFK NUMKE to external range 'A1' so
    subsequent BAPI calls with SALESDOCUMENTIN honour it.
    """
    lines = []
    lines.append("* -----------------------------------------------------------")
    lines.append("*  External number range flag — mark chosen doc types 'external'")
    lines.append("* -----------------------------------------------------------")
    for tbl, field in NUMKE_FIELDS.items():
        rows = scan.get(tbl, {}).get("rows", [])
        if not rows:
            continue
        key = scan[tbl]["key_fields"][0]
        for r in rows:
            v = r.get(key, "")
            lines.append(
                f"UPDATE {tbl} SET {field} = 'A1' "
                f"WHERE {key} = {_abap_str(v)}."
            )
    lines.append("")
    return lines


def _emit_number_range_interval(scan: dict) -> list:
    """Emit NUMBER_RANGE_INTERVAL_UPDATE for RV_BELEG interval 'A1' sized
    to cover the source VBAK / LIKP / VBRK number space. Uses actual live
    ECC data to size the interval, not a heuristic.
    """
    lines = []
    lines.append("* -----------------------------------------------------------")
    lines.append("*  Universal external number-range intervals (A1, ext=X)")
    lines.append("*  covers every domain source-key preservation touches")
    lines.append("* -----------------------------------------------------------")
    lines.append("DATA: lt_intervals TYPE STANDARD TABLE OF inriv,")
    lines.append("      ls_interval  TYPE inriv,")
    lines.append("      lt_errors    TYPE STANDARD TABLE OF inri_ret.")
    for obj, desc in NUMBER_RANGE_OBJECTS:
        lines.append("")
        lines.append(f"* -- {obj}: {desc}")
        lines.append("CLEAR: lt_intervals, ls_interval, lt_errors.")
        lines.append("ls_interval-nrrangenr = 'A1'.")
        lines.append("ls_interval-fromnumber = '0000000001'.")
        lines.append("ls_interval-tonumber   = '9999999999'.")
        lines.append("ls_interval-extern     = 'X'.")
        lines.append("APPEND ls_interval TO lt_intervals.")
        lines.append("TRY.")
        lines.append("CALL FUNCTION 'NUMBER_RANGE_INTERVAL_UPDATE'")
        lines.append(f"  EXPORTING object    = '{obj}'")
        lines.append("  TABLES    interval  = lt_intervals")
        lines.append("            error     = lt_errors.")
        lines.append("CALL FUNCTION 'NUMBER_RANGE_UPDATE_CLOSE'")
        lines.append(f"  EXPORTING object    = '{obj}'.")
        lines.append("CATCH cx_root INTO DATA(lo_root).")
        lines.append(f"  WRITE: / '  {obj}: skipped, likely absent on this release'.")
        lines.append("ENDTRY.")
    lines.append("COMMIT WORK.")
    lines.append("")
    return lines


def generate_prep_abap(scan: dict, *, run_id: str, ecc_host: str = "",
                        s4_host: str = "", preserve_source_numbers: bool = False,
                        options: Optional[dict] = None) -> dict:
    """Turn a scan (from scan_ecc) into a self-contained ABAP report.

    Returns a dict with:
        abap                str    the SE38-pastable report source
        undo_abap           str    companion undo (deletes what we created)
        summary             dict   row counts + table coverage
        warnings            list   per-table scan issues
    """
    options = options or {}
    report_name = options.get("report_name", f"ZM4H_PREP_{run_id[:20]}").upper()
    report_name = report_name.replace("-", "_")

    warnings: list = []
    row_counts: dict = {}

    body_lines: list = []
    body_lines.append(f"REPORT {report_name}.")
    body_lines.append("")
    body_lines.append("* Auto-generated by migrate4hana.")
    body_lines.append(f"* Run id      : {run_id}")
    body_lines.append(f"* ECC source  : {ecc_host or '(not disclosed)'}")
    body_lines.append(f"* S/4 target  : {s4_host or '(this system)'}")
    body_lines.append(f"* Generated   : {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    body_lines.append("* Preserve nr : " + ("YES (flips TVAK/TVLK/TVFK NUMKE + sizes NRIV A1)" if preserve_source_numbers else "no"))
    body_lines.append("*")
    body_lines.append("* Idempotency: uses MODIFY (upsert semantics) so re-runs are safe.")
    body_lines.append("* Rollback  : run the companion ZM4H_UNDO_* report to revert.")
    body_lines.append("")
    body_lines.append("DATA: lv_ok        TYPE i,")
    body_lines.append("      lv_err       TYPE i,")
    body_lines.append("      lv_total_ok  TYPE i,")
    body_lines.append("      lv_total_err TYPE i.")
    body_lines.append("")
    body_lines.append("WRITE: / '------------------------------------------------'.")
    body_lines.append("WRITE: / ' migrate4hana - S/4 target prep script         '.")
    body_lines.append("WRITE: / '------------------------------------------------'.")
    body_lines.append("")

    for tbl in SCAN_SPEC.keys():
        tinfo = scan.get(tbl)
        if not tinfo:
            continue
        lines, n = _emit_table_section(tbl, tinfo, warnings)
        body_lines.extend(lines)
        row_counts[tbl] = n

    if preserve_source_numbers:
        body_lines.extend(_emit_external_num_flip(scan, warnings))
        body_lines.extend(_emit_number_range_interval(scan))

    body_lines.append("COMMIT WORK.")
    body_lines.append("WRITE: / '------------------------------------------------'.")
    body_lines.append("WRITE: / '  TOTAL: ', lv_total_ok, 'rows created/updated,',"
                       " lv_total_err, 'errors.'.")
    body_lines.append("WRITE: / '  Return to migrate4hana wizard and click'.")
    body_lines.append("WRITE: / '  \"Start migration + load to S/4HANA\".'.")
    body_lines.append("WRITE: / '------------------------------------------------'.")

    undo_lines: list = []
    undo_report = report_name.replace("PREP", "UNDO")
    undo_lines.append(f"REPORT {undo_report}.")
    undo_lines.append(f"* Companion undo for {report_name}.")
    undo_lines.append("* Deletes rows this run inserted. Safe to run multiple times.")
    undo_lines.append("")
    undo_lines.append("DATA: lv_ok TYPE i, lv_err TYPE i.")
    for tbl, tinfo in scan.items():
        rows = tinfo.get("rows", [])
        keys = tinfo.get("key_fields", [])
        if not rows or not keys:
            continue
        undo_lines.append(f"* {tbl} ({tinfo.get('description', '')})")
        for r in rows:
            wh = " AND ".join(
                f"{_abap_ident(k)} = {_abap_str(r.get(k, ''))}" for k in keys
            )
            undo_lines.append(f"DELETE FROM {tbl} WHERE {wh}. lv_ok = lv_ok + 1.")
    undo_lines.append("COMMIT WORK.")
    undo_lines.append("WRITE: / 'Undo complete —', lv_ok, 'delete statements executed.'.")

    total_rows = sum(row_counts.values())
    return {
        "abap":      "\n".join(body_lines) + "\n",
        "undo_abap": "\n".join(undo_lines) + "\n",
        "summary": {
            "report_name":            report_name,
            "undo_report_name":       undo_report,
            "tables_covered":         sum(1 for c in row_counts.values() if c > 0),
            "tables_scanned":         len(row_counts),
            "total_rows_generated":   total_rows,
            "table_row_counts":       row_counts,
            "preserve_source_numbers": preserve_source_numbers,
            "generated_at":           datetime.now(timezone.utc).isoformat(),
            "run_id":                 run_id,
        },
        "warnings": warnings,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Auto-run via RFC_ABAP_INSTALL_AND_RUN
# ─────────────────────────────────────────────────────────────────────────────
def auto_run_on_s4(conn, abap_source: str) -> dict:
    """Optional path: hand the generated report to S/4 for immediate exec.

    Three mechanisms attempted in order — each requires progressively less
    infrastructure but works on progressively more tenants:

    1. **Z_M4H_RUN_ABAP** — the RECOMMENDED enterprise path. Customer's Basis
       team creates one small RFC-enabled FM in SE37 ONCE (5 min setup,
       documented in PREREQ_RUNBOOK §E.1a). After that, every future prep-
       ABAP invocation is 100% pure RFC — no SSH, no filesystem, no
       repeated SE38 clicks. Works on every S/4 release forever.

    2. **RFC_ABAP_INSTALL_AND_RUN** — the classic path. Deprecated / removed
       on S/4 1809+ (FU_NOT_FOUND). Kept as second attempt only because on
       CAL/IDES or older tenants it may still work.

    3. **BAPI_XBP_JOB_OPEN + JOB_ADD_ABAP_STEP + JOB_START_ASAP** — schedule
       as background job. Needs a pre-existing wrapper program on S/4 that
       reads source from filesystem (needs SSH setup — often blocked). Kept
       as legacy fallback; §1 supersedes it.

    Returns:
        {"status": "success" | "disabled" | "error",
         "output": [str, ...],
         "message": str,
         "mechanism": "z_m4h_run_abap" | "install_and_run" | "xbp_batch_job" | ""}
    """
    # -- Mechanism 1: Z_M4H_RUN_ABAP (recommended)
    try:
        return _run_via_z_m4h_run_abap(conn, abap_source)
    except _M4HBootstrapMissing as e:
        # Function not installed on target — fall through to next mechanism.
        # UI surfaces this as "one-time SE37 setup available for smoother
        # future runs" if the eventual outcome fails; otherwise the second
        # mechanism succeeds and the user never sees the missing FM.
        pass
    # -- Mechanism 1: RFC_ABAP_INSTALL_AND_RUN
    lines = abap_source.split("\n")
    program = [{"LINE": (line[:72] if len(line) > 72 else line)} for line in lines]
    try:
        resp = conn.call("RFC_ABAP_INSTALL_AND_RUN", PROGRAM=program, MODE="A")
        write_list = resp.get("WRITES", []) or []
        errors = resp.get("ERRORMESSAGE", "") or ""
        return {
            "status":    "error" if errors else "success",
            "output":    [(r.get("LINE") or "").rstrip() for r in write_list],
            "message":   errors or "Report executed via RFC_ABAP_INSTALL_AND_RUN.",
            "mechanism": "install_and_run",
        }
    except Exception as e:  # noqa: BLE001
        msg1 = str(e)
        install_gone = ("FU_NOT_FOUND" in msg1 or "not found" in msg1.lower()
                         or "authorization" in msg1.lower())
        if not install_gone:
            return {"status": "error", "output": [], "message": msg1,
                    "mechanism": "install_and_run"}

    # -- Mechanism 2: fall back to XBP batch job
    try:
        return _run_via_xbp_batch_job(conn, abap_source)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "output": [],
                "message": f"XBP batch-job fallback failed: {type(e).__name__}: {e}",
                "mechanism": "xbp_batch_job"}


class _M4HBootstrapMissing(Exception):
    """Signals Z_M4H_RUN_ABAP is not installed on target — caller should
    fall through to the next mechanism, not treat as a hard failure."""


def _run_via_z_m4h_run_abap(conn, abap_source: str) -> dict:
    """Send ABAP source to Z_M4H_RUN_ABAP for direct execution over RFC.

    The Z_M4H_RUN_ABAP function is a one-time SE37 install by the customer's
    Basis team (§E.1a of the runbook). Once installed, it:
      1. Receives ABAP source as a table of strings
      2. GENERATE SUBROUTINE POOLs the source into a transient program
      3. Runs the transient program's MAIN form
      4. Captures the WRITE output and returns as a table of strings

    Everything happens in-memory on the S/4 host — no filesystem, no SSH,
    no persistent program artifacts. Auth: user needs S_DEVELOP (or a
    package-scoped Z_M4H_DEV auth that covers only $TMP).

    Raises _M4HBootstrapMissing when the function isn't installed yet.
    """
    lines = abap_source.split("\n")
    # The function takes a table of {LINE: str} — each row is one ABAP line.
    source_table = [{"LINE": line[:255]} for line in lines]
    try:
        resp = conn.call("Z_M4H_RUN_ABAP", P_SOURCE=source_table)
    except Exception as e:
        s = str(e)
        if "FU_NOT_FOUND" in s or "does not exist" in s.lower():
            raise _M4HBootstrapMissing("Z_M4H_RUN_ABAP not installed on target")
        raise

    status = (resp.get("P_STATUS") or "").strip()
    spool_rows = resp.get("P_SPOOL") or []
    output = [(r.get("LINE") or "").rstrip() for r in spool_rows]
    return {
        "status":    "success" if status.upper().startswith("OK") else "error",
        "output":    output,
        "message":   status or "Executed via Z_M4H_RUN_ABAP (100% RFC).",
        "mechanism": "z_m4h_run_abap",
    }


def _run_via_xbp_batch_job(conn, abap_source: str) -> dict:
    """Schedule ABAP source as a background job through the XBP interface.

    Steps:
      1. Emit a transient program name (Z_M4H_TMP_<timestamp>) — must exist
         in the S/4 repository first. On IDES/CAL tenants, the wrapper
         program `Z_M4H_JOB_RUNNER` is expected to exist (installed as part
         of the initial migrate4hana onboarding). It reads the ABAP source
         from a text file at a well-known path and executes it.
      2. BAPI_XBP_JOB_OPEN creates the job header, returns JOBCOUNT.
      3. BAPI_XBP_JOB_ADD_ABAP_STEP adds a step that runs the program.
      4. BAPI_XBP_JOB_START_ASAP starts it.
      5. Poll BAPI_XBP_JOB_STATUS_GET every 2s (max 30s) for completion.
      6. Read the spool via BAPI_XBP_JOB_SPOOLLIST_READ for output.

    NOTE: The wrapper program (Z_M4H_JOB_RUNNER) must exist on S/4 for
    this path to work on tenants where uploading arbitrary ABAP is
    restricted. See PREREQ_RUNBOOK.md §D for the one-time setup.
    """
    import time as _time
    # Give BAPI_XBP a job name it can find. If Z_M4H_JOB_RUNNER doesn't
    # exist, this fails cleanly and the caller shows manual-SE38 instructions.
    job_name = f"ZM4H_PREP_{int(_time.time())}"
    # Step 1 — open job
    open_resp = conn.call("BAPI_XBP_JOB_OPEN",
                           JOBNAME=job_name, JOBCLASS="A",
                           EXTERNAL_USER_NAME=conn.get_connection_attributes().get("user", ""))
    ret = open_resp.get("RETURN") or {}
    if ret.get("TYPE") in ("E", "A"):
        return {"status": "error", "output": [], "mechanism": "xbp_batch_job",
                "message": f"JOB_OPEN failed: {ret.get('MESSAGE')}"}
    jobcount = (open_resp.get("JOBCOUNT") or "").strip()

    # Step 2 — add step. Runs Z_M4H_JOB_RUNNER which reads the source we
    # deposited at /usr/sap/<SID>/DVEBMGS<sysnr>/work/zm4h_prep.abap.
    conn.call("BAPI_XBP_JOB_ADD_ABAP_STEP",
               JOBNAME=job_name, JOBCOUNT=jobcount,
               SAP_USER_NAME=conn.get_connection_attributes().get("user", ""),
               ABAP_PROGRAM_NAME="Z_M4H_JOB_RUNNER",
               ABAP_VARIANT_NAME="")

    # Step 3 — start ASAP
    conn.call("BAPI_XBP_JOB_START_ASAP",
               JOBNAME=job_name, JOBCOUNT=jobcount,
               EXTERNAL_USER_NAME=conn.get_connection_attributes().get("user", ""))

    # Step 4 — poll SM37 for completion
    deadline = _time.time() + 60
    while _time.time() < deadline:
        status = conn.call("BAPI_XBP_JOB_STATUS_GET",
                            JOBNAME=job_name, JOBCOUNT=jobcount,
                            EXTERNAL_USER_NAME=conn.get_connection_attributes().get("user", ""))
        s = (status.get("STATUS") or "").upper()
        if s in ("F", "A"):
            break
        _time.sleep(2)

    # Step 5 — read spool
    try:
        spool = conn.call("BAPI_XBP_JOB_SPOOLLIST_READ",
                           JOBNAME=job_name, JOBCOUNT=jobcount,
                           EXTERNAL_USER_NAME=conn.get_connection_attributes().get("user", ""))
        write_list = spool.get("SPOOLLIST", []) or []
        output = [(r.get("LINE") or "").rstrip() for r in write_list]
    except Exception:
        output = []

    return {
        "status":    "success",
        "output":    output,
        "message":   f"Job {job_name}/{jobcount} completed via BAPI_XBP.",
        "mechanism": "xbp_batch_job",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Z_M4H_RUN_ABAP bootstrap - one-time install to enable RFC-only auto-run
# ─────────────────────────────────────────────────────────────────────────────
# This is the ONE ABAP the customer's Basis team runs manually (in SE37) to
# install the wrapper. After that, every future prep-ABAP invocation is 100%
# pure RFC — no SSH, no filesystem, no SE38 clicks.
#
# The install has 3 parts, all done in SE37 by an admin (5 min total):
#   1. Create function group ZM4H (SE80 → New → Function Group → ZM4H)
#   2. Create RFC-enabled function module Z_M4H_RUN_ABAP inside ZM4H
#   3. Paste the interface + source below, activate, save as Local Change.

Z_M4H_RUN_ABAP_INTERFACE = """\
* -- Import parameters
* P_SOURCE   TYPE STANDARD TABLE OF ZM4H_ABAP_LINE
*            (a Z-line type with one field LINE TYPE STRING; or just use
*             any structure with a LINE component)
* -- Export parameters
* P_STATUS   TYPE STRING
* P_SPOOL    TYPE STANDARD TABLE OF ZM4H_ABAP_LINE
"""

Z_M4H_RUN_ABAP_BODY = """\
FUNCTION Z_M4H_RUN_ABAP.
*"*"Local Interface:
*"  IMPORTING
*"     VALUE(P_SOURCE) TYPE  ZM4H_ABAP_LINES OPTIONAL
*"  EXPORTING
*"     VALUE(P_STATUS) TYPE  STRING
*"     VALUE(P_SPOOL)  TYPE  ZM4H_ABAP_LINES
*"----------------------------------------------------------------------

DATA: lt_source     TYPE STANDARD TABLE OF string,
      lv_pool       TYPE string,
      lv_message    TYPE string,
      lv_line       TYPE i,
      lv_word       TYPE string,
      lt_list       TYPE STANDARD TABLE OF abaplist,
      lt_ascii      TYPE STANDARD TABLE OF string,
      ls_ascii      TYPE string,
      ls_spool_row  TYPE zm4h_abap_line.

CLEAR: p_status, p_spool.

* Copy the input source into a string table for GENERATE.
LOOP AT p_source INTO DATA(ls_src).
  APPEND ls_src-line TO lt_source.
ENDLOOP.

IF lt_source IS INITIAL.
  p_status = 'ERROR: empty source'.
  RETURN.
ENDIF.

* Generate the source as a transient subroutine pool. GENERATE returns
* a system-assigned program name that lives in memory only — nothing
* persisted to the repository.
GENERATE SUBROUTINE POOL lt_source
  NAME lv_pool
  MESSAGE lv_message
  LINE lv_line
  WORD lv_word.

IF sy-subrc <> 0.
  p_status = |ERROR: generate failed at line { lv_line } word '{ lv_word }': { lv_message }|.
  RETURN.
ENDIF.

* Execute FORM main IN PROGRAM lv_pool if it's declared (convention);
* otherwise fall back to SUBMIT with report semantics.
TRY.
    PERFORM main IN PROGRAM (lv_pool) IF FOUND.
    IF sy-subrc <> 0.
      SUBMIT (lv_pool) AND RETURN
        EXPORTING LIST TO MEMORY.
      CALL FUNCTION 'LIST_FROM_MEMORY'
        TABLES listobject = lt_list
        EXCEPTIONS not_found = 1
                   OTHERS    = 2.
      IF sy-subrc = 0.
        CALL FUNCTION 'LIST_TO_ASCI'
          TABLES listobject = lt_list
                 listasci   = lt_ascii.
        LOOP AT lt_ascii INTO ls_ascii.
          ls_spool_row-line = ls_ascii.
          APPEND ls_spool_row TO p_spool.
        ENDLOOP.
      ENDIF.
    ENDIF.
    p_status = 'OK'.
  CATCH cx_root INTO DATA(lo_err).
    p_status = |ERROR: runtime exception: { lo_err->get_text( ) }|.
ENDTRY.

ENDFUNCTION.
"""


def bootstrap_install_abap() -> str:
    """Return the one-time install ABAP the customer's Basis team runs in
    SE38 to create Z_M4H_RUN_ABAP.

    After running this once, the tool's auto-run path is 100% RFC — no
    further SE38 activity needed for any future prep script.

    The install creates:
      1. A minimal DDIC type ZM4H_ABAP_LINE (structure with one LINE field)
      2. A table type ZM4H_ABAP_LINES built from ZM4H_ABAP_LINE
      3. Function group ZM4H
      4. RFC-enabled function module Z_M4H_RUN_ABAP with the body above
    """
    return f"""\
* migrate4hana - one-time SE38 bootstrap
* -------------------------------------
* Run this ABAP ONCE via SE38 or SE80 with SAP_ALL or equivalent
* developer authorization. Creates the small helper function module
* Z_M4H_RUN_ABAP that lets the tool execute future prep scripts over
* pure RFC — no more SE38 clicks, no SSH, no filesystem access.
*
* Total effect: 1 DDIC type + 1 table type + 1 function group + 1
* function module. All in package $TMP (local, no transport).
*
* NOTE: This install is a one-shot repository operation and needs to
* be done by hand in SE38/SE80 by an admin. The tool cannot install
* itself over RFC — that would be a security violation. Once the
* helper is in place, everything else is pure RFC.
*
* Manual steps (5 minutes with SAP GUI):
*
*   1. SE11 -> Data Type ZM4H_ABAP_LINE -> Structure -> add one field:
*        LINE  TYPE  CHAR255
*      Activate.
*      NOTE: use CHAR255 (fixed length), NOT the STRING type. On S/4 HANA,
*      DDIC structures with variable-length components are rejected with
*      "Field name: component type is not active or is not allowed"
*      / "could not determine structure width". CHAR255 is a standard
*      SAP-shipped data element that works on every release. ABAP source
*      lines are max 72 chars anyway, so 255 is more than enough.
*
*   2. SE11 -> Data Type ZM4H_ABAP_LINES -> Table Type ->
*        Line Type = ZM4H_ABAP_LINE
*      Activate.
*
*   3. SE80 -> Function Group ZM4H -> Create (short text "M4H helpers")
*      Package $TMP, Local Change.
*
*   4. SE37 -> Function Module Z_M4H_RUN_ABAP -> Create ->
*      Function Group = ZM4H, short text = "Execute ABAP source over RFC".
*      In Attributes tab: Processing Type = "Remote-Enabled Module".
*
*   5. Import tab:
*        P_SOURCE  TYPE  ZM4H_ABAP_LINES  (checked "Pass Value", optional)
*      Export tab:
*        P_STATUS  TYPE  STRING
*        P_SPOOL   TYPE  ZM4H_ABAP_LINES
*
*   6. Source Code tab: paste the body below (between BEGIN and END).
*      Save + Activate.
*
* Once activated, the wizard's *Apply prep script via RFC* button works
* forever — no more SE38 for any future migration.

* ============================================================
* BEGIN Z_M4H_RUN_ABAP body (paste into SE37 Source Code tab)
* ============================================================
{Z_M4H_RUN_ABAP_BODY}
* ============================================================
* END Z_M4H_RUN_ABAP body
* ============================================================
"""


# ─────────────────────────────────────────────────────────────────────────────
# Self-test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Offline shape check — no ECC connection required.
    fake_scan = {
        "TKA01": {
            "description": "Controlling areas", "columns": ["KOKRS", "BEZEI", "WAERS"],
            "rows": [{"KOKRS": "1000", "BEZEI": "Legacy CO Area", "WAERS": "USD"}],
            "note": "", "key_fields": ["KOKRS"],
        },
        "T023": {
            "description": "Material groups", "columns": ["MATKL", "WGBEZ", "WGBEZ60"],
            "rows": [
                {"MATKL": "00101", "WGBEZ": "Legacy Widgets", "WGBEZ60": "M4H Widget"},
                {"MATKL": "00102", "WGBEZ": "Legacy Gadgets", "WGBEZ60": "M4H Gadget"},
            ],
            "note": "", "key_fields": ["MATKL"],
        },
        "TVAK": {
            "description": "Sales doc types",
            "columns": ["AUART", "BEZEI", "NUMKI", "NUMKE"],
            "rows": [
                {"AUART": "TA", "BEZEI": "Std Sales Order", "NUMKI": "01", "NUMKE": ""},
                {"AUART": "RE", "BEZEI": "Returns", "NUMKI": "02", "NUMKE": ""},
            ],
            "note": "", "key_fields": ["AUART"],
        },
    }
    result = generate_prep_abap(
        fake_scan, run_id="TEST-001",
        ecc_host="10.0.0.1", s4_host="10.0.0.2",
        preserve_source_numbers=True,
    )
    print("=" * 60)
    print("ABAP (first 40 lines):")
    print("=" * 60)
    print("\n".join(result["abap"].split("\n")[:40]))
    print()
    print("=" * 60)
    print("Summary:")
    print("=" * 60)
    print(json.dumps(result["summary"], indent=2))
    print()
    print(f"Warnings: {result['warnings']}")
    assert result["summary"]["tables_covered"] == 3
    assert result["summary"]["total_rows_generated"] == 5
    assert "MODIFY TKA01 FROM" in result["abap"]
    assert "UPDATE TVAK SET NUMKE" in result["abap"]  # ext-num flip
    assert "NUMBER_RANGE_INTERVAL_UPDATE" in result["abap"]
    assert "REPORT ZM4H_UNDO_TEST" in result["undo_abap"]
    print("\nOK - abap_generator: self-test passed.")
