"""
sales_order_spine - SalesOrder via BAPI_SALESORDER_CREATEFROMDAT2.

Object-promotion grind batch 4 / 4. Open SD doc (VA01). The tricky shape:
sales orders need three things to align (sales area, sold-to customer with
KNVV in that area, saleable material with MVKE in that area). Source
customers/materials rarely carry the target's sales view, so — like PO
vendor harmonization — we **discover a coherent target sales area** with both
a sales-ready customer and a saleable material, then harmonize.

Source ECC row shape::

    {"VBELN": "<source SO>",
     "KUNNR": "<source customer>"}

No org context needed — everything is auto-discovered from target customizing.

Sales-area discovery: scan KNVV (customers with sales-org/channel/division
data) and MVKE (materials by sales-org/channel); find the first (VKORG,
VTWEG, SPART) tuple that has BOTH a ready customer and a saleable material.
Order type (AUART) discovered from VBAK most-common (default TA).
"""
from __future__ import annotations

from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


@register_spine
class SalesOrderSpineOrchestrator(BaseSpineOrchestrator):
    """SalesOrder via BAPI_SALESORDER_CREATEFROMDAT2 with sales-area discovery."""

    object_type           = "SalesOrder"
    source_key_field      = "VBELN"
    extension_structure   = "BAPI_TE_VBAK"
    # Note: customer resolution is explicit in build_payload (registry-then-
    # harmonize-to-sales-ready), not via default resolve_fk replace-or-fail.
    fk_fields: dict       = {}

    def validate(self, row: dict) -> Optional[str]:
        if not (row.get("VBELN") or "").strip():
            return "VBELN is required (source SO number)"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        """WS2-deepened payload. Supports:
          - Multi-item lines from row["items"]  (each item: MATNR/MENGE/MEINS)
          - Multi-role partners from row["partners"] (PARVW/KUNNR rows;
            roles other than AG resolved through F1)
          - Pricing conditions from row["conditions"] (KSCHL/KBETR rows)
          - Header / item long texts from row["texts"]
        All optional; the legacy single-item / sold-to-only shape still
        works when these arrays are absent.
        """
        from base_spine_orchestrator import (
            normalise_partner_rows, normalise_condition_rows,
            normalise_text_rows,
        )

        cfg = self._so_config()
        if not cfg:
            return {"_no_sales_area": True}

        src_so = (row.get("VBELN") or "").strip()
        src_cust = (row.get("KUNNR") or "").strip()
        tgt_cust = None
        if self.key_map is not None:
            tgt_cust = self.key_map.resolve("Customer", src_cust)
        cdisp = "registry"
        if not (tgt_cust and tgt_cust in cfg["customers"]):
            tgt_cust = cfg["sample_customer"]
            cdisp = "harmonized"

        hdr = {
            "DOC_TYPE":   cfg["otype"],
            "SALES_ORG":  cfg["sorg"],
            "DISTR_CHAN": cfg["chan"],
            "DIVISION":   cfg["div"],
        }

        # ── PARTNERS — sold-to is always present; additional partner functions
        # come from row["partners"] (KNVP-style: PARVW + KUNNR) and route
        # through F1 so target sees BP_IDs not legacy KUNNRs.
        parts = [{"PARTN_ROLE": "AG", "PARTN_NUMB": tgt_cust.zfill(10)}]
        extra_partners = normalise_partner_rows(
            row.get("partners") or [],
            role_field="PARVW", number_field="KUNNR",
            key_map=self.key_map, source_object="Customer",
        )
        for p in extra_partners:
            if p["PARTN_ROLE"] != "AG":   # don't double sold-to
                p["PARTN_NUMB"] = (p["PARTN_NUMB"] or "").zfill(10)
                parts.append(p)

        # ── ITEMS — accept multi-line items from row["items"]; each entry can
        # carry MATNR (source material, resolved through F1 if registered),
        # MENGE (quantity), MEINS (UoM). Falls back to the single-sample
        # item shape when the input doesn't carry an items array.
        src_items = row.get("items") or []
        if not src_items:
            items = [{"ITM_NUMBER": "000010",
                       "MATERIAL":   cfg["sample_material"],
                       "TARGET_QTY": "1", "TARGET_QU": "EA"}]
            sched = [{"ITM_NUMBER": "000010", "REQ_QTY": "1"}]
        else:
            items, sched = [], []
            for i, it in enumerate(src_items, start=1):
                inum = f"{i*10:06d}"
                src_mat = (it.get("MATNR") or "").strip()
                tgt_mat = None
                if self.key_map is not None and src_mat:
                    tgt_mat = self.key_map.resolve("Material", src_mat)
                # If unresolved or not saleable, harmonize to a saleable
                # material in the discovered sales area
                if not tgt_mat:
                    tgt_mat = cfg["sample_material"]
                qty = str(it.get("MENGE") or it.get("QTY") or "1")
                uom = (it.get("MEINS") or it.get("UOM") or "EA").strip()
                items.append({"ITM_NUMBER": inum, "MATERIAL": tgt_mat,
                                "TARGET_QTY": qty, "TARGET_QU": uom})
                sched.append({"ITM_NUMBER": inum, "REQ_QTY": qty})

        payload: dict = {
            "ORDER_HEADER_IN":     hdr,
            "ORDER_PARTNERS":      parts,
            "ORDER_ITEMS_IN":      items,
            "ORDER_SCHEDULES_IN":  sched,
            "_src_so":   src_so,
            "_src_cust": src_cust,
            "_tgt_cust": tgt_cust,
            "_cdisp":    cdisp,
        }

        # ── CONDITIONS — header-level or per-item pricing rows from
        # row["conditions"] mapped into the BAPI's ORDER_CONDITIONS_IN
        # table (the BAPI supports both header-level COND_TYPE 'PR00'
        # equivalents and per-item discounts).
        src_conds = row.get("conditions") or []
        if src_conds:
            # Map each per-item condition; if "ITEM" missing, attach to item 1
            cond_rows = []
            for c in src_conds:
                item_index = int(c.get("ITEM") or 10)
                cond_rows.extend(normalise_condition_rows([c],
                                                           item_index=item_index))
            payload["ORDER_CONDITIONS_IN"] = cond_rows

        # ── LONGTEXTS — header/item texts, packaged for a follow-up
        # BAPI_LONGTEXT_SAVE call after the SO commits. Carried in the
        # payload so call_bapi can issue the long-text call separately.
        src_texts = row.get("texts") or []
        if src_texts:
            payload["LONGTEXTS"] = normalise_text_rows(src_texts)

        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    def call_bapi(self, payload: dict) -> tuple:
        from base_spine_orchestrator import DISP_CREATED
        if payload.get("_no_sales_area"):
            return None, ["no coherent target sales area (customer+material) discovered"], None, None

        src_so   = payload.pop("_src_so", "")
        src_cust = payload.pop("_src_cust", "")
        tgt_cust = payload.pop("_tgt_cust", "")
        cdisp    = payload.pop("_cdisp", "registry")

        # External number preservation: when the wizard toggle is on and the
        # target sales-doc type is marked "external number range" in VOV8,
        # SALESDOCUMENTIN is honoured and the S/4 SO gets the same VBELN as
        # ECC. When the doc type is internal-range, the BAPI silently ignores
        # this field and assigns from its own range — no error.
        if self.preserve_source_numbers and src_so:
            payload["SALESDOCUMENTIN"] = str(src_so).zfill(10)

        resp = self.c.call("BAPI_SALESORDER_CREATEFROMDAT2", **payload)
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

    # ── sales-area discovery ─────────────────────────────────────────────────
    def _so_config(self):
        cache = getattr(self, "_so_cfg_cache", None)
        if cache is not None:
            return cache
        from collections import Counter
        cfg = None
        try:
            kn = self.c.call(
                "RFC_READ_TABLE", QUERY_TABLE="KNVV", DELIMITER="|",
                FIELDS=[{"FIELDNAME": "KUNNR"}, {"FIELDNAME": "VKORG"},
                        {"FIELDNAME": "VTWEG"}, {"FIELDNAME": "SPART"}],
                ROWCOUNT=2000,
            )
            mv = self.c.call(
                "RFC_READ_TABLE", QUERY_TABLE="MVKE", DELIMITER="|",
                FIELDS=[{"FIELDNAME": "MATNR"}, {"FIELDNAME": "VKORG"},
                        {"FIELDNAME": "VTWEG"}],
                ROWCOUNT=3000,
            )
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
            otypes: Counter = Counter()
            try:
                vb = self.c.call(
                    "RFC_READ_TABLE", QUERY_TABLE="VBAK", DELIMITER="|",
                    FIELDS=[{"FIELDNAME": "AUART"}], ROWCOUNT=500,
                )
                otypes = Counter((x.get("WA") or "").strip() for x in vb.get("DATA") or []
                                  if (x.get("WA") or "").strip())
            except Exception:
                pass
            otype = otypes.most_common(1)[0][0] if otypes else "TA"
            for (vk, vt, sp), cl in custs.items():
                if (vk, vt) in mats and cl and mats[(vk, vt)]:
                    cfg = {"sorg": vk, "chan": vt, "div": sp, "otype": otype,
                           "customers": set(cl), "sample_customer": cl[0],
                           "sample_material": mats[(vk, vt)][0]}
                    break
        except Exception:
            pass
        self._so_cfg_cache = cfg
        return cfg
