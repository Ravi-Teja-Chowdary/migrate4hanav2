"""
inventory_balance_spine - InventoryBalance via BAPI_GOODSMVT_CREATE mvt 561.

Object-promotion grind batch 5 / 4. Initial-stock posting — the
balance-takeover at cutover. Movement type 561 = "receipt without
reference" / initial stock entry, the canonical SAP pattern for posting
opening inventory from legacy.

Source ECC row shape::

    {"MATNR": "<source material>",
     "LABST": "<unrestricted stock quantity>",
     "MEINS": "EA"}                         # base unit (default EA)

Tricky shape — two self-heals on one record:

1. **Material+plant+sloc harmonization**: source materials rarely carry the
   target's plant/sloc views. We discover a target-ready (material, plant,
   storage location) from MARD and post against that. The source-to-target
   harmonization is recorded as a "material@matdoc" target key in F1.

2. **MM-period self-heal**: the SAP appliance's MM current period often
   lags real time, so today's posting date triggers a "period closed"
   error. We parse the open period (YYYY/MM) from the BAPI message and
   retry once on the 15th of that period, then cache the corrected date
   for subsequent records in this run.

verify_key writes to MKPF (the material-doc header table) with BELNR + MJAHR.
"""
from __future__ import annotations

import datetime
import re
from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


def _parse_qty(val, default=0.0) -> float:
    try:
        s = str(val or "").strip().replace(",", "")
        return float(s) if s else float(default)
    except Exception:
        return float(default)


@register_spine
class InventoryBalanceSpineOrchestrator(BaseSpineOrchestrator):
    """InventoryBalance via BAPI_GOODSMVT_CREATE mvt 561 with MM-period self-heal."""

    object_type           = "InventoryBalance"
    source_key_field      = "MATNR"
    extension_structure   = "BAPI_TE_MARD"
    fk_fields: dict       = {}

    def validate(self, row: dict) -> Optional[str]:
        if not (row.get("MATNR") or "").strip():
            return "MATNR is required (source material)"
        if _parse_qty(row.get("LABST"), 0) <= 0:
            return "LABST (stock quantity) must be > 0"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        src_mat = (row.get("MATNR") or "").strip()
        qty = _parse_qty(row.get("LABST"))
        uom = (row.get("MEINS") or "EA").strip() or "EA"
        tgt_mat, plant, sloc = self._stock_target()
        if not tgt_mat or not plant or not sloc:
            return {"_no_target": True}

        payload: dict = {
            "_src_mat":  src_mat,
            "_tgt_mat":  tgt_mat,
            "_plant":    plant,
            "_sloc":     sloc,
            "_qty":      qty,
            "_uom":      uom,
        }
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    def call_bapi(self, payload: dict) -> tuple:
        from base_spine_orchestrator import DISP_CREATED, DISP_REMAPPED
        if payload.get("_no_target"):
            return None, ["no target material/plant/storage-location discovered"], None, None

        src_mat = payload.pop("_src_mat", "")
        tgt_mat = payload.pop("_tgt_mat", "")
        plant   = payload.pop("_plant", "")
        sloc    = payload.pop("_sloc", "")
        qty     = payload.pop("_qty", 0.0)
        uom     = payload.pop("_uom", "EA")
        ext_in  = payload.pop("EXTENSIONIN", None)
        ext_inx = payload.pop("EXTENSIONINX", None)

        def _post(pdate: str):
            hdr = {"PSTNG_DATE": pdate, "DOC_DATE": pdate,
                   "HEADER_TXT": f"M4H init stock {src_mat}"[:25]}
            item = [{"MATERIAL": tgt_mat, "PLANT": plant, "STGE_LOC": sloc,
                     "MOVE_TYPE": "561", "ENTRY_QNT": ("%.3f" % qty),
                     "ENTRY_UOM": uom}]
            kwargs = {"GOODSMVT_HEADER": hdr, "GOODSMVT_CODE": {"GM_CODE": "05"},
                      "GOODSMVT_ITEM":   item}
            if ext_in:
                kwargs["EXTENSIONIN"] = ext_in
            if ext_inx:
                kwargs["EXTENSIONINX"] = ext_inx
            return self.c.call("BAPI_GOODSMVT_CREATE", **kwargs)

        pdate = self._mm_posting_date()
        resp = _post(pdate)
        ret = resp.get("RETURN") or []
        if isinstance(ret, dict):
            ret_list = [ret] if ret.get("TYPE") else []
        else:
            ret_list = list(ret)

        # MM-period self-heal: parse the open period from the error message,
        # cache it, retry on the 15th of that period.
        period_err = [m for m in ret_list if "period" in (m.get("MESSAGE") or "").lower()]
        if period_err and not (resp.get("MATERIALDOCUMENT") or "").strip():
            try:
                self.c.call("BAPI_TRANSACTION_ROLLBACK")
            except Exception:
                pass
            mt = re.search(r"(\d{4})/(\d{2})", period_err[0].get("MESSAGE") or "")
            if mt:
                pdate = f"{mt.group(1)}{mt.group(2)}15"
                self._mm_pdate = pdate    # cache for subsequent records
                resp = _post(pdate)
                ret = resp.get("RETURN") or []
                if isinstance(ret, dict):
                    ret_list = [ret] if ret.get("TYPE") else []
                else:
                    ret_list = list(ret)

        hard = [m for m in ret_list if m.get("TYPE") in ("E", "A")]
        msgs = [(m.get("MESSAGE") or "").strip() for m in ret_list if m.get("MESSAGE")]
        doc = (resp.get("MATERIALDOCUMENT") or "").strip()
        year = (resp.get("MATDOCUMENTYEAR") or "").strip()
        if hard or not doc:
            try:
                self.c.call("BAPI_TRANSACTION_ROLLBACK")
            except Exception:
                pass
            return None, msgs, None, None

        try:
            self.c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception as e:
            msgs.append(f"commit failed: {e}")
            return None, msgs, None, None

        # Target identity is "<target_material>@<material_document>" — captures
        # both the material harmonization AND the matdoc reference
        target = f"{tgt_mat}@{doc}" if year == "" else f"{tgt_mat}@{doc}/{year}"
        vk = {"table": "MKPF", "key": {"MBLNR": doc, "MJAHR": year}}
        if tgt_mat != src_mat:
            msgs.append(f"material {src_mat} harmonized to target {tgt_mat}/{plant}/{sloc}")
            return target, msgs, DISP_REMAPPED, vk
        return target, msgs, DISP_CREATED, vk

    # ── target probes / MM-period cache ─────────────────────────────────────
    def _stock_target(self) -> tuple:
        cache = getattr(self, "_stock_tgt_cache", None)
        if cache is not None:
            return cache
        mat, plant, sloc = "", "", ""
        try:
            r = self.c.call(
                "RFC_READ_TABLE", QUERY_TABLE="MARD", DELIMITER="|",
                FIELDS=[{"FIELDNAME": "MATNR"}, {"FIELDNAME": "WERKS"},
                        {"FIELDNAME": "LGORT"}], ROWCOUNT=1,
            )
            data = r.get("DATA") or []
            if data:
                parts = (data[0].get("WA") or "").split("|") + ["", "", ""]
                mat, plant, sloc = (p.strip() for p in parts[:3])
        except Exception:
            pass
        self._stock_tgt_cache = (mat, plant, sloc)
        return mat, plant, sloc

    def _mm_posting_date(self) -> str:
        return getattr(self, "_mm_pdate", None) or datetime.date.today().strftime("%Y%m%d")
