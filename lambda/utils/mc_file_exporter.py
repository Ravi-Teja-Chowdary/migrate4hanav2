"""
mc_file_exporter - SAP Migration Cockpit file-lane exporter.

Single framework covering the ~20 catalog objects that DON'T have a usable
direct create BAPI (probed and documented in BREADTH_TRACKER.md). These
intentionally route to SAP's Migration Cockpit XML/CSV templates rather
than to a per-object spine subclass.

The exporter:
  1. Pulls source rows from the extracted staging tier
  2. Validates each row against the MC object's template column spec
  3. Writes a UTF-8 CSV / XML conforming to the MC template
  4. Uploads to the customer's staging bucket under a canonical key
     so the customer's CSV->MC upload step is a single mc.upload call

A "MigrationCockpitFile" pseudo-spine is registered in the
BaseSpineOrchestrator registry so UnifiedLoader.load_object() routes
file-lane objects through the SAME interface as BAPI-lane objects --
caller sees a uniform load_result shape with `mechanism = "mc_file/..."`.

Covered objects (registered at import time):
  Routing · ActivityType · StatisticalKeyFigure · CommitmentItem · GLAccount
  TaskList · InspPlan · InspMethod · ServiceMaster · SourceList · HouseBank
  HouseBankAccount · ConditionRecord · CustomerHierarchy · BOMItem · Network
  WBSElement · OrgUnit · Position · EmployeeAction
"""
from __future__ import annotations

import csv
import io
import json
from typing import Optional

from base_spine_orchestrator import (
    BaseSpineOrchestrator, register_spine,
    DISP_CREATED, DEAD_LETTER_DQ,
)


# ─────────────────────────────────────────────────────────────────────────────
# MC template registry: (object_type, csv_columns, mandatory_columns,
#                        mc_template_name, target_table)
# Drawn from the standard SAP Migration Cockpit catalogue (S/4 2023);
# customer-specific Z-columns are absorbed via extension fields.
# ─────────────────────────────────────────────────────────────────────────────
MC_TEMPLATES: dict = {
    "Routing": {
        "csv_columns":         ["PLNNR", "PLNAL", "WERKS", "MATNR",
                                 "OBJEKT", "ARBPL", "USAGE", "VERWE"],
        "mandatory":           ["PLNNR", "WERKS", "MATNR", "ARBPL"],
        "template":            "MC_PP_ROUTING_TEMPLATE_V1",
        "target_table":        "PLKO",
    },
    "ActivityType": {
        "csv_columns":         ["KOKRS", "LSTAR", "TXT", "ATYP", "OUTPUT_UNIT"],
        "mandatory":           ["KOKRS", "LSTAR", "ATYP"],
        "template":            "MC_CO_ACTIVITY_TYPE_V1",
        "target_table":        "CSLA",
    },
    "StatisticalKeyFigure": {
        "csv_columns":         ["KOKRS", "STAGR", "TXT", "MEINS"],
        "mandatory":           ["KOKRS", "STAGR"],
        "template":            "MC_CO_STAT_KEY_FIG_V1",
        "target_table":        "TKA03",
    },
    "CommitmentItem": {
        "csv_columns":         ["FIKRS", "FIPEX", "TXT", "FIPLEVEL", "FIPSTATUS"],
        "mandatory":           ["FIKRS", "FIPEX"],
        "template":            "MC_FM_COMMITMENT_ITEM_V1",
        "target_table":        "FMCI",
    },
    "GLAccount": {
        "csv_columns":         ["KTOPL", "SAKNR", "TXT", "KTOKS", "MITKZ"],
        "mandatory":           ["KTOPL", "SAKNR"],
        "template":            "MC_FI_GL_ACCOUNT_V1",
        "target_table":        "SKA1",
    },
    "TaskList": {
        "csv_columns":         ["PLNTY", "PLNNR", "PLNAL", "MATNR", "WERKS"],
        "mandatory":           ["PLNTY", "PLNNR", "WERKS"],
        "template":            "MC_PM_TASK_LIST_V1",
        "target_table":        "PLKO",
    },
    "InspPlan": {
        "csv_columns":         ["PLNNR", "PLNAL", "WERKS", "PRUEFART", "STATU"],
        "mandatory":           ["PLNNR", "WERKS"],
        "template":            "MC_QM_INSP_PLAN_V1",
        "target_table":        "PLKO",
    },
    "InspMethod": {
        "csv_columns":         ["WERKS", "METHODE", "VERWMETH", "TXT"],
        "mandatory":           ["WERKS", "METHODE"],
        "template":            "MC_QM_INSP_METHOD_V1",
        "target_table":        "QPMT",
    },
    "ServiceMaster": {
        "csv_columns":         ["ASNUM", "TXT", "KTEXT", "MEINS", "MATKL"],
        "mandatory":           ["ASNUM"],
        "template":            "MC_MM_SERVICE_MASTER_V1",
        "target_table":        "ASMD",
    },
    "SourceList": {
        "csv_columns":         ["MATNR", "WERKS", "LIFNR", "EKORG", "VDATU", "BDATU"],
        "mandatory":           ["MATNR", "WERKS", "LIFNR", "EKORG"],
        "template":            "MC_MM_SOURCE_LIST_V1",
        "target_table":        "EORD",
    },
    "HouseBank": {
        "csv_columns":         ["BUKRS", "HBKID", "BANKS", "BANKL"],
        "mandatory":           ["BUKRS", "HBKID", "BANKS", "BANKL"],
        "template":            "MC_FI_HOUSE_BANK_V1",
        "target_table":        "T012",
    },
    "HouseBankAccount": {
        "csv_columns":         ["BUKRS", "HBKID", "HKTID", "BANKN", "BKONT", "WAERS"],
        "mandatory":           ["BUKRS", "HBKID", "HKTID"],
        "template":            "MC_FI_HOUSE_BANK_ACCOUNT_V1",
        "target_table":        "T012K",
    },
    "ConditionRecord": {
        "csv_columns":         ["KSCHL", "VKORG", "VTWEG", "KUNNR", "MATNR",
                                 "KBETR", "WAERS", "DATBI"],
        "mandatory":           ["KSCHL", "KBETR"],
        "template":            "MC_SD_CONDITION_RECORD_V1",
        "target_table":        "KONP",
    },
    "CustomerHierarchy": {
        "csv_columns":         ["HITYP", "KUNNR", "HKUNNR", "VKORG",
                                 "VTWEG", "SPART", "DATAB", "DATBI"],
        "mandatory":           ["HITYP", "KUNNR", "HKUNNR"],
        "template":            "MC_SD_CUSTOMER_HIERARCHY_V1",
        "target_table":        "KNVH",
    },
    "BOMItem": {
        "csv_columns":         ["STLNR", "STLKN", "POSNR", "IDNRK", "MENGE", "MEINS"],
        "mandatory":           ["STLNR", "POSNR", "IDNRK"],
        "template":            "MC_PP_BOM_ITEM_V1",
        "target_table":        "STPO",
    },
    "Network": {
        "csv_columns":         ["AUFNR", "AUART", "WERKS", "TXT", "PRIO"],
        "mandatory":           ["AUFNR", "AUART", "WERKS"],
        "template":            "MC_PS_NETWORK_V1",
        "target_table":        "AUFK",
    },
    "WBSElement": {
        "csv_columns":         ["PSPID", "POSID", "POST1", "STUFE", "PRART"],
        "mandatory":           ["PSPID", "POSID"],
        "template":            "MC_PS_WBS_ELEMENT_V1",
        "target_table":        "PRPS",
    },
    "OrgUnit": {
        "csv_columns":         ["OBJID", "STELL", "PLANS", "BEGDA", "ENDDA"],
        "mandatory":           ["OBJID"],
        "template":            "MC_HR_ORG_UNIT_V1",
        "target_table":        "HRP1000",
    },
    "Position": {
        "csv_columns":         ["PLANS", "STELL", "ORGEH", "BEGDA", "ENDDA"],
        "mandatory":           ["PLANS"],
        "template":            "MC_HR_POSITION_V1",
        "target_table":        "HRP1000",
    },
    "EmployeeAction": {
        "csv_columns":         ["PERNR", "MASSN", "MASSG", "BEGDA", "ENDDA"],
        "mandatory":           ["PERNR", "MASSN"],
        "template":            "MC_HR_EMPLOYEE_ACTION_V1",
        "target_table":        "PA0000",
    },

    # ── Finance / CO extension ────────────────────────────────────────────────
    "AssetClass": {
        "csv_columns":         ["ANLKL", "TXT", "KTOGR", "ANKAA"],
        "mandatory":           ["ANLKL"],
        "template":            "MC_FI_ASSET_CLASS_V1",
        "target_table":        "ANKA",
    },
    "DepreciationArea": {
        "csv_columns":         ["AFAPL", "AFABE", "TXT", "WAERS"],
        "mandatory":           ["AFAPL", "AFABE"],
        "template":            "MC_FI_DEPRECIATION_AREA_V1",
        "target_table":        "T093",
    },
    "ChartOfAccounts": {
        "csv_columns":         ["KTOPL", "TXT", "KTLEN", "WAERS"],
        "mandatory":           ["KTOPL"],
        "template":            "MC_FI_CHART_OF_ACCOUNTS_V1",
        "target_table":        "T004",
    },
    "FundsCenter": {
        "csv_columns":         ["FIKRS", "FICTR", "TXT", "DATAB", "DATBI"],
        "mandatory":           ["FIKRS", "FICTR"],
        "template":            "MC_FM_FUNDS_CENTER_V1",
        "target_table":        "FMFCTR",
    },
    "Fund": {
        "csv_columns":         ["FIKRS", "GEBER", "TXT", "DATAB", "DATBI"],
        "mandatory":           ["FIKRS", "GEBER"],
        "template":            "MC_FM_FUND_V1",
        "target_table":        "FMFINCODE",
    },
    "ValidationRule": {
        "csv_columns":         ["KOKRS", "RULEID", "TXT", "STATUS"],
        "mandatory":           ["RULEID"],
        "template":            "MC_FI_VALIDATION_RULE_V1",
        "target_table":        "T080D",
    },
    "SubstitutionRule": {
        "csv_columns":         ["KOKRS", "SUBID", "TXT", "STATUS"],
        "mandatory":           ["SUBID"],
        "template":            "MC_FI_SUBSTITUTION_RULE_V1",
        "target_table":        "T080S",
    },
    "AccountingPrinciple": {
        "csv_columns":         ["ACCPRINC", "TXT", "LEDGER"],
        "mandatory":           ["ACCPRINC"],
        "template":            "MC_FI_ACCOUNTING_PRINCIPLE_V1",
        "target_table":        "T881",
    },
    "Ledger": {
        "csv_columns":         ["RLDNR", "TXT", "LEADING"],
        "mandatory":           ["RLDNR"],
        "template":            "MC_FI_LEDGER_V1",
        "target_table":        "T881",
    },

    # ── Material Master extensions ─────────────────────────────────────────────
    "UnitsOfMeasureMaster": {
        "csv_columns":         ["MSEHI", "TXT", "DECAN", "ISOCODE"],
        "mandatory":           ["MSEHI"],
        "template":            "MC_MM_UOM_MASTER_V1",
        "target_table":        "T006",
    },
    "BatchClassification": {
        "csv_columns":         ["MATNR", "CHARG", "CLASS", "ATNAM", "ATWRT"],
        "mandatory":           ["MATNR", "CHARG", "CLASS"],
        "template":            "MC_MM_BATCH_CLASSIFICATION_V1",
        "target_table":        "AUSP",
    },
    "SerialNumber": {
        "csv_columns":         ["MATNR", "SERNR", "WERKS", "LGORT"],
        "mandatory":           ["MATNR", "SERNR"],
        "template":            "MC_MM_SERIAL_NUMBER_V1",
        "target_table":        "EQUI",
    },
    "MaterialClassification": {
        "csv_columns":         ["MATNR", "CLASS", "KLART", "ATNAM", "ATWRT"],
        "mandatory":           ["MATNR", "CLASS"],
        "template":            "MC_MM_MATERIAL_CLASSIFICATION_V1",
        "target_table":        "AUSP",
    },
    "MaterialLedger": {
        "csv_columns":         ["MATNR", "BUKRS", "WAERS", "VPRSV"],
        "mandatory":           ["MATNR", "BUKRS"],
        "template":            "MC_MM_MATERIAL_LEDGER_V1",
        "target_table":        "CKMLHD",
    },
    "WarehouseStock": {
        "csv_columns":         ["LGNUM", "LGTYP", "LGPLA", "MATNR", "GESME"],
        "mandatory":           ["LGNUM", "LGTYP", "LGPLA", "MATNR"],
        "template":            "MC_WM_WAREHOUSE_STOCK_V1",
        "target_table":        "LQUA",
    },

    # ── SD module extensions ──────────────────────────────────────────────────
    "SalesContract": {
        "csv_columns":         ["VBELN", "AUART", "VKORG", "VTWEG", "KUNNR"],
        "mandatory":           ["VBELN", "AUART", "VKORG"],
        "template":            "MC_SD_CONTRACT_V1",
        "target_table":        "VBAK",
    },
    "ScheduleAgreementSD": {
        "csv_columns":         ["VBELN", "AUART", "VKORG", "MATNR", "LFIMG"],
        "mandatory":           ["VBELN", "AUART"],
        "template":            "MC_SD_SCHEDULE_AGREEMENT_V1",
        "target_table":        "VBAK",
    },
    "CreditMemoRequest": {
        "csv_columns":         ["VBELN", "AUART", "VKORG", "KUNNR", "WRBTR"],
        "mandatory":           ["VBELN", "AUART"],
        "template":            "MC_SD_CREDIT_MEMO_REQ_V1",
        "target_table":        "VBAK",
    },
    "ReturnsOrderSD": {
        "csv_columns":         ["VBELN", "AUART", "VKORG", "KUNNR", "VBELN_VL"],
        "mandatory":           ["VBELN", "AUART"],
        "template":            "MC_SD_RETURNS_ORDER_V1",
        "target_table":        "VBAK",
    },
    "RebateAgreement": {
        "csv_columns":         ["KNUMA", "BOART", "VKORG", "BNDDT_PROV"],
        "mandatory":           ["KNUMA", "BOART"],
        "template":            "MC_SD_REBATE_AGREEMENT_V1",
        "target_table":        "KONA",
    },
    "ListingExclusion": {
        "csv_columns":         ["VKORG", "VTWEG", "KUNNR", "MATNR", "DATAB", "DATBI"],
        "mandatory":           ["VKORG", "VTWEG"],
        "template":            "MC_SD_LISTING_EXCLUSION_V1",
        "target_table":        "WLF1",
    },
    "PartnerFunctionDetermination": {
        "csv_columns":         ["VKORG", "VTWEG", "SPART", "PARVW", "REQ"],
        "mandatory":           ["VKORG", "PARVW"],
        "template":            "MC_SD_PARTNER_DETERMINATION_V1",
        "target_table":        "TPR_OBJ",
    },

    # ── MM/Procurement extensions ─────────────────────────────────────────────
    "ScheduleAgreementMM": {
        "csv_columns":         ["EBELN", "BSART", "LIFNR", "EKORG", "MATNR"],
        "mandatory":           ["EBELN", "BSART", "LIFNR"],
        "template":            "MC_MM_SCHEDULE_AGREEMENT_V1",
        "target_table":        "EKKO",
    },
    "ServiceEntrySheet": {
        "csv_columns":         ["LBLNI", "EBELN", "LBNUM", "MENGE", "MEINS"],
        "mandatory":           ["LBLNI", "EBELN"],
        "template":            "MC_MM_SERVICE_ENTRY_V1",
        "target_table":        "ESSR",
    },
    "InvoiceReceipt": {
        "csv_columns":         ["BELNR", "GJAHR", "LIFNR", "BUKRS", "WRBTR"],
        "mandatory":           ["BELNR", "BUKRS", "LIFNR"],
        "template":            "MC_MM_INVOICE_RECEIPT_V1",
        "target_table":        "RBKP",
    },
    "GoodsReceipt": {
        "csv_columns":         ["MBLNR", "MJAHR", "EBELN", "MATNR", "MENGE"],
        "mandatory":           ["MBLNR", "EBELN"],
        "template":            "MC_MM_GOODS_RECEIPT_V1",
        "target_table":        "MKPF",
    },
    "RFQ": {
        "csv_columns":         ["EBELN", "BSART", "EKORG", "LIFNR", "AEDAT"],
        "mandatory":           ["EBELN", "BSART"],
        "template":            "MC_MM_RFQ_V1",
        "target_table":        "EKKO",
    },
    "SubcontractingPO": {
        "csv_columns":         ["EBELN", "BSART", "LIFNR", "MATNR", "MENGE"],
        "mandatory":           ["EBELN", "BSART"],
        "template":            "MC_MM_SUBCONTRACT_PO_V1",
        "target_table":        "EKKO",
    },
    "StockTransferOrder": {
        "csv_columns":         ["EBELN", "BSART", "RESWK", "WERKS", "MATNR"],
        "mandatory":           ["EBELN", "BSART"],
        "template":            "MC_MM_STO_V1",
        "target_table":        "EKKO",
    },
    "VendorEvaluation": {
        "csv_columns":         ["EKORG", "LIFNR", "BUKRS", "KRITERION"],
        "mandatory":           ["EKORG", "LIFNR"],
        "template":            "MC_MM_VENDOR_EVALUATION_V1",
        "target_table":        "ELBK",
    },

    # ── PP / Manufacturing ────────────────────────────────────────────────────
    "ProductionOrder": {
        "csv_columns":         ["AUFNR", "AUART", "WERKS", "MATNR", "GAMNG"],
        "mandatory":           ["AUFNR", "AUART", "WERKS"],
        "template":            "MC_PP_PRODUCTION_ORDER_V1",
        "target_table":        "AUFK",
    },
    "ProcessOrder": {
        "csv_columns":         ["AUFNR", "AUART", "WERKS", "MATNR", "GAMNG"],
        "mandatory":           ["AUFNR", "AUART", "WERKS"],
        "template":            "MC_PP_PROCESS_ORDER_V1",
        "target_table":        "AUFK",
    },
    "ProductionVersion": {
        "csv_columns":         ["MATNR", "WERKS", "VERID", "STLAL", "PLNTY"],
        "mandatory":           ["MATNR", "WERKS", "VERID"],
        "template":            "MC_PP_PRODUCTION_VERSION_V1",
        "target_table":        "MKAL",
    },
    "MasterRecipe": {
        "csv_columns":         ["PLNTY", "PLNNR", "PLNAL", "WERKS", "MATNR"],
        "mandatory":           ["PLNTY", "PLNNR", "WERKS"],
        "template":            "MC_PP_MASTER_RECIPE_V1",
        "target_table":        "PLKO",
    },
    "RecipeFormula": {
        "csv_columns":         ["PLNNR", "PLNAL", "MATNR", "MENGE", "MEINS"],
        "mandatory":           ["PLNNR", "MATNR"],
        "template":            "MC_PP_RECIPE_FORMULA_V1",
        "target_table":        "PLPO",
    },
    "Resource": {
        "csv_columns":         ["WERKS", "RESOURCE", "TXT", "USAGE_CAT"],
        "mandatory":           ["WERKS", "RESOURCE"],
        "template":            "MC_PP_RESOURCE_V1",
        "target_table":        "CRHD",
    },
    "PlanningStrategy": {
        "csv_columns":         ["WERKS", "STRGR", "TXT"],
        "mandatory":           ["WERKS", "STRGR"],
        "template":            "MC_PP_PLANNING_STRATEGY_V1",
        "target_table":        "T438A",
    },
    "MRPArea": {
        "csv_columns":         ["WERKS", "BERID", "TXT", "BERTY"],
        "mandatory":           ["WERKS", "BERID"],
        "template":            "MC_PP_MRP_AREA_V1",
        "target_table":        "T001W",
    },
    "ForecastProfile": {
        "csv_columns":         ["MATNR", "WERKS", "PROFL", "STRAT"],
        "mandatory":           ["MATNR", "WERKS", "PROFL"],
        "template":            "MC_PP_FORECAST_PROFILE_V1",
        "target_table":        "MPOP",
    },

    # ── PM (Plant Maintenance) ────────────────────────────────────────────────
    "MaintenancePlan": {
        "csv_columns":         ["WARPL", "MPTYP", "STRAT", "WERKS"],
        "mandatory":           ["WARPL", "MPTYP"],
        "template":            "MC_PM_MAINTENANCE_PLAN_V1",
        "target_table":        "MPLA",
    },
    "MaintenanceItem": {
        "csv_columns":         ["WAPOS", "WARPL", "ANLZU", "TPLNR", "EQUNR"],
        "mandatory":           ["WAPOS", "WARPL"],
        "template":            "MC_PM_MAINTENANCE_ITEM_V1",
        "target_table":        "MPOS",
    },
    "MeasurementPoint": {
        "csv_columns":         ["POINT", "MPOBJ", "PSORT", "MRMIN"],
        "mandatory":           ["POINT"],
        "template":            "MC_PM_MEAS_POINT_V1",
        "target_table":        "IMPT",
    },
    "MeasurementDocument": {
        "csv_columns":         ["MDOCM", "POINT", "RECDV", "IDATE"],
        "mandatory":           ["MDOCM", "POINT"],
        "template":            "MC_PM_MEAS_DOCUMENT_V1",
        "target_table":        "IMRG",
    },
    "WorkPermit": {
        "csv_columns":         ["WORKPERMIT", "TXT", "WERKS"],
        "mandatory":           ["WORKPERMIT"],
        "template":            "MC_PM_WORK_PERMIT_V1",
        "target_table":        "PMSV_PERMIT",
    },
    "Notification": {
        "csv_columns":         ["QMNUM", "QMART", "WERKS", "EQUNR"],
        "mandatory":           ["QMNUM", "QMART"],
        "template":            "MC_PM_NOTIFICATION_V1",
        "target_table":        "QMEL",
    },
    "WarrantyClaim": {
        "csv_columns":         ["CLAIMNO", "MATNR", "EQUNR", "WERKS"],
        "mandatory":           ["CLAIMNO"],
        "template":            "MC_PM_WARRANTY_CLAIM_V1",
        "target_table":        "WTY_CLAIM",
    },

    # ── QM (Quality Management) ───────────────────────────────────────────────
    "ControlPlan": {
        "csv_columns":         ["PLNNR", "PLNAL", "WERKS", "MATNR"],
        "mandatory":           ["PLNNR", "WERKS"],
        "template":            "MC_QM_CONTROL_PLAN_V1",
        "target_table":        "PLKO",
    },
    "SamplingProcedure": {
        "csv_columns":         ["VPLAN", "BPRFP", "TXT", "WERKS"],
        "mandatory":           ["VPLAN"],
        "template":            "MC_QM_SAMPLING_PROCEDURE_V1",
        "target_table":        "QPVE",
    },
    "CatalogCode": {
        "csv_columns":         ["KATALOGART", "AUSWAHLMG", "CODEGR", "CODE"],
        "mandatory":           ["KATALOGART", "CODEGR"],
        "template":            "MC_QM_CATALOG_CODE_V1",
        "target_table":        "QPCD",
    },
    "QualityCertificate": {
        "csv_columns":         ["MATNR", "WERKS", "ZEUGNISART", "STATUS"],
        "mandatory":           ["MATNR", "WERKS"],
        "template":            "MC_QM_QUALITY_CERTIFICATE_V1",
        "target_table":        "QCERT",
    },
    "CertificateProfile": {
        "csv_columns":         ["ZEUGNISART", "MATNR", "PRFKZ"],
        "mandatory":           ["ZEUGNISART"],
        "template":            "MC_QM_CERTIFICATE_PROFILE_V1",
        "target_table":        "QCEPP",
    },
    "InspectionType": {
        "csv_columns":         ["ART", "TXT"],
        "mandatory":           ["ART"],
        "template":            "MC_QM_INSPECTION_TYPE_V1",
        "target_table":        "T370U",
    },
    "Calibration": {
        "csv_columns":         ["CALNUM", "EQUNR", "MATNR", "WERKS"],
        "mandatory":           ["CALNUM", "EQUNR"],
        "template":            "MC_QM_CALIBRATION_V1",
        "target_table":        "QCRT",
    },

    # ── Project System (PS) extensions ────────────────────────────────────────
    "NetworkActivity": {
        "csv_columns":         ["AUFNR", "VORNR", "TXT", "VGW01", "AUFMG"],
        "mandatory":           ["AUFNR", "VORNR"],
        "template":            "MC_PS_NETWORK_ACTIVITY_V1",
        "target_table":        "AFVC",
    },
    "Milestone": {
        "csv_columns":         ["MLST", "PSPID", "POSID", "BEZEICH"],
        "mandatory":           ["MLST"],
        "template":            "MC_PS_MILESTONE_V1",
        "target_table":        "MLST",
    },
    "ProjectStock": {
        "csv_columns":         ["PSPID", "POSID", "MATNR", "LABST"],
        "mandatory":           ["PSPID", "MATNR"],
        "template":            "MC_PS_PROJECT_STOCK_V1",
        "target_table":        "MARD",
    },
    "SettlementRule": {
        "csv_columns":         ["KOKRS", "OBJNR", "PERBZ", "PRZNT", "EMPGE"],
        "mandatory":           ["OBJNR", "EMPGE"],
        "template":            "MC_CO_SETTLEMENT_RULE_V1",
        "target_table":        "COBRA",
    },

    # ── HR extensions ─────────────────────────────────────────────────────────
    "Job": {
        "csv_columns":         ["STELL", "STEXT", "BEGDA", "ENDDA"],
        "mandatory":           ["STELL"],
        "template":            "MC_HR_JOB_V1",
        "target_table":        "HRP1000",
    },
    "PersonalArea": {
        "csv_columns":         ["WERKS", "NAME", "TXT", "MOLGA"],
        "mandatory":           ["WERKS"],
        "template":            "MC_HR_PERSONAL_AREA_V1",
        "target_table":        "T500P",
    },
    "PersonalSubArea": {
        "csv_columns":         ["WERKS", "BTRTL", "TXT"],
        "mandatory":           ["WERKS", "BTRTL"],
        "template":            "MC_HR_PERSONAL_SUBAREA_V1",
        "target_table":        "T001P",
    },
    "ActionType": {
        "csv_columns":         ["MASSN", "TXT", "ANSAL", "REASN"],
        "mandatory":           ["MASSN"],
        "template":            "MC_HR_ACTION_TYPE_V1",
        "target_table":        "T529A",
    },
    "AbsenceType": {
        "csv_columns":         ["MOABW", "AWART", "TXT"],
        "mandatory":           ["AWART"],
        "template":            "MC_HR_ABSENCE_TYPE_V1",
        "target_table":        "T554S",
    },
    "TimeQuotaType": {
        "csv_columns":         ["KTART", "TXT", "ZWNOR"],
        "mandatory":           ["KTART"],
        "template":            "MC_HR_TIME_QUOTA_V1",
        "target_table":        "T556A",
    },
    "PayrollSchema": {
        "csv_columns":         ["SCHEMA", "TXT", "MOLGA"],
        "mandatory":           ["SCHEMA"],
        "template":            "MC_HR_PAYROLL_SCHEMA_V1",
        "target_table":        "T52C0",
    },

    # ── Customizing / Master Data Operations ──────────────────────────────────
    "Address": {
        "csv_columns":         ["ADDRNUMBER", "NAME1", "STREET", "CITY1", "COUNTRY"],
        "mandatory":           ["ADDRNUMBER"],
        "template":            "MC_BC_ADDRESS_V1",
        "target_table":        "ADRC",
    },
    "NumberRangeObject": {
        "csv_columns":         ["OBJECT", "NRRANGENR", "FROMNUMBER", "TONUMBER"],
        "mandatory":           ["OBJECT", "NRRANGENR"],
        "template":            "MC_BC_NUMBER_RANGE_V1",
        "target_table":        "NRIV",
    },
    "FactoryCalendar": {
        "csv_columns":         ["FCALID", "TXT", "WKMASK", "PUBLIC_HOLIDAY"],
        "mandatory":           ["FCALID"],
        "template":            "MC_BC_FACTORY_CALENDAR_V1",
        "target_table":        "TFACD",
    },
    "PublicHolidayCalendar": {
        "csv_columns":         ["HOLIDAY_CAL", "TXT", "COUNTRY"],
        "mandatory":           ["HOLIDAY_CAL"],
        "template":            "MC_BC_PUBLIC_HOLIDAY_V1",
        "target_table":        "TFACS",
    },
    "Currency": {
        "csv_columns":         ["WAERS", "TXT", "DECAN", "ISOCODE"],
        "mandatory":           ["WAERS"],
        "template":            "MC_BC_CURRENCY_V1",
        "target_table":        "TCURC",
    },
    "Country": {
        "csv_columns":         ["LAND1", "TXT", "INTCA3", "WAERS"],
        "mandatory":           ["LAND1"],
        "template":            "MC_BC_COUNTRY_V1",
        "target_table":        "T005",
    },
    "Region": {
        "csv_columns":         ["LAND1", "REGIO", "TXT"],
        "mandatory":           ["LAND1", "REGIO"],
        "template":            "MC_BC_REGION_V1",
        "target_table":        "T005S",
    },
    "Language": {
        "csv_columns":         ["SPRAS", "TXT", "ISOCODE"],
        "mandatory":           ["SPRAS"],
        "template":            "MC_BC_LANGUAGE_V1",
        "target_table":        "T002",
    },
    "TimeZone": {
        "csv_columns":         ["TZONE", "TXT", "DST_RULE"],
        "mandatory":           ["TZONE"],
        "template":            "MC_BC_TIMEZONE_V1",
        "target_table":        "TTZZ",
    },
    "PaymentTerms": {
        "csv_columns":         ["ZTERM", "TXT", "ZTAG1", "ZBD1T"],
        "mandatory":           ["ZTERM"],
        "template":            "MC_FI_PAYMENT_TERMS_V1",
        "target_table":        "T052",
    },
    "TaxCode": {
        "csv_columns":         ["KALSM", "MWSKZ", "TXT", "KSCHL"],
        "mandatory":           ["MWSKZ"],
        "template":            "MC_FI_TAX_CODE_V1",
        "target_table":        "T007A",
    },
    "DunningProcedure": {
        "csv_columns":         ["MAHNS", "TXT", "GLTRX"],
        "mandatory":           ["MAHNS"],
        "template":            "MC_FI_DUNNING_PROCEDURE_V1",
        "target_table":        "T040",
    },
    "ApprovalGroup": {
        "csv_columns":         ["FRGGR", "TXT"],
        "mandatory":           ["FRGGR"],
        "template":            "MC_BC_APPROVAL_GROUP_V1",
        "target_table":        "T16FK",
    },
    "AuthorizationGroup": {
        "csv_columns":         ["BRGRU", "TXT"],
        "mandatory":           ["BRGRU"],
        "template":            "MC_BC_AUTHORIZATION_GROUP_V1",
        "target_table":        "T024B",
    },
    "Calendar": {
        "csv_columns":         ["ID_CALENDAR", "TXT", "CALENDAR_USAGE"],
        "mandatory":           ["ID_CALENDAR"],
        "template":            "MC_BC_CALENDAR_V1",
        "target_table":        "SCHOL",
    },
}


def _make_mc_file_class(obj_name: str, spec: dict):
    """Factory for a MigrationCockpitFile spine subclass per object_type.

    The subclass:
      * registers itself under object_type
      * implements build_payload to ASSEMBLE a CSV record (no BAPI call)
      * implements call_bapi as a NO-BAPI passthrough that just records the
        row was queued -- actual upload happens at end-of-run via flush()
        triggered by the lambda handler
    """
    _source_key = spec["mandatory"][0] if spec["mandatory"] else spec["csv_columns"][0]

    class _MCFileSpine(BaseSpineOrchestrator):
        object_type           = obj_name
        source_key_field      = _source_key
        extension_structure   = ""    # MC file lane doesn't use BAPI EXTENSIONIN
        fk_fields: dict       = {}

        # Buffer of accumulated rows -- flushed at end of run
        _row_buffer: list = []

        def validate(self, row: dict) -> Optional[str]:
            missing = [c for c in spec["mandatory"]
                        if not (row.get(c) or "").strip()]
            if missing:
                return f"mandatory columns missing: {','.join(missing)}"
            return None

        def build_payload(self, row: dict, ext_rows: list) -> dict:
            # Project the source row onto the MC template's column set
            record = {c: (row.get(c) or "") for c in spec["csv_columns"]}
            # Z columns passed through as a JSON sidecar (the upload step
            # may map them via the MC customizing extension layer)
            customs = {k: v for k, v in row.items()
                        if k and not k.startswith("_")
                        and any(k.startswith(p) for p in ("ZZ", "YY", "CI_", "Z_", "Y_"))}
            return {"record": record, "customs": customs, "_src": record[self.source_key_field]}

        def call_bapi(self, payload: dict) -> tuple:
            src = payload.pop("_src", "")
            record = payload["record"]
            customs = payload["customs"]
            # Append to buffer; the actual S3 write happens at flush time
            self._row_buffer.append({"record": record, "customs": customs})
            vk = {"table": spec["target_table"],
                  "key":   {self.source_key_field: src}}
            return src, [f"queued for MC template {spec['template']}"], DISP_CREATED, vk

        @classmethod
        def flush_to_s3(cls, s3_client, bucket: str, run_id: str,
                         tenant_slug: str = "default") -> dict:
            """Write the accumulated buffer to S3 as CSV under the customer's
            staging path. Returns the S3 URI + row count + any sidecar
            blob written for custom Z columns."""
            if not cls._row_buffer:
                return {"object": cls.object_type, "rows": 0, "uri": None}
            # Main CSV
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=spec["csv_columns"])
            w.writeheader()
            for r in cls._row_buffer:
                w.writerow(r["record"])
            csv_key = (f"tenants/{tenant_slug}/runs/{run_id}/mc_file/"
                        f"{cls.object_type}.csv")
            s3_client.put_object(Bucket=bucket, Key=csv_key,
                                  Body=buf.getvalue().encode("utf-8"),
                                  ContentType="text/csv")
            # Custom Z column sidecar (optional)
            customs_present = any(r["customs"] for r in cls._row_buffer)
            customs_key = None
            if customs_present:
                sidecar = [{"key": r["record"].get(cls.source_key_field),
                             "customs": r["customs"]}
                            for r in cls._row_buffer if r["customs"]]
                customs_key = (f"tenants/{tenant_slug}/runs/{run_id}/mc_file/"
                                f"{cls.object_type}.customs.json")
                s3_client.put_object(Bucket=bucket, Key=customs_key,
                                      Body=json.dumps(sidecar, indent=2).encode("utf-8"),
                                      ContentType="application/json")
            result = {
                "object":     cls.object_type,
                "template":   spec["template"],
                "rows":       len(cls._row_buffer),
                "uri":        f"s3://{bucket}/{csv_key}",
                "customs_uri": (f"s3://{bucket}/{customs_key}" if customs_key else None),
                "target_table": spec["target_table"],
            }
            cls._row_buffer = []   # reset for next run
            return result

    _MCFileSpine.__name__ = f"MCFile_{obj_name}"
    return _MCFileSpine


# Register all MC file objects at import time. We keep a direct handle to
# each MC factory class in _MC_CLASSES so callers (like the scale-probe
# handler) can flush without depending on _SPINE_REGISTRY ordering — the
# scaffolder-generated BAPI spine for the same object_type may register
# later and shadow the MC class in the shared registry.
_REGISTERED_MC_OBJECTS = []
_MC_CLASSES: dict = {}
for _obj, _spec in MC_TEMPLATES.items():
    _cls = _make_mc_file_class(_obj, _spec)
    register_spine(_cls)
    _REGISTERED_MC_OBJECTS.append(_obj)
    _MC_CLASSES[_obj] = _cls


def get_mc_class(object_type: str):
    """Return the MC factory class for object_type, bypassing the shared
    spine registry (which the scaffolder-generated BAPI spine may shadow)."""
    return _MC_CLASSES.get(object_type)


def flush_all(s3_client, bucket: str, run_id: str, tenant_slug: str = "default",
              target_conn=None, project_id: str = "", auto_trigger: bool = False,
              wait_for_complete: bool = False, timeout_secs: int = 600) -> list:
    """Flush every MC-file pseudo-spine that has accumulated rows. Returns a
    list of per-object results (uri + row count + template name).

    When ``auto_trigger=True`` and ``target_conn`` is provided, each
    successful S3 flush is immediately followed by a Migration Cockpit
    job trigger on S/4 via :func:`mc_job_trigger.trigger_mc_load`. This
    turns the MC lane into a fire-and-forget pipeline equivalent to the
    BAPI lane — no human MC operator required.

    Each result dict gains a ``trigger`` sub-dict when auto_trigger is on:
      {"mechanism": "...", "job_id": "...", "status": "DONE"/"FAILED"/...,
       "rows_loaded": N, "log_lines": [...], "errors": [...]}
    """
    # Use the direct MC-class handle, NOT the shared spine registry —
    # scaffolder-generated BAPI spines for the same object_type may have
    # registered later and shadowed the MC class in _SPINE_REGISTRY.
    results = []
    for obj in _REGISTERED_MC_OBJECTS:
        cls = _MC_CLASSES.get(obj)
        if cls is None:
            continue
        r = cls.flush_to_s3(s3_client, bucket, run_id, tenant_slug)
        if r["rows"] > 0:
            if auto_trigger and target_conn is not None and project_id:
                from mc_job_trigger import trigger_mc_load
                r["trigger"] = trigger_mc_load(
                    target_conn       = target_conn,
                    project_id        = project_id,
                    object_id         = obj,
                    file_s3_uri       = r["uri"],
                    correlation_id    = run_id,
                    wait_for_complete = wait_for_complete,
                    timeout_secs      = timeout_secs,
                )
            results.append(r)
    return results


def registered_objects() -> list:
    """Roll-call of MC-file-lane objects on the spine registry."""
    return list(_REGISTERED_MC_OBJECTS)
