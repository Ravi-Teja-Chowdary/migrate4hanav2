"""Smoke-level behavioural tests for the lift-and-shift orchestrator handlers.

These don't talk to AWS; we just import each handler with stubbed boto3 and
invoke ``lambda_handler`` with a minimal event to confirm it executes
end-to-end and returns a dict without crashing.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LAMBDA = ROOT / "lambda"

# Handlers covered. Each tuple = (folder, minimal event).
CASES = [
    ("object-router",                  {"run_id": "t", "discovered_objects": ["Customer", "Vendor"]}),
    ("sizing-advisor",                 {"run_id": "t", "discovery": {"db_size_gb": 800, "users": 200}}),
    ("basis-validator",                {"run_id": "t", "checks": []}),
    ("bc-set-builder",                 {"run_id": "t", "config_groups": [{"name": "BPGroup", "tables": ["TBC001"]}]}),
    ("transport-artifact-builder",     {"run_id": "t", "object_list": ["ZPROG_X"]}),
    ("transport-file-placer",          {"run_id": "t", "transport_id": "DEVK900001",
                                         "cofile_s3": "s3://b/co", "datafile_s3": "s3://b/data",
                                         "target_bastion_instance_id": "i-00", "target_sid": "S4D"}),
    ("transport-import-executor",      {"run_id": "t", "transport_id": "DEVK900001",
                                         "target_sid": "S4D", "target_bastion_instance_id": "i-00",
                                         "timeout_s": 1}),
    ("transport-import-verifier",      {"run_id": "t", "transport_id": "DEVK900001",
                                         "target_bastion_instance_id": "i-00", "timeout_s": 1}),
    ("migration-cockpit-orchestrator", {"run_id": "t", "object": "Customer",
                                         "template_s3_uri": "s3://b/tmpl.xml",
                                         "runbook_only": True}),
    ("ltmom-orchestrator",             {"run_id": "t", "object": "ZCUST",
                                         "design_spec": {"source_struct": "ZS_CUST"}}),
    ("idoc-orchestrator",              {"run_id": "t", "object": "Customer",
                                         "payload_s3_uri": "s3://b/idoc.xml"}),
    ("delta-extractor",                {"run_id": "t", "objects": ["KNA1"], "ecc_locked": True}),
    ("target-provisioner",             {"run_id": "t", "mode": "infra_only"}),
]


def _stub_boto3():
    """Replace boto3 with a permissive MagicMock so client(...).any_method(...) works.

    Critically: ``get_command_invocation`` must return Status='Success' so that
    the SSM polling loop in ``sap_host_runner`` exits immediately instead of
    looping for the (default 30-minute) timeout.
    """
    fake = mock.MagicMock()
    client_mock = mock.MagicMock()
    client_mock.send_command.return_value = {"Command": {"CommandId": "test-cmd"}}
    client_mock.get_command_invocation.return_value = {
        "Status": "Success", "StandardOutputContent": "", "StandardErrorContent": "",
        "ResponseCode": 0,
    }
    client_mock.get_secret_value.return_value = {"SecretString": "{}"}
    fake.client.return_value = client_mock
    fake.resource.return_value = mock.MagicMock()
    sys.modules["boto3"] = fake
    return fake


def _load(folder):
    """Reload handler with stale utils evicted so module-level boto3 clients re-bind to the stub."""
    for mod in [
        "sap_host_runner", "sap_job_monitor", "sap_log_collector",
        "sap_prereq_checks", "sap_note_planner", "logger", "rfc_pool",
    ]:
        sys.modules.pop(mod, None)
    path = LAMBDA / folder / "handler.py"
    spec = importlib.util.spec_from_file_location("h_" + folder.replace("-", "_"), path)
    m = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    sys.path.insert(0, str(LAMBDA / "utils"))
    try:
        spec.loader.exec_module(m)
    finally:
        sys.path.pop(0)
        sys.path.pop(0)
    return m


def run():
    failures = []
    env = {
        "S3_STAGING_BUCKET": "bkt-test",
        "TARGET_SECRETS_ARN": "arn:aws:secretsmanager:us-east-1:000000000000:secret:t",
        "SECRETS_ARN": "arn:aws:secretsmanager:us-east-1:000000000000:secret:t",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        for folder, event in CASES:
            _stub_boto3()
            try:
                m = _load(folder)
                result = m.lambda_handler(event, None)
                assert isinstance(result, dict), folder + " did not return dict"
                print("  OK   " + folder + "  ->  keys=" + ",".join(sorted(result.keys()))[:80])
            except Exception as e:
                print("  FAIL " + folder + ": " + type(e).__name__ + ": " + str(e))
                failures.append(folder)
    print("\nFailures: " + str(len(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(run())
