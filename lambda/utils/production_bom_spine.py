"""
production_bom_spine - PP Bill of Materials via CSAP_MAT_BOM_CREATE.

Object-promotion grind batch 8 / 4. BOM (STKO/STPO) is the multi-level
parent-component structure used in production. The CSAP_MAT_BOM_CREATE
RFM (RFC-enabled function module, not strictly a BAPI but in the same
spirit) accepts a header (material + plant + BOM usage) + a list of
component items. F1-resolves every MATNR (parent + each child).

Source ECC STKO+STPO row shape::

    {"MATNR":     "<parent material>",
     "WERKS":     "<plant>",
     "STLAN":     "1",                # BOM usage (1=production, 3=mfg)
     "STLAL":     "01",                # alternative
     "components": [{"IDNRK": "<child>", "MENGE": "<qty>", "MEINS": "EA"}, ...]}
"""
from __future__ import annotations

from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


@register_spine
class ProductionBOMSpineOrchestrator(BaseSpineOrchestrator):
    """ProductionBOM via CSAP_MAT_BOM_CREATE."""

    object_type           = "ProductionBOM"
    source_key_field      = "MATNR"
    extension_structure   = "BAPI_TE_STKO"
    fk_fields: dict       = {}

    cc_org: dict = {}

    def __init__(self, *args, cc_org: Optional[dict] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cc_org = dict(cc_org or {})

    def validate(self, row: dict) -> Optional[str]:
        if not (row.get("MATNR") or "").strip():
            return "MATNR is required (parent material)"
        if not (row.get("WERKS") or self.cc_org.get("PLANT") or "").strip():
            return "WERKS / cc_org['PLANT'] required"
        if not (row.get("components") or []):
            return "components list cannot be empty"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        src_parent = (row["MATNR"] or "").strip().upper()
        plant = (row.get("WERKS") or self.cc_org.get("PLANT")).strip()
        stlan = (row.get("STLAN") or "1").strip()
        stlal = (row.get("STLAL") or "01").strip()

        # Resolve parent via F1
        tgt_parent = None
        if self.key_map is not None:
            tgt_parent = self.key_map.resolve("Material", src_parent)
        tgt_parent = tgt_parent or src_parent

        # Resolve each component (child) via F1 -- BOM children harmonize
        # independently of parent
        t_components = []
        unresolved_count = 0
        for c in row.get("components") or []:
            src_child = (c.get("IDNRK") or "").strip().upper()
            tgt_child = (self.key_map.resolve("Material", src_child)
                          if self.key_map is not None and src_child else None)
            if not tgt_child:
                tgt_child = src_child
                if src_child:
                    unresolved_count += 1
            t_components.append({
                "COMPONENT":   tgt_child,
                "COMP_QTY":    str(c.get("MENGE") or "1"),
                "COMP_UNIT":   (c.get("MEINS") or "EA").strip(),
                "ITEM_CATEG":  (c.get("POSTP") or "L").strip(),
            })

        bom_header = {"BOM_USAGE": stlan, "ALTERNATIVE": stlal,
                       "BASE_QTY": "1", "BASE_UNIT": "EA"}
        payload: dict = {
            "MATERIAL":     tgt_parent,
            "PLANT":        plant,
            "BOM_HEADER":   bom_header,
            "ITEMS":        t_components,
            "_src_parent":  src_parent,
            "_tgt_parent":  tgt_parent,
            "_unresolved":  unresolved_count,
        }
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    def call_bapi(self, payload: dict) -> tuple:
        from base_spine_orchestrator import DISP_CREATED
        src_parent  = payload.pop("_src_parent", "")
        tgt_parent  = payload.pop("_tgt_parent", "")
        unresolved  = payload.pop("_unresolved", 0)
        plant       = payload["PLANT"]

        resp = self.c.call("CSAP_MAT_BOM_CREATE", **payload)
        ret = resp.get("RETURN") or []
        if isinstance(ret, dict):
            ret_list = [ret] if ret.get("TYPE") else []
        else:
            ret_list = list(ret)
        hard = [m for m in ret_list if m.get("TYPE") in ("E", "A")]
        msgs = [(m.get("MESSAGE") or "").strip() for m in ret_list if m.get("MESSAGE")]
        target = (resp.get("BOM_NO") or resp.get("STLNR") or "").strip()
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

        if tgt_parent != src_parent:
            msgs.append(f"parent {src_parent} resolved via F1 -> {tgt_parent}")
        if unresolved:
            msgs.append(f"{unresolved} BOM component(s) unresolved -- target BAPI judged")
        vk = {"table": "STKO", "key": {"STLNR": target}}
        return target, msgs, DISP_CREATED, vk
