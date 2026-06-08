"""
characteristic_spine - Characteristic via BAPI_CHARACT_CREATE.

Object-promotion grind batch 3 / 4. Classification master (CT04). The
characteristic name (CABN.ATNAM) is a **global key** — preserved 1:1, no remap.
Idempotent via CABN probe. Data type (ATFOR) maps to the BAPI DATA_TYPE domain
{CHAR, NUM, DATE, TIME, CURR}; anything else falls back to CHAR with the
substitution recorded in messages.

Source ECC CABN row shape::

    {"ATNAM": "<characteristic name>",
     "ATFOR": "CHAR",          # data type
     "ANZST": "10",            # length
     "ANZDZ": "0",             # decimals (NUM/CURR only)
     "ATBEZ": "<description>"}

No FK fields; org context not required.
"""
from __future__ import annotations

from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


_CHAR_DTYPES = {"CHAR", "NUM", "DATE", "TIME", "CURR"}


@register_spine
class CharacteristicSpineOrchestrator(BaseSpineOrchestrator):
    """Characteristic via BAPI_CHARACT_CREATE.

    Global-key preservation: source ATNAM == target ATNAM; no remap path.
    Data-type fallback to CHAR for unknown ATFOR is recorded in messages.
    """

    object_type           = "Characteristic"
    source_key_field      = "ATNAM"
    extension_structure   = "BAPI_TE_CABN"
    fk_fields: dict       = {}

    def validate(self, row: dict) -> Optional[str]:
        if not (row.get("ATNAM") or "").strip():
            return "ATNAM is required"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        name = (row["ATNAM"] or "").strip().upper()
        src_dtype = (row.get("ATFOR") or "CHAR").strip().upper()
        dtype = src_dtype if src_dtype in _CHAR_DTYPES else "CHAR"
        length = (row.get("ANZST") or "").strip() or (
            "10" if dtype in ("CHAR", "NUM", "CURR") else "8"
        )
        detail: dict = {"CHARACT_NAME": name, "DATA_TYPE": dtype,
                        "LENGTH": str(length), "STATUS": "1"}
        dec = (row.get("ANZDZ") or "").strip()
        if dtype in ("NUM", "CURR") and dec:
            detail["DECIMALS"] = str(dec)
        desc = ((row.get("ATBEZ") or name).strip())[:30]

        already = self._charact_exists(name)
        payload: dict = {
            "CHARACTDETAIL":  detail,
            "CHARACTDESCR":   [{"LANGUAGE_ISO": "EN", "DESCRIPTION": desc}],
            "_name":          name,
            "_already":       already,
            "_src_dtype":     src_dtype,
            "_used_dtype":    dtype,
            "_dtype_remapped": src_dtype != dtype,
        }
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    def call_bapi(self, payload: dict) -> tuple[Optional[str], list, Optional[str]]:
        from base_spine_orchestrator import DISP_CREATED, DISP_MATCHED_EXISTING
        name           = payload.pop("_name", "")
        already        = payload.pop("_already", False)
        src_dtype      = payload.pop("_src_dtype", "")
        used_dtype     = payload.pop("_used_dtype", "")
        dtype_remapped = payload.pop("_dtype_remapped", False)

        if already:
            return name, [f"characteristic {name} already exists"], DISP_MATCHED_EXISTING

        resp = self.c.call("BAPI_CHARACT_CREATE", **payload)
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

        try:
            self.c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception as e:
            msgs.append(f"commit failed: {e}")
            return None, msgs, None

        if dtype_remapped:
            msgs.append(f"data type {src_dtype} unsupported; used {used_dtype}")
        return name, msgs, DISP_CREATED

    def _charact_exists(self, name: str) -> bool:
        try:
            r = self.c.call(
                "RFC_READ_TABLE", QUERY_TABLE="CABN", DELIMITER="|",
                FIELDS=[{"FIELDNAME": "ATINN"}],
                OPTIONS=[{"TEXT": f"ATNAM = '{name}'"}], ROWCOUNT=1,
            )
            return bool(r.get("DATA"))
        except Exception:
            return False
