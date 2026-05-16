"""
idoc-orchestrator — Phase 5, Stage 18
======================================
POST IDoc XML payloads to /sap/bc/idoc_xml on the target. SAP's inbound
processor handles the actual data write. We only POST + monitor (read).
"""
import json
import logging
import os
import sys
import time
import boto3
import urllib3

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

http = urllib3.PoolManager()
s3 = boto3.client("s3")
secrets = boto3.client("secretsmanager")
STAGING_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hana-staging-dev")


def lambda_handler(event, context):
    run_id = event.get("run_id", "local")
    
    obj = event.get("object")
    if not obj:
        log_stage_event(run_id, "idoc-orchestrator", "completed",
                        {"mode": "pass_through", "reason": "no_object_spec"})
        return {"status": "ok", "mode": "pass_through",
                "reason": "No object spec provided; IDoc orchestration skipped."}
    target_creds_arn = event.get("target_creds_arn") or os.environ.get("TARGET_SECRETS_ARN")

    log_stage_event(run_id, "idoc-orchestrator", "started", {"object": obj})

    try:
        creds = json.loads(secrets.get_secret_value(SecretId=target_creds_arn)["SecretString"])
        bucket, key = _parse_s3(payload_s3)
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()

        post_res = _post_idoc(creds, body)
        if post_res["status"] != 200:
            raise RuntimeError(f"IDoc POST failed: {post_res}")

        idoc_numbers = post_res.get("idoc_numbers", [])
        status_res = _monitor_idoc_status(creds, idoc_numbers,
                                          timeout_s=event.get("timeout_s", 1800))

        result = {"object": obj, "posted": len(idoc_numbers),
                  "status": status_res, "method": "IDoc inbound /sap/bc/idoc_xml"}
        s3.put_object(Bucket=STAGING_BUCKET,
                      Key=f"runs/{run_id}/idoc/{obj}/result.json",
                      Body=json.dumps(result, default=str).encode())

        ok = all(s == "53" for s in status_res.values()) if status_res else False
        log_stage_event(run_id, "idoc-orchestrator",
                        "completed" if ok else "partial",
                        {"object": obj, "posted": len(idoc_numbers)})
        return {"status": "success" if ok else "partial", **result}

    except Exception as e:
        logger.exception("idoc-orchestrator failed for %s", obj)
        log_stage_event(run_id, "idoc-orchestrator", "failed", {"object": obj, "error": str(e)})
        return {"status": "failed", "object": obj, "error": str(e)}


def _parse_s3(uri):
    p = uri.replace("s3://", "").split("/", 1)
    return p[0], p[1]


def _post_idoc(creds, body: bytes) -> dict:
    import base64
    auth = "Basic " + base64.b64encode(f"{creds['user']}:{creds['passwd']}".encode()).decode()
    url = f"https://{creds['ashost']}:{creds.get('https_port', 443)}/sap/bc/idoc_xml"
    r = http.request("POST", url, body=body,
                     headers={"Authorization": auth, "Content-Type": "text/xml; charset=utf-8"},
                     timeout=urllib3.Timeout(connect=15, read=120))
    idoc_numbers = []
    try:
        for line in r.data.decode("utf-8", errors="ignore").splitlines():
            if "DOCNUM" in line.upper():
                idoc_numbers.append(line.strip())
    except Exception:
        pass
    return {"status": r.status, "idoc_numbers": idoc_numbers,
            "response_tail": (r.data or b"")[-1024:].decode("utf-8", errors="ignore")}


def _monitor_idoc_status(creds, idoc_numbers, timeout_s=1800) -> dict:
    """Read EDIDS via RFC_READ_TABLE — read-only."""
    if not idoc_numbers or Connection is None:
        return {n: "?" for n in idoc_numbers}
    conn = Connection(ashost=creds["ashost"], sysnr=creds["sysnr"], client=creds["client"],
                      user=creds["user"], passwd=creds["passwd"])
    deadline = time.time() + timeout_s
    statuses = {n: "?" for n in idoc_numbers}
    while time.time() < deadline and any(v in ("?", "64", "50", "51", "52") for v in statuses.values()):
        for n in list(statuses.keys()):
            try:
                res = conn.call("RFC_READ_TABLE", QUERY_TABLE="EDIDS",
                                OPTIONS=[{"TEXT": f"DOCNUM EQ '{n}'"}],
                                FIELDS=[{"FIELDNAME": "STATUS"}], ROWCOUNT=1)
                rows = res.get("DATA", [])
                if rows:
                    statuses[n] = rows[0]["WA"].strip()
            except Exception as e:
                logger.warning("IDoc status read failed for %s: %s", n, e)
        if all(v == "53" or (v.startswith("5") and v != "50" and v != "52") for v in statuses.values()):
            break
        time.sleep(15)
    return statuses
