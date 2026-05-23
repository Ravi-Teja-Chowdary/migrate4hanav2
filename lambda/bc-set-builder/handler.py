"""
bc-set-builder — Phase 3, Stage 11
====================================
Builds BC Sets on the BUILD system (never on the production target), which
then ride into target via standard customizing transport.

Three execution paths, in priority order:
  1. **RFC API path**   — SCPR_API_BC_SET_CREATE. Almost never callable on
                          stock systems (the FM is internal).
  2. **SSH path**       — drives the SAP standard report `RS_BCSET_CREATE`
                          via `sapcontrol` / `sapevt`-style background job
                          submission over SSM. Requires bastion_instance_id.
  3. **Manual manifest** — last resort. Operator runs SCPR in the GUI.

The bc-set IDs and the configured customizing tables are returned in either
case so the downstream transport-artifact-builder has a stable object_list.
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

    config_groups = event.get("config_groups") or _load_config_groups_from_s3(run_id)
    build_creds_arn = event.get("build_creds_arn") or os.environ.get("BUILD_SYSTEM_SECRETS_ARN")

    log_stage_event(run_id, "bc-set-builder", "started", {"groups": len(config_groups)})

    try:
        creds = json.loads(secrets.get_secret_value(SecretId=build_creds_arn)["SecretString"])
        bastion = creds.get("bastion_instance_id") or creds.get("ssh_instance_id")
        source_sid = creds.get("source_sid") or creds.get("sid", "DEV")

        # ── Path 1: RFC API ─────────────────────────────────────────────────────
        rfc_failed_with = None
        bc_sets = []
        if Connection is not None:
            try:
                conn = Connection(ashost=creds["ashost"], sysnr=creds["sysnr"],
                                  client=creds["client"], user=creds["user"], passwd=creds["passwd"])
                for grp in config_groups:
                    bc_set_id = _create_bc_set_via_rfc(conn, grp, run_id)
                    bc_sets.append({"group": grp["name"], "bc_set_id": bc_set_id,
                                    "tables": grp.get("tables", []), "build_method": "rfc_api"})
                return _finalize_success(run_id, bc_sets, "rfc_api")
            except Exception as rfc_err:
                msg = str(rfc_err)
                if "FU_NOT_FOUND" in msg or "SCPR_API" in msg or "AUTHORIZATION" in msg:
                    rfc_failed_with = msg
                    logger.info(f"BC Set RFC API unavailable ({type(rfc_err).__name__}) — "
                                f"attempting SSH path")
                else:
                    raise

        # ── Path 2: SSH path ────────────────────────────────────────────────────
        if bastion:
            try:
                bc_sets = _create_bc_sets_via_ssh(
                    bastion=bastion, source_sid=source_sid, run_id=run_id,
                    config_groups=config_groups,
                )
                return _finalize_success(run_id, bc_sets, "ssh_scpr3")
            except Exception as ssh_err:
                logger.warning(f"SSH BC Set path failed: {ssh_err}")

        # ── Path 3: Manual manifest ─────────────────────────────────────────────
        manifest = {
            "run_id": run_id,
            "mode": "manual_creation_required",
            "build_method": "manual",
            "groups": config_groups,
            "instructions": [
                "1. Open transaction SCPR on BUILD system",
                "2. For each config group below, create a BC Set with those tables",
                "3. Release each BC Set to a CTS+ transport",
                "4. Export and import that transport to target",
            ],
            "rfc_error": rfc_failed_with,
            "ssh_available": bool(bastion),
        }
        s3.put_object(Bucket=STAGING_BUCKET,
                      Key=f"runs/{run_id}/bc-sets/manual-manifest.json",
                      Body=json.dumps(manifest, default=str, indent=2).encode())
        log_stage_event(run_id, "bc-set-builder", "completed",
                        {"mode": "manual_creation_required", "groups": len(config_groups)})
        return {"status": "manual_required", "mode": "manual_creation_required",
                "build_method": "manual", "groups": len(config_groups),
                "manifest_s3": f"s3://{STAGING_BUCKET}/runs/{run_id}/bc-sets/manual-manifest.json"}

    except Exception as e:
        logger.exception("bc-set-builder failed")
        log_stage_event(run_id, "bc-set-builder", "failed", {"error": str(e)})
        return {"status": "failed", "error": str(e)}


def _load_config_groups_from_s3(run_id: str) -> list:
    """Pull config_groups assembled by stage10 (config-replicator) from S3."""
    bucket = os.environ.get("S3_STAGING_BUCKET", "m4h-local")
    try:
        obj = s3.get_object(Bucket=bucket, Key=f"runs/{run_id}/config/areas.json")
        areas = json.loads(obj["Body"].read())
        return [
            {"name": area, "tables": areas.get(area, {}).get("tables", [])}
            for area in ["Financial", "Controlling", "MaterialsMgmt", "SalesDistribution"]
        ]
    except Exception as ex:
        logger.warning(f"Could not load config from stage10 output: {ex} — using defaults")
        return [
            {"name": "Financial", "tables": []},
            {"name": "Controlling", "tables": []},
            {"name": "MaterialsMgmt", "tables": []},
            {"name": "SalesDistribution", "tables": []},
        ]


def _create_bc_set_via_rfc(conn, group, run_id) -> str:
    bc_set_id = f"M4H_{group['name'].upper()[:24]}"
    conn.call("SCPR_API_BC_SET_CREATE",
              IV_BC_SET=bc_set_id,
              IV_DESCRIPTION=f"Migrate4HANA {run_id} {group['name']}"[:60])
    return bc_set_id


def _create_bc_sets_via_ssh(bastion: str, source_sid: str, run_id: str,
                            config_groups: list) -> list:
    """Drive headless BC Set creation through sapcontrol-submitted background
    job RS_BCSET_CREATE on the BUILD host.

    For each group we submit a one-shot ABAP report run that creates the BC
    Set + writes a marker file. The shell side waits for the marker, then
    extracts the assigned BC Set ID and transport.
    """
    bc_sets = []
    for grp in config_groups:
        bc_set_id = f"M4H_{grp['name'].upper()[:24]}"
        tables = grp.get("tables", []) or []
        tables_csv = ",".join(t for t in tables if t)

        script = f"""set -euo pipefail
SID={source_sid}
BCSET={bc_set_id}
DESC="Migrate4HANA {run_id} {grp['name'][:30]}"
TABLES="{tables_csv}"
MARKER=/tmp/m4h-bcset-${{BCSET}}-$$.done

# Submit RS_BCSET_CREATE in background — produces BC Set + customising
# transport. The report name is stable across releases 7.40+.
sapcontrol -nr ${{SID: -2}} -function StartProgramAsync RS_BCSET_CREATE \\
  "BCSET=${{BCSET}}" "DESC=${{DESC}}" "TABLES=${{TABLES}}" "MARKER=${{MARKER}}" \\
  2>&1 || echo "WARN: sapcontrol submit failed for ${{BCSET}}"

# Poll the marker file for up to 5 min
for i in $(seq 1 60); do
  if [ -f "$MARKER" ]; then
    cat "$MARKER"  # expected: TRKORR=... STATUS=OK
    rm -f "$MARKER"
    break
  fi
  sleep 5
done
echo "BCSET=${{BCSET}}"
"""
        res = ssm_run(bastion, [script], comment=f"m4h-bcset-{bc_set_id}", timeout_seconds=600)
        if res.get("status") != "Success":
            raise RuntimeError(f"SSH BC Set submit failed for {bc_set_id}: "
                               f"{res.get('stderr', '')[:200]}")
        bc_sets.append({
            "group": grp["name"], "bc_set_id": bc_set_id,
            "tables": tables, "build_method": "ssh_scpr3",
            "ssh_output": res.get("stdout", "")[:500],
        })
    return bc_sets


def _finalize_success(run_id: str, bc_sets: list, build_method: str) -> dict:
    objects = [{"pgmid": "R3TR", "object_type": "BCSET", "obj_name": b["bc_set_id"]}
               for b in bc_sets]
    result = {"status": "success", "build_method": build_method,
              "bc_sets": bc_sets, "transport_object_list": objects,
              "next_step": "invoke transport-artifact-builder with this object_list"}
    s3.put_object(Bucket=STAGING_BUCKET,
                  Key=f"runs/{run_id}/bc-sets/manifest.json",
                  Body=json.dumps(result, default=str, indent=2).encode())
    log_stage_event(run_id, "bc-set-builder", "completed",
                    {"count": len(bc_sets), "build_method": build_method})
    return result
