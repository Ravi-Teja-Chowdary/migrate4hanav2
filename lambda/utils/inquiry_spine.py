"""
inquiry_spine - SD Customer Inquiry via BAPI_INQUIRY_CREATEFROMDATA.

Object-promotion grind batch 8 / 4. Customer inquiry (VBAK with VBTYP='A').
Pre-sales document, mirrors Quotation shape but with INQUIRY-specific BAPI
and DOC_TYPE='AF'.
"""
from __future__ import annotations

from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


@register_spine
class InquirySpineOrchestrator(BaseSpineOrchestrator):
    """Inquiry via BAPI_INQUIRY_CREATEFROMDATA."""

    object_type           = "Inquiry"
    source_key_field      = "VBELN"
    extension_structure   = "BAPI_TE_VBAK"
    fk_fields: dict       = {}

    def validate(self, row: dict) -> Optional[str]:
        if not (row.get("VBELN") or "").strip():
            return "VBELN is required (source inquiry)"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        cfg = self._sales_config()
        if not cfg:
            return {"_no_sales_area": True}

        src_doc = (row["VBELN"] or "").strip()
        src_cust = (row.get("KUNNR") or "").strip()
        tgt_cust = None
        if self.key_map is not None:
            tgt_cust = self.key_map.resolve("Customer", src_cust)
        cdisp = "registry"
        if not (tgt_cust and tgt_cust in cfg["customers"]):
            tgt_cust = cfg["sample_customer"]
            cdisp = "harmonized"

        hdr = {
            "DOC_TYPE":   "AF",      # standard inquiry
            "SALES_ORG":  cfg["sorg"],
            "DISTR_CHAN": cfg["chan"],
            "DIVISION":   cfg["div"],
        }
        partners = [{"PARTN_ROLE": "AG", "PARTN_NUMB": tgt_cust.zfill(10)}]
        items = [{"ITM_NUMBER": "000010", "MATERIAL": cfg["sample_material"],
                   "TARGET_QTY": "1", "TARGET_QU": "EA"}]

        payload: dict = {
            "INQUIRY_HEADER_IN":  hdr,
            "INQUIRY_PARTNERS":   partners,
            "INQUIRY_ITEMS_IN":   items,
            "_src_doc":  src_doc,
            "_src_cust": src_cust,
            "_tgt_cust": tgt_cust,
            "_cdisp":    cdisp,
        }
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    def call_bapi(self, payload: dict) -> tuple:
        from base_spine_orchestrator import DISP_CREATED
        if payload.get("_no_sales_area"):
            return None, ["no coherent target sales area discovered"], None, None

        src_cust = payload.pop("_src_cust", "")
        tgt_cust = payload.pop("_tgt_cust", "")
        cdisp    = payload.pop("_cdisp", "registry")
        payload.pop("_src_doc", None)

        resp = self.c.call("BAPI_INQUIRY_CREATEFROMDATA", **payload)
        ret = resp.get("RETURN") or []
        if isinstance(ret, dict):
            ret_list = [ret] if ret.get("TYPE") else []
        else:
            ret_list = list(ret)
        hard = [m for m in ret_list if m.get("TYPE") in ("E", "A")]
        msgs = [(m.get("MESSAGE") or "").strip() for m in ret_list if m.get("MESSAGE")]
        target = (resp.get("SALESDOCUMENT") or "").strip()
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

        if cdisp == "harmonized" and self.key_map is not None and src_cust:
            try:
                self.key_map.add("Customer", src_cust, tgt_cust, "harmonized")
            except Exception:
                pass
            msgs.append(f"customer {src_cust} harmonized to {tgt_cust}")
        vk = {"table": "VBAK", "key": {"VBELN": target}}
        return target, msgs, DISP_CREATED, vk

    def _sales_config(self):
        cache = getattr(self, "_sa_cache", None)
        if cache is not None:
            return cache
        cfg = None
        try:
            kn = self.c.call(
                "RFC_READ_TABLE", QUERY_TABLE="KNVV", DELIMITER="|",
                FIELDS=[{"FIELDNAME": "KUNNR"}, {"FIELDNAME": "VKORG"},
                        {"FIELDNAME": "VTWEG"}, {"FIELDNAME": "SPART"}],
                ROWCOUNT=2000)
            mv = self.c.call(
                "RFC_READ_TABLE", QUERY_TABLE="MVKE", DELIMITER="|",
                FIELDS=[{"FIELDNAME": "MATNR"}, {"FIELDNAME": "VKORG"},
                        {"FIELDNAME": "VTWEG"}],
                ROWCOUNT=3000)
            custs, mats = {}, {}
            for x in kn.get("DATA", []):
                parts = (x.get("WA") or "").split("|") + ["", "", "", ""]
                ku, vk, vt, sp = (p.strip() for p in parts[:4])
                if ku and vk:
                    custs.setdefault((vk, vt, sp), []).append(ku)
            for x in mv.get("DATA", []):
                parts = (x.get("WA") or "").split("|") + ["", "", ""]
                ma, vk, vt = (p.strip() for p in parts[:3])
                if ma and vk:
                    mats.setdefault((vk, vt), []).append(ma)
            for (vk, vt, sp), cl in custs.items():
                if (vk, vt) in mats and cl and mats[(vk, vt)]:
                    cfg = {"sorg": vk, "chan": vt, "div": sp,
                            "customers": set(cl), "sample_customer": cl[0],
                            "sample_material": mats[(vk, vt)][0]}
                    break
        except Exception:
            pass
        self._sa_cache = cfg
        return cfg
