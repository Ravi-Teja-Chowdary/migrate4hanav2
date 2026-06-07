"""
cost_center_spine - CostCenter via BAPI_COSTCENTER_CREATEMULTIPLE.

Object-promotion grind batch 1 / 4. Composite-key master with multi-FK
dependency on CompanyCode + ProfitCenter + Currency.

Source ECC CSKS row shape::

    {"KOKRS": "<controlling area>",   # e.g. "1710"
     "KOSTL": "<cost center>",        # e.g. "0017101601"
     "DATBI": "99991231",
     "KTEXT": "<short text>",
     "VERAK": "<person in charge>",
     "BUKRS": "<company code>",       # FK -> CompanyCode key_map registry
     "WAERS": "<currency>",
     "PRCTR": "<profit center>"}      # FK -> ProfitCenter key_map registry

Org context (CC_CATEGORY, CC_HIER, COMP_CODE, CURRENCY) supplied via the
``cc_org`` dict the caller attaches. Mirrors the existing bapi_loader pattern
so the spine subclass is a drop-in replacement.
"""
from __future__ import annotations

from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


@register_spine
class CostCenterSpineOrchestrator(BaseSpineOrchestrator):
    """CostCenter via BAPI_COSTCENTER_CREATEMULTIPLE. Composite key (KOKRS, KOSTL).

    BAPI takes a single-row list; we always send count=1 and read the response's
    DETAIL_RETURN for the per-row outcome. Two-pass error mapping: if the BAPI
    returns hard errors, we surface the BAPIRET2 message verbatim so DQ + dead-
    letter routing can act on it.
    """

    object_type           = "CostCenter"
    source_key_field      = "KOSTL"
    extension_structure   = "BAPI_TE_CSKS"
    # CO-CCA cost centers FK to CompanyCode (via BUKRS) and ProfitCenter (via PRCTR).
    fk_fields: dict       = {"BUKRS": "CompanyCode", "PRCTR": "ProfitCenter"}

    # Org context - mirrors UnifiedLoader.cc_org for parity with the legacy path.
    cc_org: dict = {}

    def __init__(self, *args, cc_org: Optional[dict] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cc_org = dict(cc_org or {})

    # ── validation ───────────────────────────────────────────────────────────
    def validate(self, row: dict) -> Optional[str]:
        kostl = (row.get("KOSTL") or "").strip()
        if not kostl:
            return "KOSTL is required"
        if not (self.cc_org.get("CO_AREA") or row.get("KOKRS")):
            return "CO_AREA missing - configure controlling area or pass KOKRS"
        # Org context check - we tolerate missing values since the BAPI itself rejects them
        return None

    # ── BAPI payload ─────────────────────────────────────────────────────────
    def build_payload(self, row: dict, ext_rows: list) -> dict:
        kostl = (row["KOSTL"] or "").strip()
        kokrs = (self.cc_org.get("CO_AREA") or row.get("KOKRS") or "").strip()
        comp_code = (self.cc_org.get("COMP_CODE") or row.get("BUKRS") or "").strip()
        cat   = (self.cc_org.get("CC_CATEGORY") or row.get("KOSAR") or "1").strip()
        hier  = (self.cc_org.get("CC_HIER") or row.get("KHINR") or "").strip()
        currency = (self.cc_org.get("CURRENCY") or row.get("WAERS") or "USD").strip()
        prctr = (self.cc_org.get("PROFIT_CTR") or row.get("PRCTR") or "").strip()
        valid_from = (self.cc_org.get("VALID_FROM") or row.get("DATAB") or "20240101")
        valid_to   = (row.get("DATBI") or "99991231")
        short = ((row.get("KTEXT") or f"CC {kostl}").strip() or kostl)[:20]
        verak = (row.get("VERAK") or "M4H").strip()[:20]

        cc: dict = {
            "COSTCENTER":        kostl,
            "VALID_FROM":        valid_from,
            "VALID_TO":          valid_to,
            "PERSON_IN_CHARGE":  verak,
            "COSTCENTER_TYPE":   cat,
            "COSTCTR_HIER_GRP":  hier,
            "COMP_CODE":         comp_code,
            "CURRENCY":          currency,
            "PROFIT_CTR":        prctr,
            "NAME":              short,
            "DESCRIPT":          short,
        }
        payload = {
            "CONTROLLINGAREA": kokrs,
            "COSTCENTERLIST":  [cc],
        }
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    # ── BAPI invocation ──────────────────────────────────────────────────────
    def call_bapi(self, payload: dict) -> tuple[Optional[str], list]:
        from base_spine_orchestrator import DISP_MATCHED_EXISTING
        kokrs = payload["CONTROLLINGAREA"]
        kostl = payload["COSTCENTERLIST"][0]["COSTCENTER"]
        if self._cost_center_exists(kokrs, kostl):
            return kostl, [f"cost center {kostl} already exists in {kokrs}"], DISP_MATCHED_EXISTING

        resp = self.c.call("BAPI_COSTCENTER_CREATEMULTIPLE", **payload)
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
            return None, msgs
        try:
            self.c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception as e:
            msgs.append(f"commit failed: {e}")
            return None, msgs
        return kostl, msgs

    # ── target probe ─────────────────────────────────────────────────────────
    def _cost_center_exists(self, kokrs: str, kostl: str) -> bool:
        try:
            r = self.c.call(
                "RFC_READ_TABLE",
                QUERY_TABLE="CSKS",
                DELIMITER="|",
                OPTIONS=[{"TEXT": f"KOKRS = '{kokrs}' AND KOSTL = '{kostl}'"}],
                FIELDS=[{"FIELDNAME": "KOSTL"}],
                ROWCOUNT=1,
            )
            return bool(r.get("DATA"))
        except Exception:
            return False
