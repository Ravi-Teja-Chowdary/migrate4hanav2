"""
batch_classification_spine — GENERATED FROM definitions/BatchClassification.json
======================================================================

DO NOT EDIT BY HAND. Re-run `python -m scaffolder.build BatchClassification` to
regenerate after editing the JSON definition.

Generator:    migrate4hana scaffolder v1.0.0
Source SHA:   a7968bfa20cb956c6909a6e0d2e14dbaa212bd68cdb3fecef2c97cd954922615
Object type:  BatchClassification
Category:     Master
Lane:         BAPI (fallback: MC)"""
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
from dq_rules.in_set import in_set
from dq_rules.non_empty import non_empty

# ─────────────────────────────────────────────────────────────────────────────
# Field maps lifted from the JSON definition
# ─────────────────────────────────────────────────────────────────────────────
# HEADER fields — populate the BAPI header struct (OBJECTKEYNEW)
FIELD_MAPS = {
    'OBJEK': 'OBJECTKEYNEW',
}

# ITEM fields — populate the BAPI items table (ALLOCVALUESCHAR).
# Empty for master objects whose BAPI is single-struct (no items table).
ITEM_FIELD_MAPS = {
    'ATINN': 'CHARACT',
    'ATWRT': 'VALUE_CHAR',
}

# target_field -> { source_value: target_value }
VALUE_MAPS = {
}

# Per-spine constants injected into header / items regardless of source row.
# Used for fields the source ECC table doesn't carry (PURCH_ORG defaults,
# BAPI operator flags, doc-type pins) but the target BAPI demands.
CONSTANTS_HEADER = {
}

CONSTANTS_ITEM = {
    'CHARACT': 'WARRANTY_TIME',
    'VALUE_CHAR': '12',
}

# Top-level scalar BAPI imports — sent as named params in the BAPI call,
# outside the header / items structures. Use for BAPIs that take scalar
# imports like BAPI_GOODSMVT_CREATE.GOODSMVT_CODE or BAPI_ALM_NOTIF_CREATE.NOTIF_TYPE.
CONSTANTS_EXTRA = {
    'CLASSNUMNEW': 'YB_BATCH',
    'CLASSTYPENEW': '023',
    'KEYDATE': '20251115',
    'OBJECTKEYNEW': 'TG22                              0000000020',
    'OBJECTTABLENEW': 'MCH1',
}

# Additional struct / table params for multi-struct BAPIs (BAPI_FIXEDASSET_OVRTAKE_CREATE,
# BAPI_ACC_DOCUMENT_POST, BAPI_MATERIAL_BOM_GROUP_CREATE). Object values are
# sent as struct payloads; list values are sent as table payloads.
EXTRA_PAYLOAD = {
}

# DQ gates — (field, rule_name, rule_args, dead_letter_code)
DQ_GATES = [
    ('ATINN', 'non_empty', {}, 'MISSING_CHARACTERISTIC'),
    ('KLART', 'in_set', {'values': ['023']}, 'INVALID_CLASS_TYPE'),
    ('OBJEK', 'non_empty', {}, 'MISSING_OBJECT_KEY'),
]

# Foreign keys — source_field -> registry object_type
FK_FIELDS = {
}

# Verify key contract for the post-load Reconciler
VERIFY_KEY_FIELD = 'OBJEK'
VERIFY_VALUE_FIELDS = ['ATINN', 'ATWRT']

# Resolved at runtime from version_matrix.py; falls back to default_bapi.
DEFAULT_BAPI = 'BAPI_OBJCL_CREATE'
VERSION_BAPI_MAP = {
    'S4HANA_2020': 'BAPI_OBJCL_CREATE',
    'S4HANA_2022': 'BAPI_OBJCL_CREATE',
}


# Dispatch table for DQ rules — built once at import time.
_RULE_FNS = {
    'in_set': in_set,
    'non_empty': non_empty,
}


@register_spine
class BatchClassificationSpineOrchestrator(BaseSpineOrchestrator):
    """Master object spine for BatchClassification.

    Generated from definitions/BatchClassification.json. Honours the
    BaseSpineOrchestrator lifecycle: transform -> validate -> resolve_fk
    -> build_payload -> call_bapi -> register_key -> fan_out_to_sinks.
    """

    object_type           = 'BatchClassification'
    source_key_field      = 'CHARG'
    extension_structure   = ''
    fk_fields             = FK_FIELDS
    home_table            = 'AUSP'

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
        if 'OBJECTKEYNEW':
            payload['OBJECTKEYNEW'] = row.get(self.source_key_field, "")

        # If the BAPI is two-struct (header + items table), build the item from
        # ITEM_FIELD_MAPS and place it as a single-element list. The "one row =
        # one item" pattern is the smoke-test shape; production loaders that
        # aggregate N source rows into one parent header are out of scope here.
        if ITEM_FIELD_MAPS or CONSTANTS_ITEM:
            item = self._apply_field_map(row, ITEM_FIELD_MAPS) if ITEM_FIELD_MAPS else {}
            if CONSTANTS_ITEM:
                item = {**item, **CONSTANTS_ITEM}
            payload['ALLOCVALUESCHAR'] = [item]

        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(
                self.extension_structure, field_names
            )
        if CONSTANTS_EXTRA:
            payload.update(CONSTANTS_EXTRA)
        if EXTRA_PAYLOAD:
            payload.update(EXTRA_PAYLOAD)
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
        raw_key = resp.get('OBJECTKEYNEW')
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
        items = payload.get('ALLOCVALUESCHAR', []) or []
        value_source = items[0] if items else {}
        verify_key = {
            "table": self.home_table,
            "key":   {VERIFY_KEY_FIELD: target_key},
            "values": {fld: value_source.get(fld, "") for fld in VERIFY_VALUE_FIELDS},
        }
        return target_key, msgs, DISP_CREATED, verify_key
