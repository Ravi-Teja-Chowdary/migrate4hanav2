"""
rule_router.py - DynamoDB Rule Retriever
Fetches ABAP Simplification Rules and Validation Rules dynamically from DynamoDB.
Falls back to local static JSON if DynamoDB is unreachable.
"""
import os
import json
import logging
import boto3
from botocore.exceptions import ClientError
from typing import List, Dict, Any

logger = logging.getLogger("dynamodb_rule_router")
logger.setLevel(logging.INFO)

# Initialize DynamoDB resource
DYNAMODB_TABLE_NAME = os.environ.get("RULES_TABLE_NAME", "sap-simplification-rules")
dynamodb = boto3.resource('dynamodb')

# Module-level cache: rule sets rarely change within a single process run,
# so we cache by category to avoid repeated DynamoDB scans (and log spam).
_RULES_CACHE: Dict[str, List[Dict[str, Any]]] = {}

def get_simplification_rules(category: str = None) -> List[Dict[str, Any]]:
    """
    Fetches rules from DynamoDB. If category is provided, filters by category using GSI.
    """
    cache_key = category or "__all__"
    if cache_key in _RULES_CACHE:
        return _RULES_CACHE[cache_key]
    table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    
    try:
        if category:
            # Query using Global Secondary Index for efficient category retrieval
            response = table.query(
                IndexName="CategoryIndex",
                KeyConditionExpression=boto3.dynamodb.conditions.Key('category').eq(category)
            )
            rules = response.get('Items', [])
            logger.info(f"DynamoDB Rule Router: Fetched {len(rules)} rules for category '{category}'")
            return rules
        else:
            # Scan all if no category specified (less efficient, use carefully)
            response = table.scan()
            rules = response.get('Items', [])
            logger.info(f"DynamoDB Rule Router: Scanned and fetched {len(rules)} total rules.")
            if not rules:
                # Empty table (e.g. local-shim or unprovisioned env) → use static fallback
                rules = _get_fallback_rules(category)
            _RULES_CACHE[cache_key] = rules
            return rules
            
    except ClientError as e:
        logger.error(f"Failed to fetch rules from DynamoDB: {e}. Falling back to static JSON rules.")
        return _get_fallback_rules(category)
    except Exception as e:
        logger.error(f"Unexpected error when fetching rules: {e}")
        return _get_fallback_rules(category)

def _get_fallback_rules(category: str = None) -> List[Dict[str, Any]]:
    """Emergency fallback to full static rule set if DynamoDB is offline."""
    fallback = [
        # === SYNTAX — Obsolete ABAP constructs ===
        {"rule_id": "OBS_001", "category": "SYNTAX",
         "ecc_pattern": "DATA: .* OCCURS .*",
         "s4_replacement": "DATA: .* TYPE TABLE OF .*",
         "description": "Replace obsolete OCCURS table declarations."},
        {"rule_id": "OBS_002", "category": "SYNTAX",
         "ecc_pattern": "MOVE .* TO .*",
         "s4_replacement": ".* = .*",
         "description": "Replace MOVE … TO with inline assignment."},
        {"rule_id": "OBS_003", "category": "SYNTAX",
         "ecc_pattern": "COMPUTE .*",
         "s4_replacement": ".* = .*",
         "description": "Replace COMPUTE with direct assignment."},
        {"rule_id": "OBS_004", "category": "SYNTAX",
         "ecc_pattern": "IF .* EQ .*",
         "s4_replacement": "IF .* = .*",
         "description": "Replace obsolete EQ/NE/GT/LT with =/<>/>/<."},
        {"rule_id": "OBS_005", "category": "SYNTAX",
         "ecc_pattern": "CALL METHOD (\\w+)->(\\w+)",
         "s4_replacement": "\\1->\\2( )",
         "description": "Replace CALL METHOD with functional method call."},
        {"rule_id": "OBS_006", "category": "SYNTAX",
         "ecc_pattern": "CREATE OBJECT (\\w+) TYPE (\\w+)",
         "s4_replacement": "\\1 = NEW \\2( )",
         "description": "Replace CREATE OBJECT with NEW constructor."},
        {"rule_id": "OBS_007", "category": "SYNTAX",
         "ecc_pattern": "FORM .* USING .*",
         "s4_replacement": "METHOD .* IMPORTING .*",
         "description": "Migrate FORM/PERFORM to CLASS/METHOD."},
        {"rule_id": "OBS_008", "category": "SYNTAX",
         "ecc_pattern": "RANGES .* FOR .*",
         "s4_replacement": "DATA: .* TYPE RANGE OF .*",
         "description": "Replace obsolete RANGES with TYPE RANGE OF."},
        # === DATA_MODEL — Table/view changes ===
        {"rule_id": "DB_001", "category": "DATA_MODEL",
         "ecc_pattern": "SELECT .* FROM BSEG",
         "s4_replacement": "SELECT .* FROM ACDOCA WHERE RLDNR = '0L'",
         "description": "Redirect BSEG reads to Universal Journal ACDOCA."},
        {"rule_id": "DB_002", "category": "DATA_MODEL",
         "ecc_pattern": "SELECT .* FROM BKPF",
         "s4_replacement": "SELECT .* FROM ACDOCA WHERE RLDNR = '0L'",
         "description": "Redirect BKPF reads to ACDOCA."},
        {"rule_id": "DB_003", "category": "DATA_MODEL",
         "ecc_pattern": "SELECT .* FROM KONV",
         "s4_replacement": "SELECT .* FROM PRCD_ELEMENTS",
         "description": "KONV replaced by PRCD_ELEMENTS in S/4HANA."},
        {"rule_id": "DB_004", "category": "DATA_MODEL",
         "ecc_pattern": "SELECT .* FROM MKPF",
         "s4_replacement": "SELECT .* FROM MATDOC",
         "description": "MKPF/MSEG merged into MATDOC."},
        {"rule_id": "DB_005", "category": "DATA_MODEL",
         "ecc_pattern": "SELECT .* FROM MSEG",
         "s4_replacement": "SELECT .* FROM MATDOC",
         "description": "MSEG merged into MATDOC in S/4HANA."},
        {"rule_id": "DB_006", "category": "DATA_MODEL",
         "ecc_pattern": "SELECT .* FROM KNA1",
         "s4_replacement": "SELECT .* FROM BUT000 / I_Customer CDS",
         "description": "KNA1 customer master → Business Partner (BUT000)."},
        {"rule_id": "DB_007", "category": "DATA_MODEL",
         "ecc_pattern": "SELECT .* FROM LFA1",
         "s4_replacement": "SELECT .* FROM BUT000 / I_Supplier CDS",
         "description": "LFA1 vendor master → Business Partner (BUT000)."},
        {"rule_id": "DB_008", "category": "DATA_MODEL",
         "ecc_pattern": "SELECT .* FROM VBRK",
         "s4_replacement": "SELECT .* FROM I_BillingDocument CDS",
         "description": "VBRK billing docs → CDS view recommended."},
        {"rule_id": "DB_009", "category": "DATA_MODEL",
         "ecc_pattern": "SELECT .* FROM EKKO",
         "s4_replacement": "SELECT .* FROM I_PurchaseOrderAPI01 CDS",
         "description": "EKKO purchasing → CDS view for decoupled access."},
        {"rule_id": "DB_010", "category": "DATA_MODEL",
         "ecc_pattern": "SELECT .* FROM LIPS",
         "s4_replacement": "SELECT .* FROM I_DeliveryDocumentItem CDS",
         "description": "LIPS delivery items → CDS view recommended."},
        # === BAPI — Deprecated BAPIs ===
        {"rule_id": "BAPI_001", "category": "BAPI",
         "ecc_pattern": "BAPI_CUSTOMER_CREATEFROMDATA1",
         "s4_replacement": "BAPI_BUPA_CREATE_FROM_DATA",
         "description": "Customer creation BAPI replaced by BP BAPI."},
        {"rule_id": "BAPI_002", "category": "BAPI",
         "ecc_pattern": "BAPI_VENDOR_CREATE",
         "s4_replacement": "BAPI_BUPA_CREATE_FROM_DATA",
         "description": "Vendor creation BAPI replaced by BP BAPI."},
        {"rule_id": "BAPI_003", "category": "BAPI",
         "ecc_pattern": "BAPI_GL_ACC_GETPERIODBALANCES",
         "s4_replacement": "BAPI_FAGL_GET_BALANCES",
         "description": "Classic GL balance BAPI → new GL balance BAPI."},
        {"rule_id": "BAPI_004", "category": "BAPI",
         "ecc_pattern": "BAPI_COSTCENTER_GETLIST",
         "s4_replacement": "I_CostCenter CDS view",
         "description": "Cost center BAPI → CDS view in S/4HANA."},
        # === ALV — Report display migration ===
        {"rule_id": "ALV_001", "category": "ALV",
         "ecc_pattern": "CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'",
         "s4_replacement": "CL_SALV_TABLE=>FACTORY( )",
         "description": "Classic ALV function module → SALV OO framework."},
        {"rule_id": "ALV_002", "category": "ALV",
         "ecc_pattern": "CALL FUNCTION 'REUSE_ALV_LIST_DISPLAY'",
         "s4_replacement": "CL_SALV_TABLE=>FACTORY( )",
         "description": "Classic ALV list → SALV OO framework."},
        # === FIORI — UI migration patterns ===
        {"rule_id": "FIORI_001", "category": "FIORI",
         "ecc_pattern": "CALL TRANSACTION '(FB50|FB60|VA01|ME21N)'",
         "s4_replacement": "Navigate to Fiori App (F0718/F0711/F3893/F0842A)",
         "description": "Replace CALL TRANSACTION with Fiori semantic navigation."},
        {"rule_id": "FIORI_002", "category": "FIORI",
         "ecc_pattern": "SET PF-STATUS",
         "s4_replacement": "Fiori action button configuration",
         "description": "GUI status bars replaced by Fiori action sheets."},
        # === SECURITY — Authorization changes ===
        {"rule_id": "SEC_001", "category": "SECURITY",
         "ecc_pattern": "AUTHORITY-CHECK OBJECT 'F_BKPF_BUK'",
         "s4_replacement": "AUTHORITY-CHECK OBJECT 'F_ACDOC_BUK'",
         "description": "BKPF auth object → ACDOC auth object for Universal Journal."},
        {"rule_id": "SEC_002", "category": "SECURITY",
         "ecc_pattern": "AUTHORITY-CHECK OBJECT 'V_VBAK_VKO'",
         "s4_replacement": "AUTHORITY-CHECK OBJECT 'V_VBAK_VKO' + BP auth objects",
         "description": "SD auth objects need BP extension for CVI."},
        # === PERFORMANCE — Query optimization ===
        {"rule_id": "PERF_001", "category": "PERFORMANCE",
         "ecc_pattern": "SELECT \\* FROM .*",
         "s4_replacement": "SELECT <field_list> FROM … (explicit columns)",
         "description": "Avoid SELECT * on HANA — use explicit field lists."},
        {"rule_id": "PERF_002", "category": "PERFORMANCE",
         "ecc_pattern": "SELECT .* INTO TABLE .* FROM .* FOR ALL ENTRIES IN",
         "s4_replacement": "Code pushdown via CDS view or AMDP",
         "description": "FOR ALL ENTRIES → CDS JOIN for HANA code pushdown."},
    ]
    if category:
        return [r for r in fallback if r.get('category') == category]
    logger.info(f"Using static fallback rules: {len(fallback)} rules available")
    return fallback
