"""
info_record_spine - MM Purchasing InfoRecord via BAPI_INFORECORD_CREATE.

Object-promotion grind batch 7 / 4. Purchasing info record (EINA/EINE)
links a (material, vendor, plant) tuple to pricing and lead-time data.
Most ECC->S/4 migrations need this rebuilt because:

  - The vendor side may have been harmonized via F1 (Vendor spine ran)
  - The material side may have been remapped (Material spine ran)
  - The plant org may differ between source and target

We F1-resolve both Vendor (LIFNR) and Material (MATNR) before sending,
falling back to the source key if unresolved (the BAPI then errors and
the row dead-letters cleanly).

Source ECC EINA/EINE row shape::

    {"MATNR": "<source material>",
     "LIFNR": "<source vendor>",
     "EKORG": "<purchasing org>",
     "ESOKZ": "0",                   # 0 = standard, 1 = subcontracting, ...
     "NETPR": "<net price>",
     "PEINH": "1",                   # price unit
     "BPRME": "<order unit>"}
"""
from __future__ import annotations

from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


@register_spine
class InfoRecordSpineOrchestrator(BaseSpineOrchestrator):
    """InfoRecord via BAPI_INFORECORD_CREATE with vendor + material F1 resolution."""

    object_type           = "InfoRecord"
    source_key_field      = "INFNR"
    extension_structure   = "BAPI_TE_EINA"
    fk_fields: dict       = {}    # explicit resolution in build_payload

    cc_org: dict = {}

    def __init__(self, *args, cc_org: Optional[dict] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cc_org = dict(cc_org or {})

    def validate(self, row: dict) -> Optional[str]:
        if not (row.get("MATNR") or "").strip():
            return "MATNR is required (source material)"
        if not (row.get("LIFNR") or "").strip():
            return "LIFNR is required (source vendor)"
        if not (self.cc_org.get("PURCH_ORG") or row.get("EKORG") or "").strip():
            return "EKORG / cc_org['PURCH_ORG'] required"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        src_mat    = (row["MATNR"] or "").strip().upper()
        src_vendor = (row["LIFNR"] or "").strip()
        ekorg = (self.cc_org.get("PURCH_ORG") or row.get("EKORG") or "").strip()
        esokz = (row.get("ESOKZ") or "0").strip()
        netpr = str(row.get("NETPR") or "0")
        peinh = str(row.get("PEINH") or "1")
        bprme = (row.get("BPRME") or self.cc_org.get("PO_UNIT", "EA")).strip()

        tgt_mat    = None
        tgt_vendor = None
        if self.key_map is not None:
            tgt_mat    = self.key_map.resolve("Material", src_mat)
            tgt_vendor = self.key_map.resolve("Vendor",   src_vendor)
        tgt_mat    = tgt_mat or src_mat
        tgt_vendor = (tgt_vendor or src_vendor).zfill(10)

        gen = {
            "MATERIAL":     tgt_mat,
            "VENDOR":       tgt_vendor,
            "PURCH_ORG":    ekorg,
            "INFO_CATEGORY": esokz,
        }
        org = {"PURCH_ORG": ekorg,
                "VENDOR_NO": tgt_vendor,
                "MATERIAL":  tgt_mat,
                "CURRENCY":  (row.get("WAERS") or self.cc_org.get("CURRENCY", "USD")).strip(),
                "NET_PRICE": netpr,
                "PRICE_UNIT": peinh,
                "ORDER_UNIT": bprme}

        payload: dict = {
            "GENERAL_DATA":      gen,
            "PURCHORG_DATA":     org,
            "_src_mat":          src_mat,
            "_tgt_mat":          tgt_mat,
            "_src_vendor":       src_vendor,
            "_tgt_vendor":       tgt_vendor,
        }
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    def call_bapi(self, payload: dict) -> tuple:
        from base_spine_orchestrator import DISP_CREATED
        src_mat    = payload.pop("_src_mat", "")
        tgt_mat    = payload.pop("_tgt_mat", "")
        src_vendor = payload.pop("_src_vendor", "")
        tgt_vendor = payload.pop("_tgt_vendor", "")

        resp = self.c.call("BAPI_INFORECORD_CREATE", **payload)
        ret = resp.get("RETURN") or []
        if isinstance(ret, dict):
            ret_list = [ret] if ret.get("TYPE") else []
        else:
            ret_list = list(ret)
        hard = [m for m in ret_list if m.get("TYPE") in ("E", "A")]
        msgs = [(m.get("MESSAGE") or "").strip() for m in ret_list if m.get("MESSAGE")]
        target = (resp.get("INFO_RECORD") or "").strip()
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
        if tgt_vendor.lstrip("0") != src_vendor:
            msgs.append(f"vendor {src_vendor} resolved via F1 -> {tgt_vendor}")
        vk = {"table": "EINA", "key": {"INFNR": target}}
        return target, msgs, DISP_CREATED, vk
