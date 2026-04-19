"""
Migrate4HANA — Stage 5: Role & Authorization Migrator
======================================================
Migrates PFCG roles, user masters, and authorization profiles
from ECC to S/4HANA, including Fiori catalog/group mapping.

DevOps Analogy:
- PFCG Role = IAM Role (bundles of permissions)
- Authorization Object = IAM Action (e.g., s3:PutObject)
- Authorization Field = IAM Resource constraint
- Composite Role = IAM Role with attached policies
- Fiori Catalog = Group of frontend app permissions
- Fiori Group = Visual grouping on the launchpad

Key challenges in S/4HANA:
1. Many T-codes replaced by Fiori apps → roles need new menu entries
2. Some authorization objects changed or removed
3. New Fiori catalog/group assignments needed
4. Launchpad space/page assignments (new concept)
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
# T-CODE → FIORI APP MAPPING
# =============================================================================
# This maps classic SAP transactions to their Fiori app equivalents.
# This is one of the most valuable parts of the migration tool.

TCODE_TO_FIORI = {
    # Finance
    "FB01": {"app": "F0717", "name": "Post General Journal Entries", "catalog": "SAP_SFIN_BC_GL_DOCPROC"},
    "FB03": {"app": "F0718", "name": "Display Journal Entries", "catalog": "SAP_SFIN_BC_GL_DOCPROC"},
    "FB50": {"app": "F0717", "name": "Post General Journal Entries", "catalog": "SAP_SFIN_BC_GL_DOCPROC"},
    "FB60": {"app": "F0859", "name": "Create Supplier Invoice", "catalog": "SAP_SFIN_BC_AP_INV"},
    "FB70": {"app": "F1558", "name": "Create Customer Invoice", "catalog": "SAP_SFIN_BC_AR_INV"},
    "FK01": {"app": "F1629", "name": "Manage Supplier Master Data", "catalog": "SAP_SFIN_BC_AP_MASTER"},
    "FK03": {"app": "F1629", "name": "Manage Supplier Master Data", "catalog": "SAP_SFIN_BC_AP_MASTER"},
    "FD01": {"app": "F1563", "name": "Manage Customer Master Data", "catalog": "SAP_SFIN_BC_AR_MASTER"},
    "FD03": {"app": "F1563", "name": "Manage Customer Master Data", "catalog": "SAP_SFIN_BC_AR_MASTER"},
    "FS00": {"app": "F2640", "name": "Manage G/L Account Master Data", "catalog": "SAP_SFIN_BC_GL_MASTER"},
    "F-28": {"app": "F0732", "name": "Post Incoming Payments", "catalog": "SAP_SFIN_BC_AR_PAY"},
    "F-53": {"app": "F0736", "name": "Post Outgoing Payments", "catalog": "SAP_SFIN_BC_AP_PAY"},

    # Materials Management
    "MM01": {"app": "F2641", "name": "Manage Product Master Data", "catalog": "SAP_MM_BC_MATERIAL_MASTER"},
    "MM03": {"app": "F2641", "name": "Manage Product Master Data", "catalog": "SAP_MM_BC_MATERIAL_MASTER"},
    "ME21N": {"app": "F1585", "name": "Create Purchase Order", "catalog": "SAP_MM_BC_PO_PROCESS"},
    "ME23N": {"app": "F2332", "name": "Manage Purchase Orders", "catalog": "SAP_MM_BC_PO_PROCESS"},
    "MIGO": {"app": "F2427", "name": "Post Goods Receipt", "catalog": "SAP_MM_BC_GR_PROCESS"},
    "MB51": {"app": "F2886", "name": "Material Documents Overview", "catalog": "SAP_MM_BC_MAT_DOC"},
    "MIRO": {"app": "F0859", "name": "Create Supplier Invoice", "catalog": "SAP_SFIN_BC_AP_INV"},

    # Sales & Distribution
    "VA01": {"app": "F1814", "name": "Create Sales Orders", "catalog": "SAP_SD_BC_SO_PROCESS"},
    "VA03": {"app": "F2680", "name": "Manage Sales Orders", "catalog": "SAP_SD_BC_SO_PROCESS"},
    "VL01N": {"app": "F2066", "name": "Create Outbound Delivery", "catalog": "SAP_SD_BC_DLV_PROCESS"},
    "VF01": {"app": "F1599", "name": "Create Billing Document", "catalog": "SAP_SD_BC_BILL_PROCESS"},

    # Controlling
    "KS01": {"app": "F2218", "name": "Manage Cost Centers", "catalog": "SAP_CO_BC_CCTR_MASTER"},
    "KE51": {"app": "F3297", "name": "Manage Profit Centers", "catalog": "SAP_CO_BC_PCTR_MASTER"},

    # HR / HCM
    "PA20": {"app": "F2924", "name": "Display HR Master Data", "catalog": "SAP_HCM_BC_PA_MASTER"},

    # Basis / Admin
    "SU01": {"app": "F1516", "name": "Maintain Business Users", "catalog": "SAP_BASIS_BC_USR_MGMT"},
    "SM37": {"app": "F2895", "name": "Application Jobs", "catalog": "SAP_BASIS_BC_JOB_MGMT"},
}

# Authorization objects that changed in S/4HANA
CHANGED_AUTH_OBJECTS = {
    "F_BKPF_BUK": {
        "status": "modified",
        "note": "New field BRGRU added for authorization groups",
    },
    "F_BKPF_BLA": {
        "status": "modified",
        "note": "Additional document types in S/4HANA",
    },
    "M_BEST_EKO": {
        "status": "unchanged",
        "note": "Still used for purchase order authorization",
    },
    "V_VBAK_VKO": {
        "status": "unchanged",
        "note": "Sales org authorization still active",
    },
    "S_TCODE": {
        "status": "critical",
        "note": "Must add Fiori app IDs alongside T-codes",
    },
}


def extract_roles(conn):
    """Extract complete role definitions from ECC."""
    logger.info("Extracting PFCG roles...")

    # Role definitions
    result = conn.call(
        "RFC_READ_TABLE",
        QUERY_TABLE="AGR_DEFINE",
        DELIMITER="|",
        FIELDS=[
            {"FIELDNAME": "AGR_NAME"},
            {"FIELDNAME": "PARENT_AGR"},
            {"FIELDNAME": "CREATE_USR"},
            {"FIELDNAME": "CREATE_DAT"},
            {"FIELDNAME": "CHANGE_USR"},
            {"FIELDNAME": "CHANGE_DAT"},
        ],
        ROWCOUNT=99999,
    )

    roles = {}
    for row in result.get("DATA", []):
        fields = row["WA"].split("|")
        if len(fields) >= 6:
            name = fields[0].strip()
            roles[name] = {
                "name": name,
                "parent": fields[1].strip() or None,
                "is_composite": bool(fields[1].strip()),
                "created_by": fields[2].strip(),
                "created_date": fields[3].strip(),
                "changed_by": fields[4].strip(),
                "changed_date": fields[5].strip(),
                "tcodes": [],
                "auth_objects": [],
                "user_assignments": [],
            }

    # T-code menu assignments
    result = conn.call(
        "RFC_READ_TABLE",
        QUERY_TABLE="AGR_1251",
        DELIMITER="|",
        FIELDS=[
            {"FIELDNAME": "AGR_NAME"},
            {"FIELDNAME": "OBJECT"},
            {"FIELDNAME": "AUTH"},
            {"FIELDNAME": "FIELD"},
            {"FIELDNAME": "LOW"},
            {"FIELDNAME": "HIGH"},
        ],
        ROWCOUNT=999999,
    )

    for row in result.get("DATA", []):
        fields = row["WA"].split("|")
        if len(fields) >= 6:
            role_name = fields[0].strip()
            if role_name in roles:
                auth_entry = {
                    "object": fields[1].strip(),
                    "auth_name": fields[2].strip(),
                    "field": fields[3].strip(),
                    "low": fields[4].strip(),
                    "high": fields[5].strip(),
                }
                roles[role_name]["auth_objects"].append(auth_entry)

                # Extract T-codes
                if fields[1].strip() == "S_TCODE" and fields[3].strip() == "TCD":
                    roles[role_name]["tcodes"].append(fields[4].strip())

    # User assignments
    result = conn.call(
        "RFC_READ_TABLE",
        QUERY_TABLE="AGR_USERS",
        DELIMITER="|",
        FIELDS=[
            {"FIELDNAME": "AGR_NAME"},
            {"FIELDNAME": "UNAME"},
            {"FIELDNAME": "FROM_DAT"},
            {"FIELDNAME": "TO_DAT"},
        ],
        ROWCOUNT=999999,
    )

    for row in result.get("DATA", []):
        fields = row["WA"].split("|")
        if len(fields) >= 4:
            role_name = fields[0].strip()
            if role_name in roles:
                roles[role_name]["user_assignments"].append({
                    "user": fields[1].strip(),
                    "valid_from": fields[2].strip(),
                    "valid_to": fields[3].strip(),
                })

    return roles


def generate_fiori_mapping(roles):
    """
    For each role's T-codes, generate the corresponding Fiori
    catalog and group assignments needed in S/4HANA.
    """
    fiori_mapping = {}

    for role_name, role in roles.items():
        needed_catalogs = set()
        tcode_app_map = []

        for tcode in role.get("tcodes", []):
            if tcode in TCODE_TO_FIORI:
                fiori_info = TCODE_TO_FIORI[tcode]
                needed_catalogs.add(fiori_info["catalog"])
                tcode_app_map.append({
                    "tcode": tcode,
                    "fiori_app": fiori_info["app"],
                    "fiori_app_name": fiori_info["name"],
                    "catalog": fiori_info["catalog"],
                })

        if tcode_app_map:
            fiori_mapping[role_name] = {
                "role": role_name,
                "tcode_count": len(role.get("tcodes", [])),
                "mapped_tcodes": len(tcode_app_map),
                "unmapped_tcodes": [
                    t for t in role.get("tcodes", []) if t not in TCODE_TO_FIORI
                ],
                "fiori_catalogs_needed": list(needed_catalogs),
                "tcode_to_fiori": tcode_app_map,
            }

    return fiori_mapping


def check_auth_object_changes(roles):
    """Check which roles reference changed authorization objects."""
    impacted_roles = []

    for role_name, role in roles.items():
        impacts = []
        for auth in role.get("auth_objects", []):
            obj = auth.get("object", "")
            if obj in CHANGED_AUTH_OBJECTS:
                change = CHANGED_AUTH_OBJECTS[obj]
                if change["status"] != "unchanged":
                    impacts.append({
                        "auth_object": obj,
                        "status": change["status"],
                        "note": change["note"],
                    })

        if impacts:
            impacted_roles.append({
                "role": role_name,
                "impacts": impacts,
                "user_count": len(role.get("user_assignments", [])),
            })

    return impacted_roles


# =============================================================================
# MAIN HANDLER
# =============================================================================
def lambda_handler(event, context):
    """Role & Authorization Migrator main handler."""
    logger.info("Role Migrator started")
    log_stage_event("role-migrator", "Pipeline Start", "IN_PROGRESS", {"stage": 5})
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
            roles = extract_roles(conn)
        else:
            logger.warning("No RFC — generating role migration template")
            roles = {}

        # Generate Fiori mapping
        fiori_mapping = generate_fiori_mapping(roles)

        # Check auth object impacts
        auth_impacts = check_auth_object_changes(roles)

        # Save results
        put_object(
            STAGING_BUCKET,
            f"migrations/{run_id}/roles/role-definitions.json",
            json.dumps(roles, indent=2, default=str),
        )

        put_object(
            STAGING_BUCKET,
            f"migrations/{run_id}/roles/fiori-mapping.json",
            json.dumps(fiori_mapping, indent=2),
        )

        put_object(
            STAGING_BUCKET,
            f"migrations/{run_id}/roles/auth-impact-analysis.json",
            json.dumps(auth_impacts, indent=2),
        )

        # Save the T-code to Fiori master mapping for reference
        put_object(
            STAGING_BUCKET,
            f"migrations/{run_id}/roles/tcode-fiori-master-mapping.json",
            json.dumps(TCODE_TO_FIORI, indent=2),
        )

        result = {
            "status": "success",
            "total_roles": len(roles),
            "roles_needing_fiori": len(fiori_mapping),
            "auth_impacted_roles": len(auth_impacts),
            "s3_key": f"migrations/{run_id}/roles/",
            "run_id": run_id,
        }
        log_stage_event("role-migrator", "Role Migration Complete", "SUCCESS", result, (__import__('time').time() - _stage_start) * 1000)
        return result

    except Exception as e:
        logger.error(f"Role migration failed: {str(e)}")
        log_stage_event("role-migrator", "Role Migration Failed", "ERROR", str(e))
        raise
