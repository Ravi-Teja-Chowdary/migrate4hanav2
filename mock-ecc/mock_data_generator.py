"""
Migrate4HANA — Mock SAP ECC Data Generator
============================================
Generates realistic SAP ECC data that mirrors a mid-size Indian
manufacturing + distribution company.

Company Profile (fictional):
  Name: "Bharat Industrial Solutions Pvt Ltd"
  Industry: Manufacturing + Distribution
  Employees: ~2,000
  Revenue: ₹500 Cr (~$60M)
  Locations: 4 plants across India + 1 in UAE
  ERP: SAP ECC 6.0 EHP8 on Oracle DB

This mock data generator creates:
- 1,200+ custom ABAP programs
- 90+ custom tables
- 380+ custom function modules
- 4 company codes, 12 plants, 8 sales orgs
- 340+ PFCG roles, 1,800+ users
- 65+ RFC destinations, 20+ IDoc partners
- Complete org structure
- Finance, Materials, SD master + transaction data
- Realistic code with actual ABAP patterns (including bugs to find!)

Every piece of data here is structured EXACTLY like real SAP tables
return via RFC_READ_TABLE — same field names, same delimiters, same
data formats. When we switch to a real system, the code just works.
"""

import json
import random
import os
from datetime import datetime, timedelta

random.seed(42)  # Reproducible data


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================
def random_date(start_year=2015, end_year=2024):
    start = datetime(start_year, 1, 1)
    end = datetime(end_year, 12, 31)
    delta = end - start
    return (start + timedelta(days=random.randint(0, delta.days))).strftime("%Y%m%d")


def random_user():
    first = random.choice([
        "RAVI", "PRIYA", "AMIT", "SUNITA", "VIJAY", "ANITA", "RAJESH",
        "DEEPA", "SURESH", "KAVITA", "MAHESH", "NEHA", "ARUN", "POOJA",
        "SANJAY", "REKHA", "MOHAN", "DIVYA", "PRAKASH", "SWATI",
        "GANESH", "MEERA", "ASHOK", "LATA", "VIKRAM", "GEETA",
    ])
    last = random.choice([
        "KUMAR", "SHARMA", "PATEL", "REDDY", "NAIR", "SINGH", "GUPTA",
        "IYER", "JOSHI", "MEHTA", "PILLAI", "RAO", "MISHRA", "VERMA",
        "CHATTERJEE", "BANERJEE", "DAS", "DESAI", "KAUR", "MALHOTRA",
    ])
    return f"{first}.{last}"


# =============================================================================
# COMPANY STRUCTURE — "Bharat Industrial Solutions Pvt Ltd"
# =============================================================================
COMPANY_CODES = [
    {"BUKRS": "1000", "BUTXT": "Bharat Industrial Solutions Pvt Ltd", "WAERS": "INR", "LAND1": "IN", "ORT01": "Mumbai", "KTOPL": "BIIN", "PERIV": "V3"},
    {"BUKRS": "1100", "BUTXT": "BIS Manufacturing Division", "WAERS": "INR", "LAND1": "IN", "ORT01": "Pune", "KTOPL": "BIIN", "PERIV": "V3"},
    {"BUKRS": "1200", "BUTXT": "BIS Trading & Distribution", "WAERS": "INR", "LAND1": "IN", "ORT01": "Chennai", "KTOPL": "BIIN", "PERIV": "V3"},
    {"BUKRS": "2000", "BUTXT": "BIS Middle East FZCO", "WAERS": "AED", "LAND1": "AE", "ORT01": "Dubai", "KTOPL": "BIEA", "PERIV": "K4"},
]

PLANTS = [
    {"WERKS": "1001", "NAME1": "Mumbai HQ & Assembly", "BUKRS": "1000", "LAND1": "IN", "FABKL": "IN", "ORT01": "Mumbai"},
    {"WERKS": "1002", "NAME1": "Pune Manufacturing Plant", "BUKRS": "1100", "LAND1": "IN", "FABKL": "IN", "ORT01": "Pune"},
    {"WERKS": "1003", "NAME1": "Chennai Distribution Center", "BUKRS": "1200", "LAND1": "IN", "FABKL": "IN", "ORT01": "Chennai"},
    {"WERKS": "1004", "NAME1": "Hyderabad Electronics Plant", "BUKRS": "1100", "LAND1": "IN", "FABKL": "IN", "ORT01": "Hyderabad"},
    {"WERKS": "1005", "NAME1": "Ahmedabad Chemical Plant", "BUKRS": "1100", "LAND1": "IN", "FABKL": "IN", "ORT01": "Ahmedabad"},
    {"WERKS": "1006", "NAME1": "Delhi North Warehouse", "BUKRS": "1200", "LAND1": "IN", "FABKL": "IN", "ORT01": "Delhi"},
    {"WERKS": "1007", "NAME1": "Bangalore R&D Center", "BUKRS": "1000", "LAND1": "IN", "FABKL": "IN", "ORT01": "Bangalore"},
    {"WERKS": "1008", "NAME1": "Kolkata East Warehouse", "BUKRS": "1200", "LAND1": "IN", "FABKL": "IN", "ORT01": "Kolkata"},
    {"WERKS": "1009", "NAME1": "Coimbatore Textile Unit", "BUKRS": "1100", "LAND1": "IN", "FABKL": "IN", "ORT01": "Coimbatore"},
    {"WERKS": "1010", "NAME1": "Jaipur Packaging Unit", "BUKRS": "1100", "LAND1": "IN", "FABKL": "IN", "ORT01": "Jaipur"},
    {"WERKS": "2001", "NAME1": "Dubai Trading Hub", "BUKRS": "2000", "LAND1": "AE", "FABKL": "AE", "ORT01": "Dubai"},
    {"WERKS": "2002", "NAME1": "JAFZA Warehouse", "BUKRS": "2000", "LAND1": "AE", "FABKL": "AE", "ORT01": "Jebel Ali"},
]

STORAGE_LOCATIONS = []
for plant in PLANTS:
    for sl in [
        {"LGORT": "0001", "LGOBE": "Finished Goods"},
        {"LGORT": "0002", "LGOBE": "Raw Materials"},
        {"LGORT": "0003", "LGOBE": "Quality Inspection"},
        {"LGORT": "0004", "LGOBE": "Scrap / Returns"},
    ]:
        STORAGE_LOCATIONS.append({"WERKS": plant["WERKS"], **sl})

SALES_ORGS = [
    {"VKORG": "1000", "BUKRS": "1000", "VTEXT": "Domestic Sales - West"},
    {"VKORG": "1100", "BUKRS": "1000", "VTEXT": "Domestic Sales - South"},
    {"VKORG": "1200", "BUKRS": "1000", "VTEXT": "Domestic Sales - North"},
    {"VKORG": "1300", "BUKRS": "1000", "VTEXT": "Domestic Sales - East"},
    {"VKORG": "1400", "BUKRS": "1000", "VTEXT": "Industrial Sales"},
    {"VKORG": "1500", "BUKRS": "1000", "VTEXT": "Government & PSU Sales"},
    {"VKORG": "2000", "BUKRS": "2000", "VTEXT": "Export Sales - Middle East"},
    {"VKORG": "2100", "BUKRS": "2000", "VTEXT": "Export Sales - Africa"},
]

CONTROLLING_AREAS = [
    {"KOKRS": "1000", "BEZEI": "BIS India Controlling", "WAERS": "INR", "BUKRS": "1000"},
    {"KOKRS": "2000", "BEZEI": "BIS International Controlling", "WAERS": "USD", "BUKRS": "2000"},
]

PURCHASING_ORGS = [
    {"EKORG": "1000", "EKOTX": "Central Procurement India", "BUKRS": "1000"},
    {"EKORG": "1100", "EKOTX": "Manufacturing Procurement", "BUKRS": "1100"},
    {"EKORG": "2000", "EKOTX": "International Procurement", "BUKRS": "2000"},
]


# =============================================================================
# CUSTOM ABAP PROGRAMS (1,247 programs — realistic distribution)
# =============================================================================
def generate_programs():
    programs = []

    # Naming patterns found in real SAP systems
    program_templates = [
        # Finance (200+)
        ("ZFI_{:03d}_PAYMENT_RUN", "1", 30),
        ("ZFI_{:03d}_BANK_RECONCILIATION", "1", 15),
        ("ZFI_{:03d}_TAX_REPORT_GST", "1", 25),
        ("ZFI_{:03d}_WITHHOLDING_TAX", "1", 20),
        ("ZFI_{:03d}_ASSET_DEPRECIATION", "1", 15),
        ("ZFI_{:03d}_INTERCOMPANY_POSTING", "1", 10),
        ("ZFI_{:03d}_AGING_REPORT", "1", 12),
        ("ZFI_{:03d}_VENDOR_PAYMENT", "1", 18),
        ("ZFI_{:03d}_CUSTOMER_DUNNING", "1", 10),
        ("ZFI_{:03d}_GL_BALANCE_SHEET", "1", 15),
        ("ZFI_{:03d}_PROFIT_LOSS_STMT", "1", 10),
        ("ZFI_{:03d}_CASH_FLOW_REPORT", "1", 8),
        ("ZFI_{:03d}_TDS_RETURN", "1", 12),
        # Materials (180+)
        ("ZMM_{:03d}_PO_APPROVAL", "1", 20),
        ("ZMM_{:03d}_GRN_REPORT", "1", 15),
        ("ZMM_{:03d}_STOCK_VALUATION", "1", 12),
        ("ZMM_{:03d}_MRP_ANALYSIS", "1", 18),
        ("ZMM_{:03d}_VENDOR_EVAL", "1", 10),
        ("ZMM_{:03d}_PURCHASE_REQ", "1", 15),
        ("ZMM_{:03d}_INVENTORY_AGING", "1", 10),
        ("ZMM_{:03d}_MATERIAL_MASTER", "1", 8),
        ("ZMM_{:03d}_BATCH_MGMT", "1", 12),
        ("ZMM_{:03d}_SUBCONTRACTING", "1", 8),
        ("ZMM_{:03d}_CONSIGNMENT", "1", 7),
        ("ZMM_{:03d}_QM_INSPECTION", "1", 10),
        ("ZMM_{:03d}_WAREHOUSE_RPT", "1", 15),
        # Sales (170+)
        ("ZSD_{:03d}_ORDER_STATUS", "1", 20),
        ("ZSD_{:03d}_DELIVERY_NOTE", "1", 15),
        ("ZSD_{:03d}_BILLING_REPORT", "1", 12),
        ("ZSD_{:03d}_PRICING_ANALYSIS", "1", 10),
        ("ZSD_{:03d}_CREDIT_CHECK", "1", 15),
        ("ZSD_{:03d}_SALES_COMMISSION", "1", 8),
        ("ZSD_{:03d}_QUOTATION_MGMT", "1", 10),
        ("ZSD_{:03d}_RETURNS_PROCESS", "1", 7),
        ("ZSD_{:03d}_EXPORT_DOCUMENT", "1", 12),
        ("ZSD_{:03d}_EWAY_BILL", "1", 8),
        ("ZSD_{:03d}_GST_INVOICE", "1", 15),
        # Production (100+)
        ("ZPP_{:03d}_PROD_ORDER", "1", 15),
        ("ZPP_{:03d}_BOM_EXPLOSION", "1", 10),
        ("ZPP_{:03d}_ROUTING_REPORT", "1", 8),
        ("ZPP_{:03d}_CAPACITY_PLAN", "1", 10),
        ("ZPP_{:03d}_SHOP_FLOOR", "1", 12),
        ("ZPP_{:03d}_YIELD_ANALYSIS", "1", 8),
        ("ZPP_{:03d}_WIP_REPORT", "1", 7),
        ("ZPP_{:03d}_BATCH_TRACKING", "1", 10),
        # HR (80+)
        ("ZHR_{:03d}_PAYROLL_RUN", "1", 15),
        ("ZHR_{:03d}_ATTENDANCE", "1", 10),
        ("ZHR_{:03d}_LEAVE_MGMT", "1", 8),
        ("ZHR_{:03d}_PF_REPORT", "1", 10),
        ("ZHR_{:03d}_ESI_REPORT", "1", 8),
        ("ZHR_{:03d}_FORM16", "1", 7),
        ("ZHR_{:03d}_APPRAISAL", "1", 5),
        # Controlling (50+)
        ("ZCO_{:03d}_COST_CENTER_RPT", "1", 12),
        ("ZCO_{:03d}_PROFIT_CENTER", "1", 8),
        ("ZCO_{:03d}_INTERNAL_ORDER", "1", 10),
        ("ZCO_{:03d}_MARGIN_ANALYSIS", "1", 10),
        # Basis / Cross-module (100+)
        ("ZUTIL_{:03d}_EMAIL_SENDER", "1", 8),
        ("ZUTIL_{:03d}_FILE_UPLOAD", "1", 10),
        ("ZUTIL_{:03d}_IDOC_MONITOR", "1", 12),
        ("ZUTIL_{:03d}_RFC_WRAPPER", "1", 8),
        ("ZUTIL_{:03d}_ALV_TEMPLATE", "1", 15),
        ("ZUTIL_{:03d}_PDF_GENERATE", "1", 7),
        ("ZUTIL_{:03d}_SMARTFORM", "1", 10),
        # Plant Maintenance (60+)
        ("ZPM_{:03d}_WORK_ORDER", "1", 12),
        ("ZPM_{:03d}_EQUIPMENT_LIST", "1", 10),
        ("ZPM_{:03d}_MAINT_PLAN", "1", 8),
        ("ZPM_{:03d}_BREAKDOWN_RPT", "1", 7),
        ("ZPM_{:03d}_CALIBRATION", "1", 6),
        ("ZPM_{:03d}_SPARE_PARTS", "1", 8),
        ("ZPM_{:03d}_NOTIFICATION", "1", 9),
        # Warehouse Management (45+)
        ("ZWM_{:03d}_TRANSFER_ORDER", "1", 10),
        ("ZWM_{:03d}_STOCK_PLACEMENT", "1", 8),
        ("ZWM_{:03d}_PICKING_LIST", "1", 7),
        ("ZWM_{:03d}_CYCLE_COUNT", "1", 6),
        ("ZWM_{:03d}_BIN_STATUS", "1", 7),
        ("ZWM_{:03d}_PUTAWAY_STRAT", "1", 7),
        # Quality Management (40+)
        ("ZQM_{:03d}_INSPECTION_LOT", "1", 10),
        ("ZQM_{:03d}_USAGE_DECISION", "1", 8),
        ("ZQM_{:03d}_CERT_OF_ANALYSIS", "1", 7),
        ("ZQM_{:03d}_DEFECT_RECORD", "1", 8),
        ("ZQM_{:03d}_VENDOR_QUALITY", "1", 7),
        # Project Systems (30+)
        ("ZPS_{:03d}_PROJECT_STATUS", "1", 8),
        ("ZPS_{:03d}_WBS_REPORT", "1", 7),
        ("ZPS_{:03d}_NETWORK_ACTIVITY", "1", 6),
        ("ZPS_{:03d}_MILESTONE_RPT", "1", 5),
        ("ZPS_{:03d}_BUDGET_MONITOR", "1", 6),
        # Cross-Application (35+)
        ("ZCA_{:03d}_WORKFLOW_CUSTOM", "1", 8),
        ("ZCA_{:03d}_OUTPUT_CONTROL", "1", 7),
        ("ZCA_{:03d}_NUMBER_RANGE", "1", 5),
        ("ZCA_{:03d}_CHANGE_DOC", "1", 6),
        ("ZCA_{:03d}_BATCH_JOB_MON", "1", 9),
        # Basis / Admin (30+)
        ("ZBC_{:03d}_USER_ADMIN", "1", 7),
        ("ZBC_{:03d}_AUTH_CHECK", "1", 6),
        ("ZBC_{:03d}_TRANSPORT_RPT", "1", 5),
        ("ZBC_{:03d}_SPOOL_MONITOR", "1", 6),
        ("ZBC_{:03d}_JOB_SCHEDULER", "1", 6),
        # Additional Finance reports
        ("ZFI_{:03d}_BANK_STATEMENT", "1", 10),
        ("ZFI_{:03d}_CHECK_PRINTING", "1", 7),
        ("ZFI_{:03d}_RECONCILIATION", "1", 8),
        # Additional MM reports
        ("ZMM_{:03d}_PRICE_COMPARISON", "1", 8),
        ("ZMM_{:03d}_DELIVERY_SCHED", "1", 7),
        ("ZMM_{:03d}_QUOTA_ARRANGE", "1", 6),
        # Additional SD reports
        ("ZSD_{:03d}_BACKORDER_RPT", "1", 7),
        ("ZSD_{:03d}_REBATE_PROCESS", "1", 6),
        ("ZSD_{:03d}_ATP_CHECK", "1", 5),
        # Additional HR
        ("ZHR_{:03d}_RECRUITMENT", "1", 6),
        ("ZHR_{:03d}_TRAINING_MGMT", "1", 5),
        ("ZHR_{:03d}_TRAVEL_EXPENSE", "1", 7),
        # Y-namespace programs (legacy)
        ("YFI_{:03d}_OLD_REPORT", "1", 8),
        ("YMM_{:03d}_LEGACY_UPLOAD", "1", 6),
        ("YSD_{:03d}_LEGACY_PRINT", "1", 5),
        ("YHR_{:03d}_OLD_PAYSLIP", "1", 5),
        # Includes
        ("ZFI_{:03d}_INCLUDE_TOP", "I", 30),
        ("ZMM_{:03d}_INCLUDE_TOP", "I", 20),
        ("ZSD_{:03d}_INCLUDE_FORMS", "I", 15),
        ("ZPM_{:03d}_INCLUDE_TOP", "I", 8),
        ("ZWM_{:03d}_INCLUDE_TOP", "I", 6),
        ("ZQM_{:03d}_INCLUDE_TOP", "I", 5),
        # Function Groups
        ("SAPLZFI_{:02d}", "F", 10),
        ("SAPLZMM_{:02d}", "F", 8),
        ("SAPLZSD_{:02d}", "F", 8),
        ("SAPLZPM_{:02d}", "F", 5),
        ("SAPLZWM_{:02d}", "F", 4),
        ("SAPLZQM_{:02d}", "F", 4),
        # Class pools
        ("ZCL_FI_{:03d}_PAYMENT", "K", 8),
        ("ZCL_MM_{:03d}_PROCUREMENT", "K", 6),
        ("ZCL_SD_{:03d}_ORDER", "K", 6),
        ("ZCL_UTIL_{:03d}_HELPER", "K", 5),
        ("ZCL_PM_{:03d}_MAINTENANCE", "K", 4),
        ("ZCL_WM_{:03d}_WAREHOUSE", "K", 4),
        ("ZCL_QM_{:03d}_QUALITY", "K", 3),
        # Module pool (dynpro programs)
        ("SAPMZFI_{:02d}", "M", 5),
        ("SAPMZMM_{:02d}", "M", 4),
        ("SAPMZSD_{:02d}", "M", 4),
    ]

    type_map = {"1": "executable", "I": "include", "F": "function_group", "K": "class_pool", "M": "module_pool"}

    for template, prog_type, count in program_templates:
        for i in range(1, count + 1):
            name = template.format(i)
            programs.append({
                "NAME": name,
                "SUBC": prog_type,
                "CDAT": random_date(2008, 2020),
                "UDAT": random_date(2020, 2024),
                "UNAM": random_user(),
                "RSTAT": random.choice(["K", "K", "K", "K", "S"]),  # 80% active
                # Parsed version
                "name": name,
                "type": type_map.get(prog_type, prog_type),
                "type_code": prog_type,
                "created": random_date(2008, 2020),
                "modified": random_date(2020, 2024),
                "modified_by": random_user(),
                "status": "active" if random.random() > 0.2 else "inactive",
            })

    return programs[:1247]  # Cap at 1,247


# =============================================================================
# CUSTOM TABLES (94 tables)
# =============================================================================
def generate_tables():
    tables = [
        # Finance custom tables
        {"TABNAME": "ZTFI_GST_CONFIG", "TABCLASS": "TRANSP", "rows": 450, "desc": "GST tax configuration"},
        {"TABNAME": "ZTFI_TDS_RATES", "TABCLASS": "TRANSP", "rows": 120, "desc": "TDS rate master"},
        {"TABNAME": "ZTFI_BANK_MASTER", "TABCLASS": "TRANSP", "rows": 85, "desc": "Bank master extension"},
        {"TABNAME": "ZTFI_PAY_TERMS", "TABCLASS": "TRANSP", "rows": 35, "desc": "Custom payment terms"},
        {"TABNAME": "ZTFI_FX_RATES", "TABCLASS": "TRANSP", "rows": 5000, "desc": "Historical FX rates"},
        {"TABNAME": "ZTFI_COST_ALLOC", "TABCLASS": "TRANSP", "rows": 2200, "desc": "Cost allocation rules"},
        {"TABNAME": "ZTFI_BUDGET_HDR", "TABCLASS": "TRANSP", "rows": 480, "desc": "Budget header"},
        {"TABNAME": "ZTFI_BUDGET_LINE", "TABCLASS": "TRANSP", "rows": 12000, "desc": "Budget line items"},
        {"TABNAME": "ZTFI_INTERCO_MAP", "TABCLASS": "TRANSP", "rows": 95, "desc": "Intercompany mapping"},
        {"TABNAME": "ZTFI_AUDIT_LOG", "TABCLASS": "TRANSP", "rows": 250000, "desc": "Financial audit trail"},
        # Materials custom tables
        {"TABNAME": "ZTMM_VENDOR_EXT", "TABCLASS": "TRANSP", "rows": 1500, "desc": "Vendor extension data"},
        {"TABNAME": "ZTMM_MATERIAL_EXT", "TABCLASS": "TRANSP", "rows": 8000, "desc": "Material extension"},
        {"TABNAME": "ZTMM_APPROVAL_WF", "TABCLASS": "TRANSP", "rows": 45000, "desc": "PO approval workflow log"},
        {"TABNAME": "ZTMM_QUALITY_CHK", "TABCLASS": "TRANSP", "rows": 30000, "desc": "Quality check results"},
        {"TABNAME": "ZTMM_BATCH_ATTR", "TABCLASS": "TRANSP", "rows": 15000, "desc": "Batch attributes"},
        {"TABNAME": "ZTMM_SUBCON_TRACK", "TABCLASS": "TRANSP", "rows": 7500, "desc": "Subcontracting tracker"},
        {"TABNAME": "ZTMM_IMPORT_DOC", "TABCLASS": "TRANSP", "rows": 4200, "desc": "Import documentation"},
        {"TABNAME": "ZTMM_HSN_MASTER", "TABCLASS": "TRANSP", "rows": 950, "desc": "HSN code master"},
        {"TABNAME": "ZTMM_PRICE_HIST", "TABCLASS": "TRANSP", "rows": 180000, "desc": "Price history"},
        {"TABNAME": "ZTMM_STOCK_SNAP", "TABCLASS": "TRANSP", "rows": 500000, "desc": "Daily stock snapshot"},
        # Sales custom tables
        {"TABNAME": "ZTSD_PRICING_EXT", "TABCLASS": "TRANSP", "rows": 25000, "desc": "Custom pricing conditions"},
        {"TABNAME": "ZTSD_COMMISSION", "TABCLASS": "TRANSP", "rows": 35000, "desc": "Sales commission data"},
        {"TABNAME": "ZTSD_EWAY_BILL", "TABCLASS": "TRANSP", "rows": 120000, "desc": "E-way bill tracking"},
        {"TABNAME": "ZTSD_GST_INVOICE", "TABCLASS": "TRANSP", "rows": 200000, "desc": "GST invoice details"},
        {"TABNAME": "ZTSD_CREDIT_LIMIT", "TABCLASS": "TRANSP", "rows": 3500, "desc": "Customer credit limits"},
        {"TABNAME": "ZTSD_REBATE_CALC", "TABCLASS": "TRANSP", "rows": 18000, "desc": "Rebate calculations"},
        {"TABNAME": "ZTSD_DELIVERY_EXT", "TABCLASS": "TRANSP", "rows": 90000, "desc": "Delivery extensions"},
        {"TABNAME": "ZTSD_EXPORT_DOC", "TABCLASS": "TRANSP", "rows": 15000, "desc": "Export documentation"},
        {"TABNAME": "ZTSD_TERRITORY", "TABCLASS": "TRANSP", "rows": 280, "desc": "Sales territory master"},
        # Production custom tables
        {"TABNAME": "ZTPP_YIELD_DATA", "TABCLASS": "TRANSP", "rows": 50000, "desc": "Production yield data"},
        {"TABNAME": "ZTPP_MACHINE_LOG", "TABCLASS": "TRANSP", "rows": 300000, "desc": "Machine downtime log"},
        {"TABNAME": "ZTPP_SHIFT_PLAN", "TABCLASS": "TRANSP", "rows": 8000, "desc": "Shift planning"},
        {"TABNAME": "ZTPP_BOM_CUSTOM", "TABCLASS": "TRANSP", "rows": 12000, "desc": "Custom BOM attributes"},
        {"TABNAME": "ZTPP_QC_RESULTS", "TABCLASS": "TRANSP", "rows": 75000, "desc": "QC test results"},
        # HR custom tables
        {"TABNAME": "ZTHR_ATTENDANCE", "TABCLASS": "TRANSP", "rows": 400000, "desc": "Attendance records"},
        {"TABNAME": "ZTHR_LEAVE_BAL", "TABCLASS": "TRANSP", "rows": 6000, "desc": "Leave balances"},
        {"TABNAME": "ZTHR_PF_CALC", "TABCLASS": "TRANSP", "rows": 24000, "desc": "PF calculation details"},
        {"TABNAME": "ZTHR_ESI_CALC", "TABCLASS": "TRANSP", "rows": 18000, "desc": "ESI calculation"},
        {"TABNAME": "ZTHR_GRATUITY", "TABCLASS": "TRANSP", "rows": 2000, "desc": "Gratuity provision"},
        {"TABNAME": "ZTHR_APPRAISAL", "TABCLASS": "TRANSP", "rows": 8000, "desc": "Performance ratings"},
        # Cross-module / Utility tables
        {"TABNAME": "ZTUTIL_EMAIL_LOG", "TABCLASS": "TRANSP", "rows": 500000, "desc": "Email dispatch log"},
        {"TABNAME": "ZTUTIL_FILE_LOG", "TABCLASS": "TRANSP", "rows": 120000, "desc": "File transfer log"},
        {"TABNAME": "ZTUTIL_ERROR_LOG", "TABCLASS": "TRANSP", "rows": 80000, "desc": "Custom error log"},
        {"TABNAME": "ZTUTIL_CONFIG", "TABCLASS": "TRANSP", "rows": 350, "desc": "Application configuration"},
        {"TABNAME": "ZTUTIL_NUMBER_RNG", "TABCLASS": "TRANSP", "rows": 45, "desc": "Custom number ranges"},
        {"TABNAME": "ZTUTIL_BATCH_JOB", "TABCLASS": "TRANSP", "rows": 25000, "desc": "Batch job status log"},
        # Cluster tables (will need conversion for HANA)
        {"TABNAME": "ZTHR_PAYROLL_CL", "TABCLASS": "CLUSTER", "rows": 150000, "desc": "Payroll cluster data"},
        {"TABNAME": "ZTFI_ARCHIVE_CL", "TABCLASS": "CLUSTER", "rows": 80000, "desc": "Archived FI documents"},
    ]

    # Pad to 94 with generic tables
    modules = ["FI", "MM", "SD", "PP", "HR", "CO", "QM", "PM", "WM"]
    suffixes = ["_CUSTOM_01", "_REPORT_DATA", "_STAGING", "_ARCHIVE", "_EXTENSION", "_LOG", "_MASTER_EXT", "_TEMP"]
    while len(tables) < 94:
        mod = random.choice(modules)
        suf = random.choice(suffixes)
        tables.append({
            "TABNAME": f"ZT{mod}{suf}_{len(tables):02d}",
            "TABCLASS": "TRANSP",
            "rows": random.randint(100, 50000),
            "desc": f"Custom {mod} table",
        })

    for t in tables:
        t["AS4DATE"] = random_date(2010, 2024)
        t["AS4LOCAL"] = "A"
        t["name"] = t["TABNAME"]
        t["type"] = t["TABCLASS"]
        t["last_changed"] = t["AS4DATE"]
        t["status"] = "active"
        t["estimated_rows"] = t["rows"]

    return tables


# =============================================================================
# CUSTOM FUNCTION MODULES (389)
# =============================================================================
def generate_function_modules():
    fms = []
    prefixes = [
        ("Z_FI_", 60), ("Z_MM_", 50), ("Z_SD_", 50), ("Z_PP_", 30),
        ("Z_HR_", 25), ("Z_CO_", 15), ("Z_UTIL_", 40), ("Z_RFC_", 30),
        ("Z_BAPI_", 20), ("Z_IDOC_", 15), ("Z_EMAIL_", 10), ("Z_PDF_", 8),
        ("Z_WF_", 12), ("Z_QM_", 10), ("Z_PM_", 8), ("Z_WM_", 6),
    ]

    names = [
        "GET_DATA", "SET_DATA", "VALIDATE", "PROCESS", "CALCULATE",
        "CREATE", "UPDATE", "DELETE", "SEARCH", "REPORT", "EXPORT",
        "IMPORT", "CONVERT", "CHECK", "APPROVE", "REJECT", "SEND",
        "RECEIVE", "FORMAT", "PARSE", "UPLOAD", "DOWNLOAD", "ARCHIVE",
        "EXTRACT", "TRANSFORM", "LOAD", "SYNC", "MONITOR", "LOG",
    ]

    for prefix, count in prefixes:
        for i in range(count):
            name_part = random.choice(names)
            fm_name = f"{prefix}{name_part}_{i + 1:03d}"
            fg = f"SAPL{prefix.rstrip('_')}"
            is_rfc = prefix in ("Z_RFC_", "Z_BAPI_", "Z_IDOC_") or random.random() > 0.7

            fms.append({
                "FUNCNAME": fm_name,
                "PNAME": fg,
                "FMODE": "R" if is_rfc else " ",
                "name": fm_name,
                "function_group": fg,
                "is_rfc_enabled": is_rfc,
            })

    return fms[:389]


# =============================================================================
# SAMPLE ABAP SOURCE CODE (with realistic bugs to catch)
# =============================================================================
SAMPLE_ABAP_PROGRAMS = {
    "ZFI_001_PAYMENT_RUN": """*----------------------------------------------------------------------*
* Program: ZFI_001_PAYMENT_RUN
* Description: Automatic payment run for vendor invoices
* Author: RAVI.KUMAR
* Created: 20150315
*----------------------------------------------------------------------*
REPORT ZFI_001_PAYMENT_RUN.

TABLES: BSEG, BKPF, LFA1, BSIK.

DATA: lt_items TYPE STANDARD TABLE OF BSEG OCCURS 0 WITH HEADER LINE,
      ls_vendor TYPE LFA1,
      lv_total TYPE BSEG-DMBTR,
      lv_count TYPE i.

SELECT-OPTIONS: s_bukrs FOR BSEG-BUKRS,
                s_lifnr FOR BSIK-LIFNR,
                s_budat FOR BKPF-BUDAT.

START-OF-SELECTION.

  SELECT * FROM BSIK
    INTO CORRESPONDING FIELDS OF TABLE lt_items
    WHERE BUKRS IN s_bukrs
    AND   LIFNR IN s_lifnr
    AND   BUDAT IN s_budat.

  LOOP AT lt_items.
    MOVE lt_items-DMBTR TO lv_total.
    COMPUTE lv_count = lv_count + 1.

    SELECT SINGLE * FROM LFA1 INTO ls_vendor
      WHERE LIFNR = lt_items-LIFNR.

    WRITE: / lt_items-BUKRS, lt_items-BELNR, lt_items-LIFNR,
             ls_vendor-NAME1, lt_items-DMBTR.
  ENDLOOP.

  WRITE: / 'Total items:', lv_count.
  WRITE: / 'Total amount:', lv_total.

  CALL FUNCTION 'POPUP_TO_CONFIRM_STEP'
    EXPORTING
      textline1 = 'Execute payment run?'
    IMPORTING
      answer    = lv_answer.

  CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'
    EXPORTING
      i_structure_name = 'BSEG'
    TABLES
      t_outtab         = lt_items.
""",

    "ZMM_001_PO_APPROVAL": """*----------------------------------------------------------------------*
* Program: ZMM_001_PO_APPROVAL
* Description: Purchase order approval workflow report
*----------------------------------------------------------------------*
REPORT ZMM_001_PO_APPROVAL.

TABLES: EKKO, EKPO, LFA1.

DATA: BEGIN OF lt_orders OCCURS 0,
        EBELN TYPE EKKO-EBELN,
        LIFNR TYPE EKKO-LIFNR,
        NAME1 TYPE LFA1-NAME1,
        NETWR TYPE EKPO-NETWR,
        WAERS TYPE EKKO-WAERS,
      END OF lt_orders.

DATA: lv_total TYPE p DECIMALS 2.

MULTIPLY lv_total BY 1.
DIVIDE lv_total BY 1.

SELECT EKKO~EBELN EKKO~LIFNR LFA1~NAME1
       SUM( EKPO~NETWR ) AS NETWR EKKO~WAERS
  INTO CORRESPONDING FIELDS OF TABLE lt_orders
  FROM EKKO
  INNER JOIN EKPO ON EKKO~EBELN = EKPO~EBELN
  LEFT JOIN LFA1 ON EKKO~LIFNR = LFA1~LIFNR
  WHERE EKKO~BUKRS = '1000'
  GROUP BY EKKO~EBELN EKKO~LIFNR LFA1~NAME1 EKKO~WAERS.

LOOP AT lt_orders.
  MOVE lt_orders-NETWR TO lv_total.
  WRITE: / lt_orders-EBELN, lt_orders-NAME1, lt_orders-NETWR.
ENDLOOP.
""",

    "ZSD_001_GST_INVOICE": """*----------------------------------------------------------------------*
* Program: ZSD_001_GST_INVOICE
* Description: GST Invoice generation with E-way bill
* India specific — handles CGST, SGST, IGST
*----------------------------------------------------------------------*
REPORT ZSD_001_GST_INVOICE.

TABLES: VBRK, VBRP, KNA1, KONV.

DATA: lt_billing TYPE TABLE OF VBRK,
      lt_items   TYPE TABLE OF VBRP,
      lt_cond    TYPE TABLE OF KONV,
      ls_customer TYPE KNA1.

SELECT * FROM VBRK INTO TABLE lt_billing
  WHERE BUKRS = '1000'
  AND   FKDAT >= '20240401'.

SELECT * FROM VBRP INTO TABLE lt_items
  FOR ALL ENTRIES IN lt_billing
  WHERE VBELN = lt_billing-VBELN.

* Read pricing conditions for GST
SELECT * FROM KONV INTO TABLE lt_cond
  FOR ALL ENTRIES IN lt_billing
  WHERE KNUMV = lt_billing-KNUMV.

SELECT SINGLE * FROM KNA1 INTO ls_customer
  WHERE KUNNR = '0000010001'.

WRITE: / 'GST Invoice Report'.
""",

    "ZHR_001_PAYROLL_RUN": """*----------------------------------------------------------------------*
* Program: ZHR_001_PAYROLL_RUN
* Description: Monthly payroll processing with PF & ESI
*----------------------------------------------------------------------*
REPORT ZHR_001_PAYROLL_RUN.

TABLES: PA0001, PA0008.

DATA: lt_employees TYPE STANDARD TABLE OF PA0001 WITH HEADER LINE,
      lv_basic TYPE PA0008-ANSAL,
      lv_pf    TYPE p DECIMALS 2,
      lv_esi   TYPE p DECIMALS 2.

SELECT * FROM PA0001 INTO TABLE lt_employees
  WHERE ENDDA >= sy-datum
  AND   BEGDA <= sy-datum.

LOOP AT lt_employees.
  SELECT SINGLE ANSAL FROM PA0008 INTO lv_basic
    WHERE PERNR = lt_employees-PERNR
    AND   ENDDA >= sy-datum.

  COMPUTE lv_pf = lv_basic * 12 / 100.
  COMPUTE lv_esi = lv_basic * '0.0075'.

  WRITE: / lt_employees-PERNR, lt_employees-ENAME,
           lv_basic, lv_pf, lv_esi.
ENDLOOP.
""",
}


# =============================================================================
# CUSTOMERS (KNA1) — Will need BP conversion
# =============================================================================
def generate_customers():
    customers = []
    indian_cities = ["Mumbai", "Delhi", "Bangalore", "Hyderabad", "Chennai",
                     "Kolkata", "Pune", "Ahmedabad", "Jaipur", "Lucknow",
                     "Coimbatore", "Indore", "Nagpur", "Visakhapatnam", "Surat"]
    uae_cities = ["Dubai", "Abu Dhabi", "Sharjah"]

    company_types = ["Pvt Ltd", "Ltd", "LLP", "Industries", "Enterprises",
                     "Trading Co", "Solutions", "Technologies", "Exports"]

    for i in range(1, 3501):
        is_export = random.random() > 0.85
        city = random.choice(uae_cities if is_export else indian_cities)
        country = "AE" if is_export else "IN"

        # Tax ID: PAN for India, TRN for UAE — ~5% deliberately blank
        if random.random() < 0.05:
            stcd1 = ""
        elif country == "IN":
            pan_letters = "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=5))
            pan_digits = "".join(random.choices("0123456789", k=4))
            stcd1 = f"{pan_letters}{pan_digits}{random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}"
        else:
            stcd1 = f"{random.randint(100000000000000, 999999999999999)}"

        # Email: ~8% deliberately blank
        if random.random() < 0.08:
            smtp_addr = ""
        else:
            name_part = f"contact{i}"
            domain = random.choice(["gmail.com", "outlook.com", "company.co.in", "business.in", "corp.ae"])
            smtp_addr = f"{name_part}@{domain}"

        customers.append({
            "KUNNR": f"{i:010d}",
            "NAME1": f"{random.choice(['Shri','Jai','Om','Tata','Reliance','Adani','Birla','Bajaj','Mahindra','Godrej','Wipro','HCL'])} {random.choice(['Steel','Auto','Pharma','Textile','Chemical','Food','Cement','Power','Infra','Tech'])} {random.choice(company_types)}",
            "NAME2": "",
            "LAND1": country,
            "ORT01": city,
            "STRAS": f"{random.randint(1,500)}, {random.choice(['MG Road','Industrial Area','MIDC','Phase','Sector'])} {random.choice(['','II','III','IV'])}",
            "PSTLZ": f"{random.randint(100000, 999999)}" if country == "IN" else f"{random.randint(10000,99999)}",
            "TELF1": f"+91{random.randint(7000000000, 9999999999)}" if country == "IN" else f"+971{random.randint(500000000, 599999999)}",
            "STCD1": stcd1,
            "SMTP_ADDR": smtp_addr,
            "KTOKD": "0001",
            "BUKRS": "1000",
        })

    return customers


# =============================================================================
# VENDORS (LFA1) — Will need BP conversion
# =============================================================================
def generate_vendors():
    vendors = []

    foreign_cities = {
        "CN": ["Shanghai", "Beijing", "Shenzhen", "Guangzhou"],
        "DE": ["Munich", "Berlin", "Hamburg", "Frankfurt"],
        "US": ["Chicago", "Houston", "New York", "Los Angeles"],
        "JP": ["Tokyo", "Osaka", "Nagoya"],
        "KR": ["Seoul", "Busan", "Incheon"],
    }
    indian_vendor_cities = ["Mumbai", "Pune", "Chennai", "Delhi", "Ahmedabad", "Bangalore", "Hyderabad"]

    for i in range(1, 1501):
        is_import = random.random() > 0.9
        country = random.choice(["CN", "DE", "US", "JP", "KR"]) if is_import else "IN"

        if country == "IN":
            city = random.choice(indian_vendor_cities)
        else:
            city = random.choice(foreign_cities.get(country, ["Unknown"]))

        # Postal code: ~8% deliberately blank for vendors
        if random.random() < 0.08:
            pstlz = ""
        elif country == "IN":
            pstlz = f"{random.randint(100000, 999999)}"
        elif country == "DE":
            pstlz = f"{random.randint(10000, 99999)}"
        elif country == "US":
            pstlz = f"{random.randint(10000, 99999)}"
        elif country == "CN":
            pstlz = f"{random.randint(100000, 999999)}"
        elif country == "JP":
            pstlz = f"{random.randint(1000000, 9999999)}"
        elif country == "KR":
            pstlz = f"{random.randint(10000, 99999)}"
        else:
            pstlz = f"{random.randint(10000, 99999)}"

        # Phone: ~6% blank
        if random.random() < 0.06:
            telf1 = ""
        elif country == "IN":
            telf1 = f"+91{random.randint(7000000000, 9999999999)}"
        elif country == "US":
            telf1 = f"+1{random.randint(2000000000, 9999999999)}"
        elif country == "DE":
            telf1 = f"+49{random.randint(1000000000, 9999999999)}"
        elif country == "CN":
            telf1 = f"+86{random.randint(10000000000, 19999999999)}"
        elif country == "JP":
            telf1 = f"+81{random.randint(3000000000, 9999999999)}"
        elif country == "KR":
            telf1 = f"+82{random.randint(1000000000, 9999999999)}"
        else:
            telf1 = f"+{random.randint(1000000000, 9999999999)}"

        # Tax ID: country-specific format — ~10% deliberately blank
        if random.random() < 0.10:
            stcd1 = ""
        elif country == "IN":
            pan_letters = "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=5))
            pan_digits = "".join(random.choices("0123456789", k=4))
            stcd1 = f"{pan_letters}{pan_digits}{random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}"
        elif country == "US":
            stcd1 = f"{random.randint(10, 99)}-{random.randint(1000000, 9999999)}"
        elif country == "DE":
            stcd1 = f"DE{random.randint(100000000, 999999999)}"
        elif country == "CN":
            stcd1 = f"{random.randint(100000000000000000, 999999999999999999)}"
        elif country == "JP":
            stcd1 = f"T{random.randint(1000000000000, 9999999999999)}"
        elif country == "KR":
            stcd1 = f"{random.randint(100, 999)}-{random.randint(10, 99)}-{random.randint(10000, 99999)}"
        else:
            stcd1 = f"TAX{random.randint(100000, 999999)}"

        # Email: ~12% blank for vendors
        if random.random() < 0.12:
            smtp_addr = ""
        else:
            name_part = f"vendor{i}"
            domain = random.choice(["supplier.com", "vendor.co.in", "trade.cn", "industrie.de", "corp.jp", "business.kr"])
            smtp_addr = f"{name_part}@{domain}"

        vendors.append({
            "LIFNR": f"{i:010d}",
            "NAME1": f"{random.choice(['National','Global','Premier','Supreme','Excel','Prime','Metro','Star','Royal','Atlas'])} {random.choice(['Metals','Plastics','Chemicals','Electronics','Components','Machinery','Tools','Packaging','Logistics','Raw Materials'])} {random.choice(['Pvt Ltd','Ltd','LLC','GmbH','Corp','Inc'])}",
            "NAME2": "",
            "LAND1": country,
            "ORT01": city,
            "STRAS": f"{random.randint(1,200)} Industrial Road",
            "PSTLZ": pstlz,
            "TELF1": telf1,
            "STCD1": stcd1,
            "SMTP_ADDR": smtp_addr,
            "KTOKK": "0001",
        })

    return vendors


# =============================================================================
# USER ROLES (PFCG) — 342 roles
# =============================================================================
def generate_roles():
    roles = []
    users_per_role = {}

    role_templates = [
        # Module-level roles
        ("Z_FI_ACCOUNTANT", "Finance Accountant", 45),
        ("Z_FI_AP_CLERK", "Accounts Payable Clerk", 25),
        ("Z_FI_AR_CLERK", "Accounts Receivable Clerk", 20),
        ("Z_FI_GL_MANAGER", "GL Manager", 8),
        ("Z_FI_TREASURY", "Treasury Operations", 5),
        ("Z_FI_TAX_ANALYST", "Tax Analyst (GST/TDS)", 12),
        ("Z_FI_ASSET_MGMT", "Asset Management", 6),
        ("Z_FI_INTERCO", "Intercompany Processor", 4),
        ("Z_MM_BUYER", "Procurement Buyer", 35),
        ("Z_MM_PO_APPROVER", "PO Approver", 15),
        ("Z_MM_GRN_CLERK", "Goods Receipt Clerk", 30),
        ("Z_MM_INVENTORY", "Inventory Controller", 20),
        ("Z_MM_WAREHOUSE", "Warehouse Manager", 12),
        ("Z_MM_VENDOR_MGMT", "Vendor Management", 8),
        ("Z_MM_QA_INSPECTOR", "QA Inspector", 15),
        ("Z_MM_IMPORT_EXPORT", "Import/Export Manager", 6),
        ("Z_SD_SALES_REP", "Sales Representative", 80),
        ("Z_SD_ORDER_MGMT", "Sales Order Management", 40),
        ("Z_SD_BILLING", "Billing Specialist", 15),
        ("Z_SD_SHIPPING", "Shipping Coordinator", 20),
        ("Z_SD_PRICING", "Pricing Analyst", 8),
        ("Z_SD_CREDIT_MGMT", "Credit Management", 10),
        ("Z_SD_EXPORT_DOC", "Export Documentation", 6),
        ("Z_PP_PLANNER", "Production Planner", 20),
        ("Z_PP_SUPERVISOR", "Shop Floor Supervisor", 25),
        ("Z_PP_ENGINEER", "Production Engineer", 15),
        ("Z_PP_QUALITY", "Quality Controller", 12),
        ("Z_HR_ADMIN", "HR Administrator", 15),
        ("Z_HR_PAYROLL", "Payroll Processor", 8),
        ("Z_HR_RECRUITER", "Recruiter", 6),
        ("Z_HR_MANAGER", "HR Manager", 4),
        ("Z_CO_ANALYST", "Cost Analyst", 10),
        ("Z_CO_CONTROLLER", "Financial Controller", 5),
        ("Z_BASIS_ADMIN", "SAP Basis Admin", 4),
        ("Z_SECURITY_ADMIN", "Security Administrator", 3),
        # Composite roles
        ("Z_COMP_FI_FULL", "Finance Full Access (Composite)", 0),
        ("Z_COMP_MM_FULL", "MM Full Access (Composite)", 0),
        ("Z_COMP_SD_FULL", "SD Full Access (Composite)", 0),
        ("Z_COMP_MANAGER", "Plant Manager (Composite)", 0),
        ("Z_COMP_DIRECTOR", "Director Level (Composite)", 0),
    ]

    # Generate base roles
    for name, desc, user_count in role_templates:
        roles.append({
            "AGR_NAME": name,
            "PARENT_AGR": "",
            "CREATE_USR": "SAP_ADMIN",
            "CREATE_DAT": random_date(2010, 2018),
            "name": name,
            "parent_role": None,
            "is_composite": name.startswith("Z_COMP"),
            "created_by": "SAP_ADMIN",
            "created_date": random_date(2010, 2018),
            "user_count": user_count,
            "description": desc,
        })

    # Generate plant-specific variant roles
    for plant in PLANTS[:6]:
        for base_role in ["Z_MM_BUYER", "Z_MM_GRN_CLERK", "Z_SD_SALES_REP", "Z_PP_PLANNER"]:
            roles.append({
                "AGR_NAME": f"{base_role}_{plant['WERKS']}",
                "PARENT_AGR": "",
                "CREATE_USR": "SAP_ADMIN",
                "CREATE_DAT": random_date(2015, 2020),
                "name": f"{base_role}_{plant['WERKS']}",
                "parent_role": None,
                "is_composite": False,
                "created_by": "SAP_ADMIN",
                "created_date": random_date(2015, 2020),
                "user_count": random.randint(3, 15),
            })

    # Company code specific roles
    for cc in COMPANY_CODES:
        for base in ["Z_FI_ACCOUNTANT", "Z_FI_AP_CLERK", "Z_FI_AR_CLERK"]:
            roles.append({
                "AGR_NAME": f"{base}_{cc['BUKRS']}",
                "PARENT_AGR": "",
                "CREATE_USR": "SAP_ADMIN",
                "CREATE_DAT": random_date(2012, 2019),
                "name": f"{base}_{cc['BUKRS']}",
                "parent_role": None,
                "is_composite": False,
                "created_by": "SAP_ADMIN",
                "created_date": random_date(2012, 2019),
                "user_count": random.randint(2, 10),
            })

    # Pad with additional display/change variants
    while len(roles) < 342:
        base = random.choice(role_templates[:35])
        variant = random.choice(["_DISPLAY", "_CHANGE", "_ADMIN", "_REPORTING", "_LIMITED"])
        roles.append({
            "AGR_NAME": f"{base[0]}{variant}",
            "PARENT_AGR": "",
            "CREATE_USR": random_user(),
            "CREATE_DAT": random_date(2015, 2023),
            "name": f"{base[0]}{variant}",
            "parent_role": None,
            "is_composite": False,
            "created_by": random_user(),
            "created_date": random_date(2015, 2023),
            "user_count": random.randint(1, 20),
        })

    return roles[:342]


# =============================================================================
# RFC DESTINATIONS (67)
# =============================================================================
def generate_rfc_destinations():
    destinations = [
        # SAP Standard
        {"RFCDEST": "SAP_GATEWAY", "RFCTYPE": "3", "desc": "Gateway server"},
        {"RFCDEST": "SAP_PI", "RFCTYPE": "3", "desc": "Process Integration"},
        {"RFCDEST": "SAP_BW", "RFCTYPE": "3", "desc": "BW reporting"},
        {"RFCDEST": "SAP_SRM", "RFCTYPE": "3", "desc": "Supplier RM"},
        {"RFCDEST": "SAP_CRM", "RFCTYPE": "3", "desc": "Customer RM"},
        {"RFCDEST": "SAP_SOLMAN", "RFCTYPE": "3", "desc": "Solution Manager"},
        {"RFCDEST": "SAP_GRC", "RFCTYPE": "3", "desc": "Governance Risk Compliance"},
        # Third-party integrations
        {"RFCDEST": "Z_TALLY_PRIME", "RFCTYPE": "H", "desc": "Tally accounting integration"},
        {"RFCDEST": "Z_GSTN_API", "RFCTYPE": "H", "desc": "GST Network API"},
        {"RFCDEST": "Z_EINVOICE_NIC", "RFCTYPE": "H", "desc": "E-invoice NIC portal"},
        {"RFCDEST": "Z_EWAY_BILL_API", "RFCTYPE": "H", "desc": "E-way bill NIC API"},
        {"RFCDEST": "Z_TDS_TRACES", "RFCTYPE": "H", "desc": "TDS TRACES portal"},
        {"RFCDEST": "Z_BANK_HDFC", "RFCTYPE": "H", "desc": "HDFC Bank host-to-host"},
        {"RFCDEST": "Z_BANK_SBI", "RFCTYPE": "H", "desc": "SBI Bank integration"},
        {"RFCDEST": "Z_BANK_ICICI", "RFCTYPE": "H", "desc": "ICICI Bank integration"},
        {"RFCDEST": "Z_LOGISTICS_DHL", "RFCTYPE": "H", "desc": "DHL shipment tracking"},
        {"RFCDEST": "Z_LOGISTICS_DTDC", "RFCTYPE": "H", "desc": "DTDC courier API"},
        {"RFCDEST": "Z_SALESFORCE", "RFCTYPE": "H", "desc": "Salesforce CRM sync"},
        {"RFCDEST": "Z_POWER_BI", "RFCTYPE": "H", "desc": "Power BI data feed"},
        {"RFCDEST": "Z_EMAIL_SMTP", "RFCTYPE": "H", "desc": "SMTP email relay"},
        {"RFCDEST": "Z_SMS_GATEWAY", "RFCTYPE": "H", "desc": "SMS gateway API"},
        {"RFCDEST": "Z_WHATSAPP_API", "RFCTYPE": "H", "desc": "WhatsApp Business API"},
        # External programs
        {"RFCDEST": "Z_BARCODE_PRINT", "RFCTYPE": "G", "desc": "Barcode printer RFC"},
        {"RFCDEST": "Z_WEIGHBRIDGE", "RFCTYPE": "G", "desc": "Weighbridge integration"},
        {"RFCDEST": "Z_PLC_SCADA", "RFCTYPE": "G", "desc": "PLC/SCADA shop floor"},
        {"RFCDEST": "Z_BIOMETRIC", "RFCTYPE": "G", "desc": "Biometric attendance"},
    ]

    # Add remaining to reach 67
    for i in range(len(destinations), 67):
        destinations.append({
            "RFCDEST": f"Z_INT_{i:03d}",
            "RFCTYPE": random.choice(["3", "H", "H", "H"]),
            "desc": f"Integration endpoint {i}",
        })

    for d in destinations:
        type_names = {"3": "ABAP_connection", "H": "HTTP_connection", "G": "external_program", "T": "TCP_IP"}
        d["name"] = d["RFCDEST"]
        d["type"] = type_names.get(d["RFCTYPE"], d["RFCTYPE"])
        d["type_code"] = d["RFCTYPE"]
        d["is_sap_standard"] = not d["RFCDEST"].startswith("Z")

    return destinations


# =============================================================================
# IDoc PARTNERS (30)
# =============================================================================
def generate_idoc_partners():
    return [
        # =====================================================================
        # CUSTOM / Z-IDOC PARTNERS (India-specific integrations)
        # =====================================================================
        {"RCVPRN": "GSTN_PROD", "RCVPRT": "LS", "MESTYP": "ZINVOICE", "IDOCTP": "ZGST_INV01", "RCVPOR": "SAPGSTN", "desc": "GST Network production"},
        {"RCVPRN": "TALLY_001", "RCVPRT": "LS", "MESTYP": "ZFINPOST", "IDOCTP": "ZFIDOC01", "RCVPOR": "SAPTALLY", "desc": "Tally financial sync"},
        {"RCVPRN": "HDFC_BANK", "RCVPRT": "LS", "MESTYP": "ZPAYMENT", "IDOCTP": "ZPAY_IDC01", "RCVPOR": "SAPHDFC", "desc": "HDFC bank payments"},
        {"RCVPRN": "SBI_BANK", "RCVPRT": "LS", "MESTYP": "ZPAYMENT", "IDOCTP": "ZPAY_IDC01", "RCVPOR": "SAPSBI", "desc": "SBI bank payments"},
        {"RCVPRN": "ICICI_BANK", "RCVPRT": "LS", "MESTYP": "ZPAYMENT", "IDOCTP": "ZPAY_IDC01", "RCVPOR": "SAPICICI", "desc": "ICICI bank payments"},
        {"RCVPRN": "AXIS_BANK", "RCVPRT": "LS", "MESTYP": "ZPAYMENT", "IDOCTP": "ZPAY_IDC01", "RCVPOR": "SAPAXIS", "desc": "Axis bank payments"},
        {"RCVPRN": "EINVOICE", "RCVPRT": "LS", "MESTYP": "ZINVQR", "IDOCTP": "ZEINV01", "RCVPOR": "SAPNIC", "desc": "E-invoice NIC portal"},
        {"RCVPRN": "EWAY_NIC", "RCVPRT": "LS", "MESTYP": "ZEWAY", "IDOCTP": "ZEWAY01", "RCVPOR": "SAPNIC", "desc": "E-way bill NIC portal"},
        {"RCVPRN": "TRACES_GOV", "RCVPRT": "LS", "MESTYP": "ZTDS", "IDOCTP": "ZTDS_IDC01", "RCVPOR": "SAPGOV", "desc": "TDS TRACES integration"},
        {"RCVPRN": "PORTAL_EMP", "RCVPRT": "LS", "MESTYP": "ZEMPDATA", "IDOCTP": "ZEMP_IDC01", "RCVPOR": "SAPPORT", "desc": "Employee portal sync"},
        {"RCVPRN": "SFDC_CRM", "RCVPRT": "LS", "MESTYP": "ZCUSTOMER", "IDOCTP": "ZCUST_IDC01", "RCVPOR": "SAPSFDC", "desc": "Salesforce CRM sync"},
        {"RCVPRN": "BW_SYSTEM", "RCVPRT": "LS", "MESTYP": "ZFACT", "IDOCTP": "ZBWEXT01", "RCVPOR": "SAPBW", "desc": "BW extraction IDocs"},

        # =====================================================================
        # ORDERS / ORDERS05 — Purchase Orders (vendor partners)
        # =====================================================================
        {"RCVPRN": "VENDOR_P1", "RCVPRT": "LI", "MESTYP": "ORDERS", "IDOCTP": "ORDERS05", "RCVPOR": "SAPEDI", "desc": "Vendor EDI orders - Tata Steel"},
        {"RCVPRN": "VENDOR_P2", "RCVPRT": "LI", "MESTYP": "ORDERS", "IDOCTP": "ORDERS05", "RCVPOR": "SAPEDI", "desc": "Vendor EDI orders - JSW Steel"},
        {"RCVPRN": "VENDOR_P3", "RCVPRT": "LI", "MESTYP": "ORDERS", "IDOCTP": "ORDERS05", "RCVPOR": "SAPEDI", "desc": "Vendor EDI orders - Hindalco"},
        {"RCVPRN": "VENDOR_P4", "RCVPRT": "LI", "MESTYP": "ORDERS", "IDOCTP": "ORDERS05", "RCVPOR": "SAPEDI", "desc": "Vendor EDI orders - Vedanta"},
        {"RCVPRN": "VENDOR_P5", "RCVPRT": "LI", "MESTYP": "ORDERS", "IDOCTP": "ORDERS05", "RCVPOR": "SAPEDI", "desc": "Vendor EDI orders - Bosch India"},
        {"RCVPRN": "VENDOR_P6", "RCVPRT": "LI", "MESTYP": "ORDERS", "IDOCTP": "ORDERS05", "RCVPOR": "SAPEDI", "desc": "Vendor EDI orders - Siemens India"},
        {"RCVPRN": "VENDOR_P7", "RCVPRT": "LI", "MESTYP": "ORDERS", "IDOCTP": "ORDERS05", "RCVPOR": "SAPEDI", "desc": "Vendor EDI orders - ABB India"},
        {"RCVPRN": "VENDOR_P8", "RCVPRT": "LI", "MESTYP": "ORDERS", "IDOCTP": "ORDERS05", "RCVPOR": "SAPEDI", "desc": "Vendor EDI orders - Larsen Toubro"},
        {"RCVPRN": "VENDOR_P9", "RCVPRT": "LI", "MESTYP": "ORDERS", "IDOCTP": "ORDERS05", "RCVPOR": "SAPEDI", "desc": "Vendor EDI orders - Bharat Forge"},
        {"RCVPRN": "VENDOR_P10", "RCVPRT": "LI", "MESTYP": "ORDERS", "IDOCTP": "ORDERS05", "RCVPOR": "SAPEDI", "desc": "Vendor EDI orders - Thermax"},
        {"RCVPRN": "ARIBA_PROC", "RCVPRT": "LS", "MESTYP": "ORDERS", "IDOCTP": "ORDERS05", "RCVPOR": "SAPARBA", "desc": "Ariba procurement orders"},

        # =====================================================================
        # INVOIC / INVOIC02 — Invoices (customer EDI partners)
        # =====================================================================
        {"RCVPRN": "CUST_EDI1", "RCVPRT": "KU", "MESTYP": "INVOIC", "IDOCTP": "INVOIC02", "RCVPOR": "SAPEDI", "desc": "Customer EDI invoices - Reliance"},
        {"RCVPRN": "CUST_EDI2", "RCVPRT": "KU", "MESTYP": "INVOIC", "IDOCTP": "INVOIC02", "RCVPOR": "SAPEDI", "desc": "Customer EDI invoices - Adani"},
        {"RCVPRN": "CUST_EDI3", "RCVPRT": "KU", "MESTYP": "INVOIC", "IDOCTP": "INVOIC02", "RCVPOR": "SAPEDI", "desc": "Customer EDI invoices - Mahindra"},
        {"RCVPRN": "CUST_EDI4", "RCVPRT": "KU", "MESTYP": "INVOIC", "IDOCTP": "INVOIC02", "RCVPOR": "SAPEDI", "desc": "Customer EDI invoices - Bajaj"},
        {"RCVPRN": "CUST_EDI5", "RCVPRT": "KU", "MESTYP": "INVOIC", "IDOCTP": "INVOIC02", "RCVPOR": "SAPEDI", "desc": "Customer EDI invoices - Godrej"},
        {"RCVPRN": "CUST_EDI6", "RCVPRT": "KU", "MESTYP": "INVOIC", "IDOCTP": "INVOIC02", "RCVPOR": "SAPEDI", "desc": "Customer EDI invoices - Tata Motors"},
        {"RCVPRN": "CUST_EDI7", "RCVPRT": "KU", "MESTYP": "INVOIC", "IDOCTP": "INVOIC02", "RCVPOR": "SAPEDI", "desc": "Customer EDI invoices - Hero MotoCorp"},

        # =====================================================================
        # DESADV / DELVRY03 — Delivery Advice / ASN
        # =====================================================================
        {"RCVPRN": "DHL_SHIP", "RCVPRT": "LS", "MESTYP": "DESADV", "IDOCTP": "DELVRY03", "RCVPOR": "SAPDHL", "desc": "DHL shipping ASN"},
        {"RCVPRN": "FEDEX_SHIP", "RCVPRT": "LS", "MESTYP": "DESADV", "IDOCTP": "DELVRY03", "RCVPOR": "SAPFEDX", "desc": "FedEx shipping ASN"},
        {"RCVPRN": "BLUEDART_SHIP", "RCVPRT": "LS", "MESTYP": "DESADV", "IDOCTP": "DELVRY03", "RCVPOR": "SAPBLUE", "desc": "BlueDart shipping ASN"},
        {"RCVPRN": "DTDC_SHIP", "RCVPRT": "LS", "MESTYP": "DESADV", "IDOCTP": "DELVRY03", "RCVPOR": "SAPDTDC", "desc": "DTDC shipping ASN"},
        {"RCVPRN": "VENDOR_P4", "RCVPRT": "LI", "MESTYP": "DESADV", "IDOCTP": "DELVRY03", "RCVPOR": "SAPEDI", "desc": "Vendor ASN - Vedanta"},

        # =====================================================================
        # MATMAS / MATMAS05 — Material Master Distribution
        # =====================================================================
        {"RCVPRN": "MATMAS_SUB", "RCVPRT": "LS", "MESTYP": "MATMAS", "IDOCTP": "MATMAS05", "RCVPOR": "SAPSUB", "desc": "Material master to subsidiary"},
        {"RCVPRN": "MATMAS_QA", "RCVPRT": "LS", "MESTYP": "MATMAS", "IDOCTP": "MATMAS05", "RCVPOR": "SAPQA", "desc": "Material master to QA system"},
        {"RCVPRN": "MATMAS_DR", "RCVPRT": "LS", "MESTYP": "MATMAS", "IDOCTP": "MATMAS05", "RCVPOR": "SAPDR", "desc": "Material master to DR system"},
        {"RCVPRN": "MATMAS_PR", "RCVPRT": "LS", "MESTYP": "MATMAS", "IDOCTP": "MATMAS05", "RCVPOR": "SAPPR", "desc": "Material master to pre-prod system"},

        # =====================================================================
        # DEBMAS / DEBMAS07 — Customer Master Distribution
        # =====================================================================
        {"RCVPRN": "DEBMAS_BW", "RCVPRT": "LS", "MESTYP": "DEBMAS", "IDOCTP": "DEBMAS07", "RCVPOR": "SAPBW", "desc": "Customer master to BW"},
        {"RCVPRN": "DEBMAS_QA", "RCVPRT": "LS", "MESTYP": "DEBMAS", "IDOCTP": "DEBMAS07", "RCVPOR": "SAPQA", "desc": "Customer master to QA system"},
        {"RCVPRN": "DEBMAS_CRM", "RCVPRT": "LS", "MESTYP": "DEBMAS", "IDOCTP": "DEBMAS07", "RCVPOR": "SAPCRM", "desc": "Customer master to CRM system"},

        # =====================================================================
        # CREMAS / CREMAS05 — Vendor Master Distribution
        # =====================================================================
        {"RCVPRN": "CREMAS_BW", "RCVPRT": "LS", "MESTYP": "CREMAS", "IDOCTP": "CREMAS05", "RCVPOR": "SAPBW", "desc": "Vendor master to BW"},
        {"RCVPRN": "CREMAS_QA", "RCVPRT": "LS", "MESTYP": "CREMAS", "IDOCTP": "CREMAS05", "RCVPOR": "SAPQA", "desc": "Vendor master to QA system"},
        {"RCVPRN": "CREMAS_SRM", "RCVPRT": "LS", "MESTYP": "CREMAS", "IDOCTP": "CREMAS05", "RCVPOR": "SAPSRM", "desc": "Vendor master to SRM system"},

        # =====================================================================
        # WMMBID / WMMBID02 — Warehouse Management
        # =====================================================================
        {"RCVPRN": "WMS_PROD", "RCVPRT": "LS", "MESTYP": "WMMBID", "IDOCTP": "WMMBID02", "RCVPOR": "SAPWMS", "desc": "Warehouse mgmt production"},
        {"RCVPRN": "WMS_STAG", "RCVPRT": "LS", "MESTYP": "WMMBID", "IDOCTP": "WMMBID02", "RCVPOR": "SAPWMSS", "desc": "Warehouse mgmt staging area"},
        {"RCVPRN": "WMS_QUAL", "RCVPRT": "LS", "MESTYP": "WMMBID", "IDOCTP": "WMMBID02", "RCVPOR": "SAPWMSQ", "desc": "Warehouse mgmt quality inspection"},

        # =====================================================================
        # SHPMNT / SHPMNT05 — Shipment
        # =====================================================================
        {"RCVPRN": "SHPMNT_3PL", "RCVPRT": "LS", "MESTYP": "SHPMNT", "IDOCTP": "SHPMNT05", "RCVPOR": "SAP3PL", "desc": "Shipment to 3PL provider"},
        {"RCVPRN": "SHPMNT_DHL2", "RCVPRT": "LS", "MESTYP": "SHPMNT", "IDOCTP": "SHPMNT05", "RCVPOR": "SAPDHL2", "desc": "Shipment to DHL Freight"},
        {"RCVPRN": "SHPMNT_UPS", "RCVPRT": "LS", "MESTYP": "SHPMNT", "IDOCTP": "SHPMNT05", "RCVPOR": "SAPUPS", "desc": "Shipment to UPS Logistics"},

        # =====================================================================
        # HRMD_A / HRMD_A07 — HR Master Data
        # =====================================================================
        {"RCVPRN": "HRMASTER", "RCVPRT": "LS", "MESTYP": "HRMD_A", "IDOCTP": "HRMD_A07", "RCVPOR": "SAPSF", "desc": "HR master to SuccessFactors EC"},
        {"RCVPRN": "SF_RECRUIT", "RCVPRT": "LS", "MESTYP": "HRMD_A", "IDOCTP": "HRMD_A07", "RCVPOR": "SAPSFRC", "desc": "HR master to SF Recruiting"},
        {"RCVPRN": "SF_PERF", "RCVPRT": "LS", "MESTYP": "HRMD_A", "IDOCTP": "HRMD_A07", "RCVPOR": "SAPSFPM", "desc": "HR master to SF Performance Mgmt"},

        # =====================================================================
        # LOIPRO / LOIPRO01 — Production Orders
        # =====================================================================
        {"RCVPRN": "MES_PLANT1", "RCVPRT": "LS", "MESTYP": "LOIPRO", "IDOCTP": "LOIPRO01", "RCVPOR": "SAPMES", "desc": "MES production orders Plant 1"},
        {"RCVPRN": "MES_PLANT2", "RCVPRT": "LS", "MESTYP": "LOIPRO", "IDOCTP": "LOIPRO01", "RCVPOR": "SAPMES2", "desc": "MES production orders Plant 2"},
        {"RCVPRN": "MES_PLANT3", "RCVPRT": "LS", "MESTYP": "LOIPRO", "IDOCTP": "LOIPRO01", "RCVPOR": "SAPMES3", "desc": "MES production orders Plant 3"},

        # =====================================================================
        # PORDCR / PORDCR05 — Purchase Order Creation (confirmation)
        # =====================================================================
        {"RCVPRN": "PORDCR_ARIBA", "RCVPRT": "LS", "MESTYP": "PORDCR", "IDOCTP": "PORDCR05", "RCVPOR": "SAPARBA", "desc": "PO creation confirmation to Ariba"},
        {"RCVPRN": "PORDCR_SRM", "RCVPRT": "LS", "MESTYP": "PORDCR", "IDOCTP": "PORDCR05", "RCVPOR": "SAPSRM", "desc": "PO creation confirmation to SRM"},

        # =====================================================================
        # ORDCHG / ORDCHG05 — Order Change
        # =====================================================================
        {"RCVPRN": "ORDCHG_VND1", "RCVPRT": "LI", "MESTYP": "ORDCHG", "IDOCTP": "ORDCHG05", "RCVPOR": "SAPEDI", "desc": "Order change notification to vendor"},
        {"RCVPRN": "ORDCHG_ARBA", "RCVPRT": "LS", "MESTYP": "ORDCHG", "IDOCTP": "ORDCHG05", "RCVPOR": "SAPARBA", "desc": "Order change notification to Ariba"},

        # =====================================================================
        # REMADV / REMADV01 — Payment Advice / Remittance
        # =====================================================================
        {"RCVPRN": "BANK_REMADV", "RCVPRT": "LS", "MESTYP": "REMADV", "IDOCTP": "REMADV01", "RCVPOR": "SAPBNK", "desc": "Payment remittance advice to bank"},

        # =====================================================================
        # GSVERF / GSVERF01 — Goods Receipt Verification
        # =====================================================================
        {"RCVPRN": "WMS_GR", "RCVPRT": "LS", "MESTYP": "GSVERF", "IDOCTP": "GSVERF01", "RCVPOR": "SAPWMS", "desc": "Goods receipt verification to WMS"},

        # =====================================================================
        # MBGMCR / MBGMCR03 — Goods Movement
        # =====================================================================
        {"RCVPRN": "WMS_MVMT", "RCVPRT": "LS", "MESTYP": "MBGMCR", "IDOCTP": "MBGMCR03", "RCVPOR": "SAPWMS", "desc": "Goods movement to WMS"},
        {"RCVPRN": "MES_MVMT", "RCVPRT": "LS", "MESTYP": "MBGMCR", "IDOCTP": "MBGMCR03", "RCVPOR": "SAPMES", "desc": "Goods movement to MES"},

        # =====================================================================
        # COND_A / COND_A06 — Conditions / Pricing
        # =====================================================================
        {"RCVPRN": "PRICING_DIST", "RCVPRT": "LS", "MESTYP": "COND_A", "IDOCTP": "COND_A06", "RCVPOR": "SAPSUB", "desc": "Pricing condition distribution"},

        # =====================================================================
        # TXTRAW / TXTRAW01 — Long Text Distribution
        # =====================================================================
        {"RCVPRN": "BW_TEXT", "RCVPRT": "LS", "MESTYP": "TXTRAW", "IDOCTP": "TXTRAW01", "RCVPOR": "SAPBW", "desc": "Long text distribution to BW"},

        # =====================================================================
        # FIDCCP — FI Document Change Pointer
        # =====================================================================
        {"RCVPRN": "FIDCCP_BW", "RCVPRT": "LS", "MESTYP": "FIDCCP", "IDOCTP": "FIDCCP01", "RCVPOR": "SAPBW", "desc": "FI document change pointer to BW"},

        # =====================================================================
        # GLMAST — GL Master Data Distribution
        # =====================================================================
        {"RCVPRN": "GLMAST_SUB", "RCVPRT": "LS", "MESTYP": "GLMAST", "IDOCTP": "GLMAST01", "RCVPOR": "SAPSUB", "desc": "GL master data to subsidiary"},
        {"RCVPRN": "GLMAST_BW", "RCVPRT": "LS", "MESTYP": "GLMAST", "IDOCTP": "GLMAST01", "RCVPOR": "SAPBW", "desc": "GL master data to BW"},

        # =====================================================================
        # COSMAS — Cost Center Master Distribution
        # =====================================================================
        {"RCVPRN": "COSMAS_BW", "RCVPRT": "LS", "MESTYP": "COSMAS", "IDOCTP": "COSMAS04", "RCVPOR": "SAPBW", "desc": "Cost center master to BW"},
        {"RCVPRN": "COSMAS_SUB", "RCVPRT": "LS", "MESTYP": "COSMAS", "IDOCTP": "COSMAS04", "RCVPOR": "SAPSUB", "desc": "Cost center master to subsidiary"},

        # =====================================================================
        # ADRMAS — Address Master Distribution
        # =====================================================================
        {"RCVPRN": "ADRMAS_CRM", "RCVPRT": "LS", "MESTYP": "ADRMAS", "IDOCTP": "ADRMAS03", "RCVPOR": "SAPCRM", "desc": "Address master to CRM"},
        {"RCVPRN": "ADRMAS_BW", "RCVPRT": "LS", "MESTYP": "ADRMAS", "IDOCTP": "ADRMAS03", "RCVPOR": "SAPBW", "desc": "Address master to BW"},

        # =====================================================================
        # QM_QMEL — Quality Notifications
        # =====================================================================
        {"RCVPRN": "QM_QMEL_MES", "RCVPRT": "LS", "MESTYP": "QM_QMEL", "IDOCTP": "QM_QMEL01", "RCVPOR": "SAPMES", "desc": "Quality notifications to MES"},
        {"RCVPRN": "QM_QMEL_WMS", "RCVPRT": "LS", "MESTYP": "QM_QMEL", "IDOCTP": "QM_QMEL01", "RCVPOR": "SAPWMS", "desc": "Quality notifications to WMS"},

        # =====================================================================
        # CUST_EDI — Customer EDI for Orders and Delivery
        # =====================================================================
        {"RCVPRN": "CUST_EDI4", "RCVPRT": "KU", "MESTYP": "ORDERS", "IDOCTP": "ORDERS05", "RCVPOR": "SAPEDI", "desc": "Customer EDI orders - Bajaj"},

        # =====================================================================
        # ORDERS — Additional Purchase Order vendor partners
        # =====================================================================
        {"RCVPRN": "VENDOR_P11", "SNDPRN": "BIS1000", "RCVPRT": "LI", "SNDPRT": "LS", "MESTYP": "ORDERS", "IDOCTP": "ORDERS05", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Vendor EDI orders - Kirloskar"},
        {"RCVPRN": "VENDOR_P12", "SNDPRN": "BIS1000", "RCVPRT": "LI", "SNDPRT": "LS", "MESTYP": "ORDERS", "IDOCTP": "ORDERS05", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Vendor EDI orders - Cummins India"},
        {"RCVPRN": "VENDOR_P13", "SNDPRN": "BIS1000", "RCVPRT": "LI", "SNDPRT": "LS", "MESTYP": "ORDERS", "IDOCTP": "ORDERS05", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Vendor EDI orders - Schneider Electric"},
        {"RCVPRN": "VENDOR_P14", "SNDPRN": "BIS1000", "RCVPRT": "LI", "SNDPRT": "LS", "MESTYP": "ORDERS", "IDOCTP": "ORDERS05", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Vendor EDI orders - Havells India"},
        {"RCVPRN": "VENDOR_P15", "SNDPRN": "BIS1000", "RCVPRT": "LI", "SNDPRT": "LS", "MESTYP": "ORDERS", "IDOCTP": "ORDERS05", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Vendor EDI orders - Ashok Leyland"},
        {"RCVPRN": "VENDOR_P16", "SNDPRN": "BIS1000", "RCVPRT": "LI", "SNDPRT": "LS", "MESTYP": "ORDERS", "IDOCTP": "ORDERS05", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Vendor EDI orders - Crompton Greaves"},
        {"RCVPRN": "VENDOR_P17", "SNDPRN": "BIS1000", "RCVPRT": "LI", "SNDPRT": "LS", "MESTYP": "ORDERS", "IDOCTP": "ORDERS05", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Vendor EDI orders - Bharat Electronics"},
        {"RCVPRN": "VENDOR_P18", "SNDPRN": "BIS1000", "RCVPRT": "LI", "SNDPRT": "LS", "MESTYP": "ORDERS", "IDOCTP": "ORDERS05", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Vendor EDI orders - Carborundum Universal"},
        {"RCVPRN": "VENDOR_P19", "SNDPRN": "BIS1000", "RCVPRT": "LI", "SNDPRT": "LS", "MESTYP": "ORDERS", "IDOCTP": "ORDERS05", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Vendor EDI orders - GMR Infrastructure"},
        {"RCVPRN": "VENDOR_P20", "SNDPRN": "BIS1000", "RCVPRT": "LI", "SNDPRT": "LS", "MESTYP": "ORDERS", "IDOCTP": "ORDERS05", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Vendor EDI orders - Tata Chemicals"},

        # =====================================================================
        # ORDRSP / ORDRSP05 — Order Response
        # =====================================================================
        {"RCVPRN": "ORDRSP_VND1", "SNDPRN": "BIS1000", "RCVPRT": "LI", "SNDPRT": "LS", "MESTYP": "ORDRSP", "IDOCTP": "ORDERS05", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Order response - Tata Steel"},
        {"RCVPRN": "ORDRSP_VND2", "SNDPRN": "BIS1000", "RCVPRT": "LI", "SNDPRT": "LS", "MESTYP": "ORDRSP", "IDOCTP": "ORDERS05", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Order response - JSW Steel"},
        {"RCVPRN": "ORDRSP_VND3", "SNDPRN": "BIS1000", "RCVPRT": "LI", "SNDPRT": "LS", "MESTYP": "ORDRSP", "IDOCTP": "ORDERS05", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Order response - Hindalco"},
        {"RCVPRN": "ORDRSP_VND4", "SNDPRN": "BIS1000", "RCVPRT": "LI", "SNDPRT": "LS", "MESTYP": "ORDRSP", "IDOCTP": "ORDERS05", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Order response - Bosch India"},
        {"RCVPRN": "ORDRSP_ARBA", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "ORDRSP", "IDOCTP": "ORDERS05", "RCVPOR": "SAPARBA", "SNDPOR": "SAP1000", "desc": "Order response - Ariba"},

        # =====================================================================
        # DESADV — Additional Dispatch Advice / ASN partners
        # =====================================================================
        {"RCVPRN": "GATI_SHIP", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "DESADV", "IDOCTP": "DELVRY03", "RCVPOR": "SAPGATI", "SNDPOR": "SAP1000", "desc": "Gati shipping ASN"},
        {"RCVPRN": "DELHIVERY_SHIP", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "DESADV", "IDOCTP": "DELVRY03", "RCVPOR": "SAPDLVR", "SNDPOR": "SAP1000", "desc": "Delhivery shipping ASN"},
        {"RCVPRN": "MAERSK_SHIP", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "DESADV", "IDOCTP": "DELVRY03", "RCVPOR": "SAPMRSK", "SNDPOR": "SAP1000", "desc": "Maersk shipping ASN"},
        {"RCVPRN": "VENDOR_P5", "SNDPRN": "BIS1000", "RCVPRT": "LI", "SNDPRT": "LS", "MESTYP": "DESADV", "IDOCTP": "DELVRY03", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Vendor ASN - Bosch India"},
        {"RCVPRN": "VENDOR_P6", "SNDPRN": "BIS1000", "RCVPRT": "LI", "SNDPRT": "LS", "MESTYP": "DESADV", "IDOCTP": "DELVRY03", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Vendor ASN - Siemens India"},
        {"RCVPRN": "VENDOR_P7", "SNDPRN": "BIS1000", "RCVPRT": "LI", "SNDPRT": "LS", "MESTYP": "DESADV", "IDOCTP": "DELVRY03", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Vendor ASN - ABB India"},
        {"RCVPRN": "SAFEX_SHIP", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "DESADV", "IDOCTP": "DELVRY03", "RCVPOR": "SAPSAFX", "SNDPOR": "SAP1000", "desc": "Safexpress shipping ASN"},
        {"RCVPRN": "ALLCARGO_SHIP", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "DESADV", "IDOCTP": "DELVRY03", "RCVPOR": "SAPALLC", "SNDPOR": "SAP1000", "desc": "Allcargo shipping ASN"},

        # =====================================================================
        # SHPMNT — Additional Shipment partners
        # =====================================================================
        {"RCVPRN": "SHPMNT_GATI", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "SHPMNT", "IDOCTP": "SHPMNT05", "RCVPOR": "SAPGATI", "SNDPOR": "SAP1000", "desc": "Shipment to Gati Logistics"},
        {"RCVPRN": "SHPMNT_MAER", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "SHPMNT", "IDOCTP": "SHPMNT05", "RCVPOR": "SAPMRSK", "SNDPOR": "SAP1000", "desc": "Shipment to Maersk Freight"},
        {"RCVPRN": "SHPMNT_TNT", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "SHPMNT", "IDOCTP": "SHPMNT05", "RCVPOR": "SAPTNT", "SNDPOR": "SAP1000", "desc": "Shipment to TNT Express"},
        {"RCVPRN": "SHPMNT_SAFX", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "SHPMNT", "IDOCTP": "SHPMNT05", "RCVPOR": "SAPSAFX", "SNDPOR": "SAP1000", "desc": "Shipment to Safexpress"},
        {"RCVPRN": "SHPMNT_ALLC", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "SHPMNT", "IDOCTP": "SHPMNT05", "RCVPOR": "SAPALLC", "SNDPOR": "SAP1000", "desc": "Shipment to Allcargo Logistics"},

        # =====================================================================
        # INVOIC — Additional Invoice partners
        # =====================================================================
        {"RCVPRN": "CUST_EDI8", "SNDPRN": "BIS1000", "RCVPRT": "KU", "SNDPRT": "LS", "MESTYP": "INVOIC", "IDOCTP": "INVOIC02", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Customer EDI invoices - Hindalco"},
        {"RCVPRN": "CUST_EDI9", "SNDPRN": "BIS1000", "RCVPRT": "KU", "SNDPRT": "LS", "MESTYP": "INVOIC", "IDOCTP": "INVOIC02", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Customer EDI invoices - Vedanta"},
        {"RCVPRN": "CUST_EDI10", "SNDPRN": "BIS1000", "RCVPRT": "KU", "SNDPRT": "LS", "MESTYP": "INVOIC", "IDOCTP": "INVOIC02", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Customer EDI invoices - L&T"},
        {"RCVPRN": "CUST_EDI11", "SNDPRN": "BIS1000", "RCVPRT": "KU", "SNDPRT": "LS", "MESTYP": "INVOIC", "IDOCTP": "INVOIC02", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Customer EDI invoices - Thermax"},
        {"RCVPRN": "CUST_EDI12", "SNDPRN": "BIS1000", "RCVPRT": "KU", "SNDPRT": "LS", "MESTYP": "INVOIC", "IDOCTP": "INVOIC02", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Customer EDI invoices - Kirloskar"},
        {"RCVPRN": "CUST_EDI13", "SNDPRN": "BIS1000", "RCVPRT": "KU", "SNDPRT": "LS", "MESTYP": "INVOIC", "IDOCTP": "INVOIC02", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Customer EDI invoices - BHEL"},
        {"RCVPRN": "EINV_PARTNER", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "INVOIC", "IDOCTP": "INVOIC02", "RCVPOR": "SAPNIC", "SNDPOR": "SAP1000", "desc": "E-Invoice IRP portal integration"},
        {"RCVPRN": "ARIBA_INV", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "INVOIC", "IDOCTP": "INVOIC02", "RCVPOR": "SAPARBA", "SNDPOR": "SAP1000", "desc": "Ariba invoice integration"},

        # =====================================================================
        # REMADV / REMADV01 — Additional Remittance Advice partners
        # =====================================================================
        {"RCVPRN": "REMADV_HDFC", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "REMADV", "IDOCTP": "REMADV01", "RCVPOR": "SAPHDFC", "SNDPOR": "SAP1000", "desc": "Remittance advice to HDFC Bank"},
        {"RCVPRN": "REMADV_SBI", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "REMADV", "IDOCTP": "REMADV01", "RCVPOR": "SAPSBI", "SNDPOR": "SAP1000", "desc": "Remittance advice to SBI"},
        {"RCVPRN": "REMADV_ICICI", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "REMADV", "IDOCTP": "REMADV01", "RCVPOR": "SAPICICI", "SNDPOR": "SAP1000", "desc": "Remittance advice to ICICI Bank"},
        {"RCVPRN": "REMADV_AXIS", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "REMADV", "IDOCTP": "REMADV01", "RCVPOR": "SAPAXIS", "SNDPOR": "SAP1000", "desc": "Remittance advice to Axis Bank"},
        {"RCVPRN": "REMADV_KOTA", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "REMADV", "IDOCTP": "REMADV01", "RCVPOR": "SAPKOTK", "SNDPOR": "SAP1000", "desc": "Remittance advice to Kotak Bank"},

        # =====================================================================
        # PAYEXT / PAYEXT01 — Payment Order
        # =====================================================================
        {"RCVPRN": "PAYEXT_HDFC", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "PAYEXT", "IDOCTP": "PAYEXT01", "RCVPOR": "SAPHDFC", "SNDPOR": "SAP1000", "desc": "Payment order to HDFC Bank"},
        {"RCVPRN": "PAYEXT_SBI", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "PAYEXT", "IDOCTP": "PAYEXT01", "RCVPOR": "SAPSBI", "SNDPOR": "SAP1000", "desc": "Payment order to SBI"},
        {"RCVPRN": "PAYEXT_ICICI", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "PAYEXT", "IDOCTP": "PAYEXT01", "RCVPOR": "SAPICICI", "SNDPOR": "SAP1000", "desc": "Payment order to ICICI Bank"},
        {"RCVPRN": "PAYEXT_AXIS", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "PAYEXT", "IDOCTP": "PAYEXT01", "RCVPOR": "SAPAXIS", "SNDPOR": "SAP1000", "desc": "Payment order to Axis Bank"},
        {"RCVPRN": "PAYEXT_KOTK", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "PAYEXT", "IDOCTP": "PAYEXT01", "RCVPOR": "SAPKOTK", "SNDPOR": "SAP1000", "desc": "Payment order to Kotak Bank"},

        # =====================================================================
        # DEBMUL — Debit Multiple
        # =====================================================================
        {"RCVPRN": "DEBMUL_HDFC", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "DEBMUL", "IDOCTP": "DEBMUL03", "RCVPOR": "SAPHDFC", "SNDPOR": "SAP1000", "desc": "Debit multiple to HDFC Bank"},
        {"RCVPRN": "DEBMUL_SBI", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "DEBMUL", "IDOCTP": "DEBMUL03", "RCVPOR": "SAPSBI", "SNDPOR": "SAP1000", "desc": "Debit multiple to SBI"},
        {"RCVPRN": "DEBMUL_ICICI", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "DEBMUL", "IDOCTP": "DEBMUL03", "RCVPOR": "SAPICICI", "SNDPOR": "SAP1000", "desc": "Debit multiple to ICICI Bank"},

        # =====================================================================
        # CREADV — Credit Advice
        # =====================================================================
        {"RCVPRN": "CREADV_HDFC", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "CREADV", "IDOCTP": "CREADV03", "RCVPOR": "SAPHDFC", "SNDPOR": "SAP1000", "desc": "Credit advice from HDFC Bank"},
        {"RCVPRN": "CREADV_SBI", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "CREADV", "IDOCTP": "CREADV03", "RCVPOR": "SAPSBI", "SNDPOR": "SAP1000", "desc": "Credit advice from SBI"},
        {"RCVPRN": "CREADV_ICICI", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "CREADV", "IDOCTP": "CREADV03", "RCVPOR": "SAPICICI", "SNDPOR": "SAP1000", "desc": "Credit advice from ICICI Bank"},

        # =====================================================================
        # FINSTA — Financial Statement
        # =====================================================================
        {"RCVPRN": "FINSTA_HDFC", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "FINSTA", "IDOCTP": "FINSTA01", "RCVPOR": "SAPHDFC", "SNDPOR": "SAP1000", "desc": "Bank statement from HDFC"},
        {"RCVPRN": "FINSTA_SBI", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "FINSTA", "IDOCTP": "FINSTA01", "RCVPOR": "SAPSBI", "SNDPOR": "SAP1000", "desc": "Bank statement from SBI"},
        {"RCVPRN": "FINSTA_ICICI", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "FINSTA", "IDOCTP": "FINSTA01", "RCVPOR": "SAPICICI", "SNDPOR": "SAP1000", "desc": "Bank statement from ICICI"},

        # =====================================================================
        # HRMD_A — Additional HR Master Data partners
        # =====================================================================
        {"RCVPRN": "SF_LEARN", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "HRMD_A", "IDOCTP": "HRMD_A07", "RCVPOR": "SAPSFLM", "SNDPOR": "SAP1000", "desc": "HR master to SF Learning"},
        {"RCVPRN": "SF_COMP", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "HRMD_A", "IDOCTP": "HRMD_A07", "RCVPOR": "SAPSFCM", "SNDPOR": "SAP1000", "desc": "HR master to SF Compensation"},
        {"RCVPRN": "SF_ONBRD", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "HRMD_A", "IDOCTP": "HRMD_A07", "RCVPOR": "SAPSFOB", "SNDPOR": "SAP1000", "desc": "HR master to SF Onboarding"},
        {"RCVPRN": "DARWINBOX", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "HRMD_A", "IDOCTP": "HRMD_A07", "RCVPOR": "SAPDBOX", "SNDPOR": "SAP1000", "desc": "HR master to Darwinbox HRMS"},
        {"RCVPRN": "GREYTHR", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "HRMD_A", "IDOCTP": "HRMD_A07", "RCVPOR": "SAPGRYT", "SNDPOR": "SAP1000", "desc": "HR master to GreytHR"},

        # =====================================================================
        # MATMAS — Additional Material Master Distribution
        # =====================================================================
        {"RCVPRN": "MATMAS_EWM", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "MATMAS", "IDOCTP": "MATMAS05", "RCVPOR": "SAPEWM", "SNDPOR": "SAP1000", "desc": "Material master to EWM"},
        {"RCVPRN": "MATMAS_APO", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "MATMAS", "IDOCTP": "MATMAS05", "RCVPOR": "SAPAPO", "SNDPOR": "SAP1000", "desc": "Material master to APO/IBP"},
        {"RCVPRN": "MATMAS_BW", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "MATMAS", "IDOCTP": "MATMAS05", "RCVPOR": "SAPBW", "SNDPOR": "SAP1000", "desc": "Material master to BW"},
        {"RCVPRN": "MATMAS_MES", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "MATMAS", "IDOCTP": "MATMAS05", "RCVPOR": "SAPMES", "SNDPOR": "SAP1000", "desc": "Material master to MES"},
        {"RCVPRN": "MATMAS_CRM", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "MATMAS", "IDOCTP": "MATMAS05", "RCVPOR": "SAPCRM", "SNDPOR": "SAP1000", "desc": "Material master to CRM"},
        {"RCVPRN": "MATMAS_SRM", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "MATMAS", "IDOCTP": "MATMAS05", "RCVPOR": "SAPSRM", "SNDPOR": "SAP1000", "desc": "Material master to SRM"},
        {"RCVPRN": "MATMAS_WMS", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "MATMAS", "IDOCTP": "MATMAS05", "RCVPOR": "SAPWMS", "SNDPOR": "SAP1000", "desc": "Material master to WMS"},
        {"RCVPRN": "MATMAS_DSCM", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "MATMAS", "IDOCTP": "MATMAS05", "RCVPOR": "SAPDSCM", "SNDPOR": "SAP1000", "desc": "Material master to DSCM"},

        # =====================================================================
        # CREMAS — Additional Vendor Master Distribution
        # =====================================================================
        {"RCVPRN": "CREMAS_CRM", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "CREMAS", "IDOCTP": "CREMAS05", "RCVPOR": "SAPCRM", "SNDPOR": "SAP1000", "desc": "Vendor master to CRM"},
        {"RCVPRN": "CREMAS_ARBA", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "CREMAS", "IDOCTP": "CREMAS05", "RCVPOR": "SAPARBA", "SNDPOR": "SAP1000", "desc": "Vendor master to Ariba"},
        {"RCVPRN": "CREMAS_SUB", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "CREMAS", "IDOCTP": "CREMAS05", "RCVPOR": "SAPSUB", "SNDPOR": "SAP1000", "desc": "Vendor master to subsidiary"},
        {"RCVPRN": "CREMAS_BW2", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "CREMAS", "IDOCTP": "CREMAS05", "RCVPOR": "SAPBW2", "SNDPOR": "SAP1000", "desc": "Vendor master to BW analytics"},
        {"RCVPRN": "CREMAS_EWM", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "CREMAS", "IDOCTP": "CREMAS05", "RCVPOR": "SAPEWM", "SNDPOR": "SAP1000", "desc": "Vendor master to EWM"},

        # =====================================================================
        # DEBMAS — Additional Customer Master Distribution
        # =====================================================================
        {"RCVPRN": "DEBMAS_SUB", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "DEBMAS", "IDOCTP": "DEBMAS07", "RCVPOR": "SAPSUB", "SNDPOR": "SAP1000", "desc": "Customer master to subsidiary"},
        {"RCVPRN": "DEBMAS_ARBA", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "DEBMAS", "IDOCTP": "DEBMAS07", "RCVPOR": "SAPARBA", "SNDPOR": "SAP1000", "desc": "Customer master to Ariba network"},
        {"RCVPRN": "DEBMAS_MDG", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "DEBMAS", "IDOCTP": "DEBMAS07", "RCVPOR": "SAPMDG", "SNDPOR": "SAP1000", "desc": "Customer master to MDG hub"},
        {"RCVPRN": "DEBMAS_APO", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "DEBMAS", "IDOCTP": "DEBMAS07", "RCVPOR": "SAPAPO", "SNDPOR": "SAP1000", "desc": "Customer master to APO/IBP"},
        {"RCVPRN": "DEBMAS_EWM", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "DEBMAS", "IDOCTP": "DEBMAS07", "RCVPOR": "SAPEWM", "SNDPOR": "SAP1000", "desc": "Customer master to EWM"},

        # =====================================================================
        # BOMMAT / BOMMAT04 — BOM Distribution
        # =====================================================================
        {"RCVPRN": "BOMMAT_MES", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "BOMMAT", "IDOCTP": "BOMMAT04", "RCVPOR": "SAPMES", "SNDPOR": "SAP1000", "desc": "BOM distribution to MES"},
        {"RCVPRN": "BOMMAT_APO", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "BOMMAT", "IDOCTP": "BOMMAT04", "RCVPOR": "SAPAPO", "SNDPOR": "SAP1000", "desc": "BOM distribution to APO"},
        {"RCVPRN": "BOMMAT_BW", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "BOMMAT", "IDOCTP": "BOMMAT04", "RCVPOR": "SAPBW", "SNDPOR": "SAP1000", "desc": "BOM distribution to BW"},

        # =====================================================================
        # LOIPRO — Additional Production Order partners
        # =====================================================================

        # =====================================================================
        # LOIROU / LOIROU01 — Routing Distribution
        # =====================================================================
        {"RCVPRN": "LOIROU_MES1", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "LOIROU", "IDOCTP": "LOIROU01", "RCVPOR": "SAPMES", "SNDPOR": "SAP1000", "desc": "Routing distribution to MES Plant 1"},
        {"RCVPRN": "LOIROU_MES2", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "LOIROU", "IDOCTP": "LOIROU01", "RCVPOR": "SAPMES2", "SNDPOR": "SAP1000", "desc": "Routing distribution to MES Plant 2"},
        {"RCVPRN": "LOIROU_APO", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "LOIROU", "IDOCTP": "LOIROU01", "RCVPOR": "SAPAPO", "SNDPOR": "SAP1000", "desc": "Routing distribution to APO"},

        # =====================================================================
        # WMMBXY — Warehouse Management Goods Movement
        # =====================================================================
        {"RCVPRN": "WMMBXY_EWM1", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "WMMBXY", "IDOCTP": "WMMBXY03", "RCVPOR": "SAPEWM", "SNDPOR": "SAP1000", "desc": "WM goods movement to EWM"},
        {"RCVPRN": "WMMBXY_WMS2", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "WMMBXY", "IDOCTP": "WMMBXY03", "RCVPOR": "SAPWMS2", "SNDPOR": "SAP1000", "desc": "WM goods movement to external WMS"},
        {"RCVPRN": "WMMBXY_MES2", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "WMMBXY", "IDOCTP": "WMMBXY03", "RCVPOR": "SAPMES", "SNDPOR": "SAP1000", "desc": "WM goods movement to MES"},

        # =====================================================================
        # QALITY — Quality Management
        # =====================================================================
        {"RCVPRN": "QALITY_MES", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "QALITY", "IDOCTP": "QALITY03", "RCVPOR": "SAPMES", "SNDPOR": "SAP1000", "desc": "Quality data to MES"},
        {"RCVPRN": "QALITY_LIMS", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "QALITY", "IDOCTP": "QALITY03", "RCVPOR": "SAPLIMS", "SNDPOR": "SAP1000", "desc": "Quality data to LIMS"},
        {"RCVPRN": "QALITY_BW", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "QALITY", "IDOCTP": "QALITY03", "RCVPOR": "SAPBW", "SNDPOR": "SAP1000", "desc": "Quality data to BW analytics"},

        # =====================================================================
        # PORDCR — Additional PO Confirmation partners
        # =====================================================================
        {"RCVPRN": "PORDCR_VND1", "SNDPRN": "BIS1000", "RCVPRT": "LI", "SNDPRT": "LS", "MESTYP": "PORDCR", "IDOCTP": "PORDCR05", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "PO confirmation to Tata Steel"},
        {"RCVPRN": "PORDCR_VND2", "SNDPRN": "BIS1000", "RCVPRT": "LI", "SNDPRT": "LS", "MESTYP": "PORDCR", "IDOCTP": "PORDCR05", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "PO confirmation to JSW Steel"},
        {"RCVPRN": "PORDCR_VND3", "SNDPRN": "BIS1000", "RCVPRT": "LI", "SNDPRT": "LS", "MESTYP": "PORDCR", "IDOCTP": "PORDCR05", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "PO confirmation to Bosch India"},
        {"RCVPRN": "PORDCR_COUPA", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "PORDCR", "IDOCTP": "PORDCR05", "RCVPOR": "SAPCOUP", "SNDPOR": "SAP1000", "desc": "PO confirmation to Coupa"},
        {"RCVPRN": "PORDCR_BN", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "PORDCR", "IDOCTP": "PORDCR05", "RCVPOR": "SAPBN", "SNDPOR": "SAP1000", "desc": "PO confirmation to Business Network"},

        # =====================================================================
        # GSVERF — Additional Goods Receipt Verification / Credit Memo
        # =====================================================================
        {"RCVPRN": "GSVERF_MES", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "GSVERF", "IDOCTP": "GSVERF01", "RCVPOR": "SAPMES", "SNDPOR": "SAP1000", "desc": "GR verification to MES"},
        {"RCVPRN": "GSVERF_QM", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "GSVERF", "IDOCTP": "GSVERF01", "RCVPOR": "SAPQM", "SNDPOR": "SAP1000", "desc": "GR verification to QM system"},
        {"RCVPRN": "GSVERF_ARBA", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "GSVERF", "IDOCTP": "GSVERF01", "RCVPOR": "SAPARBA", "SNDPOR": "SAP1000", "desc": "GR verification to Ariba"},

        # =====================================================================
        # DELFOR / DELFOR02 — Delivery Forecast
        # =====================================================================
        {"RCVPRN": "DELFOR_VND1", "SNDPRN": "BIS1000", "RCVPRT": "LI", "SNDPRT": "LS", "MESTYP": "DELFOR", "IDOCTP": "DELFOR02", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Delivery forecast to Tata Steel"},
        {"RCVPRN": "DELFOR_VND2", "SNDPRN": "BIS1000", "RCVPRT": "LI", "SNDPRT": "LS", "MESTYP": "DELFOR", "IDOCTP": "DELFOR02", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Delivery forecast to JSW Steel"},
        {"RCVPRN": "DELFOR_APO", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "DELFOR", "IDOCTP": "DELFOR02", "RCVPOR": "SAPAPO", "SNDPOR": "SAP1000", "desc": "Delivery forecast to APO"},

        # =====================================================================
        # DELVRY / DELVRY03 — Delivery
        # =====================================================================
        {"RCVPRN": "DELVRY_WMS", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "DELVRY", "IDOCTP": "DELVRY03", "RCVPOR": "SAPWMS", "SNDPOR": "SAP1000", "desc": "Delivery to WMS"},
        {"RCVPRN": "DELVRY_EWM", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "DELVRY", "IDOCTP": "DELVRY03", "RCVPOR": "SAPEWM", "SNDPOR": "SAP1000", "desc": "Delivery to EWM"},
        {"RCVPRN": "DELVRY_3PL", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "DELVRY", "IDOCTP": "DELVRY03", "RCVPOR": "SAP3PL", "SNDPOR": "SAP1000", "desc": "Delivery to 3PL provider"},
        {"RCVPRN": "DELVRY_TMS", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "DELVRY", "IDOCTP": "DELVRY03", "RCVPOR": "SAPTMS", "SNDPOR": "SAP1000", "desc": "Delivery to TM system"},
        {"RCVPRN": "DELVRY_CUS1", "SNDPRN": "BIS1000", "RCVPRT": "KU", "SNDPRT": "LS", "MESTYP": "DELVRY", "IDOCTP": "DELVRY03", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Delivery to Reliance EDI"},

        # =====================================================================
        # SBWAPB — Appraisal (Performance Management)
        # =====================================================================
        {"RCVPRN": "SBWAPB_SF", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "SBWAPB", "IDOCTP": "SBWAPB01", "RCVPOR": "SAPSFPM", "SNDPOR": "SAP1000", "desc": "Appraisal to SuccessFactors PM"},
        {"RCVPRN": "SBWAPB_BW", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "SBWAPB", "IDOCTP": "SBWAPB01", "RCVPOR": "SAPBW", "SNDPOR": "SAP1000", "desc": "Appraisal data to BW analytics"},

        # =====================================================================
        # BLAREL — Bank Statement Relay
        # =====================================================================
        {"RCVPRN": "BLAREL_HDFC", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "BLAREL", "IDOCTP": "BLAREL01", "RCVPOR": "SAPHDFC", "SNDPOR": "SAP1000", "desc": "Bank statement relay HDFC"},
        {"RCVPRN": "BLAREL_SBI", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "BLAREL", "IDOCTP": "BLAREL01", "RCVPOR": "SAPSBI", "SNDPOR": "SAP1000", "desc": "Bank statement relay SBI"},
        {"RCVPRN": "BLAREL_ICICI", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "BLAREL", "IDOCTP": "BLAREL01", "RCVPOR": "SAPICICI", "SNDPOR": "SAP1000", "desc": "Bank statement relay ICICI"},

        # =====================================================================
        # TXTRAW — Additional Text Distribution
        # =====================================================================
        {"RCVPRN": "TXTRAW_CRM", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "TXTRAW", "IDOCTP": "TXTRAW01", "RCVPOR": "SAPCRM", "SNDPOR": "SAP1000", "desc": "Long text distribution to CRM"},
        {"RCVPRN": "TXTRAW_SUB", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "TXTRAW", "IDOCTP": "TXTRAW01", "RCVPOR": "SAPSUB", "SNDPOR": "SAP1000", "desc": "Long text distribution to subsidiary"},

        # =====================================================================
        # COND_A — Additional Conditions / Pricing
        # =====================================================================
        {"RCVPRN": "COND_A_CRM", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "COND_A", "IDOCTP": "COND_A06", "RCVPOR": "SAPCRM", "SNDPOR": "SAP1000", "desc": "Pricing conditions to CRM"},
        {"RCVPRN": "COND_A_BW", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "COND_A", "IDOCTP": "COND_A06", "RCVPOR": "SAPBW", "SNDPOR": "SAP1000", "desc": "Pricing conditions to BW"},
        {"RCVPRN": "COND_A_APO", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "COND_A", "IDOCTP": "COND_A06", "RCVPOR": "SAPAPO", "SNDPOR": "SAP1000", "desc": "Pricing conditions to APO"},

        # =====================================================================
        # PRICAT / PRICAT05 — Price Catalog
        # =====================================================================
        {"RCVPRN": "PRICAT_CUST1", "SNDPRN": "BIS1000", "RCVPRT": "KU", "SNDPRT": "LS", "MESTYP": "PRICAT", "IDOCTP": "PRICAT05", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Price catalog to Reliance"},
        {"RCVPRN": "PRICAT_CUST2", "SNDPRN": "BIS1000", "RCVPRT": "KU", "SNDPRT": "LS", "MESTYP": "PRICAT", "IDOCTP": "PRICAT05", "RCVPOR": "SAPEDI", "SNDPOR": "SAP1000", "desc": "Price catalog to Mahindra"},
        {"RCVPRN": "PRICAT_DIST", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "PRICAT", "IDOCTP": "PRICAT05", "RCVPOR": "SAPSUB", "SNDPOR": "SAP1000", "desc": "Price catalog to distribution subsidiary"},

        # =====================================================================
        # PROACT — Process Notification
        # =====================================================================
        {"RCVPRN": "PROACT_MES", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "PROACT", "IDOCTP": "PROACT01", "RCVPOR": "SAPMES", "SNDPOR": "SAP1000", "desc": "Process notification to MES"},
        {"RCVPRN": "PROACT_SCADA", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "PROACT", "IDOCTP": "PROACT01", "RCVPOR": "SAPSCDA", "SNDPOR": "SAP1000", "desc": "Process notification to SCADA"},

        # =====================================================================
        # SYIDOC — System IDoc (Technical / Monitoring)
        # =====================================================================
        {"RCVPRN": "SYIDOC_MON", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "SYIDOC", "IDOCTP": "SYIDOC01", "RCVPOR": "SAPSOLM", "SNDPOR": "SAP1000", "desc": "System IDoc monitoring to SolMan"},
        {"RCVPRN": "SYIDOC_BW", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "SYIDOC", "IDOCTP": "SYIDOC01", "RCVPOR": "SAPBW", "SNDPOR": "SAP1000", "desc": "System IDoc to BW analytics"},

        # =====================================================================
        # WMMBID — Warehouse Management (Goods Movement)
        # =====================================================================
        {"RCVPRN": "WMMBID_EWM", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "WMMBID", "IDOCTP": "WMMBID02", "RCVPOR": "SAPEWM", "SNDPOR": "SAP1000", "desc": "WM goods movement to EWM"},
        {"RCVPRN": "WMMBID_3PL", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "WMMBID", "IDOCTP": "WMMBID02", "RCVPOR": "SAP3PL", "SNDPOR": "SAP1000", "desc": "WM goods movement to 3PL"},

        # =====================================================================
        # LOIPRO — Production Order (PP)
        # =====================================================================
        {"RCVPRN": "LOIPRO_MES", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "LOIPRO", "IDOCTP": "LOIPRO02", "RCVPOR": "SAPMES", "SNDPOR": "SAP1000", "desc": "Production order to MES system"},
        {"RCVPRN": "LOIPRO_APS", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "LOIPRO", "IDOCTP": "LOIPRO02", "RCVPOR": "SAPAPS", "SNDPOR": "SAP1000", "desc": "Production order to APS planning"},

        # =====================================================================
        # LOIROU — Routing (PP Master Data)
        # =====================================================================
        {"RCVPRN": "LOIROU_MES", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "LOIROU", "IDOCTP": "LOIROU01", "RCVPOR": "SAPMES", "SNDPOR": "SAP1000", "desc": "Routing master to MES"},

        # =====================================================================
        # GSVERF — Goods Movement (Inventory Management)
        # =====================================================================
        {"RCVPRN": "GSVERF_WMS", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "GSVERF", "IDOCTP": "GSVERF03", "RCVPOR": "SAPWMS", "SNDPOR": "SAP1000", "desc": "Goods movement verification to WMS"},

        # =====================================================================
        # BLAORD — Blanket Purchase Order / Scheduling Agreement
        # =====================================================================
        {"RCVPRN": "BLAORD_SRM", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "BLAORD", "IDOCTP": "BLAORD05", "RCVPOR": "SAPSRM", "SNDPOR": "SAP1000", "desc": "Blanket order to SRM"},
        {"RCVPRN": "BLAORD_ARIBA", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "BLAORD", "IDOCTP": "BLAORD05", "RCVPOR": "ARIBA", "SNDPOR": "SAP1000", "desc": "Blanket order to Ariba Network"},

        # =====================================================================
        # COND_A — Conditions (Pricing / SD)
        # =====================================================================
        {"RCVPRN": "COND_A_TPM", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "COND_A", "IDOCTP": "COND_A07", "RCVPOR": "SAPTPM", "SNDPOR": "SAP1000", "desc": "Pricing conditions to Trade Promotion"},
        {"RCVPRN": "COND_A_PO", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "COND_A", "IDOCTP": "COND_A07", "RCVPOR": "SAPPO", "SNDPOR": "SAP1000", "desc": "Pricing conditions to PO system"},

        # =====================================================================
        # SHPMNT — Shipment (Transportation)
        # =====================================================================
        {"RCVPRN": "SHPMNT_TMS", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "SHPMNT", "IDOCTP": "SHPMNT06", "RCVPOR": "SAPTMS", "SNDPOR": "SAP1000", "desc": "Shipment to transportation management"},
        {"RCVPRN": "SHPMNT_CARRIER", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "SHPMNT", "IDOCTP": "SHPMNT06", "RCVPOR": "CARRIER", "SNDPOR": "SAP1000", "desc": "Shipment to carrier portal"},

        # =====================================================================
        # QALITY — Quality Notification (QM)
        # =====================================================================
        {"RCVPRN": "QALITY_LIMS", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "QALITY", "IDOCTP": "QALITY03", "RCVPOR": "SAPLIMS", "SNDPOR": "SAP1000", "desc": "Quality notification to LIMS"},
        {"RCVPRN": "QALITY_QMS", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "QALITY", "IDOCTP": "QALITY03", "RCVPOR": "SAPQMS", "SNDPOR": "SAP1000", "desc": "Quality notification to QMS"},

        # =====================================================================
        # SERVAC — Service Entry Sheet (MM-SRV)
        # =====================================================================
        {"RCVPRN": "SERVAC_FM", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "SERVAC", "IDOCTP": "SERVAC03", "RCVPOR": "SAPFM", "SNDPOR": "SAP1000", "desc": "Service entry to Fieldglass/FSM"},

        # =====================================================================
        # HRMD_A — HR Master Data (PA/OM)
        # =====================================================================
        {"RCVPRN": "HRMD_A_SF", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "HRMD_A", "IDOCTP": "HRMD_A07", "RCVPOR": "SAPSF", "SNDPOR": "SAP1000", "desc": "HR master data to SuccessFactors"},
        {"RCVPRN": "HRMD_A_BW", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "HRMD_A", "IDOCTP": "HRMD_A07", "RCVPOR": "SAPBW", "SNDPOR": "SAP1000", "desc": "HR master data to BW analytics"},

        # =====================================================================
        # FINSTA — Financial Statement (FI external)
        # =====================================================================
        {"RCVPRN": "FINSTA_BANK", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "FINSTA", "IDOCTP": "FINSTA01", "RCVPOR": "BANK01", "SNDPOR": "SAP1000", "desc": "Bank statement to external bank"},

        # =====================================================================
        # COELEM — Cost Element Master (CO)
        # =====================================================================
        {"RCVPRN": "COELEM_BPC", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "COELEM", "IDOCTP": "COELEM03", "RCVPOR": "SAPBPC", "SNDPOR": "SAP1000", "desc": "Cost element master to BPC consolidation"},

        # =====================================================================
        # PEXR2 — Payment Advice (FI)
        # =====================================================================
        {"RCVPRN": "PEXR2_BANK", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "PEXR2", "IDOCTP": "PEXR2002", "RCVPOR": "BANK01", "SNDPOR": "SAP1000", "desc": "Payment advice to house bank"},
        {"RCVPRN": "PEXR2_VENDOR", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "PEXR2", "IDOCTP": "PEXR2002", "RCVPOR": "VENDOR", "SNDPOR": "SAP1000", "desc": "Payment advice to vendor portal"},

        # =====================================================================
        # WMTOID — Transfer Order (WM)
        # =====================================================================
        {"RCVPRN": "WMTOID_3PL", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "WMTOID", "IDOCTP": "WMTOID02", "RCVPOR": "SAP3PL", "SNDPOR": "SAP1000", "desc": "Transfer order to 3PL warehouse"},

        # =====================================================================
        # CNPMAS — Functional Location (PM)
        # =====================================================================
        {"RCVPRN": "CNPMAS_EAM", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "CNPMAS", "IDOCTP": "CNPMAS02", "RCVPOR": "SAPEAM", "SNDPOR": "SAP1000", "desc": "Functional location to external EAM"},

        # =====================================================================
        # BLAREL — Billing Relationship (SD)
        # =====================================================================
        {"RCVPRN": "BLAREL_CRM", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "BLAREL", "IDOCTP": "BLAREL01", "RCVPOR": "SAPCRM", "SNDPOR": "SAP1000", "desc": "Billing relationship to CRM"},

        # =====================================================================
        # ACC_DOCUMENT — Accounting Document (FI-GL)
        # =====================================================================
        {"RCVPRN": "ACC_DOC_TAX", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "ACC_DOCUMENT", "IDOCTP": "ACC_DOCUMENT04", "RCVPOR": "TAXENG", "SNDPOR": "SAP1000", "desc": "Accounting document to tax engine"},
        {"RCVPRN": "ACC_DOC_GR", "SNDPRN": "BIS1000", "RCVPRT": "LS", "SNDPRT": "LS", "MESTYP": "ACC_DOCUMENT", "IDOCTP": "ACC_DOCUMENT04", "RCVPOR": "SAPGR", "SNDPOR": "SAP1000", "desc": "Accounting document to Group Reporting"},
    ]


# =============================================================================
# FINANCE DATA — GL Documents (BKPF + BSEG)
# =============================================================================
def generate_finance_documents(count=5000):
    bkpf = []
    bseg = []

    doc_types = ["SA", "KR", "KZ", "DR", "DZ", "AB", "RE"]

    for i in range(1, count + 1):
        bukrs = random.choice(["1000", "1100", "1200", "2000"])
        belnr = f"{i:010d}"
        gjahr = random.choice(["2023", "2024"])
        blart = random.choice(doc_types)
        waers = "INR" if bukrs != "2000" else "AED"
        budat = random_date(2023, 2024)
        monat = str(int(budat[4:6])).zfill(2)

        bkpf.append({
            "BUKRS": bukrs, "BELNR": belnr, "GJAHR": gjahr,
            "BLDAT": budat, "BUDAT": budat, "MONAT": monat,
            "BLART": blart, "WAERS": waers, "BSTAT": "",
        })

        # Each document has 2-6 line items
        num_lines = random.randint(2, 6)
        total_debit = 0

        for line in range(1, num_lines + 1):
            amount = round(random.uniform(1000, 5000000), 2)
            is_debit = line <= num_lines // 2

            if is_debit:
                total_debit += amount
                shkzg = "S"
            else:
                shkzg = "H"
                amount = total_debit / (num_lines - num_lines // 2) if line == num_lines else amount

            bseg.append({
                "BUKRS": bukrs, "BELNR": belnr, "GJAHR": gjahr,
                "BUZEI": f"{line:03d}",
                "KOART": random.choice(["S", "K", "D", "A"]),
                "HKONT": f"{random.randint(100000, 999999):06d}",
                "DMBTR": f"{abs(amount):.2f}",
                "WRBTR": f"{abs(amount):.2f}",
                "SHKZG": shkzg,
                "KOSTL": f"{random.randint(1000, 9999):04d}" if random.random() > 0.3 else "",
                "PRCTR": f"{random.randint(1000, 9999):04d}" if random.random() > 0.4 else "",
            })

    return bkpf, bseg


# =============================================================================
# MASTER GENERATOR — Produces complete mock ECC dataset
# =============================================================================
def generate_complete_ecc_dataset():
    """Generate the complete mock ECC system data."""

    print("Generating mock SAP ECC data for 'Bharat Industrial Solutions Pvt Ltd'...")

    data = {}

    print("  -> Custom ABAP programs...")
    data["programs"] = generate_programs()
    print(f"    {len(data['programs'])} programs generated")

    print("  -> Custom tables...")
    data["tables"] = generate_tables()
    print(f"    {len(data['tables'])} tables generated")

    print("  -> Function modules...")
    data["function_modules"] = generate_function_modules()
    print(f"    {len(data['function_modules'])} function modules generated")

    print("  -> Org structure...")
    data["org_structure"] = {
        "company_codes": COMPANY_CODES,
        "plants": PLANTS,
        "storage_locations": STORAGE_LOCATIONS,
        "sales_orgs": SALES_ORGS,
        "controlling_areas": CONTROLLING_AREAS,
        "purchasing_orgs": PURCHASING_ORGS,
    }
    print(f"    {len(COMPANY_CODES)} company codes, {len(PLANTS)} plants, {len(SALES_ORGS)} sales orgs")

    print("  -> User roles...")
    data["roles"] = {
        "roles": generate_roles(),
        "total_users": 1847,
        "role_count": 342,
    }
    print(f"    {len(data['roles']['roles'])} roles generated")

    print("  -> Integration points...")
    data["integrations"] = {
        "rfc_destinations": generate_rfc_destinations(),
        "idoc_partners": generate_idoc_partners(),
    }
    print(f"    {len(data['integrations']['rfc_destinations'])} RFC, {len(data['integrations']['idoc_partners'])} IDoc partners")

    print("  -> Customers (KNA1)...")
    data["customers"] = generate_customers()
    print(f"    {len(data['customers'])} customers generated")

    print("  -> Vendors (LFA1)...")
    data["vendors"] = generate_vendors()
    print(f"    {len(data['vendors'])} vendors generated")

    print("  -> Finance documents (BKPF/BSEG)...")
    bkpf, bseg = generate_finance_documents(5000)
    data["finance"] = {"bkpf": bkpf, "bseg": bseg}
    print(f"    {len(bkpf)} documents, {len(bseg)} line items")

    print("  -> Sample ABAP source code...")
    try:
        from extended_abap_programs import EXTENDED_ABAP_PROGRAMS
        data["abap_source"] = {**SAMPLE_ABAP_PROGRAMS, **EXTENDED_ABAP_PROGRAMS}
    except ImportError:
        data["abap_source"] = SAMPLE_ABAP_PROGRAMS
    print(f"    {len(data['abap_source'])} programs with source code")

    # Summary
    data["system_info"] = {
        "sid": "BIS",
        "description": "Bharat Industrial Solutions Pvt Ltd — SAP ECC 6.0 EHP8",
        "database": "Oracle 19c",
        "os": "Red Hat Enterprise Linux 8.6",
        "kernel": "SAP Kernel 7.53",
        "unicode": True,
        "client": "100",
        "total_custom_programs": len(data["programs"]),
        "total_custom_tables": len(data["tables"]),
        "total_function_modules": len(data["function_modules"]),
        "total_customers": len(data["customers"]),
        "total_vendors": len(data["vendors"]),
        "total_roles": len(data["roles"]["roles"]),
        "total_users": 1847,
        "data_volume_gb": 2800,
        "generated_at": datetime.now().isoformat(),
    }

    print("\n✅ Complete ECC dataset generated!")
    print(f"   System: {data['system_info']['description']}")
    print(f"   Programs: {data['system_info']['total_custom_programs']}")
    print(f"   Tables: {data['system_info']['total_custom_tables']}")
    print(f"   Customers: {data['system_info']['total_customers']}")
    print(f"   Vendors: {data['system_info']['total_vendors']}")

    return data


# =============================================================================
# RFC SIMULATOR — Drop-in replacement for pyrfc.Connection
# =============================================================================
class MockRFCConnection:
    """
    Drop-in replacement for pyrfc.Connection that returns mock data.

    Usage:
        conn = MockRFCConnection()
        result = conn.call("RFC_READ_TABLE", QUERY_TABLE="TRDIR", ...)

    This simulates exactly what a real RFC connection returns,
    so our Lambda code works identically with mock or real data.
    """

    def __init__(self, dataset=None):
        self.dataset = dataset or generate_complete_ecc_dataset()
        self._call_count = 0
        # Execution tracking — records what would be written to S/4HANA
        self._deployed_programs = {}
        self._activated_programs = set()
        self._transport_requests = []
        self._loaded_finance_docs = []
        self._loaded_bps = []
        self._loaded_material_docs = []
        self._created_roles = []
        self._rfc_destinations = []
        self._idoc_partners = []
        self._config_applied = []
        self._committed = 0

    def call(self, function_name, **kwargs):
        self._call_count += 1

        # --- READ operations (existing) ---
        if function_name == "RFC_READ_TABLE":
            return self._handle_read_table(**kwargs)
        elif function_name == "RPY_PROGRAM_READ":
            return self._handle_read_program(**kwargs)

        # --- WRITE operations (execution stages) ---

        # Transport management
        elif function_name == "BAPI_CTREQUEST_CREATE":
            return self._handle_transport_create(**kwargs)
        elif function_name == "BAPI_CTREQUEST_RELEASE":
            return self._handle_transport_release(**kwargs)

        # Code deployment
        elif function_name == "RPY_PROGRAM_UPDATE":
            return self._handle_program_update(**kwargs)
        elif function_name == "RPY_PROGRAM_INSERT":
            return self._handle_program_insert(**kwargs)
        elif function_name == "RS_WORKING_OBJECTS_ACTIVATE":
            return self._handle_activate(**kwargs)
        elif function_name == "RS_SYNTAX_CHECK":
            return self._handle_syntax_check(**kwargs)

        # Finance data loading
        elif function_name == "BAPI_ACC_DOCUMENT_POST":
            return self._handle_acc_doc_post(**kwargs)

        # Business Partner
        elif function_name == "BAPI_BUPA_CREATE_FROM_DATA":
            return self._handle_bp_create(**kwargs)
        elif function_name == "BAPI_BUPA_ROLE_ADD_2":
            return {"RETURN": []}
        elif function_name == "BAPI_BUPA_GROUPING_CREATE":
            self._config_applied.append({"type": "bp_grouping", **kwargs})
            return {"RETURN": []}

        # Material documents
        elif function_name == "BAPI_GOODSMVT_CREATE":
            return self._handle_goods_movement(**kwargs)

        # Commit
        elif function_name == "BAPI_TRANSACTION_COMMIT":
            self._committed += 1
            return {"RETURN": []}

        # Config
        elif function_name == "NUMBER_RANGE_INTERVAL_CREATE":
            self._config_applied.append({"type": "number_range", **kwargs})
            return {"RETURN": []}
        elif function_name == "NUMBER_RANGE_INTERVAL_READ":
            return {"INTERVALS": [{"NRRANGENR": "01", "FROMNUMBER": "0000000001", "TONUMBER": "9999999999"}]}
        elif function_name == "BAPI_GLACCOUNT_EXISTENCECHECK":
            return {"RETURN": []}

        # Role provisioning
        elif function_name == "PRGN_RFC_ROLE_CREATE":
            return self._handle_role_create(**kwargs)
        elif function_name in ("PRGN_RFC_ROLE_MENU_ADD", "PRGN_RFC_ROLE_CATALOG_ADD",
                                "PRGN_RFC_ROLE_PROFILE_GEN", "PRGN_RFC_COMPOSITE_ADD"):
            return {"RETURN": []}
        elif function_name == "PRGN_RFC_ROLE_READ":
            role_name = kwargs.get("ROLE_NAME", "")
            if any(r.get("ROLE_NAME") == role_name for r in self._created_roles):
                return {"ROLE_NAME": role_name, "ROLE_TEXT": "Migrated Role"}
            return {"RETURN": [{"TYPE": "E", "MESSAGE": "Role not found"}]}
        elif function_name == "BAPI_USER_ACTGROUPS_ASSIGN":
            return {"RETURN": []}

        # Integration
        elif function_name == "RFC_MODIFY_R3_DESTINATION":
            self._rfc_destinations.append(kwargs)
            return {"RETURN": []}
        elif function_name == "RFC_PING":
            return {"RETURN": []}
        elif function_name in ("IDOC_PORT_CREATE", "EDI_PARTNER_CREATE", "EDI_PARTNER_ADD_MSGTYPE"):
            self._idoc_partners.append(kwargs)
            return {"RETURN": []}

        # India-specific
        elif function_name in ("J_1IG_GSTIN_CREATE", "J_1IEWT_SETUP", "J_1IG_EINV_CONFIG"):
            self._config_applied.append({"type": "india_" + function_name, **kwargs})
            return {"RETURN": []}

        # Fiori config
        elif function_name == "Z_FIORI_SPACE_CREATE":
            self._config_applied.append({"type": "fiori_space", **kwargs})
            return {"RETURN": []}

        # Custom table insert
        elif function_name == "Z_MIGRATE4HANA_TABLE_INSERT":
            return {"RETURN": []}

        # Catch-all
        else:
            return {"ET_RETURN": []}

    # --- Execution mock handlers ---

    def _handle_transport_create(self, **kwargs):
        tr_id = f"S4HK{900001 + len(self._transport_requests):06d}"
        self._transport_requests.append({"id": tr_id, **kwargs})
        return {"REQUESTID": tr_id, "RETURN": []}

    def _handle_transport_release(self, **kwargs):
        return {"RETURN": []}

    def _handle_program_update(self, **kwargs):
        name = kwargs.get("PROGRAM_NAME", "")
        source = kwargs.get("PROG_SOURCE", [])
        self._deployed_programs[name] = source
        return {"RETURN": []}

    def _handle_program_insert(self, **kwargs):
        name = kwargs.get("PROGRAM_NAME", "")
        source = kwargs.get("PROG_SOURCE", [])
        self._deployed_programs[name] = source
        return {"RETURN": []}

    def _handle_activate(self, **kwargs):
        objects = kwargs.get("OBJECTS", [])
        for obj in objects:
            self._activated_programs.add(obj.get("OBJ_NAME", ""))
        return {"MESSAGES": []}

    def _handle_syntax_check(self, **kwargs):
        prog = kwargs.get("PROGRAM", "")
        # Simulate: all migrated programs pass syntax check
        return {"MESSAGES": []}

    def _handle_acc_doc_post(self, **kwargs):
        doc_header = kwargs.get("DOCUMENTHEADER", {})
        self._loaded_finance_docs.append(doc_header)
        doc_nr = str(5100000000 + len(self._loaded_finance_docs))
        return {"OBJ_KEY": doc_nr, "RETURN": [{"TYPE": "S", "MESSAGE": f"Document {doc_nr} posted"}]}

    def _handle_bp_create(self, **kwargs):
        bp_nr = str(1000000 + len(self._loaded_bps)).zfill(10)
        self._loaded_bps.append({"PARTNER": bp_nr, **kwargs})
        return {"BUSINESSPARTNER": bp_nr, "RETURN": [{"TYPE": "S", "MESSAGE": f"BP {bp_nr} created"}]}

    def _handle_goods_movement(self, **kwargs):
        doc_nr = str(4900000000 + len(self._loaded_material_docs))
        self._loaded_material_docs.append(kwargs)
        return {"MATERIALDOCUMENT": doc_nr, "MATDOCUMENTYEAR": "2024",
                "RETURN": [{"TYPE": "S", "MESSAGE": f"Material doc {doc_nr} created"}]}

    def _handle_role_create(self, **kwargs):
        self._created_roles.append(kwargs)
        return {"RETURN": []}

    def _handle_read_table(self, QUERY_TABLE="", FIELDS=None, OPTIONS=None,
                            DELIMITER="|", ROWCOUNT=0, ROWSKIPS=0, **kwargs):
        """Simulate RFC_READ_TABLE — the most-used RFC in our tool."""

        field_names = [f["FIELDNAME"] for f in (FIELDS or [])] if FIELDS else None
        table = QUERY_TABLE.upper()

        # Route to correct mock data
        rows = self._get_table_data(table, field_names, OPTIONS)

        # Apply pagination
        if ROWSKIPS:
            rows = rows[ROWSKIPS:]
        if ROWCOUNT and ROWCOUNT > 0:
            rows = rows[:ROWCOUNT]

        # Format like real RFC_READ_TABLE response
        if not field_names and rows:
            field_names = list(rows[0].keys())

        result_fields = [{"FIELDNAME": f, "LENGTH": "40", "TYPE": "C"} for f in (field_names or [])]
        result_data = []

        for row in rows:
            wa = DELIMITER.join(str(row.get(f, "")).ljust(40)[:40] for f in (field_names or []))
            result_data.append({"WA": wa})

        return {"FIELDS": result_fields, "DATA": result_data}

    def _get_table_data(self, table, fields, options):
        """Route table name to mock data."""

        option_text = " ".join(o.get("TEXT", "") for o in (options or []))

        if table == "TRDIR":
            data = self.dataset.get("programs", [])
            if "Z%" in option_text or "Y%" in option_text:
                return data
            return data

        elif table == "DD02L":
            return self.dataset.get("tables", [])

        elif table == "TFDIR":
            data = self.dataset.get("function_modules", [])
            if "BAPI%" in option_text:
                return [d for d in data if "BAPI" in d.get("FUNCNAME", "")]
            return data

        elif table == "T001":
            return self.dataset["org_structure"]["company_codes"]
        elif table == "T001W":
            return self.dataset["org_structure"]["plants"]
        elif table == "T001L":
            return self.dataset["org_structure"]["storage_locations"]
        elif table == "TVKO":
            return self.dataset["org_structure"]["sales_orgs"]
        elif table == "TKA01":
            return self.dataset["org_structure"]["controlling_areas"]
        elif table == "T024E":
            return self.dataset["org_structure"]["purchasing_orgs"]

        elif table == "AGR_DEFINE":
            return self.dataset["roles"]["roles"]
        elif table == "AGR_USERS":
            # Generate user assignments from roles
            assignments = []
            for role in self.dataset["roles"]["roles"]:
                for _ in range(role.get("user_count", 0)):
                    assignments.append({
                        "AGR_NAME": role["AGR_NAME"],
                        "UNAME": random_user(),
                        "FROM_DAT": "20200101",
                        "TO_DAT": "99991231",
                    })
            return assignments
        elif table == "AGR_1251":
            return []  # Auth details - simplified

        elif table == "RFCDES":
            return self.dataset["integrations"]["rfc_destinations"]
        elif table == "EDPP1":
            return self.dataset["integrations"]["idoc_partners"]

        elif table == "KNA1":
            return self.dataset.get("customers", [])
        elif table == "LFA1":
            return self.dataset.get("vendors", [])

        elif table == "BKPF":
            return self.dataset["finance"]["bkpf"]
        elif table in ("BSEG", "BSIK", "BSID", "BSAD", "BSAK"):
            return self.dataset["finance"]["bseg"]

        # Config tables
        elif table in ("T004", "T009", "T003", "T030", "BNKA", "TKA02",
                       "CSKS", "CEPC", "T024", "T134", "TVTW", "TSPA",
                       "TVKWZ", "NRIV"):
            return []  # Empty but valid

        else:
            return []

    def _handle_read_program(self, PROGRAM_NAME="", **kwargs):
        """Simulate RPY_PROGRAM_READ."""
        source = self.dataset.get("abap_source", {}).get(PROGRAM_NAME, "")
        if source:
            lines = [{"LINE": line} for line in source.split("\n")]
            return {"PROG_SOURCE": lines, "RETURN": []}
        return {
            "PROG_SOURCE": [],
            "RETURN": [{"TYPE": "E", "MESSAGE": f"Program {PROGRAM_NAME} not found"}],
        }

    def close(self):
        pass


# =============================================================================
# MAIN — Generate and save dataset
# =============================================================================
if __name__ == "__main__":
    dataset = generate_complete_ecc_dataset()

    output_dir = os.path.dirname(os.path.abspath(__file__))
    output_file = os.path.join(output_dir, "ecc_dataset.json")

    # Save full dataset (excluding large transaction data for file size)
    save_data = {
        "system_info": dataset["system_info"],
        "programs": dataset["programs"][:50],  # Sample
        "tables": dataset["tables"],
        "function_modules": dataset["function_modules"][:50],
        "org_structure": dataset["org_structure"],
        "roles": {"roles": dataset["roles"]["roles"][:50], "total_users": 1847, "role_count": 342},
        "integrations": dataset["integrations"],
        "abap_source": dataset["abap_source"],
        "customers": dataset["customers"][:20],
        "vendors": dataset["vendors"][:20],
    }

    with open(output_file, "w") as f:
        json.dump(save_data, f, indent=2, default=str)

    print(f"\n📦 Dataset saved to: {output_file}")
    print(f"   File size: {os.path.getsize(output_file) / 1024:.0f} KB")
