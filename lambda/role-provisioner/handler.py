"""
role-provisioner (lift-and-shift) — PFCG transport export, never auto-assign.

Two strict rules:
    1. Roles are exported from the ECC PFCG buffer as a workbench-customizing
       transport, then imported via the standard CTS+ chain. We never call
       PRGN_RFC_ROLE_CREATE or BAPI_USER_ACTGROUPS_ASSIGN against the target.
    2. User-to-role assignments are NEVER written automatically. We emit a
       CSV (``user_assignments.csv``) for the customer's security team to
       review and apply via SU01 / SUCOMP / IAS — this preserves audit and
       SoD review obligations.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import time

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "utils"))

import boto3  # noqa: E402

try:
    import sapnwrfc  # noqa: F401
except Exception:  # pragma: no cover
    pass

try:
    from logger import log_stage_event  # type: ignore
except Exception:  # pragma: no cover
    def log_stage_event(*a, **k):  # type: ignore
        pass

LAMBDA = boto3.client("lambda")
S3 = boto3.client("s3")
SECRETS = boto3.client("secretsmanager")
STAGING_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hanav2-staging-dev")

ARTIFACT_BUILDER_FN = os.environ.get("TRANSPORT_ARTIFACT_BUILDER_FN", "transport-artifact-builder")
FILE_PLACER_FN     = os.environ.get("TRANSPORT_FILE_PLACER_FN",     "transport-file-placer")
IMPORT_EXEC_FN     = os.environ.get("TRANSPORT_IMPORT_EXECUTOR_FN", "transport-import-executor")
IMPORT_VERIFY_FN   = os.environ.get("TRANSPORT_IMPORT_VERIFIER_FN", "transport-import-verifier")


def _invoke(fn: str, payload: dict) -> dict:
    r = LAMBDA.invoke(FunctionName=fn, InvocationType="RequestResponse",
                      Payload=json.dumps(payload).encode("utf-8"))
    body = r["Payload"].read().decode("utf-8") if r.get("Payload") else "{}"
    try:
        return json.loads(body)
    except Exception:
        return {"status": "error", "raw": body}


def _ecc_connection(secret_id: str):
    sec = json.loads(SECRETS.get_secret_value(SecretId=secret_id)["SecretString"])
    from pyrfc import Connection  # noqa
    return Connection(
        ashost=sec["ashost"], sysnr=sec.get("sysnr", "00"),
        client=sec["client"], user=sec["user"], passwd=sec["password"],
        lang=sec.get("lang", "EN"),
    )


def _list_pfcg_roles(conn, role_filter: str) -> list:
    """Read role headers via read-only AGR_DEFINE access."""
    try:
        result = conn.call("RFC_READ_TABLE",
                           QUERY_TABLE="AGR_DEFINE",
                           OPTIONS=[{"TEXT": f"AGR_NAME LIKE '{role_filter}'"}],
                           FIELDS=[{"FIELDNAME": "AGR_NAME"}, {"FIELDNAME": "PARENT_AGR"}])
        return [r["WA"].split("|")[0].strip() for r in result.get("DATA", [])]
    except Exception:
        return []


def _list_user_assignments(conn, role_filter: str) -> list:
    try:
        result = conn.call("RFC_READ_TABLE",
                           QUERY_TABLE="AGR_USERS",
                           OPTIONS=[{"TEXT": f"AGR_NAME LIKE '{role_filter}'"}],
                           FIELDS=[{"FIELDNAME": "AGR_NAME"}, {"FIELDNAME": "UNAME"},
                                   {"FIELDNAME": "FROM_DAT"}, {"FIELDNAME": "TO_DAT"}])
        rows = []
        for r in result.get("DATA", []):
            parts = [p.strip() for p in r["WA"].split("|")]
            if len(parts) >= 4:
                rows.append({"role": parts[0], "user": parts[1],
                             "from_date": parts[2], "to_date": parts[3]})
        return rows
    except Exception:
        return []


def lambda_handler(event, context):
    run_id = event.get("run_id", f"run-{int(time.time())}")
    role_filter = event.get("role_filter", "Z*")
    secret_id = event.get("ecc_secret_id", os.environ.get("ECC_SECRET_ID", ""))
    log_stage_event(run_id, "role-provisioner", "start", {"filter": role_filter})

    roles = []
    assignments = []
    if secret_id:
        try:
            conn = _ecc_connection(secret_id)
            roles = _list_pfcg_roles(conn, role_filter)
            assignments = _list_user_assignments(conn, role_filter)
        except Exception as e:
            log_stage_event(run_id, "role-provisioner", "warning", {"ecc_read_error": str(e)})

    # 1. Build assignments CSV (NEVER auto-applied)
    csv_buf = io.StringIO()
    w = csv.DictWriter(csv_buf, fieldnames=["role", "user", "from_date", "to_date"])
    w.writeheader()
    w.writerows(assignments)
    assignments_key = f"runs/{run_id}/role-provisioner/user_assignments.csv"
    S3.put_object(Bucket=STAGING_BUCKET, Key=assignments_key,
                  Body=csv_buf.getvalue().encode(), ContentType="text/csv")

    # 2. Pack roles into a customizing transport for STMS push
    transport_objects = [{"object": "ACGR", "obj_name": r} for r in roles]
    build = _invoke(ARTIFACT_BUILDER_FN, {"run_id": run_id, "object_kind": "config",
                                            "objects": transport_objects})
    transport = build.get("transport_request") or build.get("trkorr")
    place = imp = verify = {"status": "skipped"}
    if transport:
        place = _invoke(FILE_PLACER_FN, {"run_id": run_id, "transport_request": transport,
                                           "cofile_s3": build.get("cofile_s3"),
                                           "datafile_s3": build.get("datafile_s3")})
        imp = _invoke(IMPORT_EXEC_FN, {"run_id": run_id, "transport_request": transport})
        verify = _invoke(IMPORT_VERIFY_FN, {"run_id": run_id, "transport_request": transport})

    summary = {
        "run_id": run_id,
        "status": "ok",
        "roles_exported": len(roles),
        "user_assignments_csv": f"s3://{STAGING_BUCKET}/{assignments_key}",
        "manual_gate": {
            "owner": "Customer security team",
            "instruction": "Review user_assignments.csv and apply via SU01/IAS. "
                           "Migrate4HANA never auto-assigns roles to production users.",
        },
        "transport_request": transport,
        "import_rc": imp.get("rc"),
    }
    log_stage_event(run_id, "role-provisioner", "ok", summary)
    return summary
