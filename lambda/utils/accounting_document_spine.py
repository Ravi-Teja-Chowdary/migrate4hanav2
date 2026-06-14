"""
accounting_document_spine — GENERATED FROM definitions/AccountingDocument.json
======================================================================

DO NOT EDIT BY HAND. Re-run `python -m scaffolder.build AccountingDocument` to
regenerate after editing the JSON definition.

Generator:    migrate4hana scaffolder v1.0.0
Source SHA:   5088a2374f766b8e93e4724636baac9f1673b1908f2ed33e3bcc3ac7a71c3fe2
Object type:  AccountingDocument
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
from dq_rules.bukrs_company_code import bukrs_company_code
from dq_rules.currency_iso_4217 import currency_iso_4217
from dq_rules.iso_date import iso_date
from dq_rules.non_empty import non_empty
from dq_rules.positive_number import positive_number

# ─────────────────────────────────────────────────────────────────────────────
# Field maps lifted from the JSON definition
# ─────────────────────────────────────────────────────────────────────────────
# HEADER fields — populate the BAPI header struct (DOCUMENTHEADER)
FIELD_MAPS = {
    'BKTXT': 'HEADER_TXT',
    'BLART': 'DOC_TYPE',
    'BLDAT': 'DOC_DATE',
    'BUDAT': 'PSTNG_DATE',
    'BUKRS': 'COMP_CODE',
    'USNAM': 'USERNAME',
}

# ITEM fields — populate the BAPI items table (CURRENCYAMOUNT).
# Empty for master objects whose BAPI is single-struct (no items table).
ITEM_FIELD_MAPS = {
    'AMT_DOCCUR': 'AMT_DOCCUR',
    'CURRENCY': 'CURRENCY',
    'ITEMNO_ACC': 'ITEMNO_ACC',
}

# target_field -> { source_value: target_value }
VALUE_MAPS = {
}

# DQ gates — (field, rule_name, rule_args, dead_letter_code)
DQ_GATES = [
    ('AMT_DOCCUR', 'positive_number', {}, 'INVALID_AMOUNT'),
    ('BELNR', 'non_empty', {}, 'MISSING_DOC_NUMBER'),
    ('BKTXT', 'non_empty', {}, 'MISSING_HEADER_TXT'),
    ('BLDAT', 'iso_date', {}, 'INVALID_DOC_DATE'),
    ('BUDAT', 'iso_date', {}, 'INVALID_PSTNG_DATE'),
    ('BUKRS', 'bukrs_company_code', {}, 'INVALID_COMPANY_CODE'),
    ('CURRENCY', 'currency_iso_4217', {}, 'INVALID_CURRENCY'),
    ('ITEMNO_ACC', 'positive_number', {}, 'MISSING_ITEM_NO'),
    ('USNAM', 'non_empty', {}, 'MISSING_USERNAME'),
]

# Foreign keys — source_field -> registry object_type
FK_FIELDS = {
    'BUKRS': 'CompanyCode',
}

# Verify key contract for the post-load Reconciler
VERIFY_KEY_FIELD = 'BELNR'
VERIFY_VALUE_FIELDS = ['BUKRS', 'BUDAT']

# Resolved at runtime from version_matrix.py; falls back to default_bapi.
DEFAULT_BAPI = 'BAPI_ACC_DOCUMENT_POST'
VERSION_BAPI_MAP = {
    'S4HANA_2020': 'BAPI_ACC_DOCUMENT_POST',
    'S4HANA_2022': 'BAPI_ACC_DOCUMENT_POST',
}


# Dispatch table for DQ rules — built once at import time.
_RULE_FNS = {
    'bukrs_company_code': bukrs_company_code,
    'currency_iso_4217': currency_iso_4217,
    'iso_date': iso_date,
    'non_empty': non_empty,
    'positive_number': positive_number,
}


@register_spine
class AccountingDocumentSpineOrchestrator(BaseSpineOrchestrator):
    """Transactional object spine for AccountingDocument.

    Generated from definitions/AccountingDocument.json. Honours the
    BaseSpineOrchestrator lifecycle: transform -> validate -> resolve_fk
    -> build_payload -> call_bapi -> register_key -> fan_out_to_sinks.
    """

    object_type           = 'AccountingDocument'
    source_key_field      = 'BELNR'
    extension_structure   = ''
    fk_fields             = FK_FIELDS
    home_table            = 'BKPF'

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
            'DOCUMENTHEADER': header,
            "_src_key": row.get(self.source_key_field, ""),
        }

        # If the BAPI is two-struct (header + items table), build the item from
        # ITEM_FIELD_MAPS and place it as a single-element list. The "one row =
        # one item" pattern is the smoke-test shape; production loaders that
        # aggregate N source rows into one parent header are out of scope here.
        if ITEM_FIELD_MAPS:
            item = self._apply_field_map(row, ITEM_FIELD_MAPS)
            payload['CURRENCYAMOUNT'] = [item]

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

        target_key = (resp.get('OBJ_KEY') or "").strip()

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
            "values": {fld: payload.get('DOCUMENTHEADER', {}).get(fld, "")
                       for fld in VERIFY_VALUE_FIELDS},
        }
        return target_key, msgs, DISP_CREATED, verify_key
