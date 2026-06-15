"""
anchor_discovery - Pre-flight target-customizing anchor discovery.

PURPOSE
-------
Several Tier-2-BAPI spines fail not because the spine itself is wrong, but
because the BAPI requires a customizing anchor (a plant, a purchase org,
a class number, a tax code) that exists on the TARGET S/4 — and the spine
default points at a value that doesn't exist on this particular landscape.

Examples of the gap that this module closes:

  * WBSElement.constants_extra: I_PROJECT_DEFINITION = "M.1.MIGPRO.X001" —
    this project must exist on target. On a fresh CAL S/4 it doesn't.
  * BatchClassification: CLASSNUMNEW + CLASSTYPENEW — a class number that
    exists on target.
  * Purchase orders: PURCH_ORG = "1010" — must match the target's T024 table.
  * Material movements: PLANT + STGE_LOC — must match T001W + T001L.
  * Tax-coded postings: TAX_CODE = "I0" — must match T007A.

Pre-2026-06-15 we hard-coded these per landscape and asked the basis team
to confirm. Post-2026-06-15 we auto-discover them at run start by reading
the target's own customizing tables via RFC_READ_TABLE and writing the
result to S3 / DDB. Spines then read the discovered anchors instead of
the static defaults; promotion from Tier-2 to Tier-1 happens automatically
without code changes per landscape.

INTERFACES
----------

  discover_anchors(target_conn) -> dict
      Returns a dict of anchor -> discovered value for the standard
      customizing tables. The dict shape is keyed by the constants_extra
      key the spines reference, so spines can do:

          anchors = discover_anchors(target_conn)
          plant   = anchors.get("PLANT") or self.defaults["PLANT"]

  apply_anchors(definition: dict, anchors: dict) -> dict
      Overlays discovered anchors onto a scaffolder JSON definition's
      constants_extra/constants_header/constants_item blocks. Used by the
      orchestrator to inject discovered anchors into a freshly-loaded
      spine spec.

This module is RFC_READ_TABLE-only — no special API surface needed; works
on every SAP release from 4.6C onward. Failure modes are handled by
"missing customizing -> keep the static default" — never crashes the run.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("anchor_discovery")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


# ─────────────────────────────────────────────────────────────────────────────
# Anchor catalog: (constants_extra key) -> (table, fields, where, picker)
# ─────────────────────────────────────────────────────────────────────────────
# Each entry says: "to discover the value for this anchor key, RFC_READ_TABLE
# from <table> selecting <fields>, optionally filtered with <where>, and
# pick the first row's <picker> field as the discovered value."
#
# The picker is the column we want to extract from the row. Multiple anchors
# can share the same table; each entry has its own picker.
_ANCHOR_CATALOG: Dict[str, Dict[str, Any]] = {
    # ── Org-level anchors ──────────────────────────────────────────────────
    "COMP_CODE": {
        "table":  "T001",
        "fields": ["BUKRS", "BUTXT", "LAND1", "WAERS"],
        "where":  "",
        "picker": "BUKRS",
        "label":  "company code",
    },
    "PLANT": {
        "table":  "T001W",
        "fields": ["WERKS", "NAME1"],
        "where":  "",
        "picker": "WERKS",
        "label":  "plant",
    },
    "STGE_LOC": {
        "table":  "T001L",
        "fields": ["WERKS", "LGORT", "LGOBE"],
        "where":  "",
        "picker": "LGORT",
        "label":  "storage location",
    },
    "PURCH_ORG": {
        "table":  "T024E",
        "fields": ["EKORG", "EKOTX", "BUKRS"],
        "where":  "",
        "picker": "EKORG",
        "label":  "purchase organization",
    },
    "PURCH_GROUP": {
        "table":  "T024",
        "fields": ["EKGRP", "EKNAM"],
        "where":  "",
        "picker": "EKGRP",
        "label":  "purchasing group",
    },
    "SALESORG": {
        "table":  "TVKO",
        "fields": ["VKORG", "BUKRS"],
        "where":  "",
        "picker": "VKORG",
        "label":  "sales organization",
    },
    "DISTR_CHAN": {
        "table":  "TVTW",
        "fields": ["VTWEG", "VTEXT"],
        "where":  "",
        "picker": "VTWEG",
        "label":  "distribution channel",
    },
    "DIVISION": {
        "table":  "TSPA",
        "fields": ["SPART", "VTEXT"],
        "where":  "",
        "picker": "SPART",
        "label":  "division",
    },

    # ── Tax & accounting anchors ───────────────────────────────────────────
    "TAX_CODE": {
        "table":  "T007A",
        "fields": ["KALSM", "MWSKZ", "MWART"],
        "where":  "MWART = 'V'",   # input tax
        "picker": "MWSKZ",
        "label":  "input tax code",
    },
    "COST_CTR": {
        "table":  "CSKS",
        "fields": ["KOSTL", "BUKRS"],
        "where":  "",
        "picker": "KOSTL",
        "label":  "cost center",
    },
    "PROFIT_CTR": {
        "table":  "CEPC",
        "fields": ["PRCTR", "DATBI"],
        "where":  "",
        "picker": "PRCTR",
        "label":  "profit center",
    },
    "DOC_TYPE_FI": {
        "table":  "T003",
        "fields": ["BLART", "BLTXT"],
        "where":  "BLART = 'SA'",
        "picker": "BLART",
        "label":  "FI doc type",
    },

    # ── Material / classification anchors ──────────────────────────────────
    "MOVE_TYPE_GR": {
        "table":  "T156",
        "fields": ["BWART", "SOBKZ"],
        "where":  "BWART = '561'",   # initial stock posting
        "picker": "BWART",
        "label":  "GR movement type 561",
    },
    "CLASSTYPENEW": {
        "table":  "TCLA",
        "fields": ["KLART", "KLAGR"],
        "where":  "",
        "picker": "KLART",
        "label":  "classification class type",
    },
    "CLASSNUMNEW": {
        "table":  "KLAH",
        "fields": ["CLASS", "KLART"],
        "where":  "",
        "picker": "CLASS",
        "label":  "classification class number",
    },

    # ── Project / WBS anchors ──────────────────────────────────────────────
    "I_PROJECT_DEFINITION": {
        "table":  "PROJ",
        "fields": ["PSPID", "POST1"],
        "where":  "",
        "picker": "PSPID",
        "label":  "project definition",
    },

    # ── Document-info-record anchors ───────────────────────────────────────
    "DOC_TYPE_DIR": {
        "table":  "DRAT",
        "fields": ["DOKAR", "DKTXT"],
        "where":  "DOKAR = 'AUT'",
        "picker": "DOKAR",
        "label":  "DIR document type",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Discovery routine
# ─────────────────────────────────────────────────────────────────────────────
RfcCall = Callable[[str, dict], dict]


def _read_first(rfc: RfcCall, table: str, fields: List[str],
                where: str = "", picker: str = "") -> Optional[str]:
    """Single-row probe of a customizing table. Returns picker field's
    value from the first row, or None when the table is empty / not found /
    permission-denied. Never raises — caller falls back to the static default.
    """
    try:
        opts = []
        if where:
            opts = [{"TEXT": where[i:i + 72]} for i in range(0, len(where), 72)]
        resp = rfc("RFC_READ_TABLE", {
            "QUERY_TABLE": table,
            "DELIMITER":   "|",
            "ROWCOUNT":    1,
            "OPTIONS":     opts,
            "FIELDS":      [{"FIELDNAME": f} for f in fields],
        })
        rows = resp.get("DATA") or []
        if not rows:
            return None
        first = rows[0].get("WA") or ""
        parts = first.split("|")
        # The DATA.WA value is column-positional matching the FIELDS order
        try:
            idx = fields.index(picker)
        except ValueError:
            return None
        if idx >= len(parts):
            return None
        return parts[idx].strip()
    except Exception as e:   # noqa: BLE001
        logger.debug("anchor discovery on %s failed: %s", table, e)
        return None


def discover_anchors(target_conn,
                     rfc_call: Optional[RfcCall] = None,
                     subset: Optional[List[str]] = None) -> Dict[str, str]:
    """Probe the target's customizing tables and return a dict of
    discovered anchor values.

    Args:
        target_conn: pyrfc.Connection (or any object whose .call(fn, **kw)
                     mirrors RFC_READ_TABLE). When None, ``rfc_call`` must
                     be provided.
        rfc_call:    Optional callable (fn, kwargs) -> dict for testing.
        subset:      If provided, only discover these anchor keys. Default
                     is the full catalog.

    Returns:
        dict of anchor_key -> discovered value. Missing anchors are simply
        omitted (caller falls back to its static default).
    """
    if rfc_call is None:
        if target_conn is None:
            return {}
        # pyrfc Connection: .call(fn, **kwargs) → dict
        def rfc_call(fn: str, kw: dict) -> dict:   # type: ignore
            return target_conn.call(fn, **kw)

    keys = subset or list(_ANCHOR_CATALOG.keys())
    out: Dict[str, str] = {}
    for key in keys:
        spec = _ANCHOR_CATALOG.get(key)
        if not spec:
            continue
        value = _read_first(
            rfc_call,
            table=spec["table"], fields=spec["fields"],
            where=spec.get("where", ""), picker=spec["picker"])
        if value:
            out[key] = value
            logger.info("anchor discovered: %s = %s (from %s)",
                        key, value, spec["table"])
        else:
            logger.info("anchor not found: %s (%s)", key, spec["label"])
    return out


def apply_anchors(definition: dict, anchors: Dict[str, str]) -> dict:
    """Overlay discovered anchors onto a scaffolder JSON definition's
    constants_extra / constants_header / constants_item blocks.

    Discovered values take precedence over the static defaults. Returns a
    deep-copied definition so the caller's source is not mutated.
    """
    import copy
    out = copy.deepcopy(definition)
    transform = out.setdefault("transform", {})
    for block in ("constants_extra", "constants_header", "constants_item"):
        statics = transform.get(block) or {}
        for k, v in anchors.items():
            if k in statics and statics[k] != v:
                statics[k] = v
        # Also add any anchors not already in the static map - lets spines
        # opportunistically receive newly-discovered anchors without
        # touching the JSON.
        for k, v in anchors.items():
            if k not in statics and k.upper() == k:
                # Only inject upper-case keys (the SAP convention); skip
                # any keys that happen to collide with non-anchor names.
                statics.setdefault(k, v)
        if statics:
            transform[block] = statics
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Self-test (no RFC needed)
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("anchor_discovery - self-test")
    print("=" * 70)

    # 1) Fake RFC_READ_TABLE that returns canned rows from a tiny landscape
    fake_landscape = {
        "T001":   [{"WA": "1010|FI Org Unit         |DE|EUR"}],
        "T001W":  [{"WA": "1010|Plant 1010"}],
        "T001L":  [{"WA": "1010|0001|Stge Loc 0001"}],
        "T024E":  [{"WA": "1010|Purch Org 1010      |1010"}],
        "T024":   [{"WA": "001|Group 001"}],
        "TVKO":   [{"WA": "1010|1010"}],
        "TVTW":   [{"WA": "10|Direct Sales"}],
        "TSPA":   [{"WA": "00|Cross-Division"}],
        "T007A":  [{"WA": "TAXUS|I0|V"}],
        "CSKS":   [{"WA": "1010001|1010"}],
        "CEPC":   [{"WA": "1010A|99991231"}],
        "T003":   [{"WA": "SA|G/L Account Doc"}],
        "T156":   [{"WA": "561| "}],
        "TCLA":   [{"WA": "001|Material Class"}],
        "KLAH":   [{"WA": "FERT_CLASS|001"}],
        "PROJ":   [{"WA": "M.1.MIGPRO.X001|Migration Project"}],
        "DRAT":   [{"WA": "AUT|Approval Type"}],
    }

    def fake_rfc(fn, kw):
        if fn != "RFC_READ_TABLE":
            return {}
        return {"DATA": fake_landscape.get(kw["QUERY_TABLE"], [])}

    anchors = discover_anchors(target_conn=None, rfc_call=fake_rfc)
    print(f"\n[discovered] {len(anchors)} anchors from {len(_ANCHOR_CATALOG)} probed:")
    for k, v in sorted(anchors.items()):
        print(f"  {k:24} = {v}")
    assert anchors.get("PLANT") == "1010"
    assert anchors.get("TAX_CODE") == "I0"
    assert anchors.get("I_PROJECT_DEFINITION") == "M.1.MIGPRO.X001"
    assert anchors.get("CLASSNUMNEW") == "FERT_CLASS"

    # 2) Overlay onto a sample definition
    sample_def = {
        "object_type": "WBSElement",
        "transform": {
            "constants_extra": {"I_PROJECT_DEFINITION": "STATIC_DEFAULT"},
            "constants_item":  {"WBS_ELEMENT": "M.1.MIGPRO.X001-000001"},
        },
    }
    overlaid = apply_anchors(sample_def, anchors)
    assert (overlaid["transform"]["constants_extra"]["I_PROJECT_DEFINITION"]
            == "M.1.MIGPRO.X001")
    # Static defaults that aren't anchors stay untouched
    assert (overlaid["transform"]["constants_item"]["WBS_ELEMENT"]
            == "M.1.MIGPRO.X001-000001")
    # Newly-discovered anchors not in the original spec get appended
    assert "PLANT" in overlaid["transform"]["constants_extra"]
    print(f"\n[applied] overlay merged "
          f"{len(overlaid['transform']['constants_extra'])} anchor keys "
          f"into constants_extra (was 1 static)")

    # 3) Missing-table case: anchor not found, definition default preserved
    def empty_rfc(fn, kw):
        return {"DATA": []}
    empty_anchors = discover_anchors(target_conn=None, rfc_call=empty_rfc)
    assert empty_anchors == {}
    preserved = apply_anchors(sample_def, empty_anchors)
    assert (preserved["transform"]["constants_extra"]["I_PROJECT_DEFINITION"]
            == "STATIC_DEFAULT")
    print(f"\n[fallback] empty landscape -> 0 anchors discovered; "
          f"static defaults preserved (no crash)")

    print("\nOK - anchor discovery probes target, overlays discovered "
          "values, and falls back gracefully when customizing is absent.")
