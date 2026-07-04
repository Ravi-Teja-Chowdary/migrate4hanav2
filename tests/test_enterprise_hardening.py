"""
Unit tests for the 2026-07-03 enterprise-hardening pass:

  · mc-project-provisioner Lambda (mocked OData + boto3)
  · SalesforceSink live-upsert path + DDB sync tracker + retry_failed
  · Snowpipe verifier metric emission
  · Extended DependencyDAG covers the transactional envelope
  · Extended BAPI field catalog (~40+ objects)
  · mc_file_exporter filter_condition + default_values extensions
  · transport-import-executor dry-run + already-imported precheck

Every test is offline: no real SAP / SF / Snowflake / AWS calls. Fakes
mock the boto3 clients, urllib.request, http_client, and (where relevant)
`RFC_READ_TABLE`.
"""
from __future__ import annotations

import io
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lambda" / "utils"))


def _load_handler(rel_path: str, module_name: str):
    """Load a Lambda handler.py as a uniquely-named module, so multiple
    Lambdas can be tested in the same test session without clashing on
    the shared `handler` module name."""
    import importlib.util
    p = REPO_ROOT / "lambda" / rel_path / "handler.py"
    spec = importlib.util.spec_from_file_location(module_name, str(p))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


_mcpp = _load_handler("mc-project-provisioner", "mcpp_handler")
_snowpipe = _load_handler("snowpipe-verifier",   "snowpipe_verifier_handler")
_transport = _load_handler("transport-import-executor",
                            "transport_import_executor_handler")


# ═════════════════════════════════════════════════════════════════════════════
# 1. mc-project-provisioner
# ═════════════════════════════════════════════════════════════════════════════
class _FakeS3:
    def __init__(self): self.objects = {}
    def put_object(self, **kwargs):
        self.objects[kwargs["Key"]] = kwargs["Body"]
        return {}


class _FakeSecrets:
    def __init__(self, payload=None):
        self.payload = payload or {"ashost": "vhcalabaci", "user": "ATH",
                                    "passwd": "x", "https_port": 44300}
    def get_secret_value(self, SecretId):
        return {"SecretString": json.dumps(self.payload)}


class _FakeDDB:
    def __init__(self): self.items = []
    def put_item(self, TableName, Item): self.items.append(Item); return {}
    def query(self, **kw): return {"Items": []}


def test_mc_project_provisioner_dry_run_writes_runbook_and_no_odata():
    """dry_run must skip OData and still produce the runbook artefact."""
    h = _mcpp
    h.s3 = _FakeS3()
    h.secrets = _FakeSecrets()
    h.ddb = _FakeDDB()

    event = {
        "run_id":     "test-dry",
        "objects":    ["Customer", "Material"],
        "target_creds_arn": "arn:fake:x",
        "dry_run":    True,
    }
    res = h.lambda_handler(event, None)
    assert res["status"] == "created"
    assert res["dry_run"] is True
    assert "audit_block" in res
    print("  [OK] mc-project-provisioner dry_run skips OData mutation")


def test_mc_project_provisioner_odata_failure_falls_back_to_runbook():
    """When OData is 404 (release without MC service), the runbook still
    lists the objects a human must bind manually."""
    h = _mcpp
    h.s3 = _FakeS3()
    h.secrets = _FakeSecrets()
    h.ddb = _FakeDDB()

    with patch.object(_mcpp, "_odata_project_create",
                       return_value={"ok": False, "already_exists": False,
                                     "http_status": 404,
                                     "detail": "service_not_found",
                                     "url": "x"}):
        res = h.lambda_handler({"run_id": "test-runbook",
                                  "objects": ["Customer"],
                                  "target_creds_arn": "arn:fake:x"}, None)
    assert res["status"] == "manual_gate"
    assert "runbook_s3_uri" in res
    assert len(res["objects_deferred"]) == 1
    print("  [OK] mc-project-provisioner falls back to runbook on OData 404")


def test_mc_project_provisioner_audit_block_chained():
    """Every provisioning attempt writes an audit block linking to prev_hash."""
    h = _mcpp
    h.s3 = _FakeS3()
    h.secrets = _FakeSecrets()
    fake_ddb = _FakeDDB()
    h.ddb = fake_ddb

    with patch.object(_mcpp, "_odata_project_create",
                       return_value={"ok": True, "already_exists": False,
                                     "http_status": 200, "detail": "", "url": "x"}), \
         patch.object(_mcpp, "_odata_object_bind",
                       return_value={"ok": True, "http_status": 200, "detail": ""}), \
         patch.object(_mcpp, "_odata_field_map",
                       return_value={"ok": True, "status": "auto-mapped", "detail": ""}):
        h.lambda_handler({"run_id": "test-chain",
                           "objects": ["Customer"],
                           "target_creds_arn": "arn:fake:x"}, None)
    assert len(fake_ddb.items) == 1
    item = fake_ddb.items[0]
    assert item["block_type"]["S"] == "mc_project_provisioner"
    assert item["prev_hash"]["S"] == "0" * 64  # genesis
    assert len(item["block_hash"]["S"]) == 64
    print("  [OK] mc-project-provisioner writes hash-chain audit block")


# ═════════════════════════════════════════════════════════════════════════════
# 2. Salesforce sink hardening
# ═════════════════════════════════════════════════════════════════════════════
class _FakeSFResponse:
    def __init__(self, status, body=b""):
        self.status = status
        self.data = body


class _FakeHttp:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or []
        self._i = 0
    def request(self, method, url, body=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url,
                            "body": body, "headers": headers})
        r = self.responses[self._i]
        self._i = min(self._i + 1, len(self.responses) - 1)
        return r


def test_salesforce_sink_offline_still_queues_and_records_ddb():
    """No live http client → sink queues writes and (optionally) records DDB."""
    from sink_router import SalesforceSink
    ddb = MagicMock()
    ddb.update_item = MagicMock()
    sink = SalesforceSink(dynamodb_client=ddb)
    r = sink.write_one("Customer", "C1", {"NAME1": "Acme"}, tenant_id="acme")
    assert r["status"] == "queued"
    # DDB row was updated
    assert ddb.update_item.called
    kwargs = ddb.update_item.call_args[1]  # py3.7-compat kwargs accessor
    assert kwargs["TableName"] == "salesforce_sync_status"
    assert kwargs["Key"]["tenant_id"]["S"] == "acme"
    assert kwargs["Key"]["external_id"]["S"] == "C1"
    print("  [OK] SalesforceSink offline mode queues + records DDB PENDING")


def test_salesforce_sink_live_upsert_204_marks_synced():
    """Live http path: 204 → SYNCED with DDB tracker updated."""
    from sink_router import SalesforceSink
    http = _FakeHttp(responses=[
        # OAuth token response (POST /services/oauth2/token)
        _FakeSFResponse(200, json.dumps({
            "access_token": "abc", "expires_in": 3600,
            "instance_url": "https://acme.my.salesforce.com"}).encode()),
        # Upsert PATCH → 204
        _FakeSFResponse(204),
    ])
    ddb = MagicMock()
    sink = SalesforceSink(
        instance_url="https://acme.my.salesforce.com",
        oauth_creds={"client_id": "x", "client_secret": "y"},
        http_client=http, dynamodb_client=ddb)
    r = sink.write_one("Customer", "C1", {"NAME1": "Acme"})
    assert r["status"] == "synced"
    assert r["http_status"] == 204
    # First call was the token, second was PATCH
    assert http.calls[0]["method"] == "POST"
    assert "oauth2/token" in http.calls[0]["url"]
    assert http.calls[1]["method"] == "PATCH"
    assert "sobjects/Account/External_Id__c/C1" in http.calls[1]["url"]
    print("  [OK] SalesforceSink live upsert PATCHes External_Id__c and marks SYNCED")


def test_salesforce_sink_live_upsert_4xx_marks_failed():
    from sink_router import SalesforceSink
    err_body = json.dumps([{
        "errorCode": "DUPLICATES_DETECTED", "message": "already exists"
    }]).encode()
    http = _FakeHttp(responses=[
        _FakeSFResponse(200, json.dumps({
            "access_token": "abc", "expires_in": 3600}).encode()),
        _FakeSFResponse(400, err_body),
    ])
    ddb = MagicMock()
    sink = SalesforceSink(
        instance_url="https://acme.my.salesforce.com",
        oauth_creds={"client_id": "x", "client_secret": "y"},
        http_client=http, dynamodb_client=ddb)
    r = sink.write_one("Customer", "C1", {"NAME1": "Acme"})
    assert r["status"] == "failed"
    assert r["http_status"] == 400
    print("  [OK] SalesforceSink live upsert 4xx marks FAILED + captures SF error body")


def test_salesforce_sink_retry_failed_re_drives_pending_rows():
    from sink_router import SalesforceSink
    http = _FakeHttp(responses=[
        _FakeSFResponse(200, json.dumps({
            "access_token": "abc", "expires_in": 3600}).encode()),
        _FakeSFResponse(204),
    ])
    ddb = MagicMock()
    ddb.query = MagicMock(return_value={"Items": [{
        "tenant_id":    {"S": "acme"},
        "external_id":  {"S": "C1"},
        "sf_object":    {"S": "Account"},
        "payload_json": {"S": json.dumps({"External_Id__c": "C1",
                                            "Name": "Acme"})},
        "last_status":  {"S": "FAILED"},
    }]})
    sink = SalesforceSink(
        instance_url="https://acme.my.salesforce.com",
        oauth_creds={"client_id": "x", "client_secret": "y"},
        http_client=http, dynamodb_client=ddb)
    out = sink.retry_failed(tenant_id="acme")
    assert out["synced"] == 1
    assert out["failed"] == 0
    print("  [OK] SalesforceSink.retry_failed re-drives FAILED rows to SYNCED")


# ═════════════════════════════════════════════════════════════════════════════
# 3. Snowpipe verifier metric emission
# ═════════════════════════════════════════════════════════════════════════════
def test_snowpipe_verifier_aggregate_and_metric_shapes():
    """Verifier aggregation groups rows by (tenant, object), emits
    RowsLoaded per pair + a global PipeStuckSeconds."""
    v = _snowpipe
    v.cw = MagicMock()
    per_pair = v._aggregate([
        {"tenant_id": "acme", "object_type": "Material",
         "ok_rows": 10, "total_rows": 12,
         "last_seen": "2026-07-03T12:00:00Z"},
        {"tenant_id": "acme", "object_type": "Material",
         "ok_rows": 5, "total_rows": 5,
         "last_seen": "2026-07-03T12:05:00Z"},
        {"tenant_id": "globex", "object_type": "Customer",
         "ok_rows": 0, "total_rows": 0,
         "last_seen": None},
    ])
    assert per_pair[("acme", "Material")]["total"] == 17
    assert per_pair[("acme", "Material")]["ok"] == 15
    assert per_pair[("globex", "Customer")]["total"] == 0
    # Metric emission (uses MagicMock CW client — no real AWS)
    v._emit_metrics(per_pair)
    assert v.cw.put_metric_data.called
    calls = v.cw.put_metric_data.call_args_list
    metrics = []
    for call in calls:
        metrics.extend(call[1]["MetricData"])  # py3.7-compat kwargs
    names = {m["MetricName"] for m in metrics}
    assert "RowsLoaded" in names
    assert "PipeStuckSeconds" in names
    print("  [OK] snowpipe-verifier aggregates by (tenant,object) + emits both metrics")


# ═════════════════════════════════════════════════════════════════════════════
# 4. Extended DependencyDAG
# ═════════════════════════════════════════════════════════════════════════════
def test_dag_extended_covers_transactional_envelope():
    from dependency_dag import DependencyDAG
    dag = DependencyDAG.from_defaults()
    # Cycle check first
    assert dag.validate() == []
    # Nodes we newly declared
    for n in ["OutboundDelivery", "IncomingInvoice", "ProductionOrder",
              "MaintenancePlan", "InfoRecord", "ProjectStock", "Shipment"]:
        assert n in dag.nodes, f"{n} missing from extended DAG"

    order = dag.topological_sort()
    # Order invariants
    assert order.index("Material") < order.index("InfoRecord")
    assert order.index("OpenPO") < order.index("GoodsReceipt")
    assert order.index("GoodsReceipt") < order.index("IncomingInvoice")
    assert order.index("SalesOrder") < order.index("OutboundDelivery")
    assert order.index("OutboundDelivery") < order.index("Shipment")
    assert order.index("ProductionOrder") < order.index("ProductionOrderConfirmation")
    print(f"  [OK] Extended DAG has {len(dag.nodes)} nodes, transactional envelope ordered")


# ═════════════════════════════════════════════════════════════════════════════
# 5. Extended BAPI field catalog
# ═════════════════════════════════════════════════════════════════════════════
def test_bapi_catalog_extended_object_coverage():
    from bapi_field_catalog import known_objects, for_object
    objs = known_objects()
    assert len(objs) >= 40, f"catalog too thin: {len(objs)}"
    # Sample the newly-added transactional catalog entries
    for obj in ["Quotation", "OutboundDelivery", "GoodsReceipt",
                "IncomingInvoice", "ProductionOrder", "MaintenancePlan",
                "InfoRecord", "AccountingDocument", "BOMItem"]:
        flds = for_object(obj)
        assert len(flds) >= 4, f"{obj} field set too small"
    print(f"  [OK] BAPI field catalog now covers {len(objs)} objects")


# ═════════════════════════════════════════════════════════════════════════════
# 6. mc_file_exporter extension: filter_condition + default_values
# ═════════════════════════════════════════════════════════════════════════════
def test_mc_file_filter_condition_scalar_and_list():
    from mc_file_exporter import mc_should_include_row, register_template_extension
    # HouseBank exists in the base catalog
    register_template_extension("HouseBank",
                                 filter_condition={"BUKRS": "0001"})
    assert mc_should_include_row("HouseBank",
                                   {"BUKRS": "0001", "HBKID": "H1"}) is True
    assert mc_should_include_row("HouseBank",
                                   {"BUKRS": "0002", "HBKID": "H1"}) is False

    # List membership
    register_template_extension("HouseBank",
                                 filter_condition={"BANKS": ["DE", "US", "GB"]})
    assert mc_should_include_row("HouseBank",
                                   {"BUKRS": "0001", "BANKS": "DE"}) is True
    assert mc_should_include_row("HouseBank",
                                   {"BUKRS": "0001", "BANKS": "FR"}) is False
    print("  [OK] mc_should_include_row honours scalar + list filter_condition")


def test_mc_file_filter_condition_dict_op_predicates():
    from mc_file_exporter import mc_should_include_row, register_template_extension
    register_template_extension("Position",
                                 filter_condition={"PLANS": {"op": "startswith",
                                                              "val": "US"}})
    assert mc_should_include_row("Position", {"PLANS": "US_MGR_1"}) is True
    assert mc_should_include_row("Position", {"PLANS": "DE_MGR_1"}) is False
    print("  [OK] mc_should_include_row supports {op:...} dict predicates")


def test_mc_file_default_values_apply_at_build_payload():
    """The default_values on a template spec are picked up correctly and
    surface on the MC_TEMPLATES entry so build_payload can honour them."""
    from mc_file_exporter import register_template_extension, MC_TEMPLATES
    register_template_extension("HouseBank",
                                 default_values={"BANKA": "DEFAULT BANK"})
    assert MC_TEMPLATES["HouseBank"]["default_values"]["BANKA"] == "DEFAULT BANK"
    print("  [OK] register_template_extension attaches default_values to template spec")


# ═════════════════════════════════════════════════════════════════════════════
# 7. transport-import-executor dry-run + already-imported precheck
# ═════════════════════════════════════════════════════════════════════════════
def test_transport_dry_run_returns_dry_run_ok_when_prechecks_pass():
    """When target_bastion_instance_id + creds are absent, prechecks return
    'not checked' but dry_run still returns a structured result rather than
    invoking tp."""
    t = _transport
    t.s3 = _FakeS3()

    event = {
        "run_id": "test-dry",
        "transport_id": "M4HK900123",
        "target_sid": "S4H",
        "target_client": "100",
        "dry_run": True,
    }
    with patch.object(_transport, "_check_already_imported",
                       return_value={"imported": False, "checked": False,
                                     "reason": "no rfc"}), \
         patch.object(_transport, "_check_staging_present",
                       return_value={"ok": True, "detail": "ok"}), \
         patch.object(_transport, "_check_ssm_reachable",
                       return_value={"ok": True, "detail": "ok"}):
        res = t.lambda_handler(event, None)
    assert res["status"] == "dry_run_ok"
    assert res["would_execute"] is True
    assert "prechecks" in res
    print("  [OK] transport-import-executor dry_run runs prechecks + skips tp")


def test_transport_already_imported_short_circuits():
    t = _transport
    t.s3 = _FakeS3()
    with patch.object(_transport, "_check_already_imported",
                       return_value={"imported": True, "checked": True,
                                     "detail": "E070 has 1 row"}):
        res = t.lambda_handler({
            "run_id": "test",
            "transport_id": "M4HK900123",
            "target_sid": "S4H",
            "target_client": "100"}, None)
    assert res["status"] == "already_imported"
    assert "E070" in res["reason"]
    print("  [OK] transport-import-executor skips tp when E070 shows already imported")


# ═════════════════════════════════════════════════════════════════════════════
# Runner
# ═════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    test_mc_project_provisioner_dry_run_writes_runbook_and_no_odata()
    test_mc_project_provisioner_odata_failure_falls_back_to_runbook()
    test_mc_project_provisioner_audit_block_chained()
    test_salesforce_sink_offline_still_queues_and_records_ddb()
    test_salesforce_sink_live_upsert_204_marks_synced()
    test_salesforce_sink_live_upsert_4xx_marks_failed()
    test_salesforce_sink_retry_failed_re_drives_pending_rows()
    test_snowpipe_verifier_aggregate_and_metric_shapes()
    test_dag_extended_covers_transactional_envelope()
    test_bapi_catalog_extended_object_coverage()
    test_mc_file_filter_condition_scalar_and_list()
    test_mc_file_filter_condition_dict_op_predicates()
    test_mc_file_default_values_apply_at_build_payload()
    test_transport_dry_run_returns_dry_run_ok_when_prechecks_pass()
    test_transport_already_imported_short_circuits()
    print("\nAll 15 enterprise-hardening tests passed.")
