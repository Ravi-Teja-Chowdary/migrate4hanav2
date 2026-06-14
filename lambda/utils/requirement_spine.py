"""
requirement_spine — GENERATED FROM definitions/Requirement.json
======================================================================

DO NOT EDIT BY HAND. Re-run `python -m scaffolder.build Requirement` to
regenerate after editing the JSON definition.

Generator:    migrate4hana scaffolder v1.0.0
Source SHA:   25750850a414a98dacec0fd91337436b97dcf8c0ea403f120bd1ef2d8968fcd4
Object type:  Requirement
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
from dq_rules.material_number_format import material_number_format
from dq_rules.positive_number import positive_number
from dq_rules.sap_unit_of_measure import sap_unit_of_measure
from dq_rules.werks_plant import werks_plant

# ─────────────────────────────────────────────────────────────────────────────
# Field maps lifted from the JSON definition
# ─────────────────────────────────────────────────────────────────────────────
# HEADER fields — populate the BAPI header struct (REQUIREMENTS_ITEM)
FIELD_MAPS = {
    'BDZEI': 'REQUIREMENTSTYPE',
    'MATNR': 'MATERIAL',
    'MEINS': 'BASE_UOM',
    'PLNMG': 'REQUIREMENT_QUANTITY',
    'VERSB': 'VERSION',
    'WERKS': 'PLANT',
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
    ('MATNR', 'material_number_format', {}, 'INVALID_MATERIAL'),
    ('MEINS', 'sap_unit_of_measure', {}, 'INVALID_UOM'),
    ('PLNMG', 'positive_number', {}, 'INVALID_QUANTITY'),
    ('WERKS', 'werks_plant', {}, 'INVALID_PLANT'),
]

# Foreign keys — source_field -> registry object_type
FK_FIELDS = {
    'MATNR': 'Material',
    'WERKS': 'Plant',
}

# Verify key contract for the post-load Reconciler
VERIFY_KEY_FIELD = 'MATNR'
VERIFY_VALUE_FIELDS = ['WERKS', 'PLNMG']

# Resolved at runtime from version_matrix.py; falls back to default_bapi.
DEFAULT_BAPI = 'BAPI_REQUIREMENTS_CREATE'
VERSION_BAPI_MAP = {
    'S4HANA_2020': 'BAPI_REQUIREMENTS_CREATE',
    'S4HANA_2022': 'BAPI_REQUIREMENTS_CREATE',
}


# Dispatch table for DQ rules — built once at import time.
_RULE_FNS = {
    'material_number_format': material_number_format,
    'positive_number': positive_number,
    'sap_unit_of_measure': sap_unit_of_measure,
    'werks_plant': werks_plant,
}


@register_spine
class RequirementSpineOrchestrator(BaseSpineOrchestrator):
    """Transactional object spine for Requirement.

    Generated from definitions/Requirement.json. Honours the
    BaseSpineOrchestrator lifecycle: transform -> validate -> resolve_fk
    -> build_payload -> call_bapi -> register_key -> fan_out_to_sinks.
    """

    object_type           = 'Requirement'
    source_key_field      = 'MATNR'
    extension_structure   = ''
    fk_fields             = FK_FIELDS
    home_table            = 'PBIM'

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
        header = self._apply_field_map(row, FIELD_MAPS)
        payload: dict = {
            'REQUIREMENTS_ITEM': header,
            "_src_key": row.get(self.source_key_field, ""),
        }

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

        target_key = (resp.get('REQMTSPLANNUMBER') or "").strip()

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
            "values": {fld: payload.get('REQUIREMENTS_ITEM', {}).get(fld, "")
                       for fld in VERIFY_VALUE_FIELDS},
        }
        return target_key, msgs, DISP_CREATED, verify_key
