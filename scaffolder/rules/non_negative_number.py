"""Reject rows whose ``field`` is not a numeric value >= 0."""
from __future__ import annotations


def non_negative_number(row: dict, field: str, **_kwargs) -> str:
    v = row.get(field)
    if v is None or v == "":
        return f"{field}: value is missing"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return f"{field}: not numeric: {v!r}"
    if n < 0:
        return f"{field}: negative: {n}"
    return ""
