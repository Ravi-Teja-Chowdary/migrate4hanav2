"""
inventory_reservation_spine — GENERATED FROM definitions/InventoryReservation.json
======================================================================

DO NOT EDIT BY HAND. Re-run `python -m scaffolder.build InventoryReservation` to
regenerate after editing the JSON definition.

Generator:    migrate4hana scaffolder v1.0.0
Source SHA:   2fe0ae544a0c234d240b9011a5dd31cea6b46c911e0f07e87fbae434ee33adb0
Object type:  InventoryReservation
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
from dq_rules.iso_date import iso_date
from dq_rules.material_number_format import material_number_format
from dq_rules.non_empty import non_empty
from dq_rules.positive_number import positive_number
from dq_rules.sap_unit_of_measure import sap_unit_of_measure
from dq_rules.werks_plant import werks_plant

# ─────────────────────────────────────────────────────────────────────────────
# Field maps lifted from the JSON definition
# ─────────────────────────────────────────────────────────────────────────────
# HEADER fields — populate the BAPI header struct (RESERVATIONHEADER)
FIELD_MAPS = {
    'BDTER': 'RES_DATE',
    'BSART': 'MOVE_TYPE',
}

# ITEM fields — populate the BAPI items table (RESERVATIONITEMS).
# Empty for master objects whose BAPI is single-struct (no items table).
ITEM_FIELD_MAPS = {
    'BDMNG': 'ENTRY_QNT',
    'LGORT': 'STGE_LOC',
    'MATNR': 'MATERIAL',
    'MEINS': 'ENTRY_UOM',
    'WERKS': 'PLANT',
}

# target_field -> { source_value: target_value }
VALUE_MAPS = {
    'MOVE_TYPE': {
        'AR': '201',
        'BB': '261',
        'VALUE': '101',
        'ZZAR': '201',
    },
}

# DQ gates — (field, rule_name, rule_args, dead_letter_code)
DQ_GATES = [
    ('BDMNG', 'positive_number', {}, 'INVALID_QUANTITY'),
    ('BDTER', 'iso_date', {}, 'INVALID_REQ_DATE'),
    ('MATNR', 'material_number_format', {}, 'INVALID_MATERIAL'),
    ('MEINS', 'sap_unit_of_measure', {}, 'INVALID_UOM'),
    ('RSNUM', 'non_empty', {}, 'MISSING_RES_NUMBER'),
    ('WERKS', 'werks_plant', {}, 'INVALID_PLANT'),
]

# Foreign keys — source_field -> registry object_type
FK_FIELDS = {
    'MATNR': 'Material',
    'WERKS': 'Plant',
}

# Verify key contract for the post-load Reconciler
VERIFY_KEY_FIELD = 'RSNUM'
VERIFY_VALUE_FIELDS = ['MATNR', 'BDMNG', 'WERKS']

# Resolved at runtime from version_matrix.py; falls back to default_bapi.
DEFAULT_BAPI = 'BAPI_RESERVATION_CREATE1'
VERSION_BAPI_MAP = {
    'ECC60_EHP1': 'BAPI_RESERVATION_CREATE1',
    'ECC60_EHP6': 'BAPI_RESERVATION_CREATE1',
    'S4HANA_2020': 'BAPI_RESERVATION_CREATE1',
    'S4HANA_2022': 'BAPI_RESERVATION_CREATE1',
}


# Dispatch table for DQ rules — built once at import time.
_RULE_FNS = {
    'iso_date': iso_date,
    'material_number_format': material_number_format,
    'non_empty': non_empty,
    'positive_number': positive_number,
    'sap_unit_of_measure': sap_unit_of_measure,
    'werks_plant': werks_plant,
}


@register_spine
class InventoryReservationSpineOrchestrator(BaseSpineOrchestrator):
    """Transactional object spine for InventoryReservation.

    Generated from definitions/InventoryReservation.json. Honours the
    BaseSpineOrchestrator lifecycle: transform -> validate -> resolve_fk
    -> build_payload -> call_bapi -> register_key -> fan_out_to_sinks.
    """

    object_type           = 'InventoryReservation'
    source_key_field      = 'RSNUM'
    extension_structure   = ''
    fk_fields             = FK_FIELDS
    home_table            = 'RESB'

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
        if 'RESERVATIONHEADER':
            header = self._apply_field_map(row, FIELD_MAPS)
            payload['RESERVATIONHEADER'] = header

        # If the BAPI is two-struct (header + items table), build the item from
        # ITEM_FIELD_MAPS and place it as a single-element list. The "one row =
        # one item" pattern is the smoke-test shape; production loaders that
        # aggregate N source rows into one parent header are out of scope here.
        if ITEM_FIELD_MAPS:
            item = self._apply_field_map(row, ITEM_FIELD_MAPS)
            payload['RESERVATIONITEMS'] = [item]

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

        target_key = (resp.get('RESERVATION') or "").strip()

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
        # of item struct when the BAPI is items-only.
        if 'RESERVATIONHEADER':
            value_source = payload.get('RESERVATIONHEADER', {}) or {}
        elif ITEM_FIELD_MAPS:
            items = payload.get('RESERVATIONITEMS', []) or []
            value_source = items[0] if items else {}
        else:
            value_source = {}
        verify_key = {
            "table": self.home_table,
            "key":   {VERIFY_KEY_FIELD: target_key},
            "values": {fld: value_source.get(fld, "") for fld in VERIFY_VALUE_FIELDS},
        }
        return target_key, msgs, DISP_CREATED, verify_key
