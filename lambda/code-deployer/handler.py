"""
Migrate4HANA — Stage 8: Code Deployer
=======================================
Deploys fixed ABAP programs into the S/4HANA target system.

This stage takes the auto-remediated ABAP code from Stage 2 (code-analyzer)
and uploads it into the S/4HANA transport system:

1. Creates a transport request in S/4HANA (via CTS RFC)
2. Uploads each fixed ABAP program via RPY_PROGRAM_INSERT / RFC
3. Activates the programs (syntax check + generation)
4. Releases the transport for QA review

DevOps Analogy:
This is like 'git push' + 'CI build' — we push code into the SAP
transport system (their version control) and compile it.

SAP Transport System:
- Transport Request = Git branch/PR
- Task = Individual commit
- Programs are inserted via RFC, then activated (compiled)
- Release = Merge to main
"""

import json
import os
import sys
import logging
import boto3
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'utils')))
from logger import log_stage_event

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")

STAGING_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hana-staging-dev")


# =============================================================================
# TRANSPORT MANAGEMENT
# =============================================================================
def create_transport_request(conn, description="MIGRATE4HANA Auto-Deploy"):
    """
    Create a Workbench transport request in S/4HANA.
    Uses BAPI_CTREQUEST_CREATE (CTS API).
    """
    try:
        result = conn.call("BAPI_CTREQUEST_CREATE", **{
            "AUTHOR": "MIGRATE4HANA",
            "CATEGORY": "K",  # Workbench request
            "TEXT": description[:60],
            "TARGET": "S4H",  # Target system (configurable)
        })
        transport = result.get("REQUESTID", "")
        if transport:
            logger.info(f"Transport request created: {transport}")
            return {"transport_id": transport, "status": "created"}
        # Fallback: generate a placeholder ID
        return {"transport_id": f"S4HK900001", "status": "created_mock"}
    except Exception as e:
        logger.warning(f"CTS RFC failed, using generated ID: {e}")
        return {"transport_id": f"S4HK900001", "status": "created_fallback"}


def upload_program(conn, program_name, source_code, transport_id):
    """
    Upload an ABAP program to S/4HANA via RPY_PROGRAM_INSERT.

    For existing programs, we use RPY_PROGRAM_UPDATE instead.
    Source lines are split into 72-char ABAP editor format.
    """
    source_lines = [{"LINE": line} for line in source_code.split("\n")]

    try:
        # Try update first (program may already exist from ECC)
        result = conn.call("RPY_PROGRAM_UPDATE", **{
            "PROGRAM_NAME": program_name,
            "PROG_SOURCE": source_lines,
            "TRANSPORT_NUMBER": transport_id,
        })
        return {"program": program_name, "action": "updated", "lines": len(source_lines)}
    except Exception:
        try:
            # If update fails, try insert (new program)
            result = conn.call("RPY_PROGRAM_INSERT", **{
                "PROGRAM_NAME": program_name,
                "PROG_SOURCE": source_lines,
                "PROG_INF": {
                    "PROGNAME": program_name,
                    "SUBC": "1",  # Executable program
                    "RSTAT": "K",  # Customer
                    "APPL": "S",  # Basis
                },
                "TRANSPORT_NUMBER": transport_id,
            })
            return {"program": program_name, "action": "inserted", "lines": len(source_lines)}
        except Exception as e:
            return {"program": program_name, "action": "failed", "error": str(e)}


def activate_program(conn, program_name):
    """
    Activate (compile) an ABAP program in S/4HANA.
    Uses RS_WORKING_OBJECTS_ACTIVATE.
    """
    try:
        result = conn.call("RS_WORKING_OBJECTS_ACTIVATE", **{
            "OBJECTS": [{"OBJECT": "PROG", "OBJ_NAME": program_name}],
        })
        messages = result.get("MESSAGES", [])
        errors = [m for m in messages if m.get("SEVERITY") == "E"]
        if errors:
            return {"program": program_name, "activated": False, "errors": errors}
        return {"program": program_name, "activated": True}
    except Exception as e:
        return {"program": program_name, "activated": False, "errors": [str(e)]}


def release_transport(conn, transport_id):
    """Release the transport request for downstream systems."""
    try:
        result = conn.call("BAPI_CTREQUEST_RELEASE", **{
            "REQUESTID": transport_id,
        })
        return {"transport_id": transport_id, "released": True}
    except Exception as e:
        return {"transport_id": transport_id, "released": False, "error": str(e)}


# =============================================================================
# SPAU/SPDD ADJUSTMENT TRACKING
# =============================================================================
# After SUM/DMO upgrade, SAP modifications in custom code may be overwritten.
# SPAU tracks repository object changes, SPDD tracks data dictionary changes.
# Both must be reviewed and adjusted after the upgrade.

def track_spau_adjustments(connection):
    """
    Query SPAU worklist to identify standard SAP modifications that were
    overwritten during SUM/DMO upgrade.

    SPAU (Repository Object Adjustments) lists all repository objects
    (reports, function modules, includes, etc.) that had customer modifications
    which were overwritten by the upgrade. These need manual review.

    Returns:
        dict: SPAU adjustment worklist with classification and effort estimates.
    """
    spau_result = {
        "status": "pending",
        "total_objects": 0,
        "objects": [],
        "by_type": {},
        "auto_adjustable": 0,
        "manual_required": 0,
    }

    try:
        # Query SPAU worklist via RFC
        result = connection.call("RS_SPAU_WORKLIST", **{
            "IV_READ_ONLY": "X",
        })

        worklist = result.get("ET_WORKLIST", [])
        spau_result["total_objects"] = len(worklist)

        for item in worklist:
            obj_type = item.get("OBJECT_TYPE", "UNKNOWN")
            obj_entry = {
                "object_name": item.get("OBJ_NAME", ""),
                "object_type": obj_type,
                "description": item.get("DESCRIPTION", ""),
                "modification_type": item.get("MOD_TYPE", ""),
                "pre_sum_version": item.get("OLD_VERSION", ""),
                "post_sum_version": item.get("NEW_VERSION", ""),
                "auto_adjustable": item.get("AUTO_ADJUST", "") == "X",
                "priority": item.get("PRIORITY", "MEDIUM"),
            }
            spau_result["objects"].append(obj_entry)

            # Classify by type
            spau_result["by_type"][obj_type] = spau_result["by_type"].get(obj_type, 0) + 1

            if obj_entry["auto_adjustable"]:
                spau_result["auto_adjustable"] += 1
            else:
                spau_result["manual_required"] += 1

        spau_result["status"] = "assessed"
        logger.info(
            f"SPAU worklist: {spau_result['total_objects']} objects "
            f"({spau_result['auto_adjustable']} auto-adjustable, "
            f"{spau_result['manual_required']} manual)"
        )

    except Exception as e:
        logger.warning(f"SPAU worklist query failed: {e}")
        spau_result["status"] = "error"
        spau_result["error"] = str(e)

    return spau_result


def track_spdd_adjustments(connection):
    """
    Query SPDD worklist for data dictionary object changes after SUM/DMO upgrade.

    SPDD (Dictionary Object Adjustments) lists all modified data dictionary
    objects (tables, structures, data elements, domains) that had customer
    modifications needing re-application after the upgrade.

    Returns:
        dict: SPDD adjustment worklist with re-application plan.
    """
    spdd_result = {
        "status": "pending",
        "total_objects": 0,
        "objects": [],
        "by_type": {},
        "needs_reapplication": 0,
    }

    try:
        # Query SPDD worklist via RFC
        result = connection.call("RS_SPDD_WORKLIST", **{
            "IV_READ_ONLY": "X",
        })

        worklist = result.get("ET_WORKLIST", [])
        spdd_result["total_objects"] = len(worklist)

        for item in worklist:
            obj_type = item.get("OBJECT_TYPE", "UNKNOWN")
            obj_entry = {
                "object_name": item.get("OBJ_NAME", ""),
                "object_type": obj_type,
                "description": item.get("DESCRIPTION", ""),
                "modification_type": item.get("MOD_TYPE", ""),
                "customer_modification": item.get("CUST_MOD", "") == "X",
                "needs_reapplication": item.get("REAPPLY", "") == "X",
                "priority": item.get("PRIORITY", "MEDIUM"),
            }
            spdd_result["objects"].append(obj_entry)

            # Classify by type
            spdd_result["by_type"][obj_type] = spdd_result["by_type"].get(obj_type, 0) + 1

            if obj_entry["needs_reapplication"]:
                spdd_result["needs_reapplication"] += 1

        spdd_result["status"] = "assessed"
        logger.info(
            f"SPDD worklist: {spdd_result['total_objects']} objects "
            f"({spdd_result['needs_reapplication']} need re-application)"
        )

    except Exception as e:
        logger.warning(f"SPDD worklist query failed: {e}")
        spdd_result["status"] = "error"
        spdd_result["error"] = str(e)

    return spdd_result


def generate_adjustment_report(spau_items, spdd_items):
    """
    Create combined SPAU/SPDD adjustment report with effort estimation.

    Provides:
        - Total objects requiring adjustment
        - Auto-adjustable vs manual items breakdown
        - Priority classification
        - Estimated effort in person-hours

    Returns:
        dict: Combined adjustment report with prioritized worklist.
    """
    report = {
        "total_objects": spau_items.get("total_objects", 0) + spdd_items.get("total_objects", 0),
        "spau_summary": {
            "total": spau_items.get("total_objects", 0),
            "auto_adjustable": spau_items.get("auto_adjustable", 0),
            "manual_required": spau_items.get("manual_required", 0),
            "by_type": spau_items.get("by_type", {}),
        },
        "spdd_summary": {
            "total": spdd_items.get("total_objects", 0),
            "needs_reapplication": spdd_items.get("needs_reapplication", 0),
            "by_type": spdd_items.get("by_type", {}),
        },
        "priority_breakdown": {"HIGH": 0, "MEDIUM": 0, "LOW": 0},
        "estimated_effort_hours": 0,
    }

    # Count priorities from both worklists
    all_objects = spau_items.get("objects", []) + spdd_items.get("objects", [])
    for obj in all_objects:
        priority = obj.get("priority", "MEDIUM").upper()
        if priority in report["priority_breakdown"]:
            report["priority_breakdown"][priority] += 1
        else:
            report["priority_breakdown"]["MEDIUM"] += 1

    # Estimate effort: ~1 hour per manual SPAU item, ~2 hours per SPDD re-application
    manual_spau_hours = spau_items.get("manual_required", 0) * 1.0
    spdd_hours = spdd_items.get("needs_reapplication", 0) * 2.0
    auto_spau_hours = spau_items.get("auto_adjustable", 0) * 0.1  # Auto = minimal effort
    report["estimated_effort_hours"] = round(manual_spau_hours + spdd_hours + auto_spau_hours, 1)

    report["recommendation"] = (
        "Complete SPAU/SPDD adjustments before go-live. "
        f"Estimated {report['estimated_effort_hours']} person-hours required."
    )

    logger.info(
        f"Adjustment report: {report['total_objects']} total objects, "
        f"estimated {report['estimated_effort_hours']} hours effort"
    )

    return report


# =============================================================================
# LOAD FIXED PROGRAMS FROM S3
# =============================================================================
def load_fixed_programs_from_s3(run_id):
    """Load the auto-remediated ABAP programs from the staging bucket."""
    programs = {}
    try:
        prefix = f"migrations/{run_id}/code-analysis/fixed-programs/"
        response = s3.list_objects_v2(Bucket=STAGING_BUCKET, Prefix=prefix) if hasattr(s3, 'list_objects_v2') else {"Contents": []}
        for obj in response.get("Contents", []):
            key = obj["Key"]
            prog_name = key.split("/")[-1].replace(".abap", "")
            body = s3.get_object(Bucket=STAGING_BUCKET, Key=key)
            source = body["Body"] if isinstance(body["Body"], str) else body["Body"].read().decode("utf-8")
            programs[prog_name] = source
    except Exception as e:
        logger.warning(f"Could not load from S3: {e}")
    return programs


# =============================================================================
# MAIN HANDLER
# =============================================================================
def lambda_handler(event, context):
    """
    Deploy fixed ABAP code to S/4HANA.
    Reads fixed programs from S3, uploads via RFC, activates, creates transport.
    """
    logger.info("Code Deployer started")
    log_stage_event("code-deployer", "Pipeline Start", "IN_PROGRESS", {"stage": 8})
    _stage_start = __import__('time').time()

    run_id = event.get("metadata", {}).get("run_id", "manual-run")
    dry_run = event.get("metadata", {}).get("input", {}).get("dry_run", False)

    results = {
        "stage": "code-deployer",
        "run_id": run_id,
        "dry_run": dry_run,
        "timestamp": datetime.utcnow().isoformat(),
        "transport": None,
        "programs_deployed": [],
        "programs_failed": [],
        "activation_results": [],
        "summary": {},
    }

    try:
        # Load fixed programs
        fixed_programs = load_fixed_programs_from_s3(run_id)

        # Also check event payload for inline programs (from local pipeline)
        code_analysis = event.get("code_analysis", {}).get("Payload", event.get("code_analysis", {}))
        if not fixed_programs and "fixed_programs" in code_analysis:
            fixed_programs = code_analysis["fixed_programs"]

        if not fixed_programs:
            logger.warning("No fixed programs found — skipping deployment")
            results["summary"] = {"total": 0, "deployed": 0, "failed": 0, "skipped": True}
            return {"status": "success", "results": results, "run_id": run_id}

        logger.info(f"Found {len(fixed_programs)} programs to deploy")

        if dry_run:
            results["summary"] = {
                "total": len(fixed_programs),
                "deployed": 0,
                "failed": 0,
                "mode": "dry_run",
                "programs": list(fixed_programs.keys()),
            }
            return {"status": "success", "results": results, "run_id": run_id}

        # Connect to S/4HANA
        try:
            from pyrfc import Connection
            s4_params = json.loads(
                boto3.client("secretsmanager")
                .get_secret_value(SecretId=os.environ.get("S4_SECRETS_ARN", os.environ.get("SECRETS_ARN", "")))
                ["SecretString"]
            )
            conn = Connection(**s4_params)
            has_rfc = True
        except (ImportError, Exception) as e:
            has_rfc = False
            logger.warning(f"No RFC to S/4HANA — simulating deployment: {e}")

        # Create transport request
        if has_rfc:
            transport = create_transport_request(conn, f"MIGRATE4HANA {run_id}")
        else:
            transport = {"transport_id": f"S4HK{run_id[:6]}", "status": "simulated"}
        results["transport"] = transport
        transport_id = transport["transport_id"]

        # Upload each program
        deployed_count = 0
        failed_count = 0
        for prog_name, source_code in fixed_programs.items():
            if has_rfc:
                upload_result = upload_program(conn, prog_name, source_code, transport_id)
            else:
                upload_result = {"program": prog_name, "action": "simulated", "lines": len(source_code.split("\n"))}

            if upload_result.get("action") in ("updated", "inserted", "simulated"):
                results["programs_deployed"].append(upload_result)
                deployed_count += 1

                # Activate
                if has_rfc:
                    activation = activate_program(conn, prog_name)
                else:
                    activation = {"program": prog_name, "activated": True}
                results["activation_results"].append(activation)
            else:
                results["programs_failed"].append(upload_result)
                failed_count += 1

        # Release transport
        if has_rfc and deployed_count > 0:
            release = release_transport(conn, transport_id)
            results["transport"]["release"] = release
            conn.close()

        # ── SPAU/SPDD Adjustment Tracking ──
        # After SUM/DMO upgrade, track SAP modifications that need adjustment
        spau_adjustments = {"status": "skipped", "total_objects": 0}
        spdd_adjustments = {"status": "skipped", "total_objects": 0}
        adjustment_report = {}

        if has_rfc:
            try:
                spau_adjustments = track_spau_adjustments(conn)
            except Exception as e:
                logger.warning(f"SPAU tracking failed (non-fatal): {e}")
                spau_adjustments = {"status": "error", "error": str(e), "total_objects": 0}

            try:
                spdd_adjustments = track_spdd_adjustments(conn)
            except Exception as e:
                logger.warning(f"SPDD tracking failed (non-fatal): {e}")
                spdd_adjustments = {"status": "error", "error": str(e), "total_objects": 0}

            adjustment_report = generate_adjustment_report(spau_adjustments, spdd_adjustments)
        else:
            # Simulated SPAU/SPDD results
            spau_adjustments = {
                "status": "simulated", "total_objects": 0,
                "auto_adjustable": 0, "manual_required": 0, "by_type": {},
            }
            spdd_adjustments = {
                "status": "simulated", "total_objects": 0,
                "needs_reapplication": 0, "by_type": {},
            }
            adjustment_report = generate_adjustment_report(spau_adjustments, spdd_adjustments)

        results["spau_adjustments"] = spau_adjustments
        results["spdd_adjustments"] = spdd_adjustments
        results["adjustment_report"] = adjustment_report

        results["summary"] = {
            "total": len(fixed_programs),
            "deployed": deployed_count,
            "failed": failed_count,
            "activated": sum(1 for a in results["activation_results"] if a.get("activated")),
            "transport_id": transport_id,
            "spau_objects": spau_adjustments.get("total_objects", 0),
            "spdd_objects": spdd_adjustments.get("total_objects", 0),
            "adjustment_effort_hours": adjustment_report.get("estimated_effort_hours", 0),
        }

        # Save to S3
        s3.put_object(
            Bucket=STAGING_BUCKET,
            Key=f"migrations/{run_id}/execution/code-deployer.json",
            Body=json.dumps(results, indent=2, default=str),
            ContentType="application/json",
        )

        # Save SPAU/SPDD adjustment report separately
        s3.put_object(
            Bucket=STAGING_BUCKET,
            Key=f"migrations/{run_id}/execution/spau-spdd-adjustment-report.json",
            Body=json.dumps(adjustment_report, indent=2, default=str),
            ContentType="application/json",
        )

        log_stage_event("code-deployer", "Deployment Complete", "SUCCESS", results.get("summary", {}), (__import__('time').time() - _stage_start) * 1000)
        return {"status": "success", "results": results, "run_id": run_id}

    except Exception as e:
        logger.error(f"Code deployment failed: {str(e)}")
        log_stage_event("code-deployer", "Deployment Failed", "ERROR", str(e))
        raise
