"""
measurement_point_spine — GENERATED FROM definitions/MeasurementPoint.json
======================================================================

DO NOT EDIT BY HAND. Re-run `python -m scaffolder.build MeasurementPoint` to
regenerate after editing the JSON definition.

Generator:    migrate4hana scaffolder v1.0.0
Source SHA:   2d095db91161a1e1ec3020cb6ce33f8fcbd7fee32ca5885582492a152da62231
Object type:  MeasurementPoint
Category:     Master
Lane:         MC"""
from __future__ import annotations

from typing import Optional

from base_spine_orchestrator import (
    BaseSpineOrchestrator,
    register_spine,
    DISP_CREATED,
    DISP_MATCHED_EXISTING,
    DISP_REMAPPED,
    build_extensioninx,
)

# DQ rules — pure functions, sourced from lambda/utils/dq_rules/ at runtime.
from dq_rules.non_empty import non_empty

# ─────────────────────────────────────────────────────────────────────────────
# Field maps lifted from the JSON definition
# ─────────────────────────────────────────────────────────────────────────────
# HEADER fields — populate the BAPI header struct (MEASUREMPOINT)
FIELD_MAPS = {
    'MPOBJ': 'OBJECT_NUMBER',
    'PSORT': 'SORT_FIELD',
    'PTEXT': 'DESCRIPTION',
    'PTTYP': 'POINT_TYPE',
}

# ITEM fields — populate the BAPI items table ().
# Empty for master objects whose BAPI is single-struct (no items table).
ITEM_FIELD_MAPS = {
}

# target_field -> { source_value: target_value }
VALUE_MAPS = {
}

# DQ gates — (field, rule_name, rule_args, dead_letter_code)
DQ_GATES = [
    ('MPOBJ', 'non_empty', {}, 'MISSING_OBJECT_NO'),
    ('POINT', 'non_empty', {}, 'MISSING_POINT_ID'),
]

# Foreign keys — source_field -> registry object_type
FK_FIELDS = {
}

# Verify key contract for the post-load Reconciler
VERIFY_KEY_FIELD = 'POINT'
VERIFY_VALUE_FIELDS = ['MPOBJ', 'PTEXT']

# Resolved at runtime from version_matrix.py; falls back to default_bapi.
DEFAULT_BAPI = 'BAPI_MEASUREMPOINT_CREATE'
VERSION_BAPI_MAP = {
    'S4HANA_2020': 'BAPI_MEASUREMPOINT_CREATE',
    'S4HANA_2022': 'BAPI_MEASUREMPOINT_CREATE',
}


# Dispatch table for DQ rules — built once at import time.
_RULE_FNS = {
    'non_empty': non_empty,
}


@register_spine
class MeasurementPointSpineOrchestrator(BaseSpineOrchestrator):
    """Master object spine for MeasurementPoint.

    Generated from definitions/MeasurementPoint.json. Honours the
    BaseSpineOrchestrator lifecycle: transform -> validate -> resolve_fk
    -> build_payload -> call_bapi -> register_key -> fan_out_to_sinks.
    """

    object_type           = 'MeasurementPoint'
    source_key_field      = 'POINT'
    extension_structure   = ''
    fk_fields             = FK_FIELDS
    home_table            = 'IMPT'

    # ── DQ gates ─────────────────────────────────────────────────────────────
    def validate(self, row: dict) -> Optional[str]:
        for field, rule_name, rule_args, code in DQ_GATES:
            rule_fn = _RULE_FNS.get(rule_name)
            if rule_fn is None:
                return f"{code}: rule {rule_name!r} not registered"
            err = rule_fn(row, field, **rule_args)
            if err:
                return f"{code}: {err}"
        return None

    # ── Payload construction ────────────────────────────────────────────────
    def _apply_field_map(self, row: dict, field_map: dict) -> dict:
        out = {}
        for src, tgt in field_map.items():
            v = row.get(src)
            if v is None:
                continue
            vmap = VALUE_MAPS.get(tgt)
            if vmap and str(v) in vmap:
                v = vmap[str(v)]
            out[tgt] = v
        return out

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        payload: dict = {"_src_key": row.get(self.source_key_field, "")}

        # Header struct: when header_struct is empty (items-only BAPI like
        # BAPI_QPMK_SAVEREPLICA or BAPI_INSPECTIONPLAN_CREATE), skip the
        # header path entirely — the spine sends only the items table.
        # When header_is_scalar=True (rare: BAPI_NETWORK_COMP_ADD NUMBER), the
        # named param is a scalar string at the pyrfc layer despite RFC_GET
        # introspection reporting a one-field struct — send the source key
        # value directly, not a dict.
        if 'MEASUREMPOINT':
            header = self._apply_field_map(row, FIELD_MAPS)
            payload['MEASUREMPOINT'] = header

        # If the BAPI is two-struct (header + items table), build the item from
        # ITEM_FIELD_MAPS and place it as a single-element list. The "one row =
        # one item" pattern is the smoke-test shape; production loaders that
        # aggregate N source rows into one parent header are out of scope here.
        if ITEM_FIELD_MAPS:
            item = self._apply_field_map(row, ITEM_FIELD_MAPS)
            payload[''] = [item]

        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(
                self.extension_structure, field_names
            )
        return payload

    # ── BAPI invocation ─────────────────────────────────────────────────────
    def call_bapi(self, payload: dict) -> tuple:
        src_key = payload.pop("_src_key", "")

        # Version routing: pick the BAPI per the target release.
        bapi_fn = VERSION_BAPI_MAP.get(self.target_release, DEFAULT_BAPI)

        resp = self.c.call(bapi_fn, **payload)

        # Normalize RETURN to a list (BAPIs send either a single struct or a tbl)
        ret = resp.get("RETURN") or []
        if isinstance(ret, dict):
            ret_list = [ret] if ret.get("TYPE") else []
        else:
            ret_list = list(ret)

        hard = [m for m in ret_list if m.get("TYPE") in ("E", "A")]
        msgs = [(m.get("MESSAGE") or "").strip() for m in ret_list if m.get("MESSAGE")]

        # Target-key extraction. Most BAPIs return a scalar string at
        # return_key_field, but some (BAPI_BUS2054_CREATE_MULTI, BAPI_NETWORK_
        # MAINTAIN) only return a status struct/table — no scalar key. When
        # the BAPI succeeded (no E/A in RETURN) but the named field isn't a
        # scalar, fall back to the source key as the synthetic target_key so
        # the Reconciler can still verify against home_table.
        raw_key = resp.get('MEASUREMPOINT')
        if isinstance(raw_key, str):
            target_key = raw_key.strip()
        elif raw_key is None or isinstance(raw_key, (dict, list)):
            target_key = "" if hard else src_key
        else:
            target_key = str(raw_key).strip()

        if hard or not target_key:
            try:
                self.c.call("BAPI_TRANSACTION_ROLLBACK")
            except Exception:
                pass
            return None, msgs, None, None

        # Commit. WAIT="X" is included when load.bapi.commit_with_wait is true
        # (default). A commit failure is surfaced as a BAPI failure so the
        # Reconciler still reports the gap when it cannot find the target_key
        # in home_table.
        try:
            self.c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception:
            return None, msgs + ["BAPI_TRANSACTION_COMMIT failed"], None, None

        # Verify-value lookup: prefer header struct; fall back to first item
        # of item struct when the BAPI is items-only OR when the header is a
        # scalar (the scalar carries only the key, not value-field data).
        if 'MEASUREMPOINT':
            value_source = payload.get('MEASUREMPOINT', {}) or {}
        elif ITEM_FIELD_MAPS:
            items = payload.get('', []) or []
            value_source = items[0] if items else {}
        else:
            value_source = {}
        verify_key = {
            "table": self.home_table,
            "key":   {VERIFY_KEY_FIELD: target_key},
            "values": {fld: value_source.get(fld, "") for fld in VERIFY_VALUE_FIELDS},
        }
        return target_key, msgs, DISP_CREATED, verify_key
