"""
Migrate4HANA — Stage 6: Integration Mapper
============================================
Maps and rewires all integration points from ECC to S/4HANA.

Integration types handled:
1. RFC Destinations (SM59) → Reconfigure for new hostname
2. IDoc Partners (WE20) → Update port & partner profiles
3. PI/PO Interfaces → Map to SAP Cloud Integration (CPI)
4. BAPIs → Check availability in S/4HANA
5. Web Services (SOAMANAGER) → Re-register endpoints
6. Third-party connections → Document & plan rewiring

DevOps Analogy:
Think of this like updating all your API endpoints, webhook URLs,
and service mesh routes when you migrate from one Kubernetes cluster
to another. Every system that talks to SAP needs to know the new address.
"""

import json
import os
import sys
import logging
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'utils')))
from logger import log_stage_event
from storage_client import put_object, get_object
from secrets_client import get_secret_value

logger = logging.getLogger()
logger.setLevel(logging.INFO)

STAGING_BUCKET = os.environ.get("AZURE_STORAGE_CONTAINER", "staging")


# =============================================================================
# DEPRECATED/CHANGED BAPIS IN S/4HANA
# =============================================================================
BAPI_CHANGES = {
    "BAPI_MATERIAL_SAVEDATA": {
        "status": "available",
        "note": "Still available but some fields deprecated",
    },
    "BAPI_ACC_DOCUMENT_POST": {
        "status": "available",
        "note": "Available, uses ACDOCA internally now",
    },
    "BAPI_SALESORDER_CREATEFROMDAT2": {
        "status": "available",
        "note": "Available with extended fields",
    },
    "BAPI_PO_CREATE1": {
        "status": "available",
        "note": "Available, MATDOC changes transparent",
    },
    "BAPI_GOODSMVT_CREATE": {
        "status": "available",
        "note": "Available, writes to MATDOC internally",
    },
    "BAPI_CUSTOMER_CREATEFROMDATA1": {
        "status": "deprecated",
        "replacement": "API_BUSINESS_PARTNER",
        "note": "Replace with BP API — customer master is now BP",
    },
    "BAPI_VENDOR_CREATE": {
        "status": "deprecated",
        "replacement": "API_BUSINESS_PARTNER",
        "note": "Replace with BP API — vendor master is now BP",
    },
    "BAPI_COSTCENTER_CREATEMULTIPLE": {
        "status": "available",
        "note": "Available, minor field changes",
    },
}

# PI/PO → Cloud Integration migration patterns
PIOP_TO_CPI_PATTERNS = {
    "IDoc_Sender": {
        "cpi_adapter": "IDoc adapter",
        "cpi_pattern": "IDoc receiver channel",
        "notes": "Configure IDoc metadata in Cloud Integration",
    },
    "RFC_Sender": {
        "cpi_adapter": "RFC adapter",
        "cpi_pattern": "RFC receiver channel",
        "notes": "RFC adapter available in Cloud Integration",
    },
    "SOAP_Sender": {
        "cpi_adapter": "SOAP adapter",
        "cpi_pattern": "SOAP 1.x receiver",
        "notes": "Direct migration, update endpoint URL",
    },
    "HTTP_Sender": {
        "cpi_adapter": "HTTP adapter",
        "cpi_pattern": "HTTP receiver",
        "notes": "Update URL and authentication",
    },
    "REST_Sender": {
        "cpi_adapter": "HTTP adapter (REST)",
        "cpi_pattern": "REST receiver with JSON",
        "notes": "Use JSON-to-XML converter if needed",
    },
    "FILE_Sender": {
        "cpi_adapter": "SFTP adapter",
        "cpi_pattern": "SFTP sender/receiver",
        "notes": "Migrate from NFS/FTP to SFTP in cloud",
    },
}


def extract_rfc_destinations(conn):
    """Extract RFC destinations (SM59 equivalent)."""
    logger.info("Extracting RFC destinations...")

    result = conn.call(
        "RFC_READ_TABLE",
        QUERY_TABLE="RFCDES",
        DELIMITER="|",
        FIELDS=[
            {"FIELDNAME": "RFCDEST"},
            {"FIELDNAME": "RFCTYPE"},
            {"FIELDNAME": "RFCOPTIONS"},
        ],
        ROWCOUNT=99999,
    )

    destinations = []
    type_names = {
        "3": "ABAP Connection",
        "H": "HTTP Connection",
        "G": "External Program (RFC)",
        "T": "TCP/IP Connection",
        "I": "Internal Connection",
        "L": "Logical Destination",
        "X": "Special (ABAP/4 driver)",
    }

    for row in result.get("DATA", []):
        fields = row["WA"].split("|")
        if len(fields) >= 2:
            dest_name = fields[0].strip()
            dest_type = fields[1].strip()
            destinations.append({
                "name": dest_name,
                "type_code": dest_type,
                "type_name": type_names.get(dest_type, "Unknown"),
                "is_sap_standard": not (dest_name.startswith("Z") or dest_name.startswith("Y")),
                "migration_action": get_rfc_migration_action(dest_name, dest_type),
            })

    return destinations


def get_rfc_migration_action(name, rfc_type):
    """Determine migration action for an RFC destination."""
    if rfc_type == "3":
        return {
            "action": "update_hostname",
            "detail": "Change target host to S/4HANA application server",
            "automated": True,
        }
    elif rfc_type == "H":
        return {
            "action": "update_url",
            "detail": "Update HTTP endpoint URL to S/4HANA",
            "automated": True,
        }
    elif rfc_type == "G":
        return {
            "action": "verify_external",
            "detail": "Verify external program still works with S/4HANA",
            "automated": False,
        }
    else:
        return {
            "action": "manual_review",
            "detail": f"Review {rfc_type} type destination manually",
            "automated": False,
        }


def extract_idoc_partners(conn):
    """Extract IDoc partner profiles (WE20 equivalent)."""
    logger.info("Extracting IDoc partner profiles...")

    try:
        result = conn.call(
            "RFC_READ_TABLE",
            QUERY_TABLE="EDPP1",
            DELIMITER="|",
            FIELDS=[
                {"FIELDNAME": "RCVPRN"},
                {"FIELDNAME": "RCVPRT"},
                {"FIELDNAME": "RCVPFC"},
                {"FIELDNAME": "MESTYP"},
                {"FIELDNAME": "IDOCTP"},
                {"FIELDNAME": "RCVPOR"},
            ],
            ROWCOUNT=99999,
        )

        partners = []
        for row in result.get("DATA", []):
            fields = row["WA"].split("|")
            if len(fields) >= 6:
                partners.append({
                    "partner_number": fields[0].strip(),
                    "partner_type": fields[1].strip(),
                    "partner_function": fields[2].strip(),
                    "message_type": fields[3].strip(),
                    "idoc_type": fields[4].strip(),
                    "port": fields[5].strip(),
                    "migration_action": {
                        "action": "reconfigure_port",
                        "detail": "Update port to point to S/4HANA or Cloud Integration",
                        "automated": True,
                    },
                })

        return partners

    except Exception as e:
        logger.warning(f"Could not read IDoc partners: {e}")
        return []


def check_bapi_compatibility(conn):
    """Check which BAPIs used in integrations are still available."""
    logger.info("Checking BAPI compatibility...")

    # Get list of RFC-enabled function modules being called
    try:
        result = conn.call(
            "RFC_READ_TABLE",
            QUERY_TABLE="TFDIR",
            DELIMITER="|",
            FIELDS=[
                {"FIELDNAME": "FUNCNAME"},
                {"FIELDNAME": "FMODE"},
            ],
            OPTIONS=[
                {"TEXT": "FUNCNAME LIKE 'BAPI%'"},
                {"TEXT": "AND FMODE = 'R'"},
            ],
            ROWCOUNT=99999,
        )

        bapis_in_use = []
        for row in result.get("DATA", []):
            fields = row["WA"].split("|")
            if len(fields) >= 1:
                bapi_name = fields[0].strip()
                change_info = BAPI_CHANGES.get(bapi_name, {
                    "status": "check_needed",
                    "note": "Not in known changes list — verify in S/4HANA",
                })

                bapis_in_use.append({
                    "bapi": bapi_name,
                    "status": change_info.get("status", "unknown"),
                    "note": change_info.get("note", ""),
                    "replacement": change_info.get("replacement"),
                })

        return bapis_in_use

    except Exception:
        return []


def generate_integration_plan(rfc_dests, idoc_partners, bapis):
    """Generate a comprehensive integration migration plan."""

    automated = 0
    manual = 0

    for dest in rfc_dests:
        if dest.get("migration_action", {}).get("automated"):
            automated += 1
        else:
            manual += 1

    for partner in idoc_partners:
        if partner.get("migration_action", {}).get("automated"):
            automated += 1
        else:
            manual += 1

    deprecated_bapis = [b for b in bapis if b.get("status") == "deprecated"]

    plan = {
        "summary": {
            "total_integrations": len(rfc_dests) + len(idoc_partners),
            "rfc_destinations": len(rfc_dests),
            "idoc_partners": len(idoc_partners),
            "bapis_in_use": len(bapis),
            "deprecated_bapis": len(deprecated_bapis),
            "automated_migrations": automated,
            "manual_migrations": manual,
            "automation_rate": f"{(automated / max(automated + manual, 1)) * 100:.1f}%",
        },
        "critical_actions": [],
        "pi_po_migration_guide": PIOP_TO_CPI_PATTERNS,
    }

    # Flag critical issues
    if deprecated_bapis:
        plan["critical_actions"].append({
            "priority": "critical",
            "action": f"{len(deprecated_bapis)} BAPIs deprecated in S/4HANA",
            "bapis": deprecated_bapis,
            "recommendation": "Replace with S/4HANA API equivalents before go-live",
        })

    external_rfcs = [d for d in rfc_dests if d.get("type_code") == "G"]
    if external_rfcs:
        plan["critical_actions"].append({
            "priority": "high",
            "action": f"{len(external_rfcs)} external RFC programs need verification",
            "recommendation": "Test each external program against S/4HANA",
        })

    return plan


# =============================================================================
# MAIN HANDLER
# =============================================================================
def lambda_handler(event, context):
    """Integration Mapper main handler."""
    logger.info("Integration Mapper started")
    log_stage_event("integration-mapper", "Pipeline Start", "IN_PROGRESS", {"stage": 6})
    _stage_start = __import__('time').time()

    run_id = event.get("metadata", {}).get("run_id", "manual-run")

    try:
        try:
            from pyrfc import Connection
            conn_params = json.loads(
                get_secret_value(os.environ.get("ECC_SECRET_NAME", "sap-ecc-credentials"))
                ["SecretString"]
            )
            conn = Connection(**conn_params)
            has_rfc = True
        except (ImportError, Exception):
            has_rfc = False

        if has_rfc:
            rfc_dests = extract_rfc_destinations(conn)
            idoc_partners = extract_idoc_partners(conn)
            bapis = check_bapi_compatibility(conn)
        else:
            logger.warning("No RFC — generating integration template")
            rfc_dests = []
            idoc_partners = []
            bapis = []

        # Generate migration plan
        plan = generate_integration_plan(rfc_dests, idoc_partners, bapis)

        # Save results
        put_object(
            STAGING_BUCKET,
            f"migrations/{run_id}/integrations/rfc-destinations.json",
            json.dumps(rfc_dests, indent=2, default=str),
        )

        put_object(
            STAGING_BUCKET,
            f"migrations/{run_id}/integrations/idoc-partners.json",
            json.dumps(idoc_partners, indent=2, default=str),
        )

        put_object(
            STAGING_BUCKET,
            f"migrations/{run_id}/integrations/bapi-compatibility.json",
            json.dumps(bapis, indent=2),
        )

        put_object(
            STAGING_BUCKET,
            f"migrations/{run_id}/integrations/migration-plan.json",
            json.dumps(plan, indent=2),
        )

        result = {
            "status": "success",
            "summary": plan["summary"],
            "critical_actions": len(plan["critical_actions"]),
            "s3_key": f"migrations/{run_id}/integrations/",
            "run_id": run_id,
        }
        log_stage_event("integration-mapper", "Integration Mapping Complete", "SUCCESS", result, (__import__('time').time() - _stage_start) * 1000)
        return result

    except Exception as e:
        logger.error(f"Integration mapping failed: {str(e)}")
        log_stage_event("integration-mapper", "Integration Mapping Failed", "ERROR", str(e))
        raise
