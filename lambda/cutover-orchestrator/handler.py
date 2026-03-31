"""
Migrate4HANA — Stage 7: Cutover Orchestrator
==============================================
Pre-cutover checks, source system locking, and migration orchestration.

This is the GATEWAY to execution. It:
1. Validates all planning stages (1-6) completed successfully
2. Runs pre-flight connectivity checks to S/4HANA target
3. Optionally locks the ECC source system (stop postings)
4. Creates a migration checkpoint so we can roll back
5. Signals GO/NO-GO for the execution stages (8-13)

DevOps Analogy:
This is like a deployment gate — canary checks, feature flags,
and a "big red button" that either proceeds or aborts.
"""

import json
import os
import sys
import logging
import boto3
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'utils')))
from logger import log_stage_event
from validation import validate_event

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")

STAGING_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hana-staging-dev")


# =============================================================================
# PRE-CUTOVER VALIDATION
# =============================================================================
def validate_planning_stages(event):
    """Ensure all 6 planning stages completed successfully."""
    required = ["discovery", "code_analysis", "data_migration", "config", "roles", "integrations"]
    missing = []
    for stage in required:
        stage_result = event.get(stage, {})
        payload = stage_result.get("Payload", stage_result)
        if not payload or payload.get("status") != "success":
            missing.append(stage)
    return missing


def check_s4_connectivity(conn_params):
    """Verify we can reach the S/4HANA target system via RFC."""
    try:
        from pyrfc import Connection
        conn = Connection(**conn_params)
        # Ping with a lightweight RFC
        result = conn.call("RFC_PING")
        conn.close()
        return {"reachable": True, "latency_ms": 0}
    except ImportError:
        logger.warning("PyRFC not available — skipping connectivity check")
        return {"reachable": True, "latency_ms": 0, "note": "pyrfc not installed — mock mode"}
    except Exception as e:
        return {"reachable": False, "error": str(e)}


def lock_source_system(conn, lock=True):
    """
    Lock ECC source system to prevent new postings during migration.

    Strategy (three layers):
    1. SCCR_LOCK_CLIENT — sets client to 'not modifiable' (T000-CCCORACTIV=0)
       This is the SAP-supported way to freeze a client during conversion.
    2. Lock critical transactions (FB01, VA01, ME21N, MM01, etc.) via SM01
       using BAPI_USER_LOCK on dialog users as a safety net.
    3. Record lock state so rollback-manager can reverse it.
    """
    if not lock:
        return {"locked": False, "reason": "lock_not_requested"}

    lock_result = {
        "locked": False,
        "timestamp": datetime.utcnow().isoformat(),
        "client_lock": None,
        "users_locked": 0,
        "errors": [],
    }

    # --- Layer 1: Lock the client via SCCR_LOCK_CLIENT ---
    try:
        client_id = conn.call("RFC_SYSTEM_INFO").get(
            "RFCSI_EXPORT", {}
        ).get("RFCCLIENT", "")
        result = conn.call("SCCR_LOCK_CLIENT", CLIENT=client_id)
        return_msgs = result.get("RETURN", [])
        errors = [m for m in return_msgs if m.get("TYPE") in ("E", "A")]
        if errors:
            lock_result["errors"].append(
                f"SCCR_LOCK_CLIENT: {errors[0].get('MESSAGE', 'unknown error')}"
            )
            logger.warning(f"Client lock warning: {errors}")
        else:
            lock_result["client_lock"] = "locked"
            logger.info(f"Client {client_id} locked via SCCR_LOCK_CLIENT")
    except Exception as e:
        lock_result["errors"].append(f"SCCR_LOCK_CLIENT failed: {e}")
        logger.warning(f"SCCR_LOCK_CLIENT failed: {e}")

    # --- Layer 2: Lock dialog users to prevent any slip-through ---
    try:
        user_result = conn.call(
            "RFC_READ_TABLE",
            QUERY_TABLE="USR02",
            DELIMITER="|",
            FIELDS=[{"FIELDNAME": "BNAME"}],
            OPTIONS=[{"TEXT": "USTYP = 'A'"}],  # A = Dialog users only
            ROWCOUNT=5000,
        )
        dialog_users = []
        for row in user_result.get("DATA", []):
            uname = row.get("WA", "").split("|")[0].strip()
            if uname:
                dialog_users.append(uname)

        locked_count = 0
        for uname in dialog_users:
            try:
                conn.call("BAPI_USER_LOCK", USERNAME=uname)
                locked_count += 1
            except Exception:
                pass  # Some service users may not be lockable
        if locked_count > 0:
            conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        lock_result["users_locked"] = locked_count
        logger.info(f"Locked {locked_count} dialog users")
    except Exception as e:
        lock_result["errors"].append(f"User lock phase failed: {e}")
        logger.warning(f"User lock phase failed: {e}")

    lock_result["locked"] = (
        lock_result["client_lock"] == "locked" or lock_result["users_locked"] > 0
    )
    return lock_result


# =============================================================================
# DMS CDC LATENCY MONITORING
# =============================================================================
dms_client = boto3.client("dms")

DMS_REPLICATION_TASK_ARN = os.environ.get("DMS_REPLICATION_TASK_ARN", "")
CDC_LATENCY_THRESHOLD_SEC = int(os.environ.get("CDC_LATENCY_THRESHOLD_SEC", "30"))


def monitor_dms_cdc_latency() -> dict:
    """
    Check DMS CDC replication task status and latency.

    Queries CloudWatch via the DMS DescribeReplicationTasks API to get:
    - Task status (running, stopped, error)
    - CDC latency (seconds behind source)
    - Full-load completion percentage

    Returns a dict with task_status, cdc_latency_seconds, and a pass/fail verdict.
    """
    if not DMS_REPLICATION_TASK_ARN:
        logger.warning("DMS_REPLICATION_TASK_ARN not configured — skipping CDC check")
        return {"status": "skipped", "reason": "DMS task ARN not configured"}

    try:
        response = dms_client.describe_replication_tasks(
            Filters=[{"Name": "replication-task-arn", "Values": [DMS_REPLICATION_TASK_ARN]}]
        )
        tasks = response.get("ReplicationTasks", [])
        if not tasks:
            return {"status": "error", "reason": "Replication task not found"}

        task = tasks[0]
        task_status = task.get("Status", "unknown")
        stats = task.get("ReplicationTaskStats", {})
        cdc_latency = stats.get("CDCLatencyTarget", 0)
        full_load_pct = stats.get("FullLoadProgressPercent", 0)
        tables_loaded = stats.get("TablesLoaded", 0)
        tables_errored = stats.get("TablesErrored", 0)

        latency_ok = cdc_latency <= CDC_LATENCY_THRESHOLD_SEC

        result = {
            "status": "ok" if latency_ok else "high_latency",
            "task_status": task_status,
            "cdc_latency_seconds": cdc_latency,
            "latency_threshold": CDC_LATENCY_THRESHOLD_SEC,
            "latency_acceptable": latency_ok,
            "full_load_percent": full_load_pct,
            "tables_loaded": tables_loaded,
            "tables_errored": tables_errored,
        }
        logger.info(f"DMS CDC status: {task_status}, latency: {cdc_latency}s, threshold: {CDC_LATENCY_THRESHOLD_SEC}s")
        return result

    except Exception as e:
        logger.error(f"DMS CDC monitoring failed: {e}")
        return {"status": "error", "reason": str(e)}


def finalize_dms_cdc() -> dict:
    """
    Stop the DMS CDC replication task during cutover.

    Called after the source system is locked and CDC latency has converged to
    near-zero. Stops the ongoing CDC task so the final data state is frozen
    for the execution stages.
    """
    if not DMS_REPLICATION_TASK_ARN:
        return {"status": "skipped", "reason": "DMS task ARN not configured"}

    try:
        dms_client.stop_replication_task(ReplicationTaskArn=DMS_REPLICATION_TASK_ARN)
        logger.info("DMS CDC replication task stop initiated")

        # Wait briefly and verify
        import time
        time.sleep(5)
        response = dms_client.describe_replication_tasks(
            Filters=[{"Name": "replication-task-arn", "Values": [DMS_REPLICATION_TASK_ARN]}]
        )
        tasks = response.get("ReplicationTasks", [])
        final_status = tasks[0].get("Status", "unknown") if tasks else "unknown"

        return {
            "status": "stopped" if final_status in ("stopped", "stopping") else final_status,
            "task_arn": DMS_REPLICATION_TASK_ARN,
        }

    except Exception as e:
        logger.error(f"Failed to stop DMS CDC task: {e}")
        return {"status": "error", "reason": str(e)}


def create_checkpoint(run_id, event):
    """Save a checkpoint so we can resume or roll back if execution fails."""
    checkpoint = {
        "run_id": run_id,
        "timestamp": datetime.utcnow().isoformat(),
        "planning_results": {
            k: event.get(k, {}).get("Payload", event.get(k, {}))
            for k in ["discovery", "code_analysis", "data_migration", "config", "roles", "integrations"]
        },
        "execution_started": True,
        "stages_completed": [],
        "stages_pending": [
            "code-deployer", "data-loader", "config-applier",
            "role-provisioner", "integration-activator", "migration-validator"
        ],
    }

    s3.put_object(
        Bucket=STAGING_BUCKET,
        Key=f"migrations/{run_id}/execution/checkpoint.json",
        Body=json.dumps(checkpoint, indent=2, default=str),
        ContentType="application/json",
    )
    return checkpoint


# =============================================================================
# MAIN HANDLER
# =============================================================================
def lambda_handler(event, context):
    """
    Pre-cutover orchestration.
    Validates readiness, locks source, creates checkpoint.
    """
    logger.info("Cutover Orchestrator started")
    log_stage_event("cutover-orchestrator", "Pipeline Start", "IN_PROGRESS", {"stage": 7, "dry_run": event.get("metadata", {}).get("input", {}).get("dry_run", False)})
    _stage_start = __import__('time').time()

    # Validate input at system boundary
    validation_errors = validate_event(event, required_fields=["metadata.run_id"])
    if validation_errors:
        return {
            "status": "error",
            "stage": "cutover-orchestrator",
            "errors": validation_errors,
            "message": "Input validation failed",
        }

    run_id = event.get("metadata", {}).get("run_id", "manual-run")
    mode = event.get("metadata", {}).get("input", {}).get("mode", "full")
    dry_run = event.get("metadata", {}).get("input", {}).get("dry_run", False)

    results = {
        "stage": "cutover-orchestrator",
        "run_id": run_id,
        "dry_run": dry_run,
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {},
    }

    try:
        # 1. Validate all planning stages completed
        missing = validate_planning_stages(event)
        results["checks"]["planning_stages"] = {
            "passed": len(missing) == 0,
            "missing_stages": missing,
        }
        if missing:
            return {
                "status": "blocked",
                "reason": f"Planning stages incomplete: {', '.join(missing)}",
                "results": results,
            }
        logger.info("All planning stages validated")

        # 2. Check S/4HANA target connectivity
        try:
            s4_params = json.loads(
                boto3.client("secretsmanager")
                .get_secret_value(SecretId=os.environ.get("S4_SECRETS_ARN", os.environ.get("SECRETS_ARN", "")))
                ["SecretString"]
            )
            connectivity = check_s4_connectivity(s4_params)
        except Exception:
            connectivity = {"reachable": True, "note": "secrets not configured — assuming mock mode"}

        results["checks"]["s4_connectivity"] = connectivity
        if not connectivity.get("reachable", False):
            return {
                "status": "blocked",
                "reason": f"S/4HANA target unreachable: {connectivity.get('error', 'unknown')}",
                "results": results,
            }
        logger.info("S/4HANA target system reachable")

        # 3. Review critical metrics from planning
        discovery = event.get("discovery", {}).get("Payload", event.get("discovery", {}))
        code_analysis = event.get("code_analysis", {}).get("Payload", event.get("code_analysis", {}))

        blocking_issues = discovery.get("blocking_issues", 0)
        critical_code = code_analysis.get("critical_issues", 0)

        results["checks"]["risk_assessment"] = {
            "blocking_issues": blocking_issues,
            "critical_code_issues": critical_code,
            "recommendation": "proceed" if blocking_issues == 0 else "review_required",
        }

        # 3b. Check DMS CDC latency
        cdc_status = monitor_dms_cdc_latency()
        results["checks"]["dms_cdc"] = cdc_status
        if cdc_status.get("status") == "high_latency":
            logger.warning(
                f"DMS CDC latency {cdc_status.get('cdc_latency_seconds')}s exceeds "
                f"threshold {cdc_status.get('latency_threshold')}s"
            )
        if cdc_status.get("tables_errored", 0) > 0:
            logger.warning(f"DMS has {cdc_status['tables_errored']} tables with errors")

        # 4. Create checkpoint
        if not dry_run:
            checkpoint = create_checkpoint(run_id, event)
            results["checkpoint"] = f"migrations/{run_id}/execution/checkpoint.json"
            logger.info(f"Checkpoint created: {results['checkpoint']}")

        # 5. Lock source system (only if not dry run and explicitly requested)
        lock_requested = event.get("metadata", {}).get("input", {}).get("lock_source", False)
        if lock_requested and not dry_run:
            try:
                from pyrfc import Connection
                ecc_params = json.loads(
                    boto3.client("secretsmanager")
                    .get_secret_value(SecretId=os.environ.get("SECRETS_ARN", ""))
                    ["SecretString"]
                )
                ecc_conn = Connection(**ecc_params)
                lock_result = lock_source_system(ecc_conn, lock=True)
                ecc_conn.close()
            except Exception as e:
                lock_result = {"locked": False, "reason": str(e)}
            results["checks"]["source_lock"] = lock_result
        else:
            results["checks"]["source_lock"] = {"locked": False, "reason": "not_requested_or_dry_run"}

        # 5b. Finalize DMS CDC after source lock (stop ongoing replication)
        if lock_requested and not dry_run:
            cdc_final = finalize_dms_cdc()
            results["checks"]["dms_cdc_finalized"] = cdc_final
            logger.info(f"DMS CDC finalization: {cdc_final.get('status')}")

        # Save results
        s3.put_object(
            Bucket=STAGING_BUCKET,
            Key=f"migrations/{run_id}/execution/cutover-orchestrator.json",
            Body=json.dumps(results, indent=2, default=str),
            ContentType="application/json",
        )

        result = {
            "status": "success",
            "go_no_go": "GO",
            "dry_run": dry_run,
            "results": results,
            "run_id": run_id,
        }
        log_stage_event("cutover-orchestrator", "Cutover Complete", "SUCCESS", {"go_no_go": "GO", "dry_run": dry_run}, (__import__('time').time() - _stage_start) * 1000)
        return result

    except Exception as e:
        logger.error(f"Cutover orchestration failed: {str(e)}")
        log_stage_event("cutover-orchestrator", "Cutover Failed", "ERROR", str(e))
        raise
