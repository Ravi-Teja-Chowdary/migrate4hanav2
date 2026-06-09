"""
equipment_spine - Equipment master via BAPI_EQUI_CREATE.

Object-promotion grind batch 1 / 4. Demonstrates the spine pattern for
objects with SAP-side internal numbering: source EQUNR -> SAP assigns a
new target EQUNR -> we capture it and register the (source, target) pair
in the key_map ledger so dependent objects (BOM items referencing the
equipment, work orders, etc.) can resolve through it.

Source ECC EQUI row shape::

    {"EQUNR": "<source equipment>",   # may differ from target
     "EQTYP": "<category>",           # e.g. "M" for machine
     "EQKTX": "<description>",
     "SHTXT": "<short text>"}

Equipment-category fallback: if the source EQTYP isn't in the target's
in-use set (discovered from EQUI on first call), we remap to the most-
common target category. The remap is surfaced via the messages list so the
audit ledger captures the substitution.
"""
from __future__ import annotations

import datetime
from collections import Counter
from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine, DISP_REMAPPED


@register_spine
class EquipmentSpineOrchestrator(BaseSpineOrchestrator):
    """Equipment master via BAPI_EQUI_CREATE.

    Internal numbering: source EQUNR is informational; the target EQUNR is
    assigned by SAP and read from the response. The spine result registers
    ``(Equipment, source_EQUNR) -> target_EQUNR`` so dependent objects find it.
    """

    object_type           = "Equipment"
    source_key_field      = "EQUNR"
    extension_structure   = "BAPI_TE_EQUI"
    fk_fields: dict       = {}

    # ── validation ───────────────────────────────────────────────────────────
    def validate(self, row: dict) -> Optional[str]:
        # EQUNR may be blank (internal numbering); just need SOMETHING to seed
        # the description / category.
        if not (row.get("EQUNR") or row.get("EQTYP") or row.get("EQKTX")):
            return "row must carry at least one of EQUNR / EQTYP / EQKTX"
        return None

    # ── BAPI payload ─────────────────────────────────────────────────────────
    def build_payload(self, row: dict, ext_rows: list) -> dict:
        equnr = (row.get("EQUNR") or "").strip()
        cat   = (row.get("EQTYP") or "").strip()
        valid_cats, default_cat = self._equip_cats()
        if cat and cat not in valid_cats:
            cat_used = default_cat or "M"
        else:
            cat_used = cat or default_cat or "M"
        name = ((row.get("EQKTX") or row.get("SHTXT") or f"Equipment {equnr or cat_used}").strip())[:40]

        payload = {
            "DATA_GENERAL":  {"DESCRIPT": name},
            "DATA_SPECIFIC": {"EQUICATGRY": cat_used},
            "VALID_DATE":    datetime.date.today().strftime("%Y%m%d"),
        }
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        # Stash so the BAPI message can mention the remap if it happened
        payload["_cat_remapped"] = (cat and cat != cat_used)
        payload["_source_cat"]   = cat
        payload["_used_cat"]     = cat_used
        return payload

    # ── BAPI invocation ──────────────────────────────────────────────────────
    def call_bapi(self, payload: dict) -> tuple[Optional[str], list]:
        cat_remapped = payload.pop("_cat_remapped", False)
        src_cat      = payload.pop("_source_cat", "")
        used_cat     = payload.pop("_used_cat", "")

        resp = self.c.call("BAPI_EQUI_CREATE", **payload)
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
            return None, msgs, None, None

        # Target EQUNR assigned by SAP - capture from the response
        target = (resp.get("EQUIPMENT") or "").strip()
        try:
            self.c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception as e:
            msgs.append(f"commit failed: {e}")
            return None, msgs, None, None

        if cat_remapped:
            msgs.append(f"equipment category {src_cat} not in target catalogue; used {used_cat}")
        # Equipment uses internal numbering: the BAPI assigned a fresh target
        # that won't equal the source EQUNR. Signal CREATED explicitly so the
        # base orchestrator doesn't misclassify it as matched_existing.
        from base_spine_orchestrator import DISP_CREATED
        if not target:
            return None, msgs, None, None
        vk = {"table": "EQUI", "key": {"EQUNR": target}}
        return target, msgs, DISP_CREATED, vk

    # ── discover the target's in-use equipment categories ────────────────────
    def _equip_cats(self):
        cache = getattr(self, "_eqcat_cache", None)
        if cache is not None:
            return cache
        cats = Counter()
        try:
            r = self.c.call(
                "RFC_READ_TABLE",
                QUERY_TABLE="EQUI",
                DELIMITER="|",
                FIELDS=[{"FIELDNAME": "EQTYP"}],
                ROWCOUNT=500,
            )
            cats = Counter(x["WA"].strip() for x in r.get("DATA", []) if x.get("WA", "").strip())
        except Exception:
            pass
        self._eqcat_cache = (set(cats), (cats.most_common(1)[0][0] if cats else "M"))
        return self._eqcat_cache
