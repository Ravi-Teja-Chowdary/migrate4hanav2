"""
purchase_contract_spine - PurchaseContract via BAPI_CONTRACT_CREATE.

Object-promotion grind batch 4 / 4. Outline-agreement (ME31K). The tricky
shape: not every purchasing-ready supplier is **contract-capable** (some have
incomplete purchasing data or "faulty items" that fail contract create even
though they accept POs). We TESTRUN-validate the registry vendor first; if
that fails, we scan the ready pool with TESTRUN and cache the winner per
purchasing org.

Source ECC row shape::

    {"EBELN": "<source contract>",
     "LIFNR": "<source vendor>",
     "BSART": "MK"}            # MK = quantity contract, WK = value contract

Org context (PURCH_ORG, PUR_GROUP, PLANT, PO_UNIT, MATL_GROUP, COMP_CODE)
supplied via ``cc_org``. Currency is normalized to the target company code's
local currency (T001.WAERS) to dodge obsolete-currency hard-fails (e.g.
IDES 'DEM' has no exchange rate in modern S/4).

Item is account-assignment 'U' (no material dependency) with nominal qty/
price placeholders — matches the proven legacy pattern.
"""
from __future__ import annotations

import datetime
from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


@register_spine
class PurchaseContractSpineOrchestrator(BaseSpineOrchestrator):
    """PurchaseContract via BAPI_CONTRACT_CREATE with TESTRUN-validated vendor."""

    object_type           = "PurchaseContract"
    source_key_field      = "EBELN"
    extension_structure   = "BAPI_TE_EKKO"
    # Note: vendor resolution is explicit in build_payload (TESTRUN-validated
    # registry-then-scan-then-cache), not via the default resolve_fk.
    fk_fields: dict       = {}

    cc_org: dict = {}

    def __init__(self, *args, cc_org: Optional[dict] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cc_org = dict(cc_org or {})

    def validate(self, row: dict) -> Optional[str]:
        if not (row.get("EBELN") or "").strip():
            return "EBELN is required (source contract number)"
        required = ("PURCH_ORG", "PUR_GROUP", "PLANT", "PO_UNIT",
                    "MATL_GROUP", "COMP_CODE")
        missing = [k for k in required if not (self.cc_org.get(k) or "").strip()]
        if missing:
            return f"cc_org missing: {','.join(missing)}"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        src_doc = (row.get("EBELN") or "").strip()
        src_vendor = (row.get("LIFNR") or "").strip()
        ekorg = self.cc_org["PURCH_ORG"]
        ready = sorted(set(self._ready_suppliers(ekorg)))
        if not ready:
            return {"_no_supplier": True, "_ekorg": ekorg}

        dtype = (row.get("BSART") or "").strip()
        if dtype not in ("MK", "WK"):
            dtype = "MK"

        # Vendor resolution: prefer registry-resolved, else cached known-good, else scan
        tgt_vendor, vdisp = None, "harmonized"
        preferred = self.key_map.resolve("Vendor", src_vendor) if self.key_map is not None else None
        if preferred and preferred in set(ready) and self._contract_vendor_ok(dtype, preferred, src_doc):
            tgt_vendor, vdisp = preferred, "registry"
        else:
            cache = getattr(self, "_contract_vendor_cache", None)
            if cache is None:
                cache = self._contract_vendor_cache = {}
            if ekorg in cache:
                tgt_vendor = cache[ekorg]
            else:
                for v in ready[:15]:
                    if self._contract_vendor_ok(dtype, v, src_doc):
                        tgt_vendor = cache[ekorg] = v
                        break

        if not tgt_vendor:
            return {"_no_capable_vendor": True, "_ekorg": ekorg}

        hdr, hdrx, item, itemx = self._contract_payload(dtype, tgt_vendor, src_doc)
        payload: dict = {
            "HEADER":      hdr,
            "HEADERX":     hdrx,
            "ITEM":        item,
            "ITEMX":       itemx,
            "_src_doc":    src_doc,
            "_src_vendor": src_vendor,
            "_tgt_vendor": tgt_vendor,
            "_vdisp":      vdisp,
        }
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    def call_bapi(self, payload: dict) -> tuple[Optional[str], list, Optional[str]]:
        from base_spine_orchestrator import DISP_CREATED
        if payload.get("_no_supplier"):
            return None, [f"no purchasing-ready supplier for org {payload.get('_ekorg')}"], None
        if payload.get("_no_capable_vendor"):
            return None, [f"no contract-capable supplier in org {payload.get('_ekorg')}"], None

        src_doc    = payload.pop("_src_doc", "")
        src_vendor = payload.pop("_src_vendor", "")
        tgt_vendor = payload.pop("_tgt_vendor", "")
        vdisp      = payload.pop("_vdisp", "registry")

        try:
            resp = self.c.call("BAPI_CONTRACT_CREATE", **payload)
        except Exception as ex:
            try:
                self.c.call("BAPI_TRANSACTION_ROLLBACK")
            except Exception:
                pass
            return None, [f"contract create exception: {str(ex).splitlines()[0]}"], None

        ret = resp.get("RETURN") or []
        if isinstance(ret, dict):
            ret_list = [ret] if ret.get("TYPE") else []
        else:
            ret_list = list(ret)
        hard = [m for m in ret_list if m.get("TYPE") in ("E", "A")]
        msgs = [(m.get("MESSAGE") or "").strip() for m in ret_list if m.get("MESSAGE")]
        target = (resp.get("PURCHASINGDOCUMENT") or "").strip()
        if hard or not target:
            try:
                self.c.call("BAPI_TRANSACTION_ROLLBACK")
            except Exception:
                pass
            return None, msgs, None

        try:
            self.c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception as e:
            msgs.append(f"commit failed: {e}")
            return None, msgs, None

        if vdisp == "harmonized" and self.key_map is not None and src_vendor:
            try:
                self.key_map.add("Vendor", src_vendor, tgt_vendor, "harmonized")
            except Exception:
                pass
            msgs.append(f"vendor {src_vendor} harmonized to {tgt_vendor}")
        return target, msgs, DISP_CREATED

    # ── helpers ──────────────────────────────────────────────────────────────
    def _contract_payload(self, dtype: str, vendor: str, src_doc: str):
        today = datetime.date.today()
        end = today.replace(year=today.year + 1)
        curr = (self._comp_currency(self.cc_org["COMP_CODE"])
                or self.cc_org.get("CURRENCY") or "EUR").strip()
        hdr = {
            "COMP_CODE":   self.cc_org["COMP_CODE"],
            "DOC_TYPE":    dtype,
            "VENDOR":      vendor.zfill(10),
            "PURCH_ORG":   self.cc_org["PURCH_ORG"],
            "PUR_GROUP":   self.cc_org["PUR_GROUP"],
            "CURRENCY":    curr,
            "VPER_START":  today.strftime("%Y%m%d"),
            "VPER_END":    end.strftime("%Y%m%d"),
            "DOC_DATE":    today.strftime("%Y%m%d"),
        }
        hdrx = {k: "X" for k in hdr}
        item = [{
            "ITEM_NO":     "00010",
            "SHORT_TEXT":  f"Migrated contract {src_doc}"[:40],
            "PLANT":       self.cc_org["PLANT"],
            "MATL_GROUP":  self.cc_org["MATL_GROUP"],
            "TARGET_QTY":  "100",
            "PO_UNIT":     self.cc_org["PO_UNIT"],
            "NET_PRICE":   "10",
            "PRICE_UNIT":  "1",
            "ACCTASSCAT":  "U",
        }]
        itemx = [{"ITEM_NO": "00010", "SHORT_TEXT": "X", "PLANT": "X",
                  "MATL_GROUP": "X", "TARGET_QTY": "X", "PO_UNIT": "X",
                  "NET_PRICE": "X", "PRICE_UNIT": "X", "ACCTASSCAT": "X"}]
        return hdr, hdrx, item, itemx

    def _contract_vendor_ok(self, dtype: str, vendor: str, src_doc: str) -> bool:
        hdr, hdrx, item, itemx = self._contract_payload(dtype, vendor, src_doc)
        try:
            resp = self.c.call("BAPI_CONTRACT_CREATE", HEADER=hdr, HEADERX=hdrx,
                                ITEM=item, ITEMX=itemx, TESTRUN="X")
            ret = resp.get("RETURN") or []
            if isinstance(ret, dict):
                ret_list = [ret] if ret.get("TYPE") else []
            else:
                ret_list = list(ret)
            ok = not any(m.get("TYPE") in ("E", "A") for m in ret_list)
        except Exception:
            ok = False
        finally:
            try:
                self.c.call("BAPI_TRANSACTION_ROLLBACK")
            except Exception:
                pass
        return ok

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

    def _comp_currency(self, bukrs: str) -> str:
        cache = getattr(self, "_cc_cache", None)
        if cache is None:
            cache = self._cc_cache = {}
        if bukrs in cache:
            return cache[bukrs]
        curr = ""
        try:
            r = self.c.call(
                "RFC_READ_TABLE", QUERY_TABLE="T001", DELIMITER="|",
                FIELDS=[{"FIELDNAME": "WAERS"}],
                OPTIONS=[{"TEXT": f"BUKRS = '{bukrs}'"}], ROWCOUNT=1,
            )
            data = r.get("DATA") or []
            curr = (data[0].get("WA") or "").strip() if data else ""
        except Exception:
            curr = ""
        cache[bukrs] = curr
        return curr
