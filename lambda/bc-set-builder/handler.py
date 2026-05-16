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
    
    # Try to get config_groups from event, or load from stage10 output
    config_groups = event.get("config_groups")
    if not config_groups:
        # Fallback: load from S3 if upstream stage didn't pass it inline
        staging_bucket = os.environ.get("S3_STAGING_BUCKET", "m4h-local")
        try:
            obj = s3.get_object(Bucket=staging_bucket,
                                Key=f"runs/{run_id}/config/areas.json")
            areas = json.loads(obj["Body"].read())
            # Synthesize config_groups from areas
            config_groups = [
                {"name": area, "tables": areas.get(area, {}).get("tables", [])}
                for area in ["Financial", "Controlling", "MaterialsMgmt", "SalesDistribution"]
            ]
            logger.info(f"Loaded {len(config_groups)} config groups from stage10 output")
        except Exception as ex:
            logger.warning(f"Could not load config from stage10 output: {ex} — using defaults")
            config_groups = [
                {"name": "Financial", "tables": []},
                {"name": "Controlling", "tables": []},
                {"name": "MaterialsMgmt", "tables": []},
                {"name": "SalesDistribution", "tables": []},
            ]
    build_creds_arn = event.get("build_creds_arn") or os.environ.get("BUILD_SYSTEM_SECRETS_ARN")

    log_stage_event(run_id, "bc-set-builder", "started", {"groups": len(config_groups)})

    try:
        creds = json.loads(secrets.get_secret_value(SecretId=build_creds_arn)["SecretString"])
        conn = Connection(ashost=creds["ashost"], sysnr=creds["sysnr"], client=creds["client"],
                          user=creds["user"], passwd=creds["passwd"])

        bc_sets = []
        rfc_available = True
        try:
            for grp in config_groups:
                bc_set_id = _create_bc_set(conn, grp, run_id)
                bc_sets.append({"group": grp["name"], "bc_set_id": bc_set_id,
                                "tables": grp.get("tables", [])})
        except Exception as rfc_err:
            msg = str(rfc_err)
            if "FU_NOT_FOUND" in msg or "SCPR_API" in msg:
                rfc_available = False
                logger.warning(f"BC Set API not RFC-enabled on build system: {msg}")
            else:
                raise

        if not rfc_available:
            # Emit manual manifest for basis team to create BC Sets via SCPR GUI
            manifest = {
                "run_id": run_id,
                "mode": "manual_creation_required",
                "groups": config_groups,
                "instructions": [
                    "1. Open transaction SCPR on BUILD system",
                    "2. For each config group below, create a BC Set with those tables",
                    "3. Release each BC Set to a CTS+ transport",
                    "4. Export and import that transport to target",
                ],
                "rfc_error": msg,
            }
            s3.put_object(Bucket=STAGING_BUCKET,
                          Key=f"runs/{run_id}/bc-sets/manual-manifest.json",
                          Body=json.dumps(manifest, default=str, indent=2).encode())
            logger.info(f"Wrote manual BC Set manifest to s3://{STAGING_BUCKET}/runs/{run_id}/bc-sets/")
            log_stage_event(run_id, "bc-set-builder", "completed",
                            {"mode": "manual_creation_required", "groups": len(config_groups)})
            return {"status": "manual_required", "mode": "manual_creation_required",
                    "groups": len(config_groups),
                    "manifest_s3": f"s3://{STAGING_BUCKET}/runs/{run_id}/bc-sets/manual-manifest.json"}

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
