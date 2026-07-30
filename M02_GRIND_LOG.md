# M02 Grind Log — breadth coverage across all migration areas

_Generated 2026-07-30 from `catalog/grind_results.json` (project M02_FULL, all 230 objects staged in Fiori). One-shot `grind.py` pass._

**Legend:** 📥 staged (rows written+verified) · ◻️ built empty (needs source filter) · 🔧 needs alias/source fix · map = auto-mapped columns (thin maps = key only, pending field mapping refinement).

**52 objects staged** across 14 functional areas (of 56 attempted; industry objects — EHS, oil&gas, JVA, treasury, HCM — omitted: no source data in the ECC).

## Classification
| Object | Source | Map cols | Verified | Status |
|---|---|---:|---:|---|
| Z_CHARACT_M02 | CABN | 21 | 0 | ◻️ staged-empty |
| Z_CLASS_2_M02 | KLAH | 25 | 20 | 📥 staged |

## DMS
| Object | Source | Map cols | Verified | Status |
|---|---|---:|---:|---|
| Z_DOCU_INFOREC_M02 | DRAW | 4 | 20 | 📥 staged |

## FI/CO
| Object | Source | Map cols | Verified | Status |
|---|---|---:|---:|---|
| Z_BANK_2_M02 | BNKA | 11 | 20 | 📥 staged |
| Z_CO_BUS_PROC_M02 | CBPR | 2 | 20 | 📥 staged |
| Z_EXCH_RATE_M02 | TCURR | 3 | 11 | 📥 staged |
| Z_GL_ACCOUNT_3_M02 | SKA1 | 7 | 20 | 📥 staged |
| Z_GL_ACC_EXT_M02 | SKA1 | 2 | 20 | 📥 staged |
| Z_INTORDER_2_M02 | AUFK | 33 | 1 | 📥 staged |
| Z_KOSTL_MASTER_M02 | CSKS | 52 | 20 | 📥 staged |
| Z_LSTAR_CREATE_M02 | CSLA | 16 | 20 | 📥 staged |
| Z_PRCTR_MSTR2_M02 | CEPC | 33 | 20 | 📥 staged |

## FI/CO (assets)
| Object | Source | Map cols | Verified | Status |
|---|---|---:|---:|---|
| Z_FIXED_ASSET_M02 | ANLA | 9 | 20 | 📥 staged |

## FI/CO (balances)
| Object | Source | Map cols | Verified | Status |
|---|---|---:|---:|---|
| Z_GL_BALANCE_M02 | BSIS | 17 | 2 | 📥 staged |

## FI/CO (open items)
| Object | Source | Map cols | Verified | Status |
|---|---|---:|---:|---|
| Z_OPEN_ITEM_AP_M02 | BSIK | 41 | 9 | 📥 staged |
| Z_OPEN_ITEM_AR_M02 | BSID | 42 | 8 | 📥 staged |

## MM
| Object | Source | Map cols | Verified | Status |
|---|---|---:|---:|---|
| Z_BATCHES_M02 | MCH1 | 15 | 10 | 📥 staged |
| Z_BATCHES_PLANT_M02 | MCH1 | 15 | 10 | 📥 staged |
| Z_CONTRACTS_M02 | EKKO | 19 | 1 | 📥 staged |
| Z_PURCH_INF_V2_M02 | EINA | 25 | 20 | 📥 staged |
| Z_PUR_INF_E_V2_M02 | EINA | 4 | 20 | 📥 staged |
| Z_PUR_ORDER_2_M02 | EKKO | 22 | 20 | 📥 staged |
| Z_RFM_MC_M02 | T023 | 1 | 20 | 📥 staged |
| Z_SCHED_AGRMNT_M02 | EKKO | 19 | 20 | 📥 staged |
| Z_SOURCE_LIST_M02 | EORD | 13 | 20 | 📥 staged |

## Other
| Object | Source | Map cols | Verified | Status |
|---|---|---:|---:|---|
| Z_INVENTORY_2_M02 | MKPF | 4 | 19 | 📥 staged |

## PM
| Object | Source | Map cols | Verified | Status |
|---|---|---:|---:|---|
| Z_EQUIPMENT_2_M02 | EQUI | 22 | 20 | 📥 staged |
| Z_FUNC_LOC_2_M02 | IFLOT | 28 | 1 | 📥 staged |
| Z_MAINT_ITEM_M02 | MPOS | 21 | 20 | 📥 staged |
| Z_MAINT_PLAN_3_M02 | MPLA | 21 | 0 | ◻️ staged-empty |

## PP
| Object | Source | Map cols | Verified | Status |
|---|---|---:|---:|---|
| Z_BOM_3_M02 | STKO | 7 | 1 | 📥 staged |
| Z_BOM_M02 | STKO | 7 | 1 | 📥 staged |
| Z_PP_PSA_M02 | PVBE | 11 | 18 | 📥 staged |
| Z_PRODUCT_VER_M02 | MKAL | 24 | 20 | 📥 staged |
| Z_ROUTING_M02 | PLKO | 2 | 20 | 📥 staged |
| Z_WORK_CNTR_M02 | CRHD | 69 | 19 | 📥 staged |

## PS
| Object | Source | Map cols | Verified | Status |
|---|---|---:|---:|---|
| Z_PS_PROJECT_M02 | PROJ | 1 | 1 | 📥 staged |
| Z_WBS_ELEMENT_M02 | PRPS | 0 | - | 🔧 no-automap |

## Product/Material
| Object | Source | Map cols | Verified | Status |
|---|---|---:|---:|---|
| Z_MAT_CONSUMP_M02 | MARA | 1 | 20 | 📥 staged |
| Z_PROD_CONSUMP_M02 | MARA | 1 | 20 | 📥 staged |
| Z_PROD_EXT_2_M02 | MAKT | 1 | 3 | 📥 staged |
| Z_PROD_LONGTXT_M02 | MARA | 1 | 20 | 📥 staged |
| Z_PROD_SERV_M02 | MAKT | 3 | 3 | 📥 staged |

## QM
| Object | Source | Map cols | Verified | Status |
|---|---|---:|---:|---|
| Z_INSP_METHOD_M02 | QMTB | 5 | 20 | 📥 staged |
| Z_MSTR_CHAR_M02 | QPMK | 15 | 0 | ◻️ staged-empty |
| Z_QM_CATALOG_M02 | QPGR | 3 | 20 | 📥 staged |
| Z_QM_QINF_2_M02 | QINF | 14 | 20 | 📥 staged |
| Z_SELECTED_SET_M02 | QPAM | 6 | 13 | 📥 staged |
| Z_SELSET_CODE_M02 | QPAC | 7 | 20 | 📥 staged |

## SD
| Object | Source | Map cols | Verified | Status |
|---|---|---:|---:|---|
| Z_CONDITIONS_M02 | KONH | 7 | 20 | 📥 staged |
| Z_CUSTMAT_INF_M02 | KNMT | 1 | 20 | 📥 staged |
| Z_MM_CONDITION_M02 | KONH | 4 | 20 | 📥 staged |
| Z_SD_CONDITION_M02 | KONH | 4 | 20 | 📥 staged |
| Z_SD_CONTRACT_M02 | VBAK | 20 | 20 | 📥 staged |
| Z_SD_SCHED_AGR_M02 | VBAK | 7 | 20 | 📥 staged |
| Z_SLS_ORDER_2_M02 | VBAK | 18 | 20 | 📥 staged |
