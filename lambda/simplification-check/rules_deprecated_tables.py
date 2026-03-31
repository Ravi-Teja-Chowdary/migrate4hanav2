"""
Migrate4HANA - Deprecated Tables Simplification Rules
=====================================================
200 rules covering SAP tables that are removed, replaced,
or converted to compatibility views in S/4HANA.

Reference: SAP Note 2240359 - Simplification List for S/4HANA
"""

DEPRECATED_TABLE_RULES = {
    "TBL_001": {
        "title": "BSEG Replaced by ACDOCA Compatibility View",
        "category": "Deprecated Tables",
        "description": (
            "BSEG (accounting document segment) is replaced by ACDOCA. BSEG becomes a "
            "compatibility view. Direct INSERTs, UPDATEs, DELETEs fail. SELECTs "
            "redirected but slower."
        ),
        "severity": "RED",
        "affected_tables": ['BSEG', 'ACDOCA'],
        "affected_transactions": ['FB01', 'FB02', 'FB03'],
        "remediation": "Replace BSEG reads with ACDOCA or CDS view I_JOURNALENTRYITEM. Remove all direct BSEG modifications.",
        "effort_hours": 40,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_002": {
        "title": "BSID Customer Open Items → ACDOCA View",
        "category": "Deprecated Tables",
        "description": (
            "BSID (open customer items) is a compatibility view on ACDOCA. Custom AR "
            "reports must be adapted."
        ),
        "severity": "RED",
        "affected_tables": ['BSID', 'ACDOCA'],
        "affected_transactions": ['FBL5N', 'FD10N'],
        "remediation": "Replace BSID reads with ACDOCA WHERE AUGDT IS INITIAL or CDS view I_JOURNALENTRYITEM.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_003": {
        "title": "BSAD Customer Cleared Items → ACDOCA View",
        "category": "Deprecated Tables",
        "description": (
            "BSAD (cleared customer items) is a compatibility view on ACDOCA. "
            "Customer aging and clearing reports must be adapted."
        ),
        "severity": "RED",
        "affected_tables": ['BSAD', 'ACDOCA'],
        "affected_transactions": ['FBL5N'],
        "remediation": "Replace BSAD reads with ACDOCA WHERE AUGDT IS NOT INITIAL.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_004": {
        "title": "BSIK Vendor Open Items → ACDOCA View",
        "category": "Deprecated Tables",
        "description": (
            "BSIK (open vendor items) is a compatibility view on ACDOCA. Custom AP "
            "open item reports must be adapted."
        ),
        "severity": "RED",
        "affected_tables": ['BSIK', 'ACDOCA'],
        "affected_transactions": ['FBL1N', 'FK10N'],
        "remediation": "Replace BSIK reads with ACDOCA WHERE AUGDT IS INITIAL and account type K.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_005": {
        "title": "BSAK Vendor Cleared Items → ACDOCA View",
        "category": "Deprecated Tables",
        "description": (
            "BSAK (cleared vendor items) is a compatibility view on ACDOCA. Custom "
            "vendor payment history reports must be adapted."
        ),
        "severity": "RED",
        "affected_tables": ['BSAK', 'ACDOCA'],
        "affected_transactions": ['FBL1N'],
        "remediation": "Replace BSAK reads with ACDOCA WHERE AUGDT IS NOT INITIAL and account type K.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_006": {
        "title": "BSIS GL Open Items → ACDOCA View",
        "category": "Deprecated Tables",
        "description": (
            "BSIS (GL open items) is a compatibility view on ACDOCA. Custom GL open "
            "item reports must be adapted."
        ),
        "severity": "RED",
        "affected_tables": ['BSIS', 'ACDOCA'],
        "affected_transactions": ['FBL3N'],
        "remediation": "Replace BSIS reads with ACDOCA or CDS view I_JOURNALENTRYITEM.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_007": {
        "title": "BSAS GL Cleared Items → ACDOCA View",
        "category": "Deprecated Tables",
        "description": (
            "BSAS (GL cleared items) is a compatibility view on ACDOCA. Custom GL "
            "cleared item reports must be adapted."
        ),
        "severity": "RED",
        "affected_tables": ['BSAS', 'ACDOCA'],
        "affected_transactions": ['FBL3N'],
        "remediation": "Replace BSAS reads with ACDOCA WHERE AUGDT IS NOT INITIAL.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_008": {
        "title": "GLT0 Classic GL Totals Eliminated",
        "category": "Deprecated Tables",
        "description": (
            "GLT0 (classic GL totals) is eliminated. Totals derived from ACDOCA "
            "aggregation or FAGLFLEXT. All custom reports on GLT0 must migrate."
        ),
        "severity": "RED",
        "affected_tables": ['GLT0', 'ACDOCA', 'FAGLFLEXT'],
        "affected_transactions": ['F.01', 'S_ALR_87012284'],
        "remediation": "Replace GLT0 reads with ACDOCA aggregation or CDS views for balance reporting.",
        "effort_hours": 24,
        "responsible_team": "ABAP dev",
        "sap_note": "2272189",
    },
    "TBL_009": {
        "title": "GLPCA Profit Center Actuals Eliminated",
        "category": "Deprecated Tables",
        "description": (
            "GLPCA (profit center actual line items) is eliminated. Profit center "
            "accounting is fully integrated into ACDOCA via the PRCTR field."
        ),
        "severity": "RED",
        "affected_tables": ['GLPCA', 'ACDOCA'],
        "affected_transactions": ['KE5Z', 'S_ALR_87013611'],
        "remediation": "Replace GLPCA reads with ACDOCA WHERE PRCTR IS NOT INITIAL.",
        "effort_hours": 24,
        "responsible_team": "ABAP dev",
        "sap_note": "2272189",
    },
    "TBL_010": {
        "title": "GLPCT Profit Center Totals Eliminated",
        "category": "Deprecated Tables",
        "description": (
            "GLPCT (profit center totals/texts) is eliminated. Planning data managed "
            "through ACDOCP."
        ),
        "severity": "RED",
        "affected_tables": ['GLPCT', 'ACDOCP'],
        "affected_transactions": ['KE5Z'],
        "remediation": "Replace GLPCT with ACDOCP for plan line items or ACDOCA for actuals.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2272189",
    },
    "TBL_011": {
        "title": "GLFUNCT Functional Area Totals Eliminated",
        "category": "Deprecated Tables",
        "description": (
            "GLFUNCT (functional area totals) is eliminated. Functional area is a "
            "field in ACDOCA derived via substitution."
        ),
        "severity": "YELLOW",
        "affected_tables": ['GLFUNCT', 'ACDOCA'],
        "affected_transactions": [],
        "remediation": "Use ACDOCA FKBER field for functional area reporting.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2272189",
    },
    "TBL_012": {
        "title": "FAGLFLEXA New GL Line Items → ACDOCA",
        "category": "Deprecated Tables",
        "description": (
            "FAGLFLEXA (New GL actual line items) is replaced by ACDOCA. FAGLFLEXA "
            "becomes a compatibility view."
        ),
        "severity": "RED",
        "affected_tables": ['FAGLFLEXA', 'ACDOCA'],
        "affected_transactions": ['FAGLB03'],
        "remediation": "Replace FAGLFLEXA reads with ACDOCA.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_013": {
        "title": "FAGLFLEXT New GL Totals → ACDOCA",
        "category": "Deprecated Tables",
        "description": (
            "FAGLFLEXT (New GL totals) remains but is populated from ACDOCA. Custom "
            "totals queries should use ACDOCA aggregation for real-time data."
        ),
        "severity": "YELLOW",
        "affected_tables": ['FAGLFLEXT', 'ACDOCA'],
        "affected_transactions": ['FAGLB03'],
        "remediation": "FAGLFLEXT still available but consider ACDOCA for real-time totals.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_014": {
        "title": "COEP CO Line Items → ACDOCA View",
        "category": "Deprecated Tables",
        "description": (
            "COEP (controlling actual line items) is a compatibility view on ACDOCA. "
            "All CO postings are now in ACDOCA. Custom CO reports must be adapted."
        ),
        "severity": "RED",
        "affected_tables": ['COEP', 'ACDOCA'],
        "affected_transactions": ['KSB1', 'KOB1'],
        "remediation": "Replace COEP reads with ACDOCA WHERE KOKRS IS NOT INITIAL or CDS view I_OPERATIONALACCTGDOCITEM.",
        "effort_hours": 24,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_015": {
        "title": "COBK CO Document Header → ACDOCA View",
        "category": "Deprecated Tables",
        "description": (
            "COBK (CO document header) is a compatibility view. CO document headers "
            "are integrated into BKPF/ACDOCA."
        ),
        "severity": "RED",
        "affected_tables": ['COBK', 'ACDOCA', 'BKPF'],
        "affected_transactions": ['KSB1'],
        "remediation": "Replace COBK reads with BKPF or ACDOCA header fields.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_016": {
        "title": "COSP CO Totals Primary Costs → ACDOCA View",
        "category": "Deprecated Tables",
        "description": (
            "COSP (CO totals for primary/external costs) is a compatibility view on "
            "ACDOCA. CO cost element reporting must use ACDOCA aggregation."
        ),
        "severity": "RED",
        "affected_tables": ['COSP', 'ACDOCA'],
        "affected_transactions": ['KSB1', 'S_ALR_87013611'],
        "remediation": "Replace COSP reads with ACDOCA aggregation or I_OPERATIONALACCTGDOCITEM.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_017": {
        "title": "COSS CO Totals Secondary Costs → ACDOCA View",
        "category": "Deprecated Tables",
        "description": (
            "COSS (CO totals for secondary/internal costs) is a compatibility view on "
            "ACDOCA. Internal order and cost center allocation reports must adapt."
        ),
        "severity": "RED",
        "affected_tables": ['COSS', 'ACDOCA'],
        "affected_transactions": ['KSB1'],
        "remediation": "Replace COSS reads with ACDOCA or I_OPERATIONALACCTGDOCITEM CDS view.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_018": {
        "title": "COKA Cost Element Master Eliminated → GL Account",
        "category": "Deprecated Tables",
        "description": (
            "COKA (cost element master) is eliminated. Cost elements are merged with "
            "GL accounts in S/4HANA. Table SKA1/SKAT is used instead."
        ),
        "severity": "RED",
        "affected_tables": ['COKA', 'CSKB', 'SKA1', 'SKAT'],
        "affected_transactions": ['KA01', 'KA02', 'KA03'],
        "remediation": "Replace cost element master reads with GL account master (SKA1/SKAT). Transaction FS00 replaces KA01.",
        "effort_hours": 24,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "TBL_019": {
        "title": "CSKB Cost Element Categories → GL Account Type",
        "category": "Deprecated Tables",
        "description": (
            "CSKB cost element categories merged into GL account type in S/4HANA. "
            "Cost element concept replaced by GL account with cost element category."
        ),
        "severity": "RED",
        "affected_tables": ['CSKB', 'SKA1'],
        "affected_transactions": ['KA01', 'KA02'],
        "remediation": "Use GL account master with cost element category attribute instead of CSKB.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "TBL_020": {
        "title": "CSKA Cost Element Texts Eliminated",
        "category": "Deprecated Tables",
        "description": (
            "CSKA (cost element texts) replaced by GL account texts (SKAT). Cost "
            "element text maintenance via FS00."
        ),
        "severity": "RED",
        "affected_tables": ['CSKA', 'SKAT'],
        "affected_transactions": ['KA01'],
        "remediation": "Replace CSKA reads with SKAT. Use FS00 for GL account/cost element text maintenance.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "TBL_021": {
        "title": "ANLP Asset Periodic Values Eliminated",
        "category": "Deprecated Tables",
        "description": (
            "ANLP (asset periodic values) is eliminated with New Asset Accounting. "
            "Periodic depreciation values are in ACDOCA."
        ),
        "severity": "RED",
        "affected_tables": ['ANLP', 'ACDOCA'],
        "affected_transactions": ['AW01N', 'S_ALR_87011990'],
        "remediation": "Replace ANLP reads with ACDOCA or asset CDS views.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2253616",
    },
    "TBL_022": {
        "title": "ANLC Asset Value Fields Eliminated",
        "category": "Deprecated Tables",
        "description": (
            "ANLC (asset value fields per area) is eliminated with New Asset "
            "Accounting. Asset values are derived from ACDOCA line items."
        ),
        "severity": "RED",
        "affected_tables": ['ANLC', 'ACDOCA'],
        "affected_transactions": ['AW01N'],
        "remediation": "Replace ANLC reads with ACDOCA asset-related entries or CDS view I_FIXEDASSET.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2253616",
    },
    "TBL_023": {
        "title": "ANLA Asset Master Structure Changed",
        "category": "Deprecated Tables",
        "description": (
            "ANLA (asset master) structure changed. Several fields deprecated, new "
            "fields added for parallel valuation under new asset accounting."
        ),
        "severity": "YELLOW",
        "affected_tables": ['ANLA'],
        "affected_transactions": ['AS01', 'AS02', 'AS03'],
        "remediation": "Review custom ANLA field usage. Adapt SELECT statements for new structure.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2253616",
    },
    "TBL_024": {
        "title": "ANEK Asset Document Header Eliminated",
        "category": "Deprecated Tables",
        "description": (
            "ANEK (asset document header) is eliminated. Asset documents unified into "
            "BKPF/ACDOCA. Separate asset sub-ledger documents removed."
        ),
        "severity": "RED",
        "affected_tables": ['ANEK', 'BKPF', 'ACDOCA'],
        "affected_transactions": ['AB01', 'AW01N'],
        "remediation": "Replace ANEK reads with BKPF WHERE BLART = AA or asset CDS views.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2253616",
    },
    "TBL_025": {
        "title": "ANEP Asset Line Items Eliminated",
        "category": "Deprecated Tables",
        "description": (
            "ANEP (asset line items) is eliminated. Asset postings are line items in "
            "ACDOCA with asset-specific fields."
        ),
        "severity": "RED",
        "affected_tables": ['ANEP', 'ACDOCA'],
        "affected_transactions": ['AW01N'],
        "remediation": "Replace ANEP reads with ACDOCA WHERE ANLN1 IS NOT INITIAL.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2253616",
    },
    "TBL_026": {
        "title": "ANEA Asset Proportional Values Eliminated",
        "category": "Deprecated Tables",
        "description": (
            "ANEA (proportional values for retired portions) is eliminated with New "
            "Asset Accounting. Retirement tracking integrated in ACDOCA."
        ),
        "severity": "RED",
        "affected_tables": ['ANEA', 'ACDOCA'],
        "affected_transactions": ['ABAVN'],
        "remediation": "Replace ANEA reads with ACDOCA retirement line items.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2253616",
    },
    "TBL_027": {
        "title": "KNC1 Customer Transaction Figures Eliminated",
        "category": "Deprecated Tables",
        "description": (
            "KNC1 (customer transaction figures) is a compatibility view. Customer "
            "transaction figures derived from ACDOCA aggregation."
        ),
        "severity": "RED",
        "affected_tables": ['KNC1', 'ACDOCA'],
        "affected_transactions": ['FD10N'],
        "remediation": "Replace KNC1 reads with ACDOCA aggregation or I_CUSTOMERLINEITEM CDS view.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_028": {
        "title": "KNC3 Customer Special GL Figures Eliminated",
        "category": "Deprecated Tables",
        "description": (
            "KNC3 (customer special GL transaction figures) is a compatibility view. "
            "Down payments and special GL tracked in ACDOCA."
        ),
        "severity": "YELLOW",
        "affected_tables": ['KNC3', 'ACDOCA'],
        "affected_transactions": ['FD10N'],
        "remediation": "Replace KNC3 with ACDOCA WHERE UMSKZ IS NOT INITIAL.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_029": {
        "title": "LFC1 Vendor Transaction Figures Eliminated",
        "category": "Deprecated Tables",
        "description": (
            "LFC1 (vendor transaction figures) is a compatibility view on ACDOCA. "
            "Vendor balance reports must adapt."
        ),
        "severity": "RED",
        "affected_tables": ['LFC1', 'ACDOCA'],
        "affected_transactions": ['FK10N'],
        "remediation": "Replace LFC1 reads with ACDOCA aggregation or I_SUPPLIERLINEITEM CDS view.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_030": {
        "title": "LFC3 Vendor Special GL Figures Eliminated",
        "category": "Deprecated Tables",
        "description": (
            "LFC3 (vendor special GL transaction figures) is a compatibility view on "
            "ACDOCA."
        ),
        "severity": "YELLOW",
        "affected_tables": ['LFC3', 'ACDOCA'],
        "affected_transactions": ['FK10N'],
        "remediation": "Replace LFC3 with ACDOCA WHERE UMSKZ IS NOT INITIAL.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_031": {
        "title": "SKC1A GL Consolidation Totals Eliminated",
        "category": "Deprecated Tables",
        "description": (
            "SKC1A (GL consolidation totals) eliminated. Consolidation staging via "
            "ACDOCA or Group Reporting."
        ),
        "severity": "YELLOW",
        "affected_tables": ['SKC1A', 'ACDOCA'],
        "affected_transactions": [],
        "remediation": "Use ACDOCA with ledger group for consolidation data.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2272189",
    },
    "TBL_032": {
        "title": "SKC1B GL Consolidation Totals Eliminated",
        "category": "Deprecated Tables",
        "description": (
            "SKC1B (GL consolidation totals second currency) eliminated alongside "
            "SKC1A."
        ),
        "severity": "YELLOW",
        "affected_tables": ['SKC1B', 'ACDOCA'],
        "affected_transactions": [],
        "remediation": "Use ACDOCA with ledger group for multi-currency consolidation.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2272189",
    },
    "TBL_033": {
        "title": "BVOR Intercompany Posting Procedures Eliminated",
        "category": "Deprecated Tables",
        "description": (
            "BVOR (intercompany posting procedures) is eliminated. Intercompany "
            "posting handled via ACDOCA cross-company fields."
        ),
        "severity": "YELLOW",
        "affected_tables": ['BVOR'],
        "affected_transactions": [],
        "remediation": "Use ACDOCA intercompany fields and cross-company code posting configuration.",
        "effort_hours": 8,
        "responsible_team": "Functional",
        "sap_note": "2272189",
    },
    "TBL_034": {
        "title": "FAGL_SPLINFO Document Splitting Info Changed",
        "category": "Deprecated Tables",
        "description": (
            "FAGL_SPLINFO (document splitting information) is embedded in ACDOCA. "
            "Splitting logic uses ACDOCA fields directly."
        ),
        "severity": "YELLOW",
        "affected_tables": ['FAGL_SPLINFO', 'ACDOCA'],
        "affected_transactions": [],
        "remediation": "Replace FAGL_SPLINFO reads with ACDOCA splitting-related fields.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_035": {
        "title": "CE1xxxx CO-PA Actual Line Items Changed",
        "category": "Deprecated Tables",
        "description": (
            "CE1xxxx (CO-PA actual line items for costing-based) are significantly "
            "changed. Account-based CO-PA is mandatory in S/4HANA; costing-based is "
            "optional and reads from ACDOCA."
        ),
        "severity": "RED",
        "affected_tables": ['CE1xxxx', 'CE2xxxx', 'ACDOCA'],
        "affected_transactions": ['KE24', 'KE30'],
        "remediation": "Activate account-based CO-PA. Adapt CE1/CE2 reports for ACDOCA integration.",
        "effort_hours": 80,
        "responsible_team": "Functional",
        "sap_note": "2296888",
    },
    "TBL_036": {
        "title": "CE2xxxx CO-PA Summarization Level Changed",
        "category": "Deprecated Tables",
        "description": (
            "CE2xxxx (CO-PA summarization data) adapted for account-based CO-PA "
            "mandatory activation."
        ),
        "severity": "RED",
        "affected_tables": ['CE2xxxx', 'ACDOCA'],
        "affected_transactions": ['KE30'],
        "remediation": "Review summarization hierarchy for account-based CO-PA.",
        "effort_hours": 40,
        "responsible_team": "Functional",
        "sap_note": "2296888",
    },
    "TBL_037": {
        "title": "CE3xxxx CO-PA Plan Data Changed",
        "category": "Deprecated Tables",
        "description": (
            "CE3xxxx (CO-PA plan line items) adapted. Planning integrated with ACDOCP "
            "for account-based plan data."
        ),
        "severity": "YELLOW",
        "affected_tables": ['CE3xxxx', 'ACDOCP'],
        "affected_transactions": ['KE30'],
        "remediation": "Adapt CO-PA planning reports. Consider account-based plan source.",
        "effort_hours": 40,
        "responsible_team": "Functional",
        "sap_note": "2296888",
    },
    "TBL_038": {
        "title": "CE4xxxx CO-PA Configuration Changed",
        "category": "Deprecated Tables",
        "description": (
            "CE4xxxx (CO-PA operating concern configuration tables) must be adapted "
            "for S/4HANA mandatory account-based CO-PA."
        ),
        "severity": "YELLOW",
        "affected_tables": ['CE4xxxx'],
        "affected_transactions": ['KEA0', 'KE4A'],
        "remediation": "Review operating concern configuration for account-based compatibility.",
        "effort_hours": 24,
        "responsible_team": "Functional",
        "sap_note": "2296888",
    },
    "TBL_039": {
        "title": "KNKK Credit Management → UKM Tables",
        "category": "Deprecated Tables",
        "description": (
            "KNKK (customer credit management) is replaced by SAP Credit Management "
            "(UKM). UKM_BUPA, UKM_LIMIT tables are the new master data."
        ),
        "severity": "RED",
        "affected_tables": ['KNKK', 'UKM_BUPA', 'UKM_LIMIT'],
        "affected_transactions": ['FD32', 'FD33', 'UKM_BP'],
        "remediation": "Migrate credit data from KNKK to UKM. Use transaction UKM_BP for credit limits.",
        "effort_hours": 40,
        "responsible_team": "Functional",
        "sap_note": "2265093",
    },
    "TBL_040": {
        "title": "REGUH Payment Header Adapted",
        "category": "Deprecated Tables",
        "description": (
            "REGUH (payment program header) structure adapted for S/4HANA payment "
            "processing with BP integration."
        ),
        "severity": "YELLOW",
        "affected_tables": ['REGUH', 'REGUP'],
        "affected_transactions": ['F110'],
        "remediation": "Review custom payment program exits. Adapt for new REGUH/REGUP fields.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_041": {
        "title": "REGUP Payment Items Adapted",
        "category": "Deprecated Tables",
        "description": (
            "REGUP (payment program item) structure adapted. BP-based partner fields "
            "included, vendor/customer number adapted."
        ),
        "severity": "YELLOW",
        "affected_tables": ['REGUP'],
        "affected_transactions": ['F110'],
        "remediation": "Review custom REGUP field usage in payment exits and reports.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_042": {
        "title": "BKPF Accounting Document Header Adapted",
        "category": "Deprecated Tables",
        "description": (
            "BKPF (accounting document header) enriched with ACDOCA-related fields. "
            "Custom code should use BKPF with ACDOCA for complete document data."
        ),
        "severity": "GREEN",
        "affected_tables": ['BKPF', 'ACDOCA'],
        "affected_transactions": ['FB03'],
        "remediation": "Review BKPF custom field usage. No action if only standard fields used.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_043": {
        "title": "MHNK Dunning Data Adapted",
        "category": "Deprecated Tables",
        "description": (
            "MHNK (dunning history) adapted for business partner integration. "
            "Customer/vendor number fields aligned with BP."
        ),
        "severity": "YELLOW",
        "affected_tables": ['MHNK'],
        "affected_transactions": ['F150'],
        "remediation": "Adapt dunning reports and custom logic for BP partner numbers.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_044": {
        "title": "WITH_ITEM Extended Withholding Tax Adapted",
        "category": "Deprecated Tables",
        "description": (
            "WITH_ITEM (extended withholding tax line items) adapted for ACDOCA. "
            "Withholding tax posting integrated into universal journal."
        ),
        "severity": "YELLOW",
        "affected_tables": ['WITH_ITEM', 'ACDOCA'],
        "affected_transactions": ['S_P00_07000134'],
        "remediation": "Review withholding tax reports. Adapt for ACDOCA-based WHT data.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_045": {
        "title": "FDES Cash Management Forecast Replaced",
        "category": "Deprecated Tables",
        "description": (
            "FDES (cash management planning data) replaced by new SAP Cash Management "
            "based on bank account model."
        ),
        "severity": "RED",
        "affected_tables": ['FDES', 'FDSR'],
        "affected_transactions": ['FF7A', 'FF7B'],
        "remediation": "Migrate to new SAP Cash Management. Use Fiori Liquidity Forecast apps.",
        "effort_hours": 40,
        "responsible_team": "Functional",
        "sap_note": "2265093",
    },
    "TBL_046": {
        "title": "FDSR Cash Management Position Replaced",
        "category": "Deprecated Tables",
        "description": (
            "FDSR (cash management position record) replaced by new bank "
            "account-based cash management."
        ),
        "severity": "RED",
        "affected_tables": ['FDSR'],
        "affected_transactions": ['FF7A', 'FF7B'],
        "remediation": "Migrate cash position reporting to new Cash Management framework.",
        "effort_hours": 24,
        "responsible_team": "Functional",
        "sap_note": "2265093",
    },
    "TBL_047": {
        "title": "EWUFI Euro Conversion Tracking Eliminated",
        "category": "Deprecated Tables",
        "description": (
            "EWUFI (Euro currency conversion financial tracking) is obsolete and "
            "eliminated in S/4HANA."
        ),
        "severity": "GREEN",
        "affected_tables": ['EWUFI'],
        "affected_transactions": [],
        "remediation": "No action needed unless custom code references EWUFI.",
        "effort_hours": 2,
        "responsible_team": "ABAP dev",
        "sap_note": "2272189",
    },
    "TBL_048": {
        "title": "BSET Tax Data Segment → ACDOCA/ACCTIT View",
        "category": "Deprecated Tables",
        "description": (
            "BSET (tax data segment) becomes a compatibility view. Tax item details "
            "stored in ACDOCA/ACCTIT."
        ),
        "severity": "RED",
        "affected_tables": ['BSET', 'ACCTIT', 'ACDOCA'],
        "affected_transactions": ['FB03'],
        "remediation": "Replace BSET reads with ACCTIT or ACDOCA tax fields.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_049": {
        "title": "BSEC One-Time Account Data → ACDOCA View",
        "category": "Deprecated Tables",
        "description": (
            "BSEC (one-time account document segment) is a compatibility view on "
            "ACDOCA. One-time vendor/customer data in ACDOCA."
        ),
        "severity": "YELLOW",
        "affected_tables": ['BSEC', 'ACDOCA'],
        "affected_transactions": ['FB01'],
        "remediation": "Adapt one-time account processing for ACDOCA integration.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_050": {
        "title": "T030 Account Determination Extended for ACDOCA",
        "category": "Deprecated Tables",
        "description": (
            "T030 (automatic account determination) extended for ACDOCA posting "
            "rules. New transaction keys for asset accounting."
        ),
        "severity": "GREEN",
        "affected_tables": ['T030'],
        "affected_transactions": ['OBYC', 'OB40'],
        "remediation": "Verify automatic account determination for new ACDOCA transaction keys.",
        "effort_hours": 8,
        "responsible_team": "Functional",
        "sap_note": "2253416",
    },
    "TBL_051": {
        "title": "CSKS Cost Center Master Adapted",
        "category": "Deprecated Tables",
        "description": (
            "CSKS (cost center master) adapted for S/4HANA. Activity type and "
            "statistical key figure integration changed."
        ),
        "severity": "GREEN",
        "affected_tables": ['CSKS', 'CSKT'],
        "affected_transactions": ['KS01', 'KS02'],
        "remediation": "Review custom cost center master field usage.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "TBL_052": {
        "title": "ACCTIT Tax Line Extension for ACDOCA",
        "category": "Deprecated Tables",
        "description": (
            "ACCTIT (tax line item extension for ACDOCA) stores tax-relevant journal "
            "entry details. New table replacing BSET."
        ),
        "severity": "GREEN",
        "affected_tables": ['ACCTIT', 'ACDOCA'],
        "affected_transactions": ['FB01'],
        "remediation": "Review tax reporting referencing BSET and adapt for ACCTIT.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2253416",
    },
    "TBL_053": {
        "title": "ACDOCA_M_EXTRACT Material Ledger Extension",
        "category": "Deprecated Tables",
        "description": (
            "ACDOCA_M_EXTRACT stores material ledger entries in S/4HANA. Material "
            "ledger is mandatory, integrated into ACDOCA."
        ),
        "severity": "YELLOW",
        "affected_tables": ['ACDOCA_M_EXTRACT', 'ACDOCA'],
        "affected_transactions": ['CKM3N'],
        "remediation": "Activate material ledger if not already active.",
        "effort_hours": 16,
        "responsible_team": "Functional",
        "sap_note": "2267308",
    },
    "TBL_054": {
        "title": "CKMLHD Material Ledger Document Header",
        "category": "Deprecated Tables",
        "description": (
            "CKMLHD (material ledger header) continues but is mandatory in S/4HANA. "
            "Material valuation uses actual costing."
        ),
        "severity": "YELLOW",
        "affected_tables": ['CKMLHD', 'CKMLCR'],
        "affected_transactions": ['CKM3N'],
        "remediation": "Ensure material ledger activation. Review actual costing configuration.",
        "effort_hours": 12,
        "responsible_team": "Functional",
        "sap_note": "2267308",
    },
    "TBL_055": {
        "title": "NRIV Number Range Intervals Extended",
        "category": "Deprecated Tables",
        "description": (
            "NRIV (number range intervals) must accommodate ACDOCA document volume. "
            "Buffering and capacity review needed."
        ),
        "severity": "YELLOW",
        "affected_tables": ['NRIV'],
        "affected_transactions": ['SNRO'],
        "remediation": "Review and extend number range buffers for FI document numbers.",
        "effort_hours": 8,
        "responsible_team": "Basis",
        "sap_note": "2253416",
    },
    "TBL_056": {
        "title": "TCURR Exchange Rate Table Handling Changed",
        "category": "Deprecated Tables",
        "description": (
            "TCURR/TCURX (exchange rates/currency decimals) processing adapted for "
            "CURR field type changes in S/4HANA."
        ),
        "severity": "YELLOW",
        "affected_tables": ['TCURR', 'TCURX'],
        "affected_transactions": ['OB08'],
        "remediation": "Verify currency decimal handling in custom code.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2272189",
    },
    "TBL_057": {
        "title": "T001 Company Code Table New Fields",
        "category": "Deprecated Tables",
        "description": (
            "T001 (company code) receives new fields for extended ledger, parallel "
            "currencies, and S/4HANA-specific settings."
        ),
        "severity": "GREEN",
        "affected_tables": ['T001'],
        "affected_transactions": ['OB62'],
        "remediation": "Review new T001 fields and adapt customizing if needed.",
        "effort_hours": 4,
        "responsible_team": "Functional",
        "sap_note": "2272189",
    },
    "TBL_058": {
        "title": "AUFK Order Master Adapted for ACDOCA",
        "category": "Deprecated Tables",
        "description": (
            "AUFK (order master) settlement-relevant fields adapted for unified "
            "journal posting. Settlement to ACDOCA."
        ),
        "severity": "YELLOW",
        "affected_tables": ['AUFK', 'ACDOCA'],
        "affected_transactions": ['KO01', 'KO02', 'KO03'],
        "remediation": "Review custom AUFK field usage. Adapt settlement rule exits.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "TBL_059": {
        "title": "TKA01 Controlling Area Settings Changed",
        "category": "Deprecated Tables",
        "description": (
            "TKA01 controlling area settings adapted. Cross-company cost allocation "
            "and assessment logic consolidated."
        ),
        "severity": "YELLOW",
        "affected_tables": ['TKA01'],
        "affected_transactions": ['OKKP'],
        "remediation": "Review controlling area configuration for S/4HANA changes.",
        "effort_hours": 8,
        "responsible_team": "Functional",
        "sap_note": "2296888",
    },
    "TBL_060": {
        "title": "CDHDR Change Documents Volume Increase",
        "category": "Deprecated Tables",
        "description": (
            "CDHDR/CDPOS (change documents) volume increases significantly due to "
            "ACDOCA granularity. Archiving strategy essential."
        ),
        "severity": "YELLOW",
        "affected_tables": ['CDHDR', 'CDPOS'],
        "affected_transactions": ['RSSCD100'],
        "remediation": "Implement change document archiving strategy for ACDOCA volume.",
        "effort_hours": 16,
        "responsible_team": "Basis",
        "sap_note": "2272189",
    },
    "TBL_061": {
        "title": "MKPF Material Doc Header → MATDOC",
        "category": "Deprecated Tables",
        "description": (
            "MKPF (material document header) is a compatibility view on MATDOC. All "
            "goods movements create MATDOC entries."
        ),
        "severity": "RED",
        "affected_tables": ['MKPF', 'MATDOC'],
        "affected_transactions": ['MIGO', 'MB51', 'MB52'],
        "remediation": "Replace MKPF reads with MATDOC or CDS view I_MATERIALDOCUMENT.",
        "effort_hours": 24,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_062": {
        "title": "MSEG Material Doc Items → MATDOC",
        "category": "Deprecated Tables",
        "description": (
            "MSEG (material document items) is a compatibility view on MATDOC. Custom "
            "inventory movement reports must be migrated."
        ),
        "severity": "RED",
        "affected_tables": ['MSEG', 'MATDOC'],
        "affected_transactions": ['MIGO', 'MB51'],
        "remediation": "Replace MSEG reads with MATDOC or CDS view I_MATERIALDOCUMENTITEM.",
        "effort_hours": 24,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_063": {
        "title": "MARD Storage Location Stock → MATDOC View",
        "category": "Deprecated Tables",
        "description": (
            "MARD (storage location stock) structure changed. Stock quantities "
            "derived from MATDOC. MARD is a totals-style record."
        ),
        "severity": "RED",
        "affected_tables": ['MARD', 'MATDOC'],
        "affected_transactions": ['MMBE', 'MB52'],
        "remediation": "Replace MARD reads with MATDOC aggregation or I_MATERIALSTOCKBYSLOC.",
        "effort_hours": 24,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_064": {
        "title": "MARDH Storage Location Stock History Eliminated",
        "category": "Deprecated Tables",
        "description": (
            "MARDH (storage location stock history) is eliminated. Historical stock "
            "derived from MATDOC."
        ),
        "severity": "RED",
        "affected_tables": ['MARDH', 'MATDOC'],
        "affected_transactions": ['MB5B'],
        "remediation": "Replace MARDH reads with MATDOC historical aggregation.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_065": {
        "title": "MCHB Batch Stock → MATDOC View",
        "category": "Deprecated Tables",
        "description": (
            "MCHB (batch stock) is a compatibility view. Batch stock derived from "
            "MATDOC aggregation."
        ),
        "severity": "RED",
        "affected_tables": ['MCHB', 'MATDOC'],
        "affected_transactions": ['MB52', 'MSC3N'],
        "remediation": "Replace MCHB reads with MATDOC or I_MATERIALSTOCKBYBATCH.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_066": {
        "title": "MCHBH Batch Stock History Eliminated",
        "category": "Deprecated Tables",
        "description": (
            "MCHBH (batch stock history) is eliminated. Historical batch stock from "
            "MATDOC."
        ),
        "severity": "RED",
        "affected_tables": ['MCHBH', 'MATDOC'],
        "affected_transactions": ['MB5B'],
        "remediation": "Replace MCHBH reads with MATDOC historical aggregation for batch.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_067": {
        "title": "MSLB Subcontractor Special Stock → MATDOC View",
        "category": "Deprecated Tables",
        "description": (
            "MSLB (subcontractor stock) is a compatibility view on MATDOC. Special "
            "stock management unified."
        ),
        "severity": "RED",
        "affected_tables": ['MSLB', 'MATDOC'],
        "affected_transactions": ['ME2O', 'MB54'],
        "remediation": "Replace MSLB reads with MATDOC WHERE SOBKZ = O.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_068": {
        "title": "MSKU Customer Consignment Stock → MATDOC View",
        "category": "Deprecated Tables",
        "description": (
            "MSKU (customer consignment stock) is a compatibility view on MATDOC."
        ),
        "severity": "RED",
        "affected_tables": ['MSKU', 'MATDOC'],
        "affected_transactions": ['MB54'],
        "remediation": "Replace MSKU reads with MATDOC WHERE SOBKZ = W.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_069": {
        "title": "MSSA Sales Order Stock → MATDOC View",
        "category": "Deprecated Tables",
        "description": (
            "MSSA (sales order stock) is a compatibility view on MATDOC. "
            "Project/sales order stock from MATDOC aggregation."
        ),
        "severity": "RED",
        "affected_tables": ['MSSA', 'MATDOC'],
        "affected_transactions": ['MB54', 'MMBE'],
        "remediation": "Replace MSSA reads with MATDOC WHERE SOBKZ = E.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_070": {
        "title": "MSSE Project Stock → MATDOC View",
        "category": "Deprecated Tables",
        "description": (
            "MSSE (project stock) is a compatibility view on MATDOC."
        ),
        "severity": "YELLOW",
        "affected_tables": ['MSSE', 'MATDOC'],
        "affected_transactions": ['MB54'],
        "remediation": "Replace MSSE reads with MATDOC WHERE SOBKZ = Q.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_071": {
        "title": "MSSL Vendor Special Stock → MATDOC View",
        "category": "Deprecated Tables",
        "description": (
            "MSSL (vendor special stock) is a compatibility view on MATDOC."
        ),
        "severity": "YELLOW",
        "affected_tables": ['MSSL', 'MATDOC'],
        "affected_transactions": ['MB54'],
        "remediation": "Replace MSSL reads with MATDOC with appropriate SOBKZ filter.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_072": {
        "title": "MBEW Material Valuation Adapted",
        "category": "Deprecated Tables",
        "description": (
            "MBEW (material valuation) simplified. Standard price / moving average "
            "fields consolidated. Several fields deprecated due to mandatory material "
            "ledger."
        ),
        "severity": "YELLOW",
        "affected_tables": ['MBEW', 'CKMLHD'],
        "affected_transactions": ['CKM3N'],
        "remediation": "Review custom MBEW field usage. Adapt for deprecated valuation fields.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_073": {
        "title": "MBEWH Material Valuation History Eliminated",
        "category": "Deprecated Tables",
        "description": (
            "MBEWH (material valuation history) is eliminated. Historical valuation "
            "derived from MATDOC/ACDOCA."
        ),
        "severity": "RED",
        "affected_tables": ['MBEWH', 'MATDOC'],
        "affected_transactions": ['CKM3N'],
        "remediation": "Replace MBEWH reads with MATDOC-based historical valuation.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_074": {
        "title": "S001 Purchasing Statistics LIS Removed",
        "category": "Deprecated Tables",
        "description": (
            "S001 (LIS purchasing statistics) is eliminated. LIS replaced by embedded "
            "analytics on MATDOC/ACDOCA."
        ),
        "severity": "RED",
        "affected_tables": ['S001'],
        "affected_transactions": ['MCBA', 'MC.1'],
        "remediation": "Replace LIS purchasing reports with CDS-based analytical queries.",
        "effort_hours": 16,
        "responsible_team": "Functional",
        "sap_note": "2267308",
    },
    "TBL_075": {
        "title": "S002 Vendor Statistics LIS Removed",
        "category": "Deprecated Tables",
        "description": (
            "S002 (LIS vendor statistics) is eliminated with LIS removal."
        ),
        "severity": "RED",
        "affected_tables": ['S002'],
        "affected_transactions": ['MC.1'],
        "remediation": "Replace vendor statistics reports with CDS views.",
        "effort_hours": 12,
        "responsible_team": "Functional",
        "sap_note": "2267308",
    },
    "TBL_076": {
        "title": "S003 Material Group Statistics LIS Removed",
        "category": "Deprecated Tables",
        "description": (
            "S003 (LIS material group purchasing statistics) is eliminated."
        ),
        "severity": "RED",
        "affected_tables": ['S003'],
        "affected_transactions": ['MC.1'],
        "remediation": "Replace material group statistics with CDS views.",
        "effort_hours": 12,
        "responsible_team": "Functional",
        "sap_note": "2267308",
    },
    "TBL_077": {
        "title": "S004 Material Statistics LIS Removed",
        "category": "Deprecated Tables",
        "description": (
            "S004 (LIS material statistics purchasing) eliminated."
        ),
        "severity": "RED",
        "affected_tables": ['S004'],
        "affected_transactions": ['MC.1'],
        "remediation": "Replace with CDS views or embedded analytics.",
        "effort_hours": 12,
        "responsible_team": "Functional",
        "sap_note": "2267308",
    },
    "TBL_078": {
        "title": "S005 Vendor/Material Group Statistics LIS Removed",
        "category": "Deprecated Tables",
        "description": (
            "S005 (vendor by material group statistics) eliminated with LIS."
        ),
        "severity": "RED",
        "affected_tables": ['S005'],
        "affected_transactions": ['MC.1'],
        "remediation": "Replace with CDS-based vendor-material analysis.",
        "effort_hours": 8,
        "responsible_team": "Functional",
        "sap_note": "2267308",
    },
    "TBL_079": {
        "title": "S006 Vendor/Material Statistics LIS Removed",
        "category": "Deprecated Tables",
        "description": (
            "S006 (vendor by material statistics) eliminated with LIS."
        ),
        "severity": "RED",
        "affected_tables": ['S006'],
        "affected_transactions": ['MC.1'],
        "remediation": "Replace with CDS-based analysis on EKKO/EKPO.",
        "effort_hours": 8,
        "responsible_team": "Functional",
        "sap_note": "2267308",
    },
    "TBL_080": {
        "title": "S011 Deliveries LIS Removed",
        "category": "Deprecated Tables",
        "description": (
            "S011 (LIS delivery statistics) eliminated. Delivery analytics via CDS on "
            "LIKP/LIPS."
        ),
        "severity": "RED",
        "affected_tables": ['S011'],
        "affected_transactions": ['MC.9'],
        "remediation": "Replace delivery LIS reports with CDS-based analytics.",
        "effort_hours": 12,
        "responsible_team": "Functional",
        "sap_note": "2267308",
    },
    "TBL_081": {
        "title": "S012 Shipping Points LIS Removed",
        "category": "Deprecated Tables",
        "description": (
            "S012 (LIS shipping point statistics) eliminated with LIS removal."
        ),
        "severity": "RED",
        "affected_tables": ['S012'],
        "affected_transactions": ['MC.9'],
        "remediation": "Replace shipping statistics with embedded analytics.",
        "effort_hours": 8,
        "responsible_team": "Functional",
        "sap_note": "2267308",
    },
    "TBL_082": {
        "title": "S013–S018 Sales LIS Structures Removed",
        "category": "Deprecated Tables",
        "description": (
            "S013-S018 (SD LIS sales statistics - customer, material, sales org, "
            "etc.) all eliminated with LIS removal."
        ),
        "severity": "RED",
        "affected_tables": ['S013', 'S014', 'S015', 'S016', 'S017', 'S018'],
        "affected_transactions": ['MC+A', 'MC(C'],
        "remediation": "Replace SD LIS reports with CDS views on VBAK/VBAP/VBRK/VBRP.",
        "effort_hours": 40,
        "responsible_team": "Functional",
        "sap_note": "2267308",
    },
    "TBL_083": {
        "title": "S025–S028 Inventory LIS Structures Removed",
        "category": "Deprecated Tables",
        "description": (
            "S025-S028 (inventory controlling LIS structures) eliminated. Inventory "
            "analytics via MATDOC CDS views."
        ),
        "severity": "RED",
        "affected_tables": ['S025', 'S026', 'S027', 'S028'],
        "affected_transactions": ['MC44', 'MC46'],
        "remediation": "Replace inventory LIS with MATDOC-based CDS analytics.",
        "effort_hours": 24,
        "responsible_team": "Functional",
        "sap_note": "2267308",
    },
    "TBL_084": {
        "title": "S031–S039 Shop Floor LIS Structures Removed",
        "category": "Deprecated Tables",
        "description": (
            "S031-S039 (shop floor control LIS structures) eliminated. Production "
            "analytics via CDS views."
        ),
        "severity": "RED",
        "affected_tables": ['S031', 'S032', 'S033', 'S039'],
        "affected_transactions": ['MCRE'],
        "remediation": "Replace shop floor LIS with CDS-based production analytics.",
        "effort_hours": 24,
        "responsible_team": "Functional",
        "sap_note": "2267308",
    },
    "TBL_085": {
        "title": "RESB Reservations Adapted for MATDOC",
        "category": "Deprecated Tables",
        "description": (
            "RESB (reservation items) goods movement tracking now via MATDOC. "
            "Reservation-to-goods-movement link adapted."
        ),
        "severity": "YELLOW",
        "affected_tables": ['RESB', 'MATDOC'],
        "affected_transactions": ['MB21', 'MB22', 'MIGO'],
        "remediation": "Adapt reservation tracking logic for MATDOC-based goods movements.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_086": {
        "title": "ISEG Physical Inventory Items Adapted",
        "category": "Deprecated Tables",
        "description": (
            "ISEG (physical inventory document items) adapted for MATDOC integration. "
            "Difference posting creates MATDOC entries."
        ),
        "severity": "YELLOW",
        "affected_tables": ['ISEG', 'IKPF', 'MATDOC'],
        "affected_transactions": ['MI01', 'MI04', 'MI07'],
        "remediation": "Test physical inventory with MATDOC integration. Adapt custom PI reports.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_087": {
        "title": "IKPF Physical Inventory Header Adapted",
        "category": "Deprecated Tables",
        "description": (
            "IKPF (physical inventory document header) adapted for S/4HANA. Linked to "
            "MATDOC for posting."
        ),
        "severity": "YELLOW",
        "affected_tables": ['IKPF', 'MATDOC'],
        "affected_transactions": ['MI01', 'MI04'],
        "remediation": "Review custom IKPF read logic. Adapt for MATDOC posting.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_088": {
        "title": "LQUA WM Quant Table Compatibility Mode",
        "category": "Deprecated Tables",
        "description": (
            "LQUA (WM quant table) in compatibility mode if not migrating to EWM. "
            "Embedded EWM uses /SCWM/ tables."
        ),
        "severity": "RED",
        "affected_tables": ['LQUA', '/SCWM/AQUA'],
        "affected_transactions": ['LS26', '/SCWM/MON'],
        "remediation": "Migrate WM-managed warehouses to EWM. Adapt LQUA-based reports.",
        "effort_hours": 40,
        "responsible_team": "Functional",
        "sap_note": "2326578",
    },
    "TBL_089": {
        "title": "LAGP WM Storage Bin Master Compatibility Mode",
        "category": "Deprecated Tables",
        "description": (
            "LAGP (WM storage bins) in compatibility mode. Replaced by /SCWM/LAGP in "
            "EWM."
        ),
        "severity": "RED",
        "affected_tables": ['LAGP', '/SCWM/LAGP'],
        "affected_transactions": ['LS01N', '/SCWM/LS01'],
        "remediation": "Migrate storage bin master data to EWM.",
        "effort_hours": 16,
        "responsible_team": "Functional",
        "sap_note": "2326578",
    },
    "TBL_090": {
        "title": "MCH1 Batch Master Plant Level Adapted",
        "category": "Deprecated Tables",
        "description": (
            "MCH1 (batch master at plant level) adapted. Batch management can be at "
            "plant or material level."
        ),
        "severity": "YELLOW",
        "affected_tables": ['MCH1', 'MCHA'],
        "affected_transactions": ['MSC1N', 'MSC2N'],
        "remediation": "Review batch master configuration and custom MCH1 reads.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_091": {
        "title": "MCHA Batch Classification Data Adapted",
        "category": "Deprecated Tables",
        "description": (
            "MCHA (batch assignment to class) adapted for S/4HANA batch management."
        ),
        "severity": "YELLOW",
        "affected_tables": ['MCHA', 'MCH1'],
        "affected_transactions": ['MSC2N'],
        "remediation": "Review custom batch classification logic.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_092": {
        "title": "MVER Material Consumption Data Adapted",
        "category": "Deprecated Tables",
        "description": (
            "MVER (material consumption) simplified. Forecast consumption data "
            "derived from MATDOC-based aggregation."
        ),
        "severity": "YELLOW",
        "affected_tables": ['MVER', 'MATDOC'],
        "affected_transactions": ['MD04'],
        "remediation": "Review custom MVER usage and adapt for MATDOC-based consumption tracking.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_093": {
        "title": "MARC Plant-Level Material Master Fields Changed",
        "category": "Deprecated Tables",
        "description": (
            "Several MARC fields deprecated (VPRSV, MLAST, LPLPR). Valuation changes "
            "align with single valuation approach and mandatory material ledger."
        ),
        "severity": "YELLOW",
        "affected_tables": ['MARC'],
        "affected_transactions": ['MM01', 'MM02', 'MM03'],
        "remediation": "Review custom MARC field usage. Adapt for deprecated fields.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_094": {
        "title": "MVKE Sales Org Material Master Fields Changed",
        "category": "Deprecated Tables",
        "description": (
            "MVKE (sales data for material) fields changed for S/4HANA. Pricing "
            "reference and distribution chain fields adapted."
        ),
        "severity": "YELLOW",
        "affected_tables": ['MVKE'],
        "affected_transactions": ['MM01', 'VD51'],
        "remediation": "Review custom MVKE field usage and adapt.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_095": {
        "title": "OBSL WM Storage Bins Compatibility Mode",
        "category": "Deprecated Tables",
        "description": (
            "OBSL and other WM customizing tables in compatibility mode. EWM storage "
            "type/section model replaces WM bins."
        ),
        "severity": "YELLOW",
        "affected_tables": ['OBSL'],
        "affected_transactions": ['LS01N'],
        "remediation": "Plan EWM migration to replace WM bin model.",
        "effort_hours": 8,
        "responsible_team": "Functional",
        "sap_note": "2326578",
    },
    "TBL_096": {
        "title": "MARA Material Master Header Structure Changed",
        "category": "Deprecated Tables",
        "description": (
            "MARA (material master) receives new fields and has industry-specific "
            "fields deprecated in S/4HANA."
        ),
        "severity": "YELLOW",
        "affected_tables": ['MARA', 'MAKT'],
        "affected_transactions": ['MM01', 'MM02', 'MM03'],
        "remediation": "Review custom MARA field usage. Use CDS view I_PRODUCT for reads.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_097": {
        "title": "EKKO Purchase Order Header Field Changes",
        "category": "Deprecated Tables",
        "description": (
            "EKKO (purchase order header) receives new fields. Several legacy fields "
            "deprecated for S/4HANA procurement."
        ),
        "severity": "YELLOW",
        "affected_tables": ['EKKO', 'EKPO'],
        "affected_transactions": ['ME21N', 'ME22N', 'ME23N'],
        "remediation": "Review custom EKKO/EKPO field usage. Adapt for new/deprecated fields.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_098": {
        "title": "EBAN Purchase Requisition Adapted",
        "category": "Deprecated Tables",
        "description": (
            "EBAN (purchase requisition item) structure adapted with new fields for "
            "S/4HANA."
        ),
        "severity": "YELLOW",
        "affected_tables": ['EBAN'],
        "affected_transactions": ['ME51N', 'ME52N'],
        "remediation": "Review custom EBAN field usage and adapt.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_099": {
        "title": "RBKP Invoice Document Header MATDOC Integration",
        "category": "Deprecated Tables",
        "description": (
            "RBKP (invoice receipt header) GR/IR integration adapted for MATDOC-based "
            "goods movements."
        ),
        "severity": "YELLOW",
        "affected_tables": ['RBKP', 'RSEG', 'MATDOC'],
        "affected_transactions": ['MIRO', 'MIR7'],
        "remediation": "Adapt invoice verification customization for MATDOC integration.",
        "effort_hours": 12,
        "responsible_team": "Functional",
        "sap_note": "2267308",
    },
    "TBL_100": {
        "title": "RSEG Invoice Document Items MATDOC Integration",
        "category": "Deprecated Tables",
        "description": (
            "RSEG (invoice receipt item) adapted for MATDOC-based GR reference. "
            "History fields updated."
        ),
        "severity": "YELLOW",
        "affected_tables": ['RSEG', 'MATDOC'],
        "affected_transactions": ['MIRO'],
        "remediation": "Review custom RSEG logic for MATDOC-based GR reference.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_101": {
        "title": "AFKO Production Order Header MATDOC Integration",
        "category": "Deprecated Tables",
        "description": (
            "AFKO (production order header) goods movement integration changed to "
            "MATDOC-based confirmations."
        ),
        "severity": "YELLOW",
        "affected_tables": ['AFKO', 'AFPO', 'MATDOC'],
        "affected_transactions": ['CO01', 'CO02', 'CO11N'],
        "remediation": "Adapt production order confirmation logic for MATDOC integration.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_102": {
        "title": "PLKO Routing Header Structure Changed",
        "category": "Deprecated Tables",
        "description": (
            "PLKO (task list/routing header) and PLPO (operations) receive new fields "
            "for S/4HANA production engineering."
        ),
        "severity": "GREEN",
        "affected_tables": ['PLKO', 'PLPO'],
        "affected_transactions": ['CA01', 'CA02'],
        "remediation": "Review custom routing/operation field usage.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_103": {
        "title": "LTAP Transfer Order Items WM Compatibility",
        "category": "Deprecated Tables",
        "description": (
            "LTAP (transfer order items) in WM compatibility mode. Replaced by EWM "
            "warehouse tasks (/SCWM/ORDIM_O)."
        ),
        "severity": "RED",
        "affected_tables": ['LTAP', 'LTAK', '/SCWM/ORDIM_O'],
        "affected_transactions": ['LT01', '/SCWM/MON'],
        "remediation": "Migrate transfer order logic to EWM warehouse tasks.",
        "effort_hours": 40,
        "responsible_team": "Functional",
        "sap_note": "2326578",
    },
    "TBL_104": {
        "title": "LTAK Transfer Order Header WM Compatibility",
        "category": "Deprecated Tables",
        "description": (
            "LTAK (transfer order header) in WM compatibility mode. Replaced by EWM "
            "warehouse orders."
        ),
        "severity": "RED",
        "affected_tables": ['LTAK'],
        "affected_transactions": ['LT01'],
        "remediation": "Migrate transfer order processes to EWM warehouse orders.",
        "effort_hours": 24,
        "responsible_team": "Functional",
        "sap_note": "2326578",
    },
    "TBL_105": {
        "title": "LIPS Delivery Item Pricing via PRCD_ELEMENTS",
        "category": "Deprecated Tables",
        "description": (
            "LIPS delivery item pricing conditions now reference PRCD_ELEMENTS "
            "instead of KONV."
        ),
        "severity": "YELLOW",
        "affected_tables": ['LIPS', 'PRCD_ELEMENTS'],
        "affected_transactions": ['VL01N', 'VL02N'],
        "remediation": "Adapt delivery pricing reads from KONV to PRCD_ELEMENTS.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_106": {
        "title": "LIKP Delivery Header EWM Integration Changed",
        "category": "Deprecated Tables",
        "description": (
            "LIKP (delivery header) integration with EWM warehouse request replaces "
            "WM transfer order link."
        ),
        "severity": "YELLOW",
        "affected_tables": ['LIKP', 'LIPS'],
        "affected_transactions": ['VL01N', 'VL02N'],
        "remediation": "Adapt delivery-warehouse integration for EWM.",
        "effort_hours": 16,
        "responsible_team": "Functional",
        "sap_note": "2326578",
    },
    "TBL_107": {
        "title": "STXH SAPscript Text Storage Performance",
        "category": "Deprecated Tables",
        "description": (
            "STXH/STXL (SAPscript text header/lines) remain but are "
            "performance-critical. Text storage should be reviewed."
        ),
        "severity": "GREEN",
        "affected_tables": ['STXH', 'STXL'],
        "affected_transactions": ['SE75'],
        "remediation": "Review text volume and archiving strategy.",
        "effort_hours": 4,
        "responsible_team": "Basis",
        "sap_note": "2296888",
    },
    "TBL_108": {
        "title": "JEST Status Management Performance Impact",
        "category": "Deprecated Tables",
        "description": (
            "JEST/JSTO (object status tables) remain but performance-critical due to "
            "increased object volume in S/4HANA."
        ),
        "severity": "GREEN",
        "affected_tables": ['JEST', 'JSTO'],
        "affected_transactions": [],
        "remediation": "Review status management performance. Consider archiving old statuses.",
        "effort_hours": 4,
        "responsible_team": "Basis",
        "sap_note": "2296888",
    },
    "TBL_109": {
        "title": "VBAK Sales Order Header Pricing Changed",
        "category": "Deprecated Tables",
        "description": (
            "VBAK/VBAP sales order pricing references PRCD_ELEMENTS. Custom pricing "
            "reads must adapt from KONV."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBAK', 'VBAP', 'PRCD_ELEMENTS'],
        "affected_transactions": ['VA01', 'VA02'],
        "remediation": "Adapt sales document pricing reads for PRCD_ELEMENTS.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_110": {
        "title": "VBRK Billing Document Pricing Changed",
        "category": "Deprecated Tables",
        "description": (
            "VBRK/VBRP billing document conditions now in PRCD_ELEMENTS. Custom "
            "billing reports must adapt."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBRK', 'VBRP', 'PRCD_ELEMENTS'],
        "affected_transactions": ['VF01', 'VF02', 'VF03'],
        "remediation": "Adapt billing document pricing reads from KONV to PRCD_ELEMENTS.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_111": {
        "title": "KONV Sales Pricing Conditions → PRCD_ELEMENTS",
        "category": "Deprecated Tables",
        "description": (
            "KONV (document pricing conditions) is replaced by PRCD_ELEMENTS. All "
            "pricing condition reads and writes must target PRCD_ELEMENTS."
        ),
        "severity": "RED",
        "affected_tables": ['KONV', 'PRCD_ELEMENTS'],
        "affected_transactions": ['VA01', 'VA02', 'VF01'],
        "remediation": "Replace all KONV reads/writes with PRCD_ELEMENTS. Adapt pricing exits and user routines.",
        "effort_hours": 40,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_112": {
        "title": "KONM Quantity Scale Conditions → PRCD Model",
        "category": "Deprecated Tables",
        "description": (
            "KONM (quantity-based pricing scales) moved to PRCD_ELEMENTS-based "
            "pricing model."
        ),
        "severity": "YELLOW",
        "affected_tables": ['KONM', 'PRCD_ELEMENTS'],
        "affected_transactions": ['VK11', 'VK12'],
        "remediation": "Adapt pricing scale logic for PRCD_ELEMENTS-based scale tables.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_113": {
        "title": "KONW Value Scale Conditions → PRCD Model",
        "category": "Deprecated Tables",
        "description": (
            "KONW (value-based pricing scales) moved to PRCD_ELEMENTS-based pricing "
            "model."
        ),
        "severity": "YELLOW",
        "affected_tables": ['KONW', 'PRCD_ELEMENTS'],
        "affected_transactions": ['VK11', 'VK12'],
        "remediation": "Adapt value scale logic for PRCD_ELEMENTS-based scale tables.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_114": {
        "title": "KONH Condition Header Adapted",
        "category": "Deprecated Tables",
        "description": (
            "KONH (condition header) adapted for PRCD_ELEMENTS integration. Condition "
            "record management still via KONH but document conditions use "
            "PRCD_ELEMENTS."
        ),
        "severity": "YELLOW",
        "affected_tables": ['KONH', 'KONP', 'PRCD_ELEMENTS'],
        "affected_transactions": ['VK11', 'VK12', 'VK13'],
        "remediation": "Review custom condition record logic for S/4HANA pricing changes.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_115": {
        "title": "KONP Condition Item Adapted",
        "category": "Deprecated Tables",
        "description": (
            "KONP (condition item/record) adapted. Condition maintenance still uses "
            "KONP but runtime pricing uses PRCD_ELEMENTS."
        ),
        "severity": "YELLOW",
        "affected_tables": ['KONP', 'PRCD_ELEMENTS'],
        "affected_transactions": ['VK11', 'VK12'],
        "remediation": "Adapt condition item access. Runtime pricing references PRCD_ELEMENTS.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_116": {
        "title": "VBOX SD Rebate Index Removed",
        "category": "Deprecated Tables",
        "description": (
            "VBOX (rebate agreement index) is eliminated as part of SD "
            "simplification. Settlement Management or condition contract replaces "
            "rebates."
        ),
        "severity": "RED",
        "affected_tables": ['VBOX', 'VBOH'],
        "affected_transactions": ['VBO1', 'VBO2', 'VBO3'],
        "remediation": "Migrate to Settlement Management (CLM-SLM). Remove VBOX-based custom code.",
        "effort_hours": 40,
        "responsible_team": "Functional",
        "sap_note": "2296888",
    },
    "TBL_117": {
        "title": "VBOH Rebate Agreement Header Removed",
        "category": "Deprecated Tables",
        "description": (
            "VBOH (rebate agreement header) eliminated with rebate simplification in "
            "S/4HANA."
        ),
        "severity": "RED",
        "affected_tables": ['VBOH'],
        "affected_transactions": ['VBO1', 'VBO2'],
        "remediation": "Migrate rebate agreements to Settlement Management.",
        "effort_hours": 24,
        "responsible_team": "Functional",
        "sap_note": "2296888",
    },
    "TBL_118": {
        "title": "VBREVK Revenue Recognition Header Removed",
        "category": "Deprecated Tables",
        "description": (
            "VBREVK (revenue recognition header) eliminated. Revenue recognition "
            "replaced by Event-Based Revenue Recognition or Revenue Accounting (RAR)."
        ),
        "severity": "RED",
        "affected_tables": ['VBREVK'],
        "affected_transactions": ['VF44'],
        "remediation": "Migrate to Event-Based Revenue Recognition (EA-FIN) or RAR.",
        "effort_hours": 60,
        "responsible_team": "Functional",
        "sap_note": "2296888",
    },
    "TBL_119": {
        "title": "VBKA Sales Activity Header Adapted",
        "category": "Deprecated Tables",
        "description": (
            "VBKA (sales activities) eliminated. Sales activities migrated to CRM or "
            "S/4HANA Service."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBKA'],
        "affected_transactions": ['VC01N', 'VC02N'],
        "remediation": "Use Fiori-based activity management or CRM integration.",
        "effort_hours": 12,
        "responsible_team": "Functional",
        "sap_note": "2296888",
    },
    "TBL_120": {
        "title": "VAKPA Sales Partner Index Adapted",
        "category": "Deprecated Tables",
        "description": (
            "VAKPA (SD partner index) simplified. Partner determination uses Business "
            "Partner model."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VAKPA'],
        "affected_transactions": ['VA01'],
        "remediation": "Review custom VAKPA usage. Adapt to BP-based partner determination.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "TBL_121": {
        "title": "KNVH Customer Hierarchy Adapted for BP",
        "category": "Deprecated Tables",
        "description": (
            "KNVH (customer hierarchy) structure adapted for Business Partner. "
            "Hierarchy uses BP relationship categories."
        ),
        "severity": "YELLOW",
        "affected_tables": ['KNVH', 'BUT000', 'BUT050'],
        "affected_transactions": ['VDH1N', 'VDH2N'],
        "remediation": "Adapt customer hierarchy logic for BP-based relationships.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "TBL_122": {
        "title": "VBBE Sales Requirements Availability Adapted",
        "category": "Deprecated Tables",
        "description": (
            "VBBE (sales requirements individual records) adapted. Availability check "
            "uses aATP for advanced scenarios."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBBE'],
        "affected_transactions": ['VA01', 'CO09'],
        "remediation": "Review custom availability check logic. Consider aATP enablement.",
        "effort_hours": 12,
        "responsible_team": "Functional",
        "sap_note": "2267098",
    },
    "TBL_123": {
        "title": "VBBS Sales Requirements Totals Adapted",
        "category": "Deprecated Tables",
        "description": (
            "VBBS (sales requirements totals) adapted alongside VBBE for aATP "
            "integration."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBBS'],
        "affected_transactions": ['CO09'],
        "remediation": "Adapt sales requirements reporting for aATP changes.",
        "effort_hours": 8,
        "responsible_team": "Functional",
        "sap_note": "2267098",
    },
    "TBL_124": {
        "title": "FPLA Billing Plan Header Adapted",
        "category": "Deprecated Tables",
        "description": (
            "FPLA (billing plan header) adapted for S/4HANA billing plan processing "
            "with PRCD_ELEMENTS integration."
        ),
        "severity": "YELLOW",
        "affected_tables": ['FPLA', 'FPLNR'],
        "affected_transactions": ['VF01'],
        "remediation": "Review custom billing plan logic. Adapt for PRCD_ELEMENTS.",
        "effort_hours": 12,
        "responsible_team": "Functional",
        "sap_note": "2296888",
    },
    "TBL_125": {
        "title": "NAST Output Status Replaced by BRF+",
        "category": "Deprecated Tables",
        "description": (
            "NAST (message status) is replaced by new Output Management Framework "
            "based on BRFplus and Adobe Forms for strategic direction."
        ),
        "severity": "YELLOW",
        "affected_tables": ['NAST', 'TNAPR'],
        "affected_transactions": ['NACE', 'VV31', 'MN21'],
        "remediation": "Plan migration from classic output determination (NAST/NACE) to BRFplus-based output management.",
        "effort_hours": 40,
        "responsible_team": "Functional",
        "sap_note": "2296888",
    },
    "TBL_126": {
        "title": "TNAPR Output Determination Replaced by BRF+",
        "category": "Deprecated Tables",
        "description": (
            "TNAPR (processing routines for output) replaced by BRFplus output "
            "framework. Classic programs/forms still run in compatibility."
        ),
        "severity": "YELLOW",
        "affected_tables": ['TNAPR', 'NAST'],
        "affected_transactions": ['NACE'],
        "remediation": "Migrate output processing routines to BRFplus-based framework.",
        "effort_hours": 24,
        "responsible_team": "Functional",
        "sap_note": "2296888",
    },
    "TBL_127": {
        "title": "PRCD_ELEMENTS New Pricing Table",
        "category": "Deprecated Tables",
        "description": (
            "PRCD_ELEMENTS is the new central document pricing table replacing KONV. "
            "Custom pricing code must target this table."
        ),
        "severity": "GREEN",
        "affected_tables": ['PRCD_ELEMENTS'],
        "affected_transactions": ['VA01', 'VF01'],
        "remediation": "All new pricing customizations should use PRCD_ELEMENTS.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_128": {
        "title": "PRCD_COND_SUPPL Condition Supplement Table",
        "category": "Deprecated Tables",
        "description": (
            "PRCD_COND_SUPPL added as supplement to PRCD_ELEMENTS. Custom pricing "
            "exits must be aware of two-table pricing model."
        ),
        "severity": "GREEN",
        "affected_tables": ['PRCD_COND_SUPPL', 'PRCD_ELEMENTS'],
        "affected_transactions": ['VA01', 'VF01'],
        "remediation": "Adapt pricing exits and custom pricing code for PRCD_COND_SUPPL.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_129": {
        "title": "VBEP Schedule Line Data Adapted",
        "category": "Deprecated Tables",
        "description": (
            "VBEP (sales document schedule lines) adapted for aATP and MATDOC-based "
            "delivery confirmation."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBEP'],
        "affected_transactions": ['VA01', 'VA02'],
        "remediation": "Review custom schedule line logic for aATP/MATDOC.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267098",
    },
    "TBL_130": {
        "title": "VBPA Sales Document Partners Adapted for BP",
        "category": "Deprecated Tables",
        "description": (
            "VBPA (sales document partner) adapted for BP model. Partner "
            "determination uses BP relationships."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBPA', 'BUT050'],
        "affected_transactions": ['VA01'],
        "remediation": "Adapt partner determination for BP-based partner model.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "TBL_131": {
        "title": "VBKD Sales Document Business Data Adapted",
        "category": "Deprecated Tables",
        "description": (
            "VBKD (sales document business data) adapted, payment terms and incoterms "
            "fields updated for S/4HANA."
        ),
        "severity": "GREEN",
        "affected_tables": ['VBKD'],
        "affected_transactions": ['VA01', 'VA02'],
        "remediation": "Review custom VBKD field access.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "TBL_132": {
        "title": "TVAK Sales Document Type Customizing Adapted",
        "category": "Deprecated Tables",
        "description": (
            "TVAK (sales document types) adapted for S/4HANA. Rebate-related document "
            "types removed."
        ),
        "severity": "YELLOW",
        "affected_tables": ['TVAK'],
        "affected_transactions": ['VOV8'],
        "remediation": "Review sales document type configuration. Remove rebate types.",
        "effort_hours": 8,
        "responsible_team": "Functional",
        "sap_note": "2296888",
    },
    "TBL_133": {
        "title": "VBUK Sales Document Status Header Adapted",
        "category": "Deprecated Tables",
        "description": (
            "VBUK (sales document status header) adapted. Some status fields "
            "deprecated or consolidated."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBUK'],
        "affected_transactions": ['VA02', 'VA03'],
        "remediation": "Review custom VBUK status field usage.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "TBL_134": {
        "title": "VBUP Sales Document Status Item Adapted",
        "category": "Deprecated Tables",
        "description": (
            "VBUP (sales document status item) adapted. Overall status logic changed."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBUP'],
        "affected_transactions": ['VA02', 'VA03'],
        "remediation": "Review custom VBUP status field usage.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "TBL_135": {
        "title": "A-Condition Tables Pricing Master Data Adapted",
        "category": "Deprecated Tables",
        "description": (
            "A-tables (Axxx condition tables, e.g., A004, A305) remain but are "
            "complemented by PRCD-based runtime pricing."
        ),
        "severity": "GREEN",
        "affected_tables": ['A004', 'A305', 'A306'],
        "affected_transactions": ['VK11', 'VK12'],
        "remediation": "Condition master tables unchanged; runtime pricing uses PRCD_ELEMENTS.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_136": {
        "title": "VBBE_FCOM Forward Consumption Data Adapted",
        "category": "Deprecated Tables",
        "description": (
            "VBBE forward consumption records adapted for aATP (advanced "
            "Available-to-Promise) scenarios."
        ),
        "severity": "YELLOW",
        "affected_tables": ['VBBE'],
        "affected_transactions": ['V_RA'],
        "remediation": "Review forward consumption logic for aATP.",
        "effort_hours": 8,
        "responsible_team": "Functional",
        "sap_note": "2267098",
    },
    "TBL_137": {
        "title": "VBFA Sales Document Flow Adapted",
        "category": "Deprecated Tables",
        "description": (
            "VBFA (sales document flow) adapted for new document types in S/4HANA. "
            "Additional flow categories."
        ),
        "severity": "GREEN",
        "affected_tables": ['VBFA'],
        "affected_transactions": ['VA03'],
        "remediation": "Review custom document flow logic.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "TBL_138": {
        "title": "EDID4 IDoc Data Records Adapted for Sales",
        "category": "Deprecated Tables",
        "description": (
            "EDID4 (IDoc data records) adapted for S/4HANA SD IDocs with "
            "PRCD_ELEMENTS-based pricing segments."
        ),
        "severity": "YELLOW",
        "affected_tables": ['EDID4'],
        "affected_transactions": ['WE02', 'WE05'],
        "remediation": "Review SD IDoc processing for PRCD_ELEMENTS pricing segments.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "TBL_139": {
        "title": "KOMG Pricing Communication Structure Adapted",
        "category": "Deprecated Tables",
        "description": (
            "KOMG (pricing communication structure) adapted for PRCD_ELEMENTS pricing "
            "determination."
        ),
        "severity": "YELLOW",
        "affected_tables": ['KOMG'],
        "affected_transactions": ['VK11'],
        "remediation": "Review custom pricing KOMG field access routines.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_140": {
        "title": "KOMP Pricing Communication Item Adapted",
        "category": "Deprecated Tables",
        "description": (
            "KOMP (pricing communication item data) adapted for PRCD_ELEMENTS-based "
            "pricing calls."
        ),
        "severity": "YELLOW",
        "affected_tables": ['KOMP'],
        "affected_transactions": ['VA01'],
        "remediation": "Review pricing user routines accessing KOMP.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2267308",
    },
    "TBL_141": {
        "title": "KNA1 Customer General Data → BP Compatibility View",
        "category": "Deprecated Tables",
        "description": (
            "KNA1 (customer general data) is a compatibility view on BUT000. Customer "
            "master managed via Business Partner (BP transaction). KNA1 INSERTs fail."
        ),
        "severity": "RED",
        "affected_tables": ['KNA1', 'BUT000', 'BUT020'],
        "affected_transactions": ['XD01', 'XD02', 'BP'],
        "remediation": "Replace KNA1 direct access with BP APIs. Use CVI synchronization.",
        "effort_hours": 40,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "TBL_142": {
        "title": "KNB1 Customer Company Code → BP Compatibility View",
        "category": "Deprecated Tables",
        "description": (
            "KNB1 (customer company code data) becomes a compatibility view. Company "
            "code data managed via BP role FI customer."
        ),
        "severity": "RED",
        "affected_tables": ['KNB1', 'BUT000'],
        "affected_transactions": ['XD01', 'BP'],
        "remediation": "Use BP FI customer role APIs for company code data.",
        "effort_hours": 24,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "TBL_143": {
        "title": "KNVV Customer Sales Area → BP Compatibility View",
        "category": "Deprecated Tables",
        "description": (
            "KNVV (customer sales area data) becomes a compatibility view. Sales area "
            "data via BP role SD customer."
        ),
        "severity": "RED",
        "affected_tables": ['KNVV', 'BUT000'],
        "affected_transactions": ['VD01', 'BP'],
        "remediation": "Use BP SD customer role for sales area data.",
        "effort_hours": 24,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "TBL_144": {
        "title": "KNVP Customer Partner Functions → BP Model",
        "category": "Deprecated Tables",
        "description": (
            "KNVP (customer partner functions) adapted for BP partner relationships."
        ),
        "severity": "YELLOW",
        "affected_tables": ['KNVP', 'BUT050', 'BUT051'],
        "affected_transactions": ['VD01', 'BP'],
        "remediation": "Adapt partner function logic for BP relationship model.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "TBL_145": {
        "title": "KNVK Customer Contact Persons → BP Contact Role",
        "category": "Deprecated Tables",
        "description": (
            "KNVK (customer contact persons) replaced by BP contact person role."
        ),
        "severity": "YELLOW",
        "affected_tables": ['KNVK', 'BUT000', 'BUT050'],
        "affected_transactions": ['XD01', 'BP'],
        "remediation": "Use BP contact person role (BUR010) instead of KNVK.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "TBL_146": {
        "title": "KNVD Customer Document Defaults → BP Model",
        "category": "Deprecated Tables",
        "description": (
            "KNVD (customer default document data) adapted for BP model."
        ),
        "severity": "YELLOW",
        "affected_tables": ['KNVD', 'BUT000'],
        "affected_transactions": ['VD01', 'BP'],
        "remediation": "Adapt billing document defaults for BP SD role.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "TBL_147": {
        "title": "KNVI Customer Tax Classification → BP Tax",
        "category": "Deprecated Tables",
        "description": (
            "KNVI (customer tax classification) adapted for BP tax categorization."
        ),
        "severity": "YELLOW",
        "affected_tables": ['KNVI', 'BUT000', 'DFKKBPTAXNUM'],
        "affected_transactions": ['XD01', 'BP'],
        "remediation": "Adapt tax classification logic for BP tax categorization.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "TBL_148": {
        "title": "LFA1 Vendor General Data → BP Compatibility View",
        "category": "Deprecated Tables",
        "description": (
            "LFA1 (vendor general data) becomes a compatibility view on BUT000. "
            "Vendor master managed via BP with supplier role."
        ),
        "severity": "RED",
        "affected_tables": ['LFA1', 'BUT000', 'BUT020'],
        "affected_transactions": ['XK01', 'XK02', 'BP'],
        "remediation": "Replace LFA1 access with BP supplier role APIs. Use CVI.",
        "effort_hours": 40,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "TBL_149": {
        "title": "LFB1 Vendor Company Code → BP Compatibility View",
        "category": "Deprecated Tables",
        "description": (
            "LFB1 (vendor company code data) becomes a compatibility view."
        ),
        "severity": "RED",
        "affected_tables": ['LFB1', 'BUT000'],
        "affected_transactions": ['XK01', 'BP'],
        "remediation": "Use BP FI supplier role for vendor company code data.",
        "effort_hours": 24,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "TBL_150": {
        "title": "LFB5 Vendor Dunning Data → BP Dunning",
        "category": "Deprecated Tables",
        "description": (
            "LFB5 (vendor dunning data) adapted for BP dunning procedures."
        ),
        "severity": "YELLOW",
        "affected_tables": ['LFB5', 'BUT000'],
        "affected_transactions": ['XK01', 'BP'],
        "remediation": "Adapt dunning procedure configuration for BP supplier role.",
        "effort_hours": 8,
        "responsible_team": "Functional",
        "sap_note": "2331060",
    },
    "TBL_151": {
        "title": "LFM1 Vendor Purchasing Data → BP Purchasing Role",
        "category": "Deprecated Tables",
        "description": (
            "LFM1 (vendor purchasing organization data) becomes a compatibility view "
            "on BP."
        ),
        "severity": "RED",
        "affected_tables": ['LFM1', 'BUT000'],
        "affected_transactions": ['MK01', 'MK02', 'BP'],
        "remediation": "Use BP purchasing role for vendor purchasing organization data.",
        "effort_hours": 24,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "TBL_152": {
        "title": "LFM2 Vendor Purchasing Plant Data → BP Model",
        "category": "Deprecated Tables",
        "description": (
            "LFM2 (vendor plant-level purchasing data) adapted for BP model."
        ),
        "severity": "YELLOW",
        "affected_tables": ['LFM2', 'BUT000'],
        "affected_transactions": ['MK01', 'BP'],
        "remediation": "Use BP purchasing role for plant-level vendor data.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "TBL_153": {
        "title": "BNKA Bank Master Integrated with BP",
        "category": "Deprecated Tables",
        "description": (
            "BNKA (bank master) integrated with Business Partner. Bank data shares BP "
            "address model."
        ),
        "severity": "YELLOW",
        "affected_tables": ['BNKA', 'BUT000'],
        "affected_transactions": ['FI01', 'FI02'],
        "remediation": "Review bank master integration with BP address model.",
        "effort_hours": 8,
        "responsible_team": "Functional",
        "sap_note": "2331060",
    },
    "TBL_154": {
        "title": "ADRC Address Management Shared with BP",
        "category": "Deprecated Tables",
        "description": (
            "ADRC (address management central) is the shared address model for BP, "
            "customer, and vendor. Deduplication essential."
        ),
        "severity": "YELLOW",
        "affected_tables": ['ADRC', 'BUT020'],
        "affected_transactions": ['BP'],
        "remediation": "Ensure ADRC is consistent across BP, customer, vendor records.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "TBL_155": {
        "title": "BUT000 BP Master: New CVI Fields",
        "category": "Deprecated Tables",
        "description": (
            "BUT000 (Business Partner master) receives new fields for CVI. Custom "
            "code must account for CVI direction settings."
        ),
        "severity": "YELLOW",
        "affected_tables": ['BUT000', 'BUT020', 'BUT050'],
        "affected_transactions": ['BP'],
        "remediation": "Review BUT000 custom field usage. Ensure CVI synchronization direction is set.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "TBL_156": {
        "title": "BUT020 BP Address Data Primary Table",
        "category": "Deprecated Tables",
        "description": (
            "BUT020 (BP address data) is the primary address table. Customer/vendor "
            "ADRNR references point to BUT020/ADRC."
        ),
        "severity": "GREEN",
        "affected_tables": ['BUT020', 'ADRC'],
        "affected_transactions": ['BP'],
        "remediation": "Understand BP address model for custom address logic.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "TBL_157": {
        "title": "BUT050 BP Relationships Primary Table",
        "category": "Deprecated Tables",
        "description": (
            "BUT050 (BP relationships) stores partner function mappings for customer "
            "(KNVP) and contact persons (KNVK)."
        ),
        "severity": "GREEN",
        "affected_tables": ['BUT050', 'BUT051'],
        "affected_transactions": ['BP'],
        "remediation": "Use BUT050 for partner/contact relationship handling.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "TBL_158": {
        "title": "BUT051 BP Relationship Texts",
        "category": "Deprecated Tables",
        "description": (
            "BUT051 (BP relationship texts) stores relationship descriptions for "
            "partner functions."
        ),
        "severity": "GREEN",
        "affected_tables": ['BUT051'],
        "affected_transactions": ['BP'],
        "remediation": "Review relationship text handling for partner determination.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "TBL_159": {
        "title": "BUT100 BP Roles Assignment",
        "category": "Deprecated Tables",
        "description": (
            "BUT100 (BP roles) is the primary role assignment table. Customer/vendor "
            "roles (FLCU00, FLVN00) assigned here."
        ),
        "severity": "GREEN",
        "affected_tables": ['BUT100', 'BUT000'],
        "affected_transactions": ['BP'],
        "remediation": "Verify BP role assignments for customer and vendor roles.",
        "effort_hours": 8,
        "responsible_team": "Functional",
        "sap_note": "2331060",
    },
    "TBL_160": {
        "title": "KNVH Customer Hierarchy Adapted for BP Relationships",
        "category": "Deprecated Tables",
        "description": (
            "KNVH (customer hierarchy) adapted. Customer hierarchy nodes use BP "
            "relationship categories for hierarchy processing."
        ),
        "severity": "YELLOW",
        "affected_tables": ['KNVH', 'BUT050'],
        "affected_transactions": ['VDH1N', 'VDH2N'],
        "remediation": "Migrate customer hierarchy logic to BP relationship model.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "TBL_161": {
        "title": "CVIS_MAPPING CVI Synchronization Mapping",
        "category": "Deprecated Tables",
        "description": (
            "CVIS_MAPPING stores Customer/Vendor to BP mapping. Essential for CVI "
            "synchronization and data consistency."
        ),
        "severity": "GREEN",
        "affected_tables": ['CVIS_MAPPING', 'CVI_CUST_LINK', 'CVI_VEND_LINK'],
        "affected_transactions": ['BP'],
        "remediation": "Verify CVI mapping tables are populated and consistent.",
        "effort_hours": 8,
        "responsible_team": "Functional",
        "sap_note": "2331060",
    },
    "TBL_162": {
        "title": "CVI_CUST_LINK Customer-BP Link Table",
        "category": "Deprecated Tables",
        "description": (
            "CVI_CUST_LINK stores customer number to BP number mapping for CVI "
            "synchronization."
        ),
        "severity": "GREEN",
        "affected_tables": ['CVI_CUST_LINK'],
        "affected_transactions": ['BP'],
        "remediation": "Ensure all customers have corresponding BP entries via CVI.",
        "effort_hours": 8,
        "responsible_team": "Functional",
        "sap_note": "2331060",
    },
    "TBL_163": {
        "title": "CVI_VEND_LINK Vendor-BP Link Table",
        "category": "Deprecated Tables",
        "description": (
            "CVI_VEND_LINK stores vendor number to BP number mapping for CVI "
            "synchronization."
        ),
        "severity": "GREEN",
        "affected_tables": ['CVI_VEND_LINK'],
        "affected_transactions": ['BP'],
        "remediation": "Ensure all vendors have corresponding BP entries via CVI.",
        "effort_hours": 8,
        "responsible_team": "Functional",
        "sap_note": "2331060",
    },
    "TBL_164": {
        "title": "KNBK Customer Bank Details → BP Bank Details",
        "category": "Deprecated Tables",
        "description": (
            "KNBK (customer bank details) adapted for BP bank detail model."
        ),
        "severity": "YELLOW",
        "affected_tables": ['KNBK', 'BUT0BK'],
        "affected_transactions": ['XD01', 'BP'],
        "remediation": "Adapt bank detail logic for BP bank details (BUT0BK).",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "TBL_165": {
        "title": "LFBK Vendor Bank Details → BP Bank Details",
        "category": "Deprecated Tables",
        "description": (
            "LFBK (vendor bank details) adapted for BP bank detail model."
        ),
        "severity": "YELLOW",
        "affected_tables": ['LFBK', 'BUT0BK'],
        "affected_transactions": ['XK01', 'BP'],
        "remediation": "Adapt bank detail logic for BP bank details (BUT0BK).",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2331060",
    },
    "TBL_166": {
        "title": "ILOA Functional Location Account Assignment Adapted",
        "category": "Deprecated Tables",
        "description": (
            "ILOA (functional location account assignment) fields adapted. New fields "
            "for S/4HANA asset integration."
        ),
        "severity": "YELLOW",
        "affected_tables": ['ILOA'],
        "affected_transactions": ['IL01', 'IL02'],
        "remediation": "Review custom ILOA field usage. Adapt for new field structure.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "TBL_167": {
        "title": "AFIH PM Order Header Adapted",
        "category": "Deprecated Tables",
        "description": (
            "AFIH (maintenance order header) fields adapted for S/4HANA integration "
            "with new asset accounting and scheduling."
        ),
        "severity": "YELLOW",
        "affected_tables": ['AFIH'],
        "affected_transactions": ['IW31', 'IW32'],
        "remediation": "Review custom AFIH field usage and adapt.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "TBL_168": {
        "title": "EQUI Equipment Master Adapted",
        "category": "Deprecated Tables",
        "description": (
            "EQUI (equipment master) adapted for S/4HANA. New fields for IoT "
            "integration and asset connection."
        ),
        "severity": "YELLOW",
        "affected_tables": ['EQUI'],
        "affected_transactions": ['IE01', 'IE02', 'IE03'],
        "remediation": "Review custom EQUI field usage. Adapt for new fields.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "TBL_169": {
        "title": "EQUZ Equipment Time Segment Adapted",
        "category": "Deprecated Tables",
        "description": (
            "EQUZ (equipment/installation time segment) adapted for S/4HANA "
            "equipment-to-functional-location assignment."
        ),
        "severity": "YELLOW",
        "affected_tables": ['EQUZ'],
        "affected_transactions": ['IE01', 'IE02'],
        "remediation": "Review custom EQUZ time segment logic.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "TBL_170": {
        "title": "JEST Object Status Tables Performance",
        "category": "Deprecated Tables",
        "description": (
            "JEST (individual object status) performance-critical in S/4HANA due to "
            "more status-managed objects."
        ),
        "severity": "YELLOW",
        "affected_tables": ['JEST', 'JSTO'],
        "affected_transactions": ['BS22', 'BS02'],
        "remediation": "Review JEST index usage. Optimize status queries.",
        "effort_hours": 8,
        "responsible_team": "Basis",
        "sap_note": "2326578",
    },
    "TBL_171": {
        "title": "JSTO Object Status Header Adapted",
        "category": "Deprecated Tables",
        "description": (
            "JSTO (status object header) adapted for new object types in S/4HANA."
        ),
        "severity": "GREEN",
        "affected_tables": ['JSTO', 'JEST'],
        "affected_transactions": [],
        "remediation": "Review custom status profile usage.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "TBL_172": {
        "title": "AUFK Order Master Settlement to ACDOCA",
        "category": "Deprecated Tables",
        "description": (
            "AUFK (order master) settlement rules adapted for ACDOCA. Internal order "
            "settlement posts directly to ACDOCA."
        ),
        "severity": "YELLOW",
        "affected_tables": ['AUFK', 'ACDOCA'],
        "affected_transactions": ['KO01', 'KO02', 'KO88'],
        "remediation": "Adapt settlement rule exits for ACDOCA posting.",
        "effort_hours": 12,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "TBL_173": {
        "title": "QMEL Quality Notification Header Adapted",
        "category": "Deprecated Tables",
        "description": (
            "QMEL (quality notification header) adapted for S/4HANA Fiori-based "
            "notification processing."
        ),
        "severity": "YELLOW",
        "affected_tables": ['QMEL'],
        "affected_transactions": ['QM01', 'QM02'],
        "remediation": "Test quality notification processing with Fiori apps.",
        "effort_hours": 8,
        "responsible_team": "Functional",
        "sap_note": "2253942",
    },
    "TBL_174": {
        "title": "QMIH Quality Notification Maintenance Data Adapted",
        "category": "Deprecated Tables",
        "description": (
            "QMIH (QM notification maintenance header data) adapted for PM/QM "
            "integration in S/4HANA."
        ),
        "severity": "YELLOW",
        "affected_tables": ['QMIH'],
        "affected_transactions": ['QM01', 'IW21'],
        "remediation": "Review combined QM/PM notification processing.",
        "effort_hours": 8,
        "responsible_team": "Functional",
        "sap_note": "2253942",
    },
    "TBL_175": {
        "title": "QMFE Quality Notification Items Adapted",
        "category": "Deprecated Tables",
        "description": (
            "QMFE (QM notification items/defects) adapted for Fiori-based defect "
            "recording."
        ),
        "severity": "YELLOW",
        "affected_tables": ['QMFE'],
        "affected_transactions": ['QM01', 'QM02'],
        "remediation": "Test defect recording with Fiori quality notification apps.",
        "effort_hours": 8,
        "responsible_team": "Functional",
        "sap_note": "2253942",
    },
    "TBL_176": {
        "title": "AFVC Operation/Activity in Order Adapted",
        "category": "Deprecated Tables",
        "description": (
            "AFVC (order operation/activity) adapted for S/4HANA scheduling and "
            "MATDOC-based confirmations."
        ),
        "severity": "YELLOW",
        "affected_tables": ['AFVC'],
        "affected_transactions": ['IW31', 'IW32', 'CO11N'],
        "remediation": "Review custom operation field access.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "TBL_177": {
        "title": "CRHD Work Center Master Adapted",
        "category": "Deprecated Tables",
        "description": (
            "CRHD (work center header) adapted with new capacity planning fields for "
            "S/4HANA."
        ),
        "severity": "GREEN",
        "affected_tables": ['CRHD'],
        "affected_transactions": ['CR01', 'CR02'],
        "remediation": "Review custom work center field usage.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2326578",
    },
    "TBL_178": {
        "title": "MPOS Maintenance Item Adapted",
        "category": "Deprecated Tables",
        "description": (
            "MPOS (maintenance plan item) adapted for Fiori-based maintenance "
            "planning."
        ),
        "severity": "YELLOW",
        "affected_tables": ['MPOS', 'MPLA'],
        "affected_transactions": ['IP01', 'IP02'],
        "remediation": "Adapt maintenance plan processing for Fiori apps.",
        "effort_hours": 8,
        "responsible_team": "Functional",
        "sap_note": "2326578",
    },
    "TBL_179": {
        "title": "MPLA Maintenance Plan Header Adapted",
        "category": "Deprecated Tables",
        "description": (
            "MPLA (maintenance plan header) adapted for S/4HANA with new scheduling "
            "parameters."
        ),
        "severity": "YELLOW",
        "affected_tables": ['MPLA'],
        "affected_transactions": ['IP01', 'IP02'],
        "remediation": "Review maintenance plan scheduling configuration.",
        "effort_hours": 8,
        "responsible_team": "Functional",
        "sap_note": "2326578",
    },
    "TBL_180": {
        "title": "QALS Inspection Lot Adapted for MATDOC",
        "category": "Deprecated Tables",
        "description": (
            "QALS (inspection lot) creation triggered from MATDOC-based goods receipt "
            "instead of MKPF/MSEG."
        ),
        "severity": "YELLOW",
        "affected_tables": ['QALS', 'MATDOC'],
        "affected_transactions": ['QA01', 'QA11', 'QA32'],
        "remediation": "Test inspection lot creation on goods receipt with MATDOC.",
        "effort_hours": 12,
        "responsible_team": "Functional",
        "sap_note": "2253942",
    },
    "TBL_181": {
        "title": "TSTC Transaction Code Table: Deprecated Tcodes Removed",
        "category": "Deprecated Tables",
        "description": (
            "TSTC (transaction code catalog) updated. Hundreds of deprecated "
            "transactions removed from S/4HANA."
        ),
        "severity": "YELLOW",
        "affected_tables": ['TSTC', 'TSTCA'],
        "affected_transactions": ['SE93'],
        "remediation": "Review custom TSTC reads. Deprecated tcodes return empty results.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "TBL_182": {
        "title": "TSTCA Transaction Code Authorization Adapted",
        "category": "Deprecated Tables",
        "description": (
            "TSTCA (transaction code authorization keys) adapted. Roles must be "
            "updated for removed/replaced transactions."
        ),
        "severity": "YELLOW",
        "affected_tables": ['TSTCA'],
        "affected_transactions": ['SU24', 'PFCG'],
        "remediation": "Update authorization profiles for deprecated transactions.",
        "effort_hours": 16,
        "responsible_team": "Basis",
        "sap_note": "2296888",
    },
    "TBL_183": {
        "title": "RFCDES RFC Destinations Validated",
        "category": "Deprecated Tables",
        "description": (
            "RFCDES (RFC destination configuration) must be validated. RFC "
            "connections to deprecated function modules will fail."
        ),
        "severity": "YELLOW",
        "affected_tables": ['RFCDES'],
        "affected_transactions": ['SM59'],
        "remediation": "Validate all RFC destinations for S/4HANA compatibility.",
        "effort_hours": 16,
        "responsible_team": "Basis",
        "sap_note": "2296888",
    },
    "TBL_184": {
        "title": "CWBNTHEAD SAP Note Application Status",
        "category": "Deprecated Tables",
        "description": (
            "CWBNTHEAD (SAP Note status) tracks applied notes. Prerequisite notes for "
            "S/4HANA must be verified."
        ),
        "severity": "GREEN",
        "affected_tables": ['CWBNTHEAD'],
        "affected_transactions": ['SNOTE'],
        "remediation": "Verify prerequisite SAP Notes are applied via SNOTE.",
        "effort_hours": 4,
        "responsible_team": "Basis",
        "sap_note": "2296888",
    },
    "TBL_185": {
        "title": "USR02 User Master Logon Data Adapted",
        "category": "Deprecated Tables",
        "description": (
            "USR02 (user master logon data) adapted for S/4HANA authentication. "
            "Password hash algorithm updated."
        ),
        "severity": "YELLOW",
        "affected_tables": ['USR02'],
        "affected_transactions": ['SU01', 'SU10'],
        "remediation": "Review user master data migration and password policies.",
        "effort_hours": 12,
        "responsible_team": "Basis",
        "sap_note": "2296888",
    },
    "TBL_186": {
        "title": "AGR_1251 Authorization Profile Values Adapted",
        "category": "Deprecated Tables",
        "description": (
            "AGR_1251 (role menu authorization values) must be updated for "
            "removed/replaced transactions and objects."
        ),
        "severity": "YELLOW",
        "affected_tables": ['AGR_1251', 'AGR_DEFINE'],
        "affected_transactions": ['PFCG'],
        "remediation": "Regenerate authorization profiles. Update for new Fiori apps.",
        "effort_hours": 24,
        "responsible_team": "Basis",
        "sap_note": "2296888",
    },
    "TBL_187": {
        "title": "TADIR Repository Object Directory Adapted",
        "category": "Deprecated Tables",
        "description": (
            "TADIR (repository objects) adapted for S/4HANA. Deprecated objects "
            "marked. New namespace objects added."
        ),
        "severity": "GREEN",
        "affected_tables": ['TADIR'],
        "affected_transactions": ['SE80', 'SE03'],
        "remediation": "No action unless custom code queries TADIR for deprecated objects.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "TBL_188": {
        "title": "D010TAB Table Where-Used List Adapted",
        "category": "Deprecated Tables",
        "description": (
            "D010TAB (where-used: table in program) adapted. Critical for identifying "
            "custom code using deprecated tables."
        ),
        "severity": "GREEN",
        "affected_tables": ['D010TAB'],
        "affected_transactions": ['SE03', 'SE80'],
        "remediation": "Use D010TAB to scan custom programs for deprecated table usage.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "TBL_189": {
        "title": "D010INC Include Where-Used Adapted",
        "category": "Deprecated Tables",
        "description": (
            "D010INC (where-used: include in program) adapted for S/4HANA code "
            "scanning."
        ),
        "severity": "GREEN",
        "affected_tables": ['D010INC'],
        "affected_transactions": ['SE80'],
        "remediation": "Use include where-used for custom code impact analysis.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2270689",
    },
    "TBL_190": {
        "title": "TBTCO Job Scheduling Status Adapted",
        "category": "Deprecated Tables",
        "description": (
            "TBTCO (background job status) adapted for S/4HANA. Some standard jobs "
            "replaced by Fiori-based scheduling."
        ),
        "severity": "YELLOW",
        "affected_tables": ['TBTCO', 'TBTCP'],
        "affected_transactions": ['SM36', 'SM37'],
        "remediation": "Review scheduled background jobs. Adapt for Fiori job scheduling.",
        "effort_hours": 12,
        "responsible_team": "Basis",
        "sap_note": "2296888",
    },
    "TBL_191": {
        "title": "TBTCP Job Step Table Adapted",
        "category": "Deprecated Tables",
        "description": (
            "TBTCP (background job steps) adapted. Job steps referencing deprecated "
            "programs must be updated."
        ),
        "severity": "YELLOW",
        "affected_tables": ['TBTCP'],
        "affected_transactions": ['SM36', 'SM37'],
        "remediation": "Update job steps that call deprecated reports/programs.",
        "effort_hours": 12,
        "responsible_team": "Basis",
        "sap_note": "2296888",
    },
    "TBL_192": {
        "title": "EDID4 IDoc Data Records Adapted",
        "category": "Deprecated Tables",
        "description": (
            "EDID4 (IDoc data records) adapted for S/4HANA. IDoc segments for BP, "
            "MATDOC, PRCD_ELEMENTS changed."
        ),
        "severity": "YELLOW",
        "affected_tables": ['EDID4'],
        "affected_transactions": ['WE02', 'WE05', 'WE19'],
        "remediation": "Review IDoc message types and segments for S/4HANA changes.",
        "effort_hours": 16,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "TBL_193": {
        "title": "EDIDC IDoc Control Records Adapted",
        "category": "Deprecated Tables",
        "description": (
            "EDIDC (IDoc control records) adapted. New IDoc types for S/4HANA "
            "scenarios."
        ),
        "severity": "GREEN",
        "affected_tables": ['EDIDC'],
        "affected_transactions": ['WE02', 'WE05'],
        "remediation": "Review IDoc control record processing for new message types.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "TBL_194": {
        "title": "EDIDS IDoc Status Records Adapted",
        "category": "Deprecated Tables",
        "description": (
            "EDIDS (IDoc status records) adapted. New status codes for S/4HANA IDoc "
            "processing."
        ),
        "severity": "GREEN",
        "affected_tables": ['EDIDS'],
        "affected_transactions": ['WE02', 'BD87'],
        "remediation": "Review IDoc error handling for new status codes.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "TBL_195": {
        "title": "E070 Transport Header Adapted",
        "category": "Deprecated Tables",
        "description": (
            "E070 (change request/transport header) adapted for S/4HANA transport "
            "management."
        ),
        "severity": "GREEN",
        "affected_tables": ['E070', 'E071'],
        "affected_transactions": ['SE09', 'SE10'],
        "remediation": "No action unless custom transport management logic.",
        "effort_hours": 4,
        "responsible_team": "Basis",
        "sap_note": "2296888",
    },
    "TBL_196": {
        "title": "E071 Transport Object List Adapted",
        "category": "Deprecated Tables",
        "description": (
            "E071 (transport object entries) adapted for new S/4HANA repository "
            "objects."
        ),
        "severity": "GREEN",
        "affected_tables": ['E071'],
        "affected_transactions": ['SE09', 'SE10'],
        "remediation": "Review custom transport tools for new object types.",
        "effort_hours": 4,
        "responsible_team": "Basis",
        "sap_note": "2296888",
    },
    "TBL_197": {
        "title": "PA0001 HR Infotype 0001 Compatibility Mode",
        "category": "Deprecated Tables",
        "description": (
            "PA0001 (HR organizational assignment infotype) runs in compatibility "
            "mode in S/4HANA on-premise HCM."
        ),
        "severity": "YELLOW",
        "affected_tables": ['PA0001', 'PA0002'],
        "affected_transactions": ['PA20', 'PA30'],
        "remediation": "Plan HCM strategy: S/4HANA on-premise HCM or SuccessFactors.",
        "effort_hours": 40,
        "responsible_team": "Functional",
        "sap_note": "2296888",
    },
    "TBL_198": {
        "title": "HRP1000 Org Management Objects Compatibility",
        "category": "Deprecated Tables",
        "description": (
            "HRP1000 (org management objects) runs in compatibility mode for S/4HANA "
            "on-premise HCM."
        ),
        "severity": "YELLOW",
        "affected_tables": ['HRP1000', 'HRP1001'],
        "affected_transactions": ['PPOME', 'PPOSE'],
        "remediation": "Review org management usage. Plan for S/4HANA HCM or cloud.",
        "effort_hours": 24,
        "responsible_team": "Functional",
        "sap_note": "2296888",
    },
    "TBL_199": {
        "title": "PROJ Project Master Field Changes",
        "category": "Deprecated Tables",
        "description": (
            "PROJ (project definition) and PRPS (WBS elements) receive new fields for "
            "S/4HANA project integration."
        ),
        "severity": "GREEN",
        "affected_tables": ['PROJ', 'PRPS'],
        "affected_transactions": ['CJ01', 'CJ02', 'CJ03'],
        "remediation": "Review custom PROJ/PRPS field usage.",
        "effort_hours": 8,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
    "TBL_200": {
        "title": "DRAD Document Object Link Adapted",
        "category": "Deprecated Tables",
        "description": (
            "DRAD (document-object link) and general DMS tables adapted for S/4HANA "
            "document management."
        ),
        "severity": "GREEN",
        "affected_tables": ['DRAD', 'DRAW'],
        "affected_transactions": ['CV01N', 'CV02N'],
        "remediation": "Review custom document management integrations.",
        "effort_hours": 4,
        "responsible_team": "ABAP dev",
        "sap_note": "2296888",
    },
}
