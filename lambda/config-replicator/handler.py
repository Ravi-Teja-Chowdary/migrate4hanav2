"""
Migrate4HANA — Stage 4: Config & Org Structure Replicator
==========================================================
Extracts SPRO customizing settings and org structure from ECC
and prepares them for replay on S/4HANA.

DevOps Analogy:
SPRO = SAP's equivalent of Ansible vars / Terraform variables.
It's a tree of ~100,000+ configuration entries that control how
every business process works. Think of it as the world's largest
config management system.

What we extract:
- Company code settings (currencies, fiscal year variants, chart of accounts)
- Plant settings (MRP, valuation, logistics)
- Sales org settings (pricing, shipping, billing)
- Controlling area settings (cost element accounting, profitability analysis)
- Number ranges (like auto-increment sequences for documents)
- Output determination (print forms, emails)
"""

import json
import os
import logging
import boto3
import sys

# Ensure global config module can be imported natively
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from global_config_framework import generate_spro_payload

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'utils')))
from logger import log_stage_event

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
STAGING_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hana-staging-dev")


# =============================================================================
# CONFIG TABLE DEFINITIONS
# =============================================================================
# These are the critical SPRO configuration tables that must be migrated.
# Grouped by functional area.

CONFIG_TABLES = {
    "finance": {
        "description": "Financial Accounting Configuration",
        "tables": {
            "T001": {
                "description": "Company Code Global Parameters",
                "fields": ["BUKRS", "BUTXT", "ORT01", "LAND1", "WAERS", "SPRAS",
                           "KTOPL", "PERIV", "XGJRV", "XKONT"],
                "key": "BUKRS",
            },
            "T004": {
                "description": "Chart of Accounts Directory",
                "fields": ["KTOPL", "KTPLB", "XBILK"],
                "key": "KTOPL",
            },
            "T009": {
                "description": "Fiscal Year Variants",
                "fields": ["PERIV", "XJABH", "ANPTS"],
                "key": "PERIV",
            },
            "T003": {
                "description": "Document Types",
                "fields": ["BLART", "BLTYP", "NUMKR", "XNETB"],
                "key": "BLART",
            },
            "T030": {
                "description": "GL Account Determination (Auto-posting)",
                "fields": ["KTOPL", "KTOSL", "BUKRS", "KONTS"],
                "key": "KTOPL,KTOSL",
            },
            "BNKA": {
                "description": "Bank Master Data",
                "fields": ["BANKS", "BANKL", "BANKA", "STRAS", "ORT01", "SWIFT"],
                "key": "BANKS,BANKL",
            },
        },
    },
    "controlling": {
        "description": "Controlling Configuration",
        "tables": {
            "TKA01": {
                "description": "Controlling Areas",
                "fields": ["KOKRS", "BEZEI", "WAERS", "KTOPL", "GSBER", "BUKRS"],
                "key": "KOKRS",
            },
            "TKA02": {
                "description": "Controlling Area Assignment to Company Codes",
                "fields": ["KOKRS", "BUKRS"],
                "key": "KOKRS,BUKRS",
            },
            "CSKS": {
                "description": "Cost Center Master (Header)",
                "fields": ["KOKRS", "KOSTL", "DATBI", "DATAB", "KOSAR", "VERAK"],
                "key": "KOKRS,KOSTL,DATBI",
            },
            "CEPC": {
                "description": "Profit Center Master",
                "fields": ["PRCTR", "KOKRS", "DATBI", "DATAB", "BUKRS"],
                "key": "PRCTR,KOKRS,DATBI",
            },
        },
    },
    "materials_management": {
        "description": "Materials Management Configuration",
        "tables": {
            "T001W": {
                "description": "Plants",
                "fields": ["WERKS", "NAME1", "BUKRS", "LAND1", "FABKL", "TXJCD"],
                "key": "WERKS",
            },
            "T001L": {
                "description": "Storage Locations",
                "fields": ["WERKS", "LGORT", "LGOBE"],
                "key": "WERKS,LGORT",
            },
            "T024": {
                "description": "Purchasing Groups",
                "fields": ["EKGRP", "EKNAM"],
                "key": "EKGRP",
            },
            "T024E": {
                "description": "Purchasing Organizations",
                "fields": ["EKORG", "EKOTX", "BUKRS"],
                "key": "EKORG",
            },
            "T134": {
                "description": "Material Types",
                "fields": ["MTART", "MTREF", "MBREF", "WBREF"],
                "key": "MTART",
            },
        },
    },
    "sales_distribution": {
        "description": "Sales & Distribution Configuration",
        "tables": {
            "TVKO": {
                "description": "Sales Organizations",
                "fields": ["VKORG", "WAESSION", "BUKRS", "VKOEX"],
                "key": "VKORG",
            },
            "TVTW": {
                "description": "Distribution Channels",
                "fields": ["VTWEG", "VTEXT"],
                "key": "VTWEG",
            },
            "TSPA": {
                "description": "Divisions",
                "fields": ["SPART", "VTEXT"],
                "key": "SPART",
            },
            "TVKWZ": {
                "description": "Sales Org → Plant Assignment",
                "fields": ["VKORG", "VTWEG", "SPART", "WERKS"],
                "key": "VKORG,VTWEG,SPART,WERKS",
            },
        },
    },
    "number_ranges": {
        "description": "Number Range Configuration",
        "tables": {
            "NRIV": {
                "description": "Number Range Intervals",
                "fields": ["OBJECT", "SUBOBJECT", "NRRANGENR", "FROMNUMBER",
                           "TONUMBER", "NRLEVEL", "EXTERNIND"],
                "key": "OBJECT,SUBOBJECT,NRRANGENR",
            },
        },
    },
}

# S/4HANA-specific new config that needs to be set up
S4_NEW_CONFIG = {
    "fiori_launchpad": {
        "description": "Fiori Launchpad configuration (new in S/4HANA)",
        "settings": [
            "Theme configuration (Quartz / Horizon)",
            "Launchpad spaces and pages",
            "App catalog assignments",
            "Target mappings for custom apps",
        ],
    },
    "business_partner": {
        "description": "BP number range and synchronization settings",
        "settings": [
            "BP number range (SNRO object BU_PARTNER)",
            "Customer-Vendor Integration (CVI) sync direction",
            "BP role category mapping",
            "BP grouping configuration",
        ],
    },
    "simplified_finance": {
        "description": "New finance settings for Universal Journal",
        "settings": [
            "Ledger configuration (leading vs non-leading)",
            "Currency types per ledger",
            "Extension ledger settings",
            "Margin analysis (COPA) integration",
        ],
    },
    "output_management": {
        "description": "New output management framework (replaces NACE)",
        "settings": [
            "Output types → BRF+ rules",
            "Adobe Forms → Fiori print forms",
            "Email templates",
        ],
    },
}


def extract_config_tables(conn):
    """Extract all configuration tables from ECC."""
    all_config = {}

    for area_key, area in CONFIG_TABLES.items():
        logger.info(f"Extracting config area: {area['description']}")
        all_config[area_key] = {
            "description": area["description"],
            "tables": {},
        }

        for table_name, table_def in area["tables"].items():
            try:
                result = conn.call(
                    "RFC_READ_TABLE",
                    QUERY_TABLE=table_name,
                    DELIMITER="|",
                    FIELDS=[{"FIELDNAME": f} for f in table_def["fields"]],
                    ROWCOUNT=50000,
                )

                rows = []
                for row in result.get("DATA", []):
                    values = row["WA"].split("|")
                    row_dict = {}
                    for i, field in enumerate(table_def["fields"]):
                        row_dict[field] = values[i].strip() if i < len(values) else ""
                    rows.append(row_dict)

                all_config[area_key]["tables"][table_name] = {
                    "description": table_def["description"],
                    "row_count": len(rows),
                    "data": rows,
                }

                logger.info(f"  {table_name}: {len(rows)} entries")

            except Exception as e:
                logger.warning(f"  {table_name}: Error - {str(e)}")
                all_config[area_key]["tables"][table_name] = {
                    "description": table_def["description"],
                    "error": str(e),
                }

    return all_config


def generate_s4_config_checklist(config_data):
    """
    Generate a checklist of S/4HANA-specific configurations
    that need to be set up based on the extracted ECC config.
    """
    checklist = []

    # Check finance config → Universal Journal settings needed
    finance = config_data.get("finance", {}).get("tables", {})
    if finance.get("T001", {}).get("data"):
        company_codes = finance["T001"]["data"]
        checklist.append({
            "area": "Simplified Finance",
            "task": "Configure Universal Journal ledgers",
            "detail": f"Set up ACDOCA for {len(company_codes)} company codes",
            "priority": "critical",
            "s4_transaction": "FINSC_LEDGER",
        })

    # Check if multiple currencies → extension ledger might be needed
    currencies = set()
    for cc in finance.get("T001", {}).get("data", []):
        currencies.add(cc.get("WAERS", ""))
    if len(currencies) > 1:
        checklist.append({
            "area": "Multi-Currency",
            "task": "Configure parallel currencies in Universal Journal",
            "detail": f"Currencies found: {', '.join(currencies)}",
            "priority": "high",
            "s4_transaction": "FINSC_LEDGER",
        })

    # BP conversion config
    checklist.append({
        "area": "Business Partner",
        "task": "Configure BP number ranges and CVI synchronization",
        "detail": "Required for customer/vendor to BP conversion",
        "priority": "critical",
        "s4_transaction": "BUCF",
    })

    # Fiori setup
    checklist.append({
        "area": "Fiori Launchpad",
        "task": "Configure Fiori Launchpad spaces and catalogs",
        "detail": "Map existing T-codes to Fiori apps",
        "priority": "high",
        "s4_transaction": "/UI2/FLPD_CUST",
    })

    # Add all new S/4 configs
    for config_key, config in S4_NEW_CONFIG.items():
        for setting in config["settings"]:
            checklist.append({
                "area": config["description"],
                "task": setting,
                "priority": "medium",
            })

    return checklist


# =============================================================================
# MAIN HANDLER
# =============================================================================
def lambda_handler(event, context):
    """Config & Org Structure Replicator main handler."""
    logger.info("Config Replicator started")
    log_stage_event("config-replicator", "Pipeline Start", "IN_PROGRESS", {"stage": 4})
    _stage_start = __import__('time').time()

    run_id = event.get("metadata", {}).get("run_id", "manual-run")

    try:
        # Try RFC connection
        try:
            from pyrfc import Connection
            conn_params = json.loads(
                boto3.client("secretsmanager")
                .get_secret_value(SecretId=os.environ.get("SECRETS_ARN", ""))
                ["SecretString"]
            )
            conn = Connection(**conn_params)
            has_rfc = True
        except ImportError:
            logger.error("pyrfc not available — cannot connect to SAP")
            has_rfc = False
        except Exception as e:
            logger.error(f"RFC connection error: {e}")
            has_rfc = False

        if has_rfc:
            try:
                config_data = extract_config_tables(conn)
            finally:
                conn.close()
        else:
            logger.warning("No RFC — generating config template only")
            config_data = {
                area: {"description": info["description"], "tables": {
                    t: {"description": d["description"], "row_count": 0, "data": []}
                    for t, d in info["tables"].items()
                }}
                for area, info in CONFIG_TABLES.items()
            }

        # Generate User Context S/4 checklist
        checklist = generate_s4_config_checklist(config_data)

        # Apply Global Dynamic Configuration logic
        # Extract BUKRS directly from payload or mock
        discovered_company_codes = []
        if finance := config_data.get("finance", {}).get("tables", {}):
             if t001 := finance.get("T001", {}).get("data"):
                 discovered_company_codes = [cc.get("BUKRS", "") for cc in t001 if cc.get("BUKRS")]
                 
        if not discovered_company_codes:
            # Fallback for unconnected instances
            discovered_company_codes = ["1000", "2000", "3000", "4000"]
            
        global_config_payload = generate_spro_payload(discovered_company_codes)

        # Save everything to S3
        s3.put_object(
            Bucket=STAGING_BUCKET,
            Key=f"migrations/{run_id}/config/ecc-config-dump.json",
            Body=json.dumps(config_data, indent=2, default=str),
        )

        s3.put_object(
            Bucket=STAGING_BUCKET,
            Key=f"migrations/{run_id}/config/s4-config-checklist.json",
            Body=json.dumps(checklist, indent=2),
        )

        s3.put_object(
            Bucket=STAGING_BUCKET,
            Key=f"migrations/{run_id}/config/global-config-payload.json",
            Body=json.dumps(global_config_payload, indent=2),
        )

        s3.put_object(
            Bucket=STAGING_BUCKET,
            Key=f"migrations/{run_id}/config/s4-new-config-reference.json",
            Body=json.dumps(S4_NEW_CONFIG, indent=2),
        )

        total_entries = sum(
            table_data.get("row_count", 0)
            for area in config_data.values()
            for table_data in area.get("tables", {}).values()
        )

        result = {
            "status": "success",
            "config_areas": len(config_data),
            "total_config_entries": total_entries,
            "s4_checklist_items": len(checklist),
            "s3_key": f"migrations/{run_id}/config/",
            "run_id": run_id,
            "global_config_generated": True,
            "mapped_regions": len(discovered_company_codes)
        }
        log_stage_event("config-replicator", "Config Replication Complete", "SUCCESS", result, (__import__('time').time() - _stage_start) * 1000)
        return result

    except Exception as e:
        logger.error(f"Config replication failed: {str(e)}")
        log_stage_event("config-replicator", "Config Replication Failed", "ERROR", str(e))
        raise
