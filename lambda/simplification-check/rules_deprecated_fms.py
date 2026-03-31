"""
Migrate4HANA - Deprecated Function Modules Simplification Rules
================================================================
200 rules covering SAP function modules that are deprecated, removed,
or have changed signatures/behavior in S/4HANA.

Reference: SAP Note 2270689 - S/4HANA Custom Code Adaptation
"""

DEPRECATED_FM_RULES = {
    "FM_001": {
        "title": "BAPI_ACC_DOCUMENT_POST Adapted for ACDOCA",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_ACC_DOCUMENT_POST still works but posts to ACDOCA instead of BSEG. "
            "Extension structures changed. EXTENSION1 parameter deprecated in favor "
            "of EXTENSION2."
        ),
        "severity": "YELLOW",
        "affected_tables": ['ACDOCA', 'BKPF'],
        "affected_transactions": ['FB01', 'SE37'],
        "remediation": "Review EXTENSION1 usage. Migrate to EXTENSION2. Test posting to ACDOCA.",
        "effort_hours": 24,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "FM_002": {
        "title": "BAPI_ACC_GL_POSTING_POST Adapted for ACDOCA",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_ACC_GL_POSTING_POST adapted for Universal Journal. GL posting "
            "creates ACDOCA entries. Some parameters deprecated."
        ),
        "severity": "YELLOW",
        "affected_tables": ['ACDOCA'],
        "affected_transactions": ['FB01', 'SE37'],
        "remediation": "Test GL posting scenarios. Review parameter usage for ACDOCA compatibility.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "FM_003": {
        "title": "BAPI_ACC_INVOICE_RECEIPT_POST Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_ACC_INVOICE_RECEIPT_POST adapted for ACDOCA. Invoice receipt "
            "posting creates ACDOCA line items."
        ),
        "severity": "YELLOW",
        "affected_tables": ['ACDOCA', 'RBKP'],
        "affected_transactions": ['MIRO', 'SE37'],
        "remediation": "Test invoice receipt posting. Verify ACDOCA entries.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "FM_004": {
        "title": "BAPI_ACC_DOCUMENT_REV_POST Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_ACC_DOCUMENT_REV_POST adapted for ACDOCA reversal. Reversal creates "
            "offsetting ACDOCA entries."
        ),
        "severity": "YELLOW",
        "affected_tables": ['ACDOCA', 'BKPF'],
        "affected_transactions": ['FB08', 'SE37'],
        "remediation": "Test document reversal. Verify ACDOCA reversal entries.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "FM_005": {
        "title": "FI_DOCUMENT_CHANGE Restricted in S/4HANA",
        "category": "Deprecated Function Modules",
        "description": (
            "FI_DOCUMENT_CHANGE is restricted. Direct BSEG changes not possible since "
            "BSEG is a view on ACDOCA. Only header-level changes allowed."
        ),
        "severity": "RED",
        "affected_tables": ['BSEG', 'ACDOCA'],
        "affected_transactions": ['FB02', 'SE37'],
        "remediation": "Replace FI_DOCUMENT_CHANGE with BAPI_ACC_DOCUMENT_POST for corrections or use FB02 for allowed header changes.",
        "effort_hours": 24,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "FM_006": {
        "title": "FI_DOCUMENT_POST Restricted in S/4HANA",
        "category": "Deprecated Function Modules",
        "description": (
            "FI_DOCUMENT_POST is restricted. Should use BAPI_ACC_DOCUMENT_POST for "
            "programmatic FI document creation."
        ),
        "severity": "RED",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "Replace FI_DOCUMENT_POST with BAPI_ACC_DOCUMENT_POST.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "FM_007": {
        "title": "CALCULATE_TAX_FROM_NET_AMOUNT Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "CALCULATE_TAX_FROM_NET_AMOUNT still works but tax calculation adapted "
            "for S/4HANA tax engine changes."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "Test tax calculation scenarios. No code change needed unless custom tax logic.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "FM_008": {
        "title": "CALCULATE_TAX_FROM_GROSSAMOUNT Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "CALCULATE_TAX_FROM_GROSSAMOUNT adapted alongside net amount calculation "
            "for S/4HANA."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "Test gross-to-net tax calculation. Verify with country-specific tax procedures.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "FM_009": {
        "title": "GET_CLEARED_ITEMS Adapted for ACDOCA",
        "category": "Deprecated Function Modules",
        "description": (
            "GET_CLEARED_ITEMS reads from ACDOCA instead of BSAD/BSAK. Performance "
            "may differ."
        ),
        "severity": "YELLOW",
        "affected_tables": ['ACDOCA'],
        "affected_transactions": ['SE37'],
        "remediation": "Test performance of cleared item retrieval. Consider CDS view alternatives.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "FM_010": {
        "title": "GET_OPEN_FI_ITEMS Adapted for ACDOCA",
        "category": "Deprecated Function Modules",
        "description": (
            "GET_OPEN_FI_ITEMS reads from ACDOCA instead of BSID/BSIK. Performance "
            "may differ due to ACDOCA size."
        ),
        "severity": "YELLOW",
        "affected_tables": ['ACDOCA'],
        "affected_transactions": ['SE37'],
        "remediation": "Test open item retrieval performance. Consider I_JOURNALENTRYITEM CDS view.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "FM_011": {
        "title": "BAPI_GL_BALANCE_GET Adapted for ACDOCA",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_GL_BALANCE_GET reads balances from ACDOCA aggregation instead of "
            "GLT0. Results may include additional ledger data."
        ),
        "severity": "YELLOW",
        "affected_tables": ['ACDOCA'],
        "affected_transactions": ['SE37'],
        "remediation": "Test GL balance retrieval. Verify ledger parameter usage.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2272189",
    },
    "FM_012": {
        "title": "OPEN_FI_PERFORM_00002380_E Deprecated",
        "category": "Deprecated Function Modules",
        "description": (
            "OPEN_FI_PERFORM_00002380_E (FI substitution/validation exit) deprecated. "
            "Use BAdI FAGL_POSTING for document posting exits."
        ),
        "severity": "RED",
        "affected_tables": [],
        "affected_transactions": ['GGB1', 'SE37'],
        "remediation": "Replace with BAdI FAGL_POSTING or BADI_ACC_DOCUMENT.",
        "effort_hours": 24,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "FM_013": {
        "title": "OPEN_FI_PERFORM_00002380_P Deprecated",
        "category": "Deprecated Function Modules",
        "description": (
            "OPEN_FI_PERFORM_00002380_P (FI substitution/validation exit for parking) "
            "deprecated. Use BAdI for parking scenarios."
        ),
        "severity": "RED",
        "affected_tables": [],
        "affected_transactions": ['GGB1', 'SE37'],
        "remediation": "Replace with BAdI BADI_ACC_DOCUMENT for parking.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "FM_014": {
        "title": "FAGL_GET_OPEN_ITEMS Adapted for ACDOCA",
        "category": "Deprecated Function Modules",
        "description": (
            "FAGL_GET_OPEN_ITEMS reads from ACDOCA. New GL open item retrieval "
            "adapted for Universal Journal."
        ),
        "severity": "YELLOW",
        "affected_tables": ['ACDOCA'],
        "affected_transactions": ['SE37'],
        "remediation": "Test open item retrieval from ACDOCA. Review performance.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "FM_015": {
        "title": "FI_PERIOD_DETERMINE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "FI_PERIOD_DETERMINE still works. Period determination logic enhanced for "
            "parallel ledgers."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "No change needed unless custom fiscal year variant logic.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "FM_016": {
        "title": "FI_PERIOD_CHECK Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "FI_PERIOD_CHECK enhanced for ledger-specific period control in S/4HANA."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['OB52', 'SE37'],
        "remediation": "Review period open/close logic for ledger-specific control.",
        "effort_hours": 4,
        "responsible_team": "Functional",
        "sap_note": "2253416",
    },
    "FM_017": {
        "title": "BAPI_FIXEDASSET_CREATE Adapted for New AA",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_FIXEDASSET_CREATE adapted for New Asset Accounting. New "
            "depreciation area structure. ANLP/ANLC eliminated."
        ),
        "severity": "YELLOW",
        "affected_tables": ['ANLA', 'ACDOCA'],
        "affected_transactions": ['AS01', 'SE37'],
        "remediation": "Test asset creation. Verify depreciation area configuration for new AA.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2253616",
    },
    "FM_018": {
        "title": "BAPI_FIXEDASSET_CHANGE Adapted for New AA",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_FIXEDASSET_CHANGE adapted. Asset master changes reflect new asset "
            "accounting field structure."
        ),
        "severity": "YELLOW",
        "affected_tables": ['ANLA'],
        "affected_transactions": ['AS02', 'SE37'],
        "remediation": "Test asset change scenarios. Review field mapping for new AA.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2253616",
    },
    "FM_019": {
        "title": "BAPI_FIXEDASSET_GETDETAIL Adapted for New AA",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_FIXEDASSET_GETDETAIL returns data from new asset accounting "
            "structure. ANLC/ANLP-based fields changed."
        ),
        "severity": "YELLOW",
        "affected_tables": ['ANLA', 'ACDOCA'],
        "affected_transactions": ['AS03', 'SE37'],
        "remediation": "Adapt callers for new output structure. Depreciation values from ACDOCA.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2253616",
    },
    "FM_020": {
        "title": "RW_COST_ELEMENT_GETDETAIL Eliminated",
        "category": "Deprecated Function Modules",
        "description": (
            "RW_COST_ELEMENT_GETDETAIL is obsolete. Cost elements merged with GL "
            "accounts. Use GL account APIs."
        ),
        "severity": "RED",
        "affected_tables": ['COKA', 'SKA1'],
        "affected_transactions": ['KA03', 'SE37'],
        "remediation": "Replace with BAPI_GL_GETGLACCOUNTDETAIL or direct SKA1/SKAT read.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_021": {
        "title": "BAPI_COSTCENTER_CREATEMULTIPLE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_COSTCENTER_CREATEMULTIPLE adapted for ACDOCA integration. Cost "
            "center postings go to Universal Journal."
        ),
        "severity": "YELLOW",
        "affected_tables": ['CSKS', 'ACDOCA'],
        "affected_transactions": ['KS01', 'SE37'],
        "remediation": "Test cost center creation with ACDOCA. Review custom exits.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_022": {
        "title": "BAPI_COSTCENTER_GETDETAIL Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_COSTCENTER_GETDETAIL adapted. Some output fields deprecated with "
            "cost element/GL merge."
        ),
        "severity": "YELLOW",
        "affected_tables": ['CSKS', 'CSKT'],
        "affected_transactions": ['KS03', 'SE37'],
        "remediation": "Review output field usage for deprecated cost element references.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_023": {
        "title": "BAPI_INTERNALORDER_CREATE Adapted for ACDOCA",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_INTERNALORDER_CREATE adapted. Settlement rules post to ACDOCA. "
            "Order creation parameters adjusted."
        ),
        "severity": "YELLOW",
        "affected_tables": ['AUFK', 'ACDOCA'],
        "affected_transactions": ['KO01', 'SE37'],
        "remediation": "Test internal order creation and settlement to ACDOCA.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_024": {
        "title": "BAPI_INTERNALORDER_GETDETAIL Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_INTERNALORDER_GETDETAIL adapted for S/4HANA order structure "
            "changes."
        ),
        "severity": "GREEN",
        "affected_tables": ['AUFK'],
        "affected_transactions": ['KO03', 'SE37'],
        "remediation": "Review output structure usage.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_025": {
        "title": "BAPI_PROFITCENTER_CREATE Adapted for ACDOCA",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_PROFITCENTER_CREATE adapted. Profit center accounting fully in "
            "ACDOCA. GLPCA eliminated."
        ),
        "severity": "YELLOW",
        "affected_tables": ['CEPC', 'ACDOCA'],
        "affected_transactions": ['KE51', 'SE37'],
        "remediation": "Test profit center creation. Review GLPCA-related logic.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_026": {
        "title": "BAPI_CREDITCHECK_GETINFO → UKM APIs",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_CREDITCHECK_GETINFO is obsolete. SAP Credit Management (UKM) "
            "replaces classic credit management."
        ),
        "severity": "RED",
        "affected_tables": ['KNKK', 'UKM_BUPA'],
        "affected_transactions": ['FD32', 'SE37'],
        "remediation": "Replace with UKM_BUPA_CREDIT_DATA_GET or UKM API methods.",
        "effort_hours": 24,
        "responsible_team": "ABAP dev",
        "sap_note": "2265093",
    },
    "FM_027": {
        "title": "CREDIT_LIMIT_CHECK → UKM_CREDITLIMIT_CHECK",
        "category": "Deprecated Function Modules",
        "description": (
            "CREDIT_LIMIT_CHECK is replaced by UKM_CREDITLIMIT_CHECK for S/4HANA "
            "credit management."
        ),
        "severity": "RED",
        "affected_tables": ['KNKK', 'UKM_LIMIT'],
        "affected_transactions": ['SE37'],
        "remediation": "Replace CREDIT_LIMIT_CHECK with UKM_CREDITLIMIT_CHECK.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2265093",
    },
    "FM_028": {
        "title": "K_KOSTEN_ELEMENT_SELECT Eliminated",
        "category": "Deprecated Function Modules",
        "description": (
            "K_KOSTEN_ELEMENT_SELECT is obsolete. Cost elements merged with GL "
            "accounts. No separate cost element selection."
        ),
        "severity": "RED",
        "affected_tables": ['COKA', 'SKA1'],
        "affected_transactions": ['SE37'],
        "remediation": "Replace with GL account selection via SKA1 or CDS view I_CHARTOFACCOUNTS.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_029": {
        "title": "CLOI_PUT_SIGN_IN_FRONT Obsolete",
        "category": "Deprecated Function Modules",
        "description": (
            "CLOI_PUT_SIGN_IN_FRONT is obsolete. Was used for sign formatting. Use "
            "ABAP string operations instead."
        ),
        "severity": "YELLOW",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "Replace with simple ABAP SHIFT/CONCATENATE or string template for sign positioning.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_030": {
        "title": "BAPI_ACC_ACTIVITY_ALLOC_POST Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_ACC_ACTIVITY_ALLOC_POST adapted for ACDOCA. Activity allocation "
            "posts to Universal Journal."
        ),
        "severity": "YELLOW",
        "affected_tables": ['ACDOCA'],
        "affected_transactions": ['KB21N', 'SE37'],
        "remediation": "Test activity allocation posting to ACDOCA.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "FM_031": {
        "title": "BAPI_ACC_MANUAL_ALLOC_POST Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_ACC_MANUAL_ALLOC_POST adapted for ACDOCA-based CO manual cost "
            "allocation."
        ),
        "severity": "YELLOW",
        "affected_tables": ['ACDOCA'],
        "affected_transactions": ['KB11N', 'SE37'],
        "remediation": "Test manual allocation posting. Verify ACDOCA entries.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "FM_032": {
        "title": "BAPI_ACC_PRIMARY_COSTS_POST Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_ACC_PRIMARY_COSTS_POST adapted for ACDOCA. Primary cost reposting "
            "creates ACDOCA entries."
        ),
        "severity": "YELLOW",
        "affected_tables": ['ACDOCA'],
        "affected_transactions": ['KB41N', 'SE37'],
        "remediation": "Test primary cost reposting to ACDOCA.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "FM_033": {
        "title": "BAPI_ACC_STAT_KEY_FIG_POST Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_ACC_STAT_KEY_FIG_POST adapted for ACDOCA integration of statistical "
            "key figure postings."
        ),
        "severity": "GREEN",
        "affected_tables": ['ACDOCA'],
        "affected_transactions": ['KB31N', 'SE37'],
        "remediation": "Test statistical key figure posting.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "FM_034": {
        "title": "BAPI_GL_GETGLACCOUNT_EXISTCHK Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_GL_GETGLACCOUNT_EXISTCHK adapted. Checks against unified GL/cost "
            "element account."
        ),
        "severity": "GREEN",
        "affected_tables": ['SKA1'],
        "affected_transactions": ['FS00', 'SE37'],
        "remediation": "No change needed. GL account concept includes cost elements.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_035": {
        "title": "BAPI_GL_GETGLACCOUNTDETAIL Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_GL_GETGLACCOUNTDETAIL enhanced to return cost element category as "
            "GL account attribute."
        ),
        "severity": "GREEN",
        "affected_tables": ['SKA1', 'SKAT'],
        "affected_transactions": ['FS00', 'SE37'],
        "remediation": "Review output fields for cost element category attribute.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_036": {
        "title": "FI_ITEMS_MASS_CHANGE Restricted",
        "category": "Deprecated Function Modules",
        "description": (
            "FI_ITEMS_MASS_CHANGE restricted since BSEG is a view. Mass line item "
            "changes via ACDOCA not supported."
        ),
        "severity": "RED",
        "affected_tables": ['BSEG', 'ACDOCA'],
        "affected_transactions": ['SE37'],
        "remediation": "Replace with reversal and reposting approach.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "FM_037": {
        "title": "FI_TAX_GET_NONTAXABLE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "FI_TAX_GET_NONTAXABLE adapted for S/4HANA tax engine changes. "
            "Non-taxable determination logic updated."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "Test non-taxable scenarios with S/4HANA tax engine.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "FM_038": {
        "title": "FIMA_DAYS_AND_MONTHS_AND_YEARS Still Works",
        "category": "Deprecated Function Modules",
        "description": (
            "FIMA_DAYS_AND_MONTHS_AND_YEARS (date calculation) still works. No change "
            "needed."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "No action required. FM continues to work.",
        "effort_hours": 2,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_039": {
        "title": "CONVERT_TO_LOCAL_CURRENCY Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "CONVERT_TO_LOCAL_CURRENCY adapted for S/4HANA currency handling. TCURR "
            "access unchanged."
        ),
        "severity": "GREEN",
        "affected_tables": ['TCURR'],
        "affected_transactions": ['SE37'],
        "remediation": "Test currency conversion with S/4HANA exchange rate handling.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2272189",
    },
    "FM_040": {
        "title": "BAPI_COMPANYCODE_GETDETAIL Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_COMPANYCODE_GETDETAIL enhanced with new S/4HANA fields for extended "
            "ledger and currency settings."
        ),
        "severity": "GREEN",
        "affected_tables": ['T001'],
        "affected_transactions": ['SE37'],
        "remediation": "Review output for new S/4HANA company code fields.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2272189",
    },
    "FM_041": {
        "title": "BAPI_SALESORDER_CREATEFROMDAT2 Pricing Changed",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_SALESORDER_CREATEFROMDAT2 adapted. Pricing conditions stored in "
            "PRCD_ELEMENTS instead of KONV. Condition import tables changed."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBAK', 'PRCD_ELEMENTS'],
        "affected_transactions": ['VA01', 'SE37'],
        "remediation": "Test sales order creation. Adapt condition handling for PRCD_ELEMENTS.",
        "effort_hours": 24,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_042": {
        "title": "BAPI_SALESORDER_CHANGE Pricing Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_SALESORDER_CHANGE adapted for PRCD_ELEMENTS pricing model. "
            "Condition change logic must use new structure."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBAK', 'PRCD_ELEMENTS'],
        "affected_transactions": ['VA02', 'SE37'],
        "remediation": "Test sales order change with pricing conditions. Adapt for PRCD_ELEMENTS.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_043": {
        "title": "BAPI_SALESORDER_GETLIST Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_SALESORDER_GETLIST adapted. Partner data returned in BP format when "
            "CVI active."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBAK', 'VBPA'],
        "affected_transactions": ['VA05', 'SE37'],
        "remediation": "Review partner data handling in output. Test with BP-based customers.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "FM_044": {
        "title": "SD_SALESDOCUMENT_CREATE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "SD_SALESDOCUMENT_CREATE adapted for PRCD_ELEMENTS pricing and BP-based "
            "partner determination."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBAK', 'PRCD_ELEMENTS'],
        "affected_transactions": ['VA01', 'SE37'],
        "remediation": "Test document creation with PRCD_ELEMENTS pricing.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_045": {
        "title": "BAPI_BILLINGDOC_CREATEMULTIPLE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_BILLINGDOC_CREATEMULTIPLE adapted for PRCD_ELEMENTS. Revenue "
            "recognition might require RAR. Rebate logic changed."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBRK', 'PRCD_ELEMENTS'],
        "affected_transactions": ['VF01', 'SE37'],
        "remediation": "Test billing document creation. Review revenue recognition and rebate handling.",
        "effort_hours": 24,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_046": {
        "title": "RV_ORDER_FLOW_INFORMATION Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "RV_ORDER_FLOW_INFORMATION adapted for S/4HANA document flow. New "
            "document categories may appear."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBFA'],
        "affected_transactions": ['VA03', 'SE37'],
        "remediation": "Test document flow retrieval for new S/4HANA document types.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_047": {
        "title": "SD_DOCUMENT_PARTNER_READ Adapted for BP",
        "category": "Deprecated Function Modules",
        "description": (
            "SD_DOCUMENT_PARTNER_READ returns BP numbers alongside customer/vendor "
            "numbers when CVI active."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBPA', 'BUT000'],
        "affected_transactions": ['VA03', 'SE37'],
        "remediation": "Adapt partner read logic for BP-based partner data.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "FM_048": {
        "title": "PRICING_GET_CONDITIONS → PRCD_ELEMENTS",
        "category": "Deprecated Function Modules",
        "description": (
            "PRICING_GET_CONDITIONS adapted to read from PRCD_ELEMENTS instead of "
            "KONV for document conditions."
        ),
        "severity": "YELLOW",
        "affected_tables": ['PRCD_ELEMENTS'],
        "affected_transactions": ['SE37'],
        "remediation": "Adapt condition retrieval logic for PRCD_ELEMENTS source.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_049": {
        "title": "PRICING_SET_CONDITIONS → PRCD_ELEMENTS",
        "category": "Deprecated Function Modules",
        "description": (
            "PRICING_SET_CONDITIONS adapted to write to PRCD_ELEMENTS instead of "
            "KONV."
        ),
        "severity": "YELLOW",
        "affected_tables": ['PRCD_ELEMENTS'],
        "affected_transactions": ['SE37'],
        "remediation": "Adapt condition setting logic for PRCD_ELEMENTS target.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_050": {
        "title": "RV_PRICE_PRINT_DOCUMENT Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "RV_PRICE_PRINT_DOCUMENT adapted for PRCD_ELEMENTS pricing. Print output "
            "reads conditions from new table."
        ),
        "severity": "YELLOW",
        "affected_tables": ['PRCD_ELEMENTS'],
        "affected_transactions": ['SE37'],
        "remediation": "Test pricing print output with PRCD_ELEMENTS.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_051": {
        "title": "BAPI_CUSTOMERREBATE_CREATE Removed",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_CUSTOMERREBATE_CREATE is removed. Rebate processing replaced by "
            "Settlement Management (CLM-SLM)."
        ),
        "severity": "RED",
        "affected_tables": ['VBOX', 'VBOH'],
        "affected_transactions": ['VBO1', 'SE37'],
        "remediation": "Migrate rebate creation to Settlement Management APIs.",
        "effort_hours": 40,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_052": {
        "title": "BAPI_CUSTOMER_CREATEFROMDATA1 → CVI",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_CUSTOMER_CREATEFROMDATA1 is deprecated. Customer creation must use "
            "CVI_EI_INBOUND_MAIN or BP APIs."
        ),
        "severity": "RED",
        "affected_tables": ['KNA1', 'BUT000'],
        "affected_transactions": ['XD01', 'SE37'],
        "remediation": "Replace with CVI_EI_INBOUND_MAIN for customer creation via BP.",
        "effort_hours": 32,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "FM_053": {
        "title": "BAPI_CUSTOMER_CHANGEFROMDATA1 → BP APIs",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_CUSTOMER_CHANGEFROMDATA1 is deprecated. Customer changes must use "
            "BP APIs or CVI_EI_INBOUND_MAIN."
        ),
        "severity": "RED",
        "affected_tables": ['KNA1', 'BUT000'],
        "affected_transactions": ['XD02', 'SE37'],
        "remediation": "Replace with CVI_EI_INBOUND_MAIN or CL_MD_BP_MAINTAIN for customer changes.",
        "effort_hours": 24,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "FM_054": {
        "title": "BAPI_CUSTOMER_GETDETAIL → BP APIs",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_CUSTOMER_GETDETAIL is deprecated. Customer detail retrieval should "
            "use BP APIs."
        ),
        "severity": "RED",
        "affected_tables": ['KNA1', 'BUT000'],
        "affected_transactions": ['XD03', 'SE37'],
        "remediation": "Replace with BAPI_BUPA_CENTRAL_GETDETAIL or CDS view I_CUSTOMER.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "FM_055": {
        "title": "SD_CUSTOMER_MAINTAIN_ALL → BP",
        "category": "Deprecated Function Modules",
        "description": (
            "SD_CUSTOMER_MAINTAIN_ALL is deprecated. Customer maintenance "
            "consolidated in BP transaction."
        ),
        "severity": "RED",
        "affected_tables": ['KNA1', 'KNVV', 'BUT000'],
        "affected_transactions": ['XD01', 'SE37'],
        "remediation": "Replace with BP-based customer maintenance via CVI.",
        "effort_hours": 24,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "FM_056": {
        "title": "RV_DELIVERY_CREATE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "RV_DELIVERY_CREATE adapted for EWM integration. Warehouse request "
            "replaces transfer order creation."
        ),
        "severity": "YELLOW",
        "affected_tables": ['LIKP', 'LIPS'],
        "affected_transactions": ['VL01N', 'SE37'],
        "remediation": "Test delivery creation with EWM. Review warehouse integration.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "FM_057": {
        "title": "BAPI_OUTB_DELIVERY_CREATE_SLS Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_OUTB_DELIVERY_CREATE_SLS adapted for S/4HANA delivery processing "
            "with EWM integration."
        ),
        "severity": "YELLOW",
        "affected_tables": ['LIKP', 'LIPS'],
        "affected_transactions": ['VL01N', 'SE37'],
        "remediation": "Test outbound delivery creation. Verify EWM integration.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "FM_058": {
        "title": "BAPI_INB_DELIVERY_CREATEFROMPO Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_INB_DELIVERY_CREATEFROMPO adapted for MATDOC-based goods receipt "
            "and EWM integration."
        ),
        "severity": "YELLOW",
        "affected_tables": ['LIKP', 'MATDOC'],
        "affected_transactions": ['VL31N', 'SE37'],
        "remediation": "Test inbound delivery creation with MATDOC and EWM.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_059": {
        "title": "BAPI_DELIVERYPROCESSING_EXEC Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_DELIVERYPROCESSING_EXEC adapted for EWM and MATDOC. Picking, "
            "packing, goods issue adapted."
        ),
        "severity": "YELLOW",
        "affected_tables": ['LIKP', 'LIPS', 'MATDOC'],
        "affected_transactions": ['VL02N', 'SE37'],
        "remediation": "Test delivery processing: picking, packing, PGI with EWM/MATDOC.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "FM_060": {
        "title": "SD_AVAILABILITY_CHECK Adapted for aATP",
        "category": "Deprecated Function Modules",
        "description": (
            "SD_AVAILABILITY_CHECK adapted. Advanced ATP (aATP) replaces basic ATP "
            "for advanced scenarios."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBBE'],
        "affected_transactions": ['VA01', 'SE37'],
        "remediation": "Test availability check. Consider aATP activation for advanced scenarios.",
        "effort_hours": 12,
        "responsible_team": "Functional",
        "sap_note": "2267098",
    },
    "FM_061": {
        "title": "AVAILABILITY_CHECK_CONTROLLER Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "AVAILABILITY_CHECK_CONTROLLER adapted for aATP integration and "
            "MATDOC-based stock."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBBE', 'MATDOC'],
        "affected_transactions": ['CO09', 'SE37'],
        "remediation": "Test availability check controller with MATDOC stock data.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2267098",
    },
    "FM_062": {
        "title": "BAPI_SALESORDER_GETSTATUS Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_SALESORDER_GETSTATUS adapted. Status fields reflect S/4HANA "
            "document status model."
        ),
        "severity": "GREEN",
        "affected_tables": ['VBUK', 'VBUP'],
        "affected_transactions": ['VA03', 'SE37'],
        "remediation": "Review status field output for S/4HANA changes.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_063": {
        "title": "RV_DOCUMENT_PRINT_VIEW Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "RV_DOCUMENT_PRINT_VIEW adapted for new output management. Classic output "
            "still works in compatibility."
        ),
        "severity": "YELLOW",
        "affected_tables": ['NAST'],
        "affected_transactions": ['VF03', 'SE37'],
        "remediation": "Test document print output. Plan migration to BRFplus output.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_064": {
        "title": "BAPI_CUSTOMERCONTACT_CREATE Adapted for BP",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_CUSTOMERCONTACT_CREATE adapted for BP contact person model."
        ),
        "severity": "YELLOW",
        "affected_tables": ['KNVK', 'BUT000'],
        "affected_transactions": ['SE37'],
        "remediation": "Adapt contact person creation for BP contact role.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "FM_065": {
        "title": "SD_SALES_DOCUMENT_READ Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "SD_SALES_DOCUMENT_READ adapted for PRCD_ELEMENTS pricing and BP partner "
            "data."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBAK', 'PRCD_ELEMENTS'],
        "affected_transactions": ['SE37'],
        "remediation": "Test document read with PRCD_ELEMENTS pricing data.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_066": {
        "title": "BAPI_QUOTATION_CREATEFROMDATA2 Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_QUOTATION_CREATEFROMDATA2 adapted for PRCD_ELEMENTS pricing."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBAK', 'PRCD_ELEMENTS'],
        "affected_transactions": ['VA21', 'SE37'],
        "remediation": "Test quotation creation with PRCD_ELEMENTS pricing.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_067": {
        "title": "BAPI_CONTRACT_CREATEFROMDATA Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_CONTRACT_CREATEFROMDATA adapted for S/4HANA contract management "
            "with PRCD_ELEMENTS."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBAK', 'PRCD_ELEMENTS'],
        "affected_transactions": ['VA41', 'SE37'],
        "remediation": "Test contract creation. Review pricing and validity logic.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_068": {
        "title": "BAPI_RETURNS_DELIVERY_CREATE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_RETURNS_DELIVERY_CREATE adapted for EWM integration in S/4HANA "
            "returns processing."
        ),
        "severity": "YELLOW",
        "affected_tables": ['LIKP', 'LIPS'],
        "affected_transactions": ['VL01N', 'SE37'],
        "remediation": "Test returns delivery creation with EWM integration.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "FM_069": {
        "title": "SD_COND_ACCESS Adapted for PRCD_ELEMENTS",
        "category": "Deprecated Function Modules",
        "description": (
            "SD_COND_ACCESS (condition access for pricing) adapted to use "
            "PRCD_ELEMENTS at runtime."
        ),
        "severity": "YELLOW",
        "affected_tables": ['PRCD_ELEMENTS'],
        "affected_transactions": ['SE37'],
        "remediation": "Review custom condition access routines for PRCD_ELEMENTS.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_070": {
        "title": "BAPI_BILLINGDOC_CANCEL Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_BILLINGDOC_CANCEL adapted for ACDOCA reversal and PRCD_ELEMENTS "
            "pricing."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBRK', 'ACDOCA'],
        "affected_transactions": ['VF11', 'SE37'],
        "remediation": "Test billing cancellation with ACDOCA reversal.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_071": {
        "title": "SD_PARTNER_READ Adapted for BP",
        "category": "Deprecated Function Modules",
        "description": (
            "SD_PARTNER_READ returns BP-based partner data when CVI is active."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBPA', 'BUT000'],
        "affected_transactions": ['SE37'],
        "remediation": "Adapt partner read for BP number output.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "FM_072": {
        "title": "BAPI_SALESORDER_SIMULATE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_SALESORDER_SIMULATE adapted for PRCD_ELEMENTS pricing simulation."
        ),
        "severity": "YELLOW",
        "affected_tables": ['PRCD_ELEMENTS'],
        "affected_transactions": ['SE37'],
        "remediation": "Test sales order simulation with new pricing.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_073": {
        "title": "RV_INVOICE_CREATE Adapted for PRCD_ELEMENTS",
        "category": "Deprecated Function Modules",
        "description": (
            "RV_INVOICE_CREATE adapted. Billing creation uses PRCD_ELEMENTS for "
            "condition storage."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBRK', 'PRCD_ELEMENTS'],
        "affected_transactions": ['VF01', 'SE37'],
        "remediation": "Test invoice creation with PRCD_ELEMENTS conditions.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_074": {
        "title": "BAPI_CREDITCHECK_SETINFO → UKM APIs",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_CREDITCHECK_SETINFO deprecated. Use UKM APIs for credit information "
            "maintenance."
        ),
        "severity": "RED",
        "affected_tables": ['KNKK', 'UKM_BUPA'],
        "affected_transactions": ['SE37'],
        "remediation": "Replace with UKM_BUPA_CREDIT_DATA_SET.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2265093",
    },
    "FM_075": {
        "title": "SD_SCHEDULING_DETERMINATION Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "SD_SCHEDULING_DETERMINATION adapted for S/4HANA delivery scheduling with "
            "aATP."
        ),
        "severity": "GREEN",
        "affected_tables": ['VBEP'],
        "affected_transactions": ['SE37'],
        "remediation": "Test scheduling determination. Review aATP integration.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2267098",
    },
    "FM_076": {
        "title": "BAPI_CUSTOMERREBATE_CHANGE Removed",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_CUSTOMERREBATE_CHANGE removed with rebate simplification. Use "
            "Settlement Management."
        ),
        "severity": "RED",
        "affected_tables": ['VBOX'],
        "affected_transactions": ['SE37'],
        "remediation": "Migrate to Settlement Management (CLM-SLM) APIs.",
        "effort_hours": 24,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_077": {
        "title": "BAPI_CUSTOMER_GETCONTACTLIST Adapted for BP",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_CUSTOMER_GETCONTACTLIST adapted. Contact persons now via BP contact "
            "role."
        ),
        "severity": "YELLOW",
        "affected_tables": ['KNVK', 'BUT000'],
        "affected_transactions": ['SE37'],
        "remediation": "Adapt contact list retrieval for BP model.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "FM_078": {
        "title": "RV_CONDITIONS_COPY Adapted for PRCD",
        "category": "Deprecated Function Modules",
        "description": (
            "RV_CONDITIONS_COPY adapted for PRCD_ELEMENTS. Condition copying between "
            "documents uses new table."
        ),
        "severity": "YELLOW",
        "affected_tables": ['PRCD_ELEMENTS'],
        "affected_transactions": ['SE37'],
        "remediation": "Test condition copy between SD documents.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_079": {
        "title": "BAPI_SALESORDER_GETDETAIL Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_SALESORDER_GETDETAIL output includes PRCD_ELEMENTS-based pricing "
            "and BP partner numbers."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBAK', 'PRCD_ELEMENTS'],
        "affected_transactions": ['VA03', 'SE37'],
        "remediation": "Review output structure for PRCD_ELEMENTS pricing data.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_080": {
        "title": "SD_ORDER_SAVE Adapted for PRCD_ELEMENTS",
        "category": "Deprecated Function Modules",
        "description": (
            "SD_ORDER_SAVE adapted. Document save persists conditions to "
            "PRCD_ELEMENTS instead of KONV."
        ),
        "severity": "YELLOW",
        "affected_tables": ['PRCD_ELEMENTS'],
        "affected_transactions": ['SE37'],
        "remediation": "Test order save with PRCD_ELEMENTS.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_081": {
        "title": "BAPI_PO_CREATE1 New Mandatory Fields",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_PO_CREATE1 has new mandatory fields in S/4HANA including BP-based "
            "vendor and MATDOC-related fields."
        ),
        "severity": "YELLOW",
        "affected_tables": ['EKKO', 'EKPO'],
        "affected_transactions": ['ME21N', 'SE37'],
        "remediation": "Review new mandatory fields. Test PO creation with BP vendor numbers.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_082": {
        "title": "BAPI_PO_CHANGE New Mandatory Fields",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_PO_CHANGE adapted with new mandatory fields for S/4HANA "
            "procurement."
        ),
        "severity": "YELLOW",
        "affected_tables": ['EKKO', 'EKPO'],
        "affected_transactions": ['ME22N', 'SE37'],
        "remediation": "Test PO change scenarios. Review new field requirements.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_083": {
        "title": "BAPI_PO_GETDETAIL1 Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_PO_GETDETAIL1 output includes new S/4HANA fields and BP-based "
            "vendor information."
        ),
        "severity": "GREEN",
        "affected_tables": ['EKKO', 'EKPO'],
        "affected_transactions": ['ME23N', 'SE37'],
        "remediation": "Review output structure for new fields.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_084": {
        "title": "BAPI_PR_CREATE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_PR_CREATE adapted for S/4HANA procurement. New fields for source "
            "assignment."
        ),
        "severity": "YELLOW",
        "affected_tables": ['EBAN'],
        "affected_transactions": ['ME51N', 'SE37'],
        "remediation": "Test PR creation with S/4HANA procurement fields.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_085": {
        "title": "BAPI_PR_CHANGE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_PR_CHANGE adapted for S/4HANA procurement changes."
        ),
        "severity": "GREEN",
        "affected_tables": ['EBAN'],
        "affected_transactions": ['ME52N', 'SE37'],
        "remediation": "Test PR change scenarios.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_086": {
        "title": "ME_DIRECT_INPUT_PO Deprecated",
        "category": "Deprecated Function Modules",
        "description": (
            "ME_DIRECT_INPUT_PO is deprecated. Use BAPI_PO_CREATE1 for programmatic "
            "PO creation."
        ),
        "severity": "RED",
        "affected_tables": ['EKKO', 'EKPO'],
        "affected_transactions": ['SE37'],
        "remediation": "Replace ME_DIRECT_INPUT_PO with BAPI_PO_CREATE1.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_087": {
        "title": "ME_PO_CREATE_VIA_DIRECTINPUT Deprecated",
        "category": "Deprecated Function Modules",
        "description": (
            "ME_PO_CREATE_VIA_DIRECTINPUT deprecated. Use BAPI_PO_CREATE1 instead."
        ),
        "severity": "RED",
        "affected_tables": ['EKKO'],
        "affected_transactions": ['SE37'],
        "remediation": "Replace with BAPI_PO_CREATE1.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_088": {
        "title": "BAPI_GOODSMVT_CREATE Adapted for MATDOC",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_GOODSMVT_CREATE adapted. Goods movements create MATDOC entries "
            "instead of MKPF/MSEG."
        ),
        "severity": "YELLOW",
        "affected_tables": ['MATDOC'],
        "affected_transactions": ['MIGO', 'SE37'],
        "remediation": "Test goods movement creation. Verify MATDOC entries created.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_089": {
        "title": "BAPI_GOODSMVT_GETDETAIL Adapted for MATDOC",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_GOODSMVT_GETDETAIL reads from MATDOC instead of MKPF/MSEG."
        ),
        "severity": "YELLOW",
        "affected_tables": ['MATDOC'],
        "affected_transactions": ['SE37'],
        "remediation": "Adapt callers for MATDOC-based goods movement detail.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_090": {
        "title": "MB_CREATE_GOODS_MOVEMENT → MATDOC",
        "category": "Deprecated Function Modules",
        "description": (
            "MB_CREATE_GOODS_MOVEMENT adapted for MATDOC-based goods movements. "
            "Internal posting logic changed."
        ),
        "severity": "YELLOW",
        "affected_tables": ['MATDOC'],
        "affected_transactions": ['MIGO', 'SE37'],
        "remediation": "Test goods movement creation with MATDOC backend.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_091": {
        "title": "BAPI_MATERIAL_GET_ALL Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_MATERIAL_GET_ALL adapted for S/4HANA material master changes. "
            "Industry fields deprecated."
        ),
        "severity": "GREEN",
        "affected_tables": ['MARA', 'MARC'],
        "affected_transactions": ['MM03', 'SE37'],
        "remediation": "Review output for deprecated industry-specific fields.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_092": {
        "title": "BAPI_MATERIAL_GET_DETAIL Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_MATERIAL_GET_DETAIL adapted. New product model fields. Some "
            "material type restrictions apply."
        ),
        "severity": "GREEN",
        "affected_tables": ['MARA', 'MARC', 'MVKE'],
        "affected_transactions": ['MM03', 'SE37'],
        "remediation": "Review output structure for new/removed fields.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_093": {
        "title": "BAPI_MATERIAL_SAVEDATA Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_MATERIAL_SAVEDATA adapted for S/4HANA. New mandatory fields. "
            "Material number length extended to 40 chars."
        ),
        "severity": "YELLOW",
        "affected_tables": ['MARA', 'MARC'],
        "affected_transactions": ['MM01', 'SE37'],
        "remediation": "Test material creation. Review 40-char material number impact.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_094": {
        "title": "BAPI_MATERIAL_STOCK_REQ_LIST → MATDOC",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_MATERIAL_STOCK_REQ_LIST adapted. Stock/requirements list reads from "
            "MATDOC-based stock data."
        ),
        "severity": "YELLOW",
        "affected_tables": ['MATDOC', 'MARD'],
        "affected_transactions": ['MD04', 'SE37'],
        "remediation": "Test stock requirements list for MATDOC integration.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_095": {
        "title": "STOCK_REQUIREMENTS_LIST → MATDOC",
        "category": "Deprecated Function Modules",
        "description": (
            "STOCK_REQUIREMENTS_LIST adapted. MRP stock data derived from MATDOC "
            "instead of MARD/MCHB."
        ),
        "severity": "YELLOW",
        "affected_tables": ['MATDOC', 'MARD'],
        "affected_transactions": ['MD04', 'SE37'],
        "remediation": "Review MRP stock requirements list output for MATDOC changes.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_096": {
        "title": "BAPI_RESERVATION_CREATE1 Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_RESERVATION_CREATE1 adapted. Reservation goods movement links to "
            "MATDOC."
        ),
        "severity": "YELLOW",
        "affected_tables": ['RESB', 'MATDOC'],
        "affected_transactions": ['MB21', 'SE37'],
        "remediation": "Test reservation creation with MATDOC integration.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_097": {
        "title": "BAPI_RESERVATION_CHANGE1 Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_RESERVATION_CHANGE1 adapted for MATDOC-based goods movement "
            "references."
        ),
        "severity": "GREEN",
        "affected_tables": ['RESB'],
        "affected_transactions": ['MB22', 'SE37'],
        "remediation": "Test reservation changes.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_098": {
        "title": "BAPI_VENDOR_CREATE → CVI_EI_INBOUND_MAIN",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_VENDOR_CREATE is deprecated. Vendor creation must use "
            "CVI_EI_INBOUND_MAIN or BP APIs."
        ),
        "severity": "RED",
        "affected_tables": ['LFA1', 'BUT000'],
        "affected_transactions": ['XK01', 'SE37'],
        "remediation": "Replace with CVI_EI_INBOUND_MAIN for vendor creation via BP.",
        "effort_hours": 32,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "FM_099": {
        "title": "BAPI_VENDOR_CHANGE → BP APIs",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_VENDOR_CHANGE is deprecated. Use BP APIs or CVI_EI_INBOUND_MAIN for "
            "vendor maintenance."
        ),
        "severity": "RED",
        "affected_tables": ['LFA1', 'BUT000'],
        "affected_transactions": ['XK02', 'SE37'],
        "remediation": "Replace with CVI_EI_INBOUND_MAIN or CL_MD_BP_MAINTAIN.",
        "effort_hours": 24,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "FM_100": {
        "title": "BAPI_VENDOR_GETDETAIL → BP APIs",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_VENDOR_GETDETAIL is deprecated. Use BAPI_BUPA_CENTRAL_GETDETAIL or "
            "CDS views."
        ),
        "severity": "RED",
        "affected_tables": ['LFA1', 'BUT000'],
        "affected_transactions": ['XK03', 'SE37'],
        "remediation": "Replace with BAPI_BUPA_CENTRAL_GETDETAIL or I_SUPPLIER CDS view.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "FM_101": {
        "title": "BAPI_INCOMINGINVOICE_CREATE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_INCOMINGINVOICE_CREATE adapted for S/4HANA. GR reference via "
            "MATDOC. BP-based vendor."
        ),
        "severity": "YELLOW",
        "affected_tables": ['RBKP', 'RSEG', 'MATDOC'],
        "affected_transactions": ['MIRO', 'SE37'],
        "remediation": "Test invoice creation with MATDOC GR reference and BP vendor.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_102": {
        "title": "BAPI_INCOMINGINVOICE_CHANGE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_INCOMINGINVOICE_CHANGE adapted for S/4HANA field changes."
        ),
        "severity": "GREEN",
        "affected_tables": ['RBKP', 'RSEG'],
        "affected_transactions": ['MIRO', 'SE37'],
        "remediation": "Test invoice change scenarios.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_103": {
        "title": "ME_RELEASE_PO Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "ME_RELEASE_PO adapted for S/4HANA release strategy. Workflow integration "
            "enhanced."
        ),
        "severity": "GREEN",
        "affected_tables": ['EKKO'],
        "affected_transactions": ['ME28', 'SE37'],
        "remediation": "Test PO release with S/4HANA workflow.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_104": {
        "title": "ME_UPDATE_PO Restricted",
        "category": "Deprecated Function Modules",
        "description": (
            "ME_UPDATE_PO is restricted. Use BAPI_PO_CHANGE for programmatic PO "
            "updates."
        ),
        "severity": "RED",
        "affected_tables": ['EKKO', 'EKPO'],
        "affected_transactions": ['SE37'],
        "remediation": "Replace ME_UPDATE_PO with BAPI_PO_CHANGE.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_105": {
        "title": "BAPI_MATERIAL_AVAILABILITY Adapted for MATDOC",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_MATERIAL_AVAILABILITY adapted. Stock availability derived from "
            "MATDOC."
        ),
        "severity": "YELLOW",
        "affected_tables": ['MATDOC'],
        "affected_transactions": ['CO09', 'SE37'],
        "remediation": "Test material availability with MATDOC-based stock.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_106": {
        "title": "MB_GOODS_MOVEMENT_DIRECT Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "MB_GOODS_MOVEMENT_DIRECT adapted for MATDOC. Direct goods movement "
            "posting creates MATDOC."
        ),
        "severity": "YELLOW",
        "affected_tables": ['MATDOC'],
        "affected_transactions": ['MIGO', 'SE37'],
        "remediation": "Test direct goods movement with MATDOC.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_107": {
        "title": "BAPI_BATCH_CREATE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_BATCH_CREATE adapted for S/4HANA batch management with MATDOC "
            "integration."
        ),
        "severity": "GREEN",
        "affected_tables": ['MCH1', 'MCHA'],
        "affected_transactions": ['MSC1N', 'SE37'],
        "remediation": "Test batch creation under S/4HANA.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_108": {
        "title": "BAPI_MATERIAL_BOM_GROUP_CREATE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_MATERIAL_BOM_GROUP_CREATE adapted for S/4HANA BOM processing."
        ),
        "severity": "GREEN",
        "affected_tables": ['STKO', 'STPO'],
        "affected_transactions": ['CS01', 'SE37'],
        "remediation": "Test BOM creation under S/4HANA.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_109": {
        "title": "BAPI_CONTRACT_CREATE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_CONTRACT_CREATE (purchase contract) adapted for S/4HANA "
            "procurement."
        ),
        "severity": "GREEN",
        "affected_tables": ['EKKO', 'EKPO'],
        "affected_transactions": ['ME31K', 'SE37'],
        "remediation": "Test purchase contract creation.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_110": {
        "title": "BAPI_SCHEDULE_MAINTAIN Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_SCHEDULE_MAINTAIN (scheduling agreement) adapted for S/4HANA."
        ),
        "severity": "GREEN",
        "affected_tables": ['EKKO', 'EKAB'],
        "affected_transactions": ['ME31L', 'SE37'],
        "remediation": "Test scheduling agreement maintenance.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_111": {
        "title": "BAPI_MATERIAL_GETLIST Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_MATERIAL_GETLIST adapted for extended material number (40 chars) "
            "and new product model."
        ),
        "severity": "GREEN",
        "affected_tables": ['MARA'],
        "affected_transactions": ['SE37'],
        "remediation": "Review material number length handling.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_112": {
        "title": "BAPI_PHYSINV_CREATE_COUNT Adapted for MATDOC",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_PHYSINV_CREATE_COUNT adapted. Physical inventory difference posting "
            "via MATDOC."
        ),
        "severity": "YELLOW",
        "affected_tables": ['ISEG', 'MATDOC'],
        "affected_transactions": ['MI01', 'SE37'],
        "remediation": "Test physical inventory with MATDOC posting.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_113": {
        "title": "BAPI_MATERIAL_VALUATE Adapted for ML",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_MATERIAL_VALUATE adapted for mandatory material ledger. Actual "
            "costing valuation."
        ),
        "severity": "YELLOW",
        "affected_tables": ['MBEW', 'CKMLHD'],
        "affected_transactions": ['SE37'],
        "remediation": "Review valuation logic for mandatory material ledger.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_114": {
        "title": "BAPI_INFORECORD_CREATE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_INFORECORD_CREATE adapted for S/4HANA info record with BP vendor."
        ),
        "severity": "GREEN",
        "affected_tables": ['EINE', 'EINA'],
        "affected_transactions": ['ME11', 'SE37'],
        "remediation": "Test info record creation with BP vendor.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "FM_115": {
        "title": "BAPI_REQUISITION_CREATE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_REQUISITION_CREATE adapted with new fields for S/4HANA sourcing."
        ),
        "severity": "GREEN",
        "affected_tables": ['EBAN'],
        "affected_transactions": ['ME51N', 'SE37'],
        "remediation": "Test purchase requisition creation.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_116": {
        "title": "BAPI_SOURCEOFSPPLY_CREATE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_SOURCEOFSPPLY_CREATE adapted for S/4HANA source list with BP "
            "vendor."
        ),
        "severity": "GREEN",
        "affected_tables": ['EORD'],
        "affected_transactions": ['ME01', 'SE37'],
        "remediation": "Test source of supply creation with BP vendor.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "FM_117": {
        "title": "BAPI_STOCKOVERVIEW_GETDETAIL Adapted for MATDOC",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_STOCKOVERVIEW_GETDETAIL stock overview reads from MATDOC "
            "aggregation."
        ),
        "severity": "YELLOW",
        "affected_tables": ['MATDOC', 'MARD'],
        "affected_transactions": ['MMBE', 'SE37'],
        "remediation": "Review stock overview output for MATDOC-based data.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_118": {
        "title": "BAPI_GOODS_RECEIPT_CREATE Adapted for MATDOC",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_GOODS_RECEIPT_CREATE posting creates MATDOC entries."
        ),
        "severity": "YELLOW",
        "affected_tables": ['MATDOC'],
        "affected_transactions": ['MIGO', 'SE37'],
        "remediation": "Test goods receipt with MATDOC.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_119": {
        "title": "BAPI_GOODSMOVEMENT_GETITEMS Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_GOODSMOVEMENT_GETITEMS reads from MATDOC instead of MSEG."
        ),
        "severity": "YELLOW",
        "affected_tables": ['MATDOC'],
        "affected_transactions": ['SE37'],
        "remediation": "Adapt goods movement item retrieval for MATDOC.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_120": {
        "title": "ME_CHECK_PO_ITEM Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "ME_CHECK_PO_ITEM adapted for S/4HANA PO validation. New mandatory field "
            "checks."
        ),
        "severity": "GREEN",
        "affected_tables": ['EKPO'],
        "affected_transactions": ['SE37'],
        "remediation": "Test PO item validation.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_121": {
        "title": "HR_INFOTYPE_OPERATION Compatibility Mode",
        "category": "Deprecated Function Modules",
        "description": (
            "HR_INFOTYPE_OPERATION runs in compatibility mode in S/4HANA. Plan "
            "migration to SuccessFactors or S/4HANA HCM."
        ),
        "severity": "YELLOW",
        "affected_tables": ['PA0001'],
        "affected_transactions": ['PA30', 'SE37'],
        "remediation": "Test HR infotype operations. Plan HCM modernization strategy.",
        "effort_hours": 24,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_122": {
        "title": "BAPI_EMPLOYEE_GETDATA Compatibility Mode",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_EMPLOYEE_GETDATA runs in compatibility mode. Employee data "
            "retrieval works but is strategic for cloud migration."
        ),
        "severity": "YELLOW",
        "affected_tables": ['PA0001', 'PA0002'],
        "affected_transactions": ['PA20', 'SE37'],
        "remediation": "Test employee data retrieval. Plan SuccessFactors migration.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_123": {
        "title": "HR_READ_INFOTYPE Compatibility Mode",
        "category": "Deprecated Function Modules",
        "description": (
            "HR_READ_INFOTYPE runs in compatibility mode. Infotype reads work but HCM "
            "cloud is strategic."
        ),
        "severity": "YELLOW",
        "affected_tables": ['PA0001'],
        "affected_transactions": ['SE37'],
        "remediation": "Test infotype reads. Plan HCM strategy.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_124": {
        "title": "HR_WRITE_INFOTYPE Compatibility Mode",
        "category": "Deprecated Function Modules",
        "description": (
            "HR_WRITE_INFOTYPE runs in compatibility mode. Infotype writes work but "
            "plan for cloud."
        ),
        "severity": "YELLOW",
        "affected_tables": ['PA0001'],
        "affected_transactions": ['PA30', 'SE37'],
        "remediation": "Test infotype writes. Plan HCM strategy.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_125": {
        "title": "BAPI_EMPLOYEET_CREATE Compatibility Mode",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_EMPLOYEET_CREATE (employee time) runs in compatibility mode."
        ),
        "severity": "YELLOW",
        "affected_tables": ['PA2001'],
        "affected_transactions": ['PA61', 'SE37'],
        "remediation": "Test employee time creation. Plan time management strategy.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_126": {
        "title": "BAPI_EMPLOYEET_CHANGE Compatibility Mode",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_EMPLOYEET_CHANGE (employee time change) runs in compatibility mode."
        ),
        "severity": "YELLOW",
        "affected_tables": ['PA2001'],
        "affected_transactions": ['PA61', 'SE37'],
        "remediation": "Test time change scenarios.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_127": {
        "title": "HR_GET_EMPLOYEE_DATA Compatibility Mode",
        "category": "Deprecated Function Modules",
        "description": (
            "HR_GET_EMPLOYEE_DATA (comprehensive employee data read) runs in "
            "compatibility mode."
        ),
        "severity": "YELLOW",
        "affected_tables": ['PA0001', 'PA0002', 'PA0008'],
        "affected_transactions": ['SE37'],
        "remediation": "Test comprehensive employee data retrieval.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_128": {
        "title": "BAPI_ORGUNIT_CREATE Compatibility Mode",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_ORGUNIT_CREATE (org management) runs in compatibility mode. Org "
            "structure management planned for cloud."
        ),
        "severity": "YELLOW",
        "affected_tables": ['HRP1000'],
        "affected_transactions": ['PPOME', 'SE37'],
        "remediation": "Test org unit creation. Plan org management strategy.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_129": {
        "title": "BAPI_ORGUNIT_CHANGE Compatibility Mode",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_ORGUNIT_CHANGE runs in compatibility mode. Org structure changes "
            "work but plan for cloud."
        ),
        "severity": "YELLOW",
        "affected_tables": ['HRP1000', 'HRP1001'],
        "affected_transactions": ['PPOME', 'SE37'],
        "remediation": "Test org unit change scenarios.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_130": {
        "title": "HR_ECM_CREATE_COMPENSATION Compatibility",
        "category": "Deprecated Function Modules",
        "description": (
            "HR_ECM_* compensation management FMs run in compatibility. Enterprise "
            "Compensation Management may move to cloud."
        ),
        "severity": "YELLOW",
        "affected_tables": ['PA0008'],
        "affected_transactions": ['SE37'],
        "remediation": "Test compensation management. Plan strategy for compensation cloud.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_131": {
        "title": "HR_ECM_GET_PAYRESULTS Compatibility",
        "category": "Deprecated Function Modules",
        "description": (
            "HR_ECM_GET_PAYRESULTS retrieval works in compatibility mode. Payroll "
            "results accessible."
        ),
        "severity": "YELLOW",
        "affected_tables": ['PA0008'],
        "affected_transactions": ['SE37'],
        "remediation": "Test payroll result retrieval.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_132": {
        "title": "RP_CALC_DATE_IN_INTERVAL Still Works",
        "category": "Deprecated Function Modules",
        "description": (
            "RP_CALC_DATE_IN_INTERVAL (date calculation for HR) still works in "
            "S/4HANA."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "No action needed. FM continues to work.",
        "effort_hours": 2,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_133": {
        "title": "CATS_INSERT_RECORD Compatibility Mode",
        "category": "Deprecated Function Modules",
        "description": (
            "CATS_INSERT_RECORD (time sheet entry creation) runs in compatibility "
            "mode."
        ),
        "severity": "YELLOW",
        "affected_tables": ['CATSDB'],
        "affected_transactions": ['CAT2', 'SE37'],
        "remediation": "Test time sheet entry creation. Plan CATS strategy.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_134": {
        "title": "CATS_APPROVE_RECORDS Compatibility Mode",
        "category": "Deprecated Function Modules",
        "description": (
            "CATS_APPROVE_RECORDS (time sheet approval) runs in compatibility mode."
        ),
        "severity": "YELLOW",
        "affected_tables": ['CATSDB'],
        "affected_transactions": ['CAT7', 'SE37'],
        "remediation": "Test time sheet approval workflows.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_135": {
        "title": "CATS_GET_TIMES Compatibility Mode",
        "category": "Deprecated Function Modules",
        "description": (
            "CATS_GET_TIMES (time sheet time retrieval) runs in compatibility mode."
        ),
        "severity": "GREEN",
        "affected_tables": ['CATSDB'],
        "affected_transactions": ['SE37'],
        "remediation": "Test time retrieval.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_136": {
        "title": "HR_PAYROLL_RUN Compatibility Mode",
        "category": "Deprecated Function Modules",
        "description": (
            "HR_PAYROLL_RUN (payroll execution trigger) works in compatibility with "
            "S/4HANA on-premise HCM."
        ),
        "severity": "YELLOW",
        "affected_tables": [],
        "affected_transactions": ['PC00_M99_CALC', 'SE37'],
        "remediation": "Test payroll execution. Plan payroll strategy (on-premise or cloud).",
        "effort_hours": 16,
        "responsible_team": "Functional",
        "sap_note": "2296888",
    },
    "FM_137": {
        "title": "BAPI_PERSDATA_CHANGE Compatibility Mode",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_PERSDATA_CHANGE (personal data change) runs in compatibility mode."
        ),
        "severity": "YELLOW",
        "affected_tables": ['PA0002'],
        "affected_transactions": ['PA30', 'SE37'],
        "remediation": "Test personal data change.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_138": {
        "title": "BAPI_ABSENCE_CREATE Compatibility Mode",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_ABSENCE_CREATE (absence/attendance creation) runs in compatibility "
            "mode in S/4HANA HCM."
        ),
        "severity": "YELLOW",
        "affected_tables": ['PA2001'],
        "affected_transactions": ['PA61', 'SE37'],
        "remediation": "Test absence creation and approval.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_139": {
        "title": "HR_CLUSTER_READ Compatibility Mode",
        "category": "Deprecated Function Modules",
        "description": (
            "HR_CLUSTER_READ (HR cluster table read) runs in compatibility mode. "
            "Cluster tables remain but plan for cloud."
        ),
        "severity": "YELLOW",
        "affected_tables": ['PCL1', 'PCL2'],
        "affected_transactions": ['SE37'],
        "remediation": "Test HR cluster data reads.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_140": {
        "title": "BAPI_EMPLOYEE_ENQUEUE Compatibility Mode",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_EMPLOYEE_ENQUEUE/DEQUEUE (employee lock) runs in compatibility "
            "mode."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "No change needed. Locking mechanism unchanged.",
        "effort_hours": 2,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_141": {
        "title": "BAPI_ALM_ORDER_MAINTAIN Adapted for ACDOCA",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_ALM_ORDER_MAINTAIN adapted for ACDOCA settlement. PM/CS order "
            "settlement posts to Universal Journal."
        ),
        "severity": "YELLOW",
        "affected_tables": ['AUFK', 'ACDOCA'],
        "affected_transactions": ['IW31', 'IW32', 'SE37'],
        "remediation": "Test maintenance order creation and settlement to ACDOCA.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "FM_142": {
        "title": "BAPI_EQUI_CREATE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_EQUI_CREATE adapted with new fields for S/4HANA equipment master."
        ),
        "severity": "GREEN",
        "affected_tables": ['EQUI'],
        "affected_transactions": ['IE01', 'SE37'],
        "remediation": "Test equipment creation. Review new fields.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "FM_143": {
        "title": "BAPI_EQUI_CHANGE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_EQUI_CHANGE adapted for S/4HANA equipment field changes."
        ),
        "severity": "GREEN",
        "affected_tables": ['EQUI'],
        "affected_transactions": ['IE02', 'SE37'],
        "remediation": "Test equipment change scenarios.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "FM_144": {
        "title": "BAPI_FUNCLOC_CREATE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_FUNCLOC_CREATE adapted with new fields for S/4HANA functional "
            "location master."
        ),
        "severity": "GREEN",
        "affected_tables": ['IFLOT'],
        "affected_transactions": ['IL01', 'SE37'],
        "remediation": "Test functional location creation.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "FM_145": {
        "title": "BAPI_FUNCLOC_CHANGE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_FUNCLOC_CHANGE adapted for S/4HANA functional location fields."
        ),
        "severity": "GREEN",
        "affected_tables": ['IFLOT'],
        "affected_transactions": ['IL02', 'SE37'],
        "remediation": "Test functional location change.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "FM_146": {
        "title": "BAPI_ALM_NOTIF_CREATE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_ALM_NOTIF_CREATE adapted for S/4HANA notification processing with "
            "Fiori integration."
        ),
        "severity": "GREEN",
        "affected_tables": ['QMEL'],
        "affected_transactions": ['IW21', 'SE37'],
        "remediation": "Test notification creation. Review Fiori notification apps.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "FM_147": {
        "title": "BAPI_ALM_NOTIF_CHANGE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_ALM_NOTIF_CHANGE adapted for S/4HANA Fiori-based notification "
            "change."
        ),
        "severity": "GREEN",
        "affected_tables": ['QMEL'],
        "affected_transactions": ['IW22', 'SE37'],
        "remediation": "Test notification change scenarios.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "FM_148": {
        "title": "BAPI_SERVNOT_CREATE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_SERVNOT_CREATE adapted for S/4HANA service notification with Fiori "
            "apps."
        ),
        "severity": "GREEN",
        "affected_tables": ['QMEL'],
        "affected_transactions": ['IW24', 'SE37'],
        "remediation": "Test service notification creation.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "FM_149": {
        "title": "PM_ORDER_CHANGE Adapted for ACDOCA",
        "category": "Deprecated Function Modules",
        "description": (
            "PM_ORDER_CHANGE adapted. PM order changes trigger ACDOCA-based "
            "settlement updates."
        ),
        "severity": "YELLOW",
        "affected_tables": ['AUFK', 'ACDOCA'],
        "affected_transactions": ['IW32', 'SE37'],
        "remediation": "Test PM order changes with ACDOCA settlement.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "FM_150": {
        "title": "PM_ORDER_CREATE Adapted for ACDOCA",
        "category": "Deprecated Function Modules",
        "description": (
            "PM_ORDER_CREATE adapted. New PM orders settlement to ACDOCA."
        ),
        "severity": "YELLOW",
        "affected_tables": ['AUFK', 'ACDOCA'],
        "affected_transactions": ['IW31', 'SE37'],
        "remediation": "Test PM order creation and settlement.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "FM_151": {
        "title": "BAPI_INSPOPER_RECORDRESULTS Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_INSPOPER_RECORDRESULTS adapted for S/4HANA quality inspection with "
            "MATDOC-based lot creation."
        ),
        "severity": "YELLOW",
        "affected_tables": ['QALS', 'MATDOC'],
        "affected_transactions": ['QA32', 'SE37'],
        "remediation": "Test inspection results recording with MATDOC integration.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2253942",
    },
    "FM_152": {
        "title": "BAPI_ALM_ORDER_GET_DETAIL Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_ALM_ORDER_GET_DETAIL adapted for S/4HANA PM order details with "
            "ACDOCA fields."
        ),
        "severity": "GREEN",
        "affected_tables": ['AUFK', 'AFIH'],
        "affected_transactions": ['IW33', 'SE37'],
        "remediation": "Review output for ACDOCA-related fields.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "FM_153": {
        "title": "BAPI_MEASDOC_CREATE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_MEASDOC_CREATE (measurement document) adapted for S/4HANA equipment "
            "monitoring."
        ),
        "severity": "GREEN",
        "affected_tables": ['IMRG'],
        "affected_transactions": ['IK11', 'SE37'],
        "remediation": "Test measurement document creation.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "FM_154": {
        "title": "BAPI_ALM_ORDEROPER_GET_DETAIL Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_ALM_ORDEROPER_GET_DETAIL (order operation details) adapted for "
            "MATDOC-based confirmation."
        ),
        "severity": "GREEN",
        "affected_tables": ['AFVC'],
        "affected_transactions": ['IW33', 'SE37'],
        "remediation": "Review operation output fields.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "FM_155": {
        "title": "BAPI_ALM_NOTIF_GET_DETAIL Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_ALM_NOTIF_GET_DETAIL adapted for S/4HANA notification processing."
        ),
        "severity": "GREEN",
        "affected_tables": ['QMEL', 'QMFE'],
        "affected_transactions": ['IW23', 'SE37'],
        "remediation": "Review notification detail output.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "FM_156": {
        "title": "BAPI_PM_ORDER_CONFIRM_CREATE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_PM_ORDER_CONFIRM_CREATE adapted for MATDOC-based goods movement on "
            "confirmation."
        ),
        "severity": "YELLOW",
        "affected_tables": ['AFRU', 'MATDOC'],
        "affected_transactions": ['IW42', 'SE37'],
        "remediation": "Test order confirmation with MATDOC goods movement.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "FM_157": {
        "title": "BAPI_ALM_ORDER_RELEASE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_ALM_ORDER_RELEASE adapted for S/4HANA order release with integrated "
            "scheduling."
        ),
        "severity": "GREEN",
        "affected_tables": ['AUFK'],
        "affected_transactions": ['IW31', 'SE37'],
        "remediation": "Test order release.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "FM_158": {
        "title": "BAPI_ALM_ORDER_COMPLETE Adapted for ACDOCA",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_ALM_ORDER_COMPLETE adapted. Technical completion triggers ACDOCA "
            "settlement."
        ),
        "severity": "YELLOW",
        "affected_tables": ['AUFK', 'ACDOCA'],
        "affected_transactions": ['IW32', 'SE37'],
        "remediation": "Test order completion and ACDOCA settlement.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "FM_159": {
        "title": "BAPI_ALM_TASK_MAINTAIN Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_ALM_TASK_MAINTAIN adapted for S/4HANA maintenance task list "
            "processing."
        ),
        "severity": "GREEN",
        "affected_tables": ['PLKO', 'PLPO'],
        "affected_transactions": ['IA05', 'SE37'],
        "remediation": "Test task list maintenance.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "FM_160": {
        "title": "BAPI_QUALNOTIF_CREATE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_QUALNOTIF_CREATE (quality notification) adapted for S/4HANA "
            "Fiori-based QM."
        ),
        "severity": "GREEN",
        "affected_tables": ['QMEL'],
        "affected_transactions": ['QM01', 'SE37'],
        "remediation": "Test quality notification creation.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2253942",
    },
    "FM_161": {
        "title": "REUSE_ALV_GRID_DISPLAY → CL_SALV_TABLE",
        "category": "Deprecated Function Modules",
        "description": (
            "REUSE_ALV_GRID_DISPLAY is deprecated. Use CL_SALV_TABLE for ALV grid "
            "display."
        ),
        "severity": "YELLOW",
        "affected_tables": [],
        "affected_transactions": ['SE37', 'SE38'],
        "remediation": "Replace REUSE_ALV_GRID_DISPLAY with CL_SALV_TABLE=>FACTORY().",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_162": {
        "title": "REUSE_ALV_LIST_DISPLAY → CL_SALV_TABLE",
        "category": "Deprecated Function Modules",
        "description": (
            "REUSE_ALV_LIST_DISPLAY is deprecated. Use CL_SALV_TABLE for ALV list "
            "output."
        ),
        "severity": "YELLOW",
        "affected_tables": [],
        "affected_transactions": ['SE37', 'SE38'],
        "remediation": "Replace REUSE_ALV_LIST_DISPLAY with CL_SALV_TABLE.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_163": {
        "title": "REUSE_ALV_FIELDCATALOG_MERGE → CL_SALV_TABLE",
        "category": "Deprecated Function Modules",
        "description": (
            "REUSE_ALV_FIELDCATALOG_MERGE deprecated. CL_SALV_TABLE auto-generates "
            "field catalog from structure."
        ),
        "severity": "YELLOW",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "Use CL_SALV_TABLE with automatic column generation instead.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_164": {
        "title": "REUSE_ALV_HIERSEQ_LIST_DISPLAY → CL_SALV_HIERSEQ",
        "category": "Deprecated Function Modules",
        "description": (
            "REUSE_ALV_HIERSEQ_LIST_DISPLAY deprecated. Use CL_SALV_HIERSEQ_TABLE for "
            "hierarchical ALV."
        ),
        "severity": "YELLOW",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "Replace with CL_SALV_HIERSEQ_TABLE=>FACTORY().",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_165": {
        "title": "POPUP_TO_CONFIRM_STEP → POPUP_TO_CONFIRM",
        "category": "Deprecated Function Modules",
        "description": (
            "POPUP_TO_CONFIRM_STEP is obsolete. Replace with POPUP_TO_CONFIRM."
        ),
        "severity": "YELLOW",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "Replace POPUP_TO_CONFIRM_STEP with POPUP_TO_CONFIRM.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_166": {
        "title": "POPUP_TO_CONFIRM_LOSS_OF_DATA → POPUP_TO_CONFIRM",
        "category": "Deprecated Function Modules",
        "description": (
            "POPUP_TO_CONFIRM_LOSS_OF_DATA is obsolete. Replace with "
            "POPUP_TO_CONFIRM."
        ),
        "severity": "YELLOW",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "Replace with POPUP_TO_CONFIRM using appropriate text.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_167": {
        "title": "POPUP_TO_DECIDE → POPUP_TO_CONFIRM",
        "category": "Deprecated Function Modules",
        "description": (
            "POPUP_TO_DECIDE is obsolete. Replace with POPUP_TO_CONFIRM with buttons."
        ),
        "severity": "YELLOW",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "Replace with POPUP_TO_CONFIRM using yes/no/cancel buttons.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_168": {
        "title": "POPUP_TO_DISPLAY_TEXT → POPUP_TO_INFORM",
        "category": "Deprecated Function Modules",
        "description": (
            "POPUP_TO_DISPLAY_TEXT is obsolete. Replace with POPUP_TO_INFORM."
        ),
        "severity": "YELLOW",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "Replace with POPUP_TO_INFORM for informational popups.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_169": {
        "title": "GUI_UPLOAD → CL_GUI_FRONTEND_SERVICES",
        "category": "Deprecated Function Modules",
        "description": (
            "GUI_UPLOAD is deprecated. Use CL_GUI_FRONTEND_SERVICES=>GUI_UPLOAD for "
            "file upload."
        ),
        "severity": "YELLOW",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "Replace GUI_UPLOAD with CL_GUI_FRONTEND_SERVICES=>GUI_UPLOAD.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_170": {
        "title": "GUI_DOWNLOAD → CL_GUI_FRONTEND_SERVICES",
        "category": "Deprecated Function Modules",
        "description": (
            "GUI_DOWNLOAD is deprecated. Use CL_GUI_FRONTEND_SERVICES=>GUI_DOWNLOAD "
            "for file download."
        ),
        "severity": "YELLOW",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "Replace GUI_DOWNLOAD with CL_GUI_FRONTEND_SERVICES=>GUI_DOWNLOAD.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_171": {
        "title": "WS_UPLOAD → CL_GUI_FRONTEND_SERVICES",
        "category": "Deprecated Function Modules",
        "description": (
            "WS_UPLOAD is obsolete. Use CL_GUI_FRONTEND_SERVICES=>GUI_UPLOAD."
        ),
        "severity": "RED",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "Replace WS_UPLOAD with CL_GUI_FRONTEND_SERVICES=>GUI_UPLOAD.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_172": {
        "title": "WS_DOWNLOAD → CL_GUI_FRONTEND_SERVICES",
        "category": "Deprecated Function Modules",
        "description": (
            "WS_DOWNLOAD is obsolete. Use CL_GUI_FRONTEND_SERVICES=>GUI_DOWNLOAD."
        ),
        "severity": "RED",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "Replace WS_DOWNLOAD with CL_GUI_FRONTEND_SERVICES=>GUI_DOWNLOAD.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_173": {
        "title": "SO_NEW_DOCUMENT_SEND_API1 → CL_BCS",
        "category": "Deprecated Function Modules",
        "description": (
            "SO_NEW_DOCUMENT_SEND_API1 is deprecated. Use Business Communication "
            "Services (CL_BCS) for email sending."
        ),
        "severity": "YELLOW",
        "affected_tables": [],
        "affected_transactions": ['SE37', 'SCOT'],
        "remediation": "Replace with CL_BCS=>CREATE_PERSISTENT() for email/document sending.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_174": {
        "title": "SO_NEW_DOCUMENT_ATT_SEND_API1 → CL_BCS",
        "category": "Deprecated Function Modules",
        "description": (
            "SO_NEW_DOCUMENT_ATT_SEND_API1 is deprecated. CL_BCS handles attachments "
            "natively."
        ),
        "severity": "YELLOW",
        "affected_tables": [],
        "affected_transactions": ['SE37', 'SCOT'],
        "remediation": "Replace with CL_BCS and CL_DOCUMENT_BCS for attachments.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_175": {
        "title": "READ_TEXT Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "READ_TEXT still works but text storage adapted. Consider STXH/STXL "
            "archiving for performance."
        ),
        "severity": "GREEN",
        "affected_tables": ['STXH', 'STXL'],
        "affected_transactions": ['SE75', 'SE37'],
        "remediation": "No code change needed. Review text volume and archiving.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_176": {
        "title": "SAVE_TEXT Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "SAVE_TEXT still works. Text persistence via STXH/STXL unchanged in "
            "S/4HANA."
        ),
        "severity": "GREEN",
        "affected_tables": ['STXH', 'STXL'],
        "affected_transactions": ['SE37'],
        "remediation": "No code change needed.",
        "effort_hours": 2,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_177": {
        "title": "CONVERSION_EXIT_ALPHA_INPUT Still Works",
        "category": "Deprecated Function Modules",
        "description": (
            "CONVERSION_EXIT_ALPHA_INPUT still works. Leading zero padding for "
            "alphanumeric fields unchanged."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "No action needed. FM works as before.",
        "effort_hours": 2,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_178": {
        "title": "CONVERSION_EXIT_ALPHA_OUTPUT Still Works",
        "category": "Deprecated Function Modules",
        "description": (
            "CONVERSION_EXIT_ALPHA_OUTPUT still works. Leading zero removal "
            "unchanged."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "No action needed.",
        "effort_hours": 2,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_179": {
        "title": "CONVERSION_EXIT_MATN1_INPUT 40-Char Material",
        "category": "Deprecated Function Modules",
        "description": (
            "CONVERSION_EXIT_MATN1_INPUT adapted for 40-character material number "
            "length in S/4HANA."
        ),
        "severity": "YELLOW",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "Review material number formatting for 40-char support.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_180": {
        "title": "CONVERSION_EXIT_MATN1_OUTPUT 40-Char Material",
        "category": "Deprecated Function Modules",
        "description": (
            "CONVERSION_EXIT_MATN1_OUTPUT adapted for 40-character material number "
            "display."
        ),
        "severity": "YELLOW",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "Review material number display formatting.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "FM_181": {
        "title": "RFC_READ_TABLE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "RFC_READ_TABLE adapted. Some tables are now compatibility views. "
            "Performance may differ on ACDOCA/MATDOC."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['SE37', 'SM59'],
        "remediation": "Review RFC_READ_TABLE calls against deprecated tables.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_182": {
        "title": "BAPI_TRANSACTION_COMMIT Still Works",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_TRANSACTION_COMMIT continues to work. COMMIT WORK behavior "
            "unchanged."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "No action needed.",
        "effort_hours": 2,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_183": {
        "title": "BAPI_TRANSACTION_ROLLBACK Still Works",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_TRANSACTION_ROLLBACK continues to work. ROLLBACK WORK behavior "
            "unchanged."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "No action needed.",
        "effort_hours": 2,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_184": {
        "title": "BAPI_MESSAGE_GETDETAIL Still Works",
        "category": "Deprecated Function Modules",
        "description": (
            "BAPI_MESSAGE_GETDETAIL continues to work. Message class reading "
            "unchanged."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "No action needed.",
        "effort_hours": 2,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_185": {
        "title": "ADDR_GET → BP Address Model",
        "category": "Deprecated Function Modules",
        "description": (
            "ADDR_GET adapted. Address retrieval should use BP address model "
            "(BUT020/ADRC) for customers and vendors."
        ),
        "severity": "YELLOW",
        "affected_tables": ['ADRC', 'BUT020'],
        "affected_transactions": ['SE37'],
        "remediation": "Adapt address retrieval for BP-based address model.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "FM_186": {
        "title": "ADDR_INSERT → BP Address Model",
        "category": "Deprecated Function Modules",
        "description": (
            "ADDR_INSERT adapted. Address creation should use BP address APIs for "
            "customer/vendor addresses."
        ),
        "severity": "YELLOW",
        "affected_tables": ['ADRC', 'BUT020'],
        "affected_transactions": ['SE37'],
        "remediation": "Use BP address maintenance for customer/vendor address creation.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "FM_187": {
        "title": "BDC_OPEN_GROUP Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BDC_OPEN_GROUP still works. Batch input processing adapted for S/4HANA "
            "transactions."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['SM35', 'SE37'],
        "remediation": "Review batch input recordings for deprecated transactions.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_188": {
        "title": "BDC_INSERT Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BDC_INSERT still works. Batch input data lines must reference valid "
            "S/4HANA transactions."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['SM35', 'SE37'],
        "remediation": "Update batch input programs for renamed/replaced transactions.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_189": {
        "title": "BDC_CLOSE_GROUP Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "BDC_CLOSE_GROUP still works. Batch input group processing unchanged."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['SM35', 'SE37'],
        "remediation": "No change needed to group closing logic.",
        "effort_hours": 2,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_190": {
        "title": "CALL_BROWSER → CL_GUI_HTML_VIEWER",
        "category": "Deprecated Function Modules",
        "description": (
            "CALL_BROWSER is obsolete. Use CL_GUI_HTML_VIEWER for in-GUI browser "
            "display."
        ),
        "severity": "YELLOW",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "Replace CALL_BROWSER with CL_GUI_HTML_VIEWER=>SHOW_URL.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_191": {
        "title": "GET_PRINT_PARAMETERS Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "GET_PRINT_PARAMETERS adapted. Spool handling changed for new output "
            "management framework."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['SE37', 'SP01'],
        "remediation": "Review print parameter handling for new output framework.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "FM_192": {
        "title": "GET_SPOOL_REQUEST Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "GET_SPOOL_REQUEST adapted for S/4HANA spool management."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['SP01', 'SE37'],
        "remediation": "Review spool request handling.",
        "effort_hours": 4,
        "responsible_team": "Basis",
        "sap_note": "2296888",
    },
    "FM_193": {
        "title": "SAPGUI_SET_FUNCTIONCODE Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "SAPGUI_SET_FUNCTIONCODE adapted. GUI function key handling works but "
            "Fiori is strategic."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "Works in SAP GUI. Plan Fiori migration for strategic direction.",
        "effort_hours": 2,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_194": {
        "title": "SX_TABLE_LINE_WIDTH_ANY Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "SX_TABLE_LINE_WIDTH_ANY adapted. Table line width determination for text "
            "processing."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "No action needed unless custom text processing.",
        "effort_hours": 2,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_195": {
        "title": "SX_OBJECT_CONVERT Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "SX_OBJECT_CONVERT (document format conversion) adapted. OLE object "
            "handling may differ."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "Test document conversion scenarios if used.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_196": {
        "title": "TERM_TRANSLATE_TO_EXTERNAL Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "TERM_TRANSLATE_TO_EXTERNAL adapted for S/4HANA text processing."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "No action needed.",
        "effort_hours": 2,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_197": {
        "title": "DOMAIN_VALUE_GET Still Works",
        "category": "Deprecated Function Modules",
        "description": (
            "DOMAIN_VALUE_GET continues to work. Domain value retrieval unchanged."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "No action needed.",
        "effort_hours": 2,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "FM_198": {
        "title": "NUMBER_GET_NEXT Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "NUMBER_GET_NEXT adapted. Number range buffering must accommodate "
            "ACDOCA/MATDOC volume."
        ),
        "severity": "GREEN",
        "affected_tables": ['NRIV'],
        "affected_transactions": ['SNRO', 'SE37'],
        "remediation": "Review number range buffer size for high-volume ACDOCA postings.",
        "effort_hours": 4,
        "responsible_team": "Basis",
        "sap_note": "2253416",
    },
    "FM_199": {
        "title": "AUTHORITY_CHECK_TCODE Still Works",
        "category": "Deprecated Function Modules",
        "description": (
            "AUTHORITY_CHECK_TCODE continues to work. Transaction authorization check "
            "unchanged."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['SE37'],
        "remediation": "No action needed. Update authorized tcodes for S/4HANA.",
        "effort_hours": 2,
        "responsible_team": "Basis",
        "sap_note": "2270689",
    },
    "FM_200": {
        "title": "ENQUEUE_READ Adapted",
        "category": "Deprecated Function Modules",
        "description": (
            "ENQUEUE_READ (lock entry read) adapted. Enqueue server behavior "
            "unchanged in S/4HANA."
        ),
        "severity": "GREEN",
        "affected_tables": [],
        "affected_transactions": ['SM12', 'SE37'],
        "remediation": "No action needed.",
        "effort_hours": 2,
        "responsible_team": "Basis",
        "sap_note": "2270689",
    },
}
