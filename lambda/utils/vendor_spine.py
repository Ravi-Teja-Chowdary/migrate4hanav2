"""
vendor_spine - Vendor (BP-led on S/4) via BAPI_BUPA_CREATE_FROM_DATA + role.

Object-promotion grind batch 6 / 4. Mirrors customer_spine but supplier-side.
On S/4 with CVI, vendor numbering is BP-led: BP shell first, then assign
the supplier role (FLVN01 = financial-accounting supplier). The BP number
IS the vendor number under CVI.

Source ECC LFA1 row shape::

    {"LIFNR": "<source vendor number>",      # informational under BP-led
     "NAME1": "<vendor name>"}

Role configurable via ``cc_org["VENDOR_ROLE"]`` (defaults to FLVN01).
F1 registers (source LIFNR -> target BP/vendor number) so PO/Contract/OpenAP
dependents follow.
"""
from __future__ import annotations

from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


@register_spine
class VendorSpineOrchestrator(BaseSpineOrchestrator):
    """Vendor (BP-led, CVI) - BP shell + supplier role extension."""

    object_type           = "Vendor"
    source_key_field      = "LIFNR"
    extension_structure   = "BAPI_TE_LFA1"
    fk_fields: dict       = {}

    cc_org: dict = {}

    def __init__(self, *args, cc_org: Optional[dict] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cc_org = dict(cc_org or {})

    def validate(self, row: dict) -> Optional[str]:
        if not (row.get("LIFNR") or "").strip():
            return "LIFNR is required (source vendor)"
        if not (row.get("NAME1") or "").strip():
            return "NAME1 is required (vendor name)"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        src_lifnr = (row.get("LIFNR") or "").strip()
        name = (row.get("NAME1") or "").strip()[:40]
        role = (self.cc_org.get("VENDOR_ROLE") or "FLVN01").strip()
        payload: dict = {
            "PARTNERCATEGORY":         "2",
            "CENTRALDATAORGANIZATION": {"NAME1": name},
            "_src_lifnr":              src_lifnr,
            "_role":                   role,
        }
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    external_number_field = "BUSINESSPARTNER"

    def call_bapi(self, payload: dict) -> tuple[Optional[str], list, Optional[str]]:
        from base_spine_orchestrator import DISP_CREATED
        src_lifnr = payload.pop("_src_lifnr", "")
        role      = payload.pop("_role", "FLVN01")

        self.maybe_preserve_source_number(payload, src_lifnr)

        # Step 1: BP shell
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
            return None, msgs, None

        # Step 2: supplier role. Release-tolerant: try the documented role-
        # assignment BAPIs in order; if none exist on this release, commit the
        # BP anyway and surface the gap (F1 chain still works under CVI).
        role_assigned = False
        role_attempts = []
        for fm in ("BAPI_BUPA_ROLES_CHANGE", "BAPI_BUPA_ROLES_ADD_2"):
            try:
                rrole = self.c.call(fm,
                                     BUSINESSPARTNER=bp,
                                     ROLES=[{"PARTNERROLE": role}])
                rret = rrole.get("RETURN") or []
                if isinstance(rret, dict):
                    rret_list = [rret] if rret.get("TYPE") else []
                else:
                    rret_list = list(rret)
                rhard = [m for m in rret_list if m.get("TYPE") in ("E", "A")]
                rmsgs = [(m.get("MESSAGE") or "").strip() for m in rret_list if m.get("MESSAGE")]
                if rhard:
                    role_attempts.append(f"{fm}: {rhard[0].get('MESSAGE','')[:80]}")
                    continue
                msgs.extend(rmsgs)
                role_assigned = True
                break
            except Exception as e:
                err_txt = str(e)
                role_attempts.append(f"{fm}: {err_txt.splitlines()[0][:80]}")
                if "FU_NOT_FOUND" not in err_txt:
                    try:
                        self.c.call("BAPI_TRANSACTION_ROLLBACK")
                    except Exception:
                        pass
                    return None, msgs + [f"role assignment exception: {err_txt[:200]}"], None

        if not role_assigned:
            msgs.append(f"role {role} not assigned on this release "
                         f"(tried: {'; '.join(role_attempts)[:200]}); BP committed without role")

        try:
            self.c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception as e:
            msgs.append(f"commit failed: {e}")
            return None, msgs, None, None
        # BP number IS vendor number under CVI -> verify BUT000 row
        verify_key = {"table": "BUT000", "key": {"PARTNER": bp},
                       "values": {"TYPE": "2"}}
        return bp, msgs, DISP_CREATED, verify_key
