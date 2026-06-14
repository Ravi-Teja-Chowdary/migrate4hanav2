"""Reject rows whose ``field`` is None, empty string, or whitespace-only."""
from __future__ import annotations


def non_empty(row: dict, field: str, **_kwargs) -> str:
    v = row.get(field)
    if v is None:
        return f"{field}: value is missing"
    if isinstance(v, str) and v.strip() == "":
        return f"{field}: value is empty"
    return ""
