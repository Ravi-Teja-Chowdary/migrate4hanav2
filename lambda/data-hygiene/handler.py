"""
Migrate4HANA — Stage 5: Data Hygiene
======================================
Master data cleansing: BP deduplication, pre-validation, cross-walk table
generation, and MDM data cleansing.

This handler orchestrates all data hygiene sub-modules:
- BP Pre-Validation Engine (field-level quality checks)
- BP Deduplication Engine (fuzzy-match and CVI merge)
- BP Cross-Walk Engine (ECC→S/4HANA ID mapping + re-pointing)
- MDM Data Cleanser (finance date normalization, material leading zeros)
"""

import json
import os
import sys
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from bp_pre_validation_engine import run_bp_pre_validation, generate_remediation_report
from bp_deduplication_engine import process_cvi_deduplication
from bp_crosswalk_engine import assign_bp_ids, detect_id_overlaps, generate_repointing_instructions
from mdm_data_cleanser import execute_cleaning_batch


def lambda_handler(event, context):
    """AWS Lambda entry point for data hygiene processing."""
    logger.info("Data Hygiene handler invoked")

    try:
        customers = event.get("customers", [])
        vendors = event.get("vendors", [])
        finance_records = event.get("finance_records", [])
        custom_tables = event.get("custom_tables", {})
        output_bucket = event.get("output_bucket", "")
        run_id = event.get("run_id", "unknown")

        # Step 1: BP Pre-Validation
        logger.info(f"Running BP pre-validation on {len(customers)} customers, {len(vendors)} vendors")
        validation_result = run_bp_pre_validation(customers, vendors)
        remediation_actions = generate_remediation_report(validation_result)

        # Step 2: BP Deduplication (CVI merge)
        logger.info("Running BP deduplication / CVI merge")
        dedup_result = process_cvi_deduplication(customers, vendors)

        # Step 3: Cross-Walk Table & ID Assignment
        logger.info("Generating cross-walk table and BP ID assignments")
        merged_entities = dedup_result.get("merged_entities", [])
        overlaps = detect_id_overlaps(customers, vendors)
        bp_assignments = assign_bp_ids(
            customers=customers,
            vendors=vendors,
            dedup_result=dedup_result,
            overlaps=overlaps
        )
        repointing = generate_repointing_instructions(bp_assignments)

        # Step 4: MDM Data Cleansing
        logger.info("Running MDM data cleansing on finance records")
        cleaned_finance = execute_cleaning_batch(finance_records, "BKPF")
        cleaned_tables = {}
        for table_name, records in custom_tables.items():
            cleaned_tables[table_name] = execute_cleaning_batch(records, table_name)

        result = {
            "status": "SUCCESS",
            "run_id": run_id,
            "validation": {
                "total_entities": validation_result.get("total_entities", 0),
                "valid": validation_result.get("valid", 0),
                "invalid": validation_result.get("invalid", 0),
                "remediation_actions": len(remediation_actions),
            },
            "deduplication": {
                "duplicates_found": dedup_result.get("duplicates_found", 0),
                "duplicates_merged": dedup_result.get("duplicates_merged", 0),
                "bp_created": dedup_result.get("bp_created", 0),
            },
            "crosswalk": {
                "bp_assignments": len(bp_assignments.get("assignments", [])),
                "number_range_overlaps": overlaps.get("total_overlaps", 0),
                "repointing_instructions": len(repointing.get("instructions", [])),
            },
            "cleaning": {
                "finance_records_cleaned": len(cleaned_finance),
                "custom_tables_cleaned": len(cleaned_tables),
            },
        }

        logger.info(f"Data Hygiene complete: {json.dumps(result, default=str)}")
        return result

    except Exception as e:
        logger.error(f"Data Hygiene failed: {str(e)}", exc_info=True)
        return {
            "status": "FAILED",
            "error": str(e),
        }
