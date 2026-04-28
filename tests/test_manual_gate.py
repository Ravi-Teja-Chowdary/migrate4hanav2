"""Unit tests for lambda/manual-gate/handler.py.

These run without any AWS connectivity — boto3 is stubbed via ``moto``-style
patching of module-level clients. Goal: prove the persist + notify paths and
the DynamoDB->S3 fallback work as documented.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
HANDLER_PATH = ROOT / "lambda" / "manual-gate" / "handler.py"


def _load_handler(env):
    """Reload the handler module with given env vars + stub boto3 clients."""
    fake_dynamo = mock.MagicMock()
    fake_s3 = mock.MagicMock()
    fake_sns = mock.MagicMock()

    def fake_client(name, *a, **kw):
        return {"dynamodb": fake_dynamo, "s3": fake_s3, "sns": fake_sns}[name]

    boto3_stub = types.SimpleNamespace(client=fake_client)
    sys.modules["boto3"] = boto3_stub

    # botocore.exceptions.ClientError must still be importable
    import botocore.exceptions  # noqa: F401  (real package OK)

    with mock.patch.dict("os.environ", env, clear=False):
        spec = importlib.util.spec_from_file_location("manual_gate_h", HANDLER_PATH)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    return m, fake_dynamo, fake_s3, fake_sns


def test_dynamo_path_persists_and_returns_pending():
    env = {"GATES_TABLE": "gates-test", "S3_STAGING_BUCKET": "bkt", "GATES_SNS_TOPIC_ARN": ""}
    m, dyn, s3, sns = _load_handler(env)

    out = m.lambda_handler({
        "gate": "pre_cutover",
        "token": "ABC123",
        "input": {"run_id": "run-42", "stage": "21"},
    })

    assert out["status"] == "pending"
    assert out["gate_id"] == "run-42__pre_cutover"
    assert out["persisted_via"] == "dynamodb"
    dyn.put_item.assert_called_once()
    s3.put_object.assert_not_called()
    sns.publish.assert_not_called()


def test_s3_fallback_when_no_table_env():
    env = {"GATES_TABLE": "", "S3_STAGING_BUCKET": "bkt-x"}
    m, dyn, s3, sns = _load_handler(env)

    out = m.lambda_handler({"gate": "basis_handover", "token": "T1", "input": {"run_id": "r1"}})

    assert out["persisted_via"] == "s3"
    s3.put_object.assert_called_once()
    kwargs = s3.put_object.call_args[1]
    assert kwargs["Bucket"] == "bkt-x"
    assert kwargs["Key"] == "gates/r1/basis_handover.json"


def test_sns_notify_when_topic_set():
    env = {"GATES_TABLE": "", "S3_STAGING_BUCKET": "b", "GATES_SNS_TOPIC_ARN": "arn:topic:gates"}
    m, dyn, s3, sns = _load_handler(env)
    m.lambda_handler({"gate": "final_go_live", "token": "T", "input": {"run_id": "r9"}})
    sns.publish.assert_called_once()


if __name__ == "__main__":
    test_dynamo_path_persists_and_returns_pending()
    test_s3_fallback_when_no_table_env()
    test_sns_notify_when_topic_set()
    print("all manual-gate tests OK")
