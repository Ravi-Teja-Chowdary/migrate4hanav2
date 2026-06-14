"""
schedule_agreement_mm_spine — GENERATED FROM definitions/ScheduleAgreementMM.json
======================================================================

DO NOT EDIT BY HAND. Re-run `python -m scaffolder.build ScheduleAgreementMM` to
regenerate after editing the JSON definition.

Generator:    migrate4hana scaffolder v1.0.0
Source SHA:   aa2b19d4ddbd898c7bcb77fc2bda548a19a661342631ef1c34636c18f898aa84
Object type:  ScheduleAgreementMM
Category:     Transactional
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
# HEADER fields — populate the BAPI header struct (HEADER)
FIELD_MAPS = {
    'BSART': 'DOC_TYPE',
    'EKGRP': 'PUR_GROUP',
    'EKORG': 'PURCH_ORG',
    'WAERS': 'CURRENCY',
}

# ITEM fields — populate the BAPI items table (ITEM).
# Empty for master objects whose BAPI is single-struct (no items table).
ITEM_FIELD_MAPS = {
}

# target_field -> { source_value: target_value }
VALUE_MAPS = {
}

# Per-spine constants injected into header / items regardless of source row.
# Used for fields the source ECC table doesn't carry (PURCH_ORG defaults,
# BAPI operator flags, doc-type pins) but the target BAPI demands.
CONSTANTS_HEADER = {
    'COMP_CODE': '1710',
    'CURRENCY': 'USD',
    'DOC_TYPE': 'LP',
    'PURCH_ORG': '1710',
    'PUR_GROUP': '001',
    'VENDOR': '0017300002',
    'VPER_END': '20271231',
    'VPER_START': '20270101',
}

CONSTANTS_ITEM = {
    'ITEM_NO': '00010',
    'MATERIAL': 'TG0013',
    'PLANT': '1710',
    'PO_UNIT': 'EA',
    'TARGET_QTY': '1',
}

# DQ gates — (field, rule_name, rule_args, dead_letter_code)
DQ_GATES = [
    ('BSART', 'in_set', {'values': ['LP', 'LPA']}, 'INVALID_DOC_TYPE'),
    ('EBELN', 'non_empty', {}, 'MISSING_AGREEMENT_NO'),
    ('EKORG', 'non_empty', {}, 'MISSING_PURCH_ORG'),
]

# Foreign keys — source_field -> registry object_type
FK_FIELDS = {
}

# Verify key contract for the post-load Reconciler
VERIFY_KEY_FIELD = 'EBELN'
VERIFY_VALUE_FIELDS = ['BSART', 'EKORG']

# Resolved at runtime from version_matrix.py; falls back to default_bapi.
DEFAULT_BAPI = 'BAPI_SAG_CREATE'
VERSION_BAPI_MAP = {
    'S4HANA_2020': 'BAPI_SAG_CREATE',
    'S4HANA_2022': 'BAPI_SAG_CREATE',
}


# Dispatch table for DQ rules — built once at import time.
_RULE_FNS = {
    'in_set': in_set,
    'non_empty': non_empty,
}


@register_spine
class ScheduleAgreementMMSpineOrchestrator(BaseSpineOrchestrator):
    """Transactional object spine for ScheduleAgreementMM.

    Generated from definitions/ScheduleAgreementMM.json. Honours the
    BaseSpineOrchestrator lifecycle: transform -> validate -> resolve_fk
    -> build_payload -> call_bapi -> register_key -> fan_out_to_sinks.
    """

    object_type           = 'ScheduleAgreementMM'
    source_key_field      = 'EBELN'
    extension_structure   = ''
    fk_fields             = FK_FIELDS
    home_table            = 'EKKO'

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
        if 'HEADER':
            header = self._apply_field_map(row, FIELD_MAPS)
            # Per-spine fixed values overlay the source-derived header
            if CONSTANTS_HEADER:
                header = {**header, **CONSTANTS_HEADER}
            payload['HEADER'] = header
            # MM-logistics-family X-struct: every populated header field gets
            # field='X' in the companion struct so the BAPI honours the value.
            # NUMC-key fields like NUMBER must instead carry their value (the
            # X-struct's NUMC keys are introspected as digit strings, not 'X').
            payload['HEADERX'] = {
                k: (v if (isinstance(v, str) and v.isdigit()) else "X")
                for k, v in header.items()
            }

        # If the BAPI is two-struct (header + items table), build the item from
        # ITEM_FIELD_MAPS and place it as a single-element list. The "one row =
        # one item" pattern is the smoke-test shape; production loaders that
        # aggregate N source rows into one parent header are out of scope here.
        if ITEM_FIELD_MAPS or CONSTANTS_ITEM:
            item = self._apply_field_map(row, ITEM_FIELD_MAPS) if ITEM_FIELD_MAPS else {}
            if CONSTANTS_ITEM:
                item = {**item, **CONSTANTS_ITEM}
            payload['ITEM'] = [item]
            # Same NUMC-key carve-out as the header X-struct: digit-string
            # values (PO_ITEM, ITEM_NO, etc.) get carried; everything else
            # gets 'X' as the boolean change indicator.
            payload['ITEMX'] = [{
                k: (v if (isinstance(v, str) and v.isdigit()) else "X")
                for k, v in item.items()
            }]

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
        raw_key = resp.get('PURCHASINGDOCUMENT')
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
        if 'HEADER':
            value_source = payload.get('HEADER', {}) or {}
        elif ITEM_FIELD_MAPS:
            items = payload.get('ITEM', []) or []
            value_source = items[0] if items else {}
        else:
            value_source = {}
        verify_key = {
            "table": self.home_table,
            "key":   {VERIFY_KEY_FIELD: target_key},
            "values": {fld: value_source.get(fld, "") for fld in VERIFY_VALUE_FIELDS},
        }
        return target_key, msgs, DISP_CREATED, verify_key
