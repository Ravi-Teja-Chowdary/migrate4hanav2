"""
test_accounting_document_spine — GENERATED FROM definitions/AccountingDocument.json

DO NOT EDIT BY HAND. Re-run `python -m scaffolder.build AccountingDocument` to
regenerate after editing the JSON definition.

These tests exercise the contract surface the BaseSpineOrchestrator guarantees
plus the definition-specific DQ gates and FK resolution. They use a FakeRfcConn
that records `.call()` invocations so we can assert what the spine asked SAP to
do without hitting a live system.

Generator:  migrate4hana scaffolder v1.0.0
Source SHA: cf01a77373666231b2c33c05167111ad811dd2d2492ef9714ca56084581f7728
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

from accounting_document_spine import AccountingDocumentSpineOrchestrator  # noqa: E402
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
            'OBJ_KEY': kwargs.get("_src_key", "T0001"),
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
    return {'BELNR': 'BELNR_T0001', 'BKTXT': 'X', 'BLART': 'X', 'BLDAT': '20260614', 'BUDAT': '20260614', 'BUKRS': '1010', 'USNAM': 'X'}


def _make(conn=None, key_map=None, dry_run=False):
    return AccountingDocumentSpineOrchestrator(
        conn      = conn or FakeRfcConn(),
        key_map   = key_map,
        dry_run   = dry_run,
        target_release = "S4HANA_2022",
    )


# ── Contract: registration ──────────────────────────────────────────────────
def test_object_type_registered():
    from base_spine_orchestrator import get_spine
    cls = get_spine('AccountingDocument')
    assert cls is AccountingDocumentSpineOrchestrator


def test_class_attributes_match_definition():
    assert AccountingDocumentSpineOrchestrator.object_type      == 'AccountingDocument'
    assert AccountingDocumentSpineOrchestrator.source_key_field == 'BELNR'
    assert AccountingDocumentSpineOrchestrator.home_table       == 'BKPF'


# ── Contract: dry_run never calls SAP ───────────────────────────────────────
def test_dry_run_returns_created_without_calling_bapi():
    conn = FakeRfcConn()
    spine = _make(conn=conn, dry_run=True)
    result = spine.load_one(_sample_row())
    assert result.status == DISP_CREATED
    # In dry-run the spine still walks transform/validate/resolve_fk but skips
    # call_bapi entirely.
    assert all(c[0] != 'BAPI_ACC_DOCUMENT_POST' for c in conn.calls)


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
    assert vk["table"] == 'BKPF'
    assert 'BELNR' in vk["key"]


# ── Contract: BAPI failure rolls back + dead-letters ────────────────────────
def test_bapi_failure_triggers_rollback_and_dead_letter():
    conn = FakeRfcConn(responses={
        'BAPI_ACC_DOCUMENT_POST': {
            "RETURN": [{"TYPE": "E", "MESSAGE": "Synthetic BAPI failure"}],
            'OBJ_KEY': "",
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
    km = FakeKeyMap(seed={('AccountingDocument', src_key): "EXISTING_TGT"})
    conn = FakeRfcConn()
    spine = _make(conn=conn, key_map=km)
    result = spine.load_one(_sample_row())
    # Ledger hit → status matched_existing, BAPI was NOT called
    assert result.status == DISP_MATCHED_EXISTING
    assert result.target_key == "EXISTING_TGT"
    assert all(c[0] != 'BAPI_ACC_DOCUMENT_POST' for c in conn.calls)


# ── Definition-specific: DQ gates ──────────────────────────────────────────
def test_dq_gate_belnr_missing_doc_number_dead_letters():
    row = _sample_row()
    row['BELNR'] = ""        # force the DQ gate to trip
    spine = _make()
    result = spine.load_one(row)
    assert result.status == DISP_DEAD_LETTER
    assert result.dead_letter == DEAD_LETTER_DQ
    assert any('MISSING_DOC_NUMBER' in m for m in result.messages)

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
