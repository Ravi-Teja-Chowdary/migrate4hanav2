"""
Migrate4HANA — Stage 3: Data Assessment & CVI Preparation
============================================================
Assesses data readiness and prepares Customer-Vendor Integration (CVI)
for the S/4HANA migration.

Data structural migration is performed by SAP SUM/DMO.
This stage prepares and validates data for SUM readiness.

This module handles:
1. ASSESSMENT: Analyze ECC data models for S/4HANA compatibility
2. CVI PREPARATION: Prepare Customer-Vendor-to-Business-Partner conversion
3. FINANCE READINESS: Validate finance data for ACDOCA/FINS compatibility
4. DATA QUALITY: Identify issues that must be resolved before SUM execution

Major data model changes in S/4HANA:
1. FINANCE: BSEG/BKPF/GLT0/COEP → ACDOCA (Universal Journal)
2. MATERIALS: MKPF/MSEG → MATDOC
3. BUSINESS PARTNER: KNA1+LFA1 → BUT000 (BP)
4. CONDITIONS: KONV → PRCD_ELEMENTS
5. CUSTOM Z-TABLES: Direct migration with structure validation

DevOps Analogy:
This is like running 'terraform plan' + validation checks before
the actual migration. SUM/DMO is the 'terraform apply' for core data.
"""

import json
import os
import logging
import boto3
import sys
from datetime import datetime

# Append internal hygiene modules for pre-processing mappings
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data-hygiene')))
from mdm_data_cleanser import execute_cleaning_batch
from bp_deduplication_engine import process_cvi_deduplication
from bp_pre_validation_engine import run_bp_pre_validation, generate_remediation_report
from bp_crosswalk_engine import (
    assign_bp_ids,
    generate_repointing_instructions,
    persist_crosswalk_to_s3,
    detect_id_overlaps,
)

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'utils')))
from logger import log_stage_event

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")

STAGING_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hana-staging-dev")


# =============================================================================
# TABLE MAPPING DEFINITIONS
# =============================================================================
# These define how ECC tables map to S/4HANA tables.
# Each mapping includes field-level transformations.

TABLE_MAPPINGS = {
    # ── FINANCE: Universal Journal ──
    "finance_journal": {
        "description": "Finance posting data → Universal Journal (ACDOCA)",
        "source_tables": ["BKPF", "BSEG", "BSID", "BSAD", "BSIK", "BSAK"],
        "target_table": "ACDOCA",
        "field_mapping": {
            # BKPF (Header) fields
            "BUKRS": {"target": "RBUKRS", "description": "Company code"},
            "BELNR": {"target": "BELNR", "description": "Document number"},
            "GJAHR": {"target": "GJAHR", "description": "Fiscal year"},
            "BLDAT": {"target": "BLDAT", "description": "Document date"},
            "BUDAT": {"target": "BUDAT", "description": "Posting date"},
            "MONAT": {"target": "POPER", "description": "Posting period"},
            "BLART": {"target": "BLART", "description": "Document type"},
            "WAERS": {"target": "RHCUR", "description": "Currency"},
            "BSTAT": {"target": "BSTAT", "description": "Document status"},
            # BSEG (Line item) fields
            "BUZEI": {"target": "BUZEI", "description": "Line item"},
            "KOART": {"target": "KOART", "description": "Account type"},
            "HKONT": {"target": "RACCT", "description": "GL account"},
            "DMBTR": {"target": "HSL", "description": "Amount in local currency"},
            "WRBTR": {"target": "TSL", "description": "Amount in doc currency"},
            "SHKZG": {"target": "DRCRK", "description": "Debit/Credit indicator"},
            "KOSTL": {"target": "RCNTR", "description": "Cost center"},
            "PRCTR": {"target": "PRCTR", "description": "Profit center"},
            "GSBER": {"target": "RBUSA", "description": "Business area"},
        },
        "new_required_fields": {
            "RLDNR": {"default": "0L", "description": "Ledger (0L = leading ledger)"},
            "RCLNT": {"default": "FROM_SOURCE", "description": "Client"},
            "DOCLN": {"default": "DERIVED", "description": "Document line (6 digits)"},
            "TIMESTAMP": {"default": "GENERATED", "description": "UTC timestamp"},
        },
        "notes": [
            "ACDOCA is a single table replacing ~12 ECC tables",
            "All amounts stored with currency key",
            "Multi-ledger entries stored as separate rows per ledger",
            "Reconciliation must check: sum(ACDOCA.HSL) = sum(BSEG.DMBTR) per document",
        ],
    },

    # ── MATERIALS: Material Document ──
    "material_documents": {
        "description": "Material movements → Single MATDOC table",
        "source_tables": ["MKPF", "MSEG"],
        "target_table": "MATDOC",
        "field_mapping": {
            # From MKPF (header)
            "MBLNR": {"target": "MBLNR", "description": "Material doc number"},
            "MJAHR": {"target": "MJAHR", "description": "Material doc year"},
            "BUDAT": {"target": "BUDAT_MKPF", "description": "Posting date"},
            "BLDAT": {"target": "BLDAT", "description": "Document date"},
            "USNAM": {"target": "USNAM_MKPF", "description": "User name"},
            # From MSEG (items)
            "ZEILE": {"target": "ZEILE", "description": "Line item"},
            "BWART": {"target": "BWART", "description": "Movement type"},
            "MATNR": {"target": "MATNR", "description": "Material number"},
            "WERKS": {"target": "WERKS", "description": "Plant"},
            "LGORT": {"target": "LGORT", "description": "Storage location"},
            "MENGE": {"target": "MENGE", "description": "Quantity"},
            "MEINS": {"target": "MEINS", "description": "Unit of measure"},
            "DMBTR": {"target": "DMBTR_STOCK", "description": "Amount"},
        },
        "notes": [
            "MATDOC combines header + item into one table",
            "Header fields get _MKPF suffix in MATDOC",
            "Material doc number format may change",
        ],
    },

    # ── BUSINESS PARTNER: Customer + Vendor → BP ──
    "business_partner": {
        "description": "Customer (KNA1) + Vendor (LFA1) → Business Partner (BUT000)",
        "source_tables": ["KNA1", "KNB1", "KNVV", "LFA1", "LFB1"],
        "target_table": "BUT000",
        "field_mapping": {
            # Customer (KNA1) → BP
            "KNA1.KUNNR": {"target": "PARTNER", "description": "BP number (auto-assigned or mapped)"},
            "KNA1.NAME1": {"target": "NAME_ORG1", "description": "Name line 1"},
            "KNA1.NAME2": {"target": "NAME_ORG2", "description": "Name line 2"},
            "KNA1.LAND1": {"target": "NATIONALITY", "description": "Country"},
            "KNA1.ORT01": {"target": "CITY", "description": "City (via ADRC)"},
            "KNA1.STRAS": {"target": "STREET", "description": "Street (via ADRC)"},
            # Vendor (LFA1) → BP
            "LFA1.LIFNR": {"target": "PARTNER", "description": "BP number"},
            "LFA1.NAME1": {"target": "NAME_ORG1", "description": "Name line 1"},
            "LFA1.LAND1": {"target": "NATIONALITY", "description": "Country"},
        },
        "bp_roles": {
            "customer": "FLCU00 (Customer)",
            "vendor": "FLVN00 (Vendor)",
            "customer_and_vendor": "FLCU00 + FLVN00",
        },
        "notes": [
            "Customers and vendors that represent the SAME entity must be merged into ONE BP",
            "BP number can be = customer number (recommended for simplicity)",
            "Address data moves to central address management (ADRC/BUT020)",
            "Company code data: KNB1→BUT0CK (customer), LFB1→BUT0CK (vendor)",
            "Sales area data: KNVV→BUT052 relationships",
            "SAP provides transaction BP_CVI for the conversion",
            "CRITICAL: Run duplicate check before conversion",
        ],
    },

    # ── CUSTOM Z-TABLES: Direct Migration ──
    "custom_tables": {
        "description": "Custom Z/Y tables — direct copy with validation",
        "approach": "direct_copy",
        "steps": [
            "1. Export table structure (DD02L, DD03L) from ECC",
            "2. Validate structure compatibility in S/4HANA DDIC",
            "3. Check for references to deprecated SAP tables",
            "4. Create table in S/4HANA if clean",
            "5. Export data via RFC_READ_TABLE in batches",
            "6. Import data via RFC or direct HANA SQL",
            "7. Verify row counts match",
        ],
        "batch_size": 10000,
        "notes": [
            "Custom tables usually migrate cleanly",
            "Watch for foreign keys referencing deprecated SAP tables",
            "HANA doesn't support cluster/pool tables — convert to transparent",
        ],
    },
}


# =============================================================================
# DATA EXTRACTION
# =============================================================================
def extract_table_data(conn, table_name, fields=None, batch_size=10000):
    """
    Extract data from an SAP table in batches via RFC.

    Uses RFC_READ_TABLE which has a 512-char row width limit.
    For wider tables, we call multiple times with different field sets.
    """
    all_rows = []
    offset = 0

    while True:
        params = {
            "QUERY_TABLE": table_name,
            "DELIMITER": "|",
            "ROWSKIPS": offset,
            "ROWCOUNT": batch_size,
        }

        if fields:
            params["FIELDS"] = [{"FIELDNAME": f} for f in fields]

        try:
            result = conn.call("RFC_READ_TABLE", **params)
        except Exception as e:
            logger.error(f"Error reading {table_name} at offset {offset}: {e}")
            break

        rows = result.get("DATA", [])
        if not rows:
            break

        field_names = [f["FIELDNAME"] for f in result.get("FIELDS", [])]

        for row in rows:
            values = row["WA"].split("|")
            row_dict = {}
            for i, fname in enumerate(field_names):
                row_dict[fname] = values[i].strip() if i < len(values) else ""
            all_rows.append(row_dict)

        offset += batch_size
        logger.info(f"Extracted {len(all_rows)} rows from {table_name}...")

        if len(rows) < batch_size:
            break

    return all_rows


def transform_finance_data(bkpf_rows, bseg_rows):
    """
    Transform BKPF + BSEG → ACDOCA format.
    Also executes preliminary hygiene sweeps (e.g. 00000000 to NULL for Date fields)
    """
    mapping = TABLE_MAPPINGS["finance_journal"]["field_mapping"]
    acdoca_rows = []

    # Cleanse source buffers first
    cleansed_bkpf = execute_cleaning_batch(bkpf_rows, "BKPF")
    cleansed_bseg = execute_cleaning_batch(bseg_rows, "BSEG")

    # Build header lookup
    headers = {}
    for row in cleansed_bkpf:
        key = f"{row.get('BUKRS','')}-{row.get('BELNR','')}-{row.get('GJAHR','')}"
        headers[key] = row

    # Merge header + line items
    for seg in cleansed_bseg:
        key = f"{seg.get('BUKRS','')}-{seg.get('BELNR','')}-{seg.get('GJAHR','')}"
        header = headers.get(key, {})

        acdoca_row = {
            "RLDNR": "0L",  # Leading ledger
            "RCLNT": header.get("MANDT", ""),
        }

        # Map header fields
        for source_field, target_info in mapping.items():
            value = header.get(source_field, "") or seg.get(source_field, "")
            if value:
                acdoca_row[target_info["target"]] = value

        # Generate new required fields
        acdoca_row["DOCLN"] = str(int(seg.get("BUZEI", "0"))).zfill(6)
        acdoca_row["TIMESTAMP"] = datetime.utcnow().strftime("%Y%m%d%H%M%S")

        acdoca_rows.append(acdoca_row)

    return acdoca_rows


def transform_bp_data(customers, vendors):
    """
    Transform Customer (KNA1) + Vendor (LFA1) → Business Partner.

    Production pipeline:
    1. Pre-validate all records (mandatory fields, ISO codes, tax ID format)
    2. Deduplicate within customers, within vendors, and cross-entity
    3. Detect number range overlaps between KUNNR and LIFNR
    4. Assign S/4HANA BP IDs with configurable conflict resolution strategy
    5. Generate formal cross-walk table (Old_ECC_ID → New_S4_BP_ID)
    6. Generate transactional data re-pointing instructions
    7. Persist all artifacts to S3
    """
    # ── Step 1: Pre-Validation ──
    pre_validation = run_bp_pre_validation(customers, vendors)
    remediation_report = generate_remediation_report(pre_validation)

    logger.info(
        f"Pre-validation: {pre_validation['summary']['total_with_issues']} entities "
        f"with issues ({pre_validation['summary']['critical_entities']} critical)"
    )

    # ── Step 2: Deduplication (fuzzy + cross-entity) ──
    mdm_results = process_cvi_deduplication(customers, vendors)

    # ── Step 3: Number Range Overlap Detection ──
    unique_customers = mdm_results["customers_to_create"]
    unique_vendors = mdm_results["vendors_to_create"]
    overlap_result = detect_id_overlaps(unique_customers, unique_vendors)

    logger.info(
        f"Number range overlaps: {overlap_result['overlap_count']} "
        f"conflicting IDs between customers and vendors"
    )

    # ── Step 4: BP ID Assignment with Conflict Resolution ──
    assignment = assign_bp_ids(
        unique_customers,
        unique_vendors,
        mdm_results["cross_entity_matches"],
    )

    # ── Step 5: Generate Re-pointing Instructions ──
    repointing = generate_repointing_instructions(
        assignment["remapped_vendors"],
        assignment["remapped_customers"],
        mdm_results["cross_entity_matches"],
    )

    # ── Step 6: Persist Cross-Walk to S3 ──
    try:
        crosswalk_keys = persist_crosswalk_to_s3(
            s3, STAGING_BUCKET,
            os.environ.get("CURRENT_RUN_ID", "manual-run"),
            assignment["crosswalk"],
            repointing,
            assignment["overlap_analysis"],
            assignment["strategy_used"],
        )
        crosswalk_s3_status = "success"
    except Exception as e:
        logger.warning(f"S3 crosswalk persistence failed (non-fatal): {e}")
        crosswalk_keys = {}
        crosswalk_s3_status = "failed"

    return {
        "status": "Deduplicated",
        "clean_bp_list": assignment["bp_records"],
        "crosswalk": assignment["crosswalk"],
        "crosswalk_s3_keys": crosswalk_keys,
        "crosswalk_s3_status": crosswalk_s3_status,
        "repointing_instructions": repointing,
        "pre_validation": pre_validation,
        "remediation_report": remediation_report,
        "overlap_analysis": assignment["overlap_analysis"],
        "number_range_strategy": assignment["strategy_used"],
        "conflicts_resolved": assignment["conflicts_resolved"],
        "mdm_metrics": mdm_results["stats"],
    }


# =============================================================================
# CVI (Customer-Vendor Integration) PREPARATION
# =============================================================================
# Data structural migration is performed by SAP SUM/DMO.
# This stage prepares and validates data for SUM readiness.

def prepare_cvi_synchronization(connection, customer_data, vendor_data):
    """
    Prepare Customer-Vendor Integration (CVI) synchronization for S/4HANA.

    Executes CVI_UPGRADE_CHECK_RESOLVE pre-checks via RFC to identify
    data quality issues that must be resolved before SUM/DMO can perform
    the actual Business Partner conversion.

    Returns:
        dict: CVI preparation results including mapping rules,
              overlap records, mandatory field gaps, and execution plan.
    """
    cvi_result = {
        "status": "assessed",
        "overlap_records": [],
        "mapping_rules": [],
        "mandatory_field_gaps": [],
        "execution_plan": [],
    }

    try:
        # Execute CVI_UPGRADE_CHECK_RESOLVE pre-checks via RFC
        result = connection.call("CVI_UPGRADE_CHECK_RESOLVE", **{
            "CHECK_MODE": "X",  # Check mode only, no changes
            "RESOLVE_MODE": "",
        })

        check_results = result.get("CHECK_RESULTS", [])
        for check in check_results:
            if check.get("CHECK_TYPE") == "OVERLAP":
                cvi_result["overlap_records"].append({
                    "customer": check.get("KUNNR", ""),
                    "vendor": check.get("LIFNR", ""),
                    "match_type": check.get("MATCH_TYPE", ""),
                    "resolution": check.get("RESOLUTION", ""),
                })

        logger.info(f"CVI pre-check completed: {len(check_results)} results")

    except Exception as e:
        logger.warning(f"CVI RFC pre-check failed (non-fatal): {e}")

    # Identify customer-vendor overlap records from extracted data
    customer_names = {c.get("NAME1", "").strip().upper(): c for c in customer_data if c.get("NAME1")}
    for vendor in vendor_data:
        vendor_name = vendor.get("NAME1", "").strip().upper()
        if vendor_name and vendor_name in customer_names:
            cvi_result["overlap_records"].append({
                "customer": customer_names[vendor_name].get("KUNNR", ""),
                "vendor": vendor.get("LIFNR", ""),
                "match_field": "NAME1",
                "match_value": vendor_name,
                "action": "MERGE_TO_SINGLE_BP",
            })

    # Generate CVI mapping rules
    cvi_result["mapping_rules"] = [
        {"rule": "CUSTOMER_TO_BP", "source": "KNA1", "target": "BUT000", "role": "FLCU00"},
        {"rule": "VENDOR_TO_BP", "source": "LFA1", "target": "BUT000", "role": "FLVN00"},
        {"rule": "OVERLAP_MERGE", "action": "Merge overlapping customer/vendor into single BP with dual roles"},
        {"rule": "ADDRESS_MIGRATION", "source": "KNA1/LFA1 address fields", "target": "ADRC/BUT020"},
        {"rule": "COMPANY_CODE_DATA", "source": "KNB1/LFB1", "target": "BUT0CK"},
    ]

    # Identify mandatory fields missing for Business Partner model
    bp_mandatory_fields = ["NAME1", "LAND1", "ORT01", "PSTLZ", "STRAS"]
    for entity_type, records in [("customer", customer_data), ("vendor", vendor_data)]:
        for record in records:
            missing = []
            for field in bp_mandatory_fields:
                if not record.get(field, "").strip():
                    missing.append(field)
            if missing:
                cvi_result["mandatory_field_gaps"].append({
                    "entity_type": entity_type,
                    "id": record.get("KUNNR", "") or record.get("LIFNR", ""),
                    "missing_fields": missing,
                    "severity": "critical" if "NAME1" in missing or "LAND1" in missing else "warning",
                })

    # Create CVI execution plan
    cvi_result["execution_plan"] = [
        {"step": 1, "action": "Resolve mandatory field gaps", "count": len(cvi_result["mandatory_field_gaps"])},
        {"step": 2, "action": "Resolve customer-vendor overlaps", "count": len(cvi_result["overlap_records"])},
        {"step": 3, "action": "Configure BP number ranges and groupings", "tool": "SPRO"},
        {"step": 4, "action": "Execute CVI synchronization", "tool": "Transaction BP_CVI"},
        {"step": 5, "action": "Validate BP creation and role assignment", "tool": "Transaction BP"},
    ]

    logger.info(
        f"CVI preparation complete: {len(cvi_result['overlap_records'])} overlaps, "
        f"{len(cvi_result['mandatory_field_gaps'])} field gaps"
    )

    return cvi_result


def assess_finance_data_readiness(connection, finance_data):
    """
    Assess finance data readiness for S/4HANA ACDOCA migration.

    Data structural migration is performed by SAP SUM/DMO.
    This function validates that finance data is clean and compatible
    before SUM executes FINS_MASS_DATA_MONITOR for the actual conversion.

    Checks:
        - BSEG/BSIS/BSAS data consistency
        - Open items validation for ACDOCA compatibility
        - FINS_MASS_DATA_MONITOR runtime estimation
        - Data quality issues that would block finance migration

    Returns:
        dict: Finance readiness assessment with compatibility scores and issues.
    """
    readiness = {
        "status": "assessed",
        "bseg_consistency": {"status": "pending"},
        "open_items_validation": {"status": "pending"},
        "fins_runtime_estimate": {"status": "pending"},
        "data_quality_issues": [],
        "acdoca_compatibility_score": 0.0,
    }

    bkpf_data = finance_data.get("bkpf", [])
    bseg_data = finance_data.get("bseg", [])

    # Check BSEG/BSIS/BSAS data consistency
    consistency_issues = 0
    orphan_line_items = 0
    header_keys = set()
    for row in bkpf_data:
        key = f"{row.get('BUKRS', '')}-{row.get('BELNR', '')}-{row.get('GJAHR', '')}"
        header_keys.add(key)

    for seg in bseg_data:
        key = f"{seg.get('BUKRS', '')}-{seg.get('BELNR', '')}-{seg.get('GJAHR', '')}"
        if key not in header_keys:
            orphan_line_items += 1

        # Check for zero-amount line items (potential data quality issue)
        dmbtr = seg.get("DMBTR", "0")
        wrbtr = seg.get("WRBTR", "0")
        try:
            if float(dmbtr) == 0 and float(wrbtr) == 0:
                consistency_issues += 1
        except (ValueError, TypeError):
            consistency_issues += 1

    readiness["bseg_consistency"] = {
        "status": "ok" if orphan_line_items == 0 and consistency_issues < 10 else "warning",
        "total_headers": len(bkpf_data),
        "total_line_items": len(bseg_data),
        "orphan_line_items": orphan_line_items,
        "zero_amount_items": consistency_issues,
    }

    # Validate open items for ACDOCA compatibility
    open_items = [s for s in bseg_data if s.get("AUGBL", "") == "" or s.get("AUGBL") is None]
    readiness["open_items_validation"] = {
        "status": "ok" if len(open_items) < len(bseg_data) else "warning",
        "total_open_items": len(open_items),
        "total_cleared_items": len(bseg_data) - len(open_items),
        "open_ratio": f"{len(open_items) / max(len(bseg_data), 1) * 100:.1f}%",
        "acdoca_note": "Open items will be migrated with clearing status preserved in ACDOCA",
    }

    # Estimate FINS_MASS_DATA_MONITOR runtime
    # Rule of thumb: ~1M records per hour for FINS migration on typical HANA hardware
    total_records = len(bseg_data) + len(bkpf_data)
    estimated_hours = max(total_records / 1000000, 0.5)  # Minimum 30 minutes
    readiness["fins_runtime_estimate"] = {
        "status": "ok",
        "total_records_to_migrate": total_records,
        "estimated_hours": round(estimated_hours, 1),
        "estimated_tables": ["BSIS→ACDOCA", "BSAS→ACDOCA", "BSEG→ACDOCA", "COEP→ACDOCA"],
        "recommendation": "Schedule FINS_MASS_DATA_MONITOR during maintenance window",
    }

    # Flag data quality issues that would block finance migration
    if orphan_line_items > 0:
        readiness["data_quality_issues"].append({
            "issue": "ORPHAN_LINE_ITEMS",
            "severity": "critical",
            "count": orphan_line_items,
            "description": "BSEG line items without matching BKPF header — must resolve before SUM",
            "resolution": "Run SAPF190 to clean up orphaned documents",
        })

    if consistency_issues > 100:
        readiness["data_quality_issues"].append({
            "issue": "ZERO_AMOUNT_ITEMS",
            "severity": "warning",
            "count": consistency_issues,
            "description": "Line items with zero amounts in both local and document currency",
            "resolution": "Review and archive zero-value documents if not needed",
        })

    # Check for HANA-incompatible data types via RFC if connection available
    try:
        result = connection.call("RFC_READ_TABLE", **{
            "QUERY_TABLE": "DD03L",
            "DELIMITER": "|",
            "FIELDS": [{"FIELDNAME": "TABNAME"}, {"FIELDNAME": "FIELDNAME"}, {"FIELDNAME": "DATATYPE"}],
            "OPTIONS": [{"TEXT": "TABNAME = 'BSEG' AND DATATYPE = 'RAWSTRING'"}],
            "ROWCOUNT": 100,
        })
        raw_fields = result.get("DATA", [])
        if raw_fields:
            readiness["data_quality_issues"].append({
                "issue": "RAWSTRING_FIELDS",
                "severity": "warning",
                "count": len(raw_fields),
                "description": "BSEG contains RAWSTRING fields requiring special HANA handling",
            })
    except Exception:
        pass  # Non-fatal: skip DDIC check if RFC not available

    # Calculate overall compatibility score
    issue_count = len(readiness["data_quality_issues"])
    critical_count = sum(1 for i in readiness["data_quality_issues"] if i.get("severity") == "critical")
    if critical_count > 0:
        readiness["acdoca_compatibility_score"] = max(0.0, 60.0 - (critical_count * 20))
    elif issue_count > 0:
        readiness["acdoca_compatibility_score"] = max(70.0, 95.0 - (issue_count * 5))
    else:
        readiness["acdoca_compatibility_score"] = 98.0

    readiness["status"] = "ready" if critical_count == 0 else "blocked"

    logger.info(
        f"Finance readiness assessment complete: score={readiness['acdoca_compatibility_score']}, "
        f"issues={issue_count}, critical={critical_count}"
    )

    return readiness


# =============================================================================
# MAIN HANDLER
# =============================================================================
def lambda_handler(event, context):
    """
    Main entry point for Data Assessment & CVI Preparation.

    Data structural migration is performed by SAP SUM/DMO.
    This stage prepares and validates data for SUM readiness.

    Handles extraction, transformation, assessment, and staging of migration data.
    """
    logger.info(f"Data Assessment & CVI Preparation started")
    log_stage_event("data-assessment", "Pipeline Start", "IN_PROGRESS", {"stage": 3})
    _stage_start = __import__('time').time()

    run_id = event.get("metadata", {}).get("run_id", "manual-run")
    discovery = event.get("discovery", {})

    results = {
        "finance": {"status": "pending", "records": 0},
        "materials": {"status": "pending", "records": 0},
        "business_partner": {"status": "pending", "records": 0},
        "custom_tables": {"status": "pending", "tables": 0, "records": 0},
    }

    try:
        # Try RFC connection
        try:
            from pyrfc import Connection
            conn_params = json.loads(
                boto3.client("secretsmanager")
                .get_secret_value(SecretId=os.environ.get("SECRETS_ARN", ""))
                ["SecretString"]
            )
            from pyrfc import Connection
            conn = Connection(**conn_params)
            has_rfc = True
        except (ImportError, Exception):
            has_rfc = False
            logger.warning("No RFC — generating migration plan only")

        if has_rfc:
            # ── Finance Migration ──
            logger.info("Extracting finance data...")
            bkpf = extract_table_data(conn, "BKPF", ["BUKRS","BELNR","GJAHR","BLDAT","BUDAT","MONAT","BLART","WAERS"])
            bseg = extract_table_data(conn, "BSEG", ["BUKRS","BELNR","GJAHR","BUZEI","KOART","HKONT","DMBTR","WRBTR","SHKZG","KOSTL","PRCTR"])
            acdoca_data = transform_finance_data(bkpf, bseg)

            s3.put_object(
                Bucket=STAGING_BUCKET,
                Key=f"migrations/{run_id}/data/finance/acdoca.json",
                Body=json.dumps(acdoca_data[:10000], default=str),  # Sample
            )
            results["finance"] = {"status": "extracted", "records": len(acdoca_data)}

            # ── BP Conversion (with Pre-Validation, Cross-Walk, Re-pointing) ──
            logger.info("Extracting customer/vendor data for BP conversion...")
            customers = extract_table_data(conn, "KNA1",
                ["KUNNR","NAME1","NAME2","LAND1","ORT01","STRAS","PSTLZ","TELF1","STCD1","STCD3","SMTP_ADDR","KTOKD"])
            vendors = extract_table_data(conn, "LFA1",
                ["LIFNR","NAME1","NAME2","LAND1","ORT01","STRAS","PSTLZ","TELF1","STCD1","STCD3","SMTP_ADDR","KTOKK"])
            os.environ["CURRENT_RUN_ID"] = run_id
            bp_data = transform_bp_data(customers, vendors)

            s3.put_object(
                Bucket=STAGING_BUCKET,
                Key=f"migrations/{run_id}/data/bp-conversion/business_partners.json",
                Body=json.dumps(bp_data["clean_bp_list"], default=str),
            )
            # Persist pre-validation report
            s3.put_object(
                Bucket=STAGING_BUCKET,
                Key=f"migrations/{run_id}/data/bp-conversion/pre-validation-report.json",
                Body=json.dumps(bp_data["pre_validation"], indent=2, default=str),
                ContentType="application/json",
            )
            s3.put_object(
                Bucket=STAGING_BUCKET,
                Key=f"migrations/{run_id}/data/bp-conversion/remediation-report.json",
                Body=json.dumps(bp_data["remediation_report"], indent=2, default=str),
                ContentType="application/json",
            )
            results["business_partner"] = {
                "status": "converted",
                "customers": len(customers),
                "vendors": len(vendors),
                "bp_records": len(bp_data["clean_bp_list"]),
                "merged_duplicates": bp_data["mdm_metrics"]["total_merged"],
                "cross_entity_matches": bp_data["mdm_metrics"]["cross_entity_matches"],
                "number_range_conflicts": bp_data["overlap_analysis"]["overlap_count"],
                "conflicts_resolved": bp_data["conflicts_resolved"],
                "number_range_strategy": bp_data["number_range_strategy"],
                "pre_validation": bp_data["pre_validation"]["summary"],
                "repointing_summary": bp_data["repointing_instructions"]["summary"],
                "crosswalk_entries": len(bp_data["crosswalk"]),
            }

        # ── CVI Preparation ──
        # Data structural migration is performed by SAP SUM/DMO.
        # This stage prepares and validates data for SUM readiness.
        cvi_preparation = {"status": "skipped", "message": "No RFC connection for CVI pre-checks"}
        if has_rfc:
            try:
                cvi_preparation = prepare_cvi_synchronization(conn, customers, vendors)
            except Exception as e:
                logger.warning(f"CVI preparation failed (non-fatal): {e}")
                cvi_preparation = {"status": "error", "error": str(e)}
        else:
            # Generate estimated CVI assessment from extracted data
            cvi_preparation = prepare_cvi_synchronization(
                type('MockConn', (), {'call': lambda *a, **kw: (_ for _ in ()).throw(Exception("mock"))})(),
                customers if 'customers' in dir() else [],
                vendors if 'vendors' in dir() else [],
            ) if has_rfc is False and 'customers' in dir() else cvi_preparation

        results["cvi_preparation"] = cvi_preparation

        # ── Finance Readiness Assessment ──
        finance_readiness = {"status": "skipped", "message": "No finance data extracted for assessment"}
        if has_rfc:
            try:
                finance_readiness = assess_finance_data_readiness(
                    conn,
                    {"bkpf": bkpf, "bseg": bseg},
                )
            except Exception as e:
                logger.warning(f"Finance readiness assessment failed (non-fatal): {e}")
                finance_readiness = {"status": "error", "error": str(e)}

        results["finance_readiness"] = finance_readiness

        # ── Data Quality Report ──
        # Consolidate all data quality issues that must be resolved before SUM
        data_quality_issues = []
        if isinstance(cvi_preparation, dict):
            for gap in cvi_preparation.get("mandatory_field_gaps", []):
                if gap.get("severity") == "critical":
                    data_quality_issues.append({
                        "area": "CVI",
                        "entity_type": gap.get("entity_type", ""),
                        "id": gap.get("id", ""),
                        "issue": f"Missing mandatory BP fields: {', '.join(gap.get('missing_fields', []))}",
                        "severity": "critical",
                        "blocks_sum": True,
                    })
        if isinstance(finance_readiness, dict):
            for issue in finance_readiness.get("data_quality_issues", []):
                data_quality_issues.append({
                    "area": "FINANCE",
                    "issue": issue.get("description", ""),
                    "severity": issue.get("severity", "warning"),
                    "count": issue.get("count", 0),
                    "resolution": issue.get("resolution", ""),
                    "blocks_sum": issue.get("severity") == "critical",
                })

        results["data_quality_report"] = {
            "total_issues": len(data_quality_issues),
            "critical_issues": sum(1 for i in data_quality_issues if i.get("severity") == "critical"),
            "blocking_issues": sum(1 for i in data_quality_issues if i.get("blocks_sum")),
            "issues": data_quality_issues[:500],  # Cap for payload size
            "sum_readiness": "BLOCKED" if any(i.get("blocks_sum") for i in data_quality_issues) else "READY",
        }

        # Save mapping documentation regardless
        s3.put_object(
            Bucket=STAGING_BUCKET,
            Key=f"migrations/{run_id}/data/table-mappings.json",
            Body=json.dumps(TABLE_MAPPINGS, indent=2, default=str),
            ContentType="application/json",
        )

        # Save CVI preparation report
        s3.put_object(
            Bucket=STAGING_BUCKET,
            Key=f"migrations/{run_id}/data/cvi-preparation-report.json",
            Body=json.dumps(cvi_preparation, indent=2, default=str),
            ContentType="application/json",
        )

        # Save finance readiness report
        s3.put_object(
            Bucket=STAGING_BUCKET,
            Key=f"migrations/{run_id}/data/finance-readiness-report.json",
            Body=json.dumps(finance_readiness, indent=2, default=str),
            ContentType="application/json",
        )

        # Save data quality report
        s3.put_object(
            Bucket=STAGING_BUCKET,
            Key=f"migrations/{run_id}/data/data-quality-report.json",
            Body=json.dumps(results["data_quality_report"], indent=2, default=str),
            ContentType="application/json",
        )

        # Summary
        s3_key = f"migrations/{run_id}/data/assessment-summary.json"
        s3.put_object(
            Bucket=STAGING_BUCKET,
            Key=s3_key,
            Body=json.dumps(results, indent=2, default=str),
        )

        total_records = sum(
            r.get("records", 0) or r.get("bp_records", 0)
            for r in results.values()
            if isinstance(r, dict) and ("records" in r or "bp_records" in r)
        )

        log_stage_event("data-assessment", "Assessment Complete", "SUCCESS", {
            "total_records": total_records,
            "cvi_overlaps": len(cvi_preparation.get("overlap_records", [])) if isinstance(cvi_preparation, dict) else 0,
            "finance_score": finance_readiness.get("acdoca_compatibility_score", 0) if isinstance(finance_readiness, dict) else 0,
            "data_quality_issues": len(data_quality_issues),
            "sum_readiness": results["data_quality_report"]["sum_readiness"],
        }, (__import__('time').time() - _stage_start) * 1000)
        return {
            "status": "success",
            "results": results,
            "total_records_processed": total_records,
            "cvi_preparation": cvi_preparation,
            "finance_readiness": finance_readiness,
            "data_quality_report": results["data_quality_report"],
            "s3_key": s3_key,
            "run_id": run_id,
        }

    except Exception as e:
        logger.error(f"Data assessment failed: {str(e)}")
        log_stage_event("data-assessment", "Assessment Failed", "ERROR", str(e))
        raise
