"""
fixed_asset_spine - FixedAsset via BAPI_FIXEDASSET_CREATE1.

Object-promotion grind batch 2 / 4. Asset master is composite-keyed
(BUKRS + ANLN1 [+ ANLN2 subnumber]) and can be either internal- or external-
numbered depending on the asset-class configuration. Source asset class is
validated against the target chart of depreciation and falls back to the
discovered default when invalid; the substitution is recorded in messages so
the audit ledger captures it.

Source ECC ANLA row shape::

    {"BUKRS": "<company code>",   # FK -> CompanyCode key_map
     "ANLN1": "<asset number>",
     "ANLN2": "0000",
     "ANLKL": "<asset class>",
     "TXT50": "<description>"}

Org context (ASSET_COMP_CODE + ASSET_CLASS fallback + ASSET_EXTERNAL_NUM +
CAP_DATE + ASSET_DEP_AREAS) supplied via ``cc_org``.
"""
from __future__ import annotations

from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


@register_spine
class FixedAssetSpineOrchestrator(BaseSpineOrchestrator):
    """FixedAsset via BAPI_FIXEDASSET_CREATE1.

    Numbering switch: when ``ASSET_EXTERNAL_NUM`` is true the source ANLN1 is
    preserved (and idempotent via ANLA probe); otherwise SAP assigns internal
    numbering and we capture the returned ASSET.
    """

    object_type           = "FixedAsset"
    source_key_field      = "ANLN1"
    extension_structure   = "BAPI_TE_ANLA"
    fk_fields: dict       = {"BUKRS": "CompanyCode"}

    cc_org: dict = {}

    def __init__(self, *args, cc_org: Optional[dict] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cc_org = dict(cc_org or {})

    def validate(self, row: dict) -> Optional[str]:
        if not (row.get("ANLKL") or self.cc_org.get("ASSET_CLASS")):
            return "ANLKL or fallback ASSET_CLASS required"
        if not (row.get("BUKRS") or self.cc_org.get("ASSET_COMP_CODE")
                or self.cc_org.get("COMP_CODE")):
            return "company code required"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        anln1 = (row.get("ANLN1") or "").strip()
        bukrs = (self.cc_org.get("ASSET_COMP_CODE")
                 or self.cc_org.get("COMP_CODE")
                 or row.get("BUKRS") or "").strip()
        anlkl = (row.get("ANLKL") or self.cc_org.get("ASSET_CLASS") or "").strip()
        external = bool(self.cc_org.get("ASSET_EXTERNAL_NUM")) and bool(anln1)
        desc = ((row.get("TXT50") or f"Asset {anln1 or anlkl}").strip())[:50]
        cap_date = self.cc_org.get("CAP_DATE") or self.cc_org.get("VALID_FROM", "20240101")

        # Pre-flight idempotency (external-numbering path only)
        already_exists = False
        if external and self._fixed_asset_exists(anln1, bukrs):
            already_exists = True

        # Class-validity gate
        src_class = anlkl
        class_remapped = False
        fallback = (self.cc_org.get("ASSET_CLASS") or "").strip()
        if (not already_exists and fallback and anlkl != fallback
                and not self._asset_class_valid(bukrs, anlkl, cap_date)):
            anlkl, class_remapped = fallback, True

        key = {"COMPANYCODE": bukrs}
        if external:
            key["ASSET"] = anln1
        payload: dict = {
            "KEY":                  key,
            "GENERALDATA":          {"ASSETCLASS": anlkl, "DESCRIPT": desc},
            "GENERALDATAX":         {"ASSETCLASS": "X", "DESCRIPT": "X"},
            "POSTINGINFORMATION":   {"CAP_DATE": cap_date},
            "POSTINGINFORMATIONX":  {"CAP_DATE": "X"},
        }
        deps = self.cc_org.get("ASSET_DEP_AREAS")
        if deps:
            payload["DEPRECIATIONAREAS"] = [
                {"AREA": d["AREA"],
                 **({"DEP_KEY": d["DEP_KEY"]} if d.get("DEP_KEY") else {}),
                 **({"ULIFE_YRS": d["ULIFE_YRS"]} if d.get("ULIFE_YRS") else {})}
                for d in deps
            ]
            payload["DEPRECIATIONAREASX"] = [
                {"AREA": d["AREA"],
                 "DEP_KEY":   "X" if d.get("DEP_KEY") else "",
                 "ULIFE_YRS": "X" if d.get("ULIFE_YRS") else ""}
                for d in deps
            ]
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)

        # Carry classification hints through to call_bapi
        payload["_external"]       = external
        payload["_src_anln1"]      = anln1
        payload["_already_exists"] = already_exists
        payload["_src_class"]      = src_class
        payload["_used_class"]     = anlkl
        payload["_class_remapped"] = class_remapped
        return payload

    def call_bapi(self, payload: dict) -> tuple:
        from base_spine_orchestrator import DISP_CREATED, DISP_MATCHED_EXISTING, DISP_REMAPPED
        external       = payload.pop("_external", False)
        src_anln1      = payload.pop("_src_anln1", "")
        already_exists = payload.pop("_already_exists", False)
        src_class      = payload.pop("_src_class", "")
        used_class     = payload.pop("_used_class", "")
        class_remapped = payload.pop("_class_remapped", False)
        bukrs          = (payload.get("KEY", {}) or {}).get("COMPANYCODE", "")

        if already_exists:
            vk = {"table": "ANLA", "key": {"BUKRS": bukrs, "ANLN1": src_anln1}}
            return src_anln1, [f"asset {src_anln1} already exists"], DISP_MATCHED_EXISTING, vk

        resp = self.c.call("BAPI_FIXEDASSET_CREATE1", **payload)
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

        target = (resp.get("ASSET") or src_anln1 or "").strip()
        try:
            self.c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception as e:
            msgs.append(f"commit failed: {e}")
            return None, msgs, None, None

        if class_remapped:
            msgs.append(f"asset class {src_class} not valid; used {used_class}")
        if not target:
            return None, msgs, None, None
        vk = {"table": "ANLA", "key": {"BUKRS": bukrs, "ANLN1": target}}
        # External numbering preserves the key; internal numbering = SAP-assigned -> CREATED
        return target, msgs, DISP_CREATED, vk

    # ── target probes ────────────────────────────────────────────────────────
    def _fixed_asset_exists(self, anln1: str, bukrs: str) -> bool:
        try:
            r = self.c.call(
                "RFC_READ_TABLE",
                QUERY_TABLE="ANLA",
                DELIMITER="|",
                OPTIONS=[{"TEXT": f"BUKRS = '{bukrs}' AND ANLN1 = '{anln1}'"}],
                FIELDS=[{"FIELDNAME": "ANLN1"}],
                ROWCOUNT=1,
            )
            return bool(r.get("DATA"))
        except Exception:
            return False

    def _asset_class_valid(self, bukrs: str, anlkl: str, cap_date: str) -> bool:
        """Two-pass class validity via TESTRUN. Cached per (bukrs, anlkl)."""
        cache = getattr(self, "_ac_cache", None)
        if cache is None:
            cache = self._ac_cache = {}
        key = (bukrs, anlkl)
        if key in cache:
            return cache[key]
        ok = False
        try:
            resp = self.c.call(
                "BAPI_FIXEDASSET_CREATE1",
                KEY={"COMPANYCODE": bukrs},
                GENERALDATA={"ASSETCLASS": anlkl, "DESCRIPT": "M4H probe"},
                GENERALDATAX={"ASSETCLASS": "X", "DESCRIPT": "X"},
                POSTINGINFORMATION={"CAP_DATE": cap_date},
                POSTINGINFORMATIONX={"CAP_DATE": "X"},
                TESTRUN="X",
            )
            ret = resp.get("RETURN") or []
            if isinstance(ret, dict):
                ret_list = [ret] if ret.get("TYPE") else []
            else:
                ret_list = list(ret)
            ok = not any(m.get("TYPE") in ("E", "A") for m in ret_list)
        except Exception:
            ok = False
        cache[key] = ok
        return ok
