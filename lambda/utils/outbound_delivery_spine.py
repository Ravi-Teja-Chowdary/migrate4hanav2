"""
outbound_delivery_spine - SD Outbound Delivery via BAPI_OUTB_DELIVERY_CREATESLS.

Object-promotion grind batch 7 / 4. Outbound delivery (LIKP/LIPS) is the
goods-issue document that precedes invoicing. Created from a sales order;
typically the source delivery references a target SO that the
SalesOrder spine has already loaded (so we F1-resolve VBELN_VL ->
target SO).

Source ECC LIKP/LIPS row shape::

    {"VBELN":   "<source delivery>",
     "VBELN_VL":"<source SO that this delivery references>",
     "LFART":   "LF",                   # delivery type
     "WERKS":   "<plant>",
     "POSNR":   "10",                   # item position from the SO
     "LFIMG":   "<delivery qty>"}
"""
from __future__ import annotations

from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


@register_spine
class OutboundDeliverySpineOrchestrator(BaseSpineOrchestrator):
    """OutboundDelivery via BAPI_OUTB_DELIVERY_CREATESLS."""

    object_type           = "OutboundDelivery"
    source_key_field      = "VBELN"
    extension_structure   = "BAPI_TE_LIKP"
    fk_fields: dict       = {}

    def validate(self, row: dict) -> Optional[str]:
        if not (row.get("VBELN") or "").strip():
            return "VBELN is required (source delivery number)"
        if not (row.get("VBELN_VL") or "").strip():
            return "VBELN_VL is required (referenced sales order)"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        src_dlv = (row["VBELN"] or "").strip()
        src_so  = (row["VBELN_VL"] or "").strip()
        tgt_so = None
        if self.key_map is not None:
            tgt_so = self.key_map.resolve("SalesOrder", src_so)
        tgt_so = tgt_so or src_so

        items = [{
            "REF_DOC":   tgt_so,
            "REF_ITEM":  (row.get("POSNR") or "10").rjust(6, "0"),
            "DLV_QTY":   str(row.get("LFIMG") or "1"),
            "SALES_UNIT": (row.get("MEINS") or "EA").strip(),
        }]
        payload: dict = {
            "SHIP_POINT":  (row.get("VSTEL") or "1710").strip(),
            "DUE_DATE":    row.get("WADAT") or "",
            "SALES_ORDER_ITEMS": items,
            "_src_dlv": src_dlv,
            "_src_so":  src_so,
            "_tgt_so":  tgt_so,
        }
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    def call_bapi(self, payload: dict) -> tuple:
        from base_spine_orchestrator import DISP_CREATED
        src_dlv = payload.pop("_src_dlv", "")
        src_so  = payload.pop("_src_so", "")
        tgt_so  = payload.pop("_tgt_so", "")

        resp = self.c.call("BAPI_OUTB_DELIVERY_CREATESLS", **payload)
        ret = resp.get("RETURN") or []
        if isinstance(ret, dict):
            ret_list = [ret] if ret.get("TYPE") else []
        else:
            ret_list = list(ret)
        hard = [m for m in ret_list if m.get("TYPE") in ("E", "A")]
        msgs = [(m.get("MESSAGE") or "").strip() for m in ret_list if m.get("MESSAGE")]
        target = (resp.get("DELIVERY") or "").strip()
        if hard or not target:
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

        if tgt_so != src_so:
            msgs.append(f"SO {src_so} resolved via F1 -> {tgt_so}")
        vk = {"table": "LIKP", "key": {"VBELN": target}}
        return target, msgs, DISP_CREATED, vk
