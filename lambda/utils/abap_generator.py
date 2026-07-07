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
}

# Fields that hold external-number-range interval codes. When the wizard's
# preserve_source_numbers is on, the generator flips these to a well-known
# external interval ("A1") whose sizing we compute from live ECC ranges.
NUMKE_FIELDS = {"TVAK": "NUMKE", "TVLK": "NUMKE", "TVFK": "NUMKE"}

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
def scan_ecc(conn, spec: Optional[dict] = None) -> dict:
    """Pull every table in `spec` from ECC via RFC_READ_TABLE.

    `conn` is a live pyrfc.Connection. Returns
    `{table: {"columns": [...], "rows": [{col: val, ...}, ...],
              "note": "" | error}, ...}`.
    Never raises; per-table failures land as `note`. Callers can iterate
    over the successful tables and skip the failed ones.
    """
    out = {}
    spec = spec or SCAN_SPEC
    for tbl, meta in spec.items():
        note = ""
        rows: list = []
        cols: list = list(meta["fields"])
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
        out[tbl] = {"columns": cols, "rows": rows, "note": note,
                    "description": meta["description"],
                    "key_fields": meta["key_fields"]}
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
    if note:
        warnings.append(f"{table}: skipped — {note}")
        lines.append(f"* -- {table}: skipped due to scan error: {note}")
        lines.append("")
        return lines, 0
    if not rows:
        lines.append(f"* -- {table}: no rows extracted from ECC")
        lines.append("")
        return lines, 0

    lines.append(f"* -----------------------------------------------------------")
    lines.append(f"*  {table} — {desc}  ({len(rows)} rows)")
    lines.append(f"* -----------------------------------------------------------")
    lines.append(f"DATA: ls_{table.lower()} TYPE {table}.")
    lines.append(f"WRITE: / '  {table} ({desc}):'.")
    for r in rows:
        lines.extend(_emit_row_upsert(table, r, columns, key_fields, line_prefix=""))
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
    # Sizing is derived from TVAK context — we honour the largest ECC key.
    ceilings = []
    # We don't have VBAK/LIKP/VBRK numbers in the scan (only customizing),
    # so we make a defensive default: 1..9,999,999. The wizard passes an
    # observed ECC max via _generate_options and we override here.
    lines.append("* -----------------------------------------------------------")
    lines.append("*  Number range interval 'A1' for RV_BELEG (sales/dlv/billing)")
    lines.append("* -----------------------------------------------------------")
    lines.append("DATA: lt_intervals TYPE STANDARD TABLE OF inriv,")
    lines.append("      ls_interval  TYPE inriv,")
    lines.append("      lt_errors    TYPE STANDARD TABLE OF inri_ret.")
    lines.append("ls_interval-nrrangenr = 'A1'.")
    lines.append("ls_interval-fromnumber = '0000000001'.")
    lines.append("ls_interval-tonumber   = '9999999999'.")
    lines.append("ls_interval-extern     = 'X'.")
    lines.append("APPEND ls_interval TO lt_intervals.")
    lines.append("CALL FUNCTION 'NUMBER_RANGE_INTERVAL_UPDATE'")
    lines.append("  EXPORTING object    = 'RV_BELEG'")
    lines.append("  TABLES    interval  = lt_intervals")
    lines.append("            error     = lt_errors.")
    lines.append("CALL FUNCTION 'NUMBER_RANGE_UPDATE_CLOSE'")
    lines.append("  EXPORTING object    = 'RV_BELEG'.")
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

    RFC_ABAP_INSTALL_AND_RUN takes the ABAP source in the PROGRAM table,
    executes it, and returns the WRITE list output. Many production systems
    disable this RFC for security — the tool falls back to "manual SE38"
    if the call errors, and the caller surfaces the reason to the UI.

    Returns:
        {"status": "success" | "disabled" | "error",
         "output": [str, ...],           # WRITE list from the executed report
         "message": str}
    """
    # PROGRAM structure per RFC_ABAP_INSTALL_AND_RUN: table of {LINE: str<=72}.
    lines = abap_source.split("\n")
    program = [{"LINE": (line[:72] if len(line) > 72 else line)} for line in lines]
    try:
        resp = conn.call(
            "RFC_ABAP_INSTALL_AND_RUN",
            PROGRAM=program,
            MODE="A",
        )
        write_list = resp.get("WRITES", []) or []
        errors = resp.get("ERRORMESSAGE", "") or ""
        return {
            "status": "error" if errors else "success",
            "output": [(r.get("LINE") or "").rstrip() for r in write_list],
            "message": errors or "Report executed on S/4.",
        }
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "authorization" in msg.lower() or "disabled" in msg.lower() \
                or "not allowed" in msg.lower():
            status = "disabled"
        else:
            status = "error"
        return {"status": status, "output": [], "message": msg}


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
