"""
planned_order_spine - PP Planned Order via BAPI_PLANNEDORDER_CREATE.

Object-promotion grind batch 8 / 4. Planned order (PLAF) is the MRP output
that gets converted to a production order. F1-resolves the source MATNR
before planning the target plant.

Source ECC PLAF row shape::

    {"PLNUM": "<source planned order number>",
     "MATNR": "<material>",
     "PLWRK": "<production plant>",
     "GSMNG": "<order quantity>",
     "MEINS": "<UoM>",
     "PSTTR": "<planned start>",
     "PEDTR": "<planned end>"}
"""
from __future__ import annotations

import datetime
from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


@register_spine
class PlannedOrderSpineOrchestrator(BaseSpineOrchestrator):
    """PlannedOrder via BAPI_PLANNEDORDER_CREATE."""

    object_type           = "PlannedOrder"
    source_key_field      = "PLNUM"
    extension_structure   = "BAPI_TE_PLAF"
    fk_fields: dict       = {}

    cc_org: dict = {}

    def __init__(self, *args, cc_org: Optional[dict] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cc_org = dict(cc_org or {})

    def validate(self, row: dict) -> Optional[str]:
        if not (row.get("MATNR") or "").strip():
            return "MATNR is required"
        if not (row.get("PLWRK") or self.cc_org.get("PLANT") or "").strip():
            return "PLWRK / cc_org['PLANT'] required"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        src_mat = (row["MATNR"] or "").strip().upper()
        tgt_mat = None
        if self.key_map is not None:
            tgt_mat = self.key_map.resolve("Material", src_mat)
        tgt_mat = tgt_mat or src_mat
        plant = (row.get("PLWRK") or self.cc_org.get("PLANT")).strip()
        qty   = str(row.get("GSMNG") or "1")
        uom   = (row.get("MEINS") or "EA").strip()
        today = datetime.date.today().strftime("%Y%m%d")
        order_type = (row.get("PAART") or self.cc_org.get("ORDER_TYPE", "LA")).strip()

        hdr = {
            "MATERIAL":     tgt_mat,
            "PLANT":        plant,
            "ORDER_TYPE":   order_type,
            "ORDER_QTY":    qty,
            "UNIT_OF_MSR":  uom,
            "PLND_OPEN_DT": row.get("PSTTR") or today,
            "PLND_END_DT":  row.get("PEDTR") or today,
        }

        payload: dict = {
            "PLAF_DATA": hdr,
            "_src_mat":  src_mat,
            "_tgt_mat":  tgt_mat,
        }
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    def call_bapi(self, payload: dict) -> tuple:
        from base_spine_orchestrator import DISP_CREATED
        src_mat = payload.pop("_src_mat", "")
        tgt_mat = payload.pop("_tgt_mat", "")

        resp = self.c.call("BAPI_PLANNEDORDER_CREATE", **payload)
        ret = resp.get("RETURN") or []
        if isinstance(ret, dict):
            ret_list = [ret] if ret.get("TYPE") else []
        else:
            ret_list = list(ret)
        hard = [m for m in ret_list if m.get("TYPE") in ("E", "A")]
        msgs = [(m.get("MESSAGE") or "").strip() for m in ret_list if m.get("MESSAGE")]
        target = (resp.get("PLANNEDORDER") or "").strip()
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

        if tgt_mat != src_mat:
            msgs.append(f"material {src_mat} resolved via F1 -> {tgt_mat}")
        vk = {"table": "PLAF", "key": {"PLNUM": target}}
        return target, msgs, DISP_CREATED, vk
