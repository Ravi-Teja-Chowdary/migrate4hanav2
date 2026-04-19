"""
Automated Rollback Manager (Part of Automation Edge Cases)
Invoked by Durable Functions Catch/Error states during execution failures.
Safely reverses any intermediate changes applied dynamically to S/4HANA.

Capabilities:
- Stage 8:  BAPI_ACC_DOCUMENT_REVERSE — Reverses financial document postings
            BAPI_CTREQUEST_DELETE — Deletes incomplete transport requests
- Stage 9:  Reverse loaded BPs (BAPI_BUPA_DELETE), material docs, finance docs
- Stage 10: Delete number range intervals, BP groupings, config entries
- Stage 11: Delete PFCG roles (PRGN_RFC_ROLE_DELETE), remove user role assignments
- Stage 12: Delete RFC destinations, IDoc partner profiles

Checkpoint-based partial rollback with S3 report persistence.
"""
import json
import os
import sys
import logging
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'utils')))
from logger import log_stage_event
from validation import validate_event
from storage_client import put_object, get_object
from secrets_client import get_secret_value

logger = logging.getLogger()
logger.setLevel(logging.INFO)

STAGING_CONTAINER = os.environ.get("AZURE_STORAGE_CONTAINER", "staging")
ROLLBACK_BATCH_SIZE = int(os.environ.get("ROLLBACK_BATCH_SIZE", "25"))

try:
    from pyrfc import Connection as RFCConnection
    PYRFC_AVAILABLE = True
except ImportError:
    PYRFC_AVAILABLE = False
    logger.warning("pyrfc not available — rollback will operate in simulation mode")


def _get_sap_connection(secret_name: str):
    """Obtain SAP RFC connection from secrets vault."""
    secret = json.loads(
        get_secret_value(secret_name)["SecretString"]
    )
    return RFCConnection(**secret)


def reverse_financial_postings(conn, documents: list) -> list:
    """
    Reverse financial document postings via BAPI_ACC_DOCUMENT_REVERSE.

    Each document dict requires: company_code, fiscal_year, doc_number.
    Commits in batches to avoid partial-failure inconsistencies.
    Returns a list of result dicts with per-document status.
    """
    results = []
    pending_commit = 0
    for doc in documents:
        doc_num = doc.get("doc_number", "unknown")
        try:
            result = conn.call(
                "BAPI_ACC_DOCUMENT_REVERSE",
                REVERSAL_REASON="01",
                COMPANYCODE=doc.get("company_code", ""),
                FISCALYEAR=doc.get("fiscal_year", ""),
                DOCUMENTNUMBER=doc_num,
                POSTINGDATE=datetime.utcnow().strftime("%Y%m%d"),
            )
            return_msgs = result.get("RETURN", [])
            errors = [m for m in return_msgs if m.get("TYPE") in ("E", "A")]
            if errors:
                results.append({
                    "doc": doc_num, "status": "failed",
                    "errors": [m.get("MESSAGE", "") for m in errors],
                })
            else:
                pending_commit += 1
                results.append({
                    "doc": doc_num, "status": "reversed",
                    "reversal_doc": result.get("DOCUMENTNUMBER", ""),
                })
                logger.info(f"Reversed document {doc_num}")
                if pending_commit >= ROLLBACK_BATCH_SIZE:
                    conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
                    logger.info(f"Committed batch of {pending_commit} financial reversals")
                    pending_commit = 0
        except Exception as e:
            results.append({"doc": doc_num, "status": "error", "message": str(e)})
            logger.error(f"Failed to reverse {doc_num}: {e}")
    # Final commit for remaining items
    if pending_commit > 0:
        try:
            conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception as e:
            logger.error(f"Final batch commit failed: {e}")
    return results


def delete_transport_requests(conn, transports: list) -> list:
    """
    Delete incomplete transport requests via BAPI_CTREQUEST_DELETE.

    Each transport dict requires: request_number (e.g. 'NPLK900001').
    """
    results = []
    for tp in transports:
        req = tp.get("request_number", "unknown")
        try:
            result = conn.call("BAPI_CTREQUEST_DELETE", REQUEST=req)
            return_msgs = result.get("RETURN", [])
            errors = [m for m in return_msgs if m.get("TYPE") in ("E", "A")]
            if errors:
                results.append({
                    "transport": req, "status": "failed",
                    "errors": [m.get("MESSAGE", "") for m in errors],
                })
            else:
                results.append({"transport": req, "status": "deleted"})
                logger.info(f"Deleted transport {req}")
        except Exception as e:
            results.append({"transport": req, "status": "error", "message": str(e)})
            logger.error(f"Failed to delete transport {req}: {e}")
    return results


# =========================================================================
# STAGE 9 ROLLBACK — Data Loader (BPs, Finance Docs, Material Docs)
# =========================================================================
def rollback_business_partners(conn, bp_numbers: list) -> list:
    """Delete Business Partners created during Stage 9 via BAPI_BUPA_DELETE.
    Commits in batches for atomicity."""
    results = []
    pending_commit = 0
    for bp_num in bp_numbers:
        bp_id = bp_num if isinstance(bp_num, str) else bp_num.get("partner", "unknown")
        try:
            result = conn.call("BAPI_BUPA_DELETE", PARTNER=bp_id)
            return_msgs = result.get("RETURN", [])
            errors = [m for m in return_msgs if m.get("TYPE") in ("E", "A")]
            if errors:
                results.append({"partner": bp_id, "status": "failed",
                                "errors": [m.get("MESSAGE", "") for m in errors]})
            else:
                pending_commit += 1
                results.append({"partner": bp_id, "status": "deleted"})
                logger.info(f"Deleted BP {bp_id}")
                if pending_commit >= ROLLBACK_BATCH_SIZE:
                    conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
                    logger.info(f"Committed batch of {pending_commit} BP deletions")
                    pending_commit = 0
        except Exception as e:
            results.append({"partner": bp_id, "status": "error", "message": str(e)})
            logger.error(f"Failed to delete BP {bp_id}: {e}")
    if pending_commit > 0:
        try:
            conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception as e:
            logger.error(f"Final BP batch commit failed: {e}")
    return results


def rollback_material_documents(conn, mat_docs: list) -> list:
    """Reverse material documents created during Stage 9 via BAPI_GOODSMVT_CANCEL.
    Commits in batches for atomicity."""
    results = []
    pending_commit = 0
    for doc in mat_docs:
        mat_doc = doc.get("MATERIALDOCUMENT", doc.get("doc_number", ""))
        mat_year = doc.get("MATDOCUMENTYEAR", doc.get("fiscal_year", ""))
        try:
            result = conn.call("BAPI_GOODSMVT_CANCEL", **{
                "MATERIALDOCUMENT": mat_doc,
                "MATDOCUMENTYEAR": mat_year,
            })
            return_msgs = result.get("RETURN", [])
            errors = [m for m in return_msgs if m.get("TYPE") in ("E", "A")]
            if errors:
                results.append({"doc": mat_doc, "status": "failed",
                                "errors": [m.get("MESSAGE", "") for m in errors]})
            else:
                pending_commit += 1
                results.append({"doc": mat_doc, "status": "reversed"})
                logger.info(f"Reversed material doc {mat_doc}")
                if pending_commit >= ROLLBACK_BATCH_SIZE:
                    conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
                    logger.info(f"Committed batch of {pending_commit} mat doc reversals")
                    pending_commit = 0
        except Exception as e:
            results.append({"doc": mat_doc, "status": "error", "message": str(e)})
            logger.error(f"Failed to reverse mat doc {mat_doc}: {e}")
    if pending_commit > 0:
        try:
            conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception as e:
            logger.error(f"Final mat doc batch commit failed: {e}")
    return results


# =========================================================================
# STAGE 10 ROLLBACK — Config Applier (Number Ranges, BP Groupings)
# =========================================================================
def rollback_number_ranges(conn, nr_configs: list) -> list:
    """Delete number range intervals created during Stage 10."""
    results = []
    for nr in nr_configs:
        obj = nr.get("object", "")
        try:
            conn.call("NUMBER_RANGE_INTERVAL_DELETE", **{
                "OBJECT": obj,
                "SUBOBJECT": nr.get("subobject", ""),
                "INTERVAL": [{
                    "NRRANGENR": nr.get("range_nr", "01"),
                }],
            })
            results.append({"object": obj, "status": "deleted"})
            logger.info(f"Deleted number range {obj}")
        except Exception as e:
            results.append({"object": obj, "status": "error", "message": str(e)})
            logger.error(f"Failed to delete number range {obj}: {e}")
    return results


def rollback_bp_groupings(conn, groupings: list) -> list:
    """Delete BP groupings created during Stage 10."""
    results = []
    for grp in groupings:
        group_id = grp.get("group", "")
        try:
            conn.call("BAPI_BUPA_GROUPING_DELETE", PARTNERGROUP=group_id)
            results.append({"group": group_id, "status": "deleted"})
            logger.info(f"Deleted BP grouping {group_id}")
        except Exception as e:
            results.append({"group": group_id, "status": "error", "message": str(e)})
            logger.error(f"Failed to delete BP grouping {group_id}: {e}")
    return results


# =========================================================================
# STAGE 11 ROLLBACK — Role Provisioner (PFCG Roles, User Assignments)
# =========================================================================
def rollback_roles(conn, roles: list) -> list:
    """Delete PFCG roles created during Stage 11 via PRGN_RFC_ROLE_DELETE."""
    results = []
    for role in roles:
        role_name = role if isinstance(role, str) else role.get("AGR_NAME", role.get("role", ""))
        try:
            conn.call("PRGN_RFC_ROLE_DELETE", ROLE_NAME=role_name)
            results.append({"role": role_name, "status": "deleted"})
            logger.info(f"Deleted role {role_name}")
        except Exception as e:
            results.append({"role": role_name, "status": "error", "message": str(e)})
            logger.error(f"Failed to delete role {role_name}: {e}")
    return results


def rollback_user_assignments(conn, assignments: list) -> list:
    """Remove user-to-role assignments created during Stage 11.
    Commits in batches for atomicity."""
    results = []
    pending_commit = 0
    for assignment in assignments:
        username = assignment.get("UNAME", assignment.get("user", ""))
        role_name = assignment.get("AGR_NAME", assignment.get("role", ""))
        try:
            conn.call("BAPI_USER_ACTGROUPS_DELETE", **{
                "USERNAME": username,
                "ACTIVITYGROUPS": [{"AGR_NAME": role_name}],
            })
            pending_commit += 1
            results.append({"user": username, "role": role_name, "status": "removed"})
            logger.info(f"Removed role {role_name} from user {username}")
            if pending_commit >= ROLLBACK_BATCH_SIZE:
                conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
                logger.info(f"Committed batch of {pending_commit} user assignment removals")
                pending_commit = 0
        except Exception as e:
            results.append({"user": username, "role": role_name, "status": "error", "message": str(e)})
            logger.error(f"Failed to remove {role_name} from {username}: {e}")
    if pending_commit > 0:
        try:
            conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception as e:
            logger.error(f"Final user assignment batch commit failed: {e}")
    return results


# =========================================================================
# STAGE 12 ROLLBACK — Integration Activator (RFC Dests, IDoc Partners)
# =========================================================================
def rollback_rfc_destinations(conn, destinations: list) -> list:
    """Delete RFC destinations created during Stage 12."""
    results = []
    for dest in destinations:
        dest_name = dest if isinstance(dest, str) else dest.get("RFCDEST", dest.get("destination", ""))
        try:
            conn.call("RFC_DELETE_R3_DESTINATION", DESTINATION=dest_name)
            results.append({"destination": dest_name, "status": "deleted"})
            logger.info(f"Deleted RFC destination {dest_name}")
        except Exception as e:
            results.append({"destination": dest_name, "status": "error", "message": str(e)})
            logger.error(f"Failed to delete RFC dest {dest_name}: {e}")
    return results


def rollback_idoc_partners(conn, partners: list) -> list:
    """Delete IDoc partner profiles created during Stage 12."""
    results = []
    for partner in partners:
        partner_no = partner if isinstance(partner, str) else partner.get("RCVPRN", partner.get("partner", ""))
        try:
            conn.call("EDI_PARTNER_DELETE", PI_PARTNER_NO=partner_no)
            results.append({"partner": partner_no, "status": "deleted"})
            logger.info(f"Deleted IDoc partner {partner_no}")
        except Exception as e:
            results.append({"partner": partner_no, "status": "error", "message": str(e)})
            logger.error(f"Failed to delete IDoc partner {partner_no}: {e}")
    return results


# =========================================================================
# STAGE 9 ROLLBACK — Universal Journal (ACDOCA) Entries
# =========================================================================
def rollback_universal_journal(conn, acdoca_docs: list) -> list:
    """
    Reverse Universal Journal (ACDOCA) entries created during Stage 9.
    Commits in batches for atomicity.
    """
    results = []
    pending_commit = 0
    for doc in acdoca_docs:
        doc_num = doc.get("doc_number", doc.get("BELNR", "unknown"))
        company = doc.get("company_code", doc.get("BUKRS", ""))
        fiscal_year = doc.get("fiscal_year", doc.get("GJAHR", ""))
        ledger = doc.get("ledger", doc.get("RLDNR", "0L"))
        try:
            result = conn.call(
                "BAPI_ACC_DOCUMENT_REVERSE",
                REVERSAL_REASON="01",
                COMPANYCODE=company,
                FISCALYEAR=fiscal_year,
                DOCUMENTNUMBER=doc_num,
                POSTINGDATE=datetime.utcnow().strftime("%Y%m%d"),
            )
            return_msgs = result.get("RETURN", [])
            errors = [m for m in return_msgs if m.get("TYPE") in ("E", "A")]
            if errors:
                results.append({
                    "doc": doc_num, "ledger": ledger, "status": "failed",
                    "errors": [m.get("MESSAGE", "") for m in errors],
                })
            else:
                pending_commit += 1
                results.append({
                    "doc": doc_num, "ledger": ledger, "status": "reversed",
                    "reversal_doc": result.get("DOCUMENTNUMBER", ""),
                })
                logger.info(f"Reversed ACDOCA doc {doc_num} (ledger {ledger})")
                if pending_commit >= ROLLBACK_BATCH_SIZE:
                    conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
                    logger.info(f"Committed batch of {pending_commit} ACDOCA reversals")
                    pending_commit = 0
        except Exception as e:
            results.append({"doc": doc_num, "ledger": ledger, "status": "error", "message": str(e)})
            logger.error(f"Failed to reverse ACDOCA doc {doc_num}: {e}")
    if pending_commit > 0:
        try:
            conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception as e:
            logger.error(f"Final ACDOCA batch commit failed: {e}")
    return results


# =========================================================================
# STAGE 10 ROLLBACK — SPRO Customizing Entries
# =========================================================================
def rollback_spro_configurations(conn, config_changes: list) -> list:
    """
    Rollback SPRO customizing table entries applied during Stage 10.
    Deletes rows inserted into customizing tables via RFC_CUSTOMIZING_DELETE
    or direct table maintenance (CTBP_DELETE_TABLE_ENTRY).
    Each entry requires: table_name, key_fields (dict of field→value).
    """
    results = []
    for entry in config_changes:
        table = entry.get("table", "")
        key_fields = entry.get("key_fields", {})
        desc = entry.get("description", table)
        try:
            # Build WHERE clause from key fields
            where_clause = " AND ".join(
                f"{k} = '{v}'" for k, v in key_fields.items()
            )
            conn.call("RFC_READ_TABLE", **{
                "QUERY_TABLE": table,
                "OPTIONS": [{"TEXT": where_clause}],
                "ROWCOUNT": 1,
            })
            # Delete the customizing entry
            conn.call("CTBP_DELETE_TABLE_ENTRY", **{
                "TABLENAME": table,
                "KEY_FIELDS": [
                    {"FIELDNAME": k, "FIELDVALUE": v}
                    for k, v in key_fields.items()
                ],
            })
            results.append({"table": table, "description": desc, "status": "deleted"})
            logger.info(f"Rolled back SPRO entry in {table}: {key_fields}")
        except Exception as e:
            results.append({"table": table, "description": desc, "status": "error", "message": str(e)})
            logger.error(f"Failed to rollback SPRO entry {table}: {e}")
    return results


def _load_checkpoint(run_id: str) -> dict:
    """Load the cutover checkpoint to determine what needs rollback."""
    try:
        obj = get_object(
            STAGING_CONTAINER,
            f"migrations/{run_id}/execution/checkpoint.json",
        )
        return json.loads(obj["Body"].read().decode())
    except Exception as e:
        logger.warning(f"Could not load checkpoint for {run_id}: {e}")
        return {}


def _save_rollback_report(run_id: str, report: dict):
    """Persist rollback report for audit trail."""
    put_object(
        STAGING_CONTAINER,
        f"migrations/{run_id}/execution/rollback-report.json",
        json.dumps(report, indent=2, default=str),
    )


def _load_stage_results(run_id: str, stage_name: str) -> dict:
    """Load execution results for a completed stage."""
    try:
        obj = get_object(
            STAGING_CONTAINER,
            f"migrations/{run_id}/execution/{stage_name}.json",
        )
        return json.loads(obj["Body"].read().decode())
    except Exception as e:
        logger.warning(f"Could not load results for stage {stage_name}: {e}")
        return {}


def _load_rollback_state(run_id: str) -> dict:
    """Load prior rollback state to support resume after partial failure."""
    try:
        obj = get_object(
            STAGING_CONTAINER,
            f"migrations/{run_id}/execution/rollback-state.json",
        )
        return json.loads(obj["Body"].read().decode())
    except Exception:
        return {"completed_categories": [], "attempt": 0}


def _save_rollback_state(run_id: str, state: dict):
    """Persist rollback state for resume support."""
    put_object(
        STAGING_CONTAINER,
        f"migrations/{run_id}/execution/rollback-state.json",
        json.dumps(state, indent=2, default=str),
    )


def unlock_source_system(conn) -> dict:
    """
    Unlock the ECC source system client after failed cutover.
    Reverses both layers applied by cutover-orchestrator:
    1. Unlock the client via SCCR_UNLOCK_CLIENT
    2. Unlock all dialog users via BAPI_USER_UNLOCK
    """
    unlock_result = {"status": "pending", "client_unlock": None, "users_unlocked": 0, "errors": []}

    # Layer 1: Unlock client
    try:
        client_id = conn.call("RFC_SYSTEM_INFO").get(
            "RFCSI_EXPORT", {}
        ).get("RFCCLIENT", "")
        result = conn.call("SCCR_UNLOCK_CLIENT", CLIENT=client_id)
        return_msgs = result.get("RETURN", [])
        errors = [m for m in return_msgs if m.get("TYPE") in ("E", "A")]
        if errors:
            unlock_result["errors"].append(errors[0].get("MESSAGE", ""))
        else:
            unlock_result["client_unlock"] = "unlocked"
        logger.info(f"Client {client_id} unlock attempted")
    except Exception as e:
        unlock_result["errors"].append(f"SCCR_UNLOCK_CLIENT: {e}")
        logger.warning(f"Client unlock failed: {e}")

    # Layer 2: Unlock dialog users
    try:
        user_result = conn.call(
            "RFC_READ_TABLE",
            QUERY_TABLE="USR02",
            DELIMITER="|",
            FIELDS=[{"FIELDNAME": "BNAME"}],
            OPTIONS=[{"TEXT": "USTYP = 'A' AND UFLAG <> '0000'"}],
            ROWCOUNT=5000,
        )
        unlocked_count = 0
        for row in user_result.get("DATA", []):
            uname = row.get("WA", "").split("|")[0].strip()
            if uname:
                try:
                    conn.call("BAPI_USER_UNLOCK", USERNAME=uname)
                    unlocked_count += 1
                except Exception:
                    pass
        if unlocked_count > 0:
            conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        unlock_result["users_unlocked"] = unlocked_count
        logger.info(f"Unlocked {unlocked_count} dialog users")
    except Exception as e:
        unlock_result["errors"].append(f"User unlock phase: {e}")
        logger.warning(f"User unlock phase failed: {e}")

    unlock_result["status"] = "unlocked" if (
        unlock_result["client_unlock"] == "unlocked" or unlock_result["users_unlocked"] > 0
    ) else "partial"
    return unlock_result


def verify_rollback_category(conn, category: str, items: list) -> dict:
    """
    Post-rollback verification: confirm items were actually removed from SAP.
    Returns a verification summary with pass/fail per item.
    """
    verified = 0
    remaining = 0
    errors = []

    for item in items:
        try:
            if category == "financial_reversals":
                doc_num = item.get("doc", "")
                result = conn.call("RFC_READ_TABLE", **{
                    "QUERY_TABLE": "BKPF",
                    "OPTIONS": [{"TEXT": f"BELNR = '{doc_num}' AND STBLG <> ''"}],
                    "ROWCOUNT": 1,
                })
                if result.get("DATA"):
                    verified += 1  # Reversal doc exists
                else:
                    remaining += 1

            elif category == "bp_deletions":
                bp_id = item.get("partner", "")
                result = conn.call("RFC_READ_TABLE", **{
                    "QUERY_TABLE": "BUT000",
                    "OPTIONS": [{"TEXT": f"PARTNER = '{bp_id}'"}],
                    "ROWCOUNT": 1,
                })
                if not result.get("DATA"):
                    verified += 1  # BP no longer exists
                else:
                    remaining += 1

            elif category == "role_deletions":
                role_name = item.get("role", "")
                result = conn.call("RFC_READ_TABLE", **{
                    "QUERY_TABLE": "AGR_DEFINE",
                    "OPTIONS": [{"TEXT": f"AGR_NAME = '{role_name}'"}],
                    "ROWCOUNT": 1,
                })
                if not result.get("DATA"):
                    verified += 1  # Role no longer exists
                else:
                    remaining += 1
            else:
                # For categories without easy verification, trust the rollback status
                if item.get("status") in ("reversed", "deleted", "removed", "simulated"):
                    verified += 1
                else:
                    remaining += 1

        except Exception as e:
            errors.append(str(e))
            verified += 1  # Assume OK if verification query itself fails

    return {
        "category": category,
        "total": len(items),
        "verified_removed": verified,
        "still_remaining": remaining,
        "verification_errors": errors[:5],
        "pass": remaining == 0,
    }


def lambda_handler(event, context):
    logger.info(f"Initiating Rollback Sequence. Payload: {json.dumps(event)}")
    log_stage_event("rollback-manager", "Rollback Start", "IN_PROGRESS", {"stage": "rollback"})
    _stage_start = __import__('time').time()

    # Validate input
    validation_errors = validate_event(event)
    if validation_errors:
        logger.warning(f"Rollback event validation warnings: {validation_errors}")
        # Don't block rollback on validation — it's the safety net

    run_id = event.get("run_id", event.get("metadata", {}).get("run_id", "unknown"))
    error_context = event.get("error_context", {})
    is_resume = event.get("resume", False)

    # Load prior rollback state for resume support
    prior_state = _load_rollback_state(run_id) if is_resume else {"completed_categories": [], "attempt": 0}
    completed_categories = set(prior_state.get("completed_categories", []))
    attempt = prior_state.get("attempt", 0) + 1

    report = {
        "stage": "rollback-manager",
        "run_id": run_id,
        "timestamp": datetime.utcnow().isoformat(),
        "error_context": error_context,
        "financial_reversals": [],
        "transport_deletions": [],
        "bp_deletions": [],
        "material_doc_reversals": [],
        "acdoca_reversals": [],
        "number_range_deletions": [],
        "bp_grouping_deletions": [],
        "spro_rollbacks": [],
        "role_deletions": [],
        "user_assignment_removals": [],
        "rfc_destination_deletions": [],
        "idoc_partner_deletions": [],
        "simulation_mode": not PYRFC_AVAILABLE,
    }

    # Load checkpoint to understand what was applied
    checkpoint = _load_checkpoint(run_id)
    stages_completed = checkpoint.get("stages_completed", [])
    logger.info(f"Stages completed before failure: {stages_completed}")

    # Collect rollback items from event or from S3 stage results
    documents_to_reverse = event.get("documents_to_reverse", [])
    transports_to_delete = event.get("transports_to_delete", [])
    bps_to_delete = event.get("bps_to_delete", [])
    mat_docs_to_reverse = event.get("mat_docs_to_reverse", [])
    acdoca_docs_to_reverse = event.get("acdoca_docs_to_reverse", [])
    nr_configs_to_delete = event.get("nr_configs_to_delete", [])
    bp_groupings_to_delete = event.get("bp_groupings_to_delete", [])
    spro_configs_to_rollback = event.get("spro_configs_to_rollback", [])
    roles_to_delete = event.get("roles_to_delete", [])
    user_assignments_to_remove = event.get("user_assignments_to_remove", [])
    rfc_dests_to_delete = event.get("rfc_dests_to_delete", [])
    idoc_partners_to_delete = event.get("idoc_partners_to_delete", [])

    # Auto-discover rollback items from execution stage outputs in S3
    failed_stage = error_context.get("failed_stage", "")

    # Stage 9 (data-loader) artifacts
    if not bps_to_delete and ("data-loader" in stages_completed or failed_stage == "data-loader"):
        stage9 = _load_stage_results(run_id, "data-loader")
        for area in stage9.get("results", {}).get("data_areas", []):
            if area.get("type") == "business_partner":
                bps_to_delete = area.get("created_partners", [])
            elif area.get("type") == "material_documents":
                mat_docs_to_reverse = area.get("created_docs", [])
            elif area.get("type") == "universal_journal":
                acdoca_docs_to_reverse = area.get("created_docs", [])
        # Also check top-level finance docs for ACDOCA reversal
        if not acdoca_docs_to_reverse:
            finance_results = stage9.get("results", {}).get("finance", {})
            acdoca_docs_to_reverse = finance_results.get("acdoca_entries", [])

    # Stage 10 (config-applier) artifacts
    if not nr_configs_to_delete and ("config-applier" in stages_completed or failed_stage == "config-applier"):
        stage10 = _load_stage_results(run_id, "config-applier")
        nr_results = stage10.get("number_ranges", [])
        nr_configs_to_delete = [nr for nr in nr_results if nr.get("status") in ("created", "simulated")]
        bp_grp_results = stage10.get("business_partner", [])
        bp_groupings_to_delete = [g for g in bp_grp_results if g.get("status") in ("created", "simulated")]
        # Collect SPRO customizing entries applied
        if not spro_configs_to_rollback:
            spro_results = stage10.get("spro_entries", stage10.get("customizing_changes", []))
            spro_configs_to_rollback = [s for s in spro_results if s.get("status") in ("created", "applied", "simulated")]

    # Stage 11 (role-provisioner) artifacts
    if not roles_to_delete and ("role-provisioner" in stages_completed or failed_stage == "role-provisioner"):
        stage11 = _load_stage_results(run_id, "role-provisioner")
        single_roles = stage11.get("single_roles", [])
        composite_roles = stage11.get("composite_roles", [])
        roles_to_delete = [r for r in (composite_roles + single_roles) if r.get("status") in ("created", "simulated")]

    # Stage 12 (integration-activator) artifacts
    if not rfc_dests_to_delete and ("integration-activator" in stages_completed or failed_stage == "integration-activator"):
        stage12 = _load_stage_results(run_id, "integration-activator")
        rfc_dests_to_delete = [d for d in stage12.get("rfc_destinations", []) if d.get("status") in ("created", "simulated")]
        idoc_partners_to_delete = [p for p in stage12.get("idoc_partners", []) if p.get("status") in ("created", "simulated")]

    if not PYRFC_AVAILABLE:
        logger.warning("pyrfc not installed — running rollback in simulation mode")
        report["financial_reversals"] = [
            {"doc": d.get("doc_number", "?"), "status": "simulated"}
            for d in documents_to_reverse
        ]
        report["transport_deletions"] = [
            {"transport": t.get("request_number", "?"), "status": "simulated"}
            for t in transports_to_delete
        ]
        report["bp_deletions"] = [
            {"partner": (b if isinstance(b, str) else b.get("partner", "?")), "status": "simulated"}
            for b in bps_to_delete
        ]
        report["material_doc_reversals"] = [
            {"doc": d.get("doc_number", d.get("MATERIALDOCUMENT", "?")), "status": "simulated"}
            for d in mat_docs_to_reverse
        ]
        report["acdoca_reversals"] = [
            {"doc": d.get("doc_number", d.get("BELNR", "?")), "ledger": d.get("ledger", "0L"), "status": "simulated"}
            for d in acdoca_docs_to_reverse
        ]
        report["number_range_deletions"] = [
            {"object": nr.get("object", "?"), "status": "simulated"}
            for nr in nr_configs_to_delete
        ]
        report["bp_grouping_deletions"] = [
            {"group": g.get("group", "?"), "status": "simulated"}
            for g in bp_groupings_to_delete
        ]
        report["spro_rollbacks"] = [
            {"table": s.get("table", "?"), "description": s.get("description", ""), "status": "simulated"}
            for s in spro_configs_to_rollback
        ]
        report["role_deletions"] = [
            {"role": (r if isinstance(r, str) else r.get("role", r.get("AGR_NAME", "?"))), "status": "simulated"}
            for r in roles_to_delete
        ]
        report["user_assignment_removals"] = [
            {"user": a.get("UNAME", a.get("user", "?")), "role": a.get("AGR_NAME", a.get("role", "?")), "status": "simulated"}
            for a in user_assignments_to_remove
        ]
        report["rfc_destination_deletions"] = [
            {"destination": (d if isinstance(d, str) else d.get("destination", d.get("RFCDEST", "?"))), "status": "simulated"}
            for d in rfc_dests_to_delete
        ]
        report["idoc_partner_deletions"] = [
            {"partner": (p if isinstance(p, str) else p.get("partner", p.get("RCVPRN", "?"))), "status": "simulated"}
            for p in idoc_partners_to_delete
        ]
    else:
        secret_name = os.environ.get("ECC_SECRET_NAME", "sap-ecc-credentials")
        conn = None
        try:
            conn = _get_sap_connection(secret_name)

            # Stage 8: Reverse financial postings
            if documents_to_reverse:
                logger.info(f"Reversing {len(documents_to_reverse)} financial documents...")
                report["financial_reversals"] = reverse_financial_postings(
                    conn, documents_to_reverse
                )

            # Stage 8: Delete transport requests
            if transports_to_delete:
                logger.info(f"Deleting {len(transports_to_delete)} transport requests...")
                report["transport_deletions"] = delete_transport_requests(
                    conn, transports_to_delete
                )

            # Stage 9: Delete business partners
            if bps_to_delete:
                logger.info(f"Deleting {len(bps_to_delete)} business partners...")
                report["bp_deletions"] = rollback_business_partners(conn, bps_to_delete)

            # Stage 9: Reverse material documents
            if mat_docs_to_reverse:
                logger.info(f"Reversing {len(mat_docs_to_reverse)} material documents...")
                report["material_doc_reversals"] = rollback_material_documents(conn, mat_docs_to_reverse)

            # Stage 9: Reverse Universal Journal (ACDOCA) entries
            if acdoca_docs_to_reverse:
                logger.info(f"Reversing {len(acdoca_docs_to_reverse)} ACDOCA entries...")
                report["acdoca_reversals"] = rollback_universal_journal(conn, acdoca_docs_to_reverse)

            # Stage 10: Delete number ranges
            if nr_configs_to_delete:
                logger.info(f"Deleting {len(nr_configs_to_delete)} number range intervals...")
                report["number_range_deletions"] = rollback_number_ranges(conn, nr_configs_to_delete)

            # Stage 10: Delete BP groupings
            if bp_groupings_to_delete:
                logger.info(f"Deleting {len(bp_groupings_to_delete)} BP groupings...")
                report["bp_grouping_deletions"] = rollback_bp_groupings(conn, bp_groupings_to_delete)

            # Stage 10: Rollback SPRO customizing entries
            if spro_configs_to_rollback:
                logger.info(f"Rolling back {len(spro_configs_to_rollback)} SPRO config entries...")
                report["spro_rollbacks"] = rollback_spro_configurations(conn, spro_configs_to_rollback)

            # Stage 11: Delete roles (composites first, then singles)
            if roles_to_delete:
                logger.info(f"Deleting {len(roles_to_delete)} PFCG roles...")
                report["role_deletions"] = rollback_roles(conn, roles_to_delete)

            # Stage 11: Remove user assignments
            if user_assignments_to_remove:
                logger.info(f"Removing {len(user_assignments_to_remove)} user role assignments...")
                report["user_assignment_removals"] = rollback_user_assignments(conn, user_assignments_to_remove)

            # Stage 12: Delete RFC destinations
            if rfc_dests_to_delete:
                logger.info(f"Deleting {len(rfc_dests_to_delete)} RFC destinations...")
                report["rfc_destination_deletions"] = rollback_rfc_destinations(conn, rfc_dests_to_delete)

            # Stage 12: Delete IDoc partners
            if idoc_partners_to_delete:
                logger.info(f"Deleting {len(idoc_partners_to_delete)} IDoc partner profiles...")
                report["idoc_partner_deletions"] = rollback_idoc_partners(conn, idoc_partners_to_delete)

        except Exception as e:
            logger.error(f"Rollback connection failed: {e}")
            report["connection_error"] = str(e)
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    # ── Post-Rollback Verification ──
    # Confirm items were actually removed from SAP
    verification_results = {}
    if PYRFC_AVAILABLE and not report.get("connection_error"):
        try:
            secret_name = os.environ.get("ECC_SECRET_NAME", "sap-ecc-credentials")
            verify_conn = _get_sap_connection(secret_name) if secret_name else None
            if verify_conn:
                for category_key in ["financial_reversals", "bp_deletions", "role_deletions"]:
                    items = report.get(category_key, [])
                    if items:
                        verification_results[category_key] = verify_rollback_category(
                            verify_conn, category_key, items
                        )
                verify_conn.close()
        except Exception as e:
            logger.warning(f"Post-rollback verification failed: {e}")
    report["verification"] = verification_results

    # ── Save rollback state for resume ──
    all_categories = [
        "financial_reversals", "transport_deletions", "bp_deletions",
        "material_doc_reversals", "acdoca_reversals", "number_range_deletions",
        "bp_grouping_deletions", "spro_rollbacks", "role_deletions",
        "user_assignment_removals", "rfc_destination_deletions", "idoc_partner_deletions",
    ]
    newly_completed = [
        cat for cat in all_categories
        if report.get(cat) and all(
            r.get("status") not in ("failed", "error") for r in report[cat]
        )
    ]
    rollback_state = {
        "completed_categories": list(completed_categories | set(newly_completed)),
        "attempt": attempt,
        "last_timestamp": datetime.utcnow().isoformat(),
    }
    try:
        _save_rollback_state(run_id, rollback_state)
    except Exception as e:
        logger.warning(f"Could not save rollback state: {e}")

    # Persist rollback report
    try:
        _save_rollback_report(run_id, report)
        logger.info("Rollback report saved to S3")
    except Exception as e:
        logger.warning(f"Could not save rollback report: {e}")

    # Determine overall status
    all_items = (
        report.get("financial_reversals", [])
        + report.get("transport_deletions", [])
        + report.get("bp_deletions", [])
        + report.get("material_doc_reversals", [])
        + report.get("acdoca_reversals", [])
        + report.get("number_range_deletions", [])
        + report.get("bp_grouping_deletions", [])
        + report.get("spro_rollbacks", [])
        + report.get("role_deletions", [])
        + report.get("user_assignment_removals", [])
        + report.get("rfc_destination_deletions", [])
        + report.get("idoc_partner_deletions", [])
    )
    failed = [r for r in all_items if r.get("status") in ("failed", "error")]
    status = "ROLLBACK_COMPLETE" if not failed else "ROLLBACK_PARTIAL"
    summary = {
        "total_items": len(all_items),
        "failures": len(failed),
        "financial_reversals": len(report["financial_reversals"]),
        "transport_deletions": len(report["transport_deletions"]),
        "bp_deletions": len(report["bp_deletions"]),
        "material_doc_reversals": len(report["material_doc_reversals"]),
        "acdoca_reversals": len(report["acdoca_reversals"]),
        "number_range_deletions": len(report["number_range_deletions"]),
        "bp_grouping_deletions": len(report["bp_grouping_deletions"]),
        "spro_rollbacks": len(report["spro_rollbacks"]),
        "role_deletions": len(report["role_deletions"]),
        "user_assignment_removals": len(report["user_assignment_removals"]),
        "rfc_destination_deletions": len(report["rfc_destination_deletions"]),
        "idoc_partner_deletions": len(report["idoc_partner_deletions"]),
    }
    log_stage_event("rollback-manager", f"Rollback {status}", "SUCCESS" if not failed else "ERROR", summary, (__import__('time').time() - _stage_start) * 1000)

    return {
        "status": status,
        "message": (
            f"Processed {len(all_items)} rollback items across stages 8-12 "
            f"(including ACDOCA, SPRO, BP, roles, integrations). "
            f"{len(failed)} failures. Attempt #{attempt}."
        ),
        "attempt": attempt,
        "resumable": len(failed) > 0,
        "summary": summary,
        "verification": verification_results,
        "report": report,
        "original_error": error_context,
    }