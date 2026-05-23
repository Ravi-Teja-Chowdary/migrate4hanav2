"""
sap_fields — resolve which fields a table actually has on the connected system.

RFC_READ_TABLE raises FIELD_NOT_VALID if you request a column that does not
exist on the target release. Rather than guess-and-drop from a parsed error
(unreliable — many systems return only the message *number*, not a field
index), we ask the data dictionary (DD03L) for the table's real field list and
intersect it with what the caller wants.

Usage:
    from sap_fields import valid_fields
    fields = valid_fields(conn, "T001", ["BUKRS", "BUTXT", "WAERS", "LAND1"])
    # -> only the subset that exists on this system, in the requested order
"""
from __future__ import annotations
import logging

logger = logging.getLogger("sap_fields")

# Per-connection cache so we don't hit DD03L repeatedly for the same table.
_FIELD_CACHE: dict = {}


def table_fields(conn, table: str) -> set:
    """Return the set of field names that exist for `table` on this system.

    Reads DD03L (the field catalog). Returns an empty set on any failure, in
    which case callers should fall back to requesting their full wanted list.
    """
    key = (id(conn), table.upper())
    if key in _FIELD_CACHE:
        return _FIELD_CACHE[key]

    fields: set = set()
    try:
        res = conn.call(
            "RFC_READ_TABLE",
            QUERY_TABLE="DD03L",
            DELIMITER="|",
            OPTIONS=[{"TEXT": f"TABNAME = '{table.upper()}'"}],
            FIELDS=[{"FIELDNAME": "FIELDNAME"}],
            ROWCOUNT=2000,
        )
        for row in res.get("DATA", []):
            name = row.get("WA", "").split("|")[0].strip().upper()
            # Skip dictionary pseudo-fields like .INCLUDE / .APPEND
            if name and not name.startswith("."):
                fields.add(name)
    except Exception as ex:  # noqa: BLE001
        logger.warning(f"DD03L probe failed for {table} ({type(ex).__name__}); "
                       f"caller will use unfiltered field list")
        fields = set()

    _FIELD_CACHE[key] = fields
    return fields


def valid_fields(conn, table: str, wanted: list) -> list:
    """Intersect `wanted` with the table's real fields, preserving order.

    If the DD03L probe returns nothing (probe failed / unsupported), returns
    `wanted` unchanged so behaviour is no worse than before.
    """
    have = table_fields(conn, table)
    if not have:
        return list(wanted)
    kept = [f for f in wanted if f.upper() in have]
    dropped = [f for f in wanted if f.upper() not in have]
    if dropped:
        logger.info(f"{table}: requesting {len(kept)} fields; "
                    f"not present on this release: {dropped}")
    return kept
