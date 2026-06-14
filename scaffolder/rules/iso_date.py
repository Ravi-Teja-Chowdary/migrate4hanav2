"""Reject rows whose ``field`` is not an ISO-8601 date (YYYY-MM-DD) or SAP date (YYYYMMDD)."""
from __future__ import annotations

from datetime import datetime


def iso_date(row: dict, field: str, **_kwargs) -> str:
    v = row.get(field)
    if v is None or v == "":
        return f"{field}: value is missing"
    s = str(v).strip()
    # Accept SAP DATS (8 digits) or ISO 8601 (10 chars).
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            datetime.strptime(s, fmt)
            return ""
        except ValueError:
            continue
    return f"{field}: not a valid date (expected YYYYMMDD or YYYY-MM-DD): {s!r}"
