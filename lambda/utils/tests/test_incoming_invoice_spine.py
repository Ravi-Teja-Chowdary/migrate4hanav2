"""
test_incoming_invoice_spine — GENERATED FROM definitions/IncomingInvoice.json

DO NOT EDIT BY HAND. Re-run `python -m scaffolder.build IncomingInvoice` to
regenerate after editing the JSON definition.

These tests exercise the contract surface the BaseSpineOrchestrator guarantees
plus the definition-specific DQ gates and FK resolution. They use a FakeRfcConn
that records `.call()` invocations so we can assert what the spine asked SAP to
do without hitting a live system.

Generator:  migrate4hana scaffolder v1.0.0
Source SHA: ff73607070254cfd2d4585d1c469762391ffcc267abeccc897f8463f421e06ba
"""
from __future__ import annotations

import sys
import os

import pytest


# Ensure ``lambda/utils`` is on sys.path so the spine + base + dq_rules import.
HERE = os.path.dirname(os.path.abspath(__file__))
UTILS = os.path.abspath(os.path.join(HERE, ".."))
if UTILS not in sys.path:
    sys.path.insert(0, UTILS)

from incoming_invoice_spine import IncomingInvoiceSpineOrchestrator  # noqa: E402
from base_spine_orchestrator import (                  # noqa: E402
    DISP_CREATED, DISP_DEAD_LETTER, DISP_MATCHED_EXISTING,
    DEAD_LETTER_DQ, DEAD_LETTER_FK, DEAD_LETTER_BAPI,
)


# ── Test fixtures ───────────────────────────────────────────────────────────
class FakeRfcConn:
    """Records every .call(); returns canned responses by function name."""
    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def call(self, fn_name, **kwargs):
        self.calls.append((fn_name, kwargs))
        if fn_name in self.responses:
            return self.responses[fn_name]
        # Default: BAPI succeeded with target_key = source_key
        return {
            "RETURN": [{"TYPE": "S", "MESSAGE": "OK"}],
            'INVOICEDOCNUMBER': kwargs.get("_src_key", "T0001"),
        }


class FakeKeyMap:
    """In-memory PersistentKeyMap stand-in for unit tests."""
    def __init__(self, seed=None):
        self._m = dict(seed or {})
        self.added = []

    def resolve(self, obj, src):
        return self._m.get((obj, src))

    def add(self, obj, src, tgt, disposition=""):
        self._m[(obj, src)] = tgt
        self.added.append((obj, src, tgt, disposition))


def _sample_row():
    """Minimal row that should pass all DQ gates + FK checks."""
    return {'BELNR': 'BELNR_T0001', 'BLART': 'X', 'BLDAT': '20260614', 'BUDAT': '20260614', 'BUKRS': '1010', 'INVOICE_DOC_ITEM': '1', 'ITEM_AMOUNT': '1', 'RMWWR': '1', 'TAX_CODE': 'X', 'WAERS': 'USD', 'XBLNR': 'X'}


def _make(conn=None, key_map=None, dry_run=False):
    return IncomingInvoiceSpineOrchestrator(
        conn      = conn or FakeRfcConn(),
        key_map   = key_map,
        dry_run   = dry_run,
        target_release = "S4HANA_2022",
    )


# ── Contract: registration ──────────────────────────────────────────────────
def test_object_type_registered():
    from base_spine_orchestrator import get_spine
    cls = get_spine('IncomingInvoice')
    assert cls is IncomingInvoiceSpineOrchestrator


def test_class_attributes_match_definition():
    assert IncomingInvoiceSpineOrchestrator.object_type      == 'IncomingInvoice'
    assert IncomingInvoiceSpineOrchestrator.source_key_field == 'BELNR'
    assert IncomingInvoiceSpineOrchestrator.home_table       == 'RBKP'


# ── Contract: dry_run never calls SAP ───────────────────────────────────────
def test_dry_run_returns_created_without_calling_bapi():
    conn = FakeRfcConn()
    spine = _make(conn=conn, dry_run=True)
    result = spine.load_one(_sample_row())
    assert result.status == DISP_CREATED
    # In dry-run the spine still walks transform/validate/resolve_fk but skips
    # call_bapi entirely.
    assert all(c[0] != 'BAPI_INCOMINGINVOICE_CREATE' for c in conn.calls)


# ── Contract: BAPI success path ─────────────────────────────────────────────
def test_load_one_success_returns_target_key():
    spine = _make()
    result = spine.load_one(_sample_row())
    assert result.status in (DISP_CREATED, DISP_MATCHED_EXISTING)
    assert result.target_key
    assert result.dead_letter is None


def test_verify_key_shape_matches_reconciler_input():
    spine = _make()
    result = spine.load_one(_sample_row())
    vk = result.verify_key
    assert vk is not None
    assert vk["table"] == 'RBKP'
    assert 'BELNR' in vk["key"]


# ── Contract: BAPI failure rolls back + dead-letters ────────────────────────
def test_bapi_failure_triggers_rollback_and_dead_letter():
    conn = FakeRfcConn(responses={
        'BAPI_INCOMINGINVOICE_CREATE': {
            "RETURN": [{"TYPE": "E", "MESSAGE": "Synthetic BAPI failure"}],
            'INVOICEDOCNUMBER': "",
        }
    })
    spine = _make(conn=conn)
    result = spine.load_one(_sample_row())
    assert result.status == DISP_DEAD_LETTER
    assert result.dead_letter == DEAD_LETTER_BAPI
    # Rollback must have been attempted
    assert any(c[0] == "BAPI_TRANSACTION_ROLLBACK" for c in conn.calls)


# ── Contract: idempotent replay via ledger short-circuit ───────────────────
def test_idempotent_replay_hits_ledger_short_circuit():
    src_key = _sample_row()['BELNR']
    km = FakeKeyMap(seed={('IncomingInvoice', src_key): "EXISTING_TGT"})
    conn = FakeRfcConn()
    spine = _make(conn=conn, key_map=km)
    result = spine.load_one(_sample_row())
    # Ledger hit → status matched_existing, BAPI was NOT called
    assert result.status == DISP_MATCHED_EXISTING
    assert result.target_key == "EXISTING_TGT"
    assert all(c[0] != 'BAPI_INCOMINGINVOICE_CREATE' for c in conn.calls)


# ── Definition-specific: DQ gates ──────────────────────────────────────────
def test_dq_gate_belnr_missing_invoice_doc_dead_letters():
    row = _sample_row()
    row['BELNR'] = ""        # force the DQ gate to trip
    spine = _make()
    result = spine.load_one(row)
    assert result.status == DISP_DEAD_LETTER
    assert result.dead_letter == DEAD_LETTER_DQ
    assert any('MISSING_INVOICE_DOC' in m for m in result.messages)

def test_dq_gate_bldat_invalid_doc_date_dead_letters():
    row = _sample_row()
    row['BLDAT'] = ""        # force the DQ gate to trip
    spine = _make()
    result = spine.load_one(row)
    assert result.status == DISP_DEAD_LETTER
    assert result.dead_letter == DEAD_LETTER_DQ
    assert any('INVALID_DOC_DATE' in m for m in result.messages)

def test_dq_gate_budat_invalid_pstng_date_dead_letters():
    row = _sample_row()
    row['BUDAT'] = ""        # force the DQ gate to trip
    spine = _make()
    result = spine.load_one(row)
    assert result.status == DISP_DEAD_LETTER
    assert result.dead_letter == DEAD_LETTER_DQ
    assert any('INVALID_PSTNG_DATE' in m for m in result.messages)

def test_dq_gate_bukrs_invalid_company_code_dead_letters():
    row = _sample_row()
    row['BUKRS'] = ""        # force the DQ gate to trip
    spine = _make()
    result = spine.load_one(row)
    assert result.status == DISP_DEAD_LETTER
    assert result.dead_letter == DEAD_LETTER_DQ
    assert any('INVALID_COMPANY_CODE' in m for m in result.messages)

def test_dq_gate_invoice_doc_item_missing_item_no_dead_letters():
    row = _sample_row()
    row['INVOICE_DOC_ITEM'] = ""        # force the DQ gate to trip
    spine = _make()
    result = spine.load_one(row)
    assert result.status == DISP_DEAD_LETTER
    assert result.dead_letter == DEAD_LETTER_DQ
    assert any('MISSING_ITEM_NO' in m for m in result.messages)

def test_dq_gate_item_amount_invalid_item_amount_dead_letters():
    row = _sample_row()
    row['ITEM_AMOUNT'] = ""        # force the DQ gate to trip
    spine = _make()
    result = spine.load_one(row)
    assert result.status == DISP_DEAD_LETTER
    assert result.dead_letter == DEAD_LETTER_DQ
    assert any('INVALID_ITEM_AMOUNT' in m for m in result.messages)

def test_dq_gate_rmwwr_invalid_amount_dead_letters():
    row = _sample_row()
    row['RMWWR'] = ""        # force the DQ gate to trip
    spine = _make()
    result = spine.load_one(row)
    assert result.status == DISP_DEAD_LETTER
    assert result.dead_letter == DEAD_LETTER_DQ
    assert any('INVALID_AMOUNT' in m for m in result.messages)

def test_dq_gate_waers_invalid_currency_dead_letters():
    row = _sample_row()
    row['WAERS'] = ""        # force the DQ gate to trip
    spine = _make()
    result = spine.load_one(row)
    assert result.status == DISP_DEAD_LETTER
    assert result.dead_letter == DEAD_LETTER_DQ
    assert any('INVALID_CURRENCY' in m for m in result.messages)


# ── Definition-specific: FK resolution ──────────────────────────────────────
def test_fk_unresolved_dead_letters():
    """Empty key_map → first FK field unresolvable → DEAD_LETTER_FK.

    The sample row already has DQ-valid values for every FK source field
    (synthesized by the scaffolder), so the row clears DQ. With an empty
    FakeKeyMap, the FIRST FK field tried by resolve_fk has no target —
    base_spine_orchestrator returns the FK error string and dead-letters.
    """
    spine = _make(key_map=FakeKeyMap())
    row = _sample_row()
    result = spine.load_one(row)
    assert result.status == DISP_DEAD_LETTER
    assert result.dead_letter == DEAD_LETTER_FK


# ── Definition-specific: value_maps applied ────────────────────────────────
# No value_maps declared for this object.


# ── Extension overflow guard (base contract) ───────────────────────────────
# This object does not declare an extension_structure; no overflow test.
