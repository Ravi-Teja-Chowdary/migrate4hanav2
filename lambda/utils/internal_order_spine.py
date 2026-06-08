"""
internal_order_spine - InternalOrder via BAPI_INTERNALORDER_CREATE.

Object-promotion grind batch 2 / 4. Internal-numbering pattern with two-pass
order-type validation: source AUFNR is informational; SAP assigns the target
ORDERID. When the source order type isn't valid in the target controlling area,
we fall back to the discovered default order type and record the substitution.

Source ECC AUFK row shape::

    {"AUFNR": "<source order>",
     "AUART": "<order type>",     # e.g. "0100" in ECC
     "KTEXT": "<short text>",
     "BUKRS": "<company code>",   # FK -> CompanyCode key_map
     "PRCTR": "<profit center>"}  # FK -> ProfitCenter key_map (optional)

Org context (CO_AREA + COMP_CODE + CURRENCY + PROFIT_CTR + ORDER_TYPE
fallback) supplied via ``cc_org`` dict.
"""
from __future__ import annotations

from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


@register_spine
class InternalOrderSpineOrchestrator(BaseSpineOrchestrator):
    """InternalOrder via BAPI_INTERNALORDER_CREATE.

    Internal numbering: source AUFNR -> SAP-assigned target ORDERID.
    Order-type fallback: if source AUART isn't valid in the target CO area,
    use the discovered default and surface the remap in messages.
    """

    object_type           = "InternalOrder"
    source_key_field      = "AUFNR"
    extension_structure   = "BAPI_TE_AUFK"
    fk_fields: dict       = {"BUKRS": "CompanyCode", "PRCTR": "ProfitCenter"}

    cc_org: dict = {}

    def __init__(self, *args, cc_org: Optional[dict] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cc_org = dict(cc_org or {})

    def validate(self, row: dict) -> Optional[str]:
        if not (self.cc_org.get("CO_AREA") or row.get("KOKRS")):
            return "CO_AREA missing"
        if not ((row.get("AUART") or "").strip() or self.cc_org.get("ORDER_TYPE")):
            return "AUART or fallback ORDER_TYPE required"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        aufnr = (row.get("AUFNR") or "").strip()
        kokrs = (self.cc_org.get("CO_AREA") or row.get("KOKRS") or "").strip()
        src_otype = (row.get("AUART") or self.cc_org.get("ORDER_TYPE") or "").strip()
        fallback_otype = (self.cc_org.get("ORDER_TYPE") or "").strip()
        comp = (self.cc_org.get("COMP_CODE") or row.get("BUKRS") or "").strip()
        curr = (self.cc_org.get("CURRENCY") or "USD").strip()
        prctr = (self.cc_org.get("PROFIT_CTR") or row.get("PRCTR") or "").strip()

        # Order-type validation gate (cached on the connection)
        otype, ot_remapped = src_otype, False
        if fallback_otype and src_otype != fallback_otype:
            if not self._order_type_valid(kokrs, src_otype, comp, curr, prctr):
                otype, ot_remapped = fallback_otype, True
        name = ((row.get("KTEXT") or f"IO {aufnr or otype}").strip())[:40]

        payload = {
            "I_MASTER_DATA": {
                "ORDER_TYPE":  otype,
                "CO_AREA":     kokrs,
                "ORDER_NAME":  name,
                "COMP_CODE":   comp,
                "CURRENCY":    curr,
                "PROFIT_CTR":  prctr,
            },
            "_ot_remapped": ot_remapped,
            "_src_ot":      src_otype,
            "_used_ot":     otype,
        }
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    def call_bapi(self, payload: dict) -> tuple[Optional[str], list, Optional[str]]:
        from base_spine_orchestrator import DISP_CREATED, DISP_REMAPPED
        ot_remapped = payload.pop("_ot_remapped", False)
        src_ot      = payload.pop("_src_ot", "")
        used_ot     = payload.pop("_used_ot", "")

        resp = self.c.call("BAPI_INTERNALORDER_CREATE", **payload)
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
            return None, msgs, None

        target = (resp.get("ORDERID")
                  or (resp.get("E_MASTER_DATA") or {}).get("ORDER")
                  or "").strip()
        try:
            self.c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception as e:
            msgs.append(f"commit failed: {e}")
            return None, msgs, None

        if ot_remapped:
            msgs.append(f"order type {src_ot} not valid; used {used_ot}")
        if not target:
            return None, msgs, None
        # Order numbers are SAP-assigned -> CREATED disposition
        return target, msgs, DISP_CREATED

    def _order_type_valid(self, kokrs, otype, comp, curr, prctr) -> bool:
        """TESTRUN-based order-type validation (cached on the orchestrator)."""
        cache = getattr(self, "_ot_cache", None)
        if cache is None:
            cache = self._ot_cache = {}
        key = (kokrs, otype, comp, curr, prctr)
        if key in cache:
            return cache[key]
        ok = False
        try:
            resp = self.c.call("BAPI_INTERNALORDER_CREATE", TESTRUN="X",
                                I_MASTER_DATA={"ORDER_TYPE": otype, "CO_AREA": kokrs,
                                                "ORDER_NAME": "M4H_PROBE",
                                                "COMP_CODE": comp, "CURRENCY": curr,
                                                "PROFIT_CTR": prctr})
            ret = resp.get("RETURN") or []
            if isinstance(ret, dict):
                ret_list = [ret] if ret.get("TYPE") else []
            else:
                ret_list = list(ret)
            ok = not any(m.get("TYPE") in ("E", "A") for m in ret_list)
        except Exception:
            ok = False
        cache[key] = ok
        return ok
