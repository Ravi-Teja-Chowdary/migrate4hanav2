"""
sizing-advisor — Phase 0, Stage 2
==================================
Recommend HANA + app server sizing for the target S/4HANA based on
ECC database footprint and workload metrics. Outputs an AWS instance
recommendation and warnings for capacity-planning conversations.
"""

from __future__ import annotations
import json
import logging
import os
import sys
import boto3

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "utils")))
from logger import log_stage_event  # type: ignore

try:
    import sapnwrfc  # noqa: F401
except Exception:
    pass
try:
    from pyrfc import Connection
except ImportError:
    Connection = None

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
secrets = boto3.client("secretsmanager")
STAGING_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hana-staging-dev")

HANA_BANDS = [
    (256,   "r5.8xlarge",   "256 GB"),
    (512,   "r5.16xlarge",  "512 GB"),
    (1024,  "u-3tb1.56xlarge", "1 TB"),
    (2048,  "u-6tb1.56xlarge", "2 TB"),
    (4096,  "u-9tb1.112xlarge", "4 TB"),
    (6144,  "u-12tb1.112xlarge", "6 TB"),
    (12288, "u-18tb1.112xlarge", "12 TB"),
]


def lambda_handler(event, context):
    run_id = event.get("run_id", "local")
    secrets_arn = event.get("secrets_arn") or os.environ.get("SECRETS_ARN")

    log_stage_event(run_id, "sizing-advisor", "started", {})

    try:
        creds = json.loads(secrets.get_secret_value(SecretId=secrets_arn)["SecretString"])
        conn = Connection(ashost=creds["ashost"], sysnr=creds["sysnr"],
                          client=creds["client"], user=creds["user"], passwd=creds["passwd"])

        db_size_gb = _estimate_db_size_gb(conn)
        workload = _estimate_workload(conn)
        recommendation = _recommend(db_size_gb, workload)

        result = {"ecc_db_size_gb": db_size_gb, "workload": workload,
                  "recommendation": recommendation,
                  "warnings": _warnings(db_size_gb, workload)}
        s3.put_object(Bucket=STAGING_BUCKET,
                      Key=f"runs/{run_id}/sizing-advisor/recommendation.json",
                      Body=json.dumps(result, default=str).encode())

        log_stage_event(run_id, "sizing-advisor", "completed",
                        {"hana_instance": recommendation["hana_instance"]})
        return {"status": "success", **result}

    except Exception as e:
        logger.exception("sizing-advisor failed")
        log_stage_event(run_id, "sizing-advisor", "failed", {"error": str(e)})
        return {"status": "failed", "error": str(e)}


def _estimate_db_size_gb(conn) -> int:
    """HANA in-memory ~ 30% of ECC disk size (rough)."""
    try:
        res = conn.call("RFC_READ_TABLE", QUERY_TABLE="DBSTATTORA",
                        FIELDS=[{"FIELDNAME": "TSIZE"}], ROWCOUNT=10000)
        total_kb = sum(int((r["WA"] or "0").strip() or 0) for r in res.get("DATA", []))
        ecc_gb = max(50, total_kb // (1024 * 1024))
        return int(ecc_gb * 0.30)
    except Exception:
        return 256


def _estimate_workload(conn) -> dict:
    return {"peak_dialog_users": 0, "batch_jobs_per_day": 0,
            "note": "ST03N extraction not yet wired; fill manually for production"}


def _recommend(db_size_gb: int, workload: dict) -> dict:
    for cap, inst, mem in HANA_BANDS:
        if db_size_gb <= cap:
            return {"hana_instance": inst, "hana_memory": mem,
                    "app_servers": 2, "app_instance": "r5.4xlarge"}
    return {"hana_instance": "u-24tb1.metal", "hana_memory": "24 TB",
            "app_servers": 4, "app_instance": "r5.8xlarge"}


def _warnings(db_size_gb: int, workload: dict) -> list[str]:
    w = []
    if db_size_gb > 6144:
        w.append("Database > 6 TB — consider scale-out and HANA partitioning")
    if not workload.get("peak_dialog_users"):
        w.append("Workload metrics not collected — recommendation is DB-size-only")
    return w
