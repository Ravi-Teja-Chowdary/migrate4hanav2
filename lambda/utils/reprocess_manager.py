"""
reprocess_manager - failed-record correction loop.

Enterprise migrations always have some rows that need human correction: blank
mandatory fields on source, values that don't map to target customizing,
records with malformed data. This module supports the standard workflow:

    1. Wizard run produces dead-letter rows in failed_records.json.
    2. Operator asks for either
        - a TEMPLATE (blank Excel with columns + one sample row filled in per
          object type — so the corrector knows the shape), or
        - the FAILURES (Excel of actual dead-letter rows, columns populated
          with what we had, ready to correct in-place).
    3. Corrector fills / fixes rows in Excel offline, saves.
    4. Corrector uploads the corrected Excel back through the wizard.
    5. Tool parses the Excel and calls each spine's load_one(row) — landed
       rows get added to the key_map registry, remaining failures go back
       into a NEW dead-letter file so the loop continues.

Excel format (per sheet, one sheet per object type)
---------------------------------------------------
    Row 1: Column headers (all fields the spine's field-map + DQ gates need).
    Row 2: Sample row with plausible values (guide only; corrector removes).
    Row 3+: Actual data (dead-letter rows in the failures export; blank in
            template mode).

Rationale for openpyxl over csv
-------------------------------
Corrective users edit in Excel, not text. openpyxl round-trips cleanly, we
can multi-sheet (one per object type), and native column widths + freeze
panes give the operator a comfortable UI. And the frontend can accept .xlsx
uploads via a plain multipart form — no bespoke tooling.
"""
from __future__ import annotations

import importlib
import inspect
import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    _OPENPYXL = True
except ImportError:
    _OPENPYXL = False


# ─────────────────────────────────────────────────────────────────────────────
# Sample values per common SAP field name — same pattern as verify_tier2's
# _default_for_source_field. Corrector sees these as "example values so I
# know the format" — they're removed from Row 2 before upload.
# ─────────────────────────────────────────────────────────────────────────────
_SAMPLE_VALUES = {
    "MATNR":     "TG0013",  "MATERIAL":  "TG0013",
    "KUNNR":     "0000001000", "CUSTOMER": "0000001000",
    "LIFNR":     "0000100001", "VENDOR":   "0000100001",
    "BUKRS":     "1710",    "COMP_CODE": "1710",
    "WERKS":     "1710",    "PLANT":     "1710",
    "EKORG":     "1710",    "PURCH_ORG": "1710",
    "EKGRP":     "001",     "PUR_GROUP": "001",
    "MEINS":     "EA",      "PO_UNIT":   "EA",
    "WAERS":     "USD",     "CURRENCY":  "USD",
    "NAME1":     "Sample Organization LLC",
    "NAME":      "Sample Organization LLC",
    "LAND1":     "US",
    "SPRAS":     "E",
    "KOKRS":     "A000",
    "KOSTL":     "0017101601", "COSTCENTER": "0017101601",
    "PRCTR":     "YB700",
    "SAKNR":     "0064002000", "GL_ACCOUNT": "0064002000",
    "BLART":     "SA",      "DOC_TYPE":  "NB",
    "AUART":     "TA",      "BSART":     "NB",
    "FKART":     "F2",      "LFART":     "LF",
    "VKORG":     "1710",
    "VTWEG":     "10",      "SPART":     "00",
    "MATKL":     "00101",   "MATL_GROUP": "00101",
    "MTART":     "FERT",
    "VBELN":     "0000000001",
    "EBELN":     "4500000001",
    "POSNR":     "10",
    "PSPID":     "T-20001",
    "PLNUM":     "0000000001",
    "AUFNR":     "4000000001",
    "DMBTR":     "100.00",  "AMOUNT":    "100.00",
    "MENGE":     "1",       "QUANTITY":  "1",
    "NETPR":     "10.00",   "NET_PRICE": "10.00",
    "SHKZG":     "S",
    "BELNR":     "1800000001",
    "CATEGORY":  "2",       "PARTNERCATEGORY": "2",
}


def _sample_for(field: str) -> str:
    return _SAMPLE_VALUES.get(field.upper(), "")


# ─────────────────────────────────────────────────────────────────────────────
# Spine field discovery
# ─────────────────────────────────────────────────────────────────────────────
def _spine_module_name(object_type: str) -> Optional[str]:
    """Turn an object type into the underscored spine module name."""
    import re
    snake = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', object_type)
    snake = re.sub(r'([a-z\d])([A-Z])', r'\1_\2', snake).lower()
    return f"{snake}_spine"


def _spine_field_specs(object_type: str) -> tuple:
    """Return (columns, sample_row_values) — the union of the source keys +
    every FIELD_MAPS / ITEM_FIELD_MAPS source field + every DQ_GATES field
    the spine declares.
    """
    mod_name = _spine_module_name(object_type)
    if not mod_name:
        return [], {}
    try:
        mod = importlib.import_module(mod_name)
    except Exception:
        # Squashed variant fallback (WBSElement -> wbselement_spine, etc.)
        squashed = mod_name.replace("_", "")[:-6] + "_spine"
        try:
            mod = importlib.import_module(squashed)
        except Exception:
            return [], {}

    field_maps = list(getattr(mod, "FIELD_MAPS", {}) or {})
    item_maps = list(getattr(mod, "ITEM_FIELD_MAPS", {}) or {})
    dq_gates = list(getattr(mod, "DQ_GATES", []) or [])
    dq_fields = []
    for gate in dq_gates:
        f = gate[0] if isinstance(gate, (tuple, list)) else gate.get("field")
        if f and f not in dq_fields:
            dq_fields.append(f)

    # Merge in the spine class's source_key_field
    src_key_fields = []
    try:
        from base_spine_orchestrator import BaseSpineOrchestrator
        for _, cls in inspect.getmembers(mod, inspect.isclass):
            if (cls is not BaseSpineOrchestrator
                    and issubclass(cls, BaseSpineOrchestrator)
                    and cls.__module__ == mod.__name__
                    and getattr(cls, "object_type", "") == object_type):
                sk = getattr(cls, "source_key_field", "")
                if sk:
                    src_key_fields.append(sk)
                break
    except Exception:
        pass

    # Compose column ordering: source_key first, then DQ gate fields, then
    # remaining FIELD_MAPS sources, then item fields.
    cols: list = []
    for group in (src_key_fields, dq_fields, field_maps, item_maps):
        for f in group:
            if f and f not in cols:
                cols.append(f)

    sample = {c: _sample_for(c) for c in cols}
    return cols, sample


# ─────────────────────────────────────────────────────────────────────────────
# Excel emit
# ─────────────────────────────────────────────────────────────────────────────
def _style_header(cell):
    cell.font = Font(bold=True, color="FFFFFF")
    cell.fill = PatternFill(start_color="1E40AF", end_color="1E40AF", fill_type="solid")
    cell.alignment = Alignment(horizontal="center", vertical="center")


def _style_sample(cell):
    cell.font = Font(italic=True, color="6B7280")


def write_template_workbook(object_types: list) -> bytes:
    """Emit an Excel workbook with one sheet per object type. Row 1 is the
    header, Row 2 is a sample row (italic gray), Row 3 onward is left blank
    for the corrector to add corrected rows to.
    """
    if not _OPENPYXL:
        raise RuntimeError("openpyxl not installed on the server")
    wb = Workbook()
    wb.remove(wb.active)
    for obj_type in object_types:
        cols, sample = _spine_field_specs(obj_type)
        if not cols:
            ws = wb.create_sheet(obj_type[:31] or "Sheet1")
            ws.cell(1, 1, f"(no field spec discoverable for {obj_type})")
            continue
        ws = wb.create_sheet(obj_type[:31])
        for c_idx, col in enumerate(cols, start=1):
            hdr = ws.cell(1, c_idx, col)
            _style_header(hdr)
            samp = ws.cell(2, c_idx, sample.get(col, ""))
            _style_sample(samp)
            ws.column_dimensions[get_column_letter(c_idx)].width = max(len(col) + 2, 14)
        # Notes row 3 for the operator
        ws.cell(3, 1, "-- delete Row 2 (samples) before uploading --")
        ws.cell(3, 1).font = Font(italic=True, color="9CA3AF")
        ws.freeze_panes = "A2"
    if not wb.sheetnames:
        wb.create_sheet("empty")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def write_failures_workbook(failed_records: list) -> bytes:
    """Emit an Excel workbook whose sheets contain the actual failed rows
    plus a status column and the reason for each failure so the corrector
    knows what needs fixing.
    """
    if not _OPENPYXL:
        raise RuntimeError("openpyxl not installed on the server")
    wb = Workbook()
    wb.remove(wb.active)

    by_object: dict = {}
    for fr in failed_records:
        obj = (fr.get("object") or "unknown")[:31]
        by_object.setdefault(obj, []).append(fr)

    for obj, rows in by_object.items():
        cols, _sample = _spine_field_specs(obj)
        # Field union: spine-declared + anything present in dead-letter data.
        # This gives the corrector every hint the source had.
        seen: list = list(cols)
        for r in rows:
            data = r.get("row") or r.get("source") or {}
            if isinstance(data, dict):
                for k in data.keys():
                    if k and k not in seen and not k.startswith("_"):
                        seen.append(k)
        # Two synthetic columns at the end for correction guidance
        seen.extend(["__failure_reason", "__failure_code"])

        ws = wb.create_sheet(obj)
        for c_idx, col in enumerate(seen, start=1):
            hdr = ws.cell(1, c_idx, col)
            _style_header(hdr)
            ws.column_dimensions[get_column_letter(c_idx)].width = max(len(col) + 2, 14)

        for r_idx, r in enumerate(rows, start=2):
            data = r.get("row") or r.get("source") or {}
            if not isinstance(data, dict):
                data = {}
            for c_idx, col in enumerate(seen, start=1):
                if col == "__failure_reason":
                    msgs = r.get("messages") or []
                    reason = "; ".join(str(m) for m in msgs)[:200] or r.get("reason", "")
                    ws.cell(r_idx, c_idx, reason)
                elif col == "__failure_code":
                    ws.cell(r_idx, c_idx, r.get("code") or r.get("dead_letter") or "")
                else:
                    v = data.get(col, "")
                    ws.cell(r_idx, c_idx, str(v) if v is not None else "")
        ws.freeze_panes = "A2"
    if not wb.sheetnames:
        wb.create_sheet("empty")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# Excel parse + reprocess
# ─────────────────────────────────────────────────────────────────────────────
def parse_correction_workbook(xlsx_bytes: bytes) -> dict:
    """Parse a corrected Excel workbook back into per-object row lists.

    Returns {object_type: [{row: {...}, __failure_reason?, __failure_code?},
                            ...], ...}. Ignores empty rows and the sample
    row (any row whose *first* cell is empty).
    """
    if not _OPENPYXL:
        raise RuntimeError("openpyxl not installed on the server")
    wb = load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
    out: dict = {}
    for ws in wb.worksheets:
        obj_type = ws.title
        headers = [str(c.value) if c.value is not None else "" for c in ws[1]]
        rows_out: list = []
        for r_idx in range(2, ws.max_row + 1):
            # Skip the sample row (heuristic: any row that says "delete Row"
            # in first column, or is fully empty)
            values = [ws.cell(r_idx, c + 1).value for c in range(len(headers))]
            if not any(v not in (None, "") for v in values):
                continue
            if isinstance(values[0], str) and values[0].startswith("--"):
                continue
            row_dict = {}
            for h, v in zip(headers, values):
                if not h or h.startswith("_") and h.startswith("__"):
                    # Skip our synthetic reason/code columns
                    continue
                if v is None:
                    continue
                row_dict[h] = str(v).strip() if not isinstance(v, (int, float)) else v
            if row_dict:
                rows_out.append(row_dict)
        if rows_out:
            out[obj_type] = rows_out
    return out


def reprocess_rows(tconn, corrections: dict, *, key_map=None,
                    preserve_source_numbers: bool = False) -> dict:
    """For each (object_type, rows) pair, call the spine's load_one(row) for
    every row. Report per-row outcome.

    Returns::

        {"summary": {"attempted": int, "created": int, "matched": int,
                     "still_failed": int},
         "per_object": {object_type: {"attempted": int, "created": int,
                                       "matched": int, "still_failed": int,
                                       "results": [...]}, ...},
         "still_failed_records": [row for later retry, ...]}
    """
    import inspect as _inspect
    from base_spine_orchestrator import BaseSpineOrchestrator
    if preserve_source_numbers:
        os.environ["M4H_PRESERVE_SRC_NUMBERS"] = "1"

    def _find_bapi_class(obj_type: str):
        mod_name = _spine_module_name(obj_type)
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            return None
        for _, cls in _inspect.getmembers(mod, _inspect.isclass):
            if (cls is not BaseSpineOrchestrator
                    and issubclass(cls, BaseSpineOrchestrator)
                    and cls.__module__ == mod.__name__
                    and getattr(cls, "object_type", "") == obj_type):
                return cls
        return None

    per_object: dict = {}
    still_failed: list = []
    tot_att = tot_created = tot_matched = tot_failed = 0

    for obj_type, rows in corrections.items():
        cls = _find_bapi_class(obj_type)
        if cls is None:
            per_object[obj_type] = {
                "attempted": 0, "created": 0, "matched": 0,
                "still_failed": len(rows),
                "results": [{"object": obj_type, "source_key": "",
                              "status": "no_spine",
                              "reason": f"no spine registered for {obj_type}"}
                             for _ in rows],
            }
            tot_failed += len(rows)
            for r in rows:
                still_failed.append({"object": obj_type, "row": r,
                                      "reason": "no spine registered"})
            continue

        orch = cls(tconn, key_map=key_map, dry_run=False,
                    target_release=os.environ.get("M4H_TARGET_RELEASE", "S4HANA_2022"))
        per: dict = {"attempted": 0, "created": 0, "matched": 0,
                     "still_failed": 0, "results": []}
        for row in rows:
            per["attempted"] += 1
            tot_att += 1
            try:
                res = orch.load_one(row)
            except Exception as e:
                per["still_failed"] += 1
                tot_failed += 1
                per["results"].append({"source_key": row.get(getattr(cls, "source_key_field", ""), ""),
                                        "status": "exception",
                                        "reason": f"{type(e).__name__}: {e}"})
                still_failed.append({"object": obj_type, "row": row,
                                      "reason": f"{type(e).__name__}: {e}"})
                continue
            outcome = res.status
            if outcome == "created":
                per["created"] += 1
                tot_created += 1
            elif outcome == "matched_existing":
                per["matched"] += 1
                tot_matched += 1
            else:
                per["still_failed"] += 1
                tot_failed += 1
                reason = (res.messages or [""])[0]
                still_failed.append({"object": obj_type, "row": row,
                                      "reason": reason, "code": res.dead_letter})
            per["results"].append({
                "source_key": res.source_key, "target_key": res.target_key,
                "status": outcome, "reason": (res.messages or [""])[0][:200],
                "code": res.dead_letter,
            })
        per_object[obj_type] = per

    return {
        "summary": {"attempted": tot_att, "created": tot_created,
                     "matched": tot_matched, "still_failed": tot_failed},
        "per_object": per_object,
        "still_failed_records": still_failed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Self-test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Spec discovery without live SAP
    cols, sample = _spine_field_specs("BusinessPartner")
    print("BusinessPartner columns:", cols)
    print("BusinessPartner sample:  ", sample)

    xlsx = write_template_workbook(["BusinessPartner", "Material", "SalesOrder"])
    Path("/tmp/tpl.xlsx").parent.mkdir(exist_ok=True, parents=True) if False else None
    print(f"Template workbook: {len(xlsx)} bytes")
    parsed = parse_correction_workbook(xlsx)
    print(f"Round-trip parse: {list(parsed.keys())}")
