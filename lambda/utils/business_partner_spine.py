"""
business_partner_spine - BusinessPartner via BAPI_BUPA_CREATE_FROM_DATA.

Object-promotion grind batch 6 / 4 (last batch). The BP shell — Customer and
Vendor on S/4 are FACETS of a BusinessPartner via CVI (Customer-Vendor
Integration). This spine creates the BP shell; the role extension (sold-to
for Customer, supplier for Vendor) is handled by the Customer / Vendor
spines that build on this one.

Source ECC row shape (org BP, the common case)::

    {"BPARTNER": "<source partner number>",    # informational under BP-led
     "CATEGORY": "2",                           # 1=person, 2=org (default)
     "NAME":     "<organization name>",         # max 40 chars
     "GROUPING": ""}                            # partner grouping (optional)

Or for a person::

    {"BPARTNER": "...", "CATEGORY": "1", "NAME": "<last name>"}

BP-led numbering: source BPARTNER is informational only. The S/4 BP number
is SAP-assigned and captured from the BAPI response BUSINESSPARTNER field.
verify_key on BUT000.
"""
from __future__ import annotations

from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


@register_spine
class BusinessPartnerSpineOrchestrator(BaseSpineOrchestrator):
    """BusinessPartner shell via BAPI_BUPA_CREATE_FROM_DATA (BP-led numbering)."""

    object_type           = "BusinessPartner"
    source_key_field      = "BPARTNER"
    extension_structure   = "BAPI_TE_BUT000"
    fk_fields: dict       = {}

    def validate(self, row: dict) -> Optional[str]:
        # NAME required (BP can't be created without identification data)
        if not (row.get("NAME") or "").strip():
            return "NAME is required"
        cat = (row.get("CATEGORY") or "2").strip()
        if cat not in ("1", "2"):
            return f"CATEGORY {cat} invalid (must be 1=person or 2=org)"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        cat = (row.get("CATEGORY") or "2").strip()
        name = (row.get("NAME") or "").strip()[:40]
        grouping = (row.get("GROUPING") or "").strip()
        src_bp = (row.get("BPARTNER") or "").strip()

        payload: dict = {
            "PARTNERCATEGORY": cat,
            "_src_bp": src_bp,
            "_category": cat,
        }
        if cat == "1":
            payload["CENTRALDATAPERSON"] = {"LASTNAME": name}
        else:
            payload["CENTRALDATAORGANIZATION"] = {"NAME1": name}
        if grouping:
            payload["PARTNERGROUP"] = grouping
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    def call_bapi(self, payload: dict) -> tuple:
        from base_spine_orchestrator import DISP_CREATED
        src_bp = payload.pop("_src_bp", "")
        cat = payload.pop("_category", "2")

        resp = self.c.call("BAPI_BUPA_CREATE_FROM_DATA", **payload)
        ret = resp.get("RETURN") or []
        if isinstance(ret, dict):
            ret_list = [ret] if ret.get("TYPE") else []
        else:
            ret_list = list(ret)
        hard = [m for m in ret_list if m.get("TYPE") in ("E", "A")]
        msgs = [(m.get("MESSAGE") or "").strip() for m in ret_list if m.get("MESSAGE")]
        bp = (resp.get("BUSINESSPARTNER") or "").strip()
        if hard or not bp:
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
        # verify_key: BUT000 row + category tie-out
        verify_key = {"table": "BUT000", "key": {"PARTNER": bp},
                       "values": {"TYPE": cat}}
        return bp, msgs, DISP_CREATED, verify_key
