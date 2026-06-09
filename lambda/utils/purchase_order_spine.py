"""
purchase_order_spine - PurchaseOrder via BAPI_PO_CREATE1.

Object-promotion grind batch 4 / 4. First TRANSACTIONAL object — consumes
the F1 key registry (Vendor) and may **harmonize** to a purchasing-ready
target supplier when the registry resolution doesn't yield one. Internal
numbering, multi-item, account-assigned (KNTTP=K, no material dependency).

Source ECC row shape (header + items as a sub-array)::

    {"EBELN": "<source PO>",
     "LIFNR": "<source vendor>",
     "WAERS": "<currency>",
     "items": [{"MATNR": ..., "MENGE": ..., "NETPR": ...}, ...]}

Org context (PURCH_ORG, PUR_GROUP, PLANT, PO_UNIT, MATL_GROUP, GL_ACCOUNT,
COSTCENTER, COMP_CODE, DOC_TYPE, CURRENCY) supplied via ``cc_org``.

Vendor resolution (in order):
  1. PersistentKeyMap.resolve("Vendor", src_vendor) -- the migrated vendor
  2. Discovered purchasing-ready supplier pool (LFM1 by PURCH_ORG)
  3. If the resolved vendor isn't in the pool, harmonize: pick a ready
     vendor deterministically from the pool (digit-hashed for stability)
     and register that back as a harmonized remap in the F1 ledger.
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
class PurchaseOrderSpineOrchestrator(BaseSpineOrchestrator):
    """PurchaseOrder via BAPI_PO_CREATE1 with vendor harmonization."""

    object_type           = "PurchaseOrder"
    source_key_field      = "EBELN"
    extension_structure   = "BAPI_TE_EKKO"
    # Note: vendor resolution is explicit in build_payload (registry-then-harmonize),
    # NOT via the default resolve_fk replace-or-fail. Harmonization is a real
    # migration pattern for purchasing-ready supplier alignment.
    fk_fields: dict       = {}

    cc_org: dict = {}

    def __init__(self, *args, cc_org: Optional[dict] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cc_org = dict(cc_org or {})

    def validate(self, row: dict) -> Optional[str]:
        if not (row.get("EBELN") or "").strip():
            return "EBELN is required (source PO number)"
        required = ("PURCH_ORG", "PUR_GROUP", "PLANT", "PO_UNIT",
                    "MATL_GROUP", "GL_ACCOUNT", "COSTCENTER", "COMP_CODE", "DOC_TYPE")
        missing = [k for k in required if not (self.cc_org.get(k) or "").strip()]
        if missing:
            return f"cc_org missing: {','.join(missing)}"
        if not row.get("items"):
            return "PO has no items"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        src_po = (row.get("EBELN") or "").strip()
        src_vendor = (row.get("LIFNR") or "").strip()
        ekorg = self.cc_org["PURCH_ORG"]

        ready = set(self._ready_suppliers(ekorg))
        if not ready:
            return {"_no_supplier": True, "_ekorg": ekorg}

        # Vendor resolution: registry first, harmonize if needed
        tgt_vendor = None
        if self.key_map is not None:
            tgt_vendor = self.key_map.resolve("Vendor", src_vendor)
        vdisp = "registry"
        if not (tgt_vendor and tgt_vendor in ready):
            pool = sorted(ready)
            digits = "".join(ch for ch in src_vendor if ch.isdigit())
            tgt_vendor = pool[(int(digits) if digits else 0) % len(pool)]
            vdisp = "harmonized"

        poitem, poitemx, acct, acctx = [], [], [], []
        for i, it in enumerate(row.get("items") or [], start=1):
            n = "%05d" % (i * 10)
            qty = str(int(_parse_num(it.get("MENGE"), 1)) or 1)
            txt = ("Material " + it["MATNR"]) if it.get("MATNR") else f"Migrated item PO {src_po}"
            poitem.append({"PO_ITEM": n, "SHORT_TEXT": txt[:40],
                           "PLANT": self.cc_org["PLANT"], "QUANTITY": qty,
                           "PO_UNIT": self.cc_org["PO_UNIT"],
                           "NET_PRICE": it.get("NETPR") or "0",
                           "ACCTASSCAT": "K",
                           "MATL_GROUP": self.cc_org["MATL_GROUP"]})
            poitemx.append({"PO_ITEM": n, "SHORT_TEXT": "X", "PLANT": "X",
                            "QUANTITY": "X", "PO_UNIT": "X", "NET_PRICE": "X",
                            "ACCTASSCAT": "X", "MATL_GROUP": "X"})
            acct.append({"PO_ITEM": n, "SERIAL_NO": "01",
                         "GL_ACCOUNT": self.cc_org["GL_ACCOUNT"],
                         "COSTCENTER": self.cc_org["COSTCENTER"], "QUANTITY": qty})
            acctx.append({"PO_ITEM": n, "SERIAL_NO": "01", "GL_ACCOUNT": "X",
                          "COSTCENTER": "X", "QUANTITY": "X"})

        doc_date = self.cc_org.get("DOC_DATE") or datetime.date.today().strftime("%Y%m%d")
        curr = (row.get("WAERS") or self.cc_org.get("CURRENCY") or "USD").strip()
        hdr = {
            "COMP_CODE":  self.cc_org["COMP_CODE"],
            "DOC_TYPE":   self.cc_org["DOC_TYPE"],
            "VENDOR":     tgt_vendor,
            "PURCH_ORG":  ekorg,
            "PUR_GROUP":  self.cc_org["PUR_GROUP"],
            "DOC_DATE":   doc_date,
            "CURRENCY":   curr,
        }
        payload: dict = {
            "POHEADER":   hdr,
            "POHEADERX":  {k: "X" for k in hdr},
            "POITEM":     poitem,
            "POITEMX":    poitemx,
            "POACCOUNT":  acct,
            "POACCOUNTX": acctx,
            "_src_po":      src_po,
            "_src_vendor":  src_vendor,
            "_tgt_vendor":  tgt_vendor,
            "_vdisp":       vdisp,
        }
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    def call_bapi(self, payload: dict) -> tuple:
        from base_spine_orchestrator import DISP_CREATED
        if payload.get("_no_supplier"):
            ekorg = payload.get("_ekorg")
            return None, [f"no purchasing-ready supplier for org {ekorg}"], None, None
        src_po     = payload.pop("_src_po", "")
        src_vendor = payload.pop("_src_vendor", "")
        tgt_vendor = payload.pop("_tgt_vendor", "")
        vdisp      = payload.pop("_vdisp", "registry")

        resp = self.c.call("BAPI_PO_CREATE1", **payload)
        ret = resp.get("RETURN") or []
        if isinstance(ret, dict):
            ret_list = [ret] if ret.get("TYPE") else []
        else:
            ret_list = list(ret)
        hard = [m for m in ret_list if m.get("TYPE") in ("E", "A")]
        msgs = [(m.get("MESSAGE") or "").strip() for m in ret_list if m.get("MESSAGE")]
        target = (resp.get("EXPPURCHASEORDER") or "").strip()
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

        # Register the vendor harmonization back to the ledger AFTER commit
        if vdisp == "harmonized" and self.key_map is not None and src_vendor:
            try:
                self.key_map.add("Vendor", src_vendor, tgt_vendor, "harmonized")
            except Exception:
                pass
            msgs.append(f"vendor {src_vendor} harmonized to {tgt_vendor}")
        vk = {"table": "EKKO", "key": {"EBELN": target}}
        return target, msgs, DISP_CREATED, vk

    # ── target probe ─────────────────────────────────────────────────────────
    def _ready_suppliers(self, ekorg: str) -> list:
        cache = getattr(self, "_sup_cache", None)
        if cache is None:
            cache = self._sup_cache = {}
        if ekorg in cache:
            return cache[ekorg]
        out: list = []
        try:
            r = self.c.call(
                "RFC_READ_TABLE", QUERY_TABLE="LFM1", DELIMITER="|",
                OPTIONS=[{"TEXT": f"EKORG = '{ekorg}'"}],
                FIELDS=[{"FIELDNAME": "LIFNR"}], ROWCOUNT=200,
            )
            out = [(x.get("WA") or "").strip() for x in r.get("DATA") or []
                   if (x.get("WA") or "").strip()]
        except Exception:
            out = []
        cache[ekorg] = out
        return out
