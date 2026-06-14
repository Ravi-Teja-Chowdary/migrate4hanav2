"""Unit tests for mc_job_trigger — strategy chaining + status polling."""
from __future__ import annotations

import sys
import os
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import mc_job_trigger as mjt


class _FakeConn:
    """Stub pyrfc.Connection with deterministic call() behavior."""
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def call(self, fm, **kwargs):
        self.calls.append((fm, kwargs))
        if fm not in self.responses:
            raise RuntimeError(f"FU_NOT_FOUND for {fm}")
        resp = self.responses[fm]
        if isinstance(resp, Exception):
            raise resp
        return resp

    def get_connection_attributes(self):
        return {"partnerHost": "vhcals4h", "host": "vhcals4h"}

    def close(self):
        pass


def test_strategy_a_ltmc_api_success(monkeypatch):
    """When LTMC_API_OBJ_TRANSFER returns DONE, we take strategy A and stop."""
    monkeypatch.setattr(mjt, "_fetch_s3_object_as_lines",
                         lambda uri: ["KTOPL,SAKNR", "YIKR,0000100001"])
    conn = _FakeConn(responses={
        "LTMC_API_OBJ_TRANSFER": {
            "EV_JOB_ID": "JOB-001", "EV_STATUS": "DONE",
            "EV_ROWS_LOADED": 1,
            "ET_LOG": [{"TYPE": "S", "MESSAGE": "row loaded"}],
        }
    })
    res = mjt.trigger_mc_load(conn, "PROJ", "GLAccount",
                                "s3://b/k.csv", correlation_id="run-1",
                                wait_for_complete=False)
    assert res["mechanism"] == "ltmc_api"
    assert res["job_id"]    == "JOB-001"
    assert res["status"]    == "DONE"
    assert res["rows_loaded"] == 1
    assert len(res["strategy_attempts"]) == 1
    assert res["strategy_attempts"][0]["ok"] is True


def test_falls_back_to_xbp_when_ltmc_and_odata_unavailable(monkeypatch):
    """LTMC_API and OData unavailable → strategy C (XBP) runs."""
    monkeypatch.setattr(mjt, "_fetch_s3_object_as_lines",
                         lambda uri: ["a", "b"])
    conn = _FakeConn(responses={
        "BAPI_XBP_JOB_OPEN":             {"JOBNAME": "M4H_MC_GLAccount", "JOBCOUNT": "00001"},
        "BAPI_XBP_JOB_ADD_ABAP_STEP":    {},
        "BAPI_XBP_JOB_CLOSE":            {},
        "BAPI_XBP_JOB_START_IMMEDIATELY": {},
    })
    # No requests module path needed for OData attempt; without M4H_S4_PASS
    # it short-circuits to "no OData credentials"
    res = mjt.trigger_mc_load(conn, "PROJ", "GLAccount",
                                "s3://b/k.csv", correlation_id="run-2",
                                wait_for_complete=False)
    assert res["mechanism"] == "xbp_job"
    assert res["job_id"]    == "M4H_MC_GLAccount/00001"
    assert res["status"]    == "RUNNING"
    # All three strategies attempted
    assert [a["strategy"] for a in res["strategy_attempts"]] == ["ltmc_api", "odata", "xbp_job"]
    assert res["strategy_attempts"][0]["ok"] is False
    assert res["strategy_attempts"][1]["ok"] is False
    assert res["strategy_attempts"][2]["ok"] is True


def test_all_strategies_fail_returns_unavailable(monkeypatch):
    """No strategy works → mechanism=unavailable with full diagnostic."""
    monkeypatch.setattr(mjt, "_fetch_s3_object_as_lines", lambda uri: ["x"])
    conn = _FakeConn(responses={})    # nothing exists
    res = mjt.trigger_mc_load(conn, "PROJ", "GLAccount", "s3://b/k.csv",
                                wait_for_complete=False)
    assert res["mechanism"] == "unavailable"
    assert res["status"]    == "FAILED"
    assert res["job_id"] is None
    assert "remediation_hint" in res
    assert len(res["strategy_attempts"]) == 3


def test_poll_mc_status_xbp_eventual_done(monkeypatch):
    """Poll loop: first response RUNNING, second DONE."""
    monkeypatch.setattr(mjt, "POLL_INITIAL_SECS", 0)
    monkeypatch.setattr(mjt, "POLL_MAX_SECS",     0)
    monkeypatch.setattr(mjt, "POLL_BACKOFF",      1)

    call_count = {"n": 0}
    def _xbp_status(**kwargs):
        call_count["n"] += 1
        return {"STATUS": "F" if call_count["n"] >= 2 else "R"}

    conn = MagicMock()
    conn.call.side_effect = lambda fm, **kw: (_xbp_status(**kw)
                                                if fm == "BAPI_XBP_JOB_STATUS_GET"
                                                else {})
    res = mjt.poll_mc_status(conn, "M4H_MC_X/00001", "xbp_job", timeout_secs=2)
    assert res["status"] == "DONE"
    assert call_count["n"] >= 2


def test_status_normalization():
    assert mjt._normalize_status("DONE")       == "DONE"
    assert mjt._normalize_status("completed")  == "DONE"
    assert mjt._normalize_status("F")          == "DONE"
    assert mjt._normalize_status("FAILED")     == "FAILED"
    assert mjt._normalize_status("running")    == "RUNNING"
    assert mjt._normalize_status("R")          == "RUNNING"
    assert mjt._normalize_status("")           == ""
    assert mjt._normalize_status("UNKNOWN")    == "UNKNOWN"


def test_finalize_no_wait_returns_immediately(monkeypatch):
    """wait_for_complete=False → no polling, returns initial status."""
    res_a = {"job_id": "X", "status": "RUNNING", "rows_loaded": 0,
              "log_lines": [], "errors": []}
    out = mjt._finalize(res_a, "ltmc_api", "run-x", [], 0.0,
                         target_conn=MagicMock(),
                         wait_for_complete=False, timeout_secs=10)
    assert out["status"] == "RUNNING"
    assert out["mechanism"] == "ltmc_api"
