"""
transport-artifact-builder — Phase 2/3
=======================================
Packages a CTS+ transport on the BUILD/SOURCE system, releases it,
exports cofile + datafile to S3.
"""
import json
import logging
import os
import sys
import boto3

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "utils")))
from logger import log_stage_event  # type: ignore
from sap_host_runner import run as ssm_run  # type: ignore

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
    object_list = event["object_list"]
    source_creds_arn = event.get("source_creds_arn") or os.environ.get("BUILD_SYSTEM_SECRETS_ARN")
    description = event.get("description", f"M4H lift-and-shift {run_id}")
    transport_type = event.get("transport_type", "K")

    log_stage_event(run_id, "transport-builder", "started",
                    {"object_count": len(object_list), "type": transport_type})

    try:
        creds = json.loads(secrets.get_secret_value(SecretId=source_creds_arn)["SecretString"])
        conn = Connection(ashost=creds["ashost"], sysnr=creds["sysnr"], client=creds["client"],
                          user=creds["user"], passwd=creds["passwd"])

        try:
            tr_id = _create_transport(conn, transport_type, description)
            for obj in object_list:
                _add_to_transport(conn, tr_id, obj)
            _release_transport(conn, tr_id)
        except Exception as rfc_err:
            # ECC releases prior to 7.50 don't expose TRINT_* internal FMs over RFC.
            # Emit a manifest the basis team can use to assemble a transport manually
            # via SE09/SE10 + tp release, or via abapGit.
            msg = str(rfc_err)
            if "FU_NOT_FOUND" in msg or "TRINT_" in msg or "TR_OBJECTS_INSERT" in msg:
                manifest = {
                    "run_id": run_id,
                    "mode": "manual_assembly_required",
                    "description": description,
                    "transport_type": transport_type,
                    "object_count": len(object_list),
                    "objects": object_list,
                    "instructions": [
                        "1. SE10 → Create Workbench Request with description above",
                        "2. Add the objects from this manifest (or use abapGit push)",
                        "3. Release the request (SE10 → truck icon)",
                        "4. Copy /usr/sap/trans/cofiles/K* + data/R* to S3 staging path",
                        "5. Re-run stage9b (transport-import-executor) pointing to that path",
                    ],
                    "rfc_error": msg,
                }
                key = f"runs/{run_id}/transports/manual/manifest.json"
                s3.put_object(Bucket=STAGING_BUCKET, Key=key,
                              Body=json.dumps(manifest, default=str, indent=2).encode())
                logger.warning(
                    f"Transport API not RFC-enabled on source. Wrote manual manifest to s3://{STAGING_BUCKET}/{key}"
                )
                log_stage_event(run_id, "transport-builder", "completed",
                                {"mode": "manual_assembly_required", "object_count": len(object_list)})
                return {"status": "manual_required", "mode": "manual_assembly_required",
                        "object_count": len(object_list),
                        "manifest_s3": f"s3://{STAGING_BUCKET}/{key}"}
            raise

        bastion = creds.get("bastion_instance_id")
        if not bastion:
            return {"status": "manual_export_required", "tr_id": tr_id,
                    "instruction": "Manually copy cofile + datafile to S3"}

        cof = f"/usr/sap/trans/cofiles/K{tr_id[-5:]}.{creds.get('source_sid', 'DEV')}"
        dat = f"/usr/sap/trans/data/R{tr_id[-5:]}.{creds.get('source_sid', 'DEV')}"
        s3_prefix = f"runs/{run_id}/transports/{tr_id}"
        cmds = [
            f"aws s3 cp {cof} s3://{STAGING_BUCKET}/{s3_prefix}/cofile",
            f"aws s3 cp {dat} s3://{STAGING_BUCKET}/{s3_prefix}/datafile",
        ]
        export = ssm_run(bastion, cmds, comment=f"export-{tr_id}", timeout_seconds=600)

        result = {"transport_id": tr_id, "type": transport_type,
                  "object_count": len(object_list),
                  "cofile_s3": f"s3://{STAGING_BUCKET}/{s3_prefix}/cofile",
                  "datafile_s3": f"s3://{STAGING_BUCKET}/{s3_prefix}/datafile",
                  "export_status": export.get("status")}
        s3.put_object(Bucket=STAGING_BUCKET, Key=f"{s3_prefix}/manifest.json",
                      Body=json.dumps(result, default=str).encode())

        log_stage_event(run_id, "transport-builder", "completed", {"transport_id": tr_id})
        return {"status": "success", **result}

    except Exception as e:
        logger.exception("transport-builder failed")
        log_stage_event(run_id, "transport-builder", "failed", {"error": str(e)})
        return {"status": "failed", "error": str(e)}


def _create_transport(conn, transport_type, description) -> str:
    res = conn.call("TRINT_REQUEST_CREATE",
                    REQUEST_TYPE=transport_type,
                    REQUEST_TEXT=description[:60])
    return res.get("REQUEST_HEADER", {}).get("TRKORR", "")


def _add_to_transport(conn, tr_id, obj) -> None:
    conn.call("TR_OBJECTS_INSERT",
              WI_TRKORR=tr_id,
              WT_OBJECTS=[{"PGMID": obj["pgmid"], "OBJECT": obj["object_type"],
                           "OBJ_NAME": obj["obj_name"]}])


def _release_transport(conn, tr_id) -> None:
    conn.call("TRINT_REQUEST_RELEASE", TRKORR=tr_id, IV_WITHOUT_DOCU="X")
