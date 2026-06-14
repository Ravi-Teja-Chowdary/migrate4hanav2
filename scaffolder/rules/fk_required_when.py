"""Require ``field`` to be non-empty when a trigger field has a specific value.

Row-level conditional FK requirement. Useful for "bank required when payment
method is BANK" / "cost center required when account is P&L" patterns.

Parametric. Required kwargs:
    trigger_field — name of the gating field
    trigger_value — value that makes ``field`` required (case-sensitive)
"""
from __future__ import annotations


def fk_required_when(row: dict, field: str, *,
                     trigger_field: str = "", trigger_value: str = "",
                     **_kwargs) -> str:
    if not trigger_field:
        return f"{field}: fk_required_when rule needs a 'trigger_field' arg"
    if row.get(trigger_field) != trigger_value:
        return ""        # trigger not active → field is optional
    v = row.get(field)
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return f"{field}: required when {trigger_field}={trigger_value!r}"
    return ""
