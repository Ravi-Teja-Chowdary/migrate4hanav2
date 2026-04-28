"""
bc-set-builder — Phase 3, Stage 11
====================================
Builds BC Sets on the BUILD system (never on the production target),
which then ride into target via standard customizing transport.
"""
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


def lambda_handler(event, context):
    run_id = event.get("run_id", "local")
    config_groups = event["config_groups"]
    build_creds_arn = event.get("build_creds_arn") or os.environ.get("BUILD_SYSTEM_SECRETS_ARN")

    log_stage_event(run_id, "bc-set-builder", "started", {"groups": len(config_groups)})

    try:
        creds = json.loads(secrets.get_secret_value(SecretId=build_creds_arn)["SecretString"])
        conn = Connection(ashost=creds["ashost"], sysnr=creds["sysnr"], client=creds["client"],
                          user=creds["user"], passwd=creds["passwd"])

        bc_sets = []
        for grp in config_groups:
            bc_set_id = _create_bc_set(conn, grp, run_id)
            bc_sets.append({"group": grp["name"], "bc_set_id": bc_set_id,
                            "tables": grp.get("tables", [])})

        objects = [{"pgmid": "R3TR", "object_type": "BCSET", "obj_name": b["bc_set_id"]}
                   for b in bc_sets]

        result = {"bc_sets": bc_sets, "transport_object_list": objects,
                  "next_step": "invoke transport-artifact-builder with this object_list"}
        s3.put_object(Bucket=STAGING_BUCKET,
                      Key=f"runs/{run_id}/bc-sets/manifest.json",
                      Body=json.dumps(result, default=str).encode())

        log_stage_event(run_id, "bc-set-builder", "completed", {"count": len(bc_sets)})
        return {"status": "success", **result}

    except Exception as e:
        logger.exception("bc-set-builder failed")
        log_stage_event(run_id, "bc-set-builder", "failed", {"error": str(e)})
        return {"status": "failed", "error": str(e)}


def _create_bc_set(conn, group, run_id) -> str:
    """Generate a BC Set on the BUILD system for the given customizing tables.

    SCPR_API_BC_SET_CREATE creates the BC Set on the build system's
    development class — this is a build-side operation; the data lands in
    the target only via a customizing transport later.
    """
    bc_set_id = f"M4H_{group['name'].upper()[:24]}"
    conn.call("SCPR_API_BC_SET_CREATE",
              IV_BC_SET=bc_set_id,
              IV_DESCRIPTION=f"Migrate4HANA {run_id} {group['name']}"[:60])
    return bc_set_id
