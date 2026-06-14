"""Reject rows whose ``field`` is not a 1- or 2-character SAP language code."""
from __future__ import annotations


def langu_code(row: dict, field: str, **_kwargs) -> str:
    v = row.get(field)
    if v is None or v == "":
        return f"{field}: value is missing"
    s = str(v).strip().upper()
    if len(s) not in (1, 2) or not s.isalpha():
        return f"{field}: invalid language code (LANGU must be 1-2 letters): {s!r}"
    return ""
