"""
Migrate4HANA — Level 3: S/4HANA Config Generator
==================================================
Generates actual S/4HANA configuration: ACDOCA ledgers, BP conversion,
Fiori catalogs, tax procedures for 13+ countries, number ranges,
Material Ledger, credit management, output management.
"""
import json
from typing import Dict, List
from datetime import datetime

class S4HANAConfigGenerator:
    def __init__(self, countries=None):
        self.countries = countries or ["ALL"]

    def generate_all(self, discovery_data: Dict) -> Dict:
        org = discovery_data.get("org_structure", {})
        ccs = org.get("company_codes", [])
        plants = org.get("plants", [])
        currencies = set(cc.get("WAERS", "USD") for cc in ccs)

        return {
            "metadata": {"generated_at": datetime.now().isoformat(), "countries": self.countries},
            "configs": {
                "universal_journal": self._gen_uj(ccs, currencies),
                "business_partner": self._gen_bp(discovery_data),
                "fiori_launchpad": self._gen_fiori(discovery_data),
                "number_ranges": self._gen_nr(),
                "tax_procedures": self._gen_tax(),
                "material_ledger": self._gen_ml(plants),
                "credit_management": self._gen_cm(),
                "output_management": self._gen_om(),
            },
            "abap_scripts": {
                "bp_conversion": self._script_bp_conversion(),
                "credit_migration": self._script_credit_migration(),
                "ml_activation": self._script_ml_activation(),
            },
        }

    def _gen_uj(self, ccs, currencies):
        ledgers = [{"ledger": "0L", "name": "Leading Ledger", "leading": True, "currency_type": "10"}]
        if len(currencies) > 1:
            ledgers.append({"ledger": "2L", "name": "Group Currency", "leading": False, "currency_type": "30"})
        return {"description": "Universal Journal", "transaction": "FINSC_LEDGER", "status": "AUTO_GENERATED",
                "ledgers": ledgers,
                "assignments": [{"cc": c.get("BUKRS"), "name": c.get("BUTXT"), "currency": c.get("WAERS"), "ledger": "0L"} for c in ccs]}

    def _gen_bp(self, data):
        custs, vends = len(data.get("customers") or []), len(data.get("vendors") or [])
        return {"description": "BP Conversion", "transaction": "BUCF", "status": "AUTO_GENERATED",
                "number_range": {"object": "BU_PARTNER", "from": "0000000001", "to": "0009999999"},
                "groupings": {"customer": "BP01", "vendor": "BP02"},
                "roles": {"customer": "FLCU00", "vendor": "FLVN00"},
                "sync_direction": "BP_TO_CUSTOMER_VENDOR",
                "estimated": {"customers": custs, "vendors": vends, "total_bps": custs + vends}}

    def _gen_fiori(self, data):
        mapping = {"Z_FI_": ["SAP_SFIN_BC_GL_DOCPROC"], "Z_MM_": ["SAP_MM_BC_PO_PROCESS"],
                   "Z_SD_": ["SAP_SD_BC_SO_PROCESS"], "Z_PP_": ["SAP_PP_BC_PROD_ORD"],
                   "Z_HR_": ["SAP_HCM_BC_PA_MASTER"], "Z_CO_": ["SAP_CO_BC_CCTR_MASTER"]}
        assignments = []
        for role in data.get("roles", {}).get("roles", []):
            name = role.get("AGR_NAME", role.get("name", ""))
            for prefix, cats in mapping.items():
                if name.upper().startswith(prefix):
                    for c in cats:
                        assignments.append({"role": name, "catalog": c})
        return {"description": "Fiori Launchpad", "transaction": "/UI2/FLPD_CUST", "status": "AUTO_GENERATED",
                "theme": "sap_horizon", "assignments": assignments[:100], "total": len(assignments)}

    def _gen_nr(self):
        return {"description": "Number Ranges", "transaction": "SNRO", "status": "AUTO_GENERATED",
                "ranges": [
                    {"object": "BU_PARTNER", "from": "0000000001", "to": "0009999999"},
                    {"object": "MATDOC", "from": "5000000000", "to": "5999999999"},
                    {"object": "PRCD_ELEM", "from": "0000000001", "to": "9999999999"},
                ]}

    def _gen_tax(self):
        all_procs = {
            "IN": {"procedure": "TAXINN", "desc": "India GST", "conditions": ["JIIG", "JICG", "JISG"]},
            "US": {"procedure": "TAXUS", "desc": "US Sales Tax", "conditions": ["Jurisdiction-based"]},
            "DE": {"procedure": "TAXD", "desc": "Germany VAT", "conditions": ["MWST", "MWVS"]},
            "BR": {"procedure": "TAXBRA", "desc": "Brazil", "conditions": ["ICMS", "PIS", "COFINS"]},
            "CN": {"procedure": "TAXCN", "desc": "China VAT", "conditions": ["VAT Output/Input"]},
            "GB": {"procedure": "TAXGB", "desc": "UK VAT", "conditions": ["UK VAT"]},
            "AE": {"procedure": "TAXAE", "desc": "UAE VAT 5%", "conditions": ["UAE VAT"]},
            "SA": {"procedure": "TAXSA", "desc": "Saudi VAT 15%", "conditions": ["SA VAT"]},
            "JP": {"procedure": "TAXJP", "desc": "Japan Consumption Tax", "conditions": ["10%", "8% reduced"]},
            "AU": {"procedure": "TAXAU", "desc": "Australia GST 10%", "conditions": ["AU GST"]},
            "FR": {"procedure": "TAXFRA", "desc": "France TVA", "conditions": ["TVA"]},
            "MX": {"procedure": "TAXMX", "desc": "Mexico IVA", "conditions": ["IVA", "ISR"]},
            "IT": {"procedure": "TAXITA", "desc": "Italy IVA", "conditions": ["IVA"]},
        }
        applicable = {k: v for k, v in all_procs.items() if k in self.countries or "ALL" in self.countries}
        return {"description": "Tax Procedures", "transaction": "OBYZ", "status": "AUTO_GENERATED", "procedures": applicable}

    def _gen_ml(self, plants):
        return {"description": "Material Ledger (mandatory)", "transaction": "OMX1", "status": "AUTO_GENERATED",
                "always_active": True,
                "plants": [{"plant": p.get("WERKS"), "name": p.get("NAME1"), "ml_active": True} for p in plants]}

    def _gen_cm(self):
        return {"description": "Credit Management (KNKK→UKM)", "transaction": "UKM_ADMIN", "status": "AUTO_GENERATED",
                "steps": ["Activate FIN-FSCM-CR", "Define credit segments", "Migrate KNKK→UKM_ACCOUNT",
                          "Configure BRF+ rules", "Activate real-time credit check"]}

    def _gen_om(self):
        return {"description": "Output Management (NACE→BRF+)", "status": "AUTO_GENERATED",
                "migrations": [{"old": "NACE", "new": "BRF+ Rules"}, {"old": "SAPscript", "new": "Adobe Forms"},
                               {"old": "Smart Forms", "new": "Adobe Forms / Fiori Print"}]}

    def _script_bp_conversion(self):
        return ("REPORT zbp_conversion.\n"
                "* Step 1: Pre-check\n"
                "CALL FUNCTION 'CVI_ERP_ORG_BP_CUST_PRECHECK' EXPORTING iv_bukrs = '1000'.\n"
                "* Step 2: Synchronize\n"
                "CALL FUNCTION 'CVI_ERP_ORG_BP_CUST_SYNC' EXPORTING iv_bukrs = '1000' iv_direction = 'ERP_TO_BP'.\n"
                "* Step 3: Verify\n"
                "SELECT COUNT(*) FROM but000 INTO @DATA(lv_bp).\n"
                "SELECT COUNT(*) FROM kna1 INTO @DATA(lv_cust).\n"
                "WRITE: / 'BPs:', lv_bp, 'Customers:', lv_cust.\n")

    def _script_credit_migration(self):
        return ("REPORT zcredit_migrate.\n"
                "CALL FUNCTION 'UKM_MIGRATION_KNKK_TO_UKM' EXPORTING iv_kkber = '1000' iv_test_run = 'X'.\n")

    def _script_ml_activation(self):
        return ("* Material Ledger is always active in S/4HANA.\n"
                "* Run CKMSTART for initial valuation run after migration.\n")


if __name__ == '__main__':
    gen = S4HANAConfigGenerator(countries=["IN", "US", "DE", "AE"])
    test = {"org_structure": {"company_codes": [{"BUKRS": "1000", "BUTXT": "Test", "WAERS": "INR"}],
            "plants": [{"WERKS": "1001", "NAME1": "Plant 1"}]},
            "customers": [None]*100, "vendors": [None]*50, "roles": {"roles": []}}
    cfg = gen.generate_all(test)
    print(f"Level 3 — Configs: {len(cfg['configs'])}, Scripts: {len(cfg['abap_scripts'])}")
    for k, v in cfg['configs'].items():
        print(f"  {k:25s} [{v.get('status','?')}]")
