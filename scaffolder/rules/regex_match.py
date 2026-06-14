"""Reject rows whose ``field`` does not match the configured regex pattern.

Parametric. Required kwargs:
    pattern — Python regex (anchored at start by default; use ^ ... $ for full match)
"""
from __future__ import annotations

import re


def regex_match(row: dict, field: str, *, pattern: str = "", **_kwargs) -> str:
    if not pattern:
        return f"{field}: regex_match rule needs a 'pattern' arg"
    v = row.get(field)
    if v is None or v == "":
        return f"{field}: value is missing"
    s = str(v)
    if not re.match(pattern, s):
        return f"{field}: does not match pattern {pattern!r}: {s!r}"
    return ""
