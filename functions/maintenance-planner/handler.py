"""
Migrate4HANA — Maintenance Planner Interface
==============================================
Interface with SAP Maintenance Planner output to prepare the target
system definition for S/4HANA conversion.

This stage:
1. Parses the Maintenance Planner's stack.xml export
2. Validates add-on compatibility against the target S/4HANA release
3. Queries activated business functions (SFW_BROWSER) via RFC
4. Checks software component versions (CVERS) against target requirements
5. Generates a complete target system definition document

SAP CONCEPT FOR DEVOPS ENGINEERS:
- Maintenance Planner = SAP's dependency resolver (think apt/yum for SAP)
- stack.xml = the "lockfile" — exact versions of every component to install
- Add-ons = optional SAP modules (like plugins) that may or may not be
  compatible with the target S/4HANA release
- Business Functions = feature flags inside SAP (activated via SFW5)
- CVERS = the installed software component registry (like rpm -qa)

The output of this stage feeds directly into the SUM/DMO orchestrator
to ensure the correct target stack is applied during conversion.
"""

import json
import os
import sys
import logging
from datetime import datetime

# Structured telemetry logger for real-time UI streaming
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'utils')))
from logger import log_stage_event
from storage_client import put_object, get_object
from secrets_client import get_secret_value

logger = logging.getLogger()
logger.setLevel(logging.INFO)

STAGING_CONTAINER = os.environ.get("AZURE_STORAGE_CONTAINER", "staging")
ECC_SECRET_NAME = os.environ.get("ECC_SECRET_NAME", "sap-ecc-credentials")


# =============================================================================
# ADD-ON COMPATIBILITY MATRIX
# =============================================================================
# Maps common SAP add-ons to their compatibility status per S/4HANA release.
# Status values: "compatible", "restricted", "not_compatible", "replaced"
#
# This matrix is maintained based on SAP Product Availability Matrix (PAM)
# and SAP Note 2269324 (Add-on compatibility for S/4HANA).
# =============================================================================
ADDON_COMPATIBILITY_MATRIX = {
    "IS-OIL": {
        "2021": "compatible",
        "2022": "compatible",
        "2023": "compatible",
        "description": "Industry Solution for Oil & Gas",
        "replacement": None,
    },
    "IS-UT": {
        "2021": "compatible",
        "2022": "compatible",
        "2023": "compatible",
        "description": "Industry Solution for Utilities",
        "replacement": None,
    },
    "IS-RE": {
        "2021": "replaced",
        "2022": "replaced",
        "2023": "replaced",
        "description": "Industry Solution for Real Estate",
        "replacement": "SAP S/4HANA for Real Estate Management",
    },
    "IS-PS": {
        "2021": "compatible",
        "2022": "compatible",
        "2023": "compatible",
        "description": "Industry Solution for Public Sector",
        "replacement": None,
    },
    "IS-H": {
        "2021": "restricted",
        "2022": "restricted",
        "2023": "not_compatible",
        "description": "Industry Solution for Healthcare",
        "replacement": "SAP S/4HANA for Healthcare",
    },
    "IS-MEDIA": {
        "2021": "compatible",
        "2022": "compatible",
        "2023": "compatible",
        "description": "Industry Solution for Media",
        "replacement": None,
    },
    "IS-DFS": {
        "2021": "restricted",
        "2022": "not_compatible",
        "2023": "not_compatible",
        "description": "Industry Solution for Defense & Security",
        "replacement": "SAP S/4HANA for Defense & Security",
    },
    "IS-AD": {
        "2021": "compatible",
        "2022": "compatible",
        "2023": "compatible",
        "description": "Industry Solution for Aerospace & Defense",
        "replacement": None,
    },
    "SEM-BW": {
        "2021": "not_compatible",
        "2022": "not_compatible",
        "2023": "not_compatible",
        "description": "Strategic Enterprise Management BW",
        "replacement": "SAP BW/4HANA or Embedded Analytics",
    },
    "EA-HR": {
        "2021": "restricted",
        "2022": "restricted",
        "2023": "restricted",
        "description": "Enterprise Add-on for HR",
        "replacement": "SAP SuccessFactors or HCM for S/4HANA",
    },
    "EA-APPL": {
        "2021": "compatible",
        "2022": "compatible",
        "2023": "compatible",
        "description": "Enterprise Add-on Applications",
        "replacement": None,
    },
    "EA-FINSERV": {
        "2021": "compatible",
        "2022": "compatible",
        "2023": "compatible",
        "description": "Enterprise Add-on for Financial Services",
        "replacement": None,
    },
    "EA-RETAIL": {
        "2021": "restricted",
        "2022": "restricted",
        "2023": "not_compatible",
        "description": "Enterprise Add-on for Retail",
        "replacement": "SAP S/4HANA for Retail",
    },
    "FSCM": {
        "2021": "compatible",
        "2022": "compatible",
        "2023": "compatible",
        "description": "Financial Supply Chain Management",
        "replacement": None,
    },
    "GRC": {
        "2021": "compatible",
        "2022": "compatible",
        "2023": "compatible",
        "description": "Governance Risk and Compliance",
        "replacement": None,
    },
    "SRM": {
        "2021": "not_compatible",
        "2022": "not_compatible",
        "2023": "not_compatible",
        "description": "Supplier Relationship Management",
        "replacement": "SAP Ariba / SAP S/4HANA Procurement",
    },
    "SCM": {
        "2021": "not_compatible",
        "2022": "not_compatible",
        "2023": "not_compatible",
        "description": "Supply Chain Management",
        "replacement": "SAP IBP / SAP S/4HANA Supply Chain",
    },
    "CRM": {
        "2021": "not_compatible",
        "2022": "not_compatible",
        "2023": "not_compatible",
        "description": "Customer Relationship Management",
        "replacement": "SAP C/4HANA / SAP Sales Cloud",
    },
    "PLM": {
        "2021": "compatible",
        "2022": "compatible",
        "2023": "compatible",
        "description": "Product Lifecycle Management",
        "replacement": None,
    },
    "EWM": {
        "2021": "compatible",
        "2022": "compatible",
        "2023": "compatible",
        "description": "Extended Warehouse Management",
        "replacement": None,
    },
    "TM": {
        "2021": "compatible",
        "2022": "compatible",
        "2023": "compatible",
        "description": "Transportation Management",
        "replacement": None,
    },
    "PPM": {
        "2021": "compatible",
        "2022": "compatible",
        "2023": "compatible",
        "description": "Portfolio and Project Management",
        "replacement": None,
    },
    "MDG": {
        "2021": "compatible",
        "2022": "compatible",
        "2023": "compatible",
        "description": "Master Data Governance",
        "replacement": None,
    },
    "ILM": {
        "2021": "compatible",
        "2022": "compatible",
        "2023": "compatible",
        "description": "Information Lifecycle Management",
        "replacement": None,
    },
}


# =============================================================================
# SAP RFC CONNECTION
# =============================================================================
def get_sap_connection(override_params=None):
    """
    Establish RFC connection to SAP ECC.

    Requires the PyRFC Lambda layer with SAP NW RFC SDK.
    Connection params come from Azure Key Vault.

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

    # Get credentials from Key Vault
    if override_params:
        conn_params = override_params
    else:
        secret_response = get_secret_value(ECC_SECRET_NAME)
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
# STACK.XML PARSER
# =============================================================================
def parse_stack_xml(stack_xml_content):
    """
    Parse the Maintenance Planner's stack.xml file to extract the target
    product definition.

    The stack.xml is generated by SAP Maintenance Planner
    (https://apps.support.sap.com/sap/support/mp) and contains:
    - Target product version (e.g., S/4HANA 2023)
    - Required software components and their exact versions
    - Support package stack levels
    - Kernel version requirements

    Parameters:
        stack_xml_content (str): Raw XML content from the stack.xml file.

    Returns:
        dict: Parsed stack data including product version, components,
              support packages, and kernel requirements.
    """
    logger.info("Parsing stack.xml from Maintenance Planner...")

    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(stack_xml_content)
    except Exception as e:
        logger.error(f"Failed to parse stack.xml: {e}")
        return {
            "parse_status": "error",
            "error": str(e),
            "target_product": None,
            "components": [],
            "support_packages": [],
        }

    stack_data = {
        "parse_status": "success",
        "parsed_at": datetime.utcnow().isoformat(),
        "target_product": None,
        "target_release": None,
        "components": [],
        "support_packages": [],
        "kernel_requirements": {},
        "addon_requirements": [],
        "industry_solutions": [],
    }

    # Extract target product version
    # stack.xml structure: <stack> -> <product> -> <version>
    for product in root.iter("product"):
        stack_data["target_product"] = product.get("name", product.text or "")
        stack_data["target_release"] = product.get("version", product.get("release", ""))

    # If no product tag, try alternative structures
    if not stack_data["target_product"]:
        for target in root.iter("target"):
            stack_data["target_product"] = target.get("product", target.text or "")
            stack_data["target_release"] = target.get("release", target.get("version", ""))

    # Extract software components
    for component in root.iter("component"):
        comp_name = component.get("name", component.get("id", ""))
        comp_version = component.get("version", component.get("release", ""))
        comp_type = component.get("type", "software_component")

        comp_entry = {
            "name": comp_name,
            "version": comp_version,
            "type": comp_type,
            "description": component.get("description", ""),
        }

        # Classify component
        if comp_name.startswith("IS-"):
            stack_data["industry_solutions"].append(comp_entry)
        elif comp_name.startswith("EA-") or comp_name in ADDON_COMPATIBILITY_MATRIX:
            stack_data["addon_requirements"].append(comp_entry)
        else:
            stack_data["components"].append(comp_entry)

    # Extract support packages
    for sp in root.iter("support_package"):
        stack_data["support_packages"].append({
            "name": sp.get("name", sp.get("id", "")),
            "version": sp.get("version", ""),
            "component": sp.get("component", ""),
        })

    # Extract kernel requirements
    for kernel in root.iter("kernel"):
        stack_data["kernel_requirements"] = {
            "version": kernel.get("version", ""),
            "patch_level": kernel.get("patch_level", ""),
            "architecture": kernel.get("arch", "64-bit"),
        }

    logger.info(
        f"Stack.xml parsed: target={stack_data['target_product']} "
        f"release={stack_data['target_release']}, "
        f"{len(stack_data['components'])} components, "
        f"{len(stack_data['addon_requirements'])} add-ons"
    )
    return stack_data


# =============================================================================
# ADD-ON COMPATIBILITY VALIDATOR
# =============================================================================
def validate_addon_compatibility(addons, target_release):
    """
    Check each add-on against the known compatibility matrix for
    S/4HANA releases (2021, 2022, 2023).

    Parameters:
        addons (list): List of add-on dicts with 'name' and 'version' keys,
                       typically from CVERS or stack.xml parsing.
        target_release (str): Target S/4HANA release year (e.g., "2023").

    Returns:
        dict: Compatibility results per add-on with overall assessment.
    """
    logger.info(f"Validating {len(addons)} add-ons against S/4HANA {target_release}...")

    # Normalize release to year format
    release_year = target_release
    for year in ["2023", "2022", "2021"]:
        if year in str(target_release):
            release_year = year
            break

    results = {
        "target_release": target_release,
        "release_year": release_year,
        "total_addons": len(addons),
        "compatible": 0,
        "restricted": 0,
        "not_compatible": 0,
        "replaced": 0,
        "unknown": 0,
        "details": [],
    }

    for addon in addons:
        addon_name = addon.get("name", "").upper().strip()
        addon_version = addon.get("version", "")

        matrix_entry = ADDON_COMPATIBILITY_MATRIX.get(addon_name)

        if matrix_entry:
            status = matrix_entry.get(release_year, "unknown")
            detail = {
                "addon": addon_name,
                "current_version": addon_version,
                "description": matrix_entry.get("description", ""),
                "compatibility": status,
                "replacement": matrix_entry.get("replacement"),
                "action_required": status in ("not_compatible", "replaced", "restricted"),
            }

            if status == "compatible":
                detail["recommendation"] = "No action required — add-on is fully supported."
                results["compatible"] += 1
            elif status == "restricted":
                detail["recommendation"] = (
                    "Restricted compatibility — check SAP Note 2269324 for "
                    "specific limitations and required patches."
                )
                results["restricted"] += 1
            elif status == "not_compatible":
                detail["recommendation"] = (
                    f"Not compatible with S/4HANA {release_year}. "
                    f"Must be removed or replaced before conversion."
                )
                if matrix_entry.get("replacement"):
                    detail["recommendation"] += f" Replacement: {matrix_entry['replacement']}"
                results["not_compatible"] += 1
            elif status == "replaced":
                detail["recommendation"] = (
                    f"Replaced in S/4HANA. Migrate to: {matrix_entry.get('replacement', 'N/A')}"
                )
                results["replaced"] += 1
            else:
                detail["recommendation"] = (
                    "Compatibility unknown for this release — verify manually via SAP PAM."
                )
                results["unknown"] += 1
        else:
            detail = {
                "addon": addon_name,
                "current_version": addon_version,
                "description": addon.get("description", "Unknown add-on"),
                "compatibility": "unknown",
                "replacement": None,
                "action_required": True,
                "recommendation": (
                    "Add-on not found in compatibility matrix. "
                    "Check SAP Product Availability Matrix (PAM) at "
                    "https://userapps.support.sap.com/sap/support/pam"
                ),
            }
            results["unknown"] += 1

        results["details"].append(detail)

    # Overall assessment
    if results["not_compatible"] > 0:
        results["overall_status"] = "BLOCKED"
        results["overall_message"] = (
            f"{results['not_compatible']} incompatible add-on(s) must be resolved "
            "before proceeding with S/4HANA conversion."
        )
    elif results["restricted"] > 0 or results["replaced"] > 0:
        results["overall_status"] = "WARNING"
        results["overall_message"] = (
            f"{results['restricted']} restricted and {results['replaced']} replaced "
            "add-on(s) require review before conversion."
        )
    else:
        results["overall_status"] = "CLEAR"
        results["overall_message"] = "All add-ons are compatible with the target release."

    logger.info(
        f"Add-on compatibility: {results['compatible']} compatible, "
        f"{results['restricted']} restricted, {results['not_compatible']} incompatible, "
        f"{results['replaced']} replaced, {results['unknown']} unknown"
    )
    return results


# =============================================================================
# BUSINESS FUNCTION CHECKER
# =============================================================================
def check_business_functions(connection, target_release):
    """
    Query SFW_BROWSER data via RFC to list activated business functions
    and check their compatibility with the target S/4HANA release.

    SAP CONCEPT:
    - Business Functions are SAP's feature flags — they enable new functionality
    - Once activated, they CANNOT be deactivated (one-way switch)
    - In S/4HANA, many business functions are activated by default
    - Some ECC business functions are obsolete in S/4HANA

    Tables:
        SFW_SWITCH — Business function switch definitions
        SFW_SWITCHPOS — Switch positions (activated/deactivated)

    RFC:
        SFW_GET_SWITCHPOS — Returns current switch positions

    Parameters:
        connection: Active PyRFC connection to SAP ECC.
        target_release (str): Target S/4HANA release year.

    Returns:
        dict: Business function inventory with compatibility status.
    """
    logger.info("Checking business functions via SFW_BROWSER...")

    results = {
        "checked_at": datetime.utcnow().isoformat(),
        "target_release": target_release,
        "total_functions": 0,
        "activated": 0,
        "deactivated": 0,
        "obsolete_in_target": 0,
        "mandatory_in_target": 0,
        "details": [],
    }

    # Known business functions that are obsolete or mandatory in S/4HANA
    s4_mandatory_functions = {
        "LOG_MM_SIT": "Mandatory — Material Document simplification",
        "FIN_GL_CI_1": "Mandatory — New General Ledger",
        "FIN_GL_CI_2": "Mandatory — New GL document splitting",
        "FIN_AA_CI_1": "Mandatory — New Asset Accounting",
        "LOG_PP_CI_1": "Mandatory — Advanced production planning",
        "SD_01": "Mandatory — Simplified SD processes",
        "FIN_CO_COGM": "Mandatory — Cost Object Controlling",
        "CA_BP_CI": "Mandatory — Business Partner approach",
    }

    s4_obsolete_functions = {
        "FIN_GL_CLM": "Obsolete — Classic GL replaced by New GL",
        "FIN_AA_CLM": "Obsolete — Classic Asset Accounting",
        "LOG_MM_MOB": "Obsolete — Classic mobile inventory management",
        "SRM_EHP1": "Obsolete — SRM integration replaced by S/4 Procurement",
        "CRM_EHP1": "Obsolete — CRM integration replaced by C/4HANA",
    }

    # Step 1: Read business function switch definitions from SFW_SWITCH
    try:
        result = connection.call(
            "RFC_READ_TABLE",
            QUERY_TABLE="SFW_SWITCH",
            DELIMITER="|",
            FIELDS=[
                {"FIELDNAME": "SWITCH_ID"},    # Business function ID
                {"FIELDNAME": "AUTHOR"},       # Created by
                {"FIELDNAME": "CREATEDON"},    # Creation date
                {"FIELDNAME": "VERSION"},      # Switch version
            ],
            ROWCOUNT=99999,
        )

        switches = []
        for row in result["DATA"]:
            fields = row["WA"].split("|")
            if len(fields) >= 4:
                switches.append({
                    "switch_id": fields[0].strip(),
                    "author": fields[1].strip(),
                    "created_on": fields[2].strip(),
                    "version": fields[3].strip(),
                })

        logger.info(f"Found {len(switches)} business function switches")
    except Exception as e:
        logger.warning(f"Could not read SFW_SWITCH: {e}")
        switches = []

    # Step 2: Get current switch positions via RFC
    try:
        switch_result = connection.call("SFW_GET_SWITCHPOS")
        switch_positions = {}
        for entry in switch_result.get("SWITCHPOS", switch_result.get("ET_SWITCHPOS", [])):
            sw_id = entry.get("SWITCH_ID", entry.get("SWITCHID", ""))
            sw_state = entry.get("STATE", entry.get("SWITCHPOS", ""))
            if sw_id:
                switch_positions[sw_id] = sw_state
    except Exception as e:
        logger.warning(f"Could not call SFW_GET_SWITCHPOS: {e}")
        switch_positions = {}

    # Step 3: Build the consolidated function list
    for switch in switches:
        sw_id = switch["switch_id"]
        state = switch_positions.get(sw_id, "UNKNOWN")
        is_activated = state in ("T", "ON", "1", "X")

        detail = {
            "function_id": sw_id,
            "state": "activated" if is_activated else "deactivated",
            "version": switch["version"],
            "author": switch["author"],
            "s4_status": "compatible",
            "s4_note": "",
        }

        # Check against mandatory/obsolete lists
        if sw_id in s4_mandatory_functions:
            detail["s4_status"] = "mandatory" if not is_activated else "compatible"
            detail["s4_note"] = s4_mandatory_functions[sw_id]
            if not is_activated:
                results["mandatory_in_target"] += 1
        elif sw_id in s4_obsolete_functions:
            detail["s4_status"] = "obsolete"
            detail["s4_note"] = s4_obsolete_functions[sw_id]
            results["obsolete_in_target"] += 1

        if is_activated:
            results["activated"] += 1
        else:
            results["deactivated"] += 1

        results["details"].append(detail)

    results["total_functions"] = len(results["details"])

    # Overall assessment
    if results["mandatory_in_target"] > 0:
        results["assessment"] = "ACTION_REQUIRED"
        results["assessment_message"] = (
            f"{results['mandatory_in_target']} business function(s) must be activated "
            "before S/4HANA conversion. These are mandatory in the target release."
        )
    else:
        results["assessment"] = "CLEAR"
        results["assessment_message"] = (
            "All mandatory business functions are already activated."
        )

    logger.info(
        f"Business functions: {results['activated']} active, "
        f"{results['deactivated']} inactive, "
        f"{results['mandatory_in_target']} need activation, "
        f"{results['obsolete_in_target']} obsolete"
    )
    return results


# =============================================================================
# SOFTWARE COMPONENT VERSION CHECK
# =============================================================================
def check_component_versions(connection):
    """
    Read the installed software component versions from CVERS table.

    SAP TABLE: CVERS — Component Version Registry
    Key fields: COMPONENT (component name), RELEASE (version), EXTRELEASE

    This is the SAP equivalent of 'rpm -qa' or 'dpkg -l' — it tells you
    exactly what software is installed on the SAP system.

    Parameters:
        connection: Active PyRFC connection to SAP ECC.

    Returns:
        dict: Installed component inventory with version details.
    """
    logger.info("Reading software component versions from CVERS...")

    try:
        result = connection.call(
            "RFC_READ_TABLE",
            QUERY_TABLE="CVERS",
            DELIMITER="|",
            FIELDS=[
                {"FIELDNAME": "COMPONENT"},    # Component name (e.g., SAP_BASIS)
                {"FIELDNAME": "RELEASE"},      # Release version (e.g., 750)
                {"FIELDNAME": "EXTRELEASE"},   # External release (e.g., 0023)
                {"FIELDNAME": "COMP_TYPE"},    # Component type (S=Software, R=Release)
            ],
            ROWCOUNT=99999,
        )

        components = []
        for row in result["DATA"]:
            fields = row["WA"].split("|")
            if len(fields) >= 4:
                components.append({
                    "component": fields[0].strip(),
                    "release": fields[1].strip(),
                    "ext_release": fields[2].strip(),
                    "type": fields[3].strip(),
                })

        logger.info(f"Found {len(components)} installed software components")
        return {
            "total_components": len(components),
            "components": components,
        }

    except Exception as e:
        logger.error(f"Failed to read CVERS: {e}")
        return {
            "total_components": 0,
            "components": [],
            "error": str(e),
        }


# =============================================================================
# COMPANY CODES (T001)
# =============================================================================
def read_company_codes(connection):
    """
    Read company codes from T001 table.

    SAP TABLE: T001 — Company Code Master
    Key fields: BUKRS (company code), BUTXT (name), LAND1 (country),
                WAERS (currency), PERIV (fiscal year variant)

    Parameters:
        connection: Active PyRFC connection to SAP ECC.

    Returns:
        dict: Company code inventory.
    """
    logger.info("Reading company codes from T001...")

    try:
        result = connection.call(
            "RFC_READ_TABLE",
            QUERY_TABLE="T001",
            DELIMITER="|",
            FIELDS=[
                {"FIELDNAME": "BUKRS"},     # Company code
                {"FIELDNAME": "BUTXT"},     # Company name
                {"FIELDNAME": "LAND1"},     # Country key
                {"FIELDNAME": "WAERS"},     # Currency
                {"FIELDNAME": "PERIV"},     # Fiscal year variant
            ],
            ROWCOUNT=99999,
        )

        company_codes = []
        for row in result["DATA"]:
            fields = row["WA"].split("|")
            if len(fields) >= 5:
                company_codes.append({
                    "company_code": fields[0].strip(),
                    "name": fields[1].strip(),
                    "country": fields[2].strip(),
                    "currency": fields[3].strip(),
                    "fiscal_year_variant": fields[4].strip(),
                })

        logger.info(f"Found {len(company_codes)} company codes")
        return {
            "total_company_codes": len(company_codes),
            "company_codes": company_codes,
        }

    except Exception as e:
        logger.error(f"Failed to read T001: {e}")
        return {
            "total_company_codes": 0,
            "company_codes": [],
            "error": str(e),
        }


# =============================================================================
# FINANCIAL LEDGERS (FINSC_LEDGER)
# =============================================================================
def read_financial_ledgers(connection):
    """
    Read financial ledger configuration from FINSC_LEDGER table.

    SAP TABLE: FINSC_LEDGER — Financial Accounting Ledger Configuration
    Key fields: RLDNR (ledger), RLDNRT (ledger name), RRCTY (record type),
                RVERS (version)

    This is critical for S/4HANA migration because ledger configuration
    determines how the Universal Journal (ACDOCA) is structured.

    Parameters:
        connection: Active PyRFC connection to SAP ECC.

    Returns:
        dict: Financial ledger inventory.
    """
    logger.info("Reading financial ledgers from FINSC_LEDGER...")

    try:
        result = connection.call(
            "RFC_READ_TABLE",
            QUERY_TABLE="FINSC_LEDGER",
            DELIMITER="|",
            FIELDS=[
                {"FIELDNAME": "RLDNR"},    # Ledger
                {"FIELDNAME": "RLDNRT"},   # Ledger name
                {"FIELDNAME": "RRCTY"},    # Record type
                {"FIELDNAME": "RVERS"},    # Version
            ],
            ROWCOUNT=99999,
        )

        ledgers = []
        for row in result["DATA"]:
            fields = row["WA"].split("|")
            if len(fields) >= 4:
                ledgers.append({
                    "ledger": fields[0].strip(),
                    "name": fields[1].strip(),
                    "record_type": fields[2].strip(),
                    "version": fields[3].strip(),
                })

        logger.info(f"Found {len(ledgers)} financial ledgers")
        return {
            "total_ledgers": len(ledgers),
            "ledgers": ledgers,
        }

    except Exception as e:
        logger.error(f"Failed to read FINSC_LEDGER: {e}")
        return {
            "total_ledgers": 0,
            "ledgers": [],
            "error": str(e),
        }


# =============================================================================
# ADD-ON REGISTRY CHECK
# =============================================================================
def check_addon_registry(connection):
    """
    Read the add-on registry from PAT_ADDON table.

    SAP TABLE: PAT_ADDON — Add-on registry for installed add-ons
    This provides the definitive list of what add-ons are installed,
    complementing CVERS with add-on specific metadata.

    Parameters:
        connection: Active PyRFC connection to SAP ECC.

    Returns:
        list: Installed add-ons with version and status.
    """
    logger.info("Reading add-on registry from PAT_ADDON...")

    try:
        result = connection.call(
            "RFC_READ_TABLE",
            QUERY_TABLE="PAT_ADDON",
            DELIMITER="|",
            FIELDS=[
                {"FIELDNAME": "ADDON_ID"},     # Add-on identifier
                {"FIELDNAME": "ADDON_DESC"},   # Add-on description
                {"FIELDNAME": "VERSION"},      # Installed version
                {"FIELDNAME": "STATUS"},       # Status (A=Active, I=Inactive)
            ],
            ROWCOUNT=99999,
        )

        addons = []
        for row in result["DATA"]:
            fields = row["WA"].split("|")
            if len(fields) >= 4:
                addons.append({
                    "name": fields[0].strip(),
                    "description": fields[1].strip(),
                    "version": fields[2].strip(),
                    "status": "active" if fields[3].strip() == "A" else "inactive",
                })

        logger.info(f"Found {len(addons)} registered add-ons")
        return addons

    except Exception as e:
        logger.warning(f"Could not read PAT_ADDON (table may not exist): {e}")
        return []


# =============================================================================
# TARGET DEFINITION GENERATOR
# =============================================================================
def generate_target_definition(stack_data, compatibility_results, business_functions, component_versions):
    """
    Create a complete target system definition document that will be used
    by the SUM/DMO orchestrator to configure the conversion.

    This is the "bill of materials" for the target S/4HANA system.

    Parameters:
        stack_data (dict): Parsed stack.xml results.
        compatibility_results (dict): Add-on compatibility analysis.
        business_functions (dict): Business function analysis.
        component_versions (dict): Current component version inventory.

    Returns:
        dict: Complete target system definition.
    """
    logger.info("Generating target system definition...")

    # Determine blocking items
    blocking_addons = [
        d for d in compatibility_results.get("details", [])
        if d.get("compatibility") in ("not_compatible", "replaced")
    ]

    mandatory_bf_actions = [
        d for d in business_functions.get("details", [])
        if d.get("s4_status") == "mandatory"
    ]

    target_definition = {
        "generated_at": datetime.utcnow().isoformat(),
        "target_product": stack_data.get("target_product", "SAP S/4HANA"),
        "target_release": stack_data.get("target_release", ""),
        "source_system": {
            "total_components": component_versions.get("total_components", 0),
            "key_components": [
                c for c in component_versions.get("components", [])
                if c.get("component", "").startswith("SAP_")
            ][:20],
        },
        "target_stack": {
            "components": stack_data.get("components", []),
            "support_packages": stack_data.get("support_packages", []),
            "kernel_requirements": stack_data.get("kernel_requirements", {}),
        },
        "addon_assessment": {
            "total_addons": compatibility_results.get("total_addons", 0),
            "compatible": compatibility_results.get("compatible", 0),
            "action_required": compatibility_results.get("not_compatible", 0) + compatibility_results.get("replaced", 0),
            "blocking_addons": blocking_addons,
        },
        "business_function_assessment": {
            "total_functions": business_functions.get("total_functions", 0),
            "activated": business_functions.get("activated", 0),
            "mandatory_actions": mandatory_bf_actions,
        },
        "pre_conversion_actions": [],
        "conversion_ready": True,
        "readiness_score": "GREEN",
    }

    # Build pre-conversion action list
    actions = []

    # Add-on actions
    for addon in blocking_addons:
        actions.append({
            "category": "add-on",
            "priority": "P1",
            "action": f"Remove or replace add-on {addon['addon']}",
            "detail": addon.get("recommendation", ""),
            "blocking": True,
        })

    # Business function actions
    for bf in mandatory_bf_actions:
        actions.append({
            "category": "business_function",
            "priority": "P1",
            "action": f"Activate business function {bf['function_id']}",
            "detail": bf.get("s4_note", ""),
            "blocking": True,
        })

    # Restricted add-on warnings
    for detail in compatibility_results.get("details", []):
        if detail.get("compatibility") == "restricted":
            actions.append({
                "category": "add-on",
                "priority": "P2",
                "action": f"Review restricted add-on {detail['addon']}",
                "detail": detail.get("recommendation", ""),
                "blocking": False,
            })

    target_definition["pre_conversion_actions"] = actions

    # Determine overall readiness
    p1_count = sum(1 for a in actions if a.get("priority") == "P1")
    if p1_count > 0:
        target_definition["conversion_ready"] = False
        target_definition["readiness_score"] = "RED"
        target_definition["readiness_message"] = (
            f"{p1_count} blocking action(s) must be resolved before conversion."
        )
    elif len(actions) > 0:
        target_definition["readiness_score"] = "YELLOW"
        target_definition["readiness_message"] = (
            f"{len(actions)} non-blocking action(s) should be reviewed before conversion."
        )
    else:
        target_definition["readiness_message"] = (
            "System is ready for S/4HANA conversion. No blocking issues found."
        )

    logger.info(
        f"Target definition generated: ready={target_definition['conversion_ready']}, "
        f"score={target_definition['readiness_score']}, "
        f"{len(actions)} pre-conversion actions"
    )
    return target_definition


# =============================================================================
# MAIN HANDLER
# =============================================================================
def main(event, context):
    """
    Main entry point for the Maintenance Planner interface.

    Input (from Durable Functions):
    {
        "stage": "maintenance-planner",
        "input": {
            "stack_xml_s3_key": "migrations/{run_id}/input/stack.xml",
            "target_release": "2023"
        },
        "metadata": {
            "run_id": "uuid",
            "timestamp": "..."
        }
    }

    Output (passed to next stage):
    {
        "status": "success",
        "conversion_ready": true/false,
        "readiness_score": "GREEN|YELLOW|RED",
        "summary": {...},
        "s3_prefix": "migrations/{run_id}/maintenance-planner/"
    }
    """
    logger.info(f"Maintenance Planner started: {json.dumps(event)}")
    log_stage_event("maintenance-planner", "Pipeline Start", "IN_PROGRESS", {
        "target_release": event.get("input", {}).get("target_release", "2023"),
    })
    _stage_start = __import__('time').time()

    run_id = event.get("metadata", {}).get("run_id", "manual-run")
    target_release = event.get("input", {}).get("target_release", "2023")
    stack_xml_s3_key = event.get("input", {}).get("stack_xml_s3_key", "")
    s3_prefix = f"migrations/{run_id}/maintenance-planner"

    try:
        # Step 1: Load and parse stack.xml from S3
        stack_data = {}
        if stack_xml_s3_key:
            try:
                stack_obj = get_object(STAGING_CONTAINER, stack_xml_s3_key)
                stack_xml_content = stack_obj["Body"].read().decode("utf-8")
                stack_data = parse_stack_xml(stack_xml_content)
            except Exception as e:
                logger.warning(f"Could not load stack.xml from S3: {e}")
                stack_data = {
                    "parse_status": "not_available",
                    "target_product": "SAP S/4HANA",
                    "target_release": target_release,
                    "components": [],
                    "addon_requirements": [],
                    "support_packages": [],
                    "kernel_requirements": {},
                    "industry_solutions": [],
                }
        else:
            logger.info("No stack.xml S3 key provided — using target release only")
            stack_data = {
                "parse_status": "not_provided",
                "target_product": "SAP S/4HANA",
                "target_release": target_release,
                "components": [],
                "addon_requirements": [],
                "support_packages": [],
                "kernel_requirements": {},
                "industry_solutions": [],
            }

        # Override target release from stack.xml if parsed successfully
        if stack_data.get("target_release"):
            target_release = stack_data["target_release"]

        # Step 2: Connect to SAP and gather system data
        conn = get_sap_connection()

        # Step 3: Check component versions
        component_versions = check_component_versions(conn)

        # Step 3a: Read company codes (T001)
        company_codes = read_company_codes(conn)

        # Step 3b: Read financial ledgers (FINSC_LEDGER)
        financial_ledgers = read_financial_ledgers(conn)

        # Step 4: Check add-on registry
        installed_addons = check_addon_registry(conn)

        # Merge add-ons from stack.xml and installed registry
        all_addons = list(stack_data.get("addon_requirements", []))
        addon_names_seen = {a.get("name", "").upper() for a in all_addons}
        for addon in installed_addons:
            if addon.get("name", "").upper() not in addon_names_seen:
                all_addons.append(addon)
                addon_names_seen.add(addon.get("name", "").upper())

        # Step 5: Validate add-on compatibility
        compatibility_results = validate_addon_compatibility(all_addons, target_release)

        # Step 6: Check business functions
        business_functions = check_business_functions(conn, target_release)

        # Step 7: Generate target definition
        target_definition = generate_target_definition(
            stack_data, compatibility_results, business_functions, component_versions
        )

        conn.close()

        # Save results to S3
        artifacts = {
            f"{s3_prefix}/stack_analysis.json": stack_data,
            f"{s3_prefix}/company_codes.json": company_codes,
            f"{s3_prefix}/financial_ledgers.json": financial_ledgers,
            f"{s3_prefix}/addon_compatibility.json": compatibility_results,
            f"{s3_prefix}/business_functions.json": business_functions,
            f"{s3_prefix}/target_definition.json": target_definition,
        }

        for s3_key, data in artifacts.items():
            put_object(
                STAGING_CONTAINER,
                s3_key,
                json.dumps(data, indent=2, default=str),
            )

        # Build summary
        summary = {
            "target_product": target_definition.get("target_product", ""),
            "target_release": target_release,
            "components_analyzed": component_versions.get("total_components", 0),
            "company_codes_found": company_codes.get("total_company_codes", 0),
            "financial_ledgers_found": financial_ledgers.get("total_ledgers", 0),
            "addons_checked": compatibility_results.get("total_addons", 0),
            "addons_compatible": compatibility_results.get("compatible", 0),
            "addons_incompatible": compatibility_results.get("not_compatible", 0),
            "addons_restricted": compatibility_results.get("restricted", 0),
            "business_functions_total": business_functions.get("total_functions", 0),
            "business_functions_activated": business_functions.get("activated", 0),
            "mandatory_bf_actions": business_functions.get("mandatory_in_target", 0),
            "pre_conversion_actions": len(target_definition.get("pre_conversion_actions", [])),
            "conversion_ready": target_definition.get("conversion_ready", False),
            "readiness_score": target_definition.get("readiness_score", "UNKNOWN"),
        }

        logger.info(f"Maintenance Planner complete: {json.dumps(summary)}")
        log_stage_event(
            "maintenance-planner", "Analysis Complete", "SUCCESS",
            summary, (__import__('time').time() - _stage_start) * 1000
        )

        return {
            "status": "success",
            "conversion_ready": target_definition.get("conversion_ready", False),
            "readiness_score": target_definition.get("readiness_score", "UNKNOWN"),
            "summary": summary,
            "s3_prefix": s3_prefix,
            "run_id": run_id,
        }

    except ImportError:
        # PyRFC not installed — return mock data for testing
        logger.warning("PyRFC not available — returning mock maintenance planner data")
        mock_company_codes = {
            "total_company_codes": 4,
            "company_codes": [
                {"company_code": "1000", "name": "Global Corp HQ", "country": "US", "currency": "USD", "fiscal_year_variant": "K4"},
                {"company_code": "2000", "name": "Europe Operations", "country": "DE", "currency": "EUR", "fiscal_year_variant": "K4"},
                {"company_code": "3000", "name": "Asia Pacific", "country": "JP", "currency": "JPY", "fiscal_year_variant": "K4"},
                {"company_code": "4000", "name": "Latin America", "country": "BR", "currency": "BRL", "fiscal_year_variant": "K4"},
            ],
        }
        mock_financial_ledgers = {
            "total_ledgers": 3,
            "ledgers": [
                {"ledger": "0L", "name": "Leading Ledger", "record_type": "0", "version": "001"},
                {"ledger": "2L", "name": "IFRS Ledger", "record_type": "0", "version": "001"},
                {"ledger": "3L", "name": "Tax Ledger", "record_type": "0", "version": "001"},
            ],
        }
        mock_summary = {
            "target_product": "SAP S/4HANA",
            "target_release": target_release,
            "components_analyzed": 47,
            "company_codes_found": mock_company_codes["total_company_codes"],
            "financial_ledgers_found": mock_financial_ledgers["total_ledgers"],
            "addons_checked": 8,
            "addons_compatible": 5,
            "addons_incompatible": 1,
            "addons_restricted": 2,
            "business_functions_total": 156,
            "business_functions_activated": 89,
            "mandatory_bf_actions": 2,
            "pre_conversion_actions": 5,
            "conversion_ready": False,
            "readiness_score": "YELLOW",
            "mode": "MOCK_DATA",
        }
        return {
            "status": "success",
            "conversion_ready": False,
            "readiness_score": "YELLOW",
            "summary": mock_summary,
            "s3_prefix": f"migrations/{run_id}/maintenance-planner",
            "run_id": run_id,
        }

    except Exception as e:
        logger.error(f"Maintenance Planner failed: {str(e)}")
        log_stage_event("maintenance-planner", "Analysis Failed", "ERROR", str(e))
        raise
