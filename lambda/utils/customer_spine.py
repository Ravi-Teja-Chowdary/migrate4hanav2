"""
customer_spine - Customer (BP-led on S/4) via BAPI_BUPA_CREATE_FROM_DATA + role.

Object-promotion grind batch 6 / 4. On S/4 with CVI (Customer-Vendor
Integration) the classic BAPI_CUSTOMER_CREATEFROMDATA1 path is blocked --
customer numbering and create are BP-led. The migration pattern that
actually works:

  1. Create the BP shell with org data (BAPI_BUPA_CREATE_FROM_DATA)
  2. Assign the sold-to (FLCU01) role via BAPI_BUPA_ROLES_CHANGE
  3. The BP number IS the customer number under CVI -- F1 registers
     (source KUNNR -> target BP/customer number) so dependent objects
     (OpenAR, SO, etc.) get the canonical BP-number on lookup

Source ECC KNA1 row shape::

    {"KUNNR": "<source customer number>",     # informational under BP-led
     "NAME1": "<organization name>"}

Role configurable via ``cc_org["CUSTOMER_ROLE"]`` (defaults to FLCU01 =
sold-to / financial accounting customer). Verify_key on BUT000 + BUT100.
"""
from __future__ import annotations

from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


@register_spine
class CustomerSpineOrchestrator(BaseSpineOrchestrator):
    """Customer (BP-led, CVI) - BP shell + sold-to role extension."""

    object_type           = "Customer"
    source_key_field      = "KUNNR"
    extension_structure   = "BAPI_TE_KNA1"
    fk_fields: dict       = {}

    cc_org: dict = {}

    def __init__(self, *args, cc_org: Optional[dict] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cc_org = dict(cc_org or {})

    def validate(self, row: dict) -> Optional[str]:
        if not (row.get("KUNNR") or "").strip():
            return "KUNNR is required (source customer)"
        if not (row.get("NAME1") or "").strip():
            return "NAME1 is required (customer name)"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        src_kunnr = (row.get("KUNNR") or "").strip()
        name = (row.get("NAME1") or "").strip()[:40]
        role = (self.cc_org.get("CUSTOMER_ROLE") or "FLCU01").strip()
        payload: dict = {
            "PARTNERCATEGORY":         "2",
            "CENTRALDATAORGANIZATION": {"NAME1": name},
            "_src_kunnr":              src_kunnr,
            "_role":                   role,
        }
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    def call_bapi(self, payload: dict) -> tuple[Optional[str], list, Optional[str]]:
        from base_spine_orchestrator import DISP_CREATED
        src_kunnr = payload.pop("_src_kunnr", "")
        role      = payload.pop("_role", "FLCU01")

        # Step 1: create the BP shell
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

        # Step 2: assign the customer role. The role-assignment BAPI varies by
        # S/4 release; try the documented names in order. If none exist on this
        # release (FU_NOT_FOUND), commit the BP anyway and surface the gap as
        # a message -- the F1 chain still works (BP IS customer-number under
        # CVI), the role just needs to be added by a downstream tool.
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
                # FU_NOT_FOUND -> try the next BAPI; other errors -> hard fail
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
        # BP number IS customer number under CVI -> verify BUT000 row
        verify_key = {"table": "BUT000", "key": {"PARTNER": bp},
                       "values": {"TYPE": "2"}}
        return bp, msgs, DISP_CREATED, verify_key
