"""
work_center_spine - PP WorkCenter via BAPI_WORKCENTER_CREATE.

Object-promotion grind batch 7 / 4 (first beyond live-25). Work center (CRHD)
is the production-planning capacity master used in routings, BOMs, and
production orders.

Source ECC CRHD row shape::

    {"ARBPL":  "<work-center key>",   # 8-char identifier
     "WERKS":  "<plant>",             # owner plant
     "VERWE":  "0001",                # usage code (0001 = routing+order)
     "KTEXT":  "<description>"}

The plant (WERKS) is required and must exist in target T001W; the work-
center category (KAPA / VERWE) is from customizing. Uses internal numbering
when source ARBPL collides with target; preserves ARBPL otherwise.
"""
from __future__ import annotations

from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


@register_spine
class WorkCenterSpineOrchestrator(BaseSpineOrchestrator):
    """WorkCenter via BAPI_WORKCENTER_CREATE -- PP capacity master."""

    object_type           = "WorkCenter"
    source_key_field      = "ARBPL"
    extension_structure   = "BAPI_TE_CRHD"
    fk_fields: dict       = {}

    cc_org: dict = {}

    def __init__(self, *args, cc_org: Optional[dict] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cc_org = dict(cc_org or {})

    def validate(self, row: dict) -> Optional[str]:
        if not (row.get("ARBPL") or "").strip():
            return "ARBPL is required (work center key)"
        if not (row.get("WERKS") or self.cc_org.get("PLANT") or "").strip():
            return "WERKS / cc_org['PLANT'] required"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        arbpl = (row["ARBPL"] or "").strip().upper()
        werks = (row.get("WERKS") or self.cc_org.get("PLANT") or "").strip()
        verwe = (row.get("VERWE") or self.cc_org.get("USAGE", "0001")).strip()
        ktext = ((row.get("KTEXT") or f"Work center {arbpl}").strip())[:40]
        kapa  = (row.get("KAPA") or self.cc_org.get("CAPACITY_CAT", "001")).strip()

        # Pre-flight idempotency
        already = self._wc_exists(arbpl, werks)
        payload: dict = {
            "WORKCENTER_KEY": {"PLANT": werks, "WORK_CENTER": arbpl},
            "BASIC_DATA":     {"DESCRIPTION": ktext,
                                "USAGE_CATEGORY": verwe,
                                "CAPACITY_CAT": kapa},
            "_arbpl":         arbpl,
            "_werks":         werks,
            "_already":       already,
        }
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    def call_bapi(self, payload: dict) -> tuple:
        from base_spine_orchestrator import DISP_CREATED, DISP_MATCHED_EXISTING
        arbpl   = payload.pop("_arbpl", "")
        werks   = payload.pop("_werks", "")
        already = payload.pop("_already", False)
        vk = {"table": "CRHD", "key": {"OBJID_TYP": "A", "OBJID": arbpl,
                                         "WERKS": werks}}

        if already:
            return arbpl, [f"work center {arbpl}/{werks} already exists"], DISP_MATCHED_EXISTING, vk

        resp = self.c.call("BAPI_WORKCENTER_CREATE", **payload)
        ret = resp.get("RETURN") or []
        if isinstance(ret, dict):
            ret_list = [ret] if ret.get("TYPE") else []
        else:
            ret_list = list(ret)
        hard = [m for m in ret_list if m.get("TYPE") in ("E", "A")]
        msgs = [(m.get("MESSAGE") or "").strip() for m in ret_list if m.get("MESSAGE")]
        if hard:
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
        return arbpl, msgs, DISP_CREATED, vk

    def _wc_exists(self, arbpl: str, werks: str) -> bool:
        try:
            r = self.c.call(
                "RFC_READ_TABLE", QUERY_TABLE="CRHD", DELIMITER="|",
                FIELDS=[{"FIELDNAME": "OBJID"}],
                OPTIONS=[{"TEXT": f"WERKS = '{werks}' AND ARBPL = '{arbpl}'"}],
                ROWCOUNT=1,
            )
            return bool(r.get("DATA"))
        except Exception:
            return False
