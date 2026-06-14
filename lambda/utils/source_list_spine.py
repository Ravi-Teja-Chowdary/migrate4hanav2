"""
source_list_spine — GENERATED FROM definitions/SourceList.json
======================================================================

DO NOT EDIT BY HAND. Re-run `python -m scaffolder.build SourceList` to
regenerate after editing the JSON definition.

Generator:    migrate4hana scaffolder v1.0.0
Source SHA:   1918c724106d42568aa28dbf03ceb161fe3f15ad2e2aff3d416d795b978e1d94
Object type:  SourceList
Category:     Master
Lane:         MC (fallback: LTMOM)"""
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
from dq_rules.iso_date import iso_date
from dq_rules.material_number_format import material_number_format
from dq_rules.non_empty import non_empty
from dq_rules.werks_plant import werks_plant

# ─────────────────────────────────────────────────────────────────────────────
# Field maps lifted from the JSON definition
# ─────────────────────────────────────────────────────────────────────────────
# source_field -> target_canonical_field
FIELD_MAPS = {
    'BDATU': 'VALID_TO',
    'EBELN': 'AGREEMENT',
    'EKORG': 'PURCH_ORG',
    'FLIFN': 'FIX_VENDOR',
    'LIFNR': 'VENDOR',
    'MATNR': 'MATERIAL',
    'VDATU': 'VALID_FROM',
    'WERKS': 'PLANT',
}

# target_field -> { source_value: target_value }
VALUE_MAPS = {
    'FIX_VENDOR': {
        '': ' ',
        'X': 'X',
    },
}

# DQ gates — (field, rule_name, rule_args, dead_letter_code)
DQ_GATES = [
    ('BDATU', 'iso_date', {}, 'INVALID_TO_DATE'),
    ('LIFNR', 'non_empty', {}, 'MISSING_VENDOR'),
    ('MATNR', 'material_number_format', {}, 'INVALID_MATERIAL'),
    ('VDATU', 'iso_date', {}, 'INVALID_FROM_DATE'),
    ('WERKS', 'werks_plant', {}, 'INVALID_PLANT'),
]

# Foreign keys — source_field -> registry object_type
FK_FIELDS = {
    'LIFNR': 'Vendor',
    'MATNR': 'Material',
    'WERKS': 'Plant',
}

# Verify key contract for the post-load Reconciler
VERIFY_KEY_FIELD = 'MATNR'
VERIFY_VALUE_FIELDS = ['WERKS', 'LIFNR', 'VDATU', 'BDATU']

# Resolved at runtime from version_matrix.py; falls back to default_bapi.
DEFAULT_BAPI = 'BAPI_SRCLIST_CHANGE_MULTI'
VERSION_BAPI_MAP = {
    'S4HANA_2020': 'BAPI_SRCLIST_CHANGE_MULTI',
    'S4HANA_2022': 'BAPI_SRCLIST_CHANGE_MULTI',
}


# Dispatch table for DQ rules — built once at import time.
_RULE_FNS = {
    'iso_date': iso_date,
    'material_number_format': material_number_format,
    'non_empty': non_empty,
    'werks_plant': werks_plant,
}


@register_spine
class SourceListSpineOrchestrator(BaseSpineOrchestrator):
    """Master object spine for SourceList.

    Generated from definitions/SourceList.json. Honours the
    BaseSpineOrchestrator lifecycle: transform -> validate -> resolve_fk
    -> build_payload -> call_bapi -> register_key -> fan_out_to_sinks.
    """

    object_type           = 'SourceList'
    source_key_field      = 'MATNR'
    extension_structure   = 'BAPI_TE_EORD'
    fk_fields             = FK_FIELDS
    home_table            = 'EORD'

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
    def build_payload(self, row: dict, ext_rows: list) -> dict:
        header = {}
        for src, tgt in FIELD_MAPS.items():
            v = row.get(src)
            if v is None:
                continue
            # Apply value_map if one is registered for this target field
            vmap = VALUE_MAPS.get(tgt)
            if vmap and str(v) in vmap:
                v = vmap[str(v)]
            header[tgt] = v

        payload: dict = {
            'SRCLIST_DATA': header,
            "_src_key": row.get(self.source_key_field, ""),
        }

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

        target_key = (resp.get('MATNR') or "").strip()

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

        verify_key = {
            "table": self.home_table,
            "key":   {VERIFY_KEY_FIELD: target_key},
            "values": {fld: payload.get('SRCLIST_DATA', {}).get(fld, "")
                       for fld in VERIFY_VALUE_FIELDS},
        }
        return target_key, msgs, DISP_CREATED, verify_key
