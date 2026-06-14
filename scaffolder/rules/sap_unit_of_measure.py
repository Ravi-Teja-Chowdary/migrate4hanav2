"""Reject rows whose ``field`` is not a 3-character uppercase SAP UoM (e.g., EA, KG, M, L)."""
from __future__ import annotations


def sap_unit_of_measure(row: dict, field: str, **_kwargs) -> str:
    v = row.get(field)
    if v is None or v == "":
        return f"{field}: value is missing"
    s = str(v).strip().upper()
    if not (1 <= len(s) <= 3):
        return f"{field}: UoM must be 1-3 chars, got {len(s)}: {s!r}"
    if not s.isalpha():
        return f"{field}: UoM must be alphabetic, got {s!r}"
    return ""
