"""
cost_element_group_spine - CostElementGroup via BAPI_COSTELEMENTGRP_CREATE.

Object-promotion grind batch 3 / 4. CO hierarchy (KAH1) — SAP set/group with
SETCLASS=0102 and sub-class = chart of accounts. Name (SETNAME, max 12 chars)
is preserved 1:1; names exceeding the 12-char limit are dead-lettered (manual
rename required) rather than silently truncated.

Source ECC row shape (cost element group from SETHEADER + SETNODE + SETLEAF)::

    {"SETNAME":  "<group name>",     # max 12 chars
     "DESCRIPT": "<description>",
     "VALUES":   [["from1","to1"], ["from2","to2"], ...]}  # optional cost-element ranges

Chart of accounts is auto-discovered from T001.KTOPL when not in ``cc_org``.
Idempotent via SETHEADER probe.
"""
from __future__ import annotations

from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


@register_spine
class CostElementGroupSpineOrchestrator(BaseSpineOrchestrator):
    """CostElementGroup via BAPI_COSTELEMENTGRP_CREATE.

    SETCLASS=0102, sub-class = chart of accounts (auto-discovered).
    Top-node-only when no value ranges; full HIERARCHYVALUES when present.
    """

    object_type           = "CostElementGroup"
    source_key_field      = "SETNAME"
    extension_structure   = "BAPI_TE_SETHEADER"
    fk_fields: dict       = {}

    cc_org: dict = {}
    _SETCLASS = "0102"

    def __init__(self, *args, cc_org: Optional[dict] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cc_org = dict(cc_org or {})

    def validate(self, row: dict) -> Optional[str]:
        if not (row.get("SETNAME") or "").strip():
            return "SETNAME is required"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        name = (row["SETNAME"] or "").strip().upper()
        if len(name) > 12:
            return {"_too_long": True, "_name": name}
        chart = (self.cc_org.get("CHART") or "").strip() or self._co_chart()
        if not chart:
            return {"_no_chart": True, "_name": name}

        already = self._cogroup_exists(self._SETCLASS, name)
        desc = ((row.get("DESCRIPT") or name).strip())[:40]
        values = row.get("VALUES") or []
        nodes = [{"GROUPNAME": name, "HIERLEVEL": 0,
                  "VALCOUNT": len(values), "DESCRIPT": desc}]
        hvals = [{"VALFROM": str(f).strip(), "VALTO": str(t).strip()}
                 for f, t in values]

        payload: dict = {
            "CHARTOFACCOUNTSIMP":  chart,
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

    def call_bapi(self, payload: dict) -> tuple[Optional[str], list, Optional[str]]:
        from base_spine_orchestrator import DISP_CREATED, DISP_MATCHED_EXISTING
        if payload.get("_too_long"):
            n = payload.get("_name")
            return None, [f"group name {n} exceeds the 12-char SAP set-name limit (manual rename required)"], None
        if payload.get("_no_chart"):
            return None, ["no target chart of accounts discovered"], None

        name    = payload.pop("_name", "")
        already = payload.pop("_already", False)

        if already:
            return name, [f"group {name} already exists"], DISP_MATCHED_EXISTING

        resp = self.c.call("BAPI_COSTELEMENTGRP_CREATE", **payload)
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
            return None, msgs, None

        target = (resp.get("GROUPNAME") or name).strip()
        try:
            self.c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception as e:
            msgs.append(f"commit failed: {e}")
            return None, msgs, None
        return target, msgs, DISP_CREATED

    # ── target discovery ────────────────────────────────────────────────────
    def _co_chart(self) -> str:
        cache = getattr(self, "_chart_cache", None)
        if cache is not None:
            return cache
        chart = ""
        try:
            from collections import Counter
            r = self.c.call(
                "RFC_READ_TABLE", QUERY_TABLE="T001", DELIMITER="|",
                FIELDS=[{"FIELDNAME": "KTOPL"}], ROWCOUNT=300,
            )
            cnt = Counter((x.get("WA") or "").strip() for x in r.get("DATA") or []
                          if (x.get("WA") or "").strip())
            chart = cnt.most_common(1)[0][0] if cnt else ""
        except Exception:
            pass
        self._chart_cache = chart
        return chart

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
