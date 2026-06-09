"""
project_spine - Project Definition via BAPI_PROJECTDEF_CREATE.

Object-promotion grind batch 2 / 4. Project IDs are **coding-mask bound**:
the source PSPID's separators may collide with the target project profile's
mask. We try the source ID as-is and, on a mask error, retry with a
sanitized free-form ID (separators stripped) - a collision-safe remap
recorded in the F1 ledger.

Source ECC PROJ row shape::

    {"PSPID": "<project id>",
     "POST1": "<short description>"}

The orchestrator discovers the target project profile + controlling area on
first call (cached). Standalone project create; WBS elements / activities
are loaded by downstream objects.
"""
from __future__ import annotations

import re
from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


@register_spine
class ProjectSpineOrchestrator(BaseSpineOrchestrator):
    """Project via BAPI_PROJECTDEF_CREATE."""

    object_type           = "Project"
    source_key_field      = "PSPID"
    extension_structure   = "BAPI_TE_PROJ"
    fk_fields: dict       = {}

    def validate(self, row: dict) -> Optional[str]:
        if not (row.get("PSPID") or "").strip():
            return "PSPID is required"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        cfg = self._project_config()
        if not cfg.get("profile"):
            return {"_no_profile": True}
        pid = (row["PSPID"] or "").strip()
        desc = ((row.get("POST1") or f"Project {pid}").strip())[:40]

        # Pre-flight idempotency
        already = self._project_exists(pid)

        # Build the candidate-id list: prefer source, retry with sanitized
        sanitized = re.sub(r"[^A-Za-z0-9_]", "", pid)[:24] or ("PRJ" + pid[:8])
        candidates = [pid] if pid == sanitized else [pid, sanitized]

        payload: dict = {
            "PROJECT_DEFINITION_STRU": {
                "PROJECT_DEFINITION": candidates[0],
                "DESCRIPTION":        desc,
                "PROJECT_PROFILE":    cfg["profile"],
                "CONTROLLING_AREA":   cfg["co_area"],
            },
            "_candidates":  candidates,
            "_desc":        desc,
            "_profile":     cfg["profile"],
            "_co_area":     cfg["co_area"],
            "_already":     already,
            "_src_pid":     pid,
        }
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    def call_bapi(self, payload: dict) -> tuple:
        from base_spine_orchestrator import DISP_CREATED, DISP_MATCHED_EXISTING, DISP_REMAPPED
        if payload.get("_no_profile"):
            return None, ["no target project profile discovered"], None, None
        already   = payload.pop("_already", False)
        src_pid   = payload.pop("_src_pid", "")
        candidates = payload.pop("_candidates", [src_pid])
        desc      = payload.pop("_desc", "")
        profile   = payload.pop("_profile", "")
        co_area   = payload.pop("_co_area", "")

        if already:
            vk = {"table": "PROJ", "key": {"PSPID": src_pid}}
            return src_pid, [f"project {src_pid} already exists"], DISP_MATCHED_EXISTING, vk

        last_err = None
        for cand in candidates:
            payload["PROJECT_DEFINITION_STRU"] = {
                "PROJECT_DEFINITION": cand,
                "DESCRIPTION":        desc,
                "PROJECT_PROFILE":    profile,
                "CONTROLLING_AREA":   co_area,
            }
            try:
                resp = self.c.call("BAPI_PROJECTDEF_CREATE", **payload)
            except Exception as e:
                last_err = str(e).splitlines()[0][:200]
                try:
                    self.c.call("BAPI_TRANSACTION_ROLLBACK")
                except Exception:
                    pass
                continue
            ret = resp.get("RETURN") or []
            if isinstance(ret, dict):
                ret_list = [ret] if ret.get("TYPE") else []
            else:
                ret_list = list(ret)
            hard = [m for m in ret_list if m.get("TYPE") in ("E", "A")]
            msgs = [(m.get("MESSAGE") or "").strip() for m in ret_list if m.get("MESSAGE")]
            if hard:
                last_err = "; ".join(f"{m.get('TYPE')} {m.get('MESSAGE')}" for m in hard)[:200]
                try:
                    self.c.call("BAPI_TRANSACTION_ROLLBACK")
                except Exception:
                    pass
                continue
            # success
            try:
                self.c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
            except Exception as e:
                msgs.append(f"commit failed: {e}")
                return None, msgs, None, None
            vk = {"table": "PROJ", "key": {"PSPID": cand}}
            if cand != src_pid:
                msgs.append(f"project id {src_pid} sanitized to {cand}")
                return cand, msgs, DISP_REMAPPED, vk
            return cand, msgs, DISP_CREATED, vk

        # All candidates failed
        return None, [last_err or "all project-id candidates rejected"], None, None

    # ── target probes / config discovery ─────────────────────────────────────
    def _project_exists(self, pid: str) -> bool:
        try:
            r = self.c.call(
                "RFC_READ_TABLE",
                QUERY_TABLE="PROJ",
                DELIMITER="|",
                FIELDS=[{"FIELDNAME": "PSPNR"}],
                OPTIONS=[{"TEXT": f"PSPID = '{pid}'"}],
                ROWCOUNT=1,
            )
            return bool(r.get("DATA"))
        except Exception:
            return False

    def _project_config(self) -> dict:
        cache = getattr(self, "_pcfg_cache", None)
        if cache is not None:
            return cache
        cfg = {"profile": "", "co_area": ""}
        try:
            from collections import Counter
            r = self.c.call(
                "RFC_READ_TABLE",
                QUERY_TABLE="PROJ",
                DELIMITER="|",
                FIELDS=[{"FIELDNAME": "PROFL"}, {"FIELDNAME": "KOKRS"}],
                ROWCOUNT=200,
            )
            profs = Counter()
            cos   = Counter()
            for d in r.get("DATA") or []:
                wa = d.get("WA") or ""
                parts = wa.split("|") if "|" in wa else [wa]
                if len(parts) >= 1: profs[parts[0].strip()] += 1
                if len(parts) >= 2: cos[parts[1].strip()] += 1
            if profs:
                cfg["profile"] = profs.most_common(1)[0][0]
            if cos:
                cfg["co_area"] = cos.most_common(1)[0][0]
        except Exception:
            pass
        self._pcfg_cache = cfg
        return cfg
