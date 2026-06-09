"""
class_spine - Class via BAPI_CLASS_CREATE.

Object-promotion grind batch 3 / 4. Classification master (CL02), composite-
keyed by (CLASS, KLART). Names are preserved 1:1 across systems. The class
type (KLART) must be configured in the target (TCLA) — if not, the row is
dead-lettered as a **customizing prerequisite**, not a data defect, so it can
be triaged separately.

Source ECC KLAH row shape::

    {"CLASS":  "<class name>",
     "KLART":  "<class type>",   # e.g. "001" (material), "023" (batch), "300" (PMcat)
     "KSCHL":  "<short text>",
     "SWOR":   "<catchword>"}

Idempotency via KLAH probe. No FK fields; no org context.
"""
from __future__ import annotations

from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


@register_spine
class ClassSpineOrchestrator(BaseSpineOrchestrator):
    """Class via BAPI_CLASS_CREATE.

    Composite key (CLASS, KLART). Target TCLA gate on class type — unknown
    class types are dead-lettered as customizing-prerequisite, not as failures.
    """

    object_type           = "Class"
    source_key_field      = "CLASS"
    extension_structure   = "BAPI_TE_KLAH"
    fk_fields: dict       = {}

    def validate(self, row: dict) -> Optional[str]:
        if not (row.get("CLASS") or "").strip():
            return "CLASS is required"
        if not (row.get("KLART") or "").strip():
            return "KLART (class type) is required"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        name = (row["CLASS"] or "").strip().upper()
        ktype = (row["KLART"] or "").strip()
        types = self._class_types()
        if ktype not in types:
            return {"_no_class_type": True, "_ktype": ktype, "_name": name}
        already = self._class_exists(name, ktype)
        desc = ((row.get("KSCHL") or row.get("SWOR") or name).strip())[:40]

        payload: dict = {
            "CLASSNUMNEW":        name,
            "CLASSTYPENEW":       ktype,
            "CLASSBASICDATA":     {"STATUS": "1"},
            "CLASSDESCRIPTIONS":  [{"LANGU_ISO": "EN", "CATCHWORD": desc}],
            "_name":              name,
            "_ktype":             ktype,
            "_already":           already,
        }
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    def call_bapi(self, payload: dict) -> tuple:
        from base_spine_orchestrator import DISP_CREATED, DISP_MATCHED_EXISTING
        if payload.get("_no_class_type"):
            ktype = payload.get("_ktype")
            return None, [f"class type {ktype} not configured in target (TCLA)"], None, None

        name    = payload.pop("_name", "")
        ktype   = payload.pop("_ktype", "")
        already = payload.pop("_already", False)
        vk = {"table": "KLAH", "key": {"CLASS": name, "KLART": ktype}}

        if already:
            return name, [f"class {name} already exists"], DISP_MATCHED_EXISTING, vk

        resp = self.c.call("BAPI_CLASS_CREATE", **payload)
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

        try:
            self.c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception as e:
            msgs.append(f"commit failed: {e}")
            return None, msgs, None, None
        return name, msgs, DISP_CREATED, vk

    # ── target customizing discovery ─────────────────────────────────────────
    def _class_types(self) -> set:
        cache = getattr(self, "_ct_cache", None)
        if cache is not None:
            return cache
        types: set = set()
        try:
            r = self.c.call(
                "RFC_READ_TABLE", QUERY_TABLE="TCLA", DELIMITER="|",
                FIELDS=[{"FIELDNAME": "KLART"}], ROWCOUNT=300,
            )
            types = {(x.get("WA") or "").strip() for x in r.get("DATA") or []
                     if (x.get("WA") or "").strip()}
        except Exception:
            pass
        self._ct_cache = types
        return types

    def _class_exists(self, name: str, ktype: str) -> bool:
        try:
            r = self.c.call(
                "RFC_READ_TABLE", QUERY_TABLE="KLAH", DELIMITER="|",
                FIELDS=[{"FIELDNAME": "CLINT"}],
                OPTIONS=[{"TEXT": f"CLASS = '{name}' AND KLART = '{ktype}'"}],
                ROWCOUNT=1,
            )
            return bool(r.get("DATA"))
        except Exception:
            return False
