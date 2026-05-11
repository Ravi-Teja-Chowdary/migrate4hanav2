"""
local_aws_shim.py — make AWS-dependent Lambdas runnable on a developer laptop
=============================================================================
Every Lambda in `lambda/` hardcodes `boto3.client(...)` for Secrets Manager,
S3, DynamoDB, SSM, API Gateway. That's fine in production. For a first
end-to-end test run on a laptop (no AWS Secrets Manager set up, no S3
bucket, no SSM agents on the SAP host) we still want every handler to
return successfully.

Strategy: monkey-patch `boto3.client` and `boto3.resource` *before* any
handler imports them. The shim implements just enough of each AWS service
to satisfy the Lambdas the lift-and-shift runner invokes.

Activation
----------
Set ``M4H_LOCAL_MODE=1`` (or just call ``activate()`` from the runner).
The shim is idempotent and silently no-ops if already active or if local
mode is not requested.

Coverage
--------
* secretsmanager.get_secret_value(SecretId="local:<name>") →
    reads connections.json + env vars (M4H_ECC_PASSWD, M4H_TARGET_PASSWD).
* s3.put_object / get_object / head_object / copy_object →
    backed by ./local-staging/ on the filesystem.
* dynamodb.* (client + resource) → in-process dict, persisted to
    ./local-staging/_dynamodb.json so manual gates survive between stages.
* ssm.send_command → records a manual instruction and returns a synthetic
    Command/Invocation pair with Status=Success. The shim **never** runs
    shell commands on remote hosts; if the stage needs that, the runbook
    asks you to do it by hand.
* apigatewaymanagementapi.post_to_connection → no-op (UI websocket).
* launchwizard.create_deployment → no-op (target-provisioner uses
    basis_handover_only mode for SAP CAL anyway).
* bedrock-runtime.invoke_model → returns a deterministic placeholder so
  GenAI-optional stages degrade gracefully.

Anything not listed above falls through to the real boto3 client. That's
why the shim is safe even in mixed mode (e.g. you have AWS credentials
for S3 but no Secrets Manager set up).
"""
from __future__ import annotations

import io
import json
import logging
import os
import shutil
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("m4h.local_shim")

_ACTIVE = False
_STAGING_DIR: Optional[Path] = None
_CONNECTIONS: Dict[str, Any] = {}
_DDB_FILE: Optional[Path] = None
_DDB_STATE: Dict[str, Dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------
def activate(staging_dir: str = "local-staging",
             connections_file: str = "connections.json") -> None:
    """Install monkey-patches. Idempotent."""
    global _ACTIVE, _STAGING_DIR, _CONNECTIONS, _DDB_FILE, _DDB_STATE
    if _ACTIVE:
        return

    repo_root = Path(__file__).resolve().parent
    _STAGING_DIR = (repo_root / staging_dir).resolve()
    _STAGING_DIR.mkdir(parents=True, exist_ok=True)

    conn_path = repo_root / connections_file
    if conn_path.exists():
        try:
            _CONNECTIONS = json.loads(conn_path.read_text())
        except Exception as e:
            logger.warning("Could not read %s: %s", conn_path, e)

    _DDB_FILE = _STAGING_DIR / "_dynamodb.json"
    if _DDB_FILE.exists():
        try:
            _DDB_STATE = json.loads(_DDB_FILE.read_text())
        except Exception:
            _DDB_STATE = {}

    import boto3  # noqa: WPS433
    _patch_boto3(boto3)
    _ACTIVE = True
    logger.info("local_aws_shim active — staging=%s", _STAGING_DIR)
    print(f"[local-shim] active. staging={_STAGING_DIR}")


# ---------------------------------------------------------------------------
# boto3 patching
# ---------------------------------------------------------------------------
def _patch_boto3(boto3_mod) -> None:
    real_client = boto3_mod.client
    real_resource = boto3_mod.resource

    def shimmed_client(service_name, *args, **kwargs):
        impl = _CLIENT_IMPLS.get(service_name)
        if impl is not None:
            return impl()
        # fall back to real boto3 (will fail if no AWS creds — that's fine)
        try:
            return real_client(service_name, *args, **kwargs)
        except Exception as e:
            logger.warning("no shim for %s and no AWS creds (%s) — returning no-op", service_name, e)
            return _NoopClient(service_name)

    def shimmed_resource(service_name, *args, **kwargs):
        if service_name == "dynamodb":
            return _DynamoResource()
        try:
            return real_resource(service_name, *args, **kwargs)
        except Exception:
            return _NoopClient(service_name)

    boto3_mod.client = shimmed_client      # type: ignore[assignment]
    boto3_mod.resource = shimmed_resource  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Service implementations
# ---------------------------------------------------------------------------
class _SecretsManagerClient:
    """Resolve SecretId values from connections.json + env vars."""

    def get_secret_value(self, SecretId: str, **_):
        creds = _resolve_secret(SecretId)
        return {"SecretString": json.dumps(creds), "Name": SecretId,
                "VersionId": "local", "CreatedDate": datetime.utcnow()}


def _resolve_secret(secret_id: str) -> Dict[str, Any]:
    """Map known secret-ARN-shaped strings to local creds."""
    sid = (secret_id or "").lower()
    ecc = _CONNECTIONS.get("ecc") or {}
    tgt = _CONNECTIONS.get("lift_and_shift_target") or {}

    def ecc_creds():
        return {
            "host": ecc.get("ashost", os.environ.get("ECC_HOST", "")),
            "ashost": ecc.get("ashost", os.environ.get("ECC_HOST", "")),
            "sysnr": ecc.get("sysnr", "00"),
            "client": ecc.get("client", "100"),
            "user": ecc.get("user", "M4H_RFC"),
            "passwd": os.environ.get("M4H_ECC_PASSWD", ""),
            "saprouter": ecc.get("saprouter", ""),
        }

    def target_creds():
        return {
            "host": tgt.get("target_ashost", os.environ.get("TARGET_HOST", "")),
            "ashost": tgt.get("target_ashost", os.environ.get("TARGET_HOST", "")),
            "sysnr": tgt.get("target_sysnr", "00"),
            "client": tgt.get("target_client", "100"),
            "user": tgt.get("target_user", "DDIC"),
            "passwd": os.environ.get("M4H_TARGET_PASSWD", ""),
            "mc_base_url": tgt.get("mc_base_url", ""),
            "idoc_endpoint": tgt.get("idoc_endpoint", ""),
            "idoc_partner": tgt.get("idoc_partner", ""),
            "saprouter": tgt.get("target_saprouter", ""),
        }

    # Heuristic mapping — be generous, lambdas use a variety of names.
    if "target" in sid or "s4" in sid or "build" in sid or "mc" in sid:
        return target_creds()
    return ecc_creds()


class _S3Client:
    """Filesystem-backed S3. Buckets become subdirectories of ./local-staging."""

    def _path(self, bucket: str, key: str) -> Path:
        p = (_STAGING_DIR / bucket / key).resolve()
        # safety: must stay inside staging dir
        if _STAGING_DIR not in p.parents and p != _STAGING_DIR:
            raise ValueError(f"path escapes staging: {p}")
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def put_object(self, Bucket, Key, Body=b"", **_):
        if isinstance(Body, str):
            Body = Body.encode("utf-8")
        if hasattr(Body, "read"):
            Body = Body.read()
        self._path(Bucket, Key).write_bytes(Body or b"")
        return {"ETag": "local", "VersionId": "local"}

    def get_object(self, Bucket, Key, **_):
        data = self._path(Bucket, Key).read_bytes()
        return {"Body": _BytesStream(data), "ContentLength": len(data),
                "LastModified": datetime.utcnow(), "ETag": "local"}

    def head_object(self, Bucket, Key, **_):
        p = self._path(Bucket, Key)
        if not p.exists():
            from botocore.exceptions import ClientError
            raise ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        return {"ContentLength": p.stat().st_size, "LastModified": datetime.utcnow()}

    def list_objects_v2(self, Bucket, Prefix="", **_):
        base = (_STAGING_DIR / Bucket).resolve()
        if not base.exists():
            return {"Contents": [], "KeyCount": 0}
        items = []
        for f in base.rglob("*"):
            if f.is_file():
                key = str(f.relative_to(base)).replace(os.sep, "/")
                if key.startswith(Prefix):
                    items.append({"Key": key, "Size": f.stat().st_size,
                                  "LastModified": datetime.utcnow(), "ETag": "local"})
        return {"Contents": items, "KeyCount": len(items)}

    def copy_object(self, Bucket, Key, CopySource, **_):
        if isinstance(CopySource, dict):
            src = self._path(CopySource["Bucket"], CopySource["Key"])
        else:
            sbucket, _, skey = CopySource.partition("/")
            src = self._path(sbucket, skey)
        dst = self._path(Bucket, Key)
        shutil.copy2(src, dst)
        return {"CopyObjectResult": {"ETag": "local"}}

    def upload_file(self, Filename, Bucket, Key, **_):
        dst = self._path(Bucket, Key)
        shutil.copy2(Filename, dst)
        return None

    def download_file(self, Bucket, Key, Filename, **_):
        shutil.copy2(self._path(Bucket, Key), Filename)
        return None


class _BytesStream(io.BytesIO):
    def read(self, *args, **kwargs):
        return super().read(*args, **kwargs)


class _DynamoClient:
    """Client interface — implements just put_item/get_item/update_item/query."""

    def put_item(self, TableName, Item, **_):
        _DDB_STATE.setdefault(TableName, {})
        key = _ddb_key(Item)
        _DDB_STATE[TableName][key] = _ddb_strip(Item)
        _ddb_persist()
        return {}

    def get_item(self, TableName, Key, **_):
        item = _DDB_STATE.get(TableName, {}).get(_ddb_key(Key))
        return {"Item": _ddb_wrap(item)} if item is not None else {}

    def update_item(self, TableName, Key, **kw):
        _DDB_STATE.setdefault(TableName, {})
        k = _ddb_key(Key)
        cur = _DDB_STATE[TableName].get(k, _ddb_strip(Key))
        # very partial UpdateExpression support — enough for manual-gate
        expr = kw.get("UpdateExpression", "")
        vals = {kk: list(vv.values())[0] for kk, vv in (kw.get("ExpressionAttributeValues") or {}).items()}
        names = kw.get("ExpressionAttributeNames") or {}
        if expr.upper().startswith("SET "):
            for assign in expr[4:].split(","):
                lhs, _, rhs = assign.strip().partition("=")
                lhs = lhs.strip()
                rhs = rhs.strip()
                attr = names.get(lhs, lhs)
                if rhs in vals:
                    cur[attr] = vals[rhs]
        _DDB_STATE[TableName][k] = cur
        _ddb_persist()
        return {"Attributes": _ddb_wrap(cur)}

    def query(self, TableName, **_):
        items = list((_DDB_STATE.get(TableName, {}) or {}).values())
        return {"Items": [_ddb_wrap(i) for i in items], "Count": len(items)}

    def scan(self, TableName, **_):
        return self.query(TableName)


class _DynamoResource:
    def Table(self, name):  # noqa: N802 — boto3 API
        return _DynamoTable(name)


class _DynamoTable:
    def __init__(self, name):
        self.name = name
        self._client = _DynamoClient()

    def put_item(self, Item, **_):
        _DDB_STATE.setdefault(self.name, {})
        _DDB_STATE[self.name][_ddb_key(Item)] = Item
        _ddb_persist()
        return {}

    def get_item(self, Key, **_):
        item = _DDB_STATE.get(self.name, {}).get(_ddb_key(Key))
        return {"Item": item} if item is not None else {}

    def update_item(self, Key, **kw):
        return self._client.update_item(self.name, Key, **kw)

    def query(self, **_):
        return {"Items": list((_DDB_STATE.get(self.name, {}) or {}).values()),
                "Count": len(_DDB_STATE.get(self.name, {}) or {})}

    def scan(self, **_):
        return self.query()


def _ddb_key(item: Dict[str, Any]) -> str:
    # accept both DDB low-level ({'k':{'S':'v'}}) and high-level ({'k':'v'}) shapes
    def _val(v):
        return list(v.values())[0] if isinstance(v, dict) and len(v) == 1 else v
    return "|".join(f"{k}={_val(v)}" for k, v in sorted(item.items()))


def _ddb_strip(item):
    out = {}
    for k, v in item.items():
        if isinstance(v, dict) and len(v) == 1 and list(v.keys())[0] in ("S", "N", "B"):
            out[k] = list(v.values())[0]
        else:
            out[k] = v
    return out


def _ddb_wrap(item):
    if item is None:
        return None
    out = {}
    for k, v in item.items():
        if isinstance(v, (int, float)):
            out[k] = {"N": str(v)}
        else:
            out[k] = {"S": str(v)}
    return out


def _ddb_persist():
    if _DDB_FILE is None:
        return
    try:
        _DDB_FILE.write_text(json.dumps(_DDB_STATE, default=str, indent=2))
    except Exception as e:
        logger.warning("dynamodb persist failed: %s", e)


class _SSMClient:
    """Records would-be SSM commands; never executes anything remote."""

    def send_command(self, **kw):
        cmd_id = f"local-ssm-{uuid.uuid4().hex[:12]}"
        instructions = kw.get("Parameters", {}).get("commands", [])
        manual_file = _STAGING_DIR / "_ssm_manual" / f"{cmd_id}.sh"
        manual_file.parent.mkdir(parents=True, exist_ok=True)
        manual_file.write_text("#!/bin/sh\n# " + (kw.get("Comment") or "") + "\n" +
                               "\n".join(instructions or []))
        print(f"[local-shim] SSM command recorded → {manual_file} "
              f"(target={kw.get('InstanceIds')}). Run it yourself on the target host.")
        return {"Command": {"CommandId": cmd_id, "Status": "Success"}}

    def get_command_invocation(self, CommandId, InstanceId, **_):
        return {"Status": "Success", "ResponseCode": 0,
                "StandardOutputContent": "(local-shim: assumed success)",
                "StandardErrorContent": ""}

    def list_command_invocations(self, **_):
        return {"CommandInvocations": []}


class _ApiGwClient:
    def post_to_connection(self, **_): return {}


class _LaunchWizardClient:
    def create_deployment(self, **kw):
        return {"deploymentId": "local-no-op", "note": "launchwizard skipped in local mode"}


class _BedrockClient:
    def invoke_model(self, **_):
        body = json.dumps({"completion": "(local-shim: GenAI skipped; AST rules only)"})
        return {"body": _BytesStream(body.encode()), "contentType": "application/json"}


class _SNSClient:
    def publish(self, **kw):
        print(f"[local-shim] SNS publish (no-op): {kw.get('Subject') or kw.get('TopicArn')}")
        return {"MessageId": f"local-{uuid.uuid4().hex[:8]}"}


class _NoopClient:
    def __init__(self, name): self._name = name
    def __getattr__(self, attr):
        def _f(*a, **kw):
            logger.debug("no-op %s.%s called", self._name, attr)
            return {}
        return _f


_CLIENT_IMPLS = {
    "secretsmanager":          _SecretsManagerClient,
    "s3":                      _S3Client,
    "dynamodb":                _DynamoClient,
    "ssm":                     _SSMClient,
    "apigatewaymanagementapi": _ApiGwClient,
    "launchwizard":            _LaunchWizardClient,
    "bedrock-runtime":         _BedrockClient,
    "bedrock":                 _BedrockClient,
    "sns":                     _SNSClient,
}


# Auto-activate when imported with M4H_LOCAL_MODE=1
if os.environ.get("M4H_LOCAL_MODE", "").lower() in ("1", "true", "yes", "on"):
    activate()
