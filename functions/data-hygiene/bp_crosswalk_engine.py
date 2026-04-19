"""
bp_crosswalk_engine.py - CVI Cross-Walk Table & Transactional Re-pointing
===========================================================================
Produces the formal ECC-to-S/4HANA Business Partner mapping table and
generates transactional data re-pointing instructions for all documents
that reference remapped Customer/Vendor IDs.

The cross-walk table is the single source of truth for:
  - Which ECC Customer/Vendor became which S/4HANA BP
  - Which IDs were remapped to avoid number range conflicts
  - Which entities were merged (cross-entity deduplication)
  - What BP roles were assigned

Transactional Re-pointing covers:
  - Purchase Orders (EKKO.LIFNR, EKPO.LIFNR)
  - Vendor Invoices (RBKP.LIFNR)
  - Vendor Open Items (BSIK.LIFNR, BSAK.LIFNR)
  - Sales Orders (VBAK.KUNNR, VBAK.KUNAG)
  - Billing Documents (VBRK.KUNAG, VBRK.KUNRG)
  - Customer Open Items (BSID.KUNNR, BSAD.KUNNR)

These re-pointing instructions are persisted alongside the cross-walk
so the data-loader can apply them during Stage 9.
"""

import logging
import os
import json
from typing import List, Dict, Any, Optional, Set
from datetime import datetime

logger = logging.getLogger("bp_crosswalk")
logger.setLevel(logging.INFO)

# Number range conflict resolution strategy
# CUSTOMER_PRIORITY: Customer keeps original ID; vendor gets offset
# VENDOR_PRIORITY: Vendor keeps original ID; customer gets offset
# INTERNAL: Both get new sequential IDs from internal range
NUMBER_RANGE_STRATEGY = os.environ.get("BP_NUMBER_RANGE_STRATEGY", "CUSTOMER_PRIORITY")

# Offset applied to remapped IDs (default: 5 billion — well above typical ECC ranges)
VENDOR_BP_OFFSET = int(os.environ.get("BP_VENDOR_OFFSET", "5000000000"))
CUSTOMER_BP_OFFSET = int(os.environ.get("BP_CUSTOMER_OFFSET", "5000000000"))

# Internal numbering start (used when strategy = INTERNAL)
INTERNAL_BP_START = int(os.environ.get("BP_INTERNAL_START", "3000000000"))


# =============================================================================
# NUMBER RANGE CONFLICT DETECTION
# =============================================================================

def detect_id_overlaps(
    customers: List[Dict[str, Any]],
    vendors: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Detect overlapping IDs between Customer (KUNNR) and Vendor (LIFNR) ranges.

    In ECC, KUNNR and LIFNR are separate namespaces. In S/4HANA, both map
    to a single BP ID (PARTNER). If KUNNR=1001 and LIFNR=1001 exist,
    one must be remapped.

    Returns:
        {
            "overlapping_ids": set of IDs that exist in both,
            "customer_only_ids": set,
            "vendor_only_ids": set,
            "overlap_count": int,
            "overlap_details": list of {id, customer_name, vendor_name},
        }
    """
    customer_ids = {}
    for c in customers:
        kunnr = c.get("KUNNR", "").strip()
        if kunnr:
            customer_ids[kunnr] = c.get("NAME1", "")

    vendor_ids = {}
    for v in vendors:
        lifnr = v.get("LIFNR", "").strip()
        if lifnr:
            vendor_ids[lifnr] = v.get("NAME1", "")

    customer_set = set(customer_ids.keys())
    vendor_set = set(vendor_ids.keys())

    overlapping = customer_set & vendor_set
    customer_only = customer_set - vendor_set
    vendor_only = vendor_set - customer_set

    overlap_details = []
    for oid in sorted(overlapping):
        overlap_details.append({
            "id": oid,
            "customer_name": customer_ids[oid],
            "vendor_name": vendor_ids[oid],
        })

    logger.info(
        f"Number range analysis: {len(overlapping)} overlapping IDs, "
        f"{len(customer_only)} customer-only, {len(vendor_only)} vendor-only"
    )

    return {
        "overlapping_ids": overlapping,
        "customer_only_ids": customer_only,
        "vendor_only_ids": vendor_only,
        "overlap_count": len(overlapping),
        "overlap_details": overlap_details[:100],  # Sample for reporting
    }


# =============================================================================
# BP ID ASSIGNMENT WITH CONFLICT RESOLUTION
# =============================================================================

def assign_bp_ids(
    customers: List[Dict[str, Any]],
    vendors: List[Dict[str, Any]],
    cross_entity_matches: List[Dict[str, Any]],
    strategy: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Assign S/4HANA BP IDs using configurable conflict resolution strategy.

    Handles three scenarios:
      1. Non-overlapping IDs → keep original
      2. Overlapping IDs → remap based on strategy
      3. Cross-entity matches (same entity is both customer & vendor) → single BP

    Returns:
        {
            "bp_records": list of complete BP records with assigned IDs,
            "crosswalk": list of crosswalk entries,
            "remapped_vendors": dict of {old_lifnr: new_bp_id},
            "remapped_customers": dict of {old_kunnr: new_bp_id},
            "conflicts_resolved": int,
            "strategy_used": str,
        }
    """
    if strategy is None:
        strategy = NUMBER_RANGE_STRATEGY

    # Step 1: Detect overlaps
    overlap_result = detect_id_overlaps(customers, vendors)
    overlapping_ids = overlap_result["overlapping_ids"]

    # Step 2: Build cross-entity merge set (customer KUNNR that matched a vendor LIFNR)
    merged_vendors: Set[str] = set()  # Vendor LIFNRs absorbed into a customer BP
    merged_customers: Set[str] = set()  # Customer KUNNRs absorbed into a vendor BP
    merge_map: Dict[str, str] = {}  # vendor LIFNR -> customer KUNNR (or vice versa)

    for match in cross_entity_matches:
        cust_id = match.get("customer", "").strip()
        vend_id = match.get("vendor", "").strip()
        if cust_id and vend_id:
            merged_vendors.add(vend_id)
            merge_map[vend_id] = cust_id

    # Step 3: Assign BP IDs
    bp_records = []
    crosswalk = []
    remapped_vendors: Dict[str, str] = {}
    remapped_customers: Dict[str, str] = {}
    internal_counter = INTERNAL_BP_START

    # --- Process Customers ---
    for cust in customers:
        kunnr = cust.get("KUNNR", "").strip()
        if not kunnr:
            continue

        if strategy == "INTERNAL":
            bp_id = str(internal_counter).zfill(10)
            internal_counter += 1
            id_action = "INTERNAL_ASSIGNED"
            remapped_customers[kunnr] = bp_id
        elif strategy == "VENDOR_PRIORITY" and kunnr in overlapping_ids:
            # Customer gets remapped
            try:
                raw_num = int(kunnr)
                bp_id = str(raw_num + CUSTOMER_BP_OFFSET).zfill(10)
            except ValueError:
                bp_id = str(internal_counter).zfill(10)
                internal_counter += 1
                logger.warning(f"Non-numeric KUNNR '{kunnr}' cannot use offset; assigned internal BP ID {bp_id}")
            id_action = "REMAPPED_OFFSET"
            remapped_customers[kunnr] = bp_id
        else:
            # CUSTOMER_PRIORITY (default) or no conflict: customer keeps ID
            bp_id = kunnr
            id_action = "RETAINED"

        # Check if this customer also matched a vendor (cross-entity)
        absorbed_vendor = None
        bp_role = "FLCU00"
        for match in cross_entity_matches:
            if match.get("customer", "").strip() == kunnr:
                absorbed_vendor = match.get("vendor", "").strip()
                bp_role = "FLCU00,FLVN00"
                break

        bp_records.append({
            "PARTNER": bp_id,
            "TYPE": "2",
            "NAME_ORG1": cust.get("NAME1", "")[:40],
            "NAME_ORG2": cust.get("NAME2", "")[:40],
            "NATIONALITY": cust.get("LAND1", ""),
            "CITY": cust.get("ORT01", ""),
            "STREET": cust.get("STRAS", ""),
            "POSTAL_CODE": cust.get("PSTLZ", ""),
            "TAX_ID": cust.get("STCD1", cust.get("STCD3", "")),
            "EMAIL": cust.get("SMTP_ADDR", ""),
            "TELEPHONE": cust.get("TELF1", ""),
            "BP_ROLE": bp_role,
            "BP_GROUPING": "BPCU",
            "SOURCE": "KNA1",
            "SOURCE_KEY": kunnr,
            "MERGED_FROM": [absorbed_vendor] if absorbed_vendor else [],
        })

        crosswalk_entry = {
            "ecc_table": "KNA1",
            "ecc_id": kunnr,
            "ecc_name": cust.get("NAME1", ""),
            "name": cust.get("NAME1", "")[:40],
            "s4_bp_id": bp_id,
            "bp_role": bp_role,
            "bp_grouping": "BPCU",
            "source_type": "CUSTOMER",
            "id_action": id_action,
            "merged_from_vendor": absorbed_vendor,
        }
        if id_action == "REMAPPED_OFFSET":
            crosswalk_entry["original_id_conflict"] = kunnr
        crosswalk.append(crosswalk_entry)

        # If a vendor was absorbed, add a crosswalk entry for that vendor too
        if absorbed_vendor:
            crosswalk.append({
                "ecc_table": "LFA1",
                "ecc_id": absorbed_vendor,
                "ecc_name": "(merged into customer)",
                "name": cust.get("NAME1", "")[:40],
                "s4_bp_id": bp_id,
                "bp_role": "FLVN00",
                "bp_grouping": "BPCU",
                "source_type": "VENDOR_MERGED",
                "id_action": "MERGED_INTO_CUSTOMER",
                "merged_into_bp": bp_id,
                "merged_into_customer": kunnr,
            })
            remapped_vendors[absorbed_vendor] = bp_id

    # --- Process Vendors (exclude merged ones) ---
    for vendor in vendors:
        lifnr = vendor.get("LIFNR", "").strip()
        if not lifnr or lifnr in merged_vendors:
            continue

        if strategy == "INTERNAL":
            bp_id = str(internal_counter).zfill(10)
            internal_counter += 1
            id_action = "INTERNAL_ASSIGNED"
            remapped_vendors[lifnr] = bp_id
        elif strategy == "CUSTOMER_PRIORITY" and lifnr in overlapping_ids:
            # Vendor gets remapped (default strategy)
            try:
                raw_num = int(lifnr)
                bp_id = str(raw_num + VENDOR_BP_OFFSET).zfill(10)
            except ValueError:
                bp_id = str(internal_counter).zfill(10)
                internal_counter += 1
                logger.warning(f"Non-numeric LIFNR '{lifnr}' cannot use offset; assigned internal BP ID {bp_id}")
            id_action = "REMAPPED_OFFSET"
            remapped_vendors[lifnr] = bp_id
        elif strategy == "VENDOR_PRIORITY":
            bp_id = lifnr
            id_action = "RETAINED"
        else:
            # No conflict
            bp_id = lifnr
            id_action = "RETAINED"

        bp_records.append({
            "PARTNER": bp_id,
            "TYPE": "2",
            "NAME_ORG1": vendor.get("NAME1", "")[:40],
            "NAME_ORG2": vendor.get("NAME2", "")[:40],
            "NATIONALITY": vendor.get("LAND1", ""),
            "CITY": vendor.get("ORT01", ""),
            "STREET": vendor.get("STRAS", ""),
            "POSTAL_CODE": vendor.get("PSTLZ", ""),
            "TAX_ID": vendor.get("STCD1", vendor.get("STCD3", "")),
            "EMAIL": vendor.get("SMTP_ADDR", ""),
            "TELEPHONE": vendor.get("TELF1", ""),
            "BP_ROLE": "FLVN00",
            "BP_GROUPING": "BPVN",
            "SOURCE": "LFA1",
            "SOURCE_KEY": lifnr,
            "MERGED_FROM": [],
        })

        crosswalk_entry = {
            "ecc_table": "LFA1",
            "ecc_id": lifnr,
            "ecc_name": vendor.get("NAME1", ""),
            "name": vendor.get("NAME1", "")[:40],
            "s4_bp_id": bp_id,
            "bp_role": "FLVN00",
            "bp_grouping": "BPVN",
            "source_type": "VENDOR",
            "id_action": id_action,
        }
        if id_action == "REMAPPED_OFFSET":
            crosswalk_entry["original_id_conflict"] = lifnr
        crosswalk.append(crosswalk_entry)

    conflicts_resolved = sum(
        1 for e in crosswalk if e["id_action"] in ("REMAPPED_OFFSET", "INTERNAL_ASSIGNED", "MERGED_INTO_CUSTOMER")
    )

    logger.info(
        f"BP ID assignment complete: {len(bp_records)} BPs, "
        f"{conflicts_resolved} conflicts resolved via {strategy}"
    )

    return {
        "bp_records": bp_records,
        "crosswalk": crosswalk,
        "remapped_vendors": remapped_vendors,
        "remapped_customers": remapped_customers,
        "overlap_analysis": {
            "overlap_count": overlap_result["overlap_count"],
            "overlap_details": overlap_result["overlap_details"],
        },
        "conflicts_resolved": conflicts_resolved,
        "strategy_used": strategy,
    }


# =============================================================================
# TRANSACTIONAL DATA RE-POINTING ENGINE
# =============================================================================

# SAP tables and fields that reference Customer/Vendor IDs.
# After BP ID remapping, these documents must be updated.
VENDOR_REFERENCE_TABLES = [
    {"table": "EKKO", "field": "LIFNR", "description": "Purchase Order Header"},
    {"table": "EKPO", "field": "LIFNR", "description": "Purchase Order Item (if assigned)"},
    {"table": "RBKP", "field": "LIFNR", "description": "Incoming Invoice Header"},
    {"table": "BSIK", "field": "LIFNR", "description": "Vendor Open Items (Accounting)"},
    {"table": "BSAK", "field": "LIFNR", "description": "Vendor Cleared Items (Accounting)"},
    {"table": "LFC1", "field": "LIFNR", "description": "Vendor Transaction Figures"},
    {"table": "LFC3", "field": "LIFNR", "description": "Vendor Special GL Transaction Figures"},
    {"table": "LFBK", "field": "LIFNR", "description": "Vendor Bank Details"},
]

CUSTOMER_REFERENCE_TABLES = [
    {"table": "VBAK", "field": "KUNNR", "description": "Sales Order Header (sold-to)"},
    {"table": "VBAK", "field": "KUNAG", "description": "Sales Order Header (ship-to)"},
    {"table": "VBRK", "field": "KUNAG", "description": "Billing Document (payer)"},
    {"table": "VBRK", "field": "KUNRG", "description": "Billing Document (bill-to)"},
    {"table": "BSID", "field": "KUNNR", "description": "Customer Open Items (Accounting)"},
    {"table": "BSAD", "field": "KUNNR", "description": "Customer Cleared Items (Accounting)"},
    {"table": "KNC1", "field": "KUNNR", "description": "Customer Transaction Figures"},
    {"table": "KNC3", "field": "KUNNR", "description": "Customer Special GL Transaction Figures"},
    {"table": "KNBK", "field": "KUNNR", "description": "Customer Bank Details"},
]


def generate_repointing_instructions(
    remapped_vendors: Dict[str, str],
    remapped_customers: Dict[str, str],
    cross_entity_matches: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Generate transactional data re-pointing instructions for all documents
    that reference remapped Customer/Vendor IDs.

    For each remapped ID, produces:
      - The SAP table and field to update
      - The old ID value and new BP ID value
      - An estimated affected document count (populated during execution)

    These instructions are executed by the data-loader (Stage 9) via
    RFC_FUNCTION_MODULE or direct SQL on HANA.

    Returns:
        {
            "vendor_repoints": list of re-pointing instructions,
            "customer_repoints": list of re-pointing instructions,
            "merged_entity_repoints": list for cross-entity merges,
            "total_instructions": int,
            "summary": {...},
        }
    """
    vendor_repoints = []
    customer_repoints = []
    merged_repoints = []

    # --- Vendor re-pointing (for remapped vendor IDs) ---
    for old_lifnr, new_bp_id in remapped_vendors.items():
        for ref in VENDOR_REFERENCE_TABLES:
            vendor_repoints.append({
                "table": ref["table"],
                "field": ref["field"],
                "description": ref["description"],
                "old_value": old_lifnr,
                "new_value": new_bp_id,
                "where_clause": f"{ref['field']} = '{old_lifnr}'",
                "update_type": "VENDOR_REMAP",
            })

    # --- Customer re-pointing (for remapped customer IDs — rare, only in VENDOR_PRIORITY mode) ---
    for old_kunnr, new_bp_id in remapped_customers.items():
        for ref in CUSTOMER_REFERENCE_TABLES:
            customer_repoints.append({
                "table": ref["table"],
                "field": ref["field"],
                "description": ref["description"],
                "old_value": old_kunnr,
                "new_value": new_bp_id,
                "where_clause": f"{ref['field']} = '{old_kunnr}'",
                "update_type": "CUSTOMER_REMAP",
            })

    # --- Cross-entity merge re-pointing ---
    # When vendor V is merged into customer C's BP, all V's vendor docs
    # now point to C's BP ID
    for match in cross_entity_matches:
        vend_id = match.get("vendor", "").strip()
        cust_id = match.get("customer", "").strip()
        if vend_id and cust_id:
            # Vendor documents now point to the customer's BP
            for ref in VENDOR_REFERENCE_TABLES:
                merged_repoints.append({
                    "table": ref["table"],
                    "field": ref["field"],
                    "description": ref["description"],
                    "old_value": vend_id,
                    "new_value": cust_id,  # The merged BP uses customer's ID
                    "where_clause": f"{ref['field']} = '{vend_id}'",
                    "update_type": "CROSS_ENTITY_MERGE",
                    "merge_reason": f"Vendor {vend_id} merged into Customer {cust_id} (same entity)",
                })

    total = len(vendor_repoints) + len(customer_repoints) + len(merged_repoints)

    logger.info(
        f"Re-pointing instructions generated: {total} total "
        f"({len(vendor_repoints)} vendor, {len(customer_repoints)} customer, "
        f"{len(merged_repoints)} cross-entity merge)"
    )

    return {
        "vendor_repoints": vendor_repoints,
        "customer_repoints": customer_repoints,
        "merged_entity_repoints": merged_repoints,
        "total_instructions": total,
        "summary": {
            "vendors_remapped": len(remapped_vendors),
            "customers_remapped": len(remapped_customers),
            "cross_entity_merges": len(cross_entity_matches),
            "vendor_repoint_count": len(vendor_repoints),
            "customer_repoint_count": len(customer_repoints),
            "merge_repoint_count": len(merged_repoints),
            "tables_affected": sorted(set(
                r["table"] for r in vendor_repoints + customer_repoints + merged_repoints
            )),
        },
    }


# =============================================================================
# CROSS-WALK TABLE PERSISTENCE
# =============================================================================

def persist_crosswalk_to_s3(
    s3_client,
    bucket: str,
    run_id: str,
    crosswalk: List[Dict],
    repointing: Dict[str, Any],
    overlap_analysis: Dict[str, Any],
    strategy: str,
) -> Dict[str, str]:
    """
    Persist the cross-walk table and re-pointing instructions to S3.

    Creates three artifacts:
      1. crosswalk-table.json — The full ECC_ID → S4_BP_ID mapping
      2. repointing-instructions.json — Transactional data update plan
      3. crosswalk-summary.json — Human-readable summary for consultants

    Returns: dict of S3 keys written.
    """
    base_key = f"migrations/{run_id}/data/bp-conversion"
    keys = {}

    # 1. Full cross-walk table
    crosswalk_payload = {
        "metadata": {
            "generated_at": datetime.utcnow().isoformat(),
            "run_id": run_id,
            "strategy": strategy,
            "total_entries": len(crosswalk),
        },
        "crosswalk_entries": crosswalk,
    }
    key = f"{base_key}/crosswalk-table.json"
    s3_client.put_object(
        Bucket=bucket, Key=key,
        Body=json.dumps(crosswalk_payload, indent=2, default=str),
        ContentType="application/json",
    )
    keys["crosswalk_table"] = key

    # 2. Re-pointing instructions
    repointing_payload = {
        "metadata": {
            "generated_at": datetime.utcnow().isoformat(),
            "run_id": run_id,
        },
        **repointing,
    }
    key = f"{base_key}/repointing-instructions.json"
    s3_client.put_object(
        Bucket=bucket, Key=key,
        Body=json.dumps(repointing_payload, indent=2, default=str),
        ContentType="application/json",
    )
    keys["repointing_instructions"] = key

    # 3. Human-readable summary
    retained = sum(1 for e in crosswalk if e["id_action"] == "RETAINED")
    remapped = sum(1 for e in crosswalk if e["id_action"] == "REMAPPED_OFFSET")
    merged = sum(1 for e in crosswalk if e["id_action"] == "MERGED_INTO_CUSTOMER")
    internal = sum(1 for e in crosswalk if e["id_action"] == "INTERNAL_ASSIGNED")

    summary_payload = {
        "title": "Business Partner Cross-Walk Summary",
        "generated_at": datetime.utcnow().isoformat(),
        "run_id": run_id,
        "strategy": strategy,
        "id_assignment": {
            "total_bp_entries": len(crosswalk),
            "ids_retained": retained,
            "ids_remapped_offset": remapped,
            "ids_merged_cross_entity": merged,
            "ids_internal_assigned": internal,
        },
        "number_range_conflicts": {
            "overlapping_ids": overlap_analysis.get("overlap_count", 0),
            "resolution_strategy": strategy,
            "sample_conflicts": overlap_analysis.get("overlap_details", [])[:20],
        },
        "repointing_summary": repointing.get("summary", {}),
    }
    key = f"{base_key}/crosswalk-summary.json"
    s3_client.put_object(
        Bucket=bucket, Key=key,
        Body=json.dumps(summary_payload, indent=2, default=str),
        ContentType="application/json",
    )
    keys["crosswalk_summary"] = key

    logger.info(f"Cross-walk artifacts persisted to S3: {list(keys.values())}")
    return keys


def persist_crosswalk_to_dynamodb(
    dynamodb_client,
    table_name: str,
    run_id: str,
    crosswalk: List[Dict],
) -> int:
    """
    Persist cross-walk entries to Cosmos DB for real-time lookup during
    data loading (Stage 9) and post-migration validation (Stage 13).

    Table schema:
      PK: RUN_ID#ECC_TABLE#ECC_ID
      SK: S4_BP_ID
      Attributes: bp_role, bp_grouping, id_action, source_type, etc.

    Returns: number of items written.
    """
    written = 0
    try:
        table = dynamodb_client.Table(table_name)
        with table.batch_writer() as batch:
            for entry in crosswalk:
                pk = f"{run_id}#{entry['ecc_table']}#{entry['ecc_id']}"
                item = {
                    "PK": pk,
                    "SK": entry["s4_bp_id"],
                    "run_id": run_id,
                    "ecc_table": entry["ecc_table"],
                    "ecc_id": entry["ecc_id"],
                    "s4_bp_id": entry["s4_bp_id"],
                    "bp_role": entry.get("bp_role", ""),
                    "bp_grouping": entry.get("bp_grouping", ""),
                    "source_type": entry.get("source_type", ""),
                    "id_action": entry.get("id_action", ""),
                    "ecc_name": entry.get("ecc_name", ""),
                }
                if entry.get("original_id_conflict"):
                    item["original_id_conflict"] = entry["original_id_conflict"]
                if entry.get("merged_into_bp"):
                    item["merged_into_bp"] = entry["merged_into_bp"]
                batch.put_item(Item=item)
                written += 1
    except Exception as e:
        logger.warning(f"Cosmos DB crosswalk write failed (non-fatal): {e}")

    logger.info(f"Cross-walk: {written} entries written to Cosmos DB container {table_name}")
    return written


# =============================================================================
# RE-POINTING EXECUTOR (for Stage 9 data-loader)
# =============================================================================

def execute_repointing(conn, repointing: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply transactional data re-pointing via RFC on the S/4HANA target system.

    For each re-pointing instruction, issues an UPDATE via a custom Z function
    module (Z_M4H_REPOINT_ID) or via ADBC SQL execution.

    Returns execution summary with success/failure counts.
    """
    results = {"applied": 0, "failed": 0, "skipped": 0, "errors": []}

    all_instructions = (
        repointing.get("vendor_repoints", []) +
        repointing.get("customer_repoints", []) +
        repointing.get("merged_entity_repoints", [])
    )

    for instr in all_instructions:
        try:
            # Use RFC to update the reference
            conn.call("Z_M4H_REPOINT_ID", **{
                "TABLE_NAME": instr["table"],
                "FIELD_NAME": instr["field"],
                "OLD_VALUE": instr["old_value"],
                "NEW_VALUE": instr["new_value"],
            })
            results["applied"] += 1
        except Exception as e:
            results["failed"] += 1
            if len(results["errors"]) < 50:
                results["errors"].append({
                    "table": instr["table"],
                    "field": instr["field"],
                    "old": instr["old_value"],
                    "new": instr["new_value"],
                    "error": str(e),
                })

    logger.info(
        f"Re-pointing execution: {results['applied']} applied, "
        f"{results['failed']} failed, {results['skipped']} skipped"
    )
    return results
