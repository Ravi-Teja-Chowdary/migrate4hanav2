"""
service_master_spine — GENERATED FROM definitions/ServiceMaster.json
======================================================================

DO NOT EDIT BY HAND. Re-run `python -m scaffolder.build ServiceMaster` to
regenerate after editing the JSON definition.

Generator:    migrate4hana scaffolder v1.0.0
Source SHA:   8b9f779aecf3ed3fda544d4cabe90df2677ff17e394a3ebe5de7f447ae2332f5
Object type:  ServiceMaster
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
from dq_rules.non_empty import non_empty
from dq_rules.sap_unit_of_measure import sap_unit_of_measure

# ─────────────────────────────────────────────────────────────────────────────
# Field maps lifted from the JSON definition
# ─────────────────────────────────────────────────────────────────────────────
# HEADER fields — populate the BAPI header struct (IM_SERVICE_DATA)
FIELD_MAPS = {
    'ASNUM': 'SERVICE',
    'BASME': 'BASE_UOM',
    'MATKL': 'MATL_GROUP',
    'MEINS': 'BASE_UOM_ISO',
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
    ('ASNUM', 'non_empty', {}, 'MISSING_SERVICE_NUMBER'),
    ('BASME', 'sap_unit_of_measure', {}, 'INVALID_BASE_UOM'),
]

# Foreign keys — source_field -> registry object_type
FK_FIELDS = {
}

# Verify key contract for the post-load Reconciler
VERIFY_KEY_FIELD = 'ASNUM'
VERIFY_VALUE_FIELDS = ['MATKL', 'BASME']

# Resolved at runtime from version_matrix.py; falls back to default_bapi.
DEFAULT_BAPI = 'BAPI_SERVICE_CREATE'
VERSION_BAPI_MAP = {
    'S4HANA_2020': 'BAPI_SERVICE_CREATE',
    'S4HANA_2022': 'BAPI_SERVICE_CREATE',
}


# Dispatch table for DQ rules — built once at import time.
_RULE_FNS = {
    'non_empty': non_empty,
    'sap_unit_of_measure': sap_unit_of_measure,
}


@register_spine
class ServiceMasterSpineOrchestrator(BaseSpineOrchestrator):
    """Master object spine for ServiceMaster.

    Generated from definitions/ServiceMaster.json. Honours the
    BaseSpineOrchestrator lifecycle: transform -> validate -> resolve_fk
    -> build_payload -> call_bapi -> register_key -> fan_out_to_sinks.
    """

    object_type           = 'ServiceMaster'
    source_key_field      = 'ASNUM'
    extension_structure   = 'BAPI_TE_ASMD'
    fk_fields             = FK_FIELDS
    home_table            = 'ASMD'

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
            'IM_SERVICE_DATA': header,
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

        target_key = (resp.get('SERVICE') or "").strip()

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
            "values": {fld: payload.get('IM_SERVICE_DATA', {}).get(fld, "")
                       for fld in VERIFY_VALUE_FIELDS},
        }
        return target_key, msgs, DISP_CREATED, verify_key
