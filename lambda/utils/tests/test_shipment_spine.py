"""
test_shipment_spine — GENERATED FROM definitions/Shipment.json

DO NOT EDIT BY HAND. Re-run `python -m scaffolder.build Shipment` to
regenerate after editing the JSON definition.

These tests exercise the contract surface the BaseSpineOrchestrator guarantees
plus the definition-specific DQ gates and FK resolution. They use a FakeRfcConn
that records `.call()` invocations so we can assert what the spine asked SAP to
do without hitting a live system.

Generator:  migrate4hana scaffolder v1.0.0
Source SHA: d8543555fd81993d1841f4ec98240264a04ba979e2369a23610b30473c0b829c
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

from shipment_spine import ShipmentSpineOrchestrator  # noqa: E402
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
            'TRANSPORT': kwargs.get("_src_key", "T0001"),
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
    return {'ROUTE': 'X', 'SHTYP': 'value', 'TKNUM': 'TKNUM_T0001', 'TPLST': 'value', 'VSART': 'X'}


def _make(conn=None, key_map=None, dry_run=False):
    return ShipmentSpineOrchestrator(
        conn      = conn or FakeRfcConn(),
        key_map   = key_map,
        dry_run   = dry_run,
        target_release = "S4HANA_2022",
    )


# ── Contract: registration ──────────────────────────────────────────────────
def test_object_type_registered():
    from base_spine_orchestrator import get_spine
    cls = get_spine('Shipment')
    assert cls is ShipmentSpineOrchestrator


def test_class_attributes_match_definition():
    assert ShipmentSpineOrchestrator.object_type      == 'Shipment'
    assert ShipmentSpineOrchestrator.source_key_field == 'TKNUM'
    assert ShipmentSpineOrchestrator.home_table       == 'VTTK'


# ── Contract: dry_run never calls SAP ───────────────────────────────────────
def test_dry_run_returns_created_without_calling_bapi():
    conn = FakeRfcConn()
    spine = _make(conn=conn, dry_run=True)
    result = spine.load_one(_sample_row())
    assert result.status == DISP_CREATED
    # In dry-run the spine still walks transform/validate/resolve_fk but skips
    # call_bapi entirely.
    assert all(c[0] != 'BAPI_SHIPMENT_CREATE' for c in conn.calls)


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
    assert vk["table"] == 'VTTK'
    assert 'TKNUM' in vk["key"]


# ── Contract: BAPI failure rolls back + dead-letters ────────────────────────
def test_bapi_failure_triggers_rollback_and_dead_letter():
    conn = FakeRfcConn(responses={
        'BAPI_SHIPMENT_CREATE': {
            "RETURN": [{"TYPE": "E", "MESSAGE": "Synthetic BAPI failure"}],
            'TRANSPORT': "",
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
    src_key = _sample_row()['TKNUM']
    km = FakeKeyMap(seed={('Shipment', src_key): "EXISTING_TGT"})
    conn = FakeRfcConn()
    spine = _make(conn=conn, key_map=km)
    result = spine.load_one(_sample_row())
    # Ledger hit → status matched_existing, BAPI was NOT called
    assert result.status == DISP_MATCHED_EXISTING
    assert result.target_key == "EXISTING_TGT"
    assert all(c[0] != 'BAPI_SHIPMENT_CREATE' for c in conn.calls)


# ── Definition-specific: DQ gates ──────────────────────────────────────────
def test_dq_gate_shtyp_missing_shipment_type_dead_letters():
    row = _sample_row()
    row['SHTYP'] = ""        # force the DQ gate to trip
    spine = _make()
    result = spine.load_one(row)
    assert result.status == DISP_DEAD_LETTER
    assert result.dead_letter == DEAD_LETTER_DQ
    assert any('MISSING_SHIPMENT_TYPE' in m for m in result.messages)

def test_dq_gate_tknum_missing_shipment_no_dead_letters():
    row = _sample_row()
    row['TKNUM'] = ""        # force the DQ gate to trip
    spine = _make()
    result = spine.load_one(row)
    assert result.status == DISP_DEAD_LETTER
    assert result.dead_letter == DEAD_LETTER_DQ
    assert any('MISSING_SHIPMENT_NO' in m for m in result.messages)

def test_dq_gate_tplst_missing_trans_plan_pt_dead_letters():
    row = _sample_row()
    row['TPLST'] = ""        # force the DQ gate to trip
    spine = _make()
    result = spine.load_one(row)
    assert result.status == DISP_DEAD_LETTER
    assert result.dead_letter == DEAD_LETTER_DQ
    assert any('MISSING_TRANS_PLAN_PT' in m for m in result.messages)


# ── Definition-specific: FK resolution ──────────────────────────────────────
# No FK fields declared for this object.


# ── Definition-specific: value_maps applied ────────────────────────────────
# No value_maps declared for this object.


# ── Extension overflow guard (base contract) ───────────────────────────────
# This object does not declare an extension_structure; no overflow test.
