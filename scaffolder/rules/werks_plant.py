"""Reject rows whose ``field`` is not a 4-character SAP plant code (WERKS)."""
from __future__ import annotations


def werks_plant(row: dict, field: str, **_kwargs) -> str:
    v = row.get(field)
    if v is None or v == "":
        return f"{field}: value is missing"
    s = str(v).strip().upper()
    if len(s) != 4 or not s.isalnum():
        return f"{field}: invalid plant code (WERKS must be 4 alphanumeric chars): {s!r}"
    return ""
