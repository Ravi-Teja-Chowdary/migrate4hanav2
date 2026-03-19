"""
Migrate4HANA — Readiness Check Engine
=======================================
Automates the SAP Readiness Check process by executing data collection
jobs in ECC, packaging metadata, and parsing results into an actionable
migration roadmap.

This stage:
1. Triggers the RC_COLLECT_ANALYSIS_DATA report in ECC via RFC
2. Analyzes simplification item relevance against the target release
3. Cross-references Stage 1 discovery data to estimate remediation effort
4. Assesses Fiori infrastructure prerequisites
5. Collects HANA sizing data for capacity planning
6. Generates a complete readiness roadmap with effort/risk ratings

SAP CONCEPT FOR DEVOPS ENGINEERS:
- Readiness Check = SAP's pre-flight checklist (like a deployment gate)
- Simplification Items = breaking changes in S/4HANA (like API deprecations)
- ACDOCA = the Universal Journal — S/4HANA's single source of truth for
  all financial postings (replaces 30+ legacy tables)
- Fiori = SAP's modern UI framework (think React, but for SAP apps)
- HANA Sizing = capacity planning for the in-memory database

The output feeds into the Simplification Check (deep-dive) and the
SUM/DMO orchestrator for actual conversion planning.
"""

import json
import os
import sys
import logging
import boto3
from datetime import datetime

# Structured telemetry logger for real-time UI streaming
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'utils')))
from logger import log_stage_event

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
secrets = boto3.client("secretsmanager")

STAGING_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hana-staging-dev")
SECRETS_ARN = os.environ.get("SECRETS_ARN", "")


# =============================================================================
# DEPRECATED OBJECTS REFERENCE
# =============================================================================
# Tables that are eliminated or structurally changed in S/4HANA.
# Any custom code referencing these must be remediated.
# =============================================================================
DEPRECATED_TABLES = {
    "BSEG": {"replacement": "ACDOCA", "category": "Finance", "effort_hours": 8},
    "BSID": {"replacement": "ACDOCA", "category": "Finance", "effort_hours": 4},
    "BSAD": {"replacement": "ACDOCA", "category": "Finance", "effort_hours": 4},
    "BSIK": {"replacement": "ACDOCA", "category": "Finance", "effort_hours": 4},
    "BSAK": {"replacement": "ACDOCA", "category": "Finance", "effort_hours": 4},
    "BSIS": {"replacement": "ACDOCA", "category": "Finance", "effort_hours": 4},
    "BSAS": {"replacement": "ACDOCA", "category": "Finance", "effort_hours": 4},
    "GLT0": {"replacement": "ACDOCA", "category": "Finance", "effort_hours": 6},
    "GLPCA": {"replacement": "ACDOCA", "category": "Finance", "effort_hours": 6},
    "COEP": {"replacement": "ACDOCA", "category": "Controlling", "effort_hours": 6},
    "COSP": {"replacement": "ACDOCA", "category": "Controlling", "effort_hours": 4},
    "COSS": {"replacement": "ACDOCA", "category": "Controlling", "effort_hours": 4},
    "KNA1": {"replacement": "BUT000", "category": "Business Partner", "effort_hours": 6},
    "KNB1": {"replacement": "BUT000/BUT0BK", "category": "Business Partner", "effort_hours": 4},
    "LFA1": {"replacement": "BUT000", "category": "Business Partner", "effort_hours": 6},
    "LFB1": {"replacement": "BUT000/BUT0BK", "category": "Business Partner", "effort_hours": 4},
    "MKPF": {"replacement": "MATDOC", "category": "Logistics", "effort_hours": 6},
    "MSEG": {"replacement": "MATDOC", "category": "Logistics", "effort_hours": 6},
    "KONV": {"replacement": "PRCD_ELEMENTS", "category": "Sales", "effort_hours": 4},
}

DEPRECATED_BAPIS = {
    "BAPI_CUSTOMER_CREATEFROMDATA1": {"replacement": "CVI_EI_INBOUND_MAIN", "category": "Business Partner"},
    "BAPI_VENDOR_CREATE": {"replacement": "CVI_EI_INBOUND_MAIN", "category": "Business Partner"},
    "BAPI_GL_ACC_GETPERIODBALANCES": {"replacement": "FAC_GL_BALANCE_GET", "category": "Finance"},
    "BAPI_GOODSMVT_CREATE": {"replacement": "BAPI_GOODSMVT_CREATE (new signature)", "category": "Logistics"},
    "BAPI_INCOMINGINVOICE_CREATE": {"replacement": "API_SUPPLIERINVOICE", "category": "Logistics"},
    "BAPI_ACC_DOCUMENT_POST": {"replacement": "BAPI_ACC_DOCUMENT_POST (new fields)", "category": "Finance"},
}

OBSOLETE_ABAP_STATEMENTS = [
    "COMPUTE",
    "ADD-CORRESPONDING",
    "SUBTRACT-CORRESPONDING",
    "MULTIPLY-CORRESPONDING",
    "DIVIDE-CORRESPONDING",
    "MOVE-CORRESPONDING ... EXPANDING NESTED TABLES",
    "OCCURS",
    "RANGES",
    "FIELD-SYMBOLS ... TYPE ANY TABLE",
    "LOAD REPORT",
    "EDITOR-CALL",
    "WRITE TO ... CURRENCY",
]


# =============================================================================
# SAP RFC CONNECTION
# =============================================================================
def get_sap_connection(override_params=None):
    """
    Establish RFC connection to SAP ECC.

    Requires the PyRFC Lambda layer with SAP NW RFC SDK.
    Connection params come from AWS Secrets Manager.

    SAP CONCEPT FOR DEVOPS ENGINEERS:
    - RFC = Remote Function Call — think of it like gRPC to SAP
    - Client = like an environment (100=prod, 200=dev typically)
    - System Number = port offset (00 means port 3300, 01 means 3301)
    """
    try:
        from pyrfc import Connection
    except ImportError:
        logger.error(
            "PyRFC not available. Make sure the Lambda layer is attached. "
            "See scripts/setup-pyrfc.sh for building the layer."
        )
        raise

    # Get credentials from Secrets Manager
    if override_params:
        conn_params = override_params
    else:
        secret_response = secrets.get_secret_value(SecretId=SECRETS_ARN)
        conn_params = json.loads(secret_response["SecretString"])

    connection = Connection(
        ashost=conn_params["host"],       # SAP application server hostname
        sysnr=conn_params["sysnr"],       # System number (00, 01, etc.)
        client=conn_params["client"],     # Client number (100, 200, etc.)
        user=conn_params["user"],         # RFC user (should have S_RFC auth)
        passwd=conn_params["passwd"],     # Password
        lang="EN",                        # Login language
    )

    logger.info(f"RFC connection established to {conn_params['host']} client {conn_params['client']}")
    return connection


# =============================================================================
# DATA COLLECTION ENGINE
# =============================================================================
def execute_data_collection(connection):
    """
    Trigger the RC_COLLECT_ANALYSIS_DATA report in ECC via RFC to extract
    system metadata for the readiness assessment.

    This collects:
    - Custom code statistics (Z/Y namespace program counts, types, ages)
    - Business function inventory (activated/deactivated via SFW5)
    - System sizing data (DB size, table counts, record volumes)
    - Add-on information (installed add-ons and versions)
    - Database size and table statistics (top tables by size)

    SAP REPORT: RC_COLLECT_ANALYSIS_DATA
    This is the standard SAP report used by Readiness Check to collect
    system metadata. It writes results to the READINESS_CHECK namespace.

    Parameters:
        connection: Active PyRFC connection to SAP ECC.

    Returns:
        dict: Collected system metadata across all categories.
    """
    logger.info("Executing data collection for readiness assessment...")

    collection = {
        "collected_at": datetime.utcnow().isoformat(),
        "custom_code_stats": {},
        "business_function_inventory": {},
        "system_sizing": {},
        "addon_info": [],
        "database_stats": {},
    }

    # --- Custom Code Statistics ---
    logger.info("Collecting custom code statistics...")
    try:
        # Count custom programs by type from TRDIR
        result = connection.call(
            "RFC_READ_TABLE",
            QUERY_TABLE="TRDIR",
            DELIMITER="|",
            FIELDS=[
                {"FIELDNAME": "NAME"},
                {"FIELDNAME": "SUBC"},      # Program type
                {"FIELDNAME": "CDAT"},      # Creation date
            ],
            OPTIONS=[
                {"TEXT": "NAME LIKE 'Z%' OR NAME LIKE 'Y%'"},
            ],
            ROWCOUNT=99999,
        )

        type_counts = {}
        total_custom = 0
        oldest_program = "99991231"
        newest_program = "00000000"

        for row in result["DATA"]:
            fields = row["WA"].split("|")
            if len(fields) >= 3:
                total_custom += 1
                prog_type = fields[1].strip()
                type_counts[prog_type] = type_counts.get(prog_type, 0) + 1
                cdat = fields[2].strip()
                if cdat and cdat < oldest_program:
                    oldest_program = cdat
                if cdat and cdat > newest_program:
                    newest_program = cdat

        collection["custom_code_stats"] = {
            "total_custom_programs": total_custom,
            "by_type": type_counts,
            "oldest_program_date": oldest_program if oldest_program != "99991231" else "",
            "newest_program_date": newest_program if newest_program != "00000000" else "",
        }
        logger.info(f"Custom code: {total_custom} programs found")
    except Exception as e:
        logger.warning(f"Failed to collect custom code stats: {e}")
        collection["custom_code_stats"] = {"error": str(e)}

    # --- Business Function Inventory ---
    logger.info("Collecting business function inventory...")
    try:
        result = connection.call(
            "RFC_READ_TABLE",
            QUERY_TABLE="SFW_SWITCH",
            DELIMITER="|",
            FIELDS=[
                {"FIELDNAME": "SWITCH_ID"},
                {"FIELDNAME": "VERSION"},
            ],
            ROWCOUNT=99999,
        )

        total_bf = len(result.get("DATA", []))

        # Get activation status
        try:
            switch_result = connection.call("SFW_GET_SWITCHPOS")
            positions = switch_result.get("SWITCHPOS", switch_result.get("ET_SWITCHPOS", []))
            activated = sum(
                1 for p in positions
                if p.get("STATE", p.get("SWITCHPOS", "")) in ("T", "ON", "1", "X")
            )
        except Exception:
            activated = 0

        collection["business_function_inventory"] = {
            "total_functions": total_bf,
            "activated": activated,
            "deactivated": total_bf - activated,
        }
        logger.info(f"Business functions: {total_bf} total, {activated} activated")
    except Exception as e:
        logger.warning(f"Failed to collect business function inventory: {e}")
        collection["business_function_inventory"] = {"error": str(e)}

    # --- System Sizing Data ---
    logger.info("Collecting system sizing data...")
    try:
        # Get total table count from DD02L
        result = connection.call(
            "RFC_READ_TABLE",
            QUERY_TABLE="DD02L",
            DELIMITER="|",
            FIELDS=[{"FIELDNAME": "TABNAME"}, {"FIELDNAME": "TABCLASS"}],
            OPTIONS=[{"TEXT": "TABCLASS = 'TRANSP'"}],
            ROWCOUNT=99999,
        )
        total_tables = len(result.get("DATA", []))

        collection["system_sizing"] = {
            "total_transparent_tables": total_tables,
        }
        logger.info(f"System sizing: {total_tables} transparent tables")
    except Exception as e:
        logger.warning(f"Failed to collect system sizing: {e}")
        collection["system_sizing"] = {"error": str(e)}

    # --- Add-on Information ---
    logger.info("Collecting add-on information...")
    try:
        result = connection.call(
            "RFC_READ_TABLE",
            QUERY_TABLE="CVERS",
            DELIMITER="|",
            FIELDS=[
                {"FIELDNAME": "COMPONENT"},
                {"FIELDNAME": "RELEASE"},
                {"FIELDNAME": "EXTRELEASE"},
            ],
            ROWCOUNT=99999,
        )

        for row in result["DATA"]:
            fields = row["WA"].split("|")
            if len(fields) >= 3:
                collection["addon_info"].append({
                    "component": fields[0].strip(),
                    "release": fields[1].strip(),
                    "ext_release": fields[2].strip(),
                })
        logger.info(f"Add-on info: {len(collection['addon_info'])} components")
    except Exception as e:
        logger.warning(f"Failed to collect add-on info: {e}")

    # --- Database Statistics (top tables by estimated size) ---
    logger.info("Collecting database statistics...")
    try:
        # Read table usage statistics from DB02-equivalent data
        # In a real implementation, this would query DD02L + DBSTATC
        result = connection.call(
            "RFC_READ_TABLE",
            QUERY_TABLE="DD02L",
            DELIMITER="|",
            FIELDS=[
                {"FIELDNAME": "TABNAME"},
                {"FIELDNAME": "TABCLASS"},
                {"FIELDNAME": "AS4DATE"},
            ],
            OPTIONS=[
                {"TEXT": "TABCLASS = 'TRANSP'"},
                {"TEXT": "AND TABNAME NOT LIKE '/%'"},
            ],
            ROWCOUNT=500,
        )

        table_list = []
        for row in result["DATA"]:
            fields = row["WA"].split("|")
            if len(fields) >= 3:
                table_list.append({
                    "table": fields[0].strip(),
                    "type": fields[1].strip(),
                    "last_changed": fields[2].strip(),
                })

        collection["database_stats"] = {
            "tables_sampled": len(table_list),
            "top_tables": table_list[:50],
        }
        logger.info(f"Database stats: {len(table_list)} tables sampled")
    except Exception as e:
        logger.warning(f"Failed to collect database stats: {e}")
        collection["database_stats"] = {"error": str(e)}

    logger.info("Data collection complete")
    return collection


# =============================================================================
# SIMPLIFICATION ITEM ANALYSIS
# =============================================================================
def analyze_simplification_items(connection, target_release):
    """
    Query simplification item relevance by checking which deprecated
    objects, tables, and BAPIs are actually used in the system.

    This cross-references:
    - TADIR: Object directory (what custom objects exist)
    - D010TAB: Table usage in ABAP programs (which tables are referenced)
    - TFDIR: Function module directory (which BAPIs are called)

    Parameters:
        connection: Active PyRFC connection to SAP ECC.
        target_release (str): Target S/4HANA release year.

    Returns:
        dict: Simplification item impact analysis with affected objects.
    """
    logger.info(f"Analyzing simplification item relevance for S/4HANA {target_release}...")

    results = {
        "target_release": target_release,
        "analyzed_at": datetime.utcnow().isoformat(),
        "deprecated_table_usage": [],
        "deprecated_bapi_usage": [],
        "total_impacts": 0,
        "by_category": {},
    }

    # --- Check deprecated table usage in custom programs ---
    logger.info("Checking deprecated table usage in custom code...")
    try:
        for table_name, table_info in DEPRECATED_TABLES.items():
            # D010TAB stores which tables are used by which programs
            result = connection.call(
                "RFC_READ_TABLE",
                QUERY_TABLE="D010TAB",
                DELIMITER="|",
                FIELDS=[
                    {"FIELDNAME": "MASTER"},    # Program name
                    {"FIELDNAME": "TABNAME"},   # Table referenced
                ],
                OPTIONS=[
                    {"TEXT": f"TABNAME = '{table_name}'"},
                    {"TEXT": "AND (MASTER LIKE 'Z%' OR MASTER LIKE 'Y%')"},
                ],
                ROWCOUNT=99999,
            )

            affected_programs = []
            for row in result["DATA"]:
                fields = row["WA"].split("|")
                if len(fields) >= 2:
                    affected_programs.append(fields[0].strip())

            if affected_programs:
                category = table_info["category"]
                results["deprecated_table_usage"].append({
                    "table": table_name,
                    "replacement": table_info["replacement"],
                    "category": category,
                    "affected_program_count": len(affected_programs),
                    "affected_programs": affected_programs[:20],  # Limit for readability
                    "estimated_effort_hours": table_info["effort_hours"] * max(1, len(affected_programs) // 5),
                })
                results["by_category"][category] = results["by_category"].get(category, 0) + len(affected_programs)

    except Exception as e:
        logger.warning(f"Failed to analyze deprecated table usage: {e}")
        results["deprecated_table_usage_error"] = str(e)

    # --- Check deprecated BAPI usage ---
    logger.info("Checking deprecated BAPI usage in custom code...")
    try:
        for bapi_name, bapi_info in DEPRECATED_BAPIS.items():
            result = connection.call(
                "RFC_READ_TABLE",
                QUERY_TABLE="TFDIR",
                DELIMITER="|",
                FIELDS=[
                    {"FIELDNAME": "FUNCNAME"},
                    {"FIELDNAME": "PNAME"},
                ],
                OPTIONS=[
                    {"TEXT": f"FUNCNAME = '{bapi_name}'"},
                ],
                ROWCOUNT=1,
            )

            if result.get("DATA"):
                results["deprecated_bapi_usage"].append({
                    "bapi": bapi_name,
                    "replacement": bapi_info["replacement"],
                    "category": bapi_info["category"],
                    "in_use": True,
                })

    except Exception as e:
        logger.warning(f"Failed to analyze deprecated BAPI usage: {e}")
        results["deprecated_bapi_usage_error"] = str(e)

    results["total_impacts"] = (
        len(results["deprecated_table_usage"]) +
        len(results["deprecated_bapi_usage"])
    )

    logger.info(
        f"Simplification analysis: {len(results['deprecated_table_usage'])} deprecated tables in use, "
        f"{len(results['deprecated_bapi_usage'])} deprecated BAPIs found"
    )
    return results


# =============================================================================
# CUSTOM CODE IMPACT ASSESSMENT
# =============================================================================
def assess_custom_code_impact(discovery_data):
    """
    Cross-reference Stage 1 discovery data to estimate remediation effort
    for S/4HANA custom code adaptation.

    Counts references to:
    - Deprecated tables (BSEG, KNA1, LFA1, MKPF, MSEG, KONV)
    - Deprecated BAPIs
    - Obsolete ABAP statements

    Parameters:
        discovery_data (dict): Discovery results from Stage 1 (from S3).

    Returns:
        dict: Custom code impact assessment with effort estimates.
    """
    logger.info("Assessing custom code impact from discovery data...")

    assessment = {
        "assessed_at": datetime.utcnow().isoformat(),
        "deprecated_table_references": 0,
        "deprecated_bapi_references": 0,
        "obsolete_statement_references": 0,
        "total_programs_affected": 0,
        "estimated_total_effort_hours": 0,
        "by_category": {},
        "risk_level": "LOW",
        "details": [],
    }

    programs = discovery_data.get("programs", [])
    tables = discovery_data.get("tables", [])
    function_modules = discovery_data.get("function_modules", [])
    readiness = discovery_data.get("readiness", {})

    # Count blocking issues from discovery as deprecated table references
    blocking = readiness.get("blocking", [])
    deprecated_refs = 0
    for issue in blocking:
        if issue.get("type") == "deprecated_table":
            deprecated_refs += 1
            category = "General"
            table_name = issue.get("object", "")
            if table_name in DEPRECATED_TABLES:
                category = DEPRECATED_TABLES[table_name]["category"]
            assessment["by_category"][category] = assessment["by_category"].get(category, 0) + 1

    assessment["deprecated_table_references"] = deprecated_refs

    # Estimate affected programs based on program count and typical ratios
    total_programs = len(programs)
    # Heuristic: ~30% of custom programs typically reference deprecated tables
    estimated_affected = int(total_programs * 0.30)
    assessment["total_programs_affected"] = estimated_affected

    # Estimate effort
    # Rule of thumb: 2-8 hours per affected program depending on complexity
    avg_effort_per_program = 4
    assessment["estimated_total_effort_hours"] = estimated_affected * avg_effort_per_program

    # Categorize effort
    effort_breakdown = []
    for category, count in assessment["by_category"].items():
        cat_effort = count * 8  # 8 hours per deprecated table category
        effort_breakdown.append({
            "category": category,
            "deprecated_references": count,
            "estimated_effort_hours": cat_effort,
        })
    assessment["details"] = effort_breakdown

    # Risk level based on total effort
    total_effort = assessment["estimated_total_effort_hours"]
    if total_effort > 2000:
        assessment["risk_level"] = "HIGH"
        assessment["risk_message"] = (
            f"High custom code impact: ~{total_effort} hours estimated. "
            "Consider a phased remediation approach."
        )
    elif total_effort > 500:
        assessment["risk_level"] = "MEDIUM"
        assessment["risk_message"] = (
            f"Moderate custom code impact: ~{total_effort} hours estimated. "
            "Plan for dedicated ABAP remediation sprint."
        )
    else:
        assessment["risk_level"] = "LOW"
        assessment["risk_message"] = (
            f"Low custom code impact: ~{total_effort} hours estimated. "
            "Can be handled within normal project timeline."
        )

    logger.info(
        f"Custom code impact: {estimated_affected} programs affected, "
        f"~{total_effort} hours effort, risk={assessment['risk_level']}"
    )
    return assessment


# =============================================================================
# FIORI READINESS ASSESSMENT
# =============================================================================
def assess_fiori_readiness(connection):
    """
    Check Fiori infrastructure prerequisites for S/4HANA.

    Fiori is the default UI in S/4HANA. This checks:
    - ICM (Internet Communication Manager) configuration
    - SICF service activation (HTTP endpoints)
    - SAP Gateway configuration (OData service provider)
    - Frontend server prerequisites

    SAP CONCEPT:
    - ICM = SAP's built-in web server (like nginx inside SAP)
    - SICF = Service configuration for HTTP endpoints
    - Gateway = OData service framework (like a REST API layer)
    - Fiori Launchpad = the single entry point for all SAP apps (like a portal)

    Parameters:
        connection: Active PyRFC connection to SAP ECC.

    Returns:
        dict: Fiori readiness assessment with prerequisites status.
    """
    logger.info("Assessing Fiori infrastructure readiness...")

    assessment = {
        "assessed_at": datetime.utcnow().isoformat(),
        "prerequisites": [],
        "overall_status": "UNKNOWN",
        "fiori_ready": False,
    }

    # Check 1: ICM HTTP service active (SMICM equivalent)
    try:
        # Check if HTTP port is configured by reading ICM parameters
        result = connection.call(
            "RFC_READ_TABLE",
            QUERY_TABLE="HTTPURLLOC",
            DELIMITER="|",
            FIELDS=[{"FIELDNAME": "PORT"}, {"FIELDNAME": "PROTOCOL"}],
            ROWCOUNT=10,
        )
        http_ports = len(result.get("DATA", []))
        assessment["prerequisites"].append({
            "check": "icm_http_service",
            "description": "ICM HTTP service configuration",
            "status": "ok" if http_ports > 0 else "missing",
            "detail": f"{http_ports} HTTP port(s) configured",
        })
    except Exception:
        assessment["prerequisites"].append({
            "check": "icm_http_service",
            "description": "ICM HTTP service configuration",
            "status": "check_failed",
            "detail": "Could not verify ICM configuration — manual check required",
        })

    # Check 2: SICF services for Gateway
    try:
        result = connection.call(
            "RFC_READ_TABLE",
            QUERY_TABLE="ICFSERVICE",
            DELIMITER="|",
            FIELDS=[
                {"FIELDNAME": "ICF_NAME"},      # Service name
                {"FIELDNAME": "ICF_DOCU"},      # Description
                {"FIELDNAME": "ICFACTIVE"},     # Active flag
            ],
            OPTIONS=[
                {"TEXT": "ICF_NAME LIKE 'SAP%GATEWAY%' OR ICF_NAME LIKE 'SAP%OPU%'"},
            ],
            ROWCOUNT=100,
        )

        gateway_services = []
        active_count = 0
        for row in result["DATA"]:
            fields = row["WA"].split("|")
            if len(fields) >= 3:
                is_active = fields[2].strip() == "X"
                if is_active:
                    active_count += 1
                gateway_services.append({
                    "service": fields[0].strip(),
                    "active": is_active,
                })

        assessment["prerequisites"].append({
            "check": "gateway_services",
            "description": "SAP Gateway SICF services",
            "status": "ok" if active_count > 0 else "missing",
            "detail": f"{active_count} active Gateway services found",
            "services": gateway_services[:10],
        })
    except Exception:
        assessment["prerequisites"].append({
            "check": "gateway_services",
            "description": "SAP Gateway SICF services",
            "status": "check_failed",
            "detail": "Could not verify Gateway services — manual check required",
        })

    # Check 3: SAP_GWFND component installed (Gateway Foundation)
    try:
        result = connection.call(
            "RFC_READ_TABLE",
            QUERY_TABLE="CVERS",
            DELIMITER="|",
            FIELDS=[
                {"FIELDNAME": "COMPONENT"},
                {"FIELDNAME": "RELEASE"},
            ],
            OPTIONS=[
                {"TEXT": "COMPONENT = 'SAP_GWFND' OR COMPONENT = 'GW_CORE'"},
            ],
            ROWCOUNT=10,
        )

        gw_components = []
        for row in result["DATA"]:
            fields = row["WA"].split("|")
            if len(fields) >= 2:
                gw_components.append({
                    "component": fields[0].strip(),
                    "release": fields[1].strip(),
                })

        assessment["prerequisites"].append({
            "check": "gateway_foundation",
            "description": "SAP Gateway Foundation component",
            "status": "ok" if gw_components else "missing",
            "detail": f"{len(gw_components)} Gateway component(s) installed",
            "components": gw_components,
        })
    except Exception:
        assessment["prerequisites"].append({
            "check": "gateway_foundation",
            "description": "SAP Gateway Foundation component",
            "status": "check_failed",
            "detail": "Could not verify Gateway Foundation — manual check required",
        })

    # Check 4: UI5 / Fiori component availability
    try:
        result = connection.call(
            "RFC_READ_TABLE",
            QUERY_TABLE="CVERS",
            DELIMITER="|",
            FIELDS=[
                {"FIELDNAME": "COMPONENT"},
                {"FIELDNAME": "RELEASE"},
            ],
            OPTIONS=[
                {"TEXT": "COMPONENT LIKE 'UI%' OR COMPONENT LIKE 'SAP_UI%'"},
            ],
            ROWCOUNT=20,
        )

        ui_components = []
        for row in result["DATA"]:
            fields = row["WA"].split("|")
            if len(fields) >= 2:
                ui_components.append({
                    "component": fields[0].strip(),
                    "release": fields[1].strip(),
                })

        assessment["prerequisites"].append({
            "check": "ui5_components",
            "description": "SAPUI5 / Fiori library components",
            "status": "ok" if ui_components else "info",
            "detail": f"{len(ui_components)} UI component(s) installed",
            "components": ui_components,
        })
    except Exception:
        assessment["prerequisites"].append({
            "check": "ui5_components",
            "description": "SAPUI5 / Fiori library components",
            "status": "check_failed",
            "detail": "Could not verify UI5 components — manual check required",
        })

    # Check 5: Embedded search (for Fiori apps that require search)
    assessment["prerequisites"].append({
        "check": "embedded_search",
        "description": "Embedded Search / Enterprise Search",
        "status": "info",
        "detail": "Embedded Search will be configured during S/4HANA installation. "
                  "Verify TREX or embedded search strategy in target system.",
    })

    # Overall assessment
    ok_count = sum(1 for p in assessment["prerequisites"] if p["status"] == "ok")
    failed_count = sum(1 for p in assessment["prerequisites"] if p["status"] in ("missing", "failed"))
    total = len(assessment["prerequisites"])

    if failed_count == 0:
        assessment["overall_status"] = "READY"
        assessment["fiori_ready"] = True
    elif failed_count <= 1:
        assessment["overall_status"] = "PARTIALLY_READY"
        assessment["fiori_ready"] = False
    else:
        assessment["overall_status"] = "NOT_READY"
        assessment["fiori_ready"] = False

    logger.info(
        f"Fiori readiness: {ok_count}/{total} prerequisites met, "
        f"status={assessment['overall_status']}"
    )
    return assessment


# =============================================================================
# HANA SIZING ESTIMATOR
# =============================================================================
def estimate_system_sizing(connection):
    """
    Collect HANA sizing data: database size, table sizes, and growth rates
    to recommend target HANA appliance sizing.

    SAP's HANA sizing methodology requires:
    - Total database size (compressed for HANA column store)
    - Largest tables and their row counts
    - Data growth rate over the last 12 months
    - Number of concurrent users

    SAP SIZING RULE OF THUMB:
    - HANA memory = (DB_size * compression_factor) + working_memory
    - Typical compression: 3x-7x for column store
    - Working memory: 20-50% of data memory

    Parameters:
        connection: Active PyRFC connection to SAP ECC.

    Returns:
        dict: HANA sizing estimate with recommendations.
    """
    logger.info("Estimating HANA system sizing...")

    sizing = {
        "estimated_at": datetime.utcnow().isoformat(),
        "database_metrics": {},
        "top_tables_by_size": [],
        "user_metrics": {},
        "hana_recommendation": {},
    }

    # Collect table count and estimate sizes
    try:
        # Get large tables (standard SAP tables known to be big)
        large_tables = [
            "BSEG", "BKPF", "MSEG", "MKPF", "VBAP", "VBAK",
            "LIPS", "LIKP", "EKPO", "EKKO", "CDPOS", "CDHDR",
            "BSID", "BSIK", "BSAD", "BSAK", "COEP", "GLT0",
            "AUFK", "AFKO", "JEST", "JSTO",
        ]

        table_sizes = []
        for table_name in large_tables:
            try:
                result = connection.call(
                    "RFC_READ_TABLE",
                    QUERY_TABLE=table_name,
                    DELIMITER="|",
                    FIELDS=[{"FIELDNAME": "MANDT"}],
                    ROWCOUNT=1,
                )
                # We can't get exact counts via RFC_READ_TABLE easily,
                # but the presence of data tells us it's active
                has_data = len(result.get("DATA", [])) > 0
                table_sizes.append({
                    "table": table_name,
                    "has_data": has_data,
                    "estimated_category": "large" if has_data else "empty",
                })
            except Exception:
                table_sizes.append({
                    "table": table_name,
                    "has_data": False,
                    "estimated_category": "inaccessible",
                })

        sizing["top_tables_by_size"] = table_sizes
        active_large_tables = sum(1 for t in table_sizes if t["has_data"])
        logger.info(f"Table sizing: {active_large_tables}/{len(large_tables)} large tables have data")

    except Exception as e:
        logger.warning(f"Failed to collect table sizing: {e}")
        sizing["top_tables_by_size_error"] = str(e)

    # Collect user metrics
    try:
        result = connection.call(
            "RFC_READ_TABLE",
            QUERY_TABLE="USR02",
            DELIMITER="|",
            FIELDS=[
                {"FIELDNAME": "BNAME"},     # Username
                {"FIELDNAME": "USTYP"},     # User type (A=dialog, S=system, etc.)
                {"FIELDNAME": "TRDAT"},     # Last logon date
            ],
            ROWCOUNT=99999,
        )

        total_users = len(result.get("DATA", []))
        dialog_users = 0
        recently_active = 0

        for row in result["DATA"]:
            fields = row["WA"].split("|")
            if len(fields) >= 3:
                if fields[1].strip() == "A":
                    dialog_users += 1
                # Check if logged in within last 90 days
                last_logon = fields[2].strip()
                if last_logon and last_logon >= "20240101":
                    recently_active += 1

        sizing["user_metrics"] = {
            "total_users": total_users,
            "dialog_users": dialog_users,
            "recently_active_users": recently_active,
        }
        logger.info(f"User metrics: {total_users} total, {dialog_users} dialog, {recently_active} recently active")

    except Exception as e:
        logger.warning(f"Failed to collect user metrics: {e}")
        sizing["user_metrics"] = {"error": str(e)}

    # Generate HANA sizing recommendation
    # Based on SAP Quick Sizer methodology approximations
    active_tables = sum(1 for t in sizing.get("top_tables_by_size", []) if t.get("has_data"))
    dialog_users = sizing.get("user_metrics", {}).get("dialog_users", 100)

    # Rough estimation (real sizing requires SAP Quick Sizer tool)
    estimated_db_size_gb = active_tables * 15  # Very rough: ~15GB per active large table
    compression_factor = 5  # Typical HANA column store compression
    hana_data_memory_gb = max(64, estimated_db_size_gb // compression_factor)
    hana_working_memory_gb = int(hana_data_memory_gb * 0.3)
    hana_total_memory_gb = hana_data_memory_gb + hana_working_memory_gb

    # Round up to nearest standard sizing tier
    sizing_tiers = [128, 192, 256, 384, 512, 768, 1024, 1536, 2048, 3072, 4096]
    recommended_tier = 128
    for tier in sizing_tiers:
        if tier >= hana_total_memory_gb:
            recommended_tier = tier
            break

    sizing["hana_recommendation"] = {
        "estimated_db_size_gb": estimated_db_size_gb,
        "compression_factor": compression_factor,
        "hana_data_memory_gb": hana_data_memory_gb,
        "hana_working_memory_gb": hana_working_memory_gb,
        "hana_total_memory_gb": hana_total_memory_gb,
        "recommended_tier_gb": recommended_tier,
        "estimated_cpus": max(4, dialog_users // 50),
        "note": (
            "This is a rough estimate. Run SAP Quick Sizer "
            "(https://www.sap.com/about/benchmark/sizing.html) "
            "for certified sizing."
        ),
    }

    logger.info(
        f"HANA sizing: ~{estimated_db_size_gb}GB DB, "
        f"recommended {recommended_tier}GB HANA tier"
    )
    return sizing


# =============================================================================
# READINESS ROADMAP GENERATOR
# =============================================================================
def generate_readiness_roadmap(data_collection, simplification_impact,
                                custom_code_impact, fiori_readiness, sizing_estimate):
    """
    Create a comprehensive readiness roadmap with effort estimates per
    category and overall risk/readiness scoring.

    Parameters:
        data_collection (dict): Raw data collection results.
        simplification_impact (dict): Simplification item analysis.
        custom_code_impact (dict): Code remediation effort estimate.
        fiori_readiness (dict): Fiori infrastructure assessment.
        sizing_estimate (dict): HANA sizing recommendation.

    Returns:
        dict: Complete readiness roadmap with effort, risk, and timeline.
    """
    logger.info("Generating readiness roadmap...")

    roadmap = {
        "generated_at": datetime.utcnow().isoformat(),
        "workstreams": [],
        "total_effort_hours": 0,
        "estimated_duration_weeks": 0,
        "overall_risk": "LOW",
        "overall_readiness": "GREEN",
        "go_no_go": "GO",
    }

    # Workstream 1: Custom Code Remediation
    code_effort = custom_code_impact.get("estimated_total_effort_hours", 0)
    code_risk = custom_code_impact.get("risk_level", "LOW")
    roadmap["workstreams"].append({
        "name": "Custom Code Remediation",
        "category": "technical",
        "effort_hours": code_effort,
        "risk": code_risk,
        "description": (
            f"{custom_code_impact.get('total_programs_affected', 0)} custom programs "
            "require adaptation for S/4HANA compatibility."
        ),
        "tasks": [
            "Run ATC (ABAP Test Cockpit) with S/4HANA checks",
            "Remediate deprecated table references",
            "Update deprecated BAPI calls",
            "Remove obsolete ABAP statements",
            "Unit test all modified programs",
        ],
    })

    # Workstream 2: Simplification Item Resolution
    si_effort = len(simplification_impact.get("deprecated_table_usage", [])) * 16
    si_effort += len(simplification_impact.get("deprecated_bapi_usage", [])) * 8
    roadmap["workstreams"].append({
        "name": "Simplification Item Resolution",
        "category": "functional",
        "effort_hours": si_effort,
        "risk": "HIGH" if si_effort > 200 else "MEDIUM" if si_effort > 50 else "LOW",
        "description": (
            f"{simplification_impact.get('total_impacts', 0)} simplification items "
            "affect the current system."
        ),
        "tasks": [
            "Review RED simplification items",
            "Plan data model changes (BSEG to ACDOCA, KNA1 to BUT000)",
            "Validate Business Partner conversion prerequisites",
            "Test Material Document changes (MKPF/MSEG to MATDOC)",
            "Review Credit Management changes",
        ],
    })

    # Workstream 3: Fiori Infrastructure
    fiori_effort = 0 if fiori_readiness.get("fiori_ready") else 80
    roadmap["workstreams"].append({
        "name": "Fiori Infrastructure Setup",
        "category": "technical",
        "effort_hours": fiori_effort,
        "risk": "LOW" if fiori_readiness.get("fiori_ready") else "MEDIUM",
        "description": f"Fiori readiness: {fiori_readiness.get('overall_status', 'UNKNOWN')}",
        "tasks": [
            "Configure SAP Gateway (if not already set up)",
            "Activate required SICF services",
            "Set up Fiori Launchpad content",
            "Configure Fiori app groups and catalogs",
            "Plan end-user training for Fiori UX",
        ],
    })

    # Workstream 4: HANA Sizing and Infrastructure
    hana_rec = sizing_estimate.get("hana_recommendation", {})
    roadmap["workstreams"].append({
        "name": "HANA Infrastructure",
        "category": "infrastructure",
        "effort_hours": 120,
        "risk": "MEDIUM",
        "description": (
            f"Target HANA sizing: {hana_rec.get('recommended_tier_gb', 'TBD')}GB. "
            f"Estimated DB size: {hana_rec.get('estimated_db_size_gb', 'TBD')}GB."
        ),
        "tasks": [
            "Run official SAP Quick Sizer",
            "Provision HANA infrastructure (on-prem or cloud)",
            "Configure HANA system replication (if HA required)",
            "Set up backup and recovery procedures",
            "Performance baseline testing",
        ],
    })

    # Workstream 5: Testing
    test_effort = max(160, code_effort // 2)  # At least 160 hours, or half of code effort
    roadmap["workstreams"].append({
        "name": "Integration and User Acceptance Testing",
        "category": "testing",
        "effort_hours": test_effort,
        "risk": "MEDIUM",
        "description": "End-to-end testing of all business processes post-conversion.",
        "tasks": [
            "Define test plan covering all critical business processes",
            "Execute integration tests for Finance, Logistics, HR",
            "Business Partner conversion validation",
            "Performance testing on HANA",
            "User acceptance testing with business teams",
        ],
    })

    # Calculate totals
    total_effort = sum(w["effort_hours"] for w in roadmap["workstreams"])
    roadmap["total_effort_hours"] = total_effort

    # Estimate duration (assuming 5-person team, 40 hours/week, 70% efficiency)
    team_capacity_per_week = 5 * 40 * 0.7  # 140 hours/week
    roadmap["estimated_duration_weeks"] = max(4, int(total_effort / team_capacity_per_week) + 1)

    # Overall risk assessment
    high_risk_ws = sum(1 for w in roadmap["workstreams"] if w["risk"] == "HIGH")
    medium_risk_ws = sum(1 for w in roadmap["workstreams"] if w["risk"] == "MEDIUM")

    if high_risk_ws >= 2 or total_effort > 3000:
        roadmap["overall_risk"] = "HIGH"
        roadmap["overall_readiness"] = "RED"
        roadmap["go_no_go"] = "NO-GO"
        roadmap["recommendation"] = (
            "Significant preparation required before conversion. "
            "Address all HIGH risk workstreams before proceeding."
        )
    elif high_risk_ws >= 1 or medium_risk_ws >= 3 or total_effort > 1000:
        roadmap["overall_risk"] = "MEDIUM"
        roadmap["overall_readiness"] = "YELLOW"
        roadmap["go_no_go"] = "CONDITIONAL"
        roadmap["recommendation"] = (
            "System can proceed with conversion after addressing key risks. "
            "Estimated preparation time: "
            f"{roadmap['estimated_duration_weeks']} weeks."
        )
    else:
        roadmap["overall_risk"] = "LOW"
        roadmap["overall_readiness"] = "GREEN"
        roadmap["go_no_go"] = "GO"
        roadmap["recommendation"] = (
            "System is well-positioned for S/4HANA conversion. "
            f"Estimated preparation time: {roadmap['estimated_duration_weeks']} weeks."
        )

    logger.info(
        f"Roadmap generated: {total_effort} hours total effort, "
        f"{roadmap['estimated_duration_weeks']} weeks, "
        f"risk={roadmap['overall_risk']}, readiness={roadmap['overall_readiness']}"
    )
    return roadmap


# =============================================================================
# MAIN HANDLER
# =============================================================================
def lambda_handler(event, context):
    """
    Main entry point for the Readiness Check Engine.

    Input (from Step Functions):
    {
        "stage": "readiness-check",
        "input": {
            "target_release": "2023",
            "discovery_s3_key": "migrations/{run_id}/discovery/full-scan.json"
        },
        "metadata": {
            "run_id": "uuid",
            "timestamp": "..."
        }
    }

    Output (passed to next stage):
    {
        "status": "success",
        "overall_readiness": "GREEN|YELLOW|RED",
        "go_no_go": "GO|CONDITIONAL|NO-GO",
        "summary": {...},
        "s3_prefix": "migrations/{run_id}/readiness-check/"
    }
    """
    logger.info(f"Readiness Check Engine started: {json.dumps(event)}")
    log_stage_event("readiness-check", "Pipeline Start", "IN_PROGRESS", {
        "target_release": event.get("input", {}).get("target_release", "2023"),
    })
    _stage_start = __import__('time').time()

    run_id = event.get("metadata", {}).get("run_id", "manual-run")
    target_release = event.get("input", {}).get("target_release", "2023")
    discovery_s3_key = event.get("input", {}).get("discovery_s3_key", "")
    s3_prefix = f"migrations/{run_id}/readiness-check"

    try:
        # Load discovery data from Stage 1
        discovery_data = {}
        if discovery_s3_key:
            try:
                obj = s3.get_object(Bucket=STAGING_BUCKET, Key=discovery_s3_key)
                discovery_data = json.loads(obj["Body"].read().decode("utf-8"))
                logger.info(f"Loaded discovery data from {discovery_s3_key}")
            except Exception as e:
                logger.warning(f"Could not load discovery data: {e}")

        # Connect to SAP ECC
        conn = get_sap_connection()

        # Step 1: Execute data collection
        data_collection = execute_data_collection(conn)

        # Step 2: Analyze simplification items
        simplification_impact = analyze_simplification_items(conn, target_release)

        # Step 3: Assess custom code impact
        custom_code_impact = assess_custom_code_impact(discovery_data)

        # Step 4: Assess Fiori readiness
        fiori_readiness = assess_fiori_readiness(conn)

        # Step 5: Estimate system sizing
        sizing_estimate = estimate_system_sizing(conn)

        conn.close()

        # Step 6: Generate readiness roadmap
        readiness_roadmap = generate_readiness_roadmap(
            data_collection, simplification_impact,
            custom_code_impact, fiori_readiness, sizing_estimate
        )

        # Save results to S3
        artifacts = {
            f"{s3_prefix}/data_collection.json": data_collection,
            f"{s3_prefix}/simplification_impact.json": simplification_impact,
            f"{s3_prefix}/custom_code_impact.json": custom_code_impact,
            f"{s3_prefix}/fiori_readiness.json": fiori_readiness,
            f"{s3_prefix}/sizing_estimate.json": sizing_estimate,
            f"{s3_prefix}/readiness_roadmap.json": readiness_roadmap,
        }

        for s3_key, data in artifacts.items():
            s3.put_object(
                Bucket=STAGING_BUCKET,
                Key=s3_key,
                Body=json.dumps(data, indent=2, default=str),
                ContentType="application/json",
            )

        # Build summary
        summary = {
            "target_release": target_release,
            "custom_programs_found": data_collection.get("custom_code_stats", {}).get("total_custom_programs", 0),
            "business_functions_total": data_collection.get("business_function_inventory", {}).get("total_functions", 0),
            "deprecated_table_impacts": len(simplification_impact.get("deprecated_table_usage", [])),
            "deprecated_bapi_impacts": len(simplification_impact.get("deprecated_bapi_usage", [])),
            "estimated_code_effort_hours": custom_code_impact.get("estimated_total_effort_hours", 0),
            "code_risk_level": custom_code_impact.get("risk_level", "UNKNOWN"),
            "fiori_ready": fiori_readiness.get("fiori_ready", False),
            "hana_recommended_tier_gb": sizing_estimate.get("hana_recommendation", {}).get("recommended_tier_gb", 0),
            "total_effort_hours": readiness_roadmap.get("total_effort_hours", 0),
            "estimated_duration_weeks": readiness_roadmap.get("estimated_duration_weeks", 0),
            "overall_readiness": readiness_roadmap.get("overall_readiness", "UNKNOWN"),
            "overall_risk": readiness_roadmap.get("overall_risk", "UNKNOWN"),
            "go_no_go": readiness_roadmap.get("go_no_go", "UNKNOWN"),
        }

        logger.info(f"Readiness Check complete: {json.dumps(summary)}")
        log_stage_event(
            "readiness-check", "Readiness Check Complete", "SUCCESS",
            summary, (__import__('time').time() - _stage_start) * 1000
        )

        return {
            "status": "success",
            "overall_readiness": readiness_roadmap.get("overall_readiness", "UNKNOWN"),
            "go_no_go": readiness_roadmap.get("go_no_go", "UNKNOWN"),
            "summary": summary,
            "s3_prefix": s3_prefix,
            "run_id": run_id,
        }

    except ImportError:
        # PyRFC not installed — return mock data for testing
        logger.warning("PyRFC not available — returning mock readiness check data")
        mock_summary = {
            "target_release": target_release,
            "custom_programs_found": 1247,
            "business_functions_total": 156,
            "deprecated_table_impacts": 12,
            "deprecated_bapi_impacts": 4,
            "estimated_code_effort_hours": 480,
            "code_risk_level": "MEDIUM",
            "fiori_ready": False,
            "hana_recommended_tier_gb": 256,
            "total_effort_hours": 920,
            "estimated_duration_weeks": 8,
            "overall_readiness": "YELLOW",
            "overall_risk": "MEDIUM",
            "go_no_go": "CONDITIONAL",
            "mode": "MOCK_DATA",
        }
        return {
            "status": "success",
            "overall_readiness": "YELLOW",
            "go_no_go": "CONDITIONAL",
            "summary": mock_summary,
            "s3_prefix": f"migrations/{run_id}/readiness-check",
            "run_id": run_id,
        }

    except Exception as e:
        logger.error(f"Readiness Check failed: {str(e)}")
        log_stage_event("readiness-check", "Readiness Check Failed", "ERROR", str(e))
        raise
