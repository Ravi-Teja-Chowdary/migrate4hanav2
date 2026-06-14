"""Reject rows whose ``field`` exceeds the configured decimal precision.

Parametric. Required kwargs:
    digits   — max total digits (precision)
    decimals — max digits after the decimal point (scale)
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


def decimal_max_digits(row: dict, field: str, *,
                        digits: int = 13, decimals: int = 2, **_kwargs) -> str:
    v = row.get(field)
    if v is None or v == "":
        return f"{field}: value is missing"
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        return f"{field}: not numeric: {v!r}"
    sign, dig, exp = d.as_tuple()
    n_total = len(dig)
    n_decimals = max(0, -int(exp)) if isinstance(exp, int) else 0
    if n_decimals > decimals:
        return f"{field}: {n_decimals} decimal places exceeds max {decimals}: {v!r}"
    if n_total > digits:
        return f"{field}: {n_total} digits exceeds max {digits}: {v!r}"
    return ""
