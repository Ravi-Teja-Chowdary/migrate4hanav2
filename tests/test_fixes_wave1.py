"""
Regression tests for the fix bundle (scrubber, AST round-trip, validator number
parsing, transport/BC-set SSH fallthrough, IDoc probe, data-migrator batch mode).

Runs without a live SAP system; pyrfc + boto3 are stubbed via the local shim.
"""
from __future__ import annotations
import os
import sys
import json
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lambda"))
sys.path.insert(0, str(REPO_ROOT / "lambda" / "utils"))
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("M4H_LOCAL_MODE", "1")
os.environ.setdefault("S3_STAGING_BUCKET", "m4h-local")
import local_aws_shim  # noqa: E402,F401


def _load(pkg: str, mod: str):
    path = REPO_ROOT / "lambda" / pkg / f"{mod}.py"
    if not path.exists():
        path = REPO_ROOT / f"{pkg}.py"
    spec = importlib.util.spec_from_file_location(f"{pkg}_{mod}_test", path)
    module = importlib.util.module_from_spec(spec)
    pkg_dir = REPO_ROOT / "lambda" / pkg
    if pkg_dir.is_dir():
        sys.path.insert(0, str(pkg_dir))
    try:
        spec.loader.exec_module(module)
    finally:
        if pkg_dir.is_dir():
            sys.path.pop(0)
    return module


# ── 1. Scrubber must NOT touch on-disk source ────────────────────────────────
def test_ast_remediation_preserves_string_literals():
    code_analyzer = _load("code-analyzer", "handler")
    src = "MOVE 'LH' TO carrid-low.\nAPPEND carrid TO itab.\nCALL FUNCTION 'BAPI_USER_GET_DETAIL'.\n"
    fixed_src, _changes = code_analyzer.auto_remediate_with_ast_engine(src)
    assert "<MASKED>" not in fixed_src
    assert "SCRUBBED_STRING" not in fixed_src
    assert "BAPI_USER_GET_DETAIL" in fixed_src
    assert "APPEND" in fixed_src.upper()


def test_scrubber_module_still_masks_when_called_directly():
    scrubber = _load("code-analyzer", "data_scrubber")
    out = scrubber.mask_payload_for_infosec("user = 'alice@example.com'.\n")
    assert "<MASKED>" in out
    assert "alice@example.com" not in out


# ── 1b. AST round-trip must not drop operands ────────────────────────────────
def test_ast_preserves_select_options_and_append():
    engine = _load("code-analyzer", "abap_ast_engine")
    src = (
        "REPORT ztest.\n"
        "SELECT-OPTIONS : so_dept FOR spfli-deptime.\n"
        "APPEND carrid.\n"
        "APPEND wa TO itab.\n"
    )
    out = engine.process_abap_file(src)["transformed_code"]
    assert "SELECT-OPTIONS : FOR ." not in out
    assert "TO .." not in out
    assert " = ." not in out
    assert "SO_DEPT" in out.upper()
    assert "SPFLI-DEPTIME" in out.upper()
    assert "APPEND CARRID" in out.upper()
    assert "ITAB" in out.upper()


def test_ast_ranges_declaration_does_not_crash_generation():
    """RANGES → 'DATA ... TYPE RANGE OF' morph must not lose generator attributes.
    Previously crashed with: 'DataDeclaration' object has no attribute 'is_structure_begin'."""
    engine = _load("code-analyzer", "abap_ast_engine")
    src = (
        "REPORT zranges.\n"
        "RANGES so_matnr FOR mara-matnr.\n"
        "DATA: BEGIN OF gs_x,\n"
        "        a TYPE c,\n"
        "      END OF gs_x.\n"
    )
    res = engine.process_abap_file(src)          # must not raise
    out = res["transformed_code"]
    assert "RANGE OF" in out                       # morph applied
    assert res["stats"]["parse_error_count"] == 0


def test_ast_safety_net_restores_lossy_line():
    engine = _load("code-analyzer", "abap_ast_engine")
    original = "REPORT z.\nAPPEND foo TO bar_table.\n"
    corrupted = "REPORT z.\nAPPEND foo TO ..\n"
    fixed = engine._reconcile_lossy_lines(original, corrupted)
    assert "TO .." not in fixed
    assert "bar_table" in fixed.lower()


# ── 2. parse_sap_number ──────────────────────────────────────────────────────
def test_parse_sap_number_trailing_minus():
    from sap_number import parse_sap_number
    assert parse_sap_number("123.90-") == -123.90
    assert parse_sap_number("0.01-") == -0.01
    assert parse_sap_number("  500-  ") == -500.0


def test_parse_sap_number_thousands_separator():
    from sap_number import parse_sap_number
    assert parse_sap_number("1,234.56") == 1234.56
    assert parse_sap_number("1.234,56") == 1234.56
    assert parse_sap_number("1,234,567.89") == 1234567.89


def test_parse_sap_number_edge_cases():
    from sap_number import parse_sap_number
    assert parse_sap_number(None) == 0.0
    assert parse_sap_number("") == 0.0
    assert parse_sap_number("garbage") == 0.0
    assert parse_sap_number("garbage", default=-1.0) == -1.0
    assert parse_sap_number(42) == 42.0
    assert parse_sap_number(42.5) == 42.5


# ── 3. transport-artifact-builder path selection ─────────────────────────────
def test_transport_builder_falls_through_to_manual_when_no_bastion(monkeypatch):
    builder = _load("transport-artifact-builder", "handler")

    class FakeConn:
        def call(self, fm, **kw):
            raise RuntimeError("FU_NOT_FOUND: TRINT_REQUEST_CREATE")

    monkeypatch.setattr(builder, "Connection", lambda **kw: FakeConn())
    monkeypatch.setattr(builder.secrets, "get_secret_value",
                        lambda **kw: {"SecretString": json.dumps({
                            "ashost": "h", "sysnr": "00", "client": "100",
                            "user": "u", "passwd": "p"})})
    written = {}
    monkeypatch.setattr(builder.s3, "put_object",
                        lambda **kw: written.update(kw) or {})

    res = builder.lambda_handler({
        "run_id": "TEST-001",
        "object_list": [{"object_type": "PROG", "object_name": "ZTEST"}],
        "source_creds_arn": "local:ecc",
    }, None)

    assert res["status"] == "manual_required"
    assert res["build_method"] == "manual"
    body = json.loads(written["Body"].decode())
    assert body["mode"] == "manual_assembly_required"
    assert body["ssh_available"] is False
    assert "TRINT_REQUEST_CREATE" in body["rfc_error"]


# ── 4. bc-set-builder path selection ─────────────────────────────────────────
def test_bc_set_builder_falls_through_to_manual_when_no_bastion(monkeypatch):
    bcset = _load("bc-set-builder", "handler")

    class FakeConn:
        def call(self, fm, **kw):
            raise RuntimeError("FU_NOT_FOUND: SCPR_API_BC_SET_CREATE")

    monkeypatch.setattr(bcset, "Connection", lambda **kw: FakeConn())
    monkeypatch.setattr(bcset.secrets, "get_secret_value",
                        lambda **kw: {"SecretString": json.dumps({
                            "ashost": "h", "sysnr": "00", "client": "100",
                            "user": "u", "passwd": "p"})})
    written = {}
    monkeypatch.setattr(bcset.s3, "put_object",
                        lambda **kw: written.update(kw) or {})

    res = bcset.lambda_handler({
        "run_id": "TEST-002",
        "config_groups": [{"name": "Financial", "tables": ["T001", "T004"]}],
        "build_creds_arn": "local:target",
    }, None)

    assert res["status"] == "manual_required"
    assert res["build_method"] == "manual"
    body = json.loads(written["Body"].decode())
    assert body["mode"] == "manual_creation_required"
    assert body["ssh_available"] is False


# ── 4b. sap_fields probe (FIELD_NOT_VALID fix) ───────────────────────────────
def test_valid_fields_intersects_with_dd03l():
    from sap_fields import valid_fields, _FIELD_CACHE
    _FIELD_CACHE.clear()

    class Conn:
        def call(self, fm, **kw):
            assert kw.get("QUERY_TABLE") == "DD03L"
            # T001 really has MANDT, BUKRS, BUTXT, WAERS — but NOT 'BOGUS'
            return {"DATA": [{"WA": f} for f in ["MANDT", "BUKRS", "BUTXT", "WAERS", ".INCLUDE"]]}

    kept = valid_fields(Conn(), "T001", ["BUKRS", "BUTXT", "WAERS", "BOGUS"])
    assert kept == ["BUKRS", "BUTXT", "WAERS"]      # BOGUS dropped, order preserved
    assert "BUKRS" in kept                           # key never wrongly stripped


def test_valid_fields_falls_back_when_probe_empty():
    from sap_fields import valid_fields, _FIELD_CACHE
    _FIELD_CACHE.clear()

    class Conn:
        def call(self, fm, **kw):
            raise RuntimeError("DD03L not readable")

    # Probe fails -> return wanted unchanged (no worse than before)
    kept = valid_fields(Conn(), "ZSOMETHING", ["A", "B"])
    assert kept == ["A", "B"]


# ── 5. basis-validator IDoc XML probe ────────────────────────────────────────
def test_idoc_xml_probe_handles_table_without_data():
    from sap_prereq_checks import _check_idoc_xml

    class Conn:
        def call(self, fm, **kw):
            tbl = kw.get("QUERY_TABLE")
            if tbl == "ICFSERVICE":
                return {"DATA": []}
            if tbl == "RSPFPAR":
                return {"DATA": [{"WA": "8000"}]}
            raise RuntimeError("unexpected table")

    ok, detail = _check_idoc_xml(Conn())
    assert ok is False
    assert "icm http stack" in detail.lower() or "not detected" in detail.lower()


# ── 6. data-migrator batch mode reads DAG ────────────────────────────────────
def test_data_migrator_batch_mode_iterates_dag(monkeypatch):
    dm = _load("data-migrator", "handler")
    monkeypatch.setattr(dm, "_load_dag", lambda run_id: {"nodes": []})
    res = dm.lambda_handler({"run_id": "TEST-003", "mode": "extract"}, None)
    assert res["status"] == "ok"
    assert "nothing to extract" in res["note"].lower()


def test_data_migrator_batch_mode_processes_known_object(monkeypatch):
    dm = _load("data-migrator", "handler")
    monkeypatch.setattr(dm, "_load_dag", lambda run_id: {
        "nodes": [{"object": "CompanyCode", "lane": "MC"}]
    })

    class FakeConn:
        def call(self, fm, **kw):
            if fm == "RFC_READ_TABLE":
                return {"FIELDS": [{"FIELDNAME": f} for f in
                                   ["BUKRS", "BUTXT", "ORT01", "LAND1"]],
                        "DATA": [{"WA": "1000|ACME Inc|Munich|DE"}]}
            return {}

    monkeypatch.setattr(dm, "_ecc", lambda secret_id: FakeConn())
    written = []
    monkeypatch.setattr(dm.S3, "put_object", lambda **kw: written.append(kw["Key"]))

    res = dm.lambda_handler({"run_id": "TEST-004", "mode": "extract"}, None)
    assert res["status"] == "success"
    assert res["ok_count"] == 1
    assert any(k.endswith("/CompanyCode.csv") for k in written)
    assert any(k.endswith("/summary.json") for k in written)
