"""
billing_document_spine - SD Billing Document via BAPI_BILLINGDOC_CREATEMULTIPLE.

Object-promotion grind batch 8 / 4. Billing document (VBRK/VBRP) created
from a sales order or delivery via the multi-create BAPI. F1-resolves the
referenced source document so the billing doc points at the target SO/dlv.

Source ECC VBRK row shape::

    {"VBELN":      "<source billing doc>",
     "REF_VBELN":  "<source SO or delivery>",
     "REF_TYPE":   "SO" | "DLV",            # which key_map to consult
     "FKART":      "F2"}                    # billing doc type
"""
from __future__ import annotations

from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


@register_spine
class BillingDocumentSpineOrchestrator(BaseSpineOrchestrator):
    """BillingDocument via BAPI_BILLINGDOC_CREATEMULTIPLE."""

    object_type           = "BillingDocument"
    source_key_field      = "VBELN"
    extension_structure   = "BAPI_TE_VBRK"
    fk_fields: dict       = {}

    def validate(self, row: dict) -> Optional[str]:
        if not (row.get("VBELN") or "").strip():
            return "VBELN is required (source billing doc)"
        if not (row.get("REF_VBELN") or "").strip():
            return "REF_VBELN is required (referenced SO or delivery)"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        src_doc = (row["VBELN"] or "").strip()
        src_ref = (row["REF_VBELN"] or "").strip()
        ref_type = (row.get("REF_TYPE") or "SO").strip().upper()
        fkart = (row.get("FKART") or "F2").strip()

        # Resolve referenced doc via the appropriate registry
        registry_obj = "OutboundDelivery" if ref_type == "DLV" else "SalesOrder"
        tgt_ref = None
        if self.key_map is not None:
            tgt_ref = self.key_map.resolve(registry_obj, src_ref)
        tgt_ref = tgt_ref or src_ref

        item = [{
            "REF_DOC":      tgt_ref,
            "REF_DOC_CA":   "M" if ref_type == "DLV" else "C",  # M=delivery, C=order
        }]
        # External number preservation for billing docs: DOC_NUMBER on each
        # BILLINGDATAIN row is the BAPI's external-number input. Honoured only
        # when the billing type (FKART) is marked external range in VN01.
        if self.preserve_source_numbers and src_doc:
            item[0]["DOC_NUMBER"] = str(src_doc).zfill(10)
        payload: dict = {
            "BILLINGDATAIN": item,
            "_src_doc": src_doc,
            "_src_ref": src_ref,
            "_tgt_ref": tgt_ref,
            "_fkart":   fkart,
        }
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    def call_bapi(self, payload: dict) -> tuple:
        from base_spine_orchestrator import DISP_CREATED
        src_doc = payload.pop("_src_doc", "")
        src_ref = payload.pop("_src_ref", "")
        tgt_ref = payload.pop("_tgt_ref", "")
        payload.pop("_fkart", None)

        resp = self.c.call("BAPI_BILLINGDOC_CREATEMULTIPLE", **payload)
        ret = resp.get("RETURN") or []
        if isinstance(ret, dict):
            ret_list = [ret] if ret.get("TYPE") else []
        else:
            ret_list = list(ret)
        # BAPI returns BAPI_SUCCESS structure with per-input billing doc number
        success = resp.get("SUCCESS") or []
        if isinstance(success, dict):
            success_list = [success]
        else:
            success_list = list(success)
        msgs = [(m.get("MESSAGE") or "").strip() for m in ret_list if m.get("MESSAGE")]
        hard = [m for m in ret_list if m.get("TYPE") in ("E", "A")]
        target = (success_list[0].get("BILL_DOC") if success_list else "") or ""
        target = str(target).strip()
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

        if tgt_ref != src_ref:
            msgs.append(f"referenced doc {src_ref} resolved via F1 -> {tgt_ref}")
        vk = {"table": "VBRK", "key": {"VBELN": target}}
        return target, msgs, DISP_CREATED, vk
