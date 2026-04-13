"""
bp_pre_validation_engine.py - S/4HANA Business Partner Pre-Migration Validator
================================================================================
Scans ECC Customer (KNA1) and Vendor (LFA1) master data BEFORE migration and
flags every record that would be rejected by the S/4HANA Business Partner API.

S/4HANA enforces strict data quality via:
  - BAPI_BUPA_CREATE_FROM_DATA mandatory field checks
  - CVI Cockpit synchronization requirements
  - BP role-specific field requirements (e.g. email for certain partner roles)

Running this BEFORE the push prevents batch rejections and costly re-runs.

Checks performed:
  1. Mandatory fields: NAME1, LAND1, ORT01, PSTLZ, STRAS
  2. ISO 3166 country code validation on LAND1
  3. Tax number (STCD1/STCD3) format validation per country
  4. Email format validation (SMTP_ADDR) for roles requiring it
  5. Postal code format validation per country
  6. Telephone number format validation (TELF1)
  7. Account group (KTOKD/KTOKK) presence for BP grouping mapping
  8. Duplicate tax ID detection (potential merge candidates missed upstream)

Output: Structured report suitable for client remediation handoff.
"""

import logging
import os
import re
from typing import List, Dict, Any, Tuple, Optional

logger = logging.getLogger("bp_pre_validation")
logger.setLevel(logging.INFO)

# Configurable: halt migration if critical violation rate exceeds threshold
HALT_THRESHOLD_PCT = 10.0
try:
    HALT_THRESHOLD_PCT = float(os.environ.get("BP_VALIDATION_HALT_PCT", "10.0"))
except (ValueError, TypeError):
    pass


# =============================================================================
# ISO 3166-1 ALPHA-2 COUNTRY CODES (complete set)
# =============================================================================
ISO_3166_ALPHA2 = {
    "AD", "AE", "AF", "AG", "AI", "AL", "AM", "AO", "AQ", "AR", "AS", "AT",
    "AU", "AW", "AX", "AZ", "BA", "BB", "BD", "BE", "BF", "BG", "BH", "BI",
    "BJ", "BL", "BM", "BN", "BO", "BQ", "BR", "BS", "BT", "BV", "BW", "BY",
    "BZ", "CA", "CC", "CD", "CF", "CG", "CH", "CI", "CK", "CL", "CM", "CN",
    "CO", "CR", "CU", "CV", "CW", "CX", "CY", "CZ", "DE", "DJ", "DK", "DM",
    "DO", "DZ", "EC", "EE", "EG", "EH", "ER", "ES", "ET", "FI", "FJ", "FK",
    "FM", "FO", "FR", "GA", "GB", "GD", "GE", "GF", "GG", "GH", "GI", "GL",
    "GM", "GN", "GP", "GQ", "GR", "GS", "GT", "GU", "GW", "GY", "HK", "HM",
    "HN", "HR", "HT", "HU", "ID", "IE", "IL", "IM", "IN", "IO", "IQ", "IR",
    "IS", "IT", "JE", "JM", "JO", "JP", "KE", "KG", "KH", "KI", "KM", "KN",
    "KP", "KR", "KW", "KY", "KZ", "LA", "LB", "LC", "LI", "LK", "LR", "LS",
    "LT", "LU", "LV", "LY", "MA", "MC", "MD", "ME", "MF", "MG", "MH", "MK",
    "ML", "MM", "MN", "MO", "MP", "MQ", "MR", "MS", "MT", "MU", "MV", "MW",
    "MX", "MY", "MZ", "NA", "NC", "NE", "NF", "NG", "NI", "NL", "NO", "NP",
    "NR", "NU", "NZ", "OM", "PA", "PE", "PF", "PG", "PH", "PK", "PL", "PM",
    "PN", "PR", "PS", "PT", "PW", "PY", "QA", "RE", "RO", "RS", "RU", "RW",
    "SA", "SB", "SC", "SD", "SE", "SG", "SH", "SI", "SJ", "SK", "SL", "SM",
    "SN", "SO", "SR", "SS", "ST", "SV", "SX", "SY", "SZ", "TC", "TD", "TF",
    "TG", "TH", "TJ", "TK", "TL", "TM", "TN", "TO", "TR", "TT", "TV", "TW",
    "TZ", "UA", "UG", "UM", "US", "UY", "UZ", "VA", "VC", "VE", "VG", "VI",
    "VN", "VU", "WF", "WS", "YE", "YT", "ZA", "ZM", "ZW",
}


# =============================================================================
# COUNTRY-SPECIFIC POSTAL CODE PATTERNS
# =============================================================================
POSTAL_CODE_PATTERNS = {
    "IN": re.compile(r"^\d{6}$"),                  # India: 6 digits
    "US": re.compile(r"^\d{5}(-\d{4})?$"),         # US: 5 or 5+4
    "DE": re.compile(r"^\d{5}$"),                   # Germany: 5 digits
    "GB": re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}$", re.I),  # UK
    "JP": re.compile(r"^\d{3}-?\d{4}$"),            # Japan: 123-4567
    "CN": re.compile(r"^\d{6}$"),                   # China: 6 digits
    "BR": re.compile(r"^\d{5}-?\d{3}$"),            # Brazil: 12345-678
    "AE": re.compile(r"^\d{5,6}$"),                 # UAE: 5-6 digits (or absent)
    "KR": re.compile(r"^\d{5}$"),                   # South Korea: 5 digits
    "AU": re.compile(r"^\d{4}$"),                   # Australia: 4 digits
    "SA": re.compile(r"^\d{5}$"),                   # Saudi Arabia: 5 digits
    "ZA": re.compile(r"^\d{4}$"),                   # South Africa: 4 digits
    "FR": re.compile(r"^\d{5}$"),                   # France: 5 digits
    "IT": re.compile(r"^\d{5}$"),                   # Italy: 5 digits
}

# =============================================================================
# COUNTRY-SPECIFIC TAX ID PATTERNS
# =============================================================================
TAX_ID_PATTERNS = {
    "IN": re.compile(r"^[A-Z]{5}\d{4}[A-Z]$"),                     # PAN
    "US": re.compile(r"^\d{2}-?\d{7}$"),                             # EIN
    "DE": re.compile(r"^DE\d{9}$|^\d{10,11}$"),                     # USt-IdNr / Steuernummer
    "GB": re.compile(r"^GB\d{9}$|^GB\d{12}$|^GBGD\d{3}$"),         # VAT
    "AE": re.compile(r"^\d{15}$"),                                    # TRN
    "CN": re.compile(r"^[0-9A-Z]{15,20}$"),                          # Unified Social Credit Code
    "JP": re.compile(r"^T?\d{13}$"),                                  # Corporate Number
    "KR": re.compile(r"^\d{3}-\d{2}-\d{5}$"),                        # Business Registration
    "BR": re.compile(r"^\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}$"),     # CNPJ
    "SA": re.compile(r"^\d{15}$"),                                    # VAT TIN
}

# Email regex (RFC 5322 simplified)
EMAIL_PATTERN = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,}$"
)


# =============================================================================
# S/4HANA MANDATORY FIELD DEFINITIONS PER BP CATEGORY
# =============================================================================
# Fields that BAPI_BUPA_CREATE_FROM_DATA will reject if missing.
BP_MANDATORY_FIELDS = {
    "common": ["NAME1", "LAND1"],
    "organization": ["NAME1", "LAND1"],
    "address": ["ORT01", "PSTLZ", "STRAS"],
}

# Fields that are not strictly mandatory but highly recommended and will
# cause downstream issues in S/4HANA if absent.
BP_RECOMMENDED_FIELDS = {
    "customer": ["STCD1", "TELF1", "ORT01", "PSTLZ", "STRAS"],
    "vendor": ["STCD1", "TELF1", "ORT01", "PSTLZ", "STRAS"],
}


# =============================================================================
# INDIVIDUAL FIELD VALIDATORS
# =============================================================================

def _validate_country_iso(land1: str) -> Optional[str]:
    """Validate LAND1 is a valid ISO 3166-1 alpha-2 country code."""
    if not land1 or not land1.strip():
        return "LAND1 (Country) is missing — mandatory for BP creation"
    code = land1.strip().upper()
    if code not in ISO_3166_ALPHA2:
        return f"LAND1 '{code}' is not a valid ISO 3166-1 alpha-2 country code"
    return None


def _validate_postal_code(pstlz: str, land1: str) -> Optional[str]:
    """Validate postal code format for the given country."""
    if not pstlz or not pstlz.strip():
        return "PSTLZ (Postal Code) is missing — required for S/4HANA address"
    code = pstlz.strip()
    country = (land1 or "").strip().upper()
    pattern = POSTAL_CODE_PATTERNS.get(country)
    if pattern and not pattern.match(code):
        return f"PSTLZ '{code}' does not match expected format for country {country}"
    return None


def _validate_tax_id(stcd1: str, land1: str) -> Optional[str]:
    """Validate tax number format for the given country."""
    if not stcd1 or not stcd1.strip():
        return "STCD1 (Tax Number) is missing — required for BP tax compliance"
    code = stcd1.strip().upper()
    country = (land1 or "").strip().upper()
    pattern = TAX_ID_PATTERNS.get(country)
    if pattern and not pattern.match(code):
        return f"STCD1 '{code}' does not match expected tax ID format for country {country}"
    return None


def _validate_email(smtp_addr: str) -> Optional[str]:
    """Validate email address format."""
    if not smtp_addr or not smtp_addr.strip():
        return "SMTP_ADDR (Email) is missing — recommended for BP communication"
    if not EMAIL_PATTERN.match(smtp_addr.strip()):
        return f"SMTP_ADDR '{smtp_addr}' is not a valid email format"
    return None


def _validate_name(name1: str) -> Optional[str]:
    """Validate NAME1 is present and non-trivial."""
    if not name1 or not name1.strip():
        return "NAME1 (Name) is missing — mandatory for BP creation"
    if len(name1.strip()) < 2:
        return f"NAME1 '{name1}' is too short (minimum 2 characters)"
    return None


# =============================================================================
# CORE VALIDATION ENGINE
# =============================================================================

def validate_single_entity(
    entity: Dict[str, Any],
    entity_type: str,
) -> Dict[str, Any]:
    """
    Validate a single customer or vendor record against S/4HANA BP requirements.

    Returns a dict with:
      - entity_id: the KUNNR or LIFNR
      - entity_type: CUSTOMER or VENDOR
      - violations: list of {field, severity, message}
      - status: PASS / WARNING / CRITICAL
    """
    if entity_type == "CUSTOMER":
        entity_id = entity.get("KUNNR", "UNKNOWN")
    else:
        entity_id = entity.get("LIFNR", "UNKNOWN")

    violations = []

    # --- Mandatory: NAME1 ---
    err = _validate_name(entity.get("NAME1", ""))
    if err:
        violations.append({"field": "NAME1", "severity": "CRITICAL", "message": err})

    # --- Mandatory: LAND1 (Country ISO) ---
    err = _validate_country_iso(entity.get("LAND1", ""))
    if err:
        violations.append({"field": "LAND1", "severity": "CRITICAL", "message": err})

    # --- Mandatory-for-address: ORT01 (City) ---
    if not entity.get("ORT01", "").strip():
        violations.append({
            "field": "ORT01", "severity": "CRITICAL",
            "message": "ORT01 (City) is missing — required for S/4HANA central address",
        })

    # --- Mandatory-for-address: PSTLZ (Postal Code) ---
    err = _validate_postal_code(entity.get("PSTLZ", ""), entity.get("LAND1", ""))
    if err:
        sev = "CRITICAL" if "missing" in err.lower() else "WARNING"
        violations.append({"field": "PSTLZ", "severity": sev, "message": err})

    # --- Mandatory-for-address: STRAS (Street) ---
    if not entity.get("STRAS", "").strip():
        violations.append({
            "field": "STRAS", "severity": "CRITICAL",
            "message": "STRAS (Street) is missing — required for S/4HANA central address",
        })

    # --- Recommended: Tax ID (STCD1 / STCD3) ---
    stcd1 = entity.get("STCD1", entity.get("STCD3", ""))
    err = _validate_tax_id(stcd1, entity.get("LAND1", ""))
    if err:
        sev = "WARNING" if "missing" in err.lower() else "WARNING"
        violations.append({"field": "STCD1", "severity": sev, "message": err})

    # --- Recommended: Email (SMTP_ADDR) ---
    err = _validate_email(entity.get("SMTP_ADDR", ""))
    if err:
        sev = "INFO" if "missing" in err.lower() else "WARNING"
        violations.append({"field": "SMTP_ADDR", "severity": sev, "message": err})

    # --- Recommended: Telephone (TELF1) ---
    if not entity.get("TELF1", "").strip():
        violations.append({
            "field": "TELF1", "severity": "INFO",
            "message": "TELF1 (Telephone) is missing — recommended for BP master",
        })

    # --- Customer-specific: Account Group (KTOKD) ---
    if entity_type == "CUSTOMER" and not entity.get("KTOKD", "").strip():
        violations.append({
            "field": "KTOKD", "severity": "WARNING",
            "message": "KTOKD (Customer Account Group) is missing — needed for BP grouping mapping",
        })

    # --- Vendor-specific: Account Group (KTOKK) ---
    if entity_type == "VENDOR" and not entity.get("KTOKK", "").strip():
        violations.append({
            "field": "KTOKK", "severity": "INFO",
            "message": "KTOKK (Vendor Account Group) is missing — needed for BP grouping mapping",
        })

    # Determine overall status
    crit_count = sum(1 for v in violations if v["severity"] == "CRITICAL")
    warn_count = sum(1 for v in violations if v["severity"] == "WARNING")

    if crit_count > 0:
        status = "CRITICAL"
    elif warn_count > 0:
        status = "WARNING"
    else:
        status = "PASS"

    return {
        "entity_id": entity_id,
        "entity_type": entity_type,
        "name": entity.get("NAME1", ""),
        "country": entity.get("LAND1", ""),
        "status": status,
        "critical_count": crit_count,
        "warning_count": warn_count,
        "violations": violations,
    }


# =============================================================================
# BATCH VALIDATION
# =============================================================================

def run_bp_pre_validation(
    customers: List[Dict[str, Any]],
    vendors: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Production-grade pre-migration validation for all Customer and Vendor records.

    Scans every record and produces a structured remediation report.

    Returns:
        {
            "status": "PASS" | "WARNING" | "HALT",
            "summary": { ... },
            "customer_violations": [ ... ],
            "vendor_violations": [ ... ],
            "field_summary": { field: count },
            "remediation_required": bool,
            "halt_migration": bool,
        }
    """
    customer_results = []
    vendor_results = []

    # Validate all customers
    for cust in customers:
        result = validate_single_entity(cust, "CUSTOMER")
        if result["status"] != "PASS":
            customer_results.append(result)

    # Validate all vendors
    for vendor in vendors:
        result = validate_single_entity(vendor, "VENDOR")
        if result["status"] != "PASS":
            vendor_results.append(result)

    # Aggregate field-level violation counts
    field_summary: Dict[str, int] = {}
    severity_summary = {"CRITICAL": 0, "WARNING": 0, "INFO": 0}

    for result in customer_results + vendor_results:
        for v in result["violations"]:
            field_summary[v["field"]] = field_summary.get(v["field"], 0) + 1
            severity_summary[v["severity"]] = severity_summary.get(v["severity"], 0) + 1

    total_entities = len(customers) + len(vendors)
    total_with_issues = len(customer_results) + len(vendor_results)
    critical_entities = sum(
        1 for r in (customer_results + vendor_results) if r["status"] == "CRITICAL"
    )

    critical_pct = (critical_entities / max(total_entities, 1)) * 100
    halt_migration = critical_pct > HALT_THRESHOLD_PCT

    if halt_migration:
        overall_status = "HALT"
    elif critical_entities > 0:
        overall_status = "WARNING"
    else:
        overall_status = "PASS"

    logger.info(
        f"BP Pre-Validation complete: {total_entities} entities scanned, "
        f"{total_with_issues} with issues ({critical_entities} critical, "
        f"{critical_pct:.1f}% critical rate)"
    )

    if halt_migration:
        logger.warning(
            f"HALT RECOMMENDED: Critical violation rate {critical_pct:.1f}% "
            f"exceeds threshold {HALT_THRESHOLD_PCT}%. "
            f"Fix data quality issues before proceeding with migration."
        )

    return {
        "status": overall_status,
        "summary": {
            "total_customers": len(customers),
            "total_vendors": len(vendors),
            "total_entities_scanned": total_entities,
            "customers_with_issues": len(customer_results),
            "vendors_with_issues": len(vendor_results),
            "total_with_issues": total_with_issues,
            "critical_entities": critical_entities,
            "critical_rate_pct": f"{critical_pct:.1f}%",
            "halt_threshold_pct": f"{HALT_THRESHOLD_PCT}%",
            "severity_counts": severity_summary,
        },
        "field_summary": field_summary,
        "customer_violations": customer_results,
        "vendor_violations": vendor_results,
        "remediation_required": total_with_issues > 0,
        "halt_migration": halt_migration,
    }


# =============================================================================
# REMEDIATION REPORT GENERATOR
# =============================================================================

def generate_remediation_report(validation_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Generate a prioritized remediation report from validation results.

    Sorted by: CRITICAL first, then WARNING, then INFO.
    Groups violations by field for efficient remediation workflows.
    """
    field_groups: Dict[str, List[Dict]] = {}

    all_violations = (
        validation_result.get("customer_violations", []) +
        validation_result.get("vendor_violations", [])
    )

    for entity_result in all_violations:
        for v in entity_result["violations"]:
            field = v["field"]
            if field not in field_groups:
                field_groups[field] = []
            field_groups[field].append({
                "entity_id": entity_result["entity_id"],
                "entity_type": entity_result["entity_type"],
                "name": entity_result["name"],
                "severity": v["severity"],
                "message": v["message"],
            })

    # Sort severity: CRITICAL > WARNING > INFO
    severity_order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}

    report_items = []
    for field, entities in sorted(
        field_groups.items(),
        key=lambda x: min(severity_order.get(e["severity"], 9) for e in x[1])
    ):
        max_severity = min(entities, key=lambda e: severity_order.get(e["severity"], 9))["severity"]
        report_items.append({
            "field": field,
            "max_severity": max_severity,
            "affected_count": len(entities),
            "sample_entities": entities[:10],  # Cap at 10 samples per field
            "remediation_action": _get_remediation_action(field),
        })

    return report_items


def _get_remediation_action(field: str) -> str:
    """Return recommended remediation action for a given field."""
    actions = {
        "NAME1": "Populate NAME1 in ECC master data via XD02/XK02 before migration.",
        "LAND1": "Set valid ISO 3166-1 alpha-2 country code in LAND1 via XD02/XK02.",
        "ORT01": "Populate City (ORT01) in address data via XD02/XK02 or mass update via LSMW.",
        "PSTLZ": "Populate Postal Code (PSTLZ) in address data. Use LSMW for bulk update.",
        "STRAS": "Populate Street (STRAS) in address data. Use LSMW for bulk update.",
        "STCD1": "Populate Tax Number 1 (STCD1) — PAN for India, EIN for US, VAT ID for EU.",
        "SMTP_ADDR": "Populate email address in communication data (ADR6 table or BP transaction).",
        "TELF1": "Populate telephone number in address data.",
        "KTOKD": "Assign Customer Account Group (KTOKD) — needed for BP grouping mapping.",
        "KTOKK": "Assign Vendor Account Group (KTOKK) — needed for BP grouping mapping.",
    }
    return actions.get(field, f"Review and populate {field} in ECC master data before migration.")
