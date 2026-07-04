"""
mc-project-provisioner
======================
Programmatically creates + configures an SAP Migration Cockpit (MC) project on
the target S/4 system. Complements mc_job_trigger.py, which triggers RUNS of
an already-provisioned project.

WHAT IS SAFE — WHAT IS NOT
--------------------------
This Lambda uses ONLY the customer-facing MC OData services documented under
SAP Note 2462327:

  · /sap/opu/odata4/sap/api_migrationcockpit_project        (Project CRUD)
  · /sap/opu/odata4/sap/api_migrationcockpit_object_runtime (Object bind)
  · /sap/opu/odata4/sap/api_migrationcockpit_mapping        (Field mapping)

It DOES NOT call any LTR_* / LTMC_* / DMC_* RFC-level function module.
Those are NOT in the SAP-released customer-callable set; invoking them from
an external system would put the target outside SAP support coverage.

STRATEGY CHAIN
--------------
  Strategy A — OData PROJECT create + object-bind + field-map (SAP-released,
               customer-facing). This is the ONLY strategy that actually
               mutates the S/4 project catalog.
  Strategy B — Runbook fallback: if OData is 404/501/unauthorised, produce
               a structured runbook the customer's Basis / functional lead
               executes in the LTMC / Fiori "Migrate Your Data" app.

The Lambda ALWAYS returns a runbook artefact regardless of whether OData
succeeded — the runbook doubles as the "what was created?" evidence.

RUN CONTRACT
------------
event = {
  "run_id":            "aws-e2e-20260703-...",
  "project_id":        "MIGRATE4HANA_<run_id>"   # optional; default from run_id
  "project_desc":      "Migrate4HANA run <run_id>",
  "target_release":    "S4H2023",
  "target_creds_arn":  "arn:aws:secretsmanager:...",
  "objects":           ["Customer","Vendor","Material",...],
  "staging_bucket":    "migrate4hana-staging-prod",
  "template_prefix":   "runs/<run_id>/mc-templates/",
  "dry_run":           false,          # optional; skip mutations
  "force_recreate":    false           # optional; drop & recreate if exists
}

Returns:
  { "status":  "created"|"exists"|"manual_gate"|"failed",
    "project_id":       "...",
    "objects_bound":    [...],
    "objects_deferred": [...],
    "runbook_s3_uri":   "s3://bucket/runs/<run_id>/mc/project-runbook.md",
    "audit_block":      { hash-chain block written to compliance-ledger } }
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import sys
import time
import urllib.parse
import urllib.request
from typing import Optional

import boto3

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__),
                                              "..", "utils")))
try:
    from logger import log_stage_event  # type: ignore
except Exception:  # pragma: no cover
    def log_stage_event(*a, **k):  # type: ignore
        pass

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
secrets = boto3.client("secretsmanager")
ddb = boto3.client("dynamodb")

STAGING_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hana-staging-prod")
LEDGER_TABLE   = os.environ.get("COMPLIANCE_LEDGER_TABLE",
                                 "migrate4hana-compliance-ledger-prod")
DEFAULT_TIMEOUT = int(os.environ.get("MC_ODATA_TIMEOUT_S", "30"))

# The OData services SAP Note 2462327 documents as customer-callable.
_ODATA_PROJECT_SVC   = "/sap/opu/odata4/sap/api_migrationcockpit_project"
_ODATA_RUNTIME_SVC   = "/sap/opu/odata4/sap/api_migrationcockpit_object_runtime"
_ODATA_MAPPING_SVC   = "/sap/opu/odata4/sap/api_migrationcockpit_mapping"


def lambda_handler(event, context):
    run_id       = event.get("run_id", f"local-{int(time.time())}")
    project_id   = event.get("project_id") or f"M4H_{run_id[:24].upper()}"
    project_desc = event.get("project_desc") or f"Migrate4HANA run {run_id}"
    objects      = event.get("objects") or []
    staging_bkt  = event.get("staging_bucket") or STAGING_BUCKET
    template_pfx = event.get("template_prefix") or f"runs/{run_id}/mc-templates/"
    dry_run      = bool(event.get("dry_run", False))
    force_recr   = bool(event.get("force_recreate", False))
    creds_arn    = event.get("target_creds_arn") or os.environ.get("TARGET_SECRETS_ARN")

    log_stage_event(run_id, "mc-project-provisioner", "started",
                    {"project_id": project_id, "n_objects": len(objects),
                     "dry_run": dry_run})

    try:
        creds = _load_creds(creds_arn)
    except Exception as e:
        return _return_failure(run_id, project_id, staging_bkt,
                                "credentials_unavailable", str(e), objects)

    # ── Strategy A: OData ─────────────────────────────────────────────────
    create_res = _odata_project_create(creds, project_id, project_desc,
                                        force_recreate=force_recr,
                                        dry_run=dry_run)
    bound: list = []
    deferred: list = []
    field_map_results: list = []

    if create_res["ok"] or create_res.get("already_exists"):
        for obj in objects:
            b = _odata_object_bind(creds, project_id, obj,
                                    staging_bkt, template_pfx,
                                    dry_run=dry_run)
            if b["ok"]:
                bound.append(obj)
                fm = _odata_field_map(creds, project_id, obj, dry_run=dry_run)
                field_map_results.append({"object": obj,
                                           "mapping_status": fm.get("status"),
                                           "detail": fm.get("detail", "")})
            else:
                deferred.append({"object": obj, "reason": b.get("detail", "")})
        overall = "created" if bound else "manual_gate"
    else:
        for obj in objects:
            deferred.append({"object": obj,
                              "reason": "project create failed — see project runbook"})
        overall = "manual_gate"

    # Runbook artefact (always produced)
    runbook = _build_runbook(run_id, project_id, project_desc, objects,
                              bound, deferred, create_res, dry_run)
    rb_key = f"runs/{run_id}/mc/project-runbook.md"
    if not dry_run:
        s3.put_object(Bucket=staging_bkt, Key=rb_key,
                       Body=runbook.encode("utf-8"),
                       ContentType="text/markdown")

    # Hash-chain audit
    audit_block = _write_audit_block(run_id, project_id, overall,
                                       bound, deferred, create_res)

    result = {
        "status":            overall,
        "project_id":        project_id,
        "objects_bound":     bound,
        "objects_deferred":  deferred,
        "field_map_results": field_map_results,
        "strategy_a_result": create_res,
        "runbook_s3_uri":    f"s3://{staging_bkt}/{rb_key}",
        "audit_block":       audit_block,
        "run_id":            run_id,
        "dry_run":           dry_run,
    }
    log_stage_event(run_id, "mc-project-provisioner", overall,
                    {"project_id": project_id, "bound": len(bound),
                     "deferred": len(deferred)})
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Strategy A — OData
# ─────────────────────────────────────────────────────────────────────────────
def _odata_project_create(creds, project_id: str, project_desc: str,
                           *, force_recreate: bool = False,
                           dry_run: bool = False) -> dict:
    """POST to api_migrationcockpit_project/Projects.

    Returns:
        { ok, already_exists, http_status, detail, url }
    """
    base = _odata_base(creds)
    url  = f"{base}{_ODATA_PROJECT_SVC}/Projects"
    body = {
        "ProjectId":      project_id,
        "Description":    project_desc,
        "ProjectType":    "MigrationProject",
        "TransferType":   "STAGING_TABLES",
    }
    if dry_run:
        return {"ok": True, "already_exists": False, "http_status": 0,
                "detail": "dry_run — no OData mutation attempted",
                "url": url}

    try:
        # First check if project already exists (idempotent create)
        exists = _odata_get(f"{base}{_ODATA_PROJECT_SVC}/Projects"
                             f"('{urllib.parse.quote(project_id)}')", creds)
        if exists["ok"] and exists["http_status"] < 400:
            if not force_recreate:
                return {"ok": True, "already_exists": True,
                        "http_status": exists["http_status"],
                        "detail": "project already exists — idempotent skip",
                        "url": url}
            # Force recreate: DELETE then POST
            _odata_delete(f"{base}{_ODATA_PROJECT_SVC}/Projects"
                           f"('{urllib.parse.quote(project_id)}')", creds)

        resp = _odata_post(url, body, creds)
        return {"ok": resp["http_status"] < 400,
                "already_exists": False,
                "http_status": resp["http_status"],
                "detail": resp.get("body", "")[:400],
                "url": url}
    except Exception as e:
        return {"ok": False, "already_exists": False,
                "http_status": 0,
                "detail": f"{type(e).__name__}: {str(e)[:200]}",
                "url": url}


def _odata_object_bind(creds, project_id: str, object_id: str,
                        staging_bucket: str, template_prefix: str,
                        *, dry_run: bool = False) -> dict:
    """POST to object_runtime service — bind an object template + staging
    S3 pointer to the project."""
    base = _odata_base(creds)
    url  = (f"{base}{_ODATA_RUNTIME_SVC}/Projects"
            f"('{urllib.parse.quote(project_id)}')/Objects")
    body = {
        "ObjectId":       object_id,
        "SourceType":     "S3_STAGE",
        "SourceUri":      f"s3://{staging_bucket}/{template_prefix}{object_id}/",
        "MigrationClass": "STANDARD",
    }
    if dry_run:
        return {"ok": True, "http_status": 0,
                "detail": "dry_run"}

    try:
        resp = _odata_post(url, body, creds)
        return {"ok": resp["http_status"] < 400,
                "http_status": resp["http_status"],
                "detail": resp.get("body", "")[:400]}
    except Exception as e:
        return {"ok": False, "http_status": 0,
                "detail": f"{type(e).__name__}: {str(e)[:200]}"}


def _odata_field_map(creds, project_id: str, object_id: str,
                      *, dry_run: bool = False) -> dict:
    """POST to mapping service — auto-generate the default field map from the
    project's active bind. The mapping-service default is to align by identical
    field names + apply cross-walk maps registered in the target.

    In production, per-object custom mappings ride on the staging CSV headers
    itself; this call just tells MC 'accept the mapping suggestion'.
    """
    base = _odata_base(creds)
    url  = (f"{base}{_ODATA_MAPPING_SVC}/Projects"
            f"('{urllib.parse.quote(project_id)}')/Objects"
            f"('{urllib.parse.quote(object_id)}')/AutoMap")
    if dry_run:
        return {"ok": True, "status": "dry_run"}

    try:
        resp = _odata_post(url, {}, creds)
        return {"ok": resp["http_status"] < 400,
                "status": "auto-mapped" if resp["http_status"] < 400 else "deferred",
                "detail": resp.get("body", "")[:200]}
    except Exception as e:
        return {"ok": False, "status": "deferred",
                "detail": f"{type(e).__name__}: {str(e)[:200]}"}


# ─────────────────────────────────────────────────────────────────────────────
# OData HTTP helpers — retries, exponential backoff, structured logging
# ─────────────────────────────────────────────────────────────────────────────
def _odata_base(creds) -> str:
    """Derive https://host:port from creds. Prefer explicit https_url in the
    secret; fall back to ashost + https_port default 44300."""
    if creds.get("odata_base_url"):
        return creds["odata_base_url"].rstrip("/")
    host = creds.get("ashost") or creds.get("host")
    port = creds.get("https_port", 44300)
    return f"https://{host}:{port}"


def _basic_auth_header(creds) -> str:
    user = creds.get("user") or creds.get("username") or ""
    pwd  = creds.get("passwd") or creds.get("password") or ""
    tok  = base64.b64encode(f"{user}:{pwd}".encode()).decode()
    return f"Basic {tok}"


def _odata_get(url: str, creds) -> dict:
    return _odata_request("GET", url, None, creds)


def _odata_post(url: str, body: dict, creds) -> dict:
    return _odata_request("POST", url, body, creds)


def _odata_delete(url: str, creds) -> dict:
    return _odata_request("DELETE", url, None, creds)


def _odata_request(method: str, url: str, body: Optional[dict], creds,
                    *, max_retries: int = 3, backoff_base: float = 0.5) -> dict:
    """Uniform OData caller with exponential backoff on 5xx.

    Uses urllib (stdlib) so no third-party dep is required in the Lambda
    bundle. TLS verification is on by default; SAP-side self-signed certs
    must be handled with M4H_ODATA_INSECURE=1 at the deployment level.
    """
    import ssl

    ctx = ssl.create_default_context()
    if os.environ.get("M4H_ODATA_INSECURE") == "1":  # opt-in for lab systems
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "Authorization": _basic_auth_header(creds),
        "Accept":         "application/json",
        "X-Requested-With": "XMLHttpRequest",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"

    last_exc: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers,
                                          method=method)
            with urllib.request.urlopen(req, context=ctx,
                                          timeout=DEFAULT_TIMEOUT) as resp:
                text = resp.read().decode("utf-8", errors="replace")
                return {"ok": True, "http_status": resp.status,
                        "body": text}
        except urllib.error.HTTPError as e:
            text = ""
            try:
                text = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            if e.code >= 500 and attempt < max_retries - 1:
                time.sleep(backoff_base * (2 ** attempt))
                continue
            return {"ok": False, "http_status": e.code, "body": text}
        except (urllib.error.URLError, TimeoutError) as e:
            last_exc = e
            if attempt < max_retries - 1:
                time.sleep(backoff_base * (2 ** attempt))
                continue
            return {"ok": False, "http_status": 0,
                    "body": f"transport error: {type(e).__name__}: {e}"}
        except Exception as e:
            last_exc = e
            return {"ok": False, "http_status": 0,
                    "body": f"unexpected error: {type(e).__name__}: {e}"}

    return {"ok": False, "http_status": 0,
            "body": f"max retries exceeded: {last_exc}"}


# ─────────────────────────────────────────────────────────────────────────────
# Runbook + audit block
# ─────────────────────────────────────────────────────────────────────────────
def _build_runbook(run_id: str, project_id: str, project_desc: str,
                    objects: list, bound: list, deferred: list,
                    create_res: dict, dry_run: bool) -> str:
    header = (
        f"# MC Project Provisioning Runbook — {project_id}\n\n"
        f"**run_id:** `{run_id}`  \n"
        f"**description:** {project_desc}  \n"
        f"**dry_run:** `{dry_run}`  \n\n"
    )
    outcome = "## Automated outcome\n\n"
    if create_res.get("ok") and not create_res.get("already_exists"):
        outcome += (f"- **Project created via OData** "
                     f"(HTTP {create_res.get('http_status')})\n")
    elif create_res.get("already_exists"):
        outcome += ("- **Project already existed on target** — idempotent skip.\n")
    else:
        outcome += (f"- **Automated create FAILED** "
                     f"(HTTP {create_res.get('http_status')}): "
                     f"{create_res.get('detail')}\n")
    outcome += f"- **Objects bound:** {len(bound)} / {len(objects)}\n"
    if deferred:
        outcome += (f"- **Objects deferred to manual bind:** "
                     f"{[d['object'] for d in deferred]}\n")

    manual = "\n## Manual fallback (LTMC / Fiori 'Migrate Your Data')\n\n"
    manual += (
        f"If the automated OData path is unavailable on your target release, "
        f"execute the following in S/4 as a MC Administrator:\n\n"
        f"1. Open Fiori app **Migrate Your Data**.\n"
        f"2. Create migration project `{project_id}` "
        f"(description: {project_desc}).\n"
        f"3. Add these migration objects one by one:\n"
    )
    for o in objects:
        manual += f"   - `{o}`\n"
    manual += (
        "\n4. Point each object at the S3 staging bucket "
        "(configure Cloud Connector or the SAP-supported "
        "staging-table upload mechanism).\n"
        "5. Return to the Migrate4HANA console and mark the "
        "**mc-project-provisioner** gate as `manual_confirmed`.\n"
    )
    return header + outcome + manual


def _write_audit_block(run_id: str, project_id: str, status: str,
                        bound: list, deferred: list, create_res: dict) -> dict:
    """Write a hash-chain block to compliance-ledger DDB. Best-effort; a
    failure here does NOT fail the Lambda (audit is defensive)."""
    block_body = {
        "block_type":       "mc_project_provisioner",
        "run_id":           run_id,
        "project_id":       project_id,
        "status":           status,
        "objects_bound":    bound,
        "objects_deferred": [d.get("object") for d in deferred],
        "odata_http":       create_res.get("http_status"),
        "ts":               int(time.time() * 1000),
    }
    body_str = json.dumps(block_body, sort_keys=True, default=str)
    block_hash = hashlib.sha256(body_str.encode()).hexdigest()

    prev = _read_prev_hash(run_id)
    linked_hash = hashlib.sha256(
        f"{prev}::{block_hash}".encode()).hexdigest()

    try:
        ddb.put_item(TableName=LEDGER_TABLE, Item={
            "chain_id":   {"S": f"run:{run_id}"},
            "seq":        {"N": str(block_body["ts"])},
            "block_type": {"S": "mc_project_provisioner"},
            "prev_hash":  {"S": prev},
            "block_hash": {"S": linked_hash},
            "body":       {"S": body_str},
        })
        return {"prev_hash": prev, "block_hash": linked_hash,
                "written": True}
    except Exception as e:
        return {"prev_hash": prev, "block_hash": linked_hash,
                "written": False, "reason": str(e)[:200]}


def _read_prev_hash(run_id: str) -> str:
    """Return the previous block_hash for the chain, or genesis (0×64)."""
    try:
        resp = ddb.query(
            TableName=LEDGER_TABLE,
            KeyConditionExpression="chain_id = :c",
            ExpressionAttributeValues={":c": {"S": f"run:{run_id}"}},
            ScanIndexForward=False, Limit=1)
        items = resp.get("Items") or []
        if items:
            return items[0].get("block_hash", {}).get("S") or ("0" * 64)
    except Exception:
        pass
    return "0" * 64


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _load_creds(arn: Optional[str]) -> dict:
    if not arn:
        raise RuntimeError("no target_creds_arn provided")
    val = secrets.get_secret_value(SecretId=arn)["SecretString"]
    return json.loads(val)


def _return_failure(run_id: str, project_id: str, staging_bucket: str,
                     code: str, detail: str, objects: list) -> dict:
    log_stage_event(run_id, "mc-project-provisioner", "failed",
                    {"code": code, "detail": detail[:200]})
    return {"status": "failed", "project_id": project_id,
            "reason": code, "detail": detail,
            "objects_bound": [],
            "objects_deferred": [{"object": o, "reason": code} for o in objects],
            "run_id": run_id}
