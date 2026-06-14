"""Reject rows whose ``field`` is not a 3-character numeric SAP client (MANDT, e.g., '100')."""
from __future__ import annotations


def sap_client_3char(row: dict, field: str, **_kwargs) -> str:
    v = row.get(field)
    if v is None or v == "":
        return f"{field}: value is missing"
    s = str(v).strip()
    if len(s) != 3 or not s.isdigit():
        return f"{field}: invalid client (MANDT must be 3 digits): {s!r}"
    return ""
