"""
inventory_reservation_spine — GENERATED FROM definitions/InventoryReservation.json
======================================================================

DO NOT EDIT BY HAND. Re-run `python -m scaffolder.build InventoryReservation` to
regenerate after editing the JSON definition.

Generator:    migrate4hana scaffolder v1.0.0
Source SHA:   72e1524f2185201fe34040af57955b2a6d760323e6df0a7f62458c0ffc3448a7
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
# source_field -> target_canonical_field
FIELD_MAPS = {
    'AUFNR': 'ORDER_NUMBER',
    'BDMNG': 'QUANTITY',
    'BDTER': 'REQUIREMENT_DATE',
    'BSART': 'DOC_TYPE',
    'CHARG': 'BATCH',
    'LGORT': 'STGE_LOC',
    'MATNR': 'MATERIAL',
    'MEINS': 'BASE_UOM',
    'RSNUM': 'RESERVATION_NUMBER',
    'WERKS': 'PLANT',
}

# target_field -> { source_value: target_value }
VALUE_MAPS = {
    'DOC_TYPE': {
        'AR': 'AR',
        'BB': 'BB',
        'ZZAR': 'AR',
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
VERIFY_VALUE_FIELDS = ['MATNR', 'BDMNG', 'WERKS', 'BDTER']

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
    extension_structure   = 'BAPI_TE_RESB'
    fk_fields             = FK_FIELDS
    home_table            = 'RKPF'

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
            'RESERVATION_HEADER': header,
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

        verify_key = {
            "table": self.home_table,
            "key":   {VERIFY_KEY_FIELD: target_key},
            "values": {fld: payload.get('RESERVATION_HEADER', {}).get(fld, "")
                       for fld in VERIFY_VALUE_FIELDS},
        }
        return target_key, msgs, DISP_CREATED, verify_key
