"""
handler.py - EventBridge-scheduled snapshot + delta detection for the
continuous code-sync engine (Gemini gap #5 / SmartShift's dual-maintenance
moat).

Trigger
-------
Wired to an EventBridge cron rule (recommended: once per business day) that
invokes this Lambda with no payload. The handler:

  1. Opens an RFC connection to the ECC source (creds in Secrets Manager).
  2. Takes a TADIR + REPOSRC snapshot of customer-namespace ABAP.
  3. Diffs against the most recent baseline (kept under /tmp + mirrored to S3
     so survives Lambda warm-restart cycles).
  4. For each ADDED / MODIFIED object, appends a remediation task to the
     queue file (S3) so the code-analyzer Lambda picks it up on its next
     batch run. DELETED objects are logged but not actioned.
  5. Emits a delta report (S3) for the cutover steering committee.

Idempotency
-----------
`plan_remediation` is append-only and dedupes by (objtype, objname) so a
re-fire on the same delta is a no-op. Snapshots are kept indefinitely so we
can re-diff against any prior baseline.

Env vars
--------
- ECC_SECRET_ID                  Secrets Manager id for the source RFC creds
- M4H_CODE_DELTA_BUCKET          S3 bucket for snapshots + queue (defaults to
                                 staging bucket)
- M4H_CODE_DELTA_PREFIX          S3 prefix (default 'code-delta')
- M4H_CODE_DELTA_DEEP_HASH       '1' to compute source SHA-256 per program
                                 (slower; one extra RFC per program)
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "utils"))

import boto3  # noqa: E402

logger = logging.getLogger("code-delta-scheduler")
logger.setLevel(logging.INFO)

S3 = boto3.client("s3")
SECRETS = boto3.client("secretsmanager")

STAGING_BUCKET = os.environ.get("M4H_CODE_DELTA_BUCKET") \
                 or os.environ.get("S3_STAGING_BUCKET") \
                 or os.environ.get("STAGING_BUCKET", "")
PREFIX = os.environ.get("M4H_CODE_DELTA_PREFIX", "code-delta")
DEEP_HASH = os.environ.get("M4H_CODE_DELTA_DEEP_HASH", "").lower() in ("1", "true", "yes")
SECRET_ID = os.environ.get("ECC_SECRET_ID", "local:ecc")


def _ecc():
    sec = json.loads(SECRETS.get_secret_value(SecretId=SECRET_ID)["SecretString"])
    from pyrfc import Connection
    return Connection(
        ashost=sec["ashost"], sysnr=sec.get("sysnr", "00"),
        client=sec["client"], user=sec["user"],
        passwd=sec.get("passwd") or sec.get("password"),
        lang=sec.get("lang", "EN"))


def _sync_baselines_from_s3(local_dir: Path, sid: str) -> None:
    """Mirror prior snapshots from S3 into local_dir so DeltaEngine can read
    the most recent baseline."""
    if not STAGING_BUCKET:
        return
    target = local_dir / sid
    target.mkdir(parents=True, exist_ok=True)
    paginator = S3.get_paginator("list_objects_v2")
    s3_prefix = f"{PREFIX}/{sid}/"
    for page in paginator.paginate(Bucket=STAGING_BUCKET, Prefix=s3_prefix):
        for obj in (page.get("Contents") or []):
            key = obj["Key"]
            name = key.rsplit("/", 1)[-1]
            if not name.endswith(".json"):
                continue
            body = S3.get_object(Bucket=STAGING_BUCKET, Key=key)["Body"].read()
            (target / name).write_bytes(body)


def _mirror_snapshot_to_s3(local_path: Path, sid: str) -> str:
    if not STAGING_BUCKET:
        return ""
    key = f"{PREFIX}/{sid}/{local_path.name}"
    S3.put_object(Bucket=STAGING_BUCKET, Key=key,
                  Body=local_path.read_bytes(),
                  ContentType="application/json")
    return f"s3://{STAGING_BUCKET}/{key}"


def _upload_queue(local_queue: Path) -> str:
    if not STAGING_BUCKET:
        return ""
    key = f"{PREFIX}/remediation-queue.jsonl"
    S3.put_object(Bucket=STAGING_BUCKET, Key=key,
                  Body=local_queue.read_bytes(),
                  ContentType="application/x-ndjson")
    return f"s3://{STAGING_BUCKET}/{key}"


def _emit_report(run_id: str, sid: str, deltas: list, tasks: list) -> str:
    payload = {
        "run_id": run_id,
        "sid": sid,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "delta_count": len(deltas),
        "tasks_enqueued": len(tasks),
        "summary_by_verdict": {
            v: sum(1 for d in deltas if d["verdict"] == v)
            for v in ("ADDED", "MODIFIED", "DELETED")
        },
        "deltas": deltas,
        "tasks": tasks,
    }
    if not STAGING_BUCKET:
        return ""
    key = f"{PREFIX}/reports/{run_id}.json"
    S3.put_object(Bucket=STAGING_BUCKET, Key=key,
                  Body=json.dumps(payload, indent=2).encode(),
                  ContentType="application/json")
    return f"s3://{STAGING_BUCKET}/{key}"


def lambda_handler(event, context):
    run_id = (event or {}).get("run_id") or f"codedelta-{int(time.time())}"
    sid = (event or {}).get("sid") or os.environ.get("M4H_ECC_SID", "ECC")

    logger.info("code-delta-scheduler: run=%s sid=%s deep_hash=%s",
                run_id, sid, DEEP_HASH)

    try:
        from code_delta import DeltaEngine, plan_remediation
    except ImportError as e:
        return {"status": "error", "reason": f"code_delta import failed: {e}"}

    try:
        conn = _ecc()
    except Exception as e:
        return {"status": "error", "run_id": run_id,
                "reason": f"ECC connect failed: {type(e).__name__}: {e}"}

    with tempfile.TemporaryDirectory() as td:
        local_dir = Path(td) / "baselines"
        _sync_baselines_from_s3(local_dir, sid)

        engine = DeltaEngine(baseline_dir=local_dir, sid=sid,
                             rfc_callable=lambda fn, kwargs: conn.call(fn, **kwargs),
                             deep_hash=DEEP_HASH)
        snap = engine.snapshot()
        snap_path = local_dir / sid / f"{snap.taken_at}.json"
        s3_snap = _mirror_snapshot_to_s3(snap_path, sid)

        baselines = engine.all_snapshots()
        if len(baselines) < 2:
            return {"status": "ok", "run_id": run_id,
                    "note": "first snapshot - no baseline to diff against",
                    "snapshot": s3_snap,
                    "object_count": snap.object_count}

        deltas = engine.detect_delta(baseline=baselines[-2], current=snap)
        queue_path = Path(td) / "remediation-queue.jsonl"
        # Bring down the prior queue so plan_remediation's idempotency works
        if STAGING_BUCKET:
            try:
                prior = S3.get_object(
                    Bucket=STAGING_BUCKET,
                    Key=f"{PREFIX}/remediation-queue.jsonl")["Body"].read()
                queue_path.write_bytes(prior)
            except S3.exceptions.NoSuchKey:
                pass
            except Exception:
                pass
        tasks = plan_remediation(deltas, queue_path)
        s3_queue = _upload_queue(queue_path) if tasks else None

        delta_dicts = [d.to_dict() for d in deltas]
        task_dicts = [t.to_dict() for t in tasks]
        report_url = _emit_report(run_id, sid, delta_dicts, task_dicts)

        return {
            "status": "ok",
            "run_id": run_id,
            "sid": sid,
            "snapshot": s3_snap,
            "baseline_count": len(baselines),
            "deltas": len(delta_dicts),
            "tasks_enqueued": len(task_dicts),
            "queue": s3_queue,
            "report": report_url,
            "verdict_breakdown": {
                v: sum(1 for d in deltas if d.verdict == v)
                for v in ("ADDED", "MODIFIED", "DELETED")
            },
        }
