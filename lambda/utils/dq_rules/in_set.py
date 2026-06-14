"""Reject rows whose ``field`` is not one of the allowed values.

Parametric. Required kwargs:
    values — list of acceptable string values (case-sensitive)
"""
from __future__ import annotations


def in_set(row: dict, field: str, *, values=None, **_kwargs) -> str:
    if not values:
        return f"{field}: in_set rule needs a 'values' arg"
    v = row.get(field)
    if v is None or v == "":
        return f"{field}: value is missing"
    s = str(v).strip()
    if s not in values:
        return f"{field}: value {s!r} not in allowed set {sorted(values)}"
    return ""
