"""
global_config_framework.py - Dynamic Localization Rules Engine (Stage 4)
Replaces hard-coded India-only focus. Queries Cosmos DB to apply country-specific
SPRO configurations dynamically based on the target Company Code (BUKRS).

Covers 55+ company codes across 50+ countries with comprehensive compliance
modules for tax, payroll, e-invoicing, and regulatory reporting in each region.
"""
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("global_config_framework")
logger.setLevel(logging.INFO)

# =============================================================================
# COMPANY CODE -> COUNTRY MAPPING
# Typically queried from T001 table dynamically via pyRFC. This is the mock
# mapping covering the full enterprise landscape.
# =============================================================================
COMPANY_CODE_REGIONS = {
    "1000": "DE",  # Germany HQ
    "1100": "DE",  # Germany Manufacturing
    "1200": "AE",  # UAE Operations
    "2000": "US",  # United States
    "2100": "US",  # US West Coast
    "3000": "BR",  # Brazil
    "3100": "BR",  # Brazil Manufacturing
    "4000": "IN",  # India HQ
    "4100": "IN",  # India Plant 2
    "4200": "IN",  # India Plant 3
    "5000": "GB",  # United Kingdom
    "5100": "FR",  # France
    "5200": "IT",  # Italy
    "5300": "ES",  # Spain
    "6000": "CN",  # China
    "6100": "JP",  # Japan
    "6200": "KR",  # South Korea
    "7000": "AU",  # Australia
    "7100": "ZA",  # South Africa
    "8000": "MX",  # Mexico
    "8100": "CA",  # Canada
    "9000": "SA",  # Saudi Arabia
    "9100": "SG",  # Singapore
    "9200": "PL",  # Poland
    # ---- Southeast Asia ----
    "TH01": "TH",  # Thailand
    "ID01": "ID",  # Indonesia
    "MY01": "MY",  # Malaysia
    "PH01": "PH",  # Philippines
    "VN01": "VN",  # Vietnam
    # ---- East Asia & Hong Kong ----
    "TW01": "TW",  # Taiwan
    "HK01": "HK",  # Hong Kong
    # ---- Europe (additional) ----
    "CH01": "CH",  # Switzerland
    "AT01": "AT",  # Austria
    "BE01": "BE",  # Belgium
    "DK01": "DK",  # Denmark
    "SE01": "SE",  # Sweden
    "NO01": "NO",  # Norway
    "FI02": "FI",  # Finland (FI02 to avoid conflict with FI module prefix)
    "IE01": "IE",  # Ireland
    "PT01": "PT",  # Portugal
    "GR01": "GR",  # Greece
    "CZ01": "CZ",  # Czech Republic
    "HU01": "HU",  # Hungary
    "RO01": "RO",  # Romania
    "TR01": "TR",  # Turkey
    # ---- Latin America (additional) ----
    "AR01": "AR",  # Argentina
    "CL01": "CL",  # Chile
    "CO02": "CO",  # Colombia (CO02 to avoid conflict with CO module prefix)
    "PE01": "PE",  # Peru
    # ---- Oceania ----
    "NZ01": "NZ",  # New Zealand
    # ---- Africa (additional) ----
    "NG01": "NG",  # Nigeria
    "KE01": "KE",  # Kenya
    "EG01": "EG",  # Egypt
    # ---- Europe (Baltics, Balkans, expanded) ----
    "HR01": "HR",  # Croatia
    "BG01": "BG",  # Bulgaria
    "SI01": "SI",  # Slovenia
    "LT01": "LT",  # Lithuania
    "LV01": "LV",  # Latvia
    "EE01": "EE",  # Estonia
    "LU01": "LU",  # Luxembourg
    "SK01": "SK",  # Slovakia
}

# =============================================================================
# COUNTRY COMPLIANCE MODULES
# Each country maps to the list of compliance module codes that must be
# activated in SPRO during an S/4HANA migration for that jurisdiction.
# =============================================================================
COUNTRY_COMPLIANCE_MODULES: Dict[str, List[str]] = {
    "IN": [
        "GST_SETUP", "TDS_CONFIG", "E_INVOICE_API", "E_WAY_BILL", "PAN_VALIDATION",
        "GSTIN_VALIDATION", "HSN_SAC_CODES", "GSTR_FILING", "PF_ESI_CONFIG",
        "PROFESSIONAL_TAX", "AADHAAR_INTEGRATION", "TCS_SETUP", "RCM_CONFIG", "ITC_RULES",
    ],
    "US": [
        "SALES_USE_TAX", "VERTEX_INTEGRATION_PARAMS", "SOX_AUDIT_LOGGING", "GAAP_GL_ACCOUNTS",
        "FORM_1099_REPORTING", "OFAC_SCREENING", "W2_W4_W9_FORMS", "FICA_FUTA_TAX",
        "ACH_EDI_PAYMENTS", "ASC_842_LEASES", "ASC_606_REVENUE", "STATE_PAYROLL_TAX",
        "FATCA_REPORTING", "ECONOMIC_NEXUS",
    ],
    "DE": [
        "GOBD_COMPLIANCE", "EU_GDPR_RETENTION", "DATEV_EXPORT", "SEPA_PAYMENTS",
        "HGB_RETENTION", "ELSTER_FILING", "UST_VA_RETURN", "INTRASTAT_REPORTING",
        "GERMAN_PAYROLL_SI", "E_BILANZ", "KASSENSICHV_TSE",
    ],
    "BR": [
        "NOTA_FISCAL_ELETRONICA", "SPED_REPORTING", "ICMS_TAX_CONFIG",
        "PIS_COFINS_CONFIG", "CNPJ_CPF_VALIDATION", "NCM_PRODUCT_CODES",
        "CFOP_OPERATION_CODES", "IRRF_WITHHOLDING", "DARF_PAYMENT",
        "ESOCIAL_REPORTING", "EFD_REINF", "J_1B_TABLES",
    ],
    "CN": [
        "GOLDEN_TAX_INTERFACE", "FAPIAO_INVOICING", "VAT_REFORM_MULTI_RATE",
        "CIT_CORPORATE_INCOME", "CHINESE_GAAP_CAS", "GBT_STANDARDS",
        "SOCIAL_INSURANCE_FUND", "RMB_HANDLING", "BANK_TAX_INTEGRATION",
        "CHINESE_E_INVOICE",
    ],
    "GB": [
        "MTD_VAT", "UK_VAT_RATES", "PAYE_RTI", "BREXIT_CUSTOMS",
        "FRS_ACCOUNTING", "BACS_FASTER_PAYMENTS", "CIS_CONSTRUCTION",
        "AUTO_ENROLMENT_PENSION", "IR35_OFFPAYROLL", "PLASTIC_PACKAGING_TAX",
    ],
    "AE": [
        "UAE_VAT_5PCT", "TRN_REGISTRATION", "FREE_ZONE_VAT",
        "WAGE_PROTECTION_SYSTEM", "EOSB_GRATUITY", "GOSI_INSURANCE",
    ],
    "SA": [
        "ZATCA_ZAKAT_TAX", "FATOORA_E_INVOICING", "SA_VAT",
        "WPS_SAUDI", "GOSI_SAUDI", "NITAQAT_COMPLIANCE",
    ],
    "JP": [
        "CONSUMPTION_TAX_INVOICE", "REDUCED_TAX_RATE_8_10", "E_TAX_FILING",
        "SOCIAL_INSURANCE_JP", "J_1J_TABLES", "ZENGIN_PAYMENT",
        "YEAR_END_ADJUSTMENT", "MY_NUMBER_HANDLING",
    ],
    "AU": [
        "BAS_GST_REPORTING", "STP_PHASE2", "SUPERANNUATION_GUARANTEE",
        "ABN_VALIDATION", "PAYG_WITHHOLDING", "TPAR_REPORTING",
        "FBT_FRINGE_BENEFITS", "WORKCOVER_PREMIUMS",
    ],
    "FR": [
        "FEC_ACCOUNTING", "DSN_PAYROLL", "TVA_DECLARATION",
        "CHORUS_PRO_FACTURX", "SIRET_SIREN_VALIDATION", "DEB_DES_TRADE",
        "PRELEVEMENT_SOURCE", "CET_CVAE_LOCAL_TAX",
    ],
    "MX": [
        "CFDI_COMPLIANCE", "SAT_REPORTING", "RFC_TAX_ID",
        "IVA_ISR_TAXES", "J_1M_TABLES", "NOMINA_PAYROLL",
    ],
    "IT": [
        "FATTURA_ELETTRONICA_SDI", "ESTEROMETRO", "ITALIAN_TAX_CODES",
        "WITHHOLDING_CERTIFICATES", "J_1I_PROGRAMS", "CIGO_CIGS_PAYROLL",
    ],
    "KR": [
        "E_TAX_INVOICE_KR", "K_IFRS", "BIZ_REGISTRATION",
        "J_3K_TABLES", "KR_PAYROLL_NTS",
    ],
    "ZA": [
        "SARS_COMPLIANCE", "VAT_201_EMP_201", "BBBEE_REPORTING",
        "UIF_SDL_LEVIES", "ZA_PAYROLL_TAX",
    ],
    "PL": [
        "JPK_SAF_T", "SPLIT_PAYMENT_MECHANISM", "NIP_VALIDATION",
        "KSEF_E_INVOICING", "PL_VAT_RATES",
    ],
    "EU": [
        "INTRASTAT_EU", "OSS_IOSS_VAT", "GDPR_DATA_RETENTION",
        "REVERSE_CHARGE_MECHANISM", "PEPPOL_E_INVOICING",
    ],
    "CA": [
        "GST_HST_CANADA", "T4_RL1_REPORTING", "BN_BUSINESS_NUMBER",
        "PROVINCIAL_TAX", "CPP_EI_DEDUCTIONS",
    ],
    "SG": [
        "GST_IRAS_SG", "PEPPOL_INVOICENOW", "SG_PAYROLL",
        "CPF_CONTRIBUTIONS", "IRAS_FILING",
    ],
    "ES": [
        "SII_SUMINISTRO", "MODELO_303_VAT", "SPANISH_PAYROLL",
        "IRPF_WITHHOLDING", "AEAT_FILING",
    ],
    "NL": [
        "DUTCH_VAT_BTW", "SBR_REPORTING", "DUTCH_PAYROLL",
        "INTRASTAT_NL",
    ],
    # ---- Southeast Asia ----
    "TH": [
        "THAI_VAT", "THAI_WHT", "THAI_BOI", "THAI_SSF", "THAI_ETAX",
    ],
    "ID": [
        "IDN_EFAKTUR", "IDN_PPH21", "IDN_PPH23", "IDN_BPJS", "IDN_CUSTOMS",
    ],
    "MY": [
        "MYS_SST", "MYS_EINVOICE", "MYS_EPF", "MYS_SOCSO", "MYS_PCB",
    ],
    "PH": [
        "PHL_BIR", "PHL_EWT", "PHL_SSS", "PHL_PHIC", "PHL_PAGIBIG",
    ],
    "VN": [
        "VNM_EINVOICE", "VNM_PIT", "VNM_SI", "VNM_FCT", "VNM_TP",
    ],
    # ---- East Asia & Hong Kong ----
    "TW": [
        "TWN_GUI", "TWN_VAT", "TWN_NHI", "TWN_LABOR", "TWN_XBRL",
    ],
    "HK": [
        "HKG_PROFITS_TAX", "HKG_MPF", "HKG_IRD", "HKG_STAMP_DUTY",
    ],
    # ---- Europe (additional) ----
    "CH": [
        "CHE_VAT", "CHE_QRBILL", "CHE_AHV", "CHE_BVG", "CHE_GAAP_FER",
    ],
    "AT": [
        "AUT_VAT", "AUT_FINANZONLINE", "AUT_SV", "AUT_REGISTRIERKASSE",
    ],
    "BE": [
        "BEL_VAT", "BEL_CODA", "BEL_DIMONA", "BEL_PEPPOL", "BEL_ONSS",
    ],
    "DK": [
        "DNK_VAT", "DNK_NEMHANDEL", "DNK_ATP", "DNK_SKAT",
    ],
    "SE": [
        "SWE_VAT", "SWE_PEPPOL", "SWE_SKATTEVERKET", "SWE_SAFT",
    ],
    "NO": [
        "NOR_VAT", "NOR_SAFT", "NOR_ALTINN", "NOR_OTP",
    ],
    "FI": [
        "FIN_VAT", "FIN_PEPPOL", "FIN_TYEL", "FIN_VERO",
    ],
    "IE": [
        "IRL_VAT", "IRL_ROS", "IRL_PRSI", "IRL_PAYE",
    ],
    "PT": [
        "PRT_VAT", "PRT_SAFT", "PRT_ATCUD", "PRT_SS",
    ],
    "GR": [
        "GRC_VAT", "GRC_MYDATA", "GRC_EFKA", "GRC_AADE",
    ],
    "CZ": [
        "CZE_VAT", "CZE_KHDPH", "CZE_CSSZ", "CZE_EET",
    ],
    "HU": [
        "HUN_VAT", "HUN_NAV3", "HUN_KATA", "HUN_TB",
    ],
    "RO": [
        "ROU_VAT", "ROU_EFACTURA", "ROU_ETRANSPORT", "ROU_ANAF",
    ],
    "TR": [
        "TUR_VAT", "TUR_EFATURA", "TUR_EARSIV", "TUR_EDEFTER", "TUR_SGK",
    ],
    # ---- Latin America (additional) ----
    "AR": [
        "ARG_IVA", "ARG_AFIP", "ARG_SUSS", "ARG_PERCEP", "ARG_RETEN",
    ],
    "CL": [
        "CHL_IVA", "CHL_SII", "CHL_AFP", "CHL_LIBRO",
    ],
    "CO": [
        "COL_IVA", "COL_DIAN", "COL_EPS", "COL_AFP",
    ],
    "PE": [
        "PER_IGV", "PER_SUNAT", "PER_ONP", "PER_AFP", "PER_PLE",
    ],
    # ---- Oceania (additional) ----
    "NZ": [
        "NZL_GST", "NZL_IRD", "NZL_KIWISAVER", "NZL_PAYDAY",
    ],
    # ---- Africa (additional) ----
    "NG": [
        "NGA_VAT", "NGA_FIRS", "NGA_PENCOM", "NGA_TIN",
    ],
    "KE": [
        "KEN_VAT", "KEN_TIMS", "KEN_NHIF", "KEN_NSSF", "KEN_ITAX",
    ],
    "EG": [
        "EGY_VAT", "EGY_ETA", "EGY_SI", "EGY_UNIFIED_TAX",
    ],
    # ---- Europe (Baltics, Balkans, expanded) ----
    "HR": [
        "HRV_VAT", "HRV_FISKALIZACIJA", "HRV_HZZO", "HRV_JOPPD",
    ],
    "BG": [
        "BGR_VAT", "BGR_NSSI", "BGR_NAP", "BGR_EFAKTURA",
    ],
    "SI": [
        "SVN_VAT", "SVN_FURS", "SVN_ERACUN", "SVN_ZPIZ",
    ],
    "LT": [
        "LTU_VAT", "LTU_ISAF", "LTU_SODRA", "LTU_VMI",
    ],
    "LV": [
        "LVA_VAT", "LVA_VID", "LVA_VSAOI", "LVA_EADDRESS",
    ],
    "EE": [
        "EST_VAT", "EST_EMTA", "EST_TSD", "EST_EARVELDUS",
    ],
    "LU": [
        "LUX_VAT", "LUX_ECDF", "LUX_CNS", "LUX_PEPPOL",
    ],
    "SK": [
        "SVK_VAT", "SVK_EKASA", "SVK_SP", "SVK_FINSTAT",
    ],
}

# Countries that are EU member states — they get EU-wide modules in addition
# to their country-specific ones.
EU_MEMBER_STATES = {
    "DE", "FR", "IT", "ES", "NL", "PL",
    "AT", "BE", "DK", "SE", "FI", "IE", "PT", "GR", "CZ", "HU", "RO",
    "HR", "BG", "SI", "LT", "LV", "EE", "LU", "SK",
}

# =============================================================================
# MODULE DETAILS
# Comprehensive mapping of every compliance module code to its human-readable
# description, the primary SAP transaction used for configuration, and
# implementation notes relevant to S/4HANA migration.
# =============================================================================
MODULE_DETAILS: Dict[str, Dict[str, str]] = {
    # ---- India (IN) ----
    "GST_SETUP": {
        "description": "Goods and Services Tax configuration — tax procedures, condition types (JIIG, JICG, JISG), and tax code mapping",
        "sap_transaction": "SPRO > Tax on Goods Movements > India > GST",
        "implementation_notes": "Requires TAXINN procedure. Map all CGST/SGST/IGST condition types. Verify HSN-based determination.",
    },
    "TDS_CONFIG": {
        "description": "Tax Deducted at Source — withholding tax types, codes, and certificate generation per Section 194/195",
        "sap_transaction": "SPRO > Financial Accounting > Withholding Tax > Extended Withholding Tax",
        "implementation_notes": "Configure both classic and extended WHT. Map TDS sections to WHT types. Ensure challan 281 setup.",
    },
    "E_INVOICE_API": {
        "description": "E-Invoicing API integration with NIC/IRP portal for B2B invoice registration and IRN generation",
        "sap_transaction": "SPRO > India Localization > E-Invoice",
        "implementation_notes": "Requires API credentials from NIC. Configure JSON payload mapping. Handle IRN cancellation within 24h window.",
    },
    "E_WAY_BILL": {
        "description": "E-Way Bill generation for goods transport exceeding INR 50,000 threshold",
        "sap_transaction": "SPRO > India Localization > E-Way Bill",
        "implementation_notes": "Integrate with NIC API. Auto-generate on delivery note. Validate Part A/B data. Handle multi-vehicle scenarios.",
    },
    "PAN_VALIDATION": {
        "description": "Permanent Account Number validation for vendors and customers during master data creation",
        "sap_transaction": "XK01/XD01 > Tax Information",
        "implementation_notes": "Validate PAN format (AAAAA0000A). Cross-check with GSTIN 3rd-12th characters. Block posting without valid PAN.",
    },
    "GSTIN_VALIDATION": {
        "description": "GSTIN (15-digit) validation and state code cross-referencing for all business partners",
        "sap_transaction": "SPRO > India Localization > GSTIN Setup",
        "implementation_notes": "Validate checksum digit. Match state code to plant/customer state. Support SEZ and composition dealers.",
    },
    "HSN_SAC_CODES": {
        "description": "Harmonized System of Nomenclature / Service Accounting Codes for GST rate determination",
        "sap_transaction": "SPRO > Logistics General > Tax on Goods Movements > India > HSN/SAC",
        "implementation_notes": "Maintain HSN at material master level. SAC codes for service materials. Map to correct GST rate slabs (5/12/18/28%).",
    },
    "GSTR_FILING": {
        "description": "GSTR-1, GSTR-2A/2B reconciliation, and GSTR-3B return data extraction",
        "sap_transaction": "J1IGSTR / Custom Z-reports",
        "implementation_notes": "Extract outward supply data for GSTR-1. Reconcile inward supplies with GSTR-2A. Compute net liability for GSTR-3B.",
    },
    "PF_ESI_CONFIG": {
        "description": "Provident Fund and Employee State Insurance payroll deduction configuration",
        "sap_transaction": "SPRO > Payroll India > PF/ESI",
        "implementation_notes": "Configure PF wage ceiling (INR 15,000). ESI threshold (INR 21,000). Handle voluntary PF contributions. UAN integration.",
    },
    "PROFESSIONAL_TAX": {
        "description": "State-wise Professional Tax slab configuration for payroll deduction",
        "sap_transaction": "SPRO > Payroll India > Professional Tax",
        "implementation_notes": "Different slabs per state (MH, KA, WB, etc.). Monthly deduction. Annual max INR 2,500. Maintain state-wise tables.",
    },
    "AADHAAR_INTEGRATION": {
        "description": "Aadhaar number storage and validation for employee/vendor KYC compliance",
        "sap_transaction": "PA30 Infotype 0185 / Custom",
        "implementation_notes": "Store encrypted. Validate 12-digit format with Verhoeff checksum. Link to PAN for Income Tax compliance.",
    },
    "TCS_SETUP": {
        "description": "Tax Collected at Source configuration for sellers under Section 206C",
        "sap_transaction": "SPRO > Financial Accounting > Withholding Tax > TCS",
        "implementation_notes": "Configure TCS on sale of goods exceeding INR 50 lakh. Different rates per category. Quarterly TCS return.",
    },
    "RCM_CONFIG": {
        "description": "Reverse Charge Mechanism configuration for specified goods/services under GST",
        "sap_transaction": "SPRO > India Localization > GST > Reverse Charge",
        "implementation_notes": "Identify RCM-applicable supplies. Auto-post input/output tax. Handle partial RCM. Monthly ITC claim.",
    },
    "ITC_RULES": {
        "description": "Input Tax Credit eligibility rules, blocked credits, and proportionate ITC reversal",
        "sap_transaction": "SPRO > India Localization > GST > ITC Rules",
        "implementation_notes": "Implement Rule 42/43 for proportionate reversal. Block ITC on specified items (motor vehicles, food, etc.).",
    },

    # ---- United States (US) ----
    "SALES_USE_TAX": {
        "description": "Multi-jurisdiction sales and use tax determination across 11,000+ US tax jurisdictions",
        "sap_transaction": "SPRO > Financial Accounting > Tax on Sales/Purchases",
        "implementation_notes": "Integrate with external tax engine (Vertex/Avalara). Handle nexus rules, exemption certificates, product taxability.",
    },
    "VERTEX_INTEGRATION_PARAMS": {
        "description": "Vertex O Series tax engine integration parameters for real-time tax calculation",
        "sap_transaction": "SPRO > Tax Interface > Vertex Configuration",
        "implementation_notes": "Configure RFC to Vertex. Map SAP tax codes to Vertex. Handle tax-only adjustments. Batch vs real-time mode.",
    },
    "SOX_AUDIT_LOGGING": {
        "description": "Sarbanes-Oxley Section 404 audit trail and change logging for financial controls",
        "sap_transaction": "SM19/SM20 > Security Audit Log / SPRO > SOX Controls",
        "implementation_notes": "Enable change documents for all financial master data. Configure audit trail for journal entries. Segregation of duties.",
    },
    "GAAP_GL_ACCOUNTS": {
        "description": "US GAAP chart of accounts structure and parallel ledger configuration",
        "sap_transaction": "OB13/FS00 > Chart of Accounts",
        "implementation_notes": "Maintain US GAAP CoA. Configure parallel ledger (2L) for IFRS. Map local to group chart. ASC topic alignment.",
    },
    "FORM_1099_REPORTING": {
        "description": "IRS 1099-MISC/NEC/INT reporting for vendor payments exceeding thresholds",
        "sap_transaction": "S_P00_07000134 / RFIDYYWT",
        "implementation_notes": "Classify vendors as 1099-reportable. Maintain W-9 data. Generate 1099 forms. E-file via FIRE system. Track thresholds.",
    },
    "OFAC_SCREENING": {
        "description": "Office of Foreign Assets Control sanctions screening for vendor/customer compliance",
        "sap_transaction": "SPRO > SAP GTS > Sanctioned Party List",
        "implementation_notes": "Integrate with SAP GTS or third-party screening. Check SDN list. Block transactions on match. Maintain audit log.",
    },
    "W2_W4_W9_FORMS": {
        "description": "Employee W-2/W-4 and vendor W-9 tax form configuration and generation",
        "sap_transaction": "PC00_M10_HRF > Payroll Forms",
        "implementation_notes": "Configure W-4 withholding tables. Generate W-2 year-end. Store W-9 for vendors. Handle state equivalents.",
    },
    "FICA_FUTA_TAX": {
        "description": "Federal Insurance Contributions Act (Social Security/Medicare) and Federal Unemployment Tax",
        "sap_transaction": "SPRO > Payroll US > FICA/FUTA",
        "implementation_notes": "Configure wage base limits. Handle Additional Medicare Tax (0.9%). FUTA credit reduction states. Multi-state employees.",
    },
    "ACH_EDI_PAYMENTS": {
        "description": "Automated Clearing House electronic payment configuration with EDI 820/835 formats",
        "sap_transaction": "FBZP > Payment Methods / SPRO > Payment Medium",
        "implementation_notes": "Configure ACH payment method. Map bank formats (NACHA). Handle prenotes. EDI 820 remittance advice.",
    },
    "ASC_842_LEASES": {
        "description": "ASC 842 lease accounting — right-of-use asset and lease liability recognition",
        "sap_transaction": "SPRO > RE-FX > Lease Accounting / S/4HANA Lease Contracts",
        "implementation_notes": "Classify operating vs finance leases. Calculate ROU asset and liability. Handle modifications, remeasurements, variable payments.",
    },
    "ASC_606_REVENUE": {
        "description": "ASC 606 five-step revenue recognition model for contract-based revenue",
        "sap_transaction": "SPRO > Revenue Accounting (RAR)",
        "implementation_notes": "Configure performance obligations. Allocate transaction price. Recognize over time vs point-in-time. Handle variable consideration.",
    },
    "STATE_PAYROLL_TAX": {
        "description": "State-level income tax withholding, SUI, SDI, and local tax configuration for all 50 states",
        "sap_transaction": "SPRO > Payroll US > State Tax",
        "implementation_notes": "Maintain state withholding tables. Handle reciprocity agreements. Configure SUI rates per state. Local taxes (NYC, PA localities).",
    },
    "FATCA_REPORTING": {
        "description": "Foreign Account Tax Compliance Act reporting for foreign financial accounts",
        "sap_transaction": "Custom / GRC",
        "implementation_notes": "Identify US persons with foreign accounts. Generate FATCA reports. Handle W-8BEN forms for foreign vendors.",
    },
    "ECONOMIC_NEXUS": {
        "description": "Post-Wayfair economic nexus threshold tracking across all US states",
        "sap_transaction": "Custom / Vertex Dashboard",
        "implementation_notes": "Track revenue and transaction count per state. Alert on threshold approach ($100K/200 transactions). Auto-register for tax.",
    },

    # ---- Germany (DE) ----
    "GOBD_COMPLIANCE": {
        "description": "GoBD (Grundsaetze ordnungsmaessiger Buchfuehrung) digital record-keeping compliance",
        "sap_transaction": "SPRO > Financial Accounting > Document Management",
        "implementation_notes": "Ensure immutable audit trail. Configure document archiving per GoBD. Retention period 10 years. Verfahrensdokumentation.",
    },
    "EU_GDPR_RETENTION": {
        "description": "EU General Data Protection Regulation data retention and erasure policies",
        "sap_transaction": "SPRO > SAP ILM > Data Retention / Information Lifecycle Mgmt",
        "implementation_notes": "Configure retention periods per data class. Implement right-to-erasure. Block personal data after retention. DPIA documentation.",
    },
    "DATEV_EXPORT": {
        "description": "DATEV interface export for German tax advisors — accounting data in DATEV format",
        "sap_transaction": "RFBIDE00 / SPRO > DATEV Interface",
        "implementation_notes": "Configure DATEV export format. Map SAP accounts to DATEV SKR03/SKR04. Monthly/annual data transfer. Include header/transaction files.",
    },
    "SEPA_PAYMENTS": {
        "description": "Single Euro Payments Area credit transfer and direct debit configuration",
        "sap_transaction": "FBZP > SEPA Payment Methods / SPRO > SEPA",
        "implementation_notes": "Configure SEPA CT (pain.001) and DD (pain.008). Maintain IBAN/BIC. Handle mandate management for direct debits. SDD B2B vs CORE.",
    },
    "HGB_RETENTION": {
        "description": "Handelsgesetzbuch (German Commercial Code) document retention periods — 6/10 year rules",
        "sap_transaction": "SPRO > Document Archiving > Retention",
        "implementation_notes": "Commercial letters: 6 years. Accounting docs: 10 years. Configure archiving objects. Link to SAP ILM.",
    },
    "ELSTER_FILING": {
        "description": "ELSTER (ELektronische STeuerERklaerung) electronic tax return submission to Finanzamt",
        "sap_transaction": "SPRO > Tax Reporting > ELSTER",
        "implementation_notes": "Configure ELSTER certificate. Electronic UStVA submission. Annual returns. Integrate with ERiC library.",
    },
    "UST_VA_RETURN": {
        "description": "Umsatzsteuervoranmeldung — monthly/quarterly German VAT advance return",
        "sap_transaction": "S_ALR_87012357 / RFUMSV00",
        "implementation_notes": "Map tax codes to UStVA reporting lines. Monthly submission by 10th. Quarterly if < EUR 7,500 annual VAT.",
    },
    "INTRASTAT_REPORTING": {
        "description": "Intrastat declaration for intra-EU goods movements exceeding reporting thresholds",
        "sap_transaction": "MEIS / VE01 > Foreign Trade",
        "implementation_notes": "Configure commodity codes (CN8). Track dispatch/arrival thresholds. Monthly filing to DESTATIS. Handle triangulation.",
    },
    "GERMAN_PAYROLL_SI": {
        "description": "German social insurance — health, pension, unemployment, nursing care, and accident insurance",
        "sap_transaction": "SPRO > Payroll Germany > Social Insurance",
        "implementation_notes": "Configure contribution rates (employer/employee shares). Beitragsbemessungsgrenze limits. Mini-job and Midi-job rules.",
    },
    "E_BILANZ": {
        "description": "E-Bilanz (electronic balance sheet) XBRL taxonomy filing to tax authorities",
        "sap_transaction": "SPRO > E-Bilanz / Financial Statement Version",
        "implementation_notes": "Map GL accounts to E-Bilanz taxonomy. Generate XBRL file. HGB-Taxonomie 6.x. Mandatory fields coverage.",
    },
    "KASSENSICHV_TSE": {
        "description": "KassenSichV / TSE (Technical Security Equipment) for point-of-sale cash register compliance",
        "sap_transaction": "SPRO > POS Integration > TSE",
        "implementation_notes": "Configure TSE device connection. Sign every transaction. Generate DSFinV-K export. Cloud TSE vs hardware TSE.",
    },

    # ---- Brazil (BR) ----
    "NOTA_FISCAL_ELETRONICA": {
        "description": "NF-e (Nota Fiscal Eletronica) electronic invoice issuance and SEFAZ authorization",
        "sap_transaction": "J1BNFE / SPRO > Brazil > NF-e",
        "implementation_notes": "Configure digital certificate (A1/A3). SEFAZ communication. Handle contingency modes (DPEC, FS-DA). NF-e layout 4.0.",
    },
    "SPED_REPORTING": {
        "description": "SPED (Sistema Publico de Escrituracao Digital) — ECD, ECF, EFD-ICMS/IPI reporting",
        "sap_transaction": "J1BTAX / SPRO > Brazil > SPED",
        "implementation_notes": "Generate SPED Fiscal (EFD-ICMS/IPI). SPED Contabil (ECD). SPED ECF for corporate income tax. Block/register codes.",
    },
    "ICMS_TAX_CONFIG": {
        "description": "ICMS (Imposto sobre Circulacao de Mercadorias e Servicos) state-level tax configuration",
        "sap_transaction": "J1BTAX / SPRO > Brazil > ICMS",
        "implementation_notes": "Configure inter-state vs intra-state rates. ICMS-ST (substituicao tributaria). DIFAL calculation. Tax benefits/incentives.",
    },
    "PIS_COFINS_CONFIG": {
        "description": "PIS/COFINS federal social contribution tax — cumulative and non-cumulative regimes",
        "sap_transaction": "J1BTAX / SPRO > Brazil > PIS/COFINS",
        "implementation_notes": "Configure regime type per company. Credit calculation for non-cumulative. Map NCM to PIS/COFINS rates. EFD-Contribuicoes.",
    },
    "CNPJ_CPF_VALIDATION": {
        "description": "CNPJ (corporate) and CPF (individual) tax ID validation for all business partners",
        "sap_transaction": "XK01/XD01 > Brazil Tax Numbers",
        "implementation_notes": "Validate CNPJ (14 digits) and CPF (11 digits) check digits. Block master creation without valid ID. Inscricao Estadual.",
    },
    "NCM_PRODUCT_CODES": {
        "description": "NCM (Nomenclatura Comum do Mercosul) product classification codes for tax determination",
        "sap_transaction": "J1BTAX / MM01 > Brazil Tax Classification",
        "implementation_notes": "Maintain NCM at material master. 8-digit code. Drives IPI, PIS/COFINS, ICMS rates. Map to TIPI table.",
    },
    "CFOP_OPERATION_CODES": {
        "description": "CFOP (Codigo Fiscal de Operacoes e Prestacoes) operation codes for NF-e",
        "sap_transaction": "J1BTAX / SPRO > Brazil > CFOP",
        "implementation_notes": "4-digit codes indicating operation nature. Map SAP movement types to CFOPs. Handle returns, transfers, exports.",
    },
    "IRRF_WITHHOLDING": {
        "description": "IRRF (Imposto de Renda Retido na Fonte) income tax withholding on payments",
        "sap_transaction": "SPRO > Financial Accounting > Withholding Tax > Brazil",
        "implementation_notes": "Configure withholding rates per service type. Handle progressive table for individuals. DIRF annual declaration.",
    },
    "DARF_PAYMENT": {
        "description": "DARF (Documento de Arrecadacao de Receitas Federais) federal tax payment voucher generation",
        "sap_transaction": "J1BTAX / Custom",
        "implementation_notes": "Generate DARF for IRPJ, CSLL, PIS, COFINS, IPI. Calculate penalties and interest for late payment. Bar code generation.",
    },
    "ESOCIAL_REPORTING": {
        "description": "eSocial digital bookkeeping for labor, social security, and tax obligations",
        "sap_transaction": "SPRO > Payroll Brazil > eSocial",
        "implementation_notes": "Submit employment events (S-2200, S-1200, etc.). Real-time CAGED replacement. Configure event-driven transmission.",
    },
    "EFD_REINF": {
        "description": "EFD-Reinf (Escrituracao Fiscal Digital das Retencoes e Informacoes) withholding reporting",
        "sap_transaction": "SPRO > Brazil > EFD-Reinf",
        "implementation_notes": "Report service withholdings (R-2010, R-2020). Replaces DIRF partially. Monthly digital bookkeeping. DCTFWeb integration.",
    },
    "J_1B_TABLES": {
        "description": "SAP J_1B* Brazil localization tables maintenance — tax laws, CFOP, NCM updates",
        "sap_transaction": "J1BTAX / SM30 > J_1B* tables",
        "implementation_notes": "Maintain J_1BATL (tax law), J_1BNCM (NCM codes), J_1BCFOP (CFOP). Regular updates required for legislative changes.",
    },

    # ---- China (CN) ----
    "GOLDEN_TAX_INTERFACE": {
        "description": "Golden Tax System (Aisino/Baiwang) interface for official VAT invoice issuance",
        "sap_transaction": "SPRO > China Localization > Golden Tax",
        "implementation_notes": "Configure interface to GTS hardware/software. Map SAP billing docs to Fapiao. Handle red-letter invoices (credit notes).",
    },
    "FAPIAO_INVOICING": {
        "description": "Fapiao (official Chinese tax invoice) management — special and general VAT invoices",
        "sap_transaction": "SPRO > China > Fapiao Management",
        "implementation_notes": "Track Fapiao numbers. Distinguish special vs general VAT Fapiao. Handle electronic Fapiao. Maintain Fapiao pool allocation.",
    },
    "VAT_REFORM_MULTI_RATE": {
        "description": "China VAT multi-rate structure (13%, 9%, 6%, 0%) post-VAT reform configuration",
        "sap_transaction": "SPRO > China > VAT Configuration",
        "implementation_notes": "Configure tax codes for each rate. Map goods (13%) vs services (6%) vs transport/agriculture (9%). Handle small-scale taxpayer 3%.",
    },
    "CIT_CORPORATE_INCOME": {
        "description": "Corporate Income Tax (CIT) quarterly prepayment and annual filing configuration",
        "sap_transaction": "SPRO > China > Corporate Income Tax",
        "implementation_notes": "Standard rate 25%. High-tech enterprises 15%. Small enterprises 20%. Quarterly provisional filing. Annual reconciliation.",
    },
    "CHINESE_GAAP_CAS": {
        "description": "Chinese Accounting Standards (CAS/ASBE) chart of accounts and reporting structure",
        "sap_transaction": "OB13 / FS00 > China CoA",
        "implementation_notes": "Align to CAS chart of accounts structure. Ministry of Finance prescribed format. Parallel ledger if IFRS also required.",
    },
    "GBT_STANDARDS": {
        "description": "GB/T national standards compliance for data formats and electronic records",
        "sap_transaction": "Custom / SPRO > China",
        "implementation_notes": "GB/T 24589 for accounting informatization. Standard data format for tax bureau submission. Chinese character encoding (GB18030).",
    },
    "SOCIAL_INSURANCE_FUND": {
        "description": "Five social insurances and housing fund (wu xian yi jin) payroll configuration",
        "sap_transaction": "SPRO > Payroll China > Social Insurance",
        "implementation_notes": "Pension, medical, unemployment, work injury, maternity insurance + housing fund. City-specific base and rates. Monthly filing.",
    },
    "RMB_HANDLING": {
        "description": "RMB currency handling — SAFE reporting, forex controls, and cross-border payment rules",
        "sap_transaction": "SPRO > Treasury > China Forex",
        "implementation_notes": "Configure SAFE reporting. Handle offshore/onshore RMB. Cross-border payment documentation. FX conversion controls.",
    },
    "BANK_TAX_INTEGRATION": {
        "description": "China bank-tax integration (yin shui hu dong) for direct tax bureau bank connectivity",
        "sap_transaction": "SPRO > China > Bank-Tax Interface",
        "implementation_notes": "Configure direct connection to tax bureau via bank. Automated tax payment. Real-time status feedback. Multi-bank support.",
    },
    "CHINESE_E_INVOICE": {
        "description": "China fully digitized electronic invoice (quan dian fa piao) migration",
        "sap_transaction": "SPRO > China > E-Invoice",
        "implementation_notes": "New fully electronic Fapiao replacing paper and earlier electronic formats. Pilot cities expanding. API integration with tax bureau.",
    },

    # ---- United Kingdom (GB) ----
    "MTD_VAT": {
        "description": "Making Tax Digital for VAT — HMRC-compliant digital record keeping and API filing",
        "sap_transaction": "SPRO > UK > MTD VAT / Custom API",
        "implementation_notes": "Configure HMRC API connection (OAuth2). Digital links requirement. Quarterly VAT return via API. Error correction procedures.",
    },
    "UK_VAT_RATES": {
        "description": "UK VAT rate configuration — standard (20%), reduced (5%), zero-rated, and exempt supplies",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > UK",
        "implementation_notes": "Post-Brexit separate VAT regime. Configure tax codes per rate. Handle reverse charge for construction (DRC). Import VAT accounting.",
    },
    "PAYE_RTI": {
        "description": "Pay As You Earn Real Time Information — HMRC payroll submission each pay period",
        "sap_transaction": "SPRO > Payroll UK > RTI",
        "implementation_notes": "Submit FPS (Full Payment Submission) on or before payday. EPS for adjustments. Year-end P60. Configure tax codes and NI categories.",
    },
    "BREXIT_CUSTOMS": {
        "description": "Post-Brexit customs declarations, rules of origin, and Northern Ireland Protocol handling",
        "sap_transaction": "SPRO > Foreign Trade > UK Customs / SAP GTS",
        "implementation_notes": "Configure customs procedures for EU-UK trade. Handle UKCA marking. Northern Ireland dual status. Commodity code mapping.",
    },
    "FRS_ACCOUNTING": {
        "description": "Financial Reporting Standards (FRS 101/102) UK accounting standards compliance",
        "sap_transaction": "OB13 / Financial Statement Versions",
        "implementation_notes": "Align chart of accounts to FRS structure. Configure disclosure requirements. Small company regime (FRS 105).",
    },
    "BACS_FASTER_PAYMENTS": {
        "description": "BACS and Faster Payments Service electronic payment configuration for UK banking",
        "sap_transaction": "FBZP > UK Payment Methods",
        "implementation_notes": "Configure BACS Direct Credit (3-day cycle). Faster Payments for urgent. Sort code/account number validation. CHAPS for high-value.",
    },
    "CIS_CONSTRUCTION": {
        "description": "Construction Industry Scheme — contractor/subcontractor tax deduction and HMRC reporting",
        "sap_transaction": "SPRO > Payroll UK > CIS",
        "implementation_notes": "Verify subcontractor status with HMRC. Apply deduction rates (20%/30%/0%). Monthly CIS return. Maintain verification records.",
    },
    "AUTO_ENROLMENT_PENSION": {
        "description": "Workplace pension auto-enrolment compliance per Pensions Act 2008",
        "sap_transaction": "SPRO > Payroll UK > Pension Auto-Enrolment",
        "implementation_notes": "Assess eligible jobholders. Minimum contributions (employer 3%, total 8%). Opt-out window. Re-enrolment every 3 years.",
    },
    "IR35_OFFPAYROLL": {
        "description": "IR35 off-payroll working rules for contractors operating through intermediaries",
        "sap_transaction": "SPRO > Payroll UK > IR35",
        "implementation_notes": "Status determination statements. Deemed employer responsibilities. Apply PAYE/NIC if inside IR35. CEST tool integration.",
    },
    "PLASTIC_PACKAGING_TAX": {
        "description": "UK Plastic Packaging Tax (GBP 210.82/tonne) for packaging with <30% recycled content",
        "sap_transaction": "SPRO > UK > Environmental Tax",
        "implementation_notes": "Track plastic packaging components. Calculate recycled content percentage. Quarterly returns to HMRC. De minimis 10 tonnes.",
    },

    # ---- UAE (AE) ----
    "UAE_VAT_5PCT": {
        "description": "UAE Value Added Tax at 5% — standard rate configuration and exempt/zero-rated supplies",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > UAE",
        "implementation_notes": "Configure 5% standard rate, zero-rated (exports, healthcare, education), and exempt (bare land, local transport). Quarterly filing.",
    },
    "TRN_REGISTRATION": {
        "description": "Tax Registration Number (TRN) validation and maintenance for UAE VAT compliance",
        "sap_transaction": "XK01/XD01 > Tax Information",
        "implementation_notes": "15-digit TRN validation. Mandatory on all tax invoices. Maintain in vendor/customer master. FTA portal cross-check.",
    },
    "FREE_ZONE_VAT": {
        "description": "Designated Zone (Free Zone) VAT treatment — out-of-scope supplies configuration",
        "sap_transaction": "SPRO > UAE > Free Zone VAT",
        "implementation_notes": "Configure designated zones as outside UAE VAT scope for goods. Services still subject to VAT. Transfer of goods between zones.",
    },
    "WAGE_PROTECTION_SYSTEM": {
        "description": "WPS (Wage Protection System) — MOHRE-mandated salary payment through approved agents",
        "sap_transaction": "SPRO > Payroll UAE > WPS",
        "implementation_notes": "All salaries via WPS-approved banks/exchange houses. SIF file format. Monthly compliance. MOHRE reporting.",
    },
    "EOSB_GRATUITY": {
        "description": "End of Service Benefits (Gratuity) calculation per UAE Labour Law",
        "sap_transaction": "SPRO > Payroll UAE > Gratuity",
        "implementation_notes": "21 days basic salary/year (first 5 years). 30 days/year thereafter. Max 2 years total salary. Handle limited vs unlimited contracts.",
    },
    "GOSI_INSURANCE": {
        "description": "UAE social insurance (GPSSA) for national employees — pension and retirement",
        "sap_transaction": "SPRO > Payroll UAE > GPSSA",
        "implementation_notes": "GCC nationals: employer 15%, employee 5%. Abu Dhabi pension fund. Configure contribution base. Monthly filing.",
    },

    # ---- Saudi Arabia (SA) ----
    "ZATCA_ZAKAT_TAX": {
        "description": "ZATCA (Zakat, Tax and Customs Authority) Zakat for Saudi-owned and income tax for foreign-owned entities",
        "sap_transaction": "SPRO > Saudi Arabia > ZATCA",
        "implementation_notes": "Zakat at 2.5% on Zakat base. CIT at 20% for foreign. Mixed ownership proration. Quarterly provisional. Annual filing.",
    },
    "FATOORA_E_INVOICING": {
        "description": "ZATCA Fatoora e-invoicing (Phase 1 generation, Phase 2 integration with ZATCA portal)",
        "sap_transaction": "SPRO > Saudi Arabia > E-Invoicing / Fatoora",
        "implementation_notes": "Phase 1: Generate XML/PDF-A3. Phase 2: Real-time clearance via ZATCA API. QR code with TLV encoding. UUID per invoice.",
    },
    "SA_VAT": {
        "description": "Saudi Arabia VAT at 15% — standard rate configuration and exempt supplies",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Saudi",
        "implementation_notes": "Configure 15% standard rate. Zero-rated (exports, international transport). Exempt (financial services, residential rent). Quarterly returns.",
    },
    "WPS_SAUDI": {
        "description": "Saudi Wage Protection System — GOSI/HRDF mandated salary disbursement tracking",
        "sap_transaction": "SPRO > Payroll Saudi > WPS",
        "implementation_notes": "Bank file format for salary transfers. GOSI compliance check. Nitaqat score impact. Monthly submission deadline.",
    },
    "GOSI_SAUDI": {
        "description": "Saudi GOSI (General Organization for Social Insurance) — pension and OHRP contributions",
        "sap_transaction": "SPRO > Payroll Saudi > GOSI",
        "implementation_notes": "Saudi employees: 9.75% employer + 9.75% employee (pension). OHRP: 2% employer. Non-Saudi: 2% employer OHRP only. Monthly filing.",
    },
    "NITAQAT_COMPLIANCE": {
        "description": "Nitaqat Saudization program — workforce nationalization quotas and reporting",
        "sap_transaction": "SPRO > Saudi > Nitaqat / Custom HR Reports",
        "implementation_notes": "Track Saudi vs non-Saudi headcount. Maintain Nitaqat band (Platinum/Green/Yellow/Red). Impact on work visa issuance.",
    },

    # ---- Japan (JP) ----
    "CONSUMPTION_TAX_INVOICE": {
        "description": "Qualified Invoice System (tekikaku seikyusho) for consumption tax credit claims from Oct 2023",
        "sap_transaction": "SPRO > Japan > Qualified Invoice",
        "implementation_notes": "Register as Qualified Invoice Issuer. Include registration number on invoices. Transitional measures for non-registered.",
    },
    "REDUCED_TAX_RATE_8_10": {
        "description": "Japan dual consumption tax rate — standard 10% and reduced 8% for food/newspapers",
        "sap_transaction": "SPRO > Japan > Consumption Tax Rates",
        "implementation_notes": "Configure 10% standard and 8% reduced rates. Food/beverages (excl. alcohol, dining out) at 8%. Newspaper subscriptions 8%.",
    },
    "E_TAX_FILING": {
        "description": "e-Tax electronic filing for corporate tax, consumption tax, and withholding tax returns",
        "sap_transaction": "SPRO > Japan > e-Tax",
        "implementation_notes": "Configure e-Tax certificate. eLTAX for local taxes. XML format submission. Handle interim and final returns.",
    },
    "SOCIAL_INSURANCE_JP": {
        "description": "Japanese social insurance — health, pension (Kosei Nenkin), employment, and workers compensation",
        "sap_transaction": "SPRO > Payroll Japan > Social Insurance",
        "implementation_notes": "Health insurance and Kosei Nenkin premiums based on standard monthly remuneration. Annual grade update (Santei). Bonus reporting.",
    },
    "J_1J_TABLES": {
        "description": "SAP J_1J* Japan localization tables — withholding tax, bank codes, regional codes",
        "sap_transaction": "SM30 > J_1J* tables",
        "implementation_notes": "Maintain J_1J_WHTAX (withholding rates), bank directory (Zengin codes). Update for annual tax law changes.",
    },
    "ZENGIN_PAYMENT": {
        "description": "Zengin system (All Banks Data Telecommunication System) electronic payment file format",
        "sap_transaction": "FBZP > JP Payment Methods / SPRO > Zengin",
        "implementation_notes": "Generate Zengin format files for domestic transfers. Fixed-width record format. Handle Furikomi (credit transfer) and Furikae (direct debit).",
    },
    "YEAR_END_ADJUSTMENT": {
        "description": "Nenmatsu Chosei (year-end tax adjustment) — employer-performed annual income tax reconciliation",
        "sap_transaction": "SPRO > Payroll Japan > Year-End Adjustment",
        "implementation_notes": "Calculate annual income tax. Apply deductions (insurance, dependents, mortgage). Refund/collect difference in December payroll.",
    },
    "MY_NUMBER_HANDLING": {
        "description": "My Number (Individual Number) secure storage and usage for tax and social insurance",
        "sap_transaction": "PA30 > Infotype for My Number / SPRO > Japan > My Number",
        "implementation_notes": "12-digit individual number. Encrypted storage only. Strict access control. Use for withholding tax reports and social insurance only.",
    },

    # ---- Australia (AU) ----
    "BAS_GST_REPORTING": {
        "description": "Business Activity Statement — GST, PAYG installments, and withholding reporting to ATO",
        "sap_transaction": "SPRO > Australia > BAS / S_ALR_87012357",
        "implementation_notes": "Monthly/quarterly BAS lodgement. Report GST collected and paid. PAYG installments. Handle fuel tax credits. SBR lodgement.",
    },
    "STP_PHASE2": {
        "description": "Single Touch Payroll Phase 2 — expanded ATO reporting including disaggregated gross amounts",
        "sap_transaction": "SPRO > Payroll Australia > STP Phase 2",
        "implementation_notes": "Report each pay event to ATO. Disaggregate gross into salary, overtime, allowances, etc. Income types and country codes.",
    },
    "SUPERANNUATION_GUARANTEE": {
        "description": "Superannuation Guarantee (11.5% for 2024-25) employer contributions to super funds",
        "sap_transaction": "SPRO > Payroll Australia > Super",
        "implementation_notes": "Calculate SG at prescribed rate on OTE. Handle salary sacrifice. SuperStream electronic payment. Maximum super contributions base.",
    },
    "ABN_VALIDATION": {
        "description": "Australian Business Number (11-digit) validation for all business partners",
        "sap_transaction": "XK01/XD01 > Tax Information",
        "implementation_notes": "Validate ABN check digit algorithm. ABR lookup integration. PAYG withholding if no ABN provided (47% top rate).",
    },
    "PAYG_WITHHOLDING": {
        "description": "Pay As You Go withholding — employer income tax withholding using ATO tax tables",
        "sap_transaction": "SPRO > Payroll Australia > PAYG",
        "implementation_notes": "Apply ATO weekly/fortnightly/monthly tax tables. Handle HELP/STSL debt withholding. Medicare levy (2%). Tax-free threshold.",
    },
    "TPAR_REPORTING": {
        "description": "Taxable Payments Annual Report for building/construction, cleaning, and courier industries",
        "sap_transaction": "Custom / SPRO > Australia > TPAR",
        "implementation_notes": "Report payments to contractors in specified industries. Annual lodgement by 28 August. ABN, name, address, gross paid.",
    },
    "FBT_FRINGE_BENEFITS": {
        "description": "Fringe Benefits Tax — employer tax on non-cash employee benefits at 47% gross-up rate",
        "sap_transaction": "SPRO > Payroll Australia > FBT",
        "implementation_notes": "Identify FBT-liable benefits (cars, loans, entertainment). Type 1 vs Type 2 gross-up. Annual FBT return by 21 May. Exemptions/concessions.",
    },
    "WORKCOVER_PREMIUMS": {
        "description": "Workers compensation insurance premiums — state-based calculation and reporting",
        "sap_transaction": "SPRO > Payroll Australia > Workers Comp",
        "implementation_notes": "State-specific schemes (icare NSW, WorkSafe VIC, etc.). Premium based on remuneration and industry classification. Annual reconciliation.",
    },

    # ---- France (FR) ----
    "FEC_ACCOUNTING": {
        "description": "Fichier des Ecritures Comptables — mandatory accounting entries file for tax audits",
        "sap_transaction": "SPRO > France > FEC / RFBILA00",
        "implementation_notes": "Generate FEC file in prescribed XML/CSV format. All journal entries for fiscal year. Must be producible on demand for tax audit.",
    },
    "DSN_PAYROLL": {
        "description": "Declaration Sociale Nominative — unified monthly social declaration replacing DADS-U",
        "sap_transaction": "SPRO > Payroll France > DSN",
        "implementation_notes": "Monthly electronic declaration to all social organisms. Individual employee-level data. Event-driven DSN for employment changes.",
    },
    "TVA_DECLARATION": {
        "description": "TVA (Taxe sur la Valeur Ajoutee) — French VAT return (CA3 monthly/CA12 annual)",
        "sap_transaction": "SPRO > France > TVA / S_ALR_87012357",
        "implementation_notes": "Standard rate 20%, reduced 10%/5.5%/2.1%. Monthly CA3 for large companies. Annual CA12 for simplified regime. Handle DEB for EU.",
    },
    "CHORUS_PRO_FACTURX": {
        "description": "Chorus Pro government e-invoicing platform and Factur-X hybrid PDF/XML invoice format",
        "sap_transaction": "SPRO > France > E-Invoicing / Chorus Pro",
        "implementation_notes": "Mandatory for B2G invoices via Chorus Pro. Factur-X (ZUGFeRD profile) for B2B. PDF/A-3 with embedded XML. Mandate expanding 2024-2026.",
    },
    "SIRET_SIREN_VALIDATION": {
        "description": "SIRET (14-digit) and SIREN (9-digit) business identification number validation",
        "sap_transaction": "XK01/XD01 > Tax Information",
        "implementation_notes": "Validate Luhn checksum for SIREN (first 9 of SIRET). SIRET = SIREN + NIC (5 digits). INSEE directory lookup.",
    },
    "DEB_DES_TRADE": {
        "description": "Declaration d'Echanges de Biens / Declaration Europeenne de Services for EU trade",
        "sap_transaction": "SPRO > France > DEB/DES / Foreign Trade",
        "implementation_notes": "Monthly DEB for goods (Intrastat). DES for services. Reporting thresholds. Transaction nature codes. EMEBI reform.",
    },
    "PRELEVEMENT_SOURCE": {
        "description": "Prelevement a la Source — income tax withholding at source by employer",
        "sap_transaction": "SPRO > Payroll France > PAS",
        "implementation_notes": "Apply DGFIP-provided individualized rate. Default/neutral rate if not available. Monthly DSN reporting. Handle rate changes.",
    },
    "CET_CVAE_LOCAL_TAX": {
        "description": "Contribution Economique Territoriale (CET = CFE + CVAE) local business tax",
        "sap_transaction": "SPRO > France > CET",
        "implementation_notes": "CFE based on rental value. CVAE based on value added (revenue > EUR 500K). Annual declaration 1330-CVAE. Acomptes and solde.",
    },

    # ---- Mexico (MX) ----
    "CFDI_COMPLIANCE": {
        "description": "CFDI (Comprobante Fiscal Digital por Internet) electronic invoice mandatory compliance",
        "sap_transaction": "SPRO > Mexico > CFDI / J_1M*",
        "implementation_notes": "Generate CFDI XML 4.0. PAC (Proveedor Autorizado de Certificacion) stamping. UUID (folio fiscal). Handle complementos (payroll, payments).",
    },
    "SAT_REPORTING": {
        "description": "SAT (Servicio de Administracion Tributaria) regulatory reporting and annual declarations",
        "sap_transaction": "SPRO > Mexico > SAT",
        "implementation_notes": "Monthly DIOT (informativa de operaciones con terceros). Annual declaration. Contabilidad electronica submission. SAT e.firma.",
    },
    "RFC_TAX_ID": {
        "description": "RFC (Registro Federal de Contribuyentes) tax ID validation for all Mexican business partners",
        "sap_transaction": "XK01/XD01 > Tax Information",
        "implementation_notes": "Validate RFC format (13 chars for individuals, 12 for companies). CURP cross-reference. Constancia de Situacion Fiscal.",
    },
    "IVA_ISR_TAXES": {
        "description": "IVA (16% VAT) and ISR (income tax) withholding and reporting configuration",
        "sap_transaction": "SPRO > Mexico > IVA/ISR",
        "implementation_notes": "IVA standard 16%, 0% for food/medicine. ISR withholding on services (10%). Monthly IVA/ISR declarations. Handle IEPS (excise).",
    },
    "J_1M_TABLES": {
        "description": "SAP J_1M* Mexico localization tables — tax categories, RFC validation, CFDI codes",
        "sap_transaction": "SM30 > J_1M* tables",
        "implementation_notes": "Maintain J_1MFISCAL (fiscal regime), J_1MCFDI (CFDI catalogs). Update per SAT catalog changes. Annual maintenance.",
    },
    "NOMINA_PAYROLL": {
        "description": "Complemento de Nomina — CFDI payroll complement for SAT payroll reporting",
        "sap_transaction": "SPRO > Payroll Mexico > Nomina CFDI",
        "implementation_notes": "Generate CFDI Nomina 1.2 for each pay period. Stamp via PAC. Include perceptions, deductions, ISR. Employee receipt.",
    },

    # ---- Italy (IT) ----
    "FATTURA_ELETTRONICA_SDI": {
        "description": "Fattura Elettronica via SDI (Sistema di Interscambio) — mandatory B2B/B2G e-invoicing",
        "sap_transaction": "SPRO > Italy > Fattura Elettronica / SDI",
        "implementation_notes": "Generate FatturaPA XML (format 1.2). Submit via SDI. Handle notifications (RC, NS, MC). Codice Destinatario or PEC routing.",
    },
    "ESTEROMETRO": {
        "description": "Esterometro cross-border transaction reporting (replaced by SDI from July 2022)",
        "sap_transaction": "SPRO > Italy > Esterometro",
        "implementation_notes": "From July 2022, cross-border invoices via SDI (TD17-TD19 document types). Quarterly filing for residual cases.",
    },
    "ITALIAN_TAX_CODES": {
        "description": "Codice Fiscale validation and Partita IVA (VAT number) verification for business partners",
        "sap_transaction": "XK01/XD01 > Tax Information",
        "implementation_notes": "Validate Codice Fiscale (16 chars) algorithm. Partita IVA (11 digits) check digit. VIES verification for EU VAT numbers.",
    },
    "WITHHOLDING_CERTIFICATES": {
        "description": "Certificazione Unica (CU) and ritenuta d'acconto (withholding tax) certificate generation",
        "sap_transaction": "SPRO > Italy > Withholding Tax / CU",
        "implementation_notes": "Generate annual CU for recipients. Ritenuta rates per income type (20% professionals, 23% employees). Monthly F24 payment.",
    },
    "J_1I_PROGRAMS": {
        "description": "SAP J_1I* Italy localization programs — withholding tax reports, Modello 770, Intrastat",
        "sap_transaction": "J_1I* programs / SE38",
        "implementation_notes": "J_1IWHLD (withholding report), J_1I770 (annual return). Maintain per annual legislative updates. Spesometro replacement.",
    },
    "CIGO_CIGS_PAYROLL": {
        "description": "Cassa Integrazione (CIGO/CIGS) wage supplementation fund payroll configuration",
        "sap_transaction": "SPRO > Payroll Italy > CIG",
        "implementation_notes": "Configure ordinary (CIGO) and extraordinary (CIGS) wage integration. INPS contribution. Handle COVID-era special provisions.",
    },

    # ---- South Korea (KR) ----
    "E_TAX_INVOICE_KR": {
        "description": "Korean e-Tax Invoice (Jeonja Segeum Gyesan-seo) via NTS HomeTax system",
        "sap_transaction": "SPRO > Korea > E-Tax Invoice",
        "implementation_notes": "Issue e-Tax invoices via NTS. Mandatory for corporations. Public certificate authentication. Transmit by 11th of following month.",
    },
    "K_IFRS": {
        "description": "K-IFRS (Korean IFRS) accounting standards configuration for listed companies",
        "sap_transaction": "OB13 / Financial Statement Versions",
        "implementation_notes": "Mandatory for listed companies. Align chart of accounts to K-IFRS. XBRL filing to FSS (DART). Separate vs consolidated statements.",
    },
    "BIZ_REGISTRATION": {
        "description": "Business Registration Number (10-digit Saeopja Deungnok Beonho) validation",
        "sap_transaction": "XK01/XD01 > Tax Information",
        "implementation_notes": "Validate 10-digit BRN format. Check digit validation algorithm. NTS lookup. Required for all Korean business partners.",
    },
    "J_3K_TABLES": {
        "description": "SAP J_3K* Korea localization tables — tax codes, BRN validation, e-Tax invoice config",
        "sap_transaction": "SM30 > J_3K* tables",
        "implementation_notes": "Maintain Korean-specific configuration tables. Annual update for NTS regulation changes. Tax code mapping.",
    },
    "KR_PAYROLL_NTS": {
        "description": "Korean payroll NTS reporting — income tax withholding, year-end settlement, and 4 social insurances",
        "sap_transaction": "SPRO > Payroll Korea > NTS",
        "implementation_notes": "National pension, health insurance, employment insurance, workers comp. Monthly NTS reporting. Year-end tax settlement (Yeonmal Jeonsan).",
    },

    # ---- South Africa (ZA) ----
    "SARS_COMPLIANCE": {
        "description": "SARS (South African Revenue Service) compliance — income tax, VAT, and customs duties",
        "sap_transaction": "SPRO > South Africa > SARS",
        "implementation_notes": "Corporate tax at 27%. VAT at 15%. Monthly/bimonthly VAT returns. Provisional tax (IRP6). eFiling integration.",
    },
    "VAT_201_EMP_201": {
        "description": "VAT201 return and EMP201 monthly employer declaration to SARS",
        "sap_transaction": "SPRO > South Africa > VAT/EMP Returns",
        "implementation_notes": "VAT201 monthly/bimonthly filing. EMP201 for PAYE, SDL, UIF. Reconcile with EMP501 biannual. eFiling submission.",
    },
    "BBBEE_REPORTING": {
        "description": "Broad-Based Black Economic Empowerment scoring and compliance reporting",
        "sap_transaction": "Custom / HR Reports",
        "implementation_notes": "Track ownership, management control, skills development, enterprise development scorecards. Annual verification. Procurement spend tracking.",
    },
    "UIF_SDL_LEVIES": {
        "description": "Unemployment Insurance Fund (1%) and Skills Development Levy (1%) employer contributions",
        "sap_transaction": "SPRO > Payroll South Africa > UIF/SDL",
        "implementation_notes": "UIF: 1% employer + 1% employee (max threshold). SDL: 1% of payroll (exempt < R500K). Monthly submission via EMP201.",
    },
    "ZA_PAYROLL_TAX": {
        "description": "South African PAYE income tax withholding and IRP5/IT3a certificate generation",
        "sap_transaction": "SPRO > Payroll South Africa > PAYE",
        "implementation_notes": "Progressive tax rates (18-45%). Tax tables per SARS. IRP5 annual certificate. Medical tax credits. Retirement fund deductions.",
    },

    # ---- Poland (PL) ----
    "JPK_SAF_T": {
        "description": "JPK (Jednolity Plik Kontrolny) SAF-T — Standard Audit File for Tax in XML format",
        "sap_transaction": "SPRO > Poland > JPK / SAF-T",
        "implementation_notes": "Monthly JPK_VAT with declaration (JPK_V7M/K). On-demand JPK_FA (invoices), JPK_MAG (warehouse). XML schema per MF specification.",
    },
    "SPLIT_PAYMENT_MECHANISM": {
        "description": "Split payment (podzielona platnosc) — mandatory for specific goods/services via VAT account",
        "sap_transaction": "SPRO > Poland > Split Payment",
        "implementation_notes": "Mandatory for Annex 15 goods/services > PLN 15K. Payment splits between regular and VAT bank account. Bank communication format.",
    },
    "NIP_VALIDATION": {
        "description": "NIP (Numer Identyfikacji Podatkowej) 10-digit tax ID validation for Polish business partners",
        "sap_transaction": "XK01/XD01 > Tax Information",
        "implementation_notes": "Validate NIP check digit (modulo 11). White List verification (biala lista). Required for all Polish B2B transactions.",
    },
    "KSEF_E_INVOICING": {
        "description": "KSeF (Krajowy System e-Faktur) National e-Invoicing System — structured e-invoice mandate",
        "sap_transaction": "SPRO > Poland > KSeF",
        "implementation_notes": "Mandatory from Feb 2026. Submit structured XML invoices to KSeF. Receive KSeF reference number. API integration.",
    },
    "PL_VAT_RATES": {
        "description": "Polish VAT rate configuration — standard 23%, reduced 8%/5%, zero-rated",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Poland",
        "implementation_notes": "Standard 23%, reduced 8% (food, pharma), 5% (books, basic food). Zero-rated exports. Reverse charge for specified goods.",
    },

    # ---- EU-wide ----
    "INTRASTAT_EU": {
        "description": "Intrastat declaration for intra-EU goods movements — dispatches and arrivals reporting",
        "sap_transaction": "MEIS / VE01 > Foreign Trade > Intrastat",
        "implementation_notes": "Monthly filing per member state thresholds. CN8 commodity codes. Transaction nature. Delivery terms. Partner member state.",
    },
    "OSS_IOSS_VAT": {
        "description": "One Stop Shop (OSS/IOSS) — simplified VAT registration for cross-border B2C EU sales",
        "sap_transaction": "SPRO > EU > OSS/IOSS",
        "implementation_notes": "Union OSS for B2C goods/services within EU. Import OSS for consignments < EUR 150. Quarterly return to member state of identification.",
    },
    "GDPR_DATA_RETENTION": {
        "description": "GDPR-compliant data retention policies, consent management, and right-to-erasure processes",
        "sap_transaction": "SPRO > SAP ILM > GDPR / Data Protection",
        "implementation_notes": "Define purpose-based retention. Implement blocking and deletion. Consent records. Data subject access requests. Cross-border transfer rules.",
    },
    "REVERSE_CHARGE_MECHANISM": {
        "description": "EU reverse charge mechanism — shifting VAT liability to recipient for cross-border B2B supplies",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Reverse Charge",
        "implementation_notes": "Auto-apply reverse charge for intra-EU B2B. Self-assessment of VAT by buyer. Input/output tax posting. Domestic reverse charge sectors.",
    },
    "PEPPOL_E_INVOICING": {
        "description": "PEPPOL (Pan-European Public Procurement OnLine) e-invoicing network for B2G and B2B",
        "sap_transaction": "SPRO > E-Invoicing > PEPPOL",
        "implementation_notes": "UBL 2.1 or CII format. Access point registration. PEPPOL ID for routing. Mandatory for EU public sector. Expanding to B2B.",
    },

    # ---- Canada (CA) ----
    "GST_HST_CANADA": {
        "description": "GST (5%) and HST (13-15%) configuration for Canadian federal and harmonized provincial tax",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Canada",
        "implementation_notes": "GST 5% federal. HST in ON (13%), NS/NB/NL (15%), PEI (15%). PST/QST for non-harmonized provinces. Input tax credits.",
    },
    "T4_RL1_REPORTING": {
        "description": "T4 (federal) and RL-1 (Quebec) annual employee earnings and deductions reporting",
        "sap_transaction": "SPRO > Payroll Canada > T4/RL-1",
        "implementation_notes": "Generate T4 Summary and slips by Feb 28. RL-1 for Quebec employees. T4A for non-employment income. XML filing to CRA/Revenu Quebec.",
    },
    "BN_BUSINESS_NUMBER": {
        "description": "CRA Business Number (9-digit BN) validation for Canadian business partners",
        "sap_transaction": "XK01/XD01 > Tax Information",
        "implementation_notes": "Validate 9-digit BN format. RT account for GST/HST. RP for payroll. RC for corporate tax. BN lookup via CRA registry.",
    },
    "PROVINCIAL_TAX": {
        "description": "Provincial Sales Tax (PST) and Quebec Sales Tax (QST) configuration for non-HST provinces",
        "sap_transaction": "SPRO > Canada > Provincial Tax",
        "implementation_notes": "BC PST 7%, SK PST 6%, MB RST 7%. QST 9.975%. Separate registration per province. Provincial tax credits/exemptions.",
    },
    "CPP_EI_DEDUCTIONS": {
        "description": "Canada Pension Plan (CPP/CPP2) and Employment Insurance (EI) payroll deductions",
        "sap_transaction": "SPRO > Payroll Canada > CPP/EI",
        "implementation_notes": "CPP: employee/employer rates on pensionable earnings. CPP2 second ceiling from 2024. EI: 1.66% employee, 1.4x employer. YMPE/YAMPE limits.",
    },

    # ---- Singapore (SG) ----
    "GST_IRAS_SG": {
        "description": "Singapore GST (9%) configuration and IRAS filing — GST F5/F7 returns",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Singapore",
        "implementation_notes": "Standard rate 9% (from Jan 2024). Zero-rated exports. Exempt (financial services, residential). Quarterly GST F5 return. Annual GST F8.",
    },
    "PEPPOL_INVOICENOW": {
        "description": "InvoiceNow (Singapore PEPPOL network) e-invoicing for government and B2B transactions",
        "sap_transaction": "SPRO > Singapore > InvoiceNow",
        "implementation_notes": "IMDA InvoiceNow initiative. PEPPOL-based e-invoicing. UEN-based addressing. Government mandated for vendors. Expanding to B2B.",
    },
    "SG_PAYROLL": {
        "description": "Singapore payroll — income tax (IR8A), SDL (Skills Development Levy), and FWL (Foreign Worker Levy)",
        "sap_transaction": "SPRO > Payroll Singapore",
        "implementation_notes": "No withholding tax on employment income (self-assessment). IR8A annual filing. SDL 0.25% (min $2/max $11.25). FWL per sector/tier.",
    },
    "CPF_CONTRIBUTIONS": {
        "description": "Central Provident Fund employer and employee contributions by age band",
        "sap_transaction": "SPRO > Payroll Singapore > CPF",
        "implementation_notes": "Age-based rates (up to 37% total for <=55). Ordinary/Special/Medisave accounts. OW ceiling $6,000/month. AW ceiling. Monthly submission.",
    },
    "IRAS_FILING": {
        "description": "IRAS (Inland Revenue Authority of Singapore) corporate tax filing and AIS submission",
        "sap_transaction": "SPRO > Singapore > IRAS Corporate Tax",
        "implementation_notes": "Corporate tax 17%. Partial tax exemption scheme. Estimated Chargeable Income (ECI) within 3 months. Auto-Inclusion Scheme (AIS) for employers.",
    },

    # ---- Spain (ES) ----
    "SII_SUMINISTRO": {
        "description": "SII (Suministro Inmediato de Informacion) real-time VAT reporting to AEAT",
        "sap_transaction": "SPRO > Spain > SII",
        "implementation_notes": "Mandatory for large companies (>EUR 6M revenue). Submit invoice data within 4 days. Libro Registro via web service. AEAT contraste.",
    },
    "MODELO_303_VAT": {
        "description": "Modelo 303 quarterly/monthly VAT self-assessment return to AEAT",
        "sap_transaction": "SPRO > Spain > VAT Returns / Modelo 303",
        "implementation_notes": "Standard 21%, reduced 10%, super-reduced 4%. Monthly for SII companies. Quarterly for others. Annual Modelo 390 summary.",
    },
    "SPANISH_PAYROLL": {
        "description": "Spanish payroll — Social Security (Seguridad Social) contributions and IRPF withholding",
        "sap_transaction": "SPRO > Payroll Spain",
        "implementation_notes": "Social Security: ~30% employer + ~6.5% employee. Multiple contribution groups. RED system electronic filing. Certific@2 for unemployment.",
    },
    "IRPF_WITHHOLDING": {
        "description": "IRPF (Impuesto sobre la Renta de las Personas Fisicas) income tax withholding configuration",
        "sap_transaction": "SPRO > Payroll Spain > IRPF",
        "implementation_notes": "Progressive rates (19-47%). Employee situation modifiers. Modelo 111 quarterly. Modelo 190 annual summary. Handle regional variations (Basque, Navarra).",
    },
    "AEAT_FILING": {
        "description": "AEAT (Agencia Estatal de Administracion Tributaria) electronic tax filing via Sede Electronica",
        "sap_transaction": "SPRO > Spain > AEAT Filing",
        "implementation_notes": "Digital certificate for filing. Modelo 303/390 (VAT), 200 (Corporate tax), 111/190 (withholding). AEAT web services integration.",
    },

    # ---- Netherlands (NL) ----
    "DUTCH_VAT_BTW": {
        "description": "Dutch BTW (Belasting over de Toegevoegde Waarde) VAT configuration — standard 21%, reduced 9%",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Netherlands",
        "implementation_notes": "Standard 21%, reduced 9% (food, medicines, books). Zero-rated intra-EU and exports. Quarterly or monthly BTW-aangifte.",
    },
    "SBR_REPORTING": {
        "description": "SBR (Standard Business Reporting) — XBRL-based reporting to Dutch tax authority and CBS",
        "sap_transaction": "SPRO > Netherlands > SBR",
        "implementation_notes": "XBRL taxonomy for financial statements and tax returns. Digipoort submission channel. Annual accounts to KVK. ICP declaration.",
    },
    "DUTCH_PAYROLL": {
        "description": "Dutch payroll — loonheffing (wage tax), social insurance premiums, and pension contributions",
        "sap_transaction": "SPRO > Payroll Netherlands",
        "implementation_notes": "Loonheffing: wage tax + social premiums. Werkkostenregeling (WKR) for benefits. Monthly Loonaangifte to Belastingdienst. 30% ruling for expats.",
    },
    "INTRASTAT_NL": {
        "description": "Dutch Intrastat reporting for intra-EU goods trade via CBS (Centraal Bureau voor de Statistiek)",
        "sap_transaction": "SPRO > Netherlands > Intrastat",
        "implementation_notes": "Monthly CBS filing. Arrival threshold EUR 1M, dispatch EUR 1.2M. IDEP+ electronic submission. CN8 commodity codes.",
    },

    # ---- Thailand (TH) ----
    "THAI_VAT": {
        "description": "Thai VAT (7% standard rate) configuration, input/output tax reporting, and PP30 VAT return filing",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Thailand",
        "implementation_notes": "Standard rate 7%. VAT registration threshold THB 1.8M annual revenue. Monthly PP30 filing by 15th. Handle zero-rated exports and exempt supplies.",
    },
    "THAI_WHT": {
        "description": "Thai withholding tax (WHT) configuration — PND series forms for payments to vendors and employees",
        "sap_transaction": "SPRO > Financial Accounting > Withholding Tax > Thailand",
        "implementation_notes": "Configure WHT rates per income type (1-5%). PND1 (employee), PND3 (individual), PND53 (corporate). Monthly filing. Withholding certificates issuance.",
    },
    "THAI_BOI": {
        "description": "Board of Investment (BOI) tax incentives and privileges tracking for promoted activities",
        "sap_transaction": "SPRO > Thailand > BOI Privileges",
        "implementation_notes": "Track BOI-promoted projects separately. Corporate tax exemptions (3-8 years). Import duty exemptions on machinery. Separate profit/loss tracking per BOI certificate.",
    },
    "THAI_SSF": {
        "description": "Thai Social Security Fund (SSF) employer and employee contribution configuration",
        "sap_transaction": "SPRO > Payroll Thailand > Social Security",
        "implementation_notes": "Employer 5% + employee 5% on wages up to THB 15,000/month. Monthly SSO filing. Handle contribution ceiling changes. Provident fund integration.",
    },
    "THAI_ETAX": {
        "description": "Thailand e-Tax Invoice and e-Receipt electronic tax document system with Revenue Department",
        "sap_transaction": "SPRO > Thailand > E-Tax Invoice",
        "implementation_notes": "Generate XML e-Tax Invoice per Revenue Department specification. Digital signature required. Register with Revenue Department for e-Tax system. PDF/A-3 with embedded XML.",
    },

    # ---- Indonesia (ID) ----
    "IDN_EFAKTUR": {
        "description": "e-Faktur electronic tax invoice system — mandatory VAT invoice issuance via DJP e-Faktur application",
        "sap_transaction": "SPRO > Indonesia > e-Faktur",
        "implementation_notes": "Generate e-Faktur CSV/XML for upload to DJP e-Faktur application. NPWP validation. Faktur Pajak numbering (NSFP allocation from DJP). Handle credit notes (Faktur Pengganti).",
    },
    "IDN_PPH21": {
        "description": "PPh 21 employee income tax withholding — progressive rates and annual SPT reporting",
        "sap_transaction": "SPRO > Payroll Indonesia > PPh 21",
        "implementation_notes": "Progressive rates: 5% (up to IDR 60M), 15%, 25%, 30%, 35%. Monthly SPT Masa PPh 21 filing. Annual 1721-A1 forms. Handle PTKP (non-taxable income) categories.",
    },
    "IDN_PPH23": {
        "description": "PPh 23 withholding tax on services, dividends, royalties, and interest payments",
        "sap_transaction": "SPRO > Financial Accounting > Withholding Tax > Indonesia PPh 23",
        "implementation_notes": "2% on services, 15% on dividends/royalties/interest. Monthly SPT Masa PPh 23 filing. Bukti Potong (withholding slip) generation. Handle double tax treaty rates.",
    },
    "IDN_BPJS": {
        "description": "BPJS Ketenagakerjaan (Employment) and BPJS Kesehatan (Health) social security contributions",
        "sap_transaction": "SPRO > Payroll Indonesia > BPJS",
        "implementation_notes": "BPJS Ketenagakerjaan: JKK (0.24-1.74%), JKM (0.3%), JHT (employer 3.7% + employee 2%), JP (employer 2% + employee 1%). BPJS Kesehatan: 5% (employer 4% + employee 1%). Monthly filing.",
    },
    "IDN_CUSTOMS": {
        "description": "Indonesian customs duty, import VAT, and luxury goods tax (PPnBM) for import/export operations",
        "sap_transaction": "SPRO > Indonesia > Customs / SAP GTS",
        "implementation_notes": "Configure customs tariff codes (HS codes). Import duty rates per trade agreement. Import VAT (PPN) 11%. PPnBM on luxury goods (10-200%). Bonded zone handling. AEO certification.",
    },

    # ---- Malaysia (MY) ----
    "MYS_SST": {
        "description": "Sales and Service Tax (SST) configuration — 10% sales tax and 8% service tax",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Malaysia",
        "implementation_notes": "Sales tax 10% (5% for selected goods). Service tax 8% (6% for selected services). Bimonthly SST-02 filing. Handle exemptions and group relief. SST registration threshold MYR 500K.",
    },
    "MYS_EINVOICE": {
        "description": "Malaysia e-Invoice mandate — LHDN (Inland Revenue Board) electronic invoicing system",
        "sap_transaction": "SPRO > Malaysia > E-Invoice",
        "implementation_notes": "Mandatory e-Invoice via MyInvois portal (phased rollout from Aug 2024). XML/JSON format per LHDN specification. TIN (Tax Identification Number) validation. QR code on invoices.",
    },
    "MYS_EPF": {
        "description": "Employees Provident Fund (EPF/KWSP) statutory contribution configuration",
        "sap_transaction": "SPRO > Payroll Malaysia > EPF",
        "implementation_notes": "Employer 13% (12% for salary > MYR 5,000) + employee 11% (reduced rate options for 60+). Monthly contribution via online banking. Form A submission. Handle voluntary excess contributions.",
    },
    "MYS_SOCSO": {
        "description": "SOCSO (PERKESO) social security contribution — Employment Injury and Invalidity Pension schemes",
        "sap_transaction": "SPRO > Payroll Malaysia > SOCSO",
        "implementation_notes": "Employment Injury Scheme: employer 1.25%. Invalidity Pension: employer 0.25% + employee 0.25%. Wage ceiling MYR 5,000. EIS (Employment Insurance System) 0.2% each. Monthly filing.",
    },
    "MYS_PCB": {
        "description": "Monthly Tax Deduction (PCB/MTD) — employer withholding of income tax per LHDN schedule",
        "sap_transaction": "SPRO > Payroll Malaysia > PCB",
        "implementation_notes": "Compute PCB using LHDN schedular tax deduction table or computerized calculation method. Monthly remittance via e-PCB. EA Form annual issuance. Handle tax reliefs and rebates.",
    },

    # ---- Philippines (PH) ----
    "PHL_BIR": {
        "description": "Bureau of Internal Revenue (BIR) tax compliance — VAT (12%), income tax, and regulatory filing",
        "sap_transaction": "SPRO > Philippines > BIR",
        "implementation_notes": "VAT 12% standard rate. Quarterly VAT return (BIR Form 2550Q). Monthly withholding tax returns. Annual ITR (1702/1702Q). BIR-registered sales invoices and official receipts.",
    },
    "PHL_EWT": {
        "description": "Expanded Withholding Tax (EWT) on income payments to contractors and professionals",
        "sap_transaction": "SPRO > Financial Accounting > Withholding Tax > Philippines EWT",
        "implementation_notes": "EWT rates: 1-15% depending on income type. Monthly filing (BIR Form 0619E). Quarterly filing (BIR Form 1601EQ). Annual (BIR Form 1604E). BIR Form 2307 certificates.",
    },
    "PHL_SSS": {
        "description": "Social Security System (SSS) employer and employee contribution configuration",
        "sap_transaction": "SPRO > Payroll Philippines > SSS",
        "implementation_notes": "Employer 9.5% + employee 4.5% (2025 rates). Monthly salary credit bracket system. R-3 contribution report. Handle EC (Employees Compensation) additional 1% employer.",
    },
    "PHL_PHIC": {
        "description": "PhilHealth (Philippine Health Insurance Corporation) premium contribution configuration",
        "sap_transaction": "SPRO > Payroll Philippines > PhilHealth",
        "implementation_notes": "Premium rate 5% of basic salary (shared equally employer/employee). Monthly premium ceiling PHP 100,000. RF-1 remittance report. Handle dependent registration.",
    },
    "PHL_PAGIBIG": {
        "description": "Pag-IBIG Fund (HDMF) housing and savings contribution configuration",
        "sap_transaction": "SPRO > Payroll Philippines > Pag-IBIG",
        "implementation_notes": "Employer 2% + employee 2% of monthly compensation. Maximum monthly compensation PHP 5,000 for mandatory. Handle voluntary contributions above mandatory. Monthly HDMF report.",
    },

    # ---- Vietnam (VN) ----
    "VNM_EINVOICE": {
        "description": "Vietnam e-Invoice (hoa don dien tu) mandatory electronic invoicing via General Department of Taxation",
        "sap_transaction": "SPRO > Vietnam > E-Invoice",
        "implementation_notes": "Mandatory e-Invoice from July 2022. XML format per Decree 123/2020/ND-CP. Register with tax authority for e-Invoice issuance. Handle authenticated and unauthenticated invoices.",
    },
    "VNM_PIT": {
        "description": "Personal Income Tax (PIT) withholding — progressive rates for residents and flat rate for non-residents",
        "sap_transaction": "SPRO > Payroll Vietnam > PIT",
        "implementation_notes": "Progressive rates 5-35% for residents (7 brackets). Flat 20% for non-residents. Monthly withholding and quarterly declaration. Personal deduction VND 11M/month. Dependent deduction VND 4.4M.",
    },
    "VNM_SI": {
        "description": "Vietnamese Social Insurance (BHXH), Health Insurance (BHYT), and Unemployment Insurance (BHTN)",
        "sap_transaction": "SPRO > Payroll Vietnam > Social Insurance",
        "implementation_notes": "BHXH: employer 17.5% + employee 8%. BHYT: employer 3% + employee 1.5%. BHTN: employer 1% + employee 1%. Monthly declaration. Salary base cap 20x minimum wage.",
    },
    "VNM_FCT": {
        "description": "Vietnam Foreign Contractor Tax (FCT) withholding on payments to foreign entities",
        "sap_transaction": "SPRO > Financial Accounting > Withholding Tax > Vietnam FCT",
        "implementation_notes": "CIT component: 1-10% depending on activity type. VAT component: 2-5%. Handle hybrid method, direct method, or deemed method per contractor registration. Monthly declaration.",
    },
    "VNM_TP": {
        "description": "Transfer Pricing (TP) documentation and related party transaction reporting to Vietnamese tax authority",
        "sap_transaction": "SPRO > Vietnam > Transfer Pricing / Custom Reports",
        "implementation_notes": "Annual TP disclosure form (Appendix I-IV per Decree 132). Local file, master file, and CbCR requirements. Threshold: related party transactions > VND 200 billion or taxpayer with losses.",
    },

    # ---- Taiwan (TW) ----
    "TWN_GUI": {
        "description": "Government Uniform Invoice (GUI) — mandatory electronic invoice system administered by Ministry of Finance",
        "sap_transaction": "SPRO > Taiwan > GUI / E-Invoice",
        "implementation_notes": "GUI numbering with MOF-allocated tracks. B2B (format A/B) and B2C (format C) invoices. Electronic GUI via Turnkey platform. Prize-eligible invoice lottery. Void/allowance handling.",
    },
    "TWN_VAT": {
        "description": "Taiwan Business Tax (VAT) configuration — 5% standard rate and zero-rated export supplies",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Taiwan",
        "implementation_notes": "Standard rate 5%. Zero-rated exports. Exempt (land, securities, insurance). Bimonthly filing (401 form). Annual filing for specific industries. Input tax credit mechanism.",
    },
    "TWN_NHI": {
        "description": "National Health Insurance (NHI) premium contribution configuration for employers and employees",
        "sap_transaction": "SPRO > Payroll Taiwan > NHI",
        "implementation_notes": "Premium rate shared: employer 60%, employee 30%, government 10%. Calculate on insured salary grade. Monthly declaration. Handle supplementary premium (2.11%) on bonus/other income.",
    },
    "TWN_LABOR": {
        "description": "Taiwan Labor Insurance and Labor Pension Fund contribution configuration",
        "sap_transaction": "SPRO > Payroll Taiwan > Labor Insurance",
        "implementation_notes": "Labor Insurance: employer 70%, employee 20%, government 10%. Labor Pension: employer 6% minimum (new scheme). Monthly contribution filing. Handle occupational accident insurance.",
    },
    "TWN_XBRL": {
        "description": "XBRL financial reporting to Taiwan Stock Exchange (TWSE) and Financial Supervisory Commission",
        "sap_transaction": "SPRO > Taiwan > XBRL Reporting",
        "implementation_notes": "XBRL taxonomy per TWSE specification. Quarterly and annual financial statements. IFRS-aligned reporting. MOPS (Market Observation Post System) submission.",
    },

    # ---- Hong Kong (HK) ----
    "HKG_PROFITS_TAX": {
        "description": "Hong Kong Profits Tax configuration — two-tiered tax rate for incorporated and unincorporated businesses",
        "sap_transaction": "SPRO > Hong Kong > Profits Tax",
        "implementation_notes": "Two-tiered rate: 8.25% on first HKD 2M, 16.5% thereafter (corporations). Unincorporated: 7.5%/15%. Annual filing (BIR51/52). Provisional tax. Loss carry-forward (indefinite).",
    },
    "HKG_MPF": {
        "description": "Mandatory Provident Fund (MPF) employer and employee contribution configuration",
        "sap_transaction": "SPRO > Payroll Hong Kong > MPF",
        "implementation_notes": "Employer 5% + employee 5% on relevant income (HKD 7,100-30,000/month). Below HKD 7,100: employee exempt. Cap on mandatory contribution. Monthly contribution via MPF scheme trustee.",
    },
    "HKG_IRD": {
        "description": "Inland Revenue Department (IRD) compliance — employer's return, salaries tax, and stamp duty",
        "sap_transaction": "SPRO > Hong Kong > IRD Filing",
        "implementation_notes": "Annual Employer's Return (IR56B). Salaries tax progressive rates (2-17%) or standard rate 15%. Report commencement (IR56E) and cessation (IR56F) of employment. eTAX filing.",
    },
    "HKG_STAMP_DUTY": {
        "description": "Hong Kong Stamp Duty on property transactions, stock transfers, and lease agreements",
        "sap_transaction": "SPRO > Hong Kong > Stamp Duty",
        "implementation_notes": "Ad valorem stamp duty on property (1.5-4.25%). Stock transfer stamp duty 0.13%. Lease stamp duty based on rental amount. E-stamping via IRD portal. Handle special stamp duty and buyer stamp duty.",
    },

    # ---- Switzerland (CH) ----
    "CHE_VAT": {
        "description": "Swiss VAT (MWST/TVA/IVA) configuration — standard 8.1%, reduced 2.6%, and accommodation 3.8%",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Switzerland",
        "implementation_notes": "Standard rate 8.1% (from 2024), reduced 2.6% (food, medicines, newspapers), accommodation 3.8%. Quarterly VAT return. Effective vs agreed-upon rate method. Import VAT handling.",
    },
    "CHE_QRBILL": {
        "description": "Swiss QR-bill (QR-Rechnung) payment slip with Swiss QR Code replacing legacy payment slips",
        "sap_transaction": "SPRO > Switzerland > QR-bill / Payment Medium",
        "implementation_notes": "Generate QR-bill per SIX specification. QR-IBAN for QR-reference. SCOR (Structured Creditor Reference) for creditor reference. PDF output with Swiss Cross QR code. Replace ESR/ISR.",
    },
    "CHE_AHV": {
        "description": "Swiss AHV/AVS (Old Age and Survivors Insurance) first pillar social security contributions",
        "sap_transaction": "SPRO > Payroll Switzerland > AHV",
        "implementation_notes": "AHV/AVS: employer 4.35% + employee 4.35%. IV/AI (disability): 0.7% each. EO/APG (income replacement): 0.25% each. ALV/AC (unemployment): 1.1% each. Annual salary declaration (Lohnmeldung).",
    },
    "CHE_BVG": {
        "description": "Swiss BVG/LPP occupational pension (second pillar) contribution configuration",
        "sap_transaction": "SPRO > Payroll Switzerland > BVG",
        "implementation_notes": "Mandatory BVG from age 25. Minimum employer 50% of contribution. Age-dependent rates (7-18% of coordinated salary). Coordination deduction CHF 25,725. Entry threshold CHF 22,050. Handle over-obligatory benefits.",
    },
    "CHE_GAAP_FER": {
        "description": "Swiss GAAP FER accounting standards — financial reporting framework for non-listed companies",
        "sap_transaction": "OB13 / Financial Statement Versions > Swiss GAAP FER",
        "implementation_notes": "Configure chart of accounts per Swiss GAAP FER structure. Core FER (FER 1-6) for SMEs. Full FER for larger entities. Parallel to IFRS if also required. Consolidation per FER 30.",
    },

    # ---- Austria (AT) ----
    "AUT_VAT": {
        "description": "Austrian VAT (Umsatzsteuer) configuration — standard 20%, reduced 10%/13%, and intra-EU handling",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Austria",
        "implementation_notes": "Standard 20%, reduced 10% (food, books, public transport), 13% (cultural events, plants). Monthly/quarterly UVA (Umsatzsteuervoranmeldung). Annual U30 return. FinanzOnline electronic filing.",
    },
    "AUT_FINANZONLINE": {
        "description": "FinanzOnline electronic filing platform — Austrian tax authority digital submission channel",
        "sap_transaction": "SPRO > Austria > FinanzOnline",
        "implementation_notes": "Electronic filing for UVA (VAT advance), U30 (annual VAT), E1a (income tax supplement), L16 (payroll annual return). FinanzOnline participant ID and access. XML submission format.",
    },
    "AUT_SV": {
        "description": "Austrian Social Insurance (Sozialversicherung) — ASVG contributions for pension, health, accident, and unemployment",
        "sap_transaction": "SPRO > Payroll Austria > Social Insurance",
        "implementation_notes": "Employer ~21.23% + employee ~18.07% total social insurance. Monthly contribution statement (Beitragsnachweisung). ELDA electronic filing. Handle Geringfuegigkeitsgrenze (marginal employment threshold).",
    },
    "AUT_REGISTRIERKASSE": {
        "description": "Austrian cash register regulation (Registrierkassenpflicht) with digital signature for POS transactions",
        "sap_transaction": "SPRO > Austria > Cash Register / TSE",
        "implementation_notes": "Mandatory for businesses > EUR 15,000 annual revenue and > EUR 7,500 cash revenue. Digital signature (Signatureinheit). Monthly receipt (Monatsbeleg). Annual receipt (Jahresbeleg). FinanzOnline registration.",
    },

    # ---- Belgium (BE) ----
    "BEL_VAT": {
        "description": "Belgian VAT (BTW/TVA) configuration — standard 21%, reduced 12%/6%, and Belgian VAT return",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Belgium",
        "implementation_notes": "Standard 21%, reduced 12% (housing renovation, restaurant food), 6% (food, water, pharma, books). Monthly/quarterly VAT return. Annual client/supplier listing. Intervat electronic filing.",
    },
    "BEL_CODA": {
        "description": "Belgian CODA (Coded Statement of Account) electronic bank statement format for automatic reconciliation",
        "sap_transaction": "SPRO > Belgium > CODA / Electronic Bank Statement",
        "implementation_notes": "CODA 2.5 format for automatic bank reconciliation. Configure CODA banks and structured communication (OGM/VCS). Map transaction codes to SAP posting rules. Multi-bank CODA handling.",
    },
    "BEL_DIMONA": {
        "description": "DIMONA (Declaration Immediate/Onmiddellijke Aangifte) employment registration with NSSO/RSZ",
        "sap_transaction": "SPRO > Payroll Belgium > DIMONA",
        "implementation_notes": "Mandatory declaration of employment start (IN) and end (OUT). Real-time electronic submission to NSSO. DIMONA reference number. Handle student workers, flexi-jobs, and interim workers.",
    },
    "BEL_PEPPOL": {
        "description": "Belgian PEPPOL e-invoicing — mandatory for B2G and expanding to B2B via Hermes platform",
        "sap_transaction": "SPRO > Belgium > PEPPOL E-Invoicing",
        "implementation_notes": "Mandatory for B2G via Mercurius platform. B2B mandate from 2026. UBL-BE profile (Belgian PEPPOL specification). Enterprise number (KBO/BCE) for routing. Access point registration.",
    },
    "BEL_ONSS": {
        "description": "ONSS/RSZ (Office National de Securite Sociale) quarterly social security declaration",
        "sap_transaction": "SPRO > Payroll Belgium > ONSS",
        "implementation_notes": "Quarterly DmfA (Declaration multifonctionnelle/multifunctionele Aangifte). Employer ~25% social security + special contributions. Handle sector-specific rates (PC/CP). Structural reductions and target group reductions.",
    },

    # ---- Denmark (DK) ----
    "DNK_VAT": {
        "description": "Danish VAT (moms) configuration — 25% standard rate with quarterly/monthly filing to Skattestyrelsen",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Denmark",
        "implementation_notes": "Flat 25% rate (no reduced rates). Quarterly filing for most; monthly for large companies. Annual for small businesses. Rubric-based VAT return. EU reverse charge handling.",
    },
    "DNK_NEMHANDEL": {
        "description": "NemHandel Danish e-invoicing infrastructure — OIOUBL/PEPPOL based B2G and B2B electronic invoicing",
        "sap_transaction": "SPRO > Denmark > NemHandel E-Invoice",
        "implementation_notes": "Mandatory for B2G since 2005. OIOUBL (Danish UBL profile) or PEPPOL BIS. NemHandel register for routing. CVR number for identification. EAN/GLN location numbers for public sector.",
    },
    "DNK_ATP": {
        "description": "ATP (Arbejdsmarkedets Tillaegspension) supplementary pension contribution configuration",
        "sap_transaction": "SPRO > Payroll Denmark > ATP",
        "implementation_notes": "Fixed monthly contribution based on working hours (full-time: DKK 284/month, employer 2/3 + employee 1/3). Monthly e-Indkomst reporting. AM-bidrag (labor market contribution) 8% of gross income.",
    },
    "DNK_SKAT": {
        "description": "Skat (Danish tax authority) electronic reporting — e-Indkomst payroll and annual tax return",
        "sap_transaction": "SPRO > Payroll Denmark > Skat / e-Indkomst",
        "implementation_notes": "Monthly e-Indkomst payroll reporting. A-tax (provisional income tax) withholding per tax card. AM-bidrag 8%. Annual employer statement. Research tax credit (Skattekreditordningen) handling.",
    },

    # ---- Sweden (SE) ----
    "SWE_VAT": {
        "description": "Swedish VAT (moms) configuration — standard 25%, reduced 12%/6%, and Skatteverket filing",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Sweden",
        "implementation_notes": "Standard 25%, reduced 12% (food, hotel, restaurant), 6% (books, newspapers, public transport, cultural events). Monthly/quarterly VAT return via Skatteverket. EU sales list (periodisk sammanstallning).",
    },
    "SWE_PEPPOL": {
        "description": "Swedish PEPPOL e-invoicing — mandatory for B2G via DIGG and expanding B2B adoption",
        "sap_transaction": "SPRO > Sweden > PEPPOL E-Invoice",
        "implementation_notes": "Mandatory for B2G invoices. Svefaktura/PEPPOL BIS 3.0 format. Organization number (organisationsnummer) for routing. DIGG compliance requirements. Access point registration.",
    },
    "SWE_SKATTEVERKET": {
        "description": "Skatteverket (Swedish Tax Agency) electronic reporting — employer declarations and tax returns",
        "sap_transaction": "SPRO > Payroll Sweden > Skatteverket",
        "implementation_notes": "Monthly employer declaration (arbetsgivardeklaration) with individual reporting (AGI). Income tax withholding per tax table (skattetabell). Annual kontrolluppgift. Social security employer fee ~31.42%.",
    },
    "SWE_SAFT": {
        "description": "Swedish SAF-T (Standard Audit File for Tax) implementation for digital tax audit compliance",
        "sap_transaction": "SPRO > Sweden > SAF-T",
        "implementation_notes": "SAF-T 2.0 format per Skatteverket specification. XML export of general ledger, accounts receivable/payable, and asset data. On-demand generation for tax audits.",
    },

    # ---- Norway (NO) ----
    "NOR_VAT": {
        "description": "Norwegian VAT (merverdiavgift/mva) configuration — standard 25%, reduced 15%/12%",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Norway",
        "implementation_notes": "Standard 25%, reduced 15% (food), 12% (transport, hotel, cinema, cultural). Bimonthly mva-melding (VAT return). Handle 0% rate for exports and specific services.",
    },
    "NOR_SAFT": {
        "description": "Norwegian SAF-T mandatory accounting file — Skatteetaten digital audit format",
        "sap_transaction": "SPRO > Norway > SAF-T",
        "implementation_notes": "Mandatory from 2020. SAF-T Financial per Norwegian mapping (OECD standard). XML format. Must be producible on 10 business days notice. Bookkeeping Act (Bokforingsloven) compliance.",
    },
    "NOR_ALTINN": {
        "description": "Altinn electronic government reporting platform — tax returns, VAT, and employer declarations",
        "sap_transaction": "SPRO > Norway > Altinn",
        "implementation_notes": "Electronic filing via Altinn portal. VAT return (mva-melding), employer report (a-melding), annual tax return. API integration for automated submission. Organization number for identification.",
    },
    "NOR_OTP": {
        "description": "OTP (Obligatorisk Tjenestepensjon) mandatory occupational pension contribution",
        "sap_transaction": "SPRO > Payroll Norway > OTP",
        "implementation_notes": "Minimum 2% of salary (between 1G-12G). Employer-funded. Various pension schemes (defined contribution/benefit). Monthly contribution to pension provider. Handle AFP (Avtalefestet Pensjon).",
    },

    # ---- Finland (FI) ----
    "FIN_VAT": {
        "description": "Finnish VAT (arvonlisavero/ALV) configuration — standard 25.5%, reduced 14%/10%",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Finland",
        "implementation_notes": "Standard 25.5% (from Sep 2024), reduced 14% (food, restaurant, animal feed), 10% (books, pharma, transport, hotel). Monthly VAT return via MyTax (OmaVero). EU reverse charge.",
    },
    "FIN_PEPPOL": {
        "description": "Finnish PEPPOL e-invoicing adoption — Finvoice and PEPPOL BIS for B2G and B2B",
        "sap_transaction": "SPRO > Finland > PEPPOL / Finvoice",
        "implementation_notes": "Finvoice 3.0 domestic standard. PEPPOL BIS for cross-border. Mandatory for public sector suppliers. Business ID (Y-tunnus) for routing. Finnish banking integration for payment initiation.",
    },
    "FIN_TYEL": {
        "description": "TyEL (Tyoelakevakuutusmaksu) earnings-related pension insurance contribution",
        "sap_transaction": "SPRO > Payroll Finland > TyEL",
        "implementation_notes": "Employer ~17.35% + employee 7.15%/8.65% (age-dependent). Monthly contribution to pension insurance company. Annual reconciliation. Handle part-time and multiple employer situations.",
    },
    "FIN_VERO": {
        "description": "Vero (Finnish Tax Administration) electronic reporting — income register and tax returns",
        "sap_transaction": "SPRO > Payroll Finland > Vero / Income Register",
        "implementation_notes": "Tulorekisteri (Income Register) real-time earnings reporting within 5 days of payment. Replaces annual employer declarations. Social insurance base reporting. MyTax (OmaVero) corporate filing.",
    },

    # ---- Ireland (IE) ----
    "IRL_VAT": {
        "description": "Irish VAT configuration — standard 23%, reduced 13.5%/9%/4.8%, and Revenue Online Service filing",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Ireland",
        "implementation_notes": "Standard 23%, reduced 13.5% (housing, building services), 9% (newspapers, sports facilities), 4.8% (livestock, greyhounds). Bimonthly VAT3 return via ROS. Annual VAT3 for small traders.",
    },
    "IRL_ROS": {
        "description": "Revenue Online Service (ROS) — Irish Revenue electronic filing for VAT, PAYE, and corporation tax",
        "sap_transaction": "SPRO > Ireland > ROS",
        "implementation_notes": "ROS digital certificate for electronic filing. VAT3 bimonthly. CT1 (corporation tax annual). P35 employer annual return. VIES reporting. Intrastat via CSO. ROS payment methods.",
    },
    "IRL_PRSI": {
        "description": "PRSI (Pay Related Social Insurance) employer and employee contribution configuration",
        "sap_transaction": "SPRO > Payroll Ireland > PRSI",
        "implementation_notes": "Employer PRSI: 8.8% or 11.05% depending on earnings. Employee PRSI: 4%. Multiple PRSI classes (A, J, S, etc.) based on employment type. Weekly/monthly contribution calculation. Handle PRSI credit.",
    },
    "IRL_PAYE": {
        "description": "Irish PAYE (Pay As You Earn) income tax withholding and USC (Universal Social Charge)",
        "sap_transaction": "SPRO > Payroll Ireland > PAYE",
        "implementation_notes": "PAYE Modernisation: real-time payroll reporting to Revenue. Revenue Payroll Notification (RPN) for tax credits. USC rates 0.5-8%. PAYE rates 20%/40%. Monthly employer P30 submission.",
    },

    # ---- Portugal (PT) ----
    "PRT_VAT": {
        "description": "Portuguese VAT (IVA) configuration — standard 23%, reduced 13%/6%, and AT filing",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Portugal",
        "implementation_notes": "Continental: standard 23%, intermediate 13%, reduced 6%. Madeira/Azores have lower rates. Monthly/quarterly IVA return via AT portal. SAF-T(PT) mandatory. Recapitulative statement for EU sales.",
    },
    "PRT_SAFT": {
        "description": "SAF-T(PT) mandatory standard audit file — monthly submission to Autoridade Tributaria (AT)",
        "sap_transaction": "SPRO > Portugal > SAF-T",
        "implementation_notes": "Monthly SAF-T(PT) submission to AT since 2013. XML format per Portuguese specification (differs from OECD standard). Covers sales invoices, general ledger, customer/supplier data. Automatic IVA pre-fill.",
    },
    "PRT_ATCUD": {
        "description": "ATCUD (Codigo Unico de Documento) unique document code required on all commercial documents",
        "sap_transaction": "SPRO > Portugal > ATCUD",
        "implementation_notes": "Unique code per document combining series validation code and sequential number. AT-allocated series validation code. QR code with document data on invoices. Mandatory for all tax-relevant documents.",
    },
    "PRT_SS": {
        "description": "Portuguese Social Security (Seguranca Social) employer and employee contribution configuration",
        "sap_transaction": "SPRO > Payroll Portugal > Social Security",
        "implementation_notes": "Employer 23.75% + employee 11% (standard rates). Monthly DMR (Declaracao Mensal de Remuneracoes). Handle different rates for board members, self-employed. Overtime-specific contribution rules.",
    },

    # ---- Greece (GR) ----
    "GRC_VAT": {
        "description": "Greek VAT (FPA) configuration — standard 24%, reduced 13%/6%, and myDATA integration",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Greece",
        "implementation_notes": "Standard 24%, reduced 13% (food, energy, water), super-reduced 6% (pharma, books, hotel). 30% discount on Aegean islands for specific rates. Monthly VAT return. myDATA real-time reporting.",
    },
    "GRC_MYDATA": {
        "description": "myDATA (my Digital Accounting and Tax Application) real-time invoice reporting to AADE",
        "sap_transaction": "SPRO > Greece > myDATA",
        "implementation_notes": "Mandatory real-time transmission of income/expense data to AADE. Classification of income types and expense categories. API or ERP provider integration. MARK (unique identifier) per document.",
    },
    "GRC_EFKA": {
        "description": "EFKA (Unified Social Insurance Fund) employer and employee contribution configuration",
        "sap_transaction": "SPRO > Payroll Greece > EFKA",
        "implementation_notes": "Employer ~22.54% + employee ~13.87% (main pension + supplementary + health + unemployment). Monthly APD (Analitiki Periodiki Dilosi) declaration via ERGANI. Handle different rates per employment category.",
    },
    "GRC_AADE": {
        "description": "AADE (Independent Authority for Public Revenue) tax compliance and electronic filing",
        "sap_transaction": "SPRO > Greece > AADE Filing",
        "implementation_notes": "Electronic filing of VAT returns, income tax, and property tax via TAXISnet. Annual E3 (income statement) and N (tax return). myDATA integration for real-time compliance. Digital tax certificate.",
    },

    # ---- Czech Republic (CZ) ----
    "CZE_VAT": {
        "description": "Czech VAT (DPH) configuration — standard 21%, reduced 12%, and Control Report (KH DPH)",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Czech Republic",
        "implementation_notes": "Standard 21%, reduced 12% (food, beverages, books, medicines). Monthly VAT return. KH DPH (kontrolni hlaseni) monthly control report. Summary report (Souhrnne hlaseni) for EU. Reverse charge domestic.",
    },
    "CZE_KHDPH": {
        "description": "Czech Control Report (KH DPH / Kontrolni Hlaseni) detailed transaction-level VAT reporting",
        "sap_transaction": "SPRO > Czech Republic > Control Report",
        "implementation_notes": "Monthly control report to tax authority. Section A (sales > CZK 10,000), B (purchases > CZK 10,000), C (other). XML format. 5-day deadline for corrections. Significant penalties for non-compliance.",
    },
    "CZE_CSSZ": {
        "description": "CSSZ (Czech Social Security Administration) employer social insurance and health insurance contributions",
        "sap_transaction": "SPRO > Payroll Czech Republic > CSSZ",
        "implementation_notes": "Social insurance: employer 24.8% (pension 21.5% + sickness 2.1% + employment 1.2%) + employee 7.1%. Health insurance: employer 9% + employee 4.5%. Monthly ELDP reporting.",
    },
    "CZE_EET": {
        "description": "EET (Elektronicka Evidence Trzeb) electronic record of sales — real-time cash register reporting",
        "sap_transaction": "SPRO > Czech Republic > EET",
        "implementation_notes": "Real-time reporting of cash transactions to tax authority. FIK (fiscal identification code) per transaction. BKP (taxpayer security code). Handle offline mode with PKP. Note: EET was suspended in 2023 but may be reinstated.",
    },

    # ---- Hungary (HU) ----
    "HUN_VAT": {
        "description": "Hungarian VAT (AFA) configuration — standard 27% (EU highest), reduced 18%/5%",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Hungary",
        "implementation_notes": "Standard 27%, reduced 18% (dairy, bakery), 5% (medicines, books, restaurant, hotel, new residential property). Monthly/quarterly VAT return. Real-time invoice reporting via NAV.",
    },
    "HUN_NAV3": {
        "description": "NAV Online Invoice System 3.0 — real-time B2B invoice reporting to Hungarian Tax Authority",
        "sap_transaction": "SPRO > Hungary > NAV Online Invoice",
        "implementation_notes": "Mandatory real-time reporting of all B2B invoices (domestic VAT-liable). NAV 3.0 XML schema. API integration with NAV Online platform. Technical user registration. Report within seconds of invoice issuance.",
    },
    "HUN_KATA": {
        "description": "KATA (Small Taxpayer Tax) simplified taxation regime handling for small business partners",
        "sap_transaction": "SPRO > Hungary > KATA",
        "implementation_notes": "Handle KATA-subject vendors in AP (different withholding rules). KATA taxpayer identification in master data. Impact on deductibility of expenses paid to KATA taxpayers above HUF 3M threshold.",
    },
    "HUN_TB": {
        "description": "Hungarian local business tax (iparuzesi ado) and innovation contribution (innovacios jarulok)",
        "sap_transaction": "SPRO > Hungary > Local Business Tax",
        "implementation_notes": "Local business tax up to 2% on net revenue (municipality-dependent). Innovation contribution 0.3%. Semi-annual advance payments. Annual reconciliation. Municipality-specific declarations.",
    },

    # ---- Romania (RO) ----
    "ROU_VAT": {
        "description": "Romanian VAT (TVA) configuration — standard 19%, reduced 9%/5%, and D300 VAT return",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Romania",
        "implementation_notes": "Standard 19%, reduced 9% (food, hotel, restaurant), 5% (textbooks, first home, cultural). Monthly/quarterly D300 VAT return. D394 informative return. Reverse charge for specific goods/services.",
    },
    "ROU_EFACTURA": {
        "description": "Romania e-Factura mandatory electronic invoicing system via ANAF SPV platform",
        "sap_transaction": "SPRO > Romania > e-Factura",
        "implementation_notes": "Mandatory B2B e-invoicing from January 2024. XML format per CIUS-RO specification (UBL 2.1). Upload to ANAF e-Factura system. Download seal from ANAF. 5-day upload deadline.",
    },
    "ROU_ETRANSPORT": {
        "description": "Romania e-Transport system for tracking goods transportation and high fiscal risk products",
        "sap_transaction": "SPRO > Romania > e-Transport",
        "implementation_notes": "Mandatory declaration of goods transport. UIT (unique identification code) per transport. API declaration to ANAF. Cover high fiscal risk goods and international transport. Penalties for non-compliance.",
    },
    "ROU_ANAF": {
        "description": "ANAF (National Agency for Fiscal Administration) electronic tax filing and SAF-T RO",
        "sap_transaction": "SPRO > Romania > ANAF / SAF-T",
        "implementation_notes": "D100/D300/D394 electronic tax returns via ANAF portal. SAF-T RO (D406 declaration) mandatory from 2025 for large taxpayers. Digital signature required. SPV (Spatiu Privat Virtual) for submission.",
    },

    # ---- Turkey (TR) ----
    "TUR_VAT": {
        "description": "Turkish VAT (KDV) configuration — standard 20%, reduced 10%/1%, and KDV beyannamesi",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Turkey",
        "implementation_notes": "Standard 20%, reduced 10% (basic food, textile), 1% (agricultural, newspapers). Monthly KDV beyannamesi (VAT return). Handle reverse charge for specific services. Withholding KDV on designated sectors.",
    },
    "TUR_EFATURA": {
        "description": "Turkish e-Fatura mandatory electronic invoicing via GIB (Revenue Administration) portal",
        "sap_transaction": "SPRO > Turkey > e-Fatura",
        "implementation_notes": "Mandatory for companies with revenue > TRY 3M (2024 threshold). UBL-TR 1.2 format. GIB portal or special integrator submission. Inbound/outbound e-Fatura processing. Handle commercial vs basic e-Invoice.",
    },
    "TUR_EARSIV": {
        "description": "Turkish e-Arsiv Fatura electronic archive invoice for B2C and non-e-Fatura registered recipients",
        "sap_transaction": "SPRO > Turkey > e-Arsiv",
        "implementation_notes": "e-Arsiv for invoices to non-e-Fatura registered entities. Same technical format as e-Fatura. Must be issued for invoices > TRY 5,000 to non-registered. GIB portal reporting. 7-day archive requirement.",
    },
    "TUR_EDEFTER": {
        "description": "Turkish e-Defter (electronic bookkeeping) — monthly digital accounting books submission to GIB",
        "sap_transaction": "SPRO > Turkey > e-Defter",
        "implementation_notes": "Monthly Yevmiye (journal) and Defteri Kebir (general ledger) in XBRL-GL format. Digital signature and time stamp. Upload to GIB by end of 3rd month following the period. Berat (receipt) download.",
    },
    "TUR_SGK": {
        "description": "SGK (Social Security Institution) employer social insurance contribution and MUHSGK declaration",
        "sap_transaction": "SPRO > Payroll Turkey > SGK",
        "implementation_notes": "Employer ~20.5% + employee ~14% (social insurance + unemployment). Monthly MUHSGK (Muhtasar ve SGK bildirge) unified declaration combining withholding tax and social insurance. Handle SGK incentives and exemptions.",
    },

    # ---- Argentina (AR) ----
    "ARG_IVA": {
        "description": "Argentine IVA (Impuesto al Valor Agregado) configuration — standard 21%, reduced 10.5%/27%",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Argentina",
        "implementation_notes": "Standard 21%, reduced 10.5% (capital goods, transport, newspapers), differential 27% (utilities for non-residential). Monthly IVA filing via AFIP. Handle IVA withholding (percepcion/retencion) per provincial regimes.",
    },
    "ARG_AFIP": {
        "description": "AFIP (Administracion Federal de Ingresos Publicos) electronic invoicing and tax compliance",
        "sap_transaction": "SPRO > Argentina > AFIP / Factura Electronica",
        "implementation_notes": "Mandatory electronic invoicing via AFIP web services. CAE (Codigo de Autorizacion Electronico) per invoice. CUIT validation. Handle different invoice types (A, B, C, M). Regimen informativo de compras y ventas.",
    },
    "ARG_SUSS": {
        "description": "SUSS (Sistema Unico de la Seguridad Social) employer social security contribution reporting",
        "sap_transaction": "SPRO > Payroll Argentina > SUSS",
        "implementation_notes": "Employer contributions ~26% (jubilacion 12.71%, INSSJP 1.62%, asignaciones familiares 5.56%, fondo de empleo 1.11%, ART ~2.5%, obra social ~6%). Monthly F.931 declaration via AFIP SICOSS. Handle reductions per zone.",
    },
    "ARG_PERCEP": {
        "description": "Argentine perception taxes (percepciones) — withholding at source on sales per provincial and national regimes",
        "sap_transaction": "SPRO > Argentina > Percepciones",
        "implementation_notes": "IVA perception on sales per RG 2408. Ingresos Brutos (gross income tax) perception per province. Each province has different rates and regimes. Multiple SIFERE padrones. Automatic perception applicability check.",
    },
    "ARG_RETEN": {
        "description": "Argentine retention taxes (retenciones) — withholding on payments per national and provincial regimes",
        "sap_transaction": "SPRO > Financial Accounting > Withholding Tax > Argentina",
        "implementation_notes": "IVA retention per RG 2854. Ganancias (income tax) retention per RG 830. SIRE retention regime. Monthly SICORE filing. Handle exclusion certificates. Ingresos Brutos retention per provincial padron.",
    },

    # ---- Chile (CL) ----
    "CHL_IVA": {
        "description": "Chilean IVA (Impuesto al Valor Agregado) configuration — 19% standard rate",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Chile",
        "implementation_notes": "Standard rate 19%. Monthly F29 tax return. Handle IVA credito fiscal (input tax credit). Proporcional IVA for mixed supplies. Retention of IVA on specific services (e.g., construction).",
    },
    "CHL_SII": {
        "description": "SII (Servicio de Impuestos Internos) electronic invoicing and tax compliance",
        "sap_transaction": "SPRO > Chile > SII / DTE",
        "implementation_notes": "Mandatory electronic invoicing (DTE - Documento Tributario Electronico). Factura Electronica, Nota de Credito/Debito, Guia de Despacho. CAF (Codigo de Autorizacion de Folios) from SII. XML format per SII schema.",
    },
    "CHL_AFP": {
        "description": "Chilean AFP (Administradora de Fondos de Pensiones) pension contribution configuration",
        "sap_transaction": "SPRO > Payroll Chile > AFP",
        "implementation_notes": "Employee mandatory contribution 10% + AFP commission (~1.0-1.5%). Employer no mandatory pension contribution. Health insurance (Isapre/Fonasa) 7%. Monthly declaration via Previred. Handle voluntary pension savings (APV).",
    },
    "CHL_LIBRO": {
        "description": "Libro de Remuneraciones Electronico mandatory electronic payroll book",
        "sap_transaction": "SPRO > Payroll Chile > Libro de Remuneraciones",
        "implementation_notes": "Mandatory electronic payroll book since 2021 for companies > 5 employees. Monthly upload to Direccion del Trabajo. Standardized format. Individual employee detail records. Integration with Previred.",
    },

    # ---- Colombia (CO) ----
    "COL_IVA": {
        "description": "Colombian IVA (Impuesto al Valor Agregado) configuration — standard 19%, reduced 5%/0%",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Colombia",
        "implementation_notes": "Standard 19%, reduced 5% (specific food, medical equipment), excluded (basic food, education, health). Bimonthly/quarterly IVA filing. Handle ICA (Impuesto de Industria y Comercio) municipal tax. Autoretenciones.",
    },
    "COL_DIAN": {
        "description": "DIAN (Direccion de Impuestos y Aduanas Nacionales) electronic invoicing (Factura Electronica de Venta)",
        "sap_transaction": "SPRO > Colombia > DIAN / Factura Electronica",
        "implementation_notes": "Mandatory electronic invoicing via DIAN validation. UBL 2.1 format per DIAN specification. CUFE (Codigo Unico de Facturacion Electronica) per document. Technological provider or direct connection. Handle notas debito/credito.",
    },
    "COL_EPS": {
        "description": "Colombian EPS (Entidad Promotora de Salud) health insurance employer contributions",
        "sap_transaction": "SPRO > Payroll Colombia > EPS",
        "implementation_notes": "Employer 8.5% + employee 4% for health (salaries > 4 SMLMV). PILA (Planilla Integrada de Liquidacion de Aportes) integrated social security payment. Monthly filing via PILA operators.",
    },
    "COL_AFP": {
        "description": "Colombian AFP pension fund employer and employee contribution configuration",
        "sap_transaction": "SPRO > Payroll Colombia > AFP",
        "implementation_notes": "Employer 12% + employee 4% for pension. ARL (Administradora de Riesgos Laborales) employer only (0.522-6.96% based on risk). Caja de Compensacion 4% employer. Monthly PILA integrated declaration.",
    },

    # ---- Peru (PE) ----
    "PER_IGV": {
        "description": "Peruvian IGV (Impuesto General a las Ventas) configuration — 18% (16% IGV + 2% IPM)",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Peru",
        "implementation_notes": "IGV 16% + IPM 2% = 18% effective rate. Monthly PDT 621 filing to SUNAT. Handle IGV retention (agente de retencion) and perception regimes. Detracciones (spot system) for specific goods/services.",
    },
    "PER_SUNAT": {
        "description": "SUNAT (Superintendencia Nacional de Aduanas y Administracion Tributaria) electronic invoicing",
        "sap_transaction": "SPRO > Peru > SUNAT / Comprobantes Electronicos",
        "implementation_notes": "Mandatory electronic invoicing (CPE - Comprobante de Pago Electronico). Factura, Boleta, Nota de Credito/Debito. UBL 2.1 per SUNAT specification. OSE (Operador de Servicios Electronicos) or SOL portal submission. CDR response handling.",
    },
    "PER_ONP": {
        "description": "ONP (Oficina de Normalizacion Previsional) national pension system contribution",
        "sap_transaction": "SPRO > Payroll Peru > ONP",
        "implementation_notes": "Employee 13% for national pension system (ONP). Alternative: AFP (private pension) ~10% + insurance + commission. Employer no pension contribution. Monthly PDT-PLAME filing. Handle pension system choice by employee.",
    },
    "PER_AFP": {
        "description": "Peruvian AFP (Administradora de Fondo de Pensiones) private pension contribution configuration",
        "sap_transaction": "SPRO > Payroll Peru > AFP",
        "implementation_notes": "Employee contribution ~10% + insurance premium (~1.7%) + commission (mixed or flow-based). Four AFP providers with different rates. Monthly filing via AFPnet. Handle voluntary contributions.",
    },
    "PER_PLE": {
        "description": "PLE (Programa de Libros Electronicos) electronic accounting books mandatory filing to SUNAT",
        "sap_transaction": "SPRO > Peru > PLE",
        "implementation_notes": "Electronic accounting books: registro de compras, registro de ventas, libro diario, libro mayor. Monthly/annual filing depending on book type. TXT format per SUNAT specification. Handle registro de activos fijos.",
    },

    # ---- New Zealand (NZ) ----
    "NZL_GST": {
        "description": "New Zealand GST (Goods and Services Tax) configuration — standard 15% with Inland Revenue filing",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > New Zealand",
        "implementation_notes": "Standard rate 15%. Zero-rated (exports, financial services to non-residents). Exempt (financial services, residential rent). Monthly/bimonthly/six-monthly GST return periods. Handle GST on imported services.",
    },
    "NZL_IRD": {
        "description": "Inland Revenue Department (IRD) electronic filing — income tax, PAYE, and employer reporting",
        "sap_transaction": "SPRO > New Zealand > IRD / myIR",
        "implementation_notes": "myIR online filing for GST, income tax, employer schedules. Employment Information (EI) filing each pay day. IR3/IR4 annual tax returns. Provisional tax payments. Handle student loan and child support deductions.",
    },
    "NZL_KIWISAVER": {
        "description": "KiwiSaver workplace retirement savings scheme — employer and employee contribution configuration",
        "sap_transaction": "SPRO > Payroll New Zealand > KiwiSaver",
        "implementation_notes": "Employee contribution: 3%, 4%, 6%, 8%, or 10% of gross pay. Employer minimum 3%. Employer Superannuation Contribution Tax (ESCT). Handle opt-out and savings suspension. Report via Employment Information.",
    },
    "NZL_PAYDAY": {
        "description": "Payday filing — real-time employer payroll reporting to Inland Revenue each pay cycle",
        "sap_transaction": "SPRO > Payroll New Zealand > Payday Filing",
        "implementation_notes": "Mandatory payday filing: Employment Information within 2 working days of pay day. Employee details, gross earnings, PAYE, student loan, KiwiSaver, child support. Direct submission via myIR or payroll software integration.",
    },

    # ---- Nigeria (NG) ----
    "NGA_VAT": {
        "description": "Nigerian VAT configuration — 7.5% standard rate with FIRS filing",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Nigeria",
        "implementation_notes": "Standard rate 7.5%. Exempt (basic food, medical, educational, baby products). Monthly VAT return to FIRS by 21st. Handle WHT (Withholding Tax) on supplies to government. TaxProMax electronic filing.",
    },
    "NGA_FIRS": {
        "description": "FIRS (Federal Inland Revenue Service) tax compliance — CIT, withholding tax, and electronic filing",
        "sap_transaction": "SPRO > Nigeria > FIRS",
        "implementation_notes": "CIT 30% (standard), 20% (medium companies). WHT rates 5-10% per income type. Annual CIT filing. Monthly VAT and WHT returns. TaxProMax portal for electronic filing. TIN (Tax Identification Number) validation.",
    },
    "NGA_PENCOM": {
        "description": "PENCOM (National Pension Commission) contributory pension scheme configuration",
        "sap_transaction": "SPRO > Payroll Nigeria > PENCOM",
        "implementation_notes": "Employer minimum 10% + employee minimum 8% of monthly emolument. Remit to Pension Fund Administrator (PFA) via Pension Fund Custodian. Monthly contribution schedule. RSA (Retirement Savings Account) per employee.",
    },
    "NGA_TIN": {
        "description": "TIN (Tax Identification Number) validation and Joint Tax Board compliance",
        "sap_transaction": "XK01/XD01 > Tax Information",
        "implementation_notes": "Validate TIN format (10 digits + dash + 4 digits). FIRS TIN verification via TaxProMax API. Mandatory for all business transactions. Joint Tax Board for interstate tax coordination. Handle multiple tax IDs per entity.",
    },

    # ---- Kenya (KE) ----
    "KEN_VAT": {
        "description": "Kenyan VAT configuration — standard 16%, reduced 8%/0%, and KRA iTax filing",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Kenya",
        "implementation_notes": "Standard 16%, reduced 8% (petroleum products, specific fuels). Zero-rated (exports, specific goods). Exempt (financial services, education). Monthly VAT return via iTax. Handle Withholding VAT (2% on B2G).",
    },
    "KEN_TIMS": {
        "description": "TIMS (Tax Invoice Management System) — KRA electronic tax invoice management for VAT compliance",
        "sap_transaction": "SPRO > Kenya > TIMS",
        "implementation_notes": "Mandatory electronic tax invoice via TIMS/eTIMS. Real-time invoice transmission to KRA. Device-based (fiscal device) or system-based integration. QR code on invoices. Handle credit/debit notes via TIMS.",
    },
    "KEN_NHIF": {
        "description": "NHIF (National Hospital Insurance Fund) employer health insurance contribution",
        "sap_transaction": "SPRO > Payroll Kenya > NHIF",
        "implementation_notes": "Employee contribution based on salary bracket (KES 150-1,700/month). Employer deducts and remits. Monthly filing via NHIF portal. Handle SHA (Social Health Authority) transition. SHIF (Social Health Insurance Fund) replacing NHIF.",
    },
    "KEN_NSSF": {
        "description": "NSSF (National Social Security Fund) tier I and tier II pension contribution",
        "sap_transaction": "SPRO > Payroll Kenya > NSSF",
        "implementation_notes": "Tier I: employee 6% + employer 6% (on lower earnings limit). Tier II: employee 6% + employer 6% (between lower and upper earnings limits). Monthly contribution via NSSF portal. Handle upper earnings limit adjustments.",
    },
    "KEN_ITAX": {
        "description": "KRA iTax electronic filing platform — PAYE, CIT, VAT, and withholding tax returns",
        "sap_transaction": "SPRO > Kenya > iTax Filing",
        "implementation_notes": "Monthly PAYE (P10) filing by 9th. Monthly VAT by 20th. Monthly WHT by 20th. Annual CIT by 6th month after year-end. iTax PIN validation for all business partners. Handle turnover tax for small businesses.",
    },

    # ---- Egypt (EG) ----
    "EGY_VAT": {
        "description": "Egyptian VAT configuration — standard 14%, and Egyptian Tax Authority (ETA) filing",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Egypt",
        "implementation_notes": "Standard 14%. Table tax (5-10%) on specific goods. Exempt (financial services, education, health). Monthly VAT return. Handle withholding VAT on government payments. Schedule differential tax rates per product category.",
    },
    "EGY_ETA": {
        "description": "ETA (Egyptian Tax Authority) e-Invoice mandate — mandatory electronic invoicing via ETA portal",
        "sap_transaction": "SPRO > Egypt > ETA e-Invoice",
        "implementation_notes": "Mandatory e-Invoice for all B2B transactions (phased rollout completed). JSON format submission to ETA portal. Digital signature (token/HSM). UUID per document. Handle e-Receipt for B2C. ETA SDK integration.",
    },
    "EGY_SI": {
        "description": "Egyptian Social Insurance contributions — employer and employee under unified social insurance law",
        "sap_transaction": "SPRO > Payroll Egypt > Social Insurance",
        "implementation_notes": "Employer ~18.75% + employee ~11% on insurable salary. Salary ceiling for contributions. Monthly contribution filing. Handle new social insurance law (Law 148/2019) phased salary ceiling increases.",
    },
    "EGY_UNIFIED_TAX": {
        "description": "Egyptian unified tax procedures law and electronic tax filing via ETA online portal",
        "sap_transaction": "SPRO > Egypt > ETA Tax Filing",
        "implementation_notes": "Corporate income tax 22.5%. Monthly payroll tax (salary tax) filing. Annual corporate tax return. Unified tax procedures law for streamlined compliance. ETA online portal for electronic filing. TIN registration and validation.",
    },

    # ---- Croatia (HR) ----
    "HRV_VAT": {
        "description": "Croatian VAT (PDV) configuration — standard 25%, reduced 13%/5%",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Croatia",
        "implementation_notes": "Standard 25%, reduced 13% (hospitality, food), super-reduced 5% (bread, milk, books). Quarterly VAT return. EU reverse charge for B2B. Intra-Community supply reporting.",
    },
    "HRV_FISKALIZACIJA": {
        "description": "Croatian fiscalization — mandatory real-time invoice registration with Tax Administration",
        "sap_transaction": "SPRO > Croatia > Fiscalization",
        "implementation_notes": "All invoices must be fiscalized in real-time with Porezna Uprava. Digital certificate (FINA) for signing. JIR (unique identifier) received per invoice. Offline mode with manual registration within 48h.",
    },
    "HRV_HZZO": {
        "description": "Croatian health insurance (HZZO) and social contributions",
        "sap_transaction": "SPRO > Payroll Croatia > Social Insurance",
        "implementation_notes": "Employer contributions ~16.5% (pension 1st pillar). Employee pension 2nd pillar 5%. HZZO health contribution 16.5%. JOPPD monthly report to Tax Authority.",
    },
    "HRV_JOPPD": {
        "description": "JOPPD payroll reporting — unified form for income, tax, and contributions",
        "sap_transaction": "SPRO > Croatia > JOPPD",
        "implementation_notes": "Monthly JOPPD form replaces multiple legacy reports. Reports salary income, tax withheld, pension/health contributions. XML submission to ePorezna portal.",
    },

    # ---- Bulgaria (BG) ----
    "BGR_VAT": {
        "description": "Bulgarian VAT (DDS) configuration — standard 20%, reduced 9%",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Bulgaria",
        "implementation_notes": "Standard 20%, reduced 9% (hospitality, books, baby products). VAT registration threshold BGN 100,000. Monthly VAT return + purchase/sales ledgers to NRA. Reverse charge for construction services.",
    },
    "BGR_NSSI": {
        "description": "Bulgarian NSSI social insurance contributions",
        "sap_transaction": "SPRO > Payroll Bulgaria > Social Insurance",
        "implementation_notes": "Total social insurance ~32% split employer/employee. Pension (DOO), health (ZO), unemployment, labor accident funds. Minimum insurance thresholds per profession. Monthly Declaration 1 and Declaration 6 to NRA.",
    },
    "BGR_NAP": {
        "description": "Bulgarian National Revenue Agency (NAP) electronic filing",
        "sap_transaction": "SPRO > Bulgaria > NAP",
        "implementation_notes": "Annual corporate tax return. Monthly VAT filing. Declaration 1/6 for payroll. Electronic filing via NAP portal with digital signature (B-Trust/Evrotrust).",
    },
    "BGR_EFAKTURA": {
        "description": "Bulgarian e-invoicing — upcoming mandate for B2G and B2B",
        "sap_transaction": "SPRO > Bulgaria > e-Faktura",
        "implementation_notes": "B2G e-invoicing via national e-invoicing platform. B2B mandate planned. Peppol-based format. Integration with SAP Document Compliance.",
    },

    # ---- Slovenia (SI) ----
    "SVN_VAT": {
        "description": "Slovenian VAT (DDV) configuration — standard 22%, reduced 9.5%",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Slovenia",
        "implementation_notes": "Standard 22%, reduced 9.5% (food, pharmaceuticals, books). Monthly/quarterly VAT return. EU Intrastat reporting. Reverse charge for construction and telecom.",
    },
    "SVN_FURS": {
        "description": "Slovenian FURS fiscal verification — mandatory cash register fiscalization",
        "sap_transaction": "SPRO > Slovenia > FURS",
        "implementation_notes": "All cash transactions must be fiscalized with FURS in real-time. Digital certificate for signing. EOR (unique identifier) per invoice. Applies to B2C and certain B2B cash payments.",
    },
    "SVN_ERACUN": {
        "description": "Slovenian eRacun — mandatory B2G e-invoicing via UJP portal",
        "sap_transaction": "SPRO > Slovenia > eRacun",
        "implementation_notes": "B2G invoices mandatory via UJP (Public Payments) portal. eSlog 2.0 XML format. Peppol supported. B2B e-invoicing voluntary but growing adoption.",
    },
    "SVN_ZPIZ": {
        "description": "Slovenian pension and disability insurance (ZPIZ) contributions",
        "sap_transaction": "SPRO > Payroll Slovenia > Social Insurance",
        "implementation_notes": "Employer pension ~8.85% + employee ~15.5%. Health insurance ZZZS: employer 6.56% + employee 6.36%. Monthly payroll reporting via REK-O form.",
    },

    # ---- Lithuania (LT) ----
    "LTU_VAT": {
        "description": "Lithuanian VAT (PVM) configuration — standard 21%, reduced 9%/5%",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Lithuania",
        "implementation_notes": "Standard 21%, reduced 9% (heating, newspapers), 5% (pharmaceuticals). Monthly VAT return via VMI portal. EU Intrastat/EC Sales list. Reverse charge for metals scrap.",
    },
    "LTU_ISAF": {
        "description": "Lithuanian i.SAF — mandatory purchase/sales invoice register",
        "sap_transaction": "SPRO > Lithuania > i.SAF",
        "implementation_notes": "Monthly i.SAF XML submission listing all issued and received invoices above threshold. Replaced previous VAT register format. XML schema defined by VMI. Integration with SAP Document Compliance.",
    },
    "LTU_SODRA": {
        "description": "Lithuanian SODRA social insurance contributions",
        "sap_transaction": "SPRO > Payroll Lithuania > Social Insurance",
        "implementation_notes": "Employer social insurance ~1.77% (reduced from previous ~31%). Employee 19.5% (pension 8.72%, health 6.98%, sickness 2.09%, unemployment 1.71%). Monthly SODRA reporting via portal.",
    },
    "LTU_VMI": {
        "description": "Lithuanian State Tax Inspectorate (VMI) electronic filing",
        "sap_transaction": "SPRO > Lithuania > VMI",
        "implementation_notes": "Monthly/annual tax returns via VMI portal. i.SAF for VAT. GPM312 for personal income tax. FR0600 for annual corporate income tax (15%). Digital signature required.",
    },

    # ---- Latvia (LV) ----
    "LVA_VAT": {
        "description": "Latvian VAT (PVN) configuration — standard 21%, reduced 12%/5%",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Latvia",
        "implementation_notes": "Standard 21%, reduced 12% (medical, domestic heating), 5% (fruits, vegetables). Monthly VAT return via VID EDS portal. Reverse charge for metals, construction.",
    },
    "LVA_VID": {
        "description": "Latvian State Revenue Service (VID) electronic filing",
        "sap_transaction": "SPRO > Latvia > VID",
        "implementation_notes": "Monthly PVN declaration. Annual CIT return (20% on distributed profits, 0% on retained). Monthly payroll reports via EDS portal. Digital signature required.",
    },
    "LVA_VSAOI": {
        "description": "Latvian mandatory social insurance (VSAOI) contributions",
        "sap_transaction": "SPRO > Payroll Latvia > Social Insurance",
        "implementation_notes": "Total VSAOI ~34.09%: employer ~23.59%, employee ~10.5%. Covers pension, disability, unemployment, maternity. Monthly reporting via VID EDS.",
    },
    "LVA_EADDRESS": {
        "description": "Latvian e-Address — government electronic communication platform",
        "sap_transaction": "SPRO > Latvia > e-Address",
        "implementation_notes": "Electronic document exchange with government authorities. Integration for receiving tax notices, submitting replies. Latvija.lv platform integration.",
    },

    # ---- Estonia (EE) ----
    "EST_VAT": {
        "description": "Estonian VAT (KM) configuration — standard 22%, reduced 9%",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Estonia",
        "implementation_notes": "Standard 22% (increased from 20%), reduced 9% (press, accommodation, pharmaceuticals). Monthly VAT return via EMTA e-Tax portal. EU Intrastat reporting.",
    },
    "EST_EMTA": {
        "description": "Estonian Tax and Customs Board (EMTA) electronic filing",
        "sap_transaction": "SPRO > Estonia > EMTA",
        "implementation_notes": "Monthly TSD (income and social tax) return. Appendix formats INF 1-14. Annual CIT return (20% on distributions, 14% for regular dividends). e-Tax environment with ID card / Mobile-ID authentication.",
    },
    "EST_TSD": {
        "description": "Estonian TSD — monthly payroll tax and social tax reporting",
        "sap_transaction": "SPRO > Payroll Estonia > TSD",
        "implementation_notes": "Social tax 33% (employer only). Unemployment insurance: employer 0.8%, employee 1.6%. Funded pension 2% employee. Monthly TSD declaration via EMTA e-Tax.",
    },
    "EST_EARVELDUS": {
        "description": "Estonian e-invoicing — e-arveldus platform for B2G and B2B",
        "sap_transaction": "SPRO > Estonia > e-Arveldus",
        "implementation_notes": "B2G e-invoicing mandatory via e-arveldus platform. Estonian e-invoice standard (based on OASIS UBL). Peppol network supported. B2B adoption growing via operator model.",
    },

    # ---- Luxembourg (LU) ----
    "LUX_VAT": {
        "description": "Luxembourg VAT (TVA) configuration — standard 17%, reduced 14%/8%/3%",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Luxembourg",
        "implementation_notes": "Standard 17% (one of lowest in EU), intermediate 14%, reduced 8%, super-reduced 3% (food, books, medicine). Monthly/quarterly/annual VAT return depending on turnover. EU Intrastat.",
    },
    "LUX_ECDF": {
        "description": "Luxembourg eCDF — electronic filing platform for tax returns",
        "sap_transaction": "SPRO > Luxembourg > eCDF",
        "implementation_notes": "Mandatory electronic filing via eCDF platform. Annual income tax (IRC), municipal business tax (ICC), net wealth tax. XBRL format for financial statements. LuxTrust authentication.",
    },
    "LUX_CNS": {
        "description": "Luxembourg social security (CNS/CCSS) contributions",
        "sap_transaction": "SPRO > Payroll Luxembourg > Social Insurance",
        "implementation_notes": "Total social insurance ~25% split equally employer/employee (~12.5% each). Covers pension, health (CNS), dependency, accident. Monthly declaration to CCSS. Minimum social wage considerations.",
    },
    "LUX_PEPPOL": {
        "description": "Luxembourg Peppol e-invoicing for B2G",
        "sap_transaction": "SPRO > Luxembourg > Peppol",
        "implementation_notes": "B2G e-invoicing via Peppol network. EN 16931 compliant format. Mandatory for public procurement contracts. Access point integration required.",
    },

    # ---- Slovakia (SK) ----
    "SVK_VAT": {
        "description": "Slovak VAT (DPH) configuration — standard 20%, reduced 10%",
        "sap_transaction": "SPRO > Tax on Sales/Purchases > Slovakia",
        "implementation_notes": "Standard 20%, reduced 10% (food, pharmaceuticals, books). Monthly VAT return for turnover > EUR 100K, quarterly otherwise. Control statement (KV DPH) mandatory. EU Intrastat.",
    },
    "SVK_EKASA": {
        "description": "Slovak eKasa — mandatory online cash register system",
        "sap_transaction": "SPRO > Slovakia > eKasa",
        "implementation_notes": "All cash register transactions transmitted in real-time to Financial Administration (FSSR). Online or virtual cash register. Unique identifier (OKP/PKP) per receipt. Applies to all B2C cash sales.",
    },
    "SVK_SP": {
        "description": "Slovak Social Insurance Agency (Socialná poisťovňa) contributions",
        "sap_transaction": "SPRO > Payroll Slovakia > Social Insurance",
        "implementation_notes": "Employer ~35.2% (pension 14%, health 10%, sickness 1.4%, unemployment 1%, guarantee 0.25%, reserve 4.75%, accident 0.8%). Employee ~13.4%. Monthly reporting to SP portal.",
    },
    "SVK_FINSTAT": {
        "description": "Slovak financial statements filing via Finstat/Register of Financial Statements",
        "sap_transaction": "SPRO > Slovakia > Financial Statements",
        "implementation_notes": "Annual financial statements filed to Register of Financial Statements (RUZ). XBRL format. Corporate income tax 21%. Mandatory electronic filing via slovensko.sk portal with eID.",
    },
}


def determine_regional_requirements(company_code: str) -> List[str]:
    """
    Determines which compliance modules to load based on strict SPRO
    country links. Looks up the company code's country, then returns
    all applicable compliance modules including EU-wide modules for
    EU member states.
    """
    country = COMPANY_CODE_REGIONS.get(company_code, "UNKNOWN")
    logger.info(f"Target BUKRS {company_code} mapped to Country Code: {country}")

    if country == "UNKNOWN":
        logger.warning(f"No country mapping found for company code {company_code}")
        return []

    compliance_modules = list(COUNTRY_COMPLIANCE_MODULES.get(country, []))

    # EU member states also get the EU-wide compliance modules
    if country in EU_MEMBER_STATES:
        eu_modules = COUNTRY_COMPLIANCE_MODULES.get("EU", [])
        for module in eu_modules:
            if module not in compliance_modules:
                compliance_modules.append(module)

    return compliance_modules


def get_compliance_module_details(module_code: str) -> Optional[Dict[str, str]]:
    """
    Returns the full details for a given compliance module code.

    Args:
        module_code: The compliance module identifier (e.g. "GST_SETUP", "MTD_VAT").

    Returns:
        A dictionary with keys 'description', 'sap_transaction', and
        'implementation_notes', or None if the module code is not found.
    """
    return MODULE_DETAILS.get(module_code)


def get_all_modules_for_country(country_code: str) -> Dict[str, Dict[str, str]]:
    """
    Returns full details for every compliance module applicable to a country.

    Args:
        country_code: ISO 2-letter country code (e.g. "IN", "US", "DE").

    Returns:
        Dictionary keyed by module code, each value containing the module's
        description, SAP transaction, and implementation notes.
    """
    module_codes = list(COUNTRY_COMPLIANCE_MODULES.get(country_code, []))

    # Include EU-wide modules for EU member states
    if country_code in EU_MEMBER_STATES:
        eu_modules = COUNTRY_COMPLIANCE_MODULES.get("EU", [])
        for module in eu_modules:
            if module not in module_codes:
                module_codes.append(module)

    result = {}
    for code in module_codes:
        details = MODULE_DETAILS.get(code)
        if details:
            result[code] = details
        else:
            result[code] = {
                "description": f"Compliance module {code} — details pending",
                "sap_transaction": "TBD",
                "implementation_notes": "Configuration details to be documented.",
            }
    return result


def generate_spro_payload(company_codes: List[str]) -> Dict[str, Any]:
    """
    Generates the dynamic JSON payload passed from config-replicator (Stage 4)
    to config-applier (Stage 10) for automated SPRO configuration application.

    Includes both the module list and full module details for each company code
    so that Stage 10 has everything it needs for unattended configuration.
    """
    master_config_plan: Dict[str, Any] = {
        "global_settings": {
            "fiscal_year_variant": "K4",
            "leading_ledger": "0L",
        },
        "regional_settings": {},
    }

    for bukrs in company_codes:
        required_modules = determine_regional_requirements(bukrs)
        country = COMPANY_CODE_REGIONS.get(bukrs, "UNKNOWN")
        master_config_plan["regional_settings"][bukrs] = {
            "country_code": country,
            "modules_to_activate": required_modules,
            "module_count": len(required_modules),
            "module_details": {
                mod: MODULE_DETAILS.get(mod, {})
                for mod in required_modules
            },
            "status": "PENDING_STAGE_10",
        }
        logger.info(
            f"Generated regional payload for {bukrs} ({country}): "
            f"{len(required_modules)} modules — {required_modules}"
        )

    return master_config_plan
