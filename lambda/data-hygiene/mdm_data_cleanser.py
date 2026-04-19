"""
mdm_data_cleanser.py - Master Data Management (MDM) Data Hygiene Engine
Cleanses common SAP ERP source inconsistencies before S/4HANA migration.
Works in the early planning phase ahead of standard AWS DMS execution.
"""
import logging
from typing import List, Dict, Any

logger = logging.getLogger("mdm_data_cleanser")
logger.setLevel(logging.INFO)

def cleanse_finance_dates(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    In ECC, uninitialized dates are often stored as "00000000".
    S/4HANA strictly prefers proper NULLs to prevent ABAP dump crashes.
    """
    cleansed = dict(record)
    date_fields = ['BUDAT', 'BLDAT', 'CPUDT', 'ZFBDT']
    
    for field in date_fields:
        if field in cleansed and cleansed[field] in ["00000000", "        ", ""]:
            cleansed[field] = None
            
    return cleansed

def strip_material_leading_zeros(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Strips leading Zeros from standard 18/40 char MATNR unless they are 
    meaningful to the lexical structure (e.g. configuring output schemas).
    """
    cleansed = dict(record)
    if 'MATNR' in cleansed and type(cleansed['MATNR']) == str:
        # Example logic: lstrip zeros but leave at least one if wholly zero
        try:
             stripped = cleansed['MATNR'].lstrip('0')
             cleansed['MATNR'] = stripped if stripped else '0'
        except Exception:
            pass
    return cleansed

def execute_cleaning_batch(records: List[Dict[str, Any]], table_name: str) -> List[Dict[str, Any]]:
    """Runs data through applicable cleaning filters based on source table"""
    results = []
    for rec in records:
        if table_name in ['BKPF', 'BSEG', 'BSID', 'BSIK']:
            rec = cleanse_finance_dates(rec)
        elif table_name in ['MARA', 'MARC', 'MARD']:
            rec = strip_material_leading_zeros(rec)
        
        results.append(rec)
    
    logger.info(f"Cleansed batch of {len(records)} records for table {table_name}")
    return results
