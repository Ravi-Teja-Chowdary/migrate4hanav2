"""
sap_number — parse SAP-formatted numeric strings safely.

SAP stores negative amounts with a trailing minus sign (e.g. `123.90-`) and
may include thousands separators (commas or periods depending on locale).
Plain `float(...)` raises ValueError on these.

Use parse_sap_number(value) wherever you would otherwise call float() on a
value coming from an SAP RFC read / table dump.
"""
from __future__ import annotations


def parse_sap_number(value, default: float = 0.0) -> float:
    """
    Convert an SAP-formatted numeric string to float.

    Handles:
      - trailing minus: `'123.90-'` -> -123.90
      - leading minus:  `'-123.90'` -> -123.90
      - thousands separators (comma): `'1,234.56'` -> 1234.56
      - whitespace, None, empty string -> `default`
      - already-numeric values -> float(value)

    Never raises. On unparseable input returns `default` (0.0 by default).
    """
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)

    s = str(value).strip()
    if not s:
        return default

    negative = False
    if s.endswith("-"):
        negative = True
        s = s[:-1].rstrip()
    elif s.startswith("-"):
        negative = True
        s = s[1:].lstrip()
    elif s.startswith("+"):
        s = s[1:].lstrip()

    # Strip thousands separators. Heuristic: if both '.' and ',' present,
    # the rightmost is the decimal separator and the other is thousands.
    if "." in s and "," in s:
        if s.rfind(".") > s.rfind(","):
            s = s.replace(",", "")           # comma is thousands
        else:
            s = s.replace(".", "").replace(",", ".")  # period is thousands
    elif "," in s:
        # Lone comma — treat as thousands when 3 digits follow, else as decimal
        right = s.split(",")[-1]
        if len(right) == 3 and right.isdigit():
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")

    try:
        val = float(s)
    except ValueError:
        return default

    return -val if negative else val
