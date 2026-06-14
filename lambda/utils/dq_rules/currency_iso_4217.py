"""Reject rows whose ``field`` is not a 3-letter ISO 4217 currency code."""
from __future__ import annotations


def currency_iso_4217(row: dict, field: str, **_kwargs) -> str:
    v = row.get(field)
    if v is None or v == "":
        return f"{field}: value is missing"
    s = str(v).strip().upper()
    if len(s) != 3 or not s.isalpha():
        return f"{field}: not a valid ISO 4217 currency code: {s!r}"
    return ""
