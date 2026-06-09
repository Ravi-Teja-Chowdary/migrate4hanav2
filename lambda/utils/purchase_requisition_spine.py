"""
purchase_requisition_spine - PurchaseRequisition via BAPI_REQUISITION_CREATE.

Object-promotion grind batch 4 / 4 (first of the transactional-document set).
The PR is the simplest open-MM doc — single account-assigned item, internal
numbering. Source BANFN is informational; the BAPI assigns the target PR
number which we capture and register in the F1 ledger.

Source ECC row shape::

    {"BANFN": "<source PR number>",
     "TXZ01": "<short text>",
     "MENGE": "<quantity>",
     "PREIS": "<valuation price>"}

Org context (PUR_GROUP, PLANT, PO_UNIT, MATL_GROUP, GL_ACCOUNT, COSTCENTER,
DOC_TYPE default "NB") supplied via ``cc_org``.

Account-assigned (KNTTP=K) with C_AMT_BAPI mandatory for valuation. No
material-master dependency — mirrors the PO loader pattern.
"""
from __future__ import annotations

import datetime
from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


def _parse_num(val, default=0):
    try:
        s = str(val or "").strip().replace(",", "")
        return float(s) if s else float(default)
    except Exception:
        return float(default)


@register_spine
class PurchaseRequisitionSpineOrchestrator(BaseSpineOrchestrator):
    """PurchaseRequisition via BAPI_REQUISITION_CREATE.

    Internal numbering -> SAP-assigned target PR. Source BANFN preserved as
    source_key for ledger; target captured from BAPI response NUMBER.
    """

    object_type           = "PurchaseRequisition"
    source_key_field      = "BANFN"
    extension_structure   = "BAPI_TE_EBAN"
    fk_fields: dict       = {}

    cc_org: dict = {}

    def __init__(self, *args, cc_org: Optional[dict] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cc_org = dict(cc_org or {})

    def validate(self, row: dict) -> Optional[str]:
        if not (row.get("BANFN") or "").strip():
            return "BANFN is required (source PR number)"
        required_org = ("PUR_GROUP", "PLANT", "PO_UNIT", "MATL_GROUP",
                        "GL_ACCOUNT", "COSTCENTER")
        missing = [k for k in required_org if not (self.cc_org.get(k) or "").strip()]
        if missing:
            return f"cc_org missing: {','.join(missing)}"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        src_pr = (row.get("BANFN") or "").strip()
        qty = str(int(_parse_num(row.get("MENGE"), 1)) or 1)
        price = _parse_num(row.get("PREIS"), 0)
        c_amt = ("%.2f" % price) if price else "100.00"
        txt = ((row.get("TXZ01") or f"Migrated PR {src_pr or 'item'}").strip())[:40]
        deliv = (datetime.date.today() + datetime.timedelta(days=30)).strftime("%Y%m%d")

        item = [{
            "PREQ_ITEM":  "00010",
            "DOC_TYPE":   self.cc_org.get("DOC_TYPE", "NB"),
            "PUR_GROUP":  self.cc_org["PUR_GROUP"],
            "SHORT_TEXT": txt,
            "PLANT":      self.cc_org["PLANT"],
            "QUANTITY":   qty,
            "UNIT":       self.cc_org["PO_UNIT"],
            "DELIV_DATE": deliv,
            "MAT_GRP":    self.cc_org["MATL_GROUP"],
            "ACCTASSCAT": "K",
            "C_AMT_BAPI": c_amt,
            "PRICE_UNIT": "1",
        }]
        acc = [{
            "PREQ_ITEM": "00010",
            "SERIAL_NO": "01",
            "G_L_ACCT":  self.cc_org["GL_ACCOUNT"],
            "COST_CTR":  self.cc_org["COSTCENTER"],
        }]
        payload: dict = {
            "REQUISITION_ITEMS":               item,
            "REQUISITION_ACCOUNT_ASSIGNMENT":  acc,
            "_src_pr":                         src_pr,
        }
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    def call_bapi(self, payload: dict) -> tuple:
        from base_spine_orchestrator import DISP_CREATED
        payload.pop("_src_pr", None)

        resp = self.c.call("BAPI_REQUISITION_CREATE", **payload)
        ret = resp.get("RETURN") or []
        if isinstance(ret, dict):
            ret_list = [ret] if ret.get("TYPE") else []
        else:
            ret_list = list(ret)
        hard = [m for m in ret_list if m.get("TYPE") in ("E", "A")]
        msgs = [(m.get("MESSAGE") or "").strip() for m in ret_list if m.get("MESSAGE")]
        target = (resp.get("NUMBER") or "").strip()
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
        vk = {"table": "EBAN", "key": {"BANFN": target}}
        return target, msgs, DISP_CREATED, vk
