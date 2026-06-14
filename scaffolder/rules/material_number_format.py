"""Reject rows whose ``field`` is not a valid SAP material number (alphanumeric, up to 40 chars)."""
from __future__ import annotations


def material_number_format(row: dict, field: str, **_kwargs) -> str:
    v = row.get(field)
    if v is None or v == "":
        return f"{field}: value is missing"
    s = str(v).strip()
    if len(s) > 40:
        return f"{field}: material number too long ({len(s)} > 40): {s!r}"
    if not all(c.isalnum() or c in "_-/" for c in s):
        return f"{field}: invalid characters in material number: {s!r}"
    return ""
