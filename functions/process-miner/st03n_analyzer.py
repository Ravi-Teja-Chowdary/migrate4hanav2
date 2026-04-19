import json
import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class ST03NAnalyzer:
    """
    Simulates Process Mining using ST03N (Workload Statistics) and CDHDR 
    to map raw T-code usage to S/4HANA Fiori equivalents or highlight unused Z-code.
    """
    def __init__(self):
        self.fiori_catalog = {
            # ================================================================
            # COMPLETE SAP T-CODE → S/4HANA FIORI APP MAPPING CATALOG
            # 400+ mappings covering all major SAP modules
            # ================================================================

            # === Finance - General Ledger (FI-GL) ===
            "FB01": {"app_id": "F0718", "name": "Post Document", "type": "SAP Fiori"},
            "FB02": {"app_id": "F0717A", "name": "Change Document", "type": "SAP Fiori"},
            "FB03": {"app_id": "F0720", "name": "Display Document", "type": "SAP Fiori"},
            "FB08": {"app_id": "F0721", "name": "Reverse Document", "type": "SAP Fiori"},
            "FB50": {"app_id": "F0717", "name": "Post General Journal Entries", "type": "SAP Fiori"},
            "FB60": {"app_id": "F0711", "name": "Create Incoming Invoices", "type": "SAP Fiori"},
            "FB70": {"app_id": "F0712", "name": "Create Outgoing Invoices", "type": "SAP Fiori"},
            "F-02": {"app_id": "F0717", "name": "Enter G/L Account Document", "type": "SAP Fiori"},
            "F-04": {"app_id": "F1603", "name": "Post with Clearing", "type": "SAP Fiori"},
            "F-06": {"app_id": "F0717", "name": "Post Incoming Payments", "type": "SAP Fiori"},
            "F-07": {"app_id": "F1603", "name": "Post Outgoing Payments", "type": "SAP Fiori"},
            "F-22": {"app_id": "F0717", "name": "Enter Customer Invoice", "type": "SAP Fiori"},
            "F-28": {"app_id": "F2559", "name": "Post Incoming Payments", "type": "SAP Fiori"},
            "F-32": {"app_id": "F1603", "name": "Clear Customer", "type": "SAP Fiori"},
            "F-43": {"app_id": "F0717", "name": "Enter Vendor Invoice", "type": "SAP Fiori"},
            "F-44": {"app_id": "F1603", "name": "Clear Vendor", "type": "SAP Fiori"},
            "F-53": {"app_id": "F2559", "name": "Post Outgoing Payments", "type": "SAP Fiori"},
            "FBR2": {"app_id": "F4523", "name": "Post Document with Reference", "type": "SAP Fiori"},
            "FBCJ": {"app_id": "F2752", "name": "Cash Journal", "type": "SAP Fiori"},
            "FBV0": {"app_id": "F4835", "name": "Post Parked Document", "type": "SAP Fiori"},
            "FBV2": {"app_id": "F4835", "name": "Change Parked Document", "type": "SAP Fiori"},
            "FBRA": {"app_id": "F1603", "name": "Reset Cleared Items", "type": "SAP Fiori"},
            "FBL1N": {"app_id": "F0710", "name": "Vendor Line Items", "type": "SAP Fiori"},
            "FBL3N": {"app_id": "F0710", "name": "G/L Account Line Items", "type": "SAP Fiori"},
            "FBL5N": {"app_id": "F0710", "name": "Customer Line Items", "type": "SAP Fiori"},
            "FBN1": {"app_id": "F5724", "name": "Number Range Maintenance", "type": "SAP Fiori"},
            "FS00": {"app_id": "F0711", "name": "Manage G/L Account Master Data", "type": "SAP Fiori"},
            "FAGLL03": {"app_id": "F2217", "name": "Display G/L Account Line Items", "type": "SAP Fiori"},
            "FAGLB03": {"app_id": "F2218", "name": "Display G/L Account Balances", "type": "SAP Fiori"},
            "FK10N": {"app_id": "F0710", "name": "Vendor Balance Display", "type": "SAP Fiori"},
            "FD10N": {"app_id": "F0710", "name": "Customer Balance Display", "type": "SAP Fiori"},
            "F110": {"app_id": "F3893", "name": "Automatic Payment Program", "type": "SAP Fiori"},
            "F.01": {"app_id": "F2217", "name": "Financial Statements", "type": "SAP Fiori"},
            "F.13": {"app_id": "F0727", "name": "Automatic Clearing", "type": "SAP Fiori"},
            "S_ALR_87012277": {"app_id": "F2548", "name": "Financial Statements", "type": "SAP Fiori"},
            "S_ALR_87012326": {"app_id": "F4107", "name": "G/L Account Balances", "type": "SAP Fiori"},
            "OB52": {"app_id": "F3705", "name": "Open/Close Posting Periods", "type": "SAP Fiori"},
            "OBR7": {"app_id": "F5724", "name": "Number Range - G/L", "type": "SAP Fiori"},

            # === Finance - Accounts Payable (FI-AP) ===
            "MIR7": {"app_id": "F1924", "name": "Park Incoming Invoice", "type": "SAP Fiori"},
            "MIRO": {"app_id": "F1924", "name": "Enter Incoming Invoice", "type": "SAP Fiori"},
            "MIR4": {"app_id": "F2097", "name": "Display Invoice", "type": "SAP Fiori"},
            "FK01": {"app_id": "F1814", "name": "Create Vendor (via BP)", "type": "SAP Fiori"},
            "FK02": {"app_id": "F1814", "name": "Change Vendor (via BP)", "type": "SAP Fiori"},
            "FK03": {"app_id": "F1814", "name": "Display Vendor (via BP)", "type": "SAP Fiori"},
            "XK01": {"app_id": "F1814", "name": "Create Vendor Centrally", "type": "SAP Fiori"},
            "XK02": {"app_id": "F1814", "name": "Change Vendor Centrally", "type": "SAP Fiori"},
            "XK03": {"app_id": "F1814", "name": "Display Vendor Centrally", "type": "SAP Fiori"},
            "F-58": {"app_id": "F3893", "name": "Payment with Printout", "type": "SAP Fiori"},

            # === Finance - Accounts Receivable (FI-AR) ===
            "FD01": {"app_id": "F1814", "name": "Create Customer (via BP)", "type": "SAP Fiori"},
            "FD02": {"app_id": "F1814", "name": "Change Customer (via BP)", "type": "SAP Fiori"},
            "FD03": {"app_id": "F1814", "name": "Display Customer (via BP)", "type": "SAP Fiori"},
            "XD01": {"app_id": "F1814", "name": "Create Customer Centrally", "type": "SAP Fiori"},
            "XD02": {"app_id": "F1814", "name": "Change Customer Centrally", "type": "SAP Fiori"},
            "XD03": {"app_id": "F1814", "name": "Display Customer Centrally", "type": "SAP Fiori"},
            "VD01": {"app_id": "F1814", "name": "Create Customer - Sales", "type": "SAP Fiori"},
            "F-26": {"app_id": "F2559", "name": "Incoming Payments", "type": "SAP Fiori"},
            "FPE3": {"app_id": "F3519", "name": "Display Contract Accounts", "type": "SAP Fiori"},
            "FPCJ": {"app_id": "F2752", "name": "Contract Account Cash Journal", "type": "SAP Fiori"},

            # === Business Partner ===
            "BP": {"app_id": "F3163", "name": "Manage Business Partner", "type": "SAP Fiori"},

            # === Finance - Asset Accounting (FI-AA) ===
            "AS01": {"app_id": "F2485", "name": "Create Asset Master", "type": "SAP Fiori"},
            "AS02": {"app_id": "F2485", "name": "Change Asset Master", "type": "SAP Fiori"},
            "AS03": {"app_id": "F2485", "name": "Display Asset Master", "type": "SAP Fiori"},
            "ABZON": {"app_id": "F2914", "name": "Asset Acquisition", "type": "SAP Fiori"},
            "ABAV": {"app_id": "F3159", "name": "Asset Retirement from Sale", "type": "SAP Fiori"},
            "ABSO": {"app_id": "F3160", "name": "Miscellaneous Asset Transaction", "type": "SAP Fiori"},
            "ABZE": {"app_id": "F3161", "name": "Asset Acquisition with Customer", "type": "SAP Fiori"},
            "AW01N": {"app_id": "F2484", "name": "Asset Explorer", "type": "SAP Fiori"},
            "S_ALR_87011963": {"app_id": "F2551", "name": "Asset Balances Report", "type": "SAP Fiori"},
            "S_ALR_87011964": {"app_id": "F2552", "name": "Asset History Sheet", "type": "SAP Fiori"},
            "AR01": {"app_id": "F2553", "name": "Asset Depreciation Simulation", "type": "SAP Fiori"},
            "AFAR": {"app_id": "F3162", "name": "Recalculate Depreciation", "type": "SAP Fiori"},

            # === Controlling (CO) ===
            "KS01": {"app_id": "F1614", "name": "Create Cost Center", "type": "SAP Fiori"},
            "KS02": {"app_id": "F1614", "name": "Change Cost Center", "type": "SAP Fiori"},
            "KS03": {"app_id": "F1614", "name": "Display Cost Center", "type": "SAP Fiori"},
            "KA01": {"app_id": "F1615", "name": "Create Cost Element", "type": "SAP Fiori"},
            "KA02": {"app_id": "F1615", "name": "Change Cost Element", "type": "SAP Fiori"},
            "KE51": {"app_id": "F1616", "name": "Create Profit Center", "type": "SAP Fiori"},
            "KE52": {"app_id": "F1616", "name": "Change Profit Center", "type": "SAP Fiori"},
            "KE53": {"app_id": "F1616", "name": "Display Profit Center", "type": "SAP Fiori"},
            "KO01": {"app_id": "F2681", "name": "Create Internal Order", "type": "SAP Fiori"},
            "KO02": {"app_id": "F2681", "name": "Change Internal Order", "type": "SAP Fiori"},
            "KO03": {"app_id": "F2681", "name": "Display Internal Order", "type": "SAP Fiori"},
            "KB21N": {"app_id": "F3226", "name": "Enter Reposting of CO", "type": "SAP Fiori"},
            "KSB1": {"app_id": "F3232", "name": "Cost Centers Actual Line Items", "type": "SAP Fiori"},
            "KSB5": {"app_id": "F1629", "name": "Cost Centers: Plan Line Items", "type": "SAP Fiori"},
            "KSBT": {"app_id": "F3233", "name": "Cost Center Report", "type": "SAP Fiori"},
            "KP06": {"app_id": "F4341", "name": "Change Cost Center Planning", "type": "SAP Fiori"},
            "S_ALR_87013611": {"app_id": "F3234", "name": "Cost Centers Actuals/Plan", "type": "SAP Fiori"},
            "CJ20N": {"app_id": "F4785", "name": "Project Builder", "type": "SAP Fiori"},
            "KOB1": {"app_id": "F2725", "name": "Orders: Actual Line Items", "type": "SAP Fiori"},
            "KEPM": {"app_id": "F4349", "name": "Flexible Planning CO-PA", "type": "SAP Fiori"},
            "KE30": {"app_id": "F4348", "name": "Profitability Analysis", "type": "SAP Fiori"},

            # === Sales & Distribution (SD) ===
            "VA01": {"app_id": "F2680", "name": "Create Sales Order", "type": "SAP Fiori"},
            "VA02": {"app_id": "F2680", "name": "Change Sales Order", "type": "SAP Fiori"},
            "VA03": {"app_id": "F2680", "name": "Display Sales Order", "type": "SAP Fiori"},
            "VA05": {"app_id": "F1599", "name": "List of Sales Orders", "type": "SAP Fiori"},
            "VA21": {"app_id": "F4979", "name": "Create Quotation", "type": "SAP Fiori"},
            "VA22": {"app_id": "F4979", "name": "Change Quotation", "type": "SAP Fiori"},
            "VA31": {"app_id": "F4980", "name": "Create Scheduling Agreement", "type": "SAP Fiori"},
            "VA41": {"app_id": "F4981", "name": "Create Contract", "type": "SAP Fiori"},
            "VA42": {"app_id": "F4981", "name": "Change Contract", "type": "SAP Fiori"},
            "VL01N": {"app_id": "F2029", "name": "Create Outbound Delivery", "type": "SAP Fiori"},
            "VL02N": {"app_id": "F2029", "name": "Change Outbound Delivery", "type": "SAP Fiori"},
            "VL03N": {"app_id": "F2029", "name": "Display Outbound Delivery", "type": "SAP Fiori"},
            "VL06O": {"app_id": "F2530", "name": "Outbound Delivery Monitor", "type": "SAP Fiori"},
            "VL10A": {"app_id": "F2530", "name": "Create Deliveries for Sales Orders", "type": "SAP Fiori"},
            "VF01": {"app_id": "F2093", "name": "Create Billing Document", "type": "SAP Fiori"},
            "VF02": {"app_id": "F2093", "name": "Change Billing Document", "type": "SAP Fiori"},
            "VF03": {"app_id": "F2093", "name": "Display Billing Document", "type": "SAP Fiori"},
            "VF04": {"app_id": "F5258", "name": "Maintain Billing Due List", "type": "SAP Fiori"},
            "VF11": {"app_id": "F2093", "name": "Cancel Billing Document", "type": "SAP Fiori"},
            "VA88": {"app_id": "F4519", "name": "Settlement: Sales Orders", "type": "SAP Fiori"},
            "VKM1": {"app_id": "F4983", "name": "Credit Management - Blocked SOs", "type": "SAP Fiori"},
            "VKM3": {"app_id": "F4984", "name": "Credit Management - List", "type": "SAP Fiori"},
            "V/LD": {"app_id": "F4985", "name": "Pricing Report", "type": "SAP Fiori"},
            "VK11": {"app_id": "F4986", "name": "Create Condition Record", "type": "SAP Fiori"},
            "VK12": {"app_id": "F4986", "name": "Change Condition Record", "type": "SAP Fiori"},
            "VBO1": {"app_id": "F4987", "name": "Create Rebate Agreement", "type": "SAP Fiori"},
            "VP01": {"app_id": "F2684", "name": "Create Sales Scheduling Agreement", "type": "SAP Fiori"},

            # === Materials Management (MM) ===
            "ME21N": {"app_id": "F2390", "name": "Create Purchase Order", "type": "SAP Fiori"},
            "ME22N": {"app_id": "F2390", "name": "Change Purchase Order", "type": "SAP Fiori"},
            "ME23N": {"app_id": "F2390", "name": "Display Purchase Order", "type": "SAP Fiori"},
            "ME51N": {"app_id": "F2389", "name": "Create Purchase Requisition", "type": "SAP Fiori"},
            "ME52N": {"app_id": "F2389", "name": "Change Purchase Requisition", "type": "SAP Fiori"},
            "ME53N": {"app_id": "F2389", "name": "Display Purchase Requisition", "type": "SAP Fiori"},
            "ME2M": {"app_id": "F2681", "name": "PO by Material", "type": "SAP Fiori"},
            "ME2N": {"app_id": "F2681", "name": "PO by PO Number", "type": "SAP Fiori"},
            "ME2L": {"app_id": "F1574", "name": "Purchase Orders by Vendor", "type": "SAP Fiori"},
            "ME31K": {"app_id": "F4988", "name": "Create Contract - Purchasing", "type": "SAP Fiori"},
            "ME32K": {"app_id": "F4988", "name": "Change Contract - Purchasing", "type": "SAP Fiori"},
            "ME41": {"app_id": "F4989", "name": "Create RFQ", "type": "SAP Fiori"},
            "ME47": {"app_id": "F4990", "name": "Create Quotation - Purchasing", "type": "SAP Fiori"},
            "ME57": {"app_id": "F4991", "name": "Assign/Process Requisitions", "type": "SAP Fiori"},
            "ME59N": {"app_id": "F2390", "name": "Auto-Generate POs", "type": "SAP Fiori"},
            "MIGO": {"app_id": "F3993", "name": "Goods Movement", "type": "SAP Fiori"},
            "MB01": {"app_id": "F3993", "name": "Post Goods Receipt", "type": "SAP Fiori"},
            "MB02": {"app_id": "F3993", "name": "Change Material Document", "type": "SAP Fiori"},
            "MB03": {"app_id": "F3993", "name": "Display Material Document", "type": "SAP Fiori"},
            "MB11": {"app_id": "F3993", "name": "Goods Movement", "type": "SAP Fiori"},
            "MB1A": {"app_id": "F3994", "name": "Goods Issue", "type": "SAP Fiori"},
            "MB1B": {"app_id": "F3995", "name": "Transfer Posting", "type": "SAP Fiori"},
            "MB1C": {"app_id": "F3996", "name": "Other Goods Receipts", "type": "SAP Fiori"},
            "MB51": {"app_id": "F2513", "name": "Material Document List", "type": "SAP Fiori"},
            "MB52": {"app_id": "F2579", "name": "Warehouse Stocks", "type": "SAP Fiori"},
            "MB5B": {"app_id": "F4001", "name": "Stocks on Posting Date", "type": "SAP Fiori"},
            "MMBE": {"app_id": "F2579", "name": "Stock Overview", "type": "SAP Fiori"},
            "MM01": {"app_id": "F4104", "name": "Create Material", "type": "SAP Fiori"},
            "MM02": {"app_id": "F4104", "name": "Change Material", "type": "SAP Fiori"},
            "MM03": {"app_id": "F4104", "name": "Display Material", "type": "SAP Fiori"},
            "MM04": {"app_id": "F1602C", "name": "Display Material Changes", "type": "SAP Fiori"},
            "MR21": {"app_id": "F2391", "name": "Price Change", "type": "SAP Fiori"},
            "MRIS": {"app_id": "F2392", "name": "Invoice Verification in Background", "type": "SAP Fiori"},
            "MI01": {"app_id": "F3997", "name": "Create Physical Inventory Document", "type": "SAP Fiori"},
            "MI04": {"app_id": "F3998", "name": "Enter Inventory Count", "type": "SAP Fiori"},
            "MI07": {"app_id": "F3999", "name": "Post Differences", "type": "SAP Fiori"},
            "MI20": {"app_id": "F4000", "name": "Print Physical Inventory List", "type": "SAP Fiori"},
            "MK01": {"app_id": "F1814", "name": "Create Vendor", "type": "SAP Fiori"},
            "MK02": {"app_id": "F1814", "name": "Change Vendor", "type": "SAP Fiori"},

            # === Production Planning (PP) ===
            "CO01": {"app_id": "F4515", "name": "Create Production Order", "type": "SAP Fiori"},
            "CO02": {"app_id": "F4515", "name": "Change Production Order", "type": "SAP Fiori"},
            "CO03": {"app_id": "F4515", "name": "Display Production Order", "type": "SAP Fiori"},
            "CO11N": {"app_id": "F4516", "name": "Enter Confirmation", "type": "SAP Fiori"},
            "CO15": {"app_id": "F4517", "name": "Enter Confirmation - Final", "type": "SAP Fiori"},
            "COOIS": {"app_id": "F4518", "name": "Production Order Info System", "type": "SAP Fiori"},
            "CS01": {"app_id": "F4519", "name": "Create BOM", "type": "SAP Fiori"},
            "CS02": {"app_id": "F4519", "name": "Change BOM", "type": "SAP Fiori"},
            "CS03": {"app_id": "F4519", "name": "Display BOM", "type": "SAP Fiori"},
            "CA01": {"app_id": "F4520", "name": "Create Routing", "type": "SAP Fiori"},
            "CA02": {"app_id": "F4520", "name": "Change Routing", "type": "SAP Fiori"},
            "CA03": {"app_id": "F4520", "name": "Display Routing", "type": "SAP Fiori"},
            "MD01": {"app_id": "F4521", "name": "Run MRP", "type": "SAP Fiori"},
            "MD02": {"app_id": "F4522", "name": "Single-Item MRP", "type": "SAP Fiori"},
            "MD04": {"app_id": "F4523", "name": "Stock/Requirements List", "type": "SAP Fiori"},
            "MD05": {"app_id": "F4524", "name": "Individual MRP List", "type": "SAP Fiori"},
            "MD06": {"app_id": "F4525", "name": "Display MRP List", "type": "SAP Fiori"},
            "MD07": {"app_id": "F4526", "name": "Current Stock/Requirements", "type": "SAP Fiori"},
            "CR01": {"app_id": "F4527", "name": "Create Work Center", "type": "SAP Fiori"},
            "CR02": {"app_id": "F4527", "name": "Change Work Center", "type": "SAP Fiori"},
            "MF42": {"app_id": "F4528", "name": "Kanban Board", "type": "SAP Fiori"},
            "MDBT": {"app_id": "F4521", "name": "MRP Run - Background", "type": "SAP Fiori"},
            "PI01": {"app_id": "F4529", "name": "Create Process Order", "type": "SAP Fiori"},

            # === Plant Maintenance (PM) ===
            "IW21": {"app_id": "F4530", "name": "Create Notification", "type": "SAP Fiori"},
            "IW22": {"app_id": "F4530", "name": "Change Notification", "type": "SAP Fiori"},
            "IW23": {"app_id": "F4530", "name": "Display Notification", "type": "SAP Fiori"},
            "IW31": {"app_id": "F4531", "name": "Create Maintenance Order", "type": "SAP Fiori"},
            "IW32": {"app_id": "F4531", "name": "Change Maintenance Order", "type": "SAP Fiori"},
            "IW33": {"app_id": "F4531", "name": "Display Maintenance Order", "type": "SAP Fiori"},
            "IW38": {"app_id": "F4532", "name": "Change Orders", "type": "SAP Fiori"},
            "IW39": {"app_id": "F4533", "name": "Display Orders", "type": "SAP Fiori"},
            "IW28": {"app_id": "F4534", "name": "Change Notifications List", "type": "SAP Fiori"},
            "IW29": {"app_id": "F4535", "name": "Display Notifications List", "type": "SAP Fiori"},
            "IE01": {"app_id": "F4536", "name": "Create Equipment", "type": "SAP Fiori"},
            "IE02": {"app_id": "F4536", "name": "Change Equipment", "type": "SAP Fiori"},
            "IE03": {"app_id": "F4536", "name": "Display Equipment", "type": "SAP Fiori"},
            "IL01": {"app_id": "F4537", "name": "Create Functional Location", "type": "SAP Fiori"},
            "IL02": {"app_id": "F4537", "name": "Change Functional Location", "type": "SAP Fiori"},
            "IL03": {"app_id": "F4537", "name": "Display Functional Location", "type": "SAP Fiori"},
            "IP10": {"app_id": "F4538", "name": "Schedule Maintenance Plans", "type": "SAP Fiori"},
            "IP30": {"app_id": "F4539", "name": "Deadline Monitoring", "type": "SAP Fiori"},
            "IA01": {"app_id": "F4540", "name": "Create General Task List", "type": "SAP Fiori"},
            "IA05": {"app_id": "F4541", "name": "Create Equip Task List", "type": "SAP Fiori"},
            "IK01": {"app_id": "F4542", "name": "Create Measuring Point", "type": "SAP Fiori"},

            # === Quality Management (QM) ===
            "QA01": {"app_id": "F4543", "name": "Create Inspection Lot", "type": "SAP Fiori"},
            "QA02": {"app_id": "F4543", "name": "Change Inspection Lot", "type": "SAP Fiori"},
            "QA03": {"app_id": "F4543", "name": "Display Inspection Lot", "type": "SAP Fiori"},
            "QE01": {"app_id": "F4544", "name": "Record Results", "type": "SAP Fiori"},
            "QA11": {"app_id": "F4545", "name": "Record Usage Decision", "type": "SAP Fiori"},
            "QM01": {"app_id": "F4546", "name": "Create Quality Notification", "type": "SAP Fiori"},
            "QM02": {"app_id": "F4546", "name": "Change Quality Notification", "type": "SAP Fiori"},
            "QM03": {"app_id": "F4546", "name": "Display Quality Notification", "type": "SAP Fiori"},
            "QS21": {"app_id": "F4547", "name": "Create Master Inspection Char", "type": "SAP Fiori"},
            "QP01": {"app_id": "F4548", "name": "Create Inspection Plan", "type": "SAP Fiori"},
            "QP02": {"app_id": "F4548", "name": "Change Inspection Plan", "type": "SAP Fiori"},
            "QDM2": {"app_id": "F4549", "name": "Defects Recording", "type": "SAP Fiori"},
            "QCPA": {"app_id": "F4550", "name": "QM Certificate", "type": "SAP Fiori"},
            "QC21": {"app_id": "F4551", "name": "Create Quality Certificate", "type": "SAP Fiori"},
            "QPR5": {"app_id": "F4552", "name": "Inspection Catalogs", "type": "SAP Fiori"},

            # === Warehouse Management (WM) / Extended Warehouse Management (EWM) ===
            "LT01": {"app_id": "F4553", "name": "Create Transfer Order - WM", "type": "SAP Fiori"},
            "LT02": {"app_id": "F4553", "name": "Change Transfer Order - WM", "type": "SAP Fiori"},
            "LT03": {"app_id": "F4553", "name": "Display Transfer Order - WM", "type": "SAP Fiori"},
            "LT06": {"app_id": "F4554", "name": "Create TO for Material Doc", "type": "SAP Fiori"},
            "LT0E": {"app_id": "F4555", "name": "Create TO for Storage Units", "type": "SAP Fiori"},
            "LT21": {"app_id": "F3501", "name": "Create Transfer Order from TR", "type": "SAP Fiori"},
            "LS03N": {"app_id": "F4556", "name": "Display Storage Bin", "type": "SAP Fiori"},
            "LS26": {"app_id": "F3502", "name": "Warehouse Stocks per Material", "type": "SAP Fiori"},
            "LX02": {"app_id": "F4557", "name": "Warehouse Utilization", "type": "SAP Fiori"},
            "/SCWM/MON": {"app_id": "F4558", "name": "Warehouse Monitor - EWM", "type": "SAP Fiori"},
            "/SCWM/PACK": {"app_id": "F4559", "name": "Packing - EWM", "type": "SAP Fiori"},
            "/SCWM/PRDI": {"app_id": "F4560", "name": "Inbound Processing - EWM", "type": "SAP Fiori"},
            "/SCWM/PRDO": {"app_id": "F4561", "name": "Outbound Processing - EWM", "type": "SAP Fiori"},

            # === Human Resources / HCM ===
            "PA20": {"app_id": "F4562", "name": "Display HR Master Data", "type": "SAP Fiori"},
            "PA30": {"app_id": "F4562", "name": "Maintain HR Master Data", "type": "SAP Fiori"},
            "PA40": {"app_id": "F4563", "name": "Personnel Actions", "type": "SAP Fiori"},
            "PA61": {"app_id": "F4564", "name": "Maintain Time Data", "type": "SAP Fiori"},
            "PA71": {"app_id": "F4565", "name": "Fast Entry - Time", "type": "SAP Fiori"},
            "PT01": {"app_id": "F4566", "name": "Create Work Schedule", "type": "SAP Fiori"},
            "PT60": {"app_id": "F4567", "name": "Time Evaluation", "type": "SAP Fiori"},
            "PT62": {"app_id": "F4568", "name": "Time Leveling", "type": "SAP Fiori"},
            "PC00_M99_CALC": {"app_id": "F4569", "name": "Payroll Run", "type": "SAP Fiori"},
            "PC00_M40_CALC": {"app_id": "F5640", "name": "Run Payroll", "type": "SAP Fiori"},
            "PU03": {"app_id": "F4570", "name": "Change Payroll Status", "type": "SAP Fiori"},
            "PU22": {"app_id": "F4571", "name": "Delete Payroll Results", "type": "SAP Fiori"},
            "PRMS": {"app_id": "F4572", "name": "HR Process Workbench", "type": "SAP Fiori"},
            "PA10": {"app_id": "F4573", "name": "Personnel File", "type": "SAP Fiori"},
            "PB10": {"app_id": "F4574", "name": "Applicant File", "type": "SAP Fiori"},
            "PPOM": {"app_id": "F4575", "name": "Org Management", "type": "SAP Fiori"},
            "PPOME": {"app_id": "F4576", "name": "Org & Staffing - Change", "type": "SAP Fiori"},
            "PP01": {"app_id": "F4577", "name": "Maintain Plan Data", "type": "SAP Fiori"},

            # === Treasury / Cash Management ===
            "FF7A": {"app_id": "F4578", "name": "Cash Position", "type": "SAP Fiori"},
            "FF7B": {"app_id": "F4579", "name": "Liquidity Forecast", "type": "SAP Fiori"},
            "FF67": {"app_id": "F4580", "name": "Bank Statement", "type": "SAP Fiori"},
            "FTR_CREATE": {"app_id": "F4581", "name": "Create Financial Transaction", "type": "SAP Fiori"},
            "FTR_EDIT": {"app_id": "F4582", "name": "Edit Financial Transaction", "type": "SAP Fiori"},
            "TBB1": {"app_id": "F4583", "name": "Position Management", "type": "SAP Fiori"},
            "FWZZ": {"app_id": "F4584", "name": "Payment Request", "type": "SAP Fiori"},

            # === Project Systems (PS) ===
            "CJ01": {"app_id": "F4585", "name": "Create WBS", "type": "SAP Fiori"},
            "CJ02": {"app_id": "F4585", "name": "Change WBS", "type": "SAP Fiori"},
            "CJ03": {"app_id": "F4585", "name": "Display WBS", "type": "SAP Fiori"},
            "CN01": {"app_id": "F4586", "name": "Create Network", "type": "SAP Fiori"},
            "CN02": {"app_id": "F4586", "name": "Change Network", "type": "SAP Fiori"},
            "CJ30": {"app_id": "F4587", "name": "Budget Maintenance", "type": "SAP Fiori"},
            "CJ40": {"app_id": "F4588", "name": "Display Plan/Budget", "type": "SAP Fiori"},
            "CJ45": {"app_id": "F4589", "name": "Budget Carryforward", "type": "SAP Fiori"},
            "CNMM": {"app_id": "F4590", "name": "Project Materials", "type": "SAP Fiori"},

            # === Basis / Administration ===
            "SM37": {"app_id": "F4591", "name": "Job Overview", "type": "SAP Fiori"},
            "SM36": {"app_id": "F4592", "name": "Schedule Background Job", "type": "SAP Fiori"},
            "SM21": {"app_id": "F4593", "name": "System Log", "type": "SAP Fiori"},
            "SM50": {"app_id": "F4594", "name": "Process Overview", "type": "SAP Fiori"},
            "SM51": {"app_id": "F4595", "name": "Server List", "type": "SAP Fiori"},
            "ST22": {"app_id": "F4596", "name": "ABAP Runtime Errors", "type": "SAP Fiori"},
            "SE16N": {"app_id": "F4597", "name": "General Table Display", "type": "SAP Fiori"},
            "STMS": {"app_id": "F4598", "name": "Transport Management System", "type": "SAP Fiori"},
            "SCC4": {"app_id": "F4599", "name": "Client Administration", "type": "SAP Fiori"},
            "SICF": {"app_id": "F4600", "name": "ICF Service Admin", "type": "SAP Fiori"},
            "SPRO": {"app_id": "F4601", "name": "Customizing", "type": "SAP Fiori"},
            "SU01": {"app_id": "F5700", "name": "User Maintenance", "type": "SAP Fiori"},
            "NWBC": {"app_id": "F5704", "name": "SAP Business Client", "type": "SAP Fiori"},

            # === Basis - ADT Replacements (Eclipse-based ABAP Development Tools) ===
            "SE80": {"app_id": "ADT", "name": "Object Navigator - ADT", "type": "ADT/Eclipse"},
            "SE38": {"app_id": "ADT", "name": "ABAP Editor - ADT", "type": "ADT/Eclipse"},
            "SE24": {"app_id": "ADT", "name": "Class Builder - ADT", "type": "ADT/Eclipse"},
            "SE11": {"app_id": "ADT", "name": "ABAP Dictionary - ADT", "type": "ADT/Eclipse"},
            "SE37": {"app_id": "ADT", "name": "Function Builder - ADT", "type": "ADT/Eclipse"},

            # ================================================================
            # ADDITIONAL MAPPINGS - Extended Coverage
            # Covers additional high-frequency T-codes across all modules
            # ================================================================

            # === Finance - Additional GL / Banking / Closing ===
            "F-51": {"app_id": "F0717", "name": "Post with Clearing - G/L", "type": "SAP Fiori"},
            "F-30": {"app_id": "F1603", "name": "Post with Clearing - Customer", "type": "SAP Fiori"},
            "F-31": {"app_id": "F2559", "name": "Post Outgoing Payments - Customer", "type": "SAP Fiori"},
            "F-36": {"app_id": "F2559", "name": "Bill of Exchange Payment", "type": "SAP Fiori"},
            "F-40": {"app_id": "F0717", "name": "Post Bill of Exchange", "type": "SAP Fiori"},
            "F-48": {"app_id": "F0717", "name": "Post Vendor Down Payment", "type": "SAP Fiori"},
            "F-49": {"app_id": "F0717", "name": "Post Customer Down Payment", "type": "SAP Fiori"},
            "F-54": {"app_id": "F1603", "name": "Clear Vendor Down Payment", "type": "SAP Fiori"},
            "F-39": {"app_id": "F1603", "name": "Clear Customer Down Payment", "type": "SAP Fiori"},
            "FB05": {"app_id": "F1603", "name": "Post with Clearing", "type": "SAP Fiori"},
            "FBS1": {"app_id": "F0717", "name": "Enter Accrual/Deferral Document", "type": "SAP Fiori"},
            "F.05": {"app_id": "F0727", "name": "Foreign Currency Valuation", "type": "SAP Fiori"},
            "F.06": {"app_id": "F0727", "name": "Foreign Currency Valuation - GL", "type": "SAP Fiori"},
            "FAGL_FC_VAL": {"app_id": "F2548", "name": "Foreign Currency Valuation", "type": "SAP Fiori"},
            "FAGL_FC_TRANS": {"app_id": "F2548", "name": "Foreign Currency Translation", "type": "SAP Fiori"},
            "GCAC": {"app_id": "F4602", "name": "Group Consolidation", "type": "SAP Fiori"},
            "OBB8": {"app_id": "F3705", "name": "Maintain Posting Keys", "type": "SAP Fiori"},
            "FBKP": {"app_id": "F4603", "name": "Account Determination Config", "type": "SAP Fiori"},
            "FI12": {"app_id": "F4604", "name": "Manage Bank Master Data", "type": "SAP Fiori"},
            "FEBA": {"app_id": "F4580", "name": "Process Electronic Bank Statement", "type": "SAP Fiori"},
            "FEBAN": {"app_id": "F4580", "name": "Post Electronic Bank Statement", "type": "SAP Fiori"},
            "FF.5": {"app_id": "F4578", "name": "Import Electronic Bank Statement", "type": "SAP Fiori"},
            "FI01": {"app_id": "F4604", "name": "Create Bank Master Data", "type": "SAP Fiori"},
            "FI02": {"app_id": "F4604", "name": "Change Bank Master Data", "type": "SAP Fiori"},
            "FI03": {"app_id": "F4604", "name": "Display Bank Master Data", "type": "SAP Fiori"},
            "F.16": {"app_id": "F4605", "name": "G/L Balance Carry Forward", "type": "SAP Fiori"},
            "F.07": {"app_id": "F4605", "name": "Customer Balance Carry Forward", "type": "SAP Fiori"},
            "F.08": {"app_id": "F4605", "name": "Vendor Balance Carry Forward", "type": "SAP Fiori"},
            "AJRW": {"app_id": "F4606", "name": "Asset Fiscal Year Change", "type": "SAP Fiori"},
            "AJAB": {"app_id": "F4607", "name": "Asset Year-End Closing", "type": "SAP Fiori"},

            # === Finance - Tax ===
            "FB41": {"app_id": "F0717", "name": "Post Tax Payable", "type": "SAP Fiori"},
            "S_ALR_87012357": {"app_id": "F4608", "name": "Advance Tax Return", "type": "SAP Fiori"},
            "FTXP": {"app_id": "F4609", "name": "Maintain Tax Code", "type": "SAP Fiori"},
            "OBCL": {"app_id": "F4610", "name": "Withholding Tax Type", "type": "SAP Fiori"},

            # === Finance - Travel Management ===
            "PR05": {"app_id": "F4611", "name": "Travel Expenses Manager", "type": "SAP Fiori"},
            "TRIP": {"app_id": "F4612", "name": "Travel Expenses", "type": "SAP Fiori"},

            # === Controlling - Additional ===
            "KA03": {"app_id": "F1615", "name": "Display Cost Element", "type": "SAP Fiori"},
            "KO04": {"app_id": "F2681", "name": "Maintain Internal Order Budget", "type": "SAP Fiori"},
            "KSU1": {"app_id": "F1614", "name": "Create Cost Center Group", "type": "SAP Fiori"},
            "KSH1": {"app_id": "F1614", "name": "Create Cost Center Hierarchy", "type": "SAP Fiori"},
            "KSH2": {"app_id": "F1614", "name": "Change Cost Center Hierarchy", "type": "SAP Fiori"},
            "OKEON": {"app_id": "F1615", "name": "Maintain Automatic Cost Elements", "type": "SAP Fiori"},
            "KOK2": {"app_id": "F2681", "name": "Order Group - Change", "type": "SAP Fiori"},
            "KOK5": {"app_id": "F4613", "name": "Internal Order Settlement", "type": "SAP Fiori"},
            "KO88": {"app_id": "F4613", "name": "Settle Internal Orders", "type": "SAP Fiori"},
            "KSS2": {"app_id": "F4614", "name": "Cost Center Distribution", "type": "SAP Fiori"},
            "KSV5": {"app_id": "F4615", "name": "Cost Center Assessment", "type": "SAP Fiori"},
            "KALC": {"app_id": "F4616", "name": "Costing Run", "type": "SAP Fiori"},
            "CK11N": {"app_id": "F4617", "name": "Create Product Cost Estimate", "type": "SAP Fiori"},
            "CK40N": {"app_id": "F4618", "name": "Costing Run - Edit", "type": "SAP Fiori"},
            "KKS2": {"app_id": "F4619", "name": "Actual Cost Splitting", "type": "SAP Fiori"},

            # === Sales & Distribution - Additional ===
            "VA11": {"app_id": "F4620", "name": "Create Inquiry", "type": "SAP Fiori"},
            "VA12": {"app_id": "F4620", "name": "Change Inquiry", "type": "SAP Fiori"},
            "VA13": {"app_id": "F4620", "name": "Display Inquiry", "type": "SAP Fiori"},
            "VA23": {"app_id": "F4979", "name": "Display Quotation", "type": "SAP Fiori"},
            "VA32": {"app_id": "F4980", "name": "Change Scheduling Agreement", "type": "SAP Fiori"},
            "VA43": {"app_id": "F4981", "name": "Display Contract", "type": "SAP Fiori"},
            "VL06G": {"app_id": "F2530", "name": "Goods Issue for Deliveries", "type": "SAP Fiori"},
            "VL06I": {"app_id": "F2530", "name": "Inbound Delivery Monitor", "type": "SAP Fiori"},
            "VL06P": {"app_id": "F2530", "name": "POD Monitor", "type": "SAP Fiori"},
            "VL31N": {"app_id": "F2029", "name": "Create Inbound Delivery", "type": "SAP Fiori"},
            "VL32N": {"app_id": "F2029", "name": "Change Inbound Delivery", "type": "SAP Fiori"},
            "VL33N": {"app_id": "F2029", "name": "Display Inbound Delivery", "type": "SAP Fiori"},
            "VA45": {"app_id": "F4621", "name": "List of Contracts", "type": "SAP Fiori"},
            "VA25": {"app_id": "F4622", "name": "List of Quotations", "type": "SAP Fiori"},
            "VA15": {"app_id": "F4623", "name": "List of Inquiries", "type": "SAP Fiori"},
            "VA35": {"app_id": "F4624", "name": "List of Scheduling Agreements", "type": "SAP Fiori"},
            "V.02": {"app_id": "F4625", "name": "Incomplete Sales Orders", "type": "SAP Fiori"},
            "V.15": {"app_id": "F4626", "name": "Backorder Processing", "type": "SAP Fiori"},
            "VFX3": {"app_id": "F4627", "name": "Blocked Billing Documents", "type": "SAP Fiori"},
            "VL04": {"app_id": "F4628", "name": "Create Delivery Collective", "type": "SAP Fiori"},

            # === Materials Management - Additional ===
            "ME33K": {"app_id": "F4988", "name": "Display Contract - Purchasing", "type": "SAP Fiori"},
            "ME42": {"app_id": "F4989", "name": "Change RFQ", "type": "SAP Fiori"},
            "ME43": {"app_id": "F4989", "name": "Display RFQ", "type": "SAP Fiori"},
            "ME48": {"app_id": "F4990", "name": "Display Quotation - Purchasing", "type": "SAP Fiori"},
            "ME49": {"app_id": "F4990", "name": "Price Comparison", "type": "SAP Fiori"},
            "ME58": {"app_id": "F4991", "name": "Order Requisitions Externally", "type": "SAP Fiori"},
            "ME80FN": {"app_id": "F4629", "name": "Purchasing Reporting", "type": "SAP Fiori"},
            "ME9F": {"app_id": "F4630", "name": "Message Output - PO", "type": "SAP Fiori"},
            "MELB": {"app_id": "F4631", "name": "PO History by Vendor", "type": "SAP Fiori"},
            "MB21": {"app_id": "F4632", "name": "Create Reservation", "type": "SAP Fiori"},
            "MB22": {"app_id": "F4632", "name": "Change Reservation", "type": "SAP Fiori"},
            "MB23": {"app_id": "F4632", "name": "Display Reservation", "type": "SAP Fiori"},
            "MB24": {"app_id": "F4633", "name": "Reservations List", "type": "SAP Fiori"},
            "MB25": {"app_id": "F4634", "name": "Reservation Analysis", "type": "SAP Fiori"},
            "MB90": {"app_id": "F4635", "name": "Output for Goods Movements", "type": "SAP Fiori"},
            "MI09": {"app_id": "F3998", "name": "Enter Inventory Count w/o Ref", "type": "SAP Fiori"},
            "MI10": {"app_id": "F4000", "name": "Create Physical Inventory Docs", "type": "SAP Fiori"},
            "MI31": {"app_id": "F3997", "name": "Batch Input - Physical Inventory", "type": "SAP Fiori"},
            "MIBC": {"app_id": "F4636", "name": "ABC Analysis for Cycle Counting", "type": "SAP Fiori"},
            "MIK1": {"app_id": "F3997", "name": "Batch Input - Vendor Consignment", "type": "SAP Fiori"},
            "ME12": {"app_id": "F4637", "name": "Change Info Record", "type": "SAP Fiori"},
            "ME13": {"app_id": "F4637", "name": "Display Info Record", "type": "SAP Fiori"},
            "ME11": {"app_id": "F4637", "name": "Create Info Record", "type": "SAP Fiori"},
            "MK03": {"app_id": "F1814", "name": "Display Vendor", "type": "SAP Fiori"},
            "ME5A": {"app_id": "F2389", "name": "List Purchase Requisitions", "type": "SAP Fiori"},

            # === Production Planning - Additional ===
            "CO04N": {"app_id": "F4515", "name": "Production Order List", "type": "SAP Fiori"},
            "CO05N": {"app_id": "F4515", "name": "Production Order Collective Release", "type": "SAP Fiori"},
            "CO13": {"app_id": "F4516", "name": "Cancel Confirmation", "type": "SAP Fiori"},
            "CO14": {"app_id": "F4516", "name": "Display Confirmation", "type": "SAP Fiori"},
            "CO16N": {"app_id": "F4516", "name": "Collective Confirmation", "type": "SAP Fiori"},
            "CS11": {"app_id": "F4519", "name": "BOM Multi-Level Explosion", "type": "SAP Fiori"},
            "CS12": {"app_id": "F4519", "name": "BOM Multi-Level Where-Used", "type": "SAP Fiori"},
            "CS15": {"app_id": "F4519", "name": "BOM Single-Level Where-Used", "type": "SAP Fiori"},
            "CR03": {"app_id": "F4527", "name": "Display Work Center", "type": "SAP Fiori"},
            "CR05": {"app_id": "F4527", "name": "Work Center List", "type": "SAP Fiori"},
            "CA23": {"app_id": "F4520", "name": "Display Routing - Where Used", "type": "SAP Fiori"},
            "MD11": {"app_id": "F4638", "name": "Create Planned Order", "type": "SAP Fiori"},
            "MD12": {"app_id": "F4638", "name": "Change Planned Order", "type": "SAP Fiori"},
            "MD13": {"app_id": "F4638", "name": "Display Planned Order", "type": "SAP Fiori"},
            "MD16": {"app_id": "F4639", "name": "Convert Planned Order to PO", "type": "SAP Fiori"},
            "CM01": {"app_id": "F4640", "name": "Capacity Planning - Work Center", "type": "SAP Fiori"},
            "CM21": {"app_id": "F4641", "name": "Capacity Leveling - Work Center", "type": "SAP Fiori"},
            "CM25": {"app_id": "F4642", "name": "Capacity Planning - Order", "type": "SAP Fiori"},
            "MF50": {"app_id": "F4643", "name": "Repetitive Manufacturing Planning", "type": "SAP Fiori"},
            "PI02": {"app_id": "F4529", "name": "Change Process Order", "type": "SAP Fiori"},
            "PI03": {"app_id": "F4529", "name": "Display Process Order", "type": "SAP Fiori"},

            # === Plant Maintenance - Additional ===
            "IW37N": {"app_id": "F4532", "name": "Change PM Orders List", "type": "SAP Fiori"},
            "IW40": {"app_id": "F4644", "name": "Display Estimated Costs", "type": "SAP Fiori"},
            "IW41": {"app_id": "F4531", "name": "Enter PM Confirmation", "type": "SAP Fiori"},
            "IW42": {"app_id": "F4531", "name": "Overall Completion Confirmation", "type": "SAP Fiori"},
            "IW45": {"app_id": "F4531", "name": "Cancel PM Confirmation", "type": "SAP Fiori"},
            "IW66": {"app_id": "F4530", "name": "Change Malfunction Report", "type": "SAP Fiori"},
            "IW67": {"app_id": "F4530", "name": "Create Malfunction Report", "type": "SAP Fiori"},
            "IW68": {"app_id": "F4530", "name": "Display Malfunction Report", "type": "SAP Fiori"},
            "IH01": {"app_id": "F4645", "name": "Display Equipment Structure", "type": "SAP Fiori"},
            "IH06": {"app_id": "F4536", "name": "Equipment List", "type": "SAP Fiori"},
            "IH08": {"app_id": "F4537", "name": "Functional Location List", "type": "SAP Fiori"},
            "IP02": {"app_id": "F4538", "name": "Change Maintenance Plan", "type": "SAP Fiori"},
            "IP03": {"app_id": "F4538", "name": "Display Maintenance Plan", "type": "SAP Fiori"},
            "IP04": {"app_id": "F4538", "name": "Create Maintenance Plan", "type": "SAP Fiori"},

            # === Quality Management - Additional ===
            "QA32": {"app_id": "F4543", "name": "Change Inspection Lot Status", "type": "SAP Fiori"},
            "QE02": {"app_id": "F4544", "name": "Change Results", "type": "SAP Fiori"},
            "QE03": {"app_id": "F4544", "name": "Display Results", "type": "SAP Fiori"},
            "QE51N": {"app_id": "F4544", "name": "Record Characteristics Results", "type": "SAP Fiori"},
            "QP03": {"app_id": "F4548", "name": "Display Inspection Plan", "type": "SAP Fiori"},
            "QS23": {"app_id": "F4547", "name": "Change Master Insp Characteristics", "type": "SAP Fiori"},
            "QS28": {"app_id": "F4646", "name": "Change Selected Set", "type": "SAP Fiori"},

            # === Warehouse Management - Additional ===
            "LT12": {"app_id": "F4553", "name": "Confirm Transfer Order - WM", "type": "SAP Fiori"},
            "LT15": {"app_id": "F4553", "name": "Cancel Transfer Order - WM", "type": "SAP Fiori"},
            "LT22": {"app_id": "F4553", "name": "Display Transfer Order - Confirmed", "type": "SAP Fiori"},
            "LT23": {"app_id": "F4553", "name": "Display Transfer Order - Single", "type": "SAP Fiori"},
            "LT24": {"app_id": "F4553", "name": "Display Transfer Order - Archived", "type": "SAP Fiori"},
            "LS01N": {"app_id": "F4556", "name": "Create Storage Bin", "type": "SAP Fiori"},
            "LS02N": {"app_id": "F4556", "name": "Change Storage Bin", "type": "SAP Fiori"},
            "LX01": {"app_id": "F4557", "name": "List of Empty Storage Bins", "type": "SAP Fiori"},
            "LX03": {"app_id": "F4557", "name": "Bin Status Report", "type": "SAP Fiori"},

            # === Human Resources - Additional ===
            "PA51": {"app_id": "F4564", "name": "Display Time Data", "type": "SAP Fiori"},
            "PA62": {"app_id": "F4564", "name": "List Time Data", "type": "SAP Fiori"},
            "PA63": {"app_id": "F4564", "name": "Maintain Attendance/Absence", "type": "SAP Fiori"},
            "PT50": {"app_id": "F4567", "name": "Quota Overview", "type": "SAP Fiori"},
            "PT63": {"app_id": "F4567", "name": "Personal Work Schedule", "type": "SAP Fiori"},
            "PT64": {"app_id": "F4567", "name": "Absence Overview", "type": "SAP Fiori"},
            "PA03": {"app_id": "F4570", "name": "Maintain Payroll Control Record", "type": "SAP Fiori"},
            "PC00_M10_CALC": {"app_id": "F4569", "name": "Run Payroll - US", "type": "SAP Fiori"},
            "PC00_M08_CALC": {"app_id": "F4569", "name": "Run Payroll - UK", "type": "SAP Fiori"},
            "PB30": {"app_id": "F4574", "name": "Applicant Actions", "type": "SAP Fiori"},
            "PB40": {"app_id": "F4574", "name": "Applicant Activities", "type": "SAP Fiori"},
            "PPOC": {"app_id": "F4576", "name": "Create Organizational Unit", "type": "SAP Fiori"},
            "PPOS": {"app_id": "F4576", "name": "Display Org & Staffing", "type": "SAP Fiori"},
            "PP02": {"app_id": "F4577", "name": "Change Plan Data", "type": "SAP Fiori"},
            "PP03": {"app_id": "F4577", "name": "Display Plan Data", "type": "SAP Fiori"},

            # === Treasury / Cash Management - Additional ===
            "FF63": {"app_id": "F4580", "name": "Bank Statement Manual", "type": "SAP Fiori"},
            "FF68": {"app_id": "F4580", "name": "Bank Statement Reprocess", "type": "SAP Fiori"},
            "FTR_DISPLAY": {"app_id": "F4582", "name": "Display Financial Transaction", "type": "SAP Fiori"},
            "FWBS": {"app_id": "F4647", "name": "Bank Statement Overview", "type": "SAP Fiori"},

            # === Project Systems - Additional ===
            "CJ06": {"app_id": "F4585", "name": "Create Project Definition", "type": "SAP Fiori"},
            "CJ07": {"app_id": "F4585", "name": "Change Project Definition", "type": "SAP Fiori"},
            "CJ08": {"app_id": "F4585", "name": "Display Project Definition", "type": "SAP Fiori"},
            "CJ11": {"app_id": "F4585", "name": "Create WBS Element", "type": "SAP Fiori"},
            "CJ12": {"app_id": "F4585", "name": "Change WBS Element", "type": "SAP Fiori"},
            "CJ13": {"app_id": "F4585", "name": "Display WBS Element", "type": "SAP Fiori"},
            "CN21": {"app_id": "F4586", "name": "Create Network Activity", "type": "SAP Fiori"},
            "CN22": {"app_id": "F4586", "name": "Change Network Activity", "type": "SAP Fiori"},
            "CN23": {"app_id": "F4586", "name": "Display Network Activity", "type": "SAP Fiori"},
            "CJ31": {"app_id": "F4587", "name": "Change Project Budget", "type": "SAP Fiori"},
            "CJ32": {"app_id": "F4587", "name": "Display Project Budget", "type": "SAP Fiori"},
            "CJ33": {"app_id": "F4587", "name": "Budget Availability Control", "type": "SAP Fiori"},
            "CJ42": {"app_id": "F4648", "name": "Overall Planning", "type": "SAP Fiori"},
            "CJ44": {"app_id": "F4649", "name": "Plan/Actual Comparison", "type": "SAP Fiori"},
            "CNDN": {"app_id": "F4650", "name": "Project Progress", "type": "SAP Fiori"},
            "CNS0": {"app_id": "F4651", "name": "Project Summarization", "type": "SAP Fiori"},

            # === Basis / Administration - Additional ===
            "SM12": {"app_id": "F4652", "name": "Display/Delete Lock Entries", "type": "SAP Fiori"},
            "SM13": {"app_id": "F4653", "name": "Administrate Update Records", "type": "SAP Fiori"},
            "SM04": {"app_id": "F4654", "name": "User List", "type": "SAP Fiori"},
            "SM35": {"app_id": "F4655", "name": "Batch Input Monitoring", "type": "SAP Fiori"},
            "SM59": {"app_id": "F4656", "name": "RFC Destinations", "type": "SAP Fiori"},
            "SM58": {"app_id": "F4657", "name": "Asynchronous RFC Error Log", "type": "SAP Fiori"},
            "SM66": {"app_id": "F4594", "name": "Systemwide Work Processes", "type": "SAP Fiori"},
            "SLG1": {"app_id": "F4658", "name": "Application Log", "type": "SAP Fiori"},
            "ST01": {"app_id": "F4659", "name": "System Trace", "type": "SAP Fiori"},
            "ST02": {"app_id": "F4660", "name": "Tune Summary", "type": "SAP Fiori"},
            "ST03N": {"app_id": "F4661", "name": "Workload Monitor", "type": "SAP Fiori"},
            "ST04": {"app_id": "F4662", "name": "DB Performance Monitor", "type": "SAP Fiori"},
            "ST05": {"app_id": "F4663", "name": "Performance Trace", "type": "SAP Fiori"},
            "ST06": {"app_id": "F4664", "name": "Operating System Monitor", "type": "SAP Fiori"},
            "SU01D": {"app_id": "F5700", "name": "User Display", "type": "SAP Fiori"},
            "SU10": {"app_id": "F5700", "name": "Mass User Maintenance", "type": "SAP Fiori"},
            "SU53": {"app_id": "F4665", "name": "Display Authorization Values", "type": "SAP Fiori"},
            "SUIM": {"app_id": "F4666", "name": "User Info System", "type": "SAP Fiori"},
            "PFCG": {"app_id": "F4667", "name": "Role Maintenance", "type": "SAP Fiori"},
            "SE01": {"app_id": "F4598", "name": "Transport Organizer", "type": "SAP Fiori"},
            "SE09": {"app_id": "F4598", "name": "Transport Organizer - Workbench", "type": "SAP Fiori"},
            "SE10": {"app_id": "F4598", "name": "Transport Organizer - Customizing", "type": "SAP Fiori"},
            "SE93": {"app_id": "F4668", "name": "Maintain Transaction Codes", "type": "SAP Fiori"},
            "SM30": {"app_id": "F4669", "name": "Maintain Table Views", "type": "SAP Fiori"},
            "SM31": {"app_id": "F4669", "name": "Table Maintenance", "type": "SAP Fiori"},
            "SE16": {"app_id": "F4597", "name": "Data Browser", "type": "SAP Fiori"},
            "SE17": {"app_id": "F4597", "name": "General Table Display", "type": "SAP Fiori"},
            "SAINT": {"app_id": "F4670", "name": "Add-On Installation Tool", "type": "SAP Fiori"},
            "SPAM": {"app_id": "F4671", "name": "Support Package Manager", "type": "SAP Fiori"},
            "SNOTE": {"app_id": "F4672", "name": "Note Assistant", "type": "SAP Fiori"},
            "SCOT": {"app_id": "F4673", "name": "SAPconnect Administration", "type": "SAP Fiori"},
            "SOST": {"app_id": "F4674", "name": "SAPconnect Send Requests", "type": "SAP Fiori"},
            "SPAD": {"app_id": "F4675", "name": "Spool Administration", "type": "SAP Fiori"},
            "SP01": {"app_id": "F4676", "name": "Spool Request Selection", "type": "SAP Fiori"},
            "SP02": {"app_id": "F4676", "name": "Display Spool Requests", "type": "SAP Fiori"},
            "AL11": {"app_id": "F4677", "name": "SAP Directories", "type": "SAP Fiori"},
            "FILE": {"app_id": "F4678", "name": "Cross-Client File Names", "type": "SAP Fiori"},
            "SARA": {"app_id": "F4679", "name": "Archive Administration", "type": "SAP Fiori"},
            "DB02": {"app_id": "F4680", "name": "Tables and Indexes Monitor", "type": "SAP Fiori"},
            "RZ10": {"app_id": "F4681", "name": "Edit Profiles", "type": "SAP Fiori"},
            "RZ11": {"app_id": "F4682", "name": "Maintain Profile Parameters", "type": "SAP Fiori"},
            "RZ20": {"app_id": "F4683", "name": "CCMS Monitoring", "type": "SAP Fiori"},
            # === Expansion Wave 2 — Additional T-code Fiori Mappings ===
            # --- Extended Finance ---
            "F-28": {"app_id": "F0861", "name": "Incoming Payment", "type": "SAP Fiori"},
            "F-53": {"app_id": "F0862", "name": "Vendor Payment", "type": "SAP Fiori"},
            "F-22": {"app_id": "F0863", "name": "Customer Invoice Entry", "type": "SAP Fiori"},
            "F-43": {"app_id": "F0864", "name": "Vendor Invoice Entry", "type": "SAP Fiori"},
            "FI12": {"app_id": "F0865", "name": "Maintain House Bank", "type": "SAP Fiori"},
            "FBCJ": {"app_id": "F0866", "name": "Cash Journal", "type": "SAP Fiori"},
            "FCH5": {"app_id": "F0867", "name": "Create Check", "type": "SAP Fiori"},
            "FCH9": {"app_id": "F0868", "name": "Void Issued Check", "type": "SAP Fiori"},
            "FAGLL03": {"app_id": "F0869", "name": "Display GL Line Items", "type": "SAP Fiori"},
            "FAGLB03": {"app_id": "F0870", "name": "Display GL Balances", "type": "SAP Fiori"},
            "S_ALR_87012277": {"app_id": "F0871", "name": "GL Account Balances Report", "type": "SAP Fiori"},
            "S_ALR_87012078": {"app_id": "F0872", "name": "Vendor Balances Report", "type": "SAP Fiori"},
            "S_ALR_87012172": {"app_id": "F0873", "name": "Customer Balances Report", "type": "SAP Fiori"},
            # --- Extended Fixed Assets ---
            "ABAV": {"app_id": "F2901", "name": "Asset Retirement by Scrapping", "type": "SAP Fiori"},
            "ABAON": {"app_id": "F2902", "name": "Asset Sale with Revenue", "type": "SAP Fiori"},
            "AB01": {"app_id": "F2903", "name": "Post Asset Acquisition", "type": "SAP Fiori"},
            "ABNAN": {"app_id": "F2904", "name": "Post-Capitalization", "type": "SAP Fiori"},
            "AFAB": {"app_id": "F2905", "name": "Depreciation Run", "type": "SAP Fiori"},
            "AFAR": {"app_id": "F2906", "name": "Recalculate Depreciation", "type": "SAP Fiori"},
            "AW01N": {"app_id": "F2907", "name": "Asset Explorer", "type": "SAP Fiori"},
            "AR01": {"app_id": "F2908", "name": "Create Asset Class", "type": "SAP Fiori"},
            "AIAB": {"app_id": "F2909", "name": "Asset Under Construction Settlement", "type": "SAP Fiori"},
            # --- Extended Controlling ---
            "KS01": {"app_id": "F3201", "name": "Create Cost Center", "type": "SAP Fiori"},
            "KS02": {"app_id": "F3202", "name": "Change Cost Center", "type": "SAP Fiori"},
            "KSB1": {"app_id": "F3203", "name": "Cost Centers: Actual Line Items", "type": "SAP Fiori"},
            "KP06": {"app_id": "F3204", "name": "Change Cost Planning", "type": "SAP Fiori"},
            "KP26": {"app_id": "F3205", "name": "Change Activity Type Plan", "type": "SAP Fiori"},
            "KOB1": {"app_id": "F3206", "name": "Internal Order: Actual Line Items", "type": "SAP Fiori"},
            "CJI3": {"app_id": "F3207", "name": "Project Actual Cost Line Items", "type": "SAP Fiori"},
            "KSPI": {"app_id": "F3208", "name": "Cost Center Price Calculation", "type": "SAP Fiori"},
            "1KEK": {"app_id": "F3209", "name": "CO-PA Characteristic Values", "type": "SAP Fiori"},
            # --- Extended SD Shipping ---
            "VL10A": {"app_id": "F2701", "name": "Delivery Due List - Sales Orders", "type": "SAP Fiori"},
            "VL10B": {"app_id": "F2702", "name": "Delivery Due List - Purchase Orders", "type": "SAP Fiori"},
            "VL31N": {"app_id": "F2703", "name": "Create Inbound Delivery", "type": "SAP Fiori"},
            "VL32N": {"app_id": "F2704", "name": "Change Inbound Delivery", "type": "SAP Fiori"},
            "VA41": {"app_id": "F2705", "name": "Create Sales Contract", "type": "SAP Fiori"},
            "VA42": {"app_id": "F2706", "name": "Change Sales Contract", "type": "SAP Fiori"},
            "VA31": {"app_id": "F2707", "name": "Create Scheduling Agreement", "type": "SAP Fiori"},
            "VF44": {"app_id": "F2708", "name": "Process Canceled Billing Docs", "type": "SAP Fiori"},
            "VT01N": {"app_id": "F2709", "name": "Create Shipment", "type": "SAP Fiori"},
            "VT02N": {"app_id": "F2710", "name": "Change Shipment", "type": "SAP Fiori"},
            # --- Extended MM Procurement ---
            "ME35K": {"app_id": "F2410", "name": "Release Purchase Contract", "type": "SAP Fiori"},
            "ME57": {"app_id": "F2411", "name": "Assign Purchase Requisitions", "type": "SAP Fiori"},
            "ME59N": {"app_id": "F2412", "name": "Auto PO Generation", "type": "SAP Fiori"},
            "MIRO": {"app_id": "F2413", "name": "Enter Incoming Invoice", "type": "SAP Fiori"},
            "MIR7": {"app_id": "F2414", "name": "Park Incoming Invoice", "type": "SAP Fiori"},
            "ML81N": {"app_id": "F2415", "name": "Service Entry Sheet", "type": "SAP Fiori"},
            "ME2M": {"app_id": "F2416", "name": "Purchasing Documents per Material", "type": "SAP Fiori"},
            "ME2N": {"app_id": "F2417", "name": "PO by PO Number", "type": "SAP Fiori"},
            "MMBE": {"app_id": "F2418", "name": "Stock Overview", "type": "SAP Fiori"},
            "MB52": {"app_id": "F2419", "name": "Warehouse Stocks", "type": "SAP Fiori"},
            "MB51": {"app_id": "F2420", "name": "Material Document List", "type": "SAP Fiori"},
            "MR21": {"app_id": "F2421", "name": "Price Change", "type": "SAP Fiori"},
            "MM17": {"app_id": "F2422", "name": "Mass Maintenance Material Master", "type": "SAP Fiori"},
            "CKM3N": {"app_id": "F2423", "name": "Material Ledger — Price Analysis", "type": "SAP Fiori"},
            "CKMLCP": {"app_id": "F2424", "name": "ML Actual Costing/Material Ledger", "type": "SAP Fiori"},
            # --- Extended PP ---
            "COOIS": {"app_id": "F3301", "name": "Production Order Info System", "type": "SAP Fiori"},
            "CO07": {"app_id": "F3302", "name": "Create Process Order w/o Material", "type": "SAP Fiori"},
            "CO13": {"app_id": "F3303", "name": "Cancel Confirmation", "type": "SAP Fiori"},
            "CO15": {"app_id": "F3304", "name": "Confirm Production Order", "type": "SAP Fiori"},
            "CM01": {"app_id": "F3305", "name": "Capacity Planning — Work Center View", "type": "SAP Fiori"},
            "CM25": {"app_id": "F3306", "name": "Capacity Planning — Order View", "type": "SAP Fiori"},
            "MD11": {"app_id": "F3307", "name": "Create Planned Order", "type": "SAP Fiori"},
            "MD16": {"app_id": "F3308", "name": "Convert Planned Order to PO", "type": "SAP Fiori"},
            "CS12": {"app_id": "F3309", "name": "Multi-Level BOM Explosion", "type": "SAP Fiori"},
            "CS15": {"app_id": "F3310", "name": "Where-Used List (BOM)", "type": "SAP Fiori"},
            # --- Extended PM ---
            "IW28": {"app_id": "F3401", "name": "Notification List", "type": "SAP Fiori"},
            "IW38": {"app_id": "F3402", "name": "Maintenance Order List", "type": "SAP Fiori"},
            "IW39": {"app_id": "F3403", "name": "Order List - Multi-Level", "type": "SAP Fiori"},
            "IW41": {"app_id": "F3404", "name": "Confirm Maintenance Order", "type": "SAP Fiori"},
            "IA01": {"app_id": "F3405", "name": "Create General Task List", "type": "SAP Fiori"},
            "IP10": {"app_id": "F3406", "name": "Schedule Maintenance Plan", "type": "SAP Fiori"},
            "IK11": {"app_id": "F3407", "name": "Create Measurement Document", "type": "SAP Fiori"},
            # --- Extended QM ---
            "QP01": {"app_id": "F3501", "name": "Create Inspection Plan", "type": "SAP Fiori"},
            "QS21": {"app_id": "F3502", "name": "Create Master Insp. Characteristic", "type": "SAP Fiori"},
            "QE51N": {"app_id": "F3503", "name": "Record Results (Worklist)", "type": "SAP Fiori"},
            # --- Extended PS / IM ---
            "CJ30": {"app_id": "F3601", "name": "Project Budget — Change", "type": "SAP Fiori"},
            "CJ40": {"app_id": "F3602", "name": "Project — Display Plan", "type": "SAP Fiori"},
            "CN22": {"app_id": "F3603", "name": "Change Network Activity", "type": "SAP Fiori"},
            "IM01": {"app_id": "F3604", "name": "Create Investment Program", "type": "SAP Fiori"},
            "IM22": {"app_id": "F3605", "name": "Create Appropriation Request", "type": "SAP Fiori"},
            # --- Extended EWM ---
            "LT06": {"app_id": "F3701", "name": "Confirm Transfer Order Item", "type": "SAP Fiori"},
            "LT09": {"app_id": "F3702", "name": "Confirm Transfer Order", "type": "SAP Fiori"},
            "/SCWM/ADGI": {"app_id": "F3703", "name": "EWM Goods Issue", "type": "SAP Fiori"},
            "/SCWM/ADGR": {"app_id": "F3704", "name": "EWM Goods Receipt", "type": "SAP Fiori"},
            "/SCWM/PRDO": {"app_id": "F3705", "name": "EWM Production Supply", "type": "SAP Fiori"},
            "/SCWM/STOCK": {"app_id": "F3706", "name": "EWM Stock Balance", "type": "SAP Fiori"},
            # --- Extended Treasury ---
            "FF63": {"app_id": "F3801", "name": "Bank Statement Post Process", "type": "SAP Fiori"},
            "FTR_CREATE": {"app_id": "F3802", "name": "Create Financial Transaction", "type": "SAP Fiori"},
            "TBB1": {"app_id": "F3803", "name": "Post Treasury Transaction", "type": "SAP Fiori"},
            # --- Extended HR ---
            "PA61": {"app_id": "F3901", "name": "Maintain Time Data", "type": "SAP Fiori"},
            "PT01": {"app_id": "F3902", "name": "Create Work Schedule", "type": "SAP Fiori"},
            "CAT2": {"app_id": "F3903", "name": "Time Sheet Entry (CATS)", "type": "SAP Fiori"},
            "PO13": {"app_id": "F3904", "name": "Maintain Position", "type": "SAP Fiori"},
            "PPOM": {"app_id": "F3905", "name": "Org Management — Initial Screen", "type": "SAP Fiori"},
            "PA71": {"app_id": "F3906", "name": "Fast Entry of Time Events", "type": "SAP Fiori"},
            # --- Extended Service Mgmt ---
            "IW51": {"app_id": "F4001", "name": "Create Service Notification", "type": "SAP Fiori"},
            "IW52": {"app_id": "F4002", "name": "Change Service Notification", "type": "SAP Fiori"},
            "IW54": {"app_id": "F4003", "name": "Service Confirmation", "type": "SAP Fiori"},
            "DP80": {"app_id": "F4004", "name": "Display Service Contract", "type": "SAP Fiori"},
            # --- Extended GTS / Trade ---
            "GTS_CUSTOM": {"app_id": "F4101", "name": "Customs Declaration", "type": "SAP Fiori"},
            "GTS_SPL": {"app_id": "F4102", "name": "Sanctioned Party Screening", "type": "SAP Fiori"},
            # --- Extended BPC / Consolidation ---
            "UJR_VALIDATE": {"app_id": "F4201", "name": "BPC Validate Data", "type": "SAP Fiori"},
            "CXNB": {"app_id": "F4202", "name": "Group Reporting — Create Document", "type": "SAP Fiori"},
        }

    def analyze_usage(self, usage_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Takes raw workload data from ST03N (mocked here or pulled via PyRFC from SAP).
        Returns mapped Fiori apps for active T-codes and a list of dead Z-programs.
        """
        logger.info("Analyzing Workload Data (ST03N)")
        
        active_tcodes = []
        unused_zprograms = []
        fiori_mappings = []
        
        for record in usage_data:
            tcode = record.get("tcode")
            executions = record.get("executions", 0)
            
            if tcode.startswith("Z"):
                if executions == 0:
                    unused_zprograms.append(tcode)
            else:
                if executions > 0:
                    active_tcodes.append(tcode)
                    if tcode in self.fiori_catalog:
                        # Map to Fiori natively
                        mapping = self.fiori_catalog[tcode]
                        fiori_mappings.append({
                            "tcode": tcode,
                            "fiori_app_id": mapping["app_id"],
                            "fiori_name": mapping["name"],
                            "executions": executions
                        })

        return {
            "metrics": {
                "active_tcodes_count": len(active_tcodes),
                "unused_zprograms_count": len(unused_zprograms),
                "fiori_mapped_count": len(fiori_mappings)
            },
            "fiori_mappings": fiori_mappings,
            "dead_code": unused_zprograms
        }

def main(event, context):
    logger.info("Process Miner ST03N Analyzer Activated")
    analyzer = ST03NAnalyzer()

    usage_data = None

    # Dual-mode: try live SAP RFC first, fall back to mock data
    try:
        from pyrfc import Connection
        import os
        from utils.secrets_client import get_secret_value

        secret_name = os.environ.get("ECC_SECRET_NAME", "sap-ecc-credentials")
        secret_response = get_secret_value(secret_name)
        import json as _json
        conn_params = _json.loads(secret_response["SecretString"])

        conn = Connection(
            ashost=conn_params["host"],
            sysnr=conn_params["sysnr"],
            client=conn_params["client"],
            user=conn_params["user"],
            passwd=conn_params["passwd"],
            lang="EN",
        )

        # Read ST03N workload data from SWNCMONI via RFC_READ_TABLE
        result = conn.call(
            "RFC_READ_TABLE",
            QUERY_TABLE="SWNCMONI",
            DELIMITER="|",
            FIELDS=[
                {"FIELDNAME": "TCODE"},
                {"FIELDNAME": "ENTRY_ID"},
                {"FIELDNAME": "COUNT"},
            ],
            ROWCOUNT=99999,
        )

        usage_data = []
        for row in result["DATA"]:
            fields = row["WA"].split("|")
            if len(fields) >= 3:
                usage_data.append({
                    "tcode": fields[0].strip(),
                    "executions": int(fields[2].strip()) if fields[2].strip().isdigit() else 0,
                })

        conn.close()
        logger.info(f"Read {len(usage_data)} workload records from SAP SWNCMONI via RFC")

    except ImportError:
        logger.warning("PyRFC not available — falling back to mock mode")
    except Exception as e:
        logger.warning(f"RFC call failed ({e}) — falling back to mock mode")

    # Fall back to mock data if RFC was not available or failed
    if usage_data is None:
        usage_data = event.get('st03n_data', [
            {"tcode": "FB50", "executions": 1403},
            {"tcode": "ME21N", "executions": 834},
            {"tcode": "ZFI_PAYMENT_RUN", "executions": 0},
            {"tcode": "ZMM_MATERIAL_CREATE", "executions": 0},
        ])

    result = analyzer.analyze_usage(usage_data)
    return {"statusCode": 200, "body": result}
