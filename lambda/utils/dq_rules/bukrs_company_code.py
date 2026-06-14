"""Reject rows whose ``field`` is not a 4-character SAP company code (BUKRS)."""
from __future__ import annotations


def bukrs_company_code(row: dict, field: str, **_kwargs) -> str:
    v = row.get(field)
    if v is None or v == "":
        return f"{field}: value is missing"
    s = str(v).strip().upper()
    if len(s) != 4 or not s.isalnum():
        return f"{field}: invalid company code (BUKRS must be 4 alphanumeric chars): {s!r}"
    return ""
