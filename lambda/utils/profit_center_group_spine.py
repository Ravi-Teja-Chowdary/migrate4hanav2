"""
profit_center_group_spine - ProfitCenterGroup via BAPI_PROFITCENTERGRP_CREATE.

Object-promotion grind batch 3 / 4. CO hierarchy (KCH1) — mirrors the cost-
element-group pattern: SETCLASS=0106, sub-class = controlling area. Name
(SETNAME, max 12 chars) preserved 1:1; > 12 → dead-letter (manual rename).

Source ECC row shape::

    {"SETNAME":  "<group name>",     # max 12 chars
     "DESCRIPT": "<description>",
     "VALUES":   [["from1","to1"], ...]}   # optional PC ranges

Controlling area is taken from ``cc_org["CO_AREA"]`` (no auto-discovery —
CO_AREA is org-wide and the orchestrator caller knows it). Idempotent via
SETHEADER probe.
"""
from __future__ import annotations

from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


@register_spine
class ProfitCenterGroupSpineOrchestrator(BaseSpineOrchestrator):
    """ProfitCenterGroup via BAPI_PROFITCENTERGRP_CREATE.

    SETCLASS=0106, sub-class = controlling area (from cc_org).
    """

    object_type           = "ProfitCenterGroup"
    source_key_field      = "SETNAME"
    extension_structure   = "BAPI_TE_SETHEADER"
    fk_fields: dict       = {}

    cc_org: dict = {}
    _SETCLASS = "0106"

    def __init__(self, *args, cc_org: Optional[dict] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cc_org = dict(cc_org or {})

    def validate(self, row: dict) -> Optional[str]:
        if not (row.get("SETNAME") or "").strip():
            return "SETNAME is required"
        if not (self.cc_org.get("CO_AREA") or "").strip():
            return "CO_AREA missing in cc_org"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        name = (row["SETNAME"] or "").strip().upper()
        if len(name) > 12:
            return {"_too_long": True, "_name": name}
        coarea = (self.cc_org.get("CO_AREA") or "").strip()

        already = self._cogroup_exists(self._SETCLASS, name)
        desc = ((row.get("DESCRIPT") or name).strip())[:40]
        values = row.get("VALUES") or []
        nodes = [{"GROUPNAME": name, "HIERLEVEL": 0,
                  "VALCOUNT": len(values), "DESCRIPT": desc}]
        hvals = [{"VALFROM": str(f).strip(), "VALTO": str(t).strip()}
                 for f, t in values]

        payload: dict = {
            "CONTROLLINGAREAIMP":  coarea,
            "LANGUAGE":            {"LANGU_ISO": "EN"},
            "HIERARCHYNODES":      nodes,
            "_name":               name,
            "_already":            already,
        }
        if hvals:
            payload["HIERARCHYVALUES"] = hvals
        else:
            payload["TOPNODEONLY"] = "X"
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    def call_bapi(self, payload: dict) -> tuple:
        from base_spine_orchestrator import DISP_CREATED, DISP_MATCHED_EXISTING
        if payload.get("_too_long"):
            n = payload.get("_name")
            return None, [f"group name {n} exceeds the 12-char SAP set-name limit (manual rename required)"], None, None

        name    = payload.pop("_name", "")
        already = payload.pop("_already", False)

        if already:
            vk = {"table": "SETHEADER", "key": {"SETCLASS": self._SETCLASS, "SETNAME": name}}
            return name, [f"group {name} already exists"], DISP_MATCHED_EXISTING, vk

        resp = self.c.call("BAPI_PROFITCENTERGRP_CREATE", **payload)
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

        target = (resp.get("GROUPNAME") or name).strip()
        try:
            self.c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception as e:
            msgs.append(f"commit failed: {e}")
            return None, msgs, None, None
        vk = {"table": "SETHEADER", "key": {"SETCLASS": self._SETCLASS, "SETNAME": target}}
        return target, msgs, DISP_CREATED, vk

    def _cogroup_exists(self, setclass: str, name: str) -> bool:
        try:
            r = self.c.call(
                "RFC_READ_TABLE", QUERY_TABLE="SETHEADER", DELIMITER="|",
                FIELDS=[{"FIELDNAME": "SETNAME"}],
                OPTIONS=[{"TEXT": f"SETCLASS = '{setclass}' AND SETNAME = '{name}'"}],
                ROWCOUNT=1,
            )
            return bool(r.get("DATA"))
        except Exception:
            return False
