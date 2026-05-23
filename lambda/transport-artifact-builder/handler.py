"""
transport-artifact-builder — Phase 2/3
=======================================
Packages a CTS+ transport on the BUILD/SOURCE system, releases it, exports
cofile + datafile to S3.

Three execution paths, in priority order:
  1. **RFC API path**       — calls TRINT_REQUEST_CREATE / TR_OBJECTS_INSERT /
                              TRINT_REQUEST_RELEASE. Works on systems where
                              the internal transport FMs are RFC-enabled
                              (rare on stock ECC; common on dev BUILD systems
                              with custom enabling).
  2. **SSH/tp shell path**  — invokes `tp` and `abapGit` on the BUILD host via
                              SSM Run Command. This is the supported way to
                              create transports without exposing TRINT_* over
                              RFC. Requires `bastion_instance_id` in the
                              secret + the BUILD host having `tp` on PATH.
  3. **Manual manifest**    — last resort. Writes a JSON manifest enumerating
                              objects + step-by-step SE10/abapGit instructions.

The path actually used is recorded in the result manifest as `build_method`.
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
    object_kind = event.get("object_kind", "code")  # code | config

    log_stage_event(run_id, "transport-builder", "started",
                    {"object_count": len(object_list), "type": transport_type, "kind": object_kind})

    try:
        creds = json.loads(secrets.get_secret_value(SecretId=source_creds_arn)["SecretString"])
        bastion = creds.get("bastion_instance_id") or creds.get("ssh_instance_id")
        source_sid = creds.get("source_sid") or creds.get("sid", "DEV")

        # ── Path 1: RFC API ─────────────────────────────────────────────────────
        rfc_failed_with = None
        if Connection is not None:
            try:
                conn = Connection(ashost=creds["ashost"], sysnr=creds["sysnr"],
                                  client=creds["client"], user=creds["user"], passwd=creds["passwd"])
                tr_id = _create_transport_via_rfc(conn, transport_type, description)
                for obj in object_list:
                    _add_to_transport_via_rfc(conn, tr_id, obj)
                _release_transport_via_rfc(conn, tr_id)
                return _export_and_finalize(run_id, tr_id, source_sid, bastion, object_list,
                                            transport_type, build_method="rfc_api")
            except Exception as rfc_err:
                msg = str(rfc_err)
                if any(p in msg for p in ("FU_NOT_FOUND", "TRINT_", "TR_OBJECTS_INSERT", "AUTHORIZATION")):
                    rfc_failed_with = msg
                    logger.info(f"RFC transport API unavailable on source ({type(rfc_err).__name__}) — "
                                f"attempting SSH/tp fallback")
                else:
                    raise

        # ── Path 2: SSH/tp shell ────────────────────────────────────────────────
        if bastion:
            try:
                result = _build_transport_via_ssh(
                    bastion=bastion,
                    source_sid=source_sid,
                    run_id=run_id,
                    transport_type=transport_type,
                    description=description,
                    object_list=object_list,
                    object_kind=object_kind,
                )
                return _export_and_finalize(run_id, result["tr_id"], source_sid, bastion,
                                            object_list, transport_type,
                                            build_method="ssh_tp",
                                            ssh_output=result.get("ssh_output"))
            except Exception as ssh_err:
                logger.warning(f"SSH/tp build path failed: {ssh_err}")
                # fall through to manual manifest

        # ── Path 3: Manual manifest ─────────────────────────────────────────────
        manifest = {
            "run_id": run_id,
            "mode": "manual_assembly_required",
            "build_method": "manual",
            "description": description,
            "transport_type": transport_type,
            "object_kind": object_kind,
            "object_count": len(object_list),
            "objects": object_list,
            "instructions": [
                "1. SE10 → Create Workbench Request with description above",
                "2. Add the objects from this manifest (or use abapGit push)",
                "3. Release the request (SE10 → truck icon)",
                "4. Copy /usr/sap/trans/cofiles/K* + data/R* to S3 staging path",
                "5. Re-run stage9b (transport-import-executor) pointing to that path",
            ],
            "rfc_error": rfc_failed_with,
            "ssh_available": bool(bastion),
        }
        key = f"runs/{run_id}/transports/manual/manifest.json"
        s3.put_object(Bucket=STAGING_BUCKET, Key=key,
                      Body=json.dumps(manifest, default=str, indent=2).encode())
        logger.warning(
            f"Transport build degraded to manual_assembly_required. "
            f"Manifest at s3://{STAGING_BUCKET}/{key}"
        )
        log_stage_event(run_id, "transport-builder", "completed",
                        {"mode": "manual_assembly_required", "object_count": len(object_list)})
        return {"status": "manual_required", "mode": "manual_assembly_required",
                "build_method": "manual",
                "object_count": len(object_list),
                "manifest_s3": f"s3://{STAGING_BUCKET}/{key}"}

    except Exception as e:
        logger.exception("transport-builder failed")
        log_stage_event(run_id, "transport-builder", "failed", {"error": str(e)})
        return {"status": "failed", "error": str(e)}


# ── Path 1 helpers (RFC) ─────────────────────────────────────────────────────
def _create_transport_via_rfc(conn, transport_type, description) -> str:
    res = conn.call("TRINT_REQUEST_CREATE",
                    REQUEST_TYPE=transport_type,
                    REQUEST_TEXT=description[:60])
    return res.get("REQUEST_HEADER", {}).get("TRKORR", "")


def _add_to_transport_via_rfc(conn, tr_id, obj) -> None:
    # Accept either object schema: {"pgmid","object_type","obj_name"} OR
    # {"object_type","object_name"} (used by the local runner).
    pgmid = obj.get("pgmid", "R3TR")
    otype = obj.get("object_type")
    oname = obj.get("obj_name") or obj.get("object_name")
    conn.call("TR_OBJECTS_INSERT",
              WI_TRKORR=tr_id,
              WT_OBJECTS=[{"PGMID": pgmid, "OBJECT": otype, "OBJ_NAME": oname}])


def _release_transport_via_rfc(conn, tr_id) -> None:
    conn.call("TRINT_REQUEST_RELEASE", TRKORR=tr_id, IV_WITHOUT_DOCU="X")


# ── Path 2 helpers (SSH + tp) ────────────────────────────────────────────────
def _build_transport_via_ssh(bastion: str, source_sid: str, run_id: str,
                             transport_type: str, description: str,
                             object_list: list, object_kind: str) -> dict:
    """Build a CTS+ transport on the BUILD host using shell-invoked tp.

    Approach: drop a small shell script via SSM that:
      1. Creates an empty transport with `tp newreq <SID> "<desc>"`.
      2. Echoes the object list into the cofile via tp's add-objects mode
         OR uses abapGit for source-code objects.
      3. Releases via `tp release <TRKORR> <SID>`.
      4. Returns the assigned TRKORR on stdout.
    """
    # Serialize the object list to a /tmp file the script can read
    object_lines = []
    for obj in object_list:
        pgmid = obj.get("pgmid", "R3TR")
        otype = obj.get("object_type", "PROG")
        oname = obj.get("obj_name") or obj.get("object_name", "")
        object_lines.append(f"{pgmid} {otype} {oname}")
    object_file_content = "\n".join(object_lines)

    # The script runs as the SAP admin user (s4hadm/<sid>adm).
    # We use heredoc-safe quoting via printf %s to avoid shell expansion.
    script = f"""set -euo pipefail
SID={source_sid}
TRDIR=/usr/sap/trans
DESC="{description[:60].replace('"', '')}"
OBJFILE=$(mktemp /tmp/m4h-objects-XXXXXX)
printf '%s\\n' "{object_file_content.replace(chr(34), '')}" > "$OBJFILE"

# 1. Create empty transport (tp newreq returns TRKORR on stdout)
TR_OUTPUT=$(tp newreq $SID "$DESC" pf=$TRDIR/bin/TP_DOMAIN_$SID.PFL 2>&1) || {{
  echo "tp newreq failed: $TR_OUTPUT" >&2
  exit 1
}}
TRKORR=$(echo "$TR_OUTPUT" | grep -oE "[A-Z]{{3}}K9[0-9]+" | head -1)
if [ -z "$TRKORR" ]; then
  echo "Could not parse TRKORR from tp output: $TR_OUTPUT" >&2
  exit 2
fi
echo "TRKORR=$TRKORR"

# 2. Add objects (one per line: PGMID OBJECT OBJ_NAME)
while read -r pgmid otype oname; do
  [ -z "$oname" ] && continue
  tp addtobuffer "$TRKORR" "$pgmid" "$otype" "$oname" "$SID" \\
    pf=$TRDIR/bin/TP_DOMAIN_$SID.PFL 2>&1 || \\
    echo "WARN: could not add $pgmid/$otype/$oname" >&2
done < "$OBJFILE"

# 3. Release the transport (this exports cofile + datafile)
tp release $TRKORR $SID pf=$TRDIR/bin/TP_DOMAIN_$SID.PFL 2>&1
echo "RELEASED=$TRKORR"

rm -f "$OBJFILE"
"""

    cmds = [script]
    res = ssm_run(bastion, cmds, comment=f"m4h-tp-build-{run_id}", timeout_seconds=900)

    if res.get("status") != "Success":
        raise RuntimeError(f"tp shell build failed: status={res.get('status')} "
                           f"stderr={res.get('stderr', '')[:300]}")

    stdout = res.get("stdout", "")
    tr_id = None
    for line in stdout.splitlines():
        if line.startswith("TRKORR="):
            tr_id = line.split("=", 1)[1].strip()
            break
    if not tr_id:
        raise RuntimeError(f"tp build produced no TRKORR. Output: {stdout[:400]}")

    return {"tr_id": tr_id, "ssh_output": stdout[:2000]}


# ── Common: export cofile + datafile to S3 ───────────────────────────────────
def _export_and_finalize(run_id: str, tr_id: str, source_sid: str, bastion: str,
                        object_list: list, transport_type: str, build_method: str,
                        ssh_output: str = "") -> dict:
    if not bastion:
        manifest = {
            "run_id": run_id, "tr_id": tr_id, "transport_type": transport_type,
            "build_method": build_method, "object_count": len(object_list),
            "status": "manual_export_required",
            "instruction": (
                f"Transport {tr_id} created on BUILD system. Manually copy "
                f"/usr/sap/trans/cofiles/K* and /usr/sap/trans/data/R* matching "
                f"{tr_id} to s3://{STAGING_BUCKET}/runs/{run_id}/transports/{tr_id}/"
            ),
        }
        s3.put_object(Bucket=STAGING_BUCKET,
                      Key=f"runs/{run_id}/transports/{tr_id}/manifest.json",
                      Body=json.dumps(manifest, default=str, indent=2).encode())
        log_stage_event(run_id, "transport-builder", "completed",
                        {"mode": "manual_export_required", "tr_id": tr_id, "build_method": build_method})
        return manifest

    # Auto-export cofile + datafile via SSM
    cof = f"/usr/sap/trans/cofiles/K{tr_id[-5:]}.{source_sid}"
    dat = f"/usr/sap/trans/data/R{tr_id[-5:]}.{source_sid}"
    s3_prefix = f"runs/{run_id}/transports/{tr_id}"
    cmds = [
        f"aws s3 cp {cof} s3://{STAGING_BUCKET}/{s3_prefix}/cofile",
        f"aws s3 cp {dat} s3://{STAGING_BUCKET}/{s3_prefix}/datafile",
    ]
    export = ssm_run(bastion, cmds, comment=f"export-{tr_id}", timeout_seconds=600)

    result = {
        "status": "success",
        "build_method": build_method,
        "transport_id": tr_id,
        "type": transport_type,
        "object_count": len(object_list),
        "cofile_s3": f"s3://{STAGING_BUCKET}/{s3_prefix}/cofile",
        "datafile_s3": f"s3://{STAGING_BUCKET}/{s3_prefix}/datafile",
        "export_status": export.get("status"),
        "ssh_output_preview": ssh_output[:500] if ssh_output else None,
    }
    s3.put_object(Bucket=STAGING_BUCKET, Key=f"{s3_prefix}/manifest.json",
                  Body=json.dumps(result, default=str, indent=2).encode())

    log_stage_event(run_id, "transport-builder", "completed",
                    {"transport_id": tr_id, "build_method": build_method,
                     "export_status": export.get("status")})
    return result
