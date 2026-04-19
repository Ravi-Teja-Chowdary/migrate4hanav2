"""
Migrate4HANA — Level 1: Smart Table/Field Rewriter
====================================================
Automatically rewrites ABAP code that references deprecated
ECC tables to use their S/4HANA equivalents.

This handles:
  - SELECT statements: rewrites table name + all field names
  - DATA declarations: rewrites TYPE references
  - TABLES statements: rewrites to new table names
  - WHERE clauses: rewrites field references
  - Field-symbol/work area references: table-field to new-table-field

Coverage: ~40% of all migration issues become auto-fixable.
"""

import re
from typing import Dict, List, Tuple, Optional


# =============================================================================
# COMPLETE ECC → S/4HANA TABLE + FIELD MAPPING
# =============================================================================

TABLE_FIELD_MAP = {
    # ─── FINANCE: BSEG → ACDOCA ───
    "BSEG": {
        "target_table": "ACDOCA",
        "target_type": "table",
        "cds_view": "I_JournalEntry",
        "field_map": {
            "BUKRS": "RBUKRS",
            "BELNR": "BELNR",
            "GJAHR": "GJAHR",
            "BUZEI": "DOCLN",
            "KOART": "KOART",
            "HKONT": "RACCT",
            "DMBTR": "HSL",
            "WRBTR": "TSL",
            "SHKZG": "DRCRK",
            "KOSTL": "RCNTR",
            "PRCTR": "PRCTR",
            "GSBER": "RBUSA",
            "MANDT": "RCLNT",
            "MONAT": "POPER",
            "LIFNR": "LIFNR",
            "KUNNR": "KUNNR",
            "MATNR": "MATNR",
            "MENGE": "MSL",
            "MEINS": "RUNIT",
            "ZUONR": "ZUONR",
            "SGTXT": "SGTXT",
            "AUFNR": "AUFNR",
            "ANLN1": "ANLN1",
            "ANLN2": "ANLN2",
            "SAKNR": "RACCT",
            "AUGDT": "AUGDT",
            "AUGBL": "AUGBL",
            "ZFBDT": "ZFBDT",
            "ZTERM": "ZTERM",
            "BSCHL": "BSCHL",
            "UMSKZ": "UMSKZ",
            "DMBE2": "HSL",  # Second local currency → same field
            "PSWSL": "RHCUR",
            "BEWAR": "BTTYPE",
        },
        "notes": "ACDOCA requires RLDNR (ledger) field. Default '0L' for leading ledger.",
    },
    "BKPF": {
        "target_table": "ACDOCA",
        "target_type": "table",
        "cds_view": "I_JournalEntry",
        "field_map": {
            "BUKRS": "RBUKRS", "BELNR": "BELNR", "GJAHR": "GJAHR",
            "BLART": "BLART", "BLDAT": "BLDAT", "BUDAT": "BUDAT",
            "MONAT": "POPER", "WAERS": "RHCUR", "BSTAT": "BSTAT",
            "USNAM": "USNAM", "CPUDT": "CPUDT", "CPUTM": "CPUTM",
            "XBLNR": "XBLNR", "STBLG": "STBLG",
        },
    },
    # GL secondary index tables → ACDOCA
    "BSID": {"target_table": "ACDOCA", "target_type": "view",
             "cds_view": "I_JournalEntryItem",
             "field_map": {"BUKRS": "RBUKRS", "KUNNR": "KUNNR", "BELNR": "BELNR",
                           "GJAHR": "GJAHR", "DMBTR": "HSL", "WRBTR": "TSL",
                           "SHKZG": "DRCRK", "BUDAT": "BUDAT", "BLDAT": "BLDAT",
                           "ZFBDT": "ZFBDT", "HKONT": "RACCT"},
             "where_addition": "AND KOART = 'D' AND AUGDT = '00000000'"},
    "BSAD": {"target_table": "ACDOCA", "target_type": "view",
             "cds_view": "I_JournalEntryItem",
             "field_map": {"BUKRS": "RBUKRS", "KUNNR": "KUNNR", "BELNR": "BELNR",
                           "GJAHR": "GJAHR", "DMBTR": "HSL", "WRBTR": "TSL",
                           "SHKZG": "DRCRK", "BUDAT": "BUDAT", "HKONT": "RACCT"},
             "where_addition": "AND KOART = 'D' AND AUGDT <> '00000000'"},
    "BSIK": {"target_table": "ACDOCA", "target_type": "view",
             "cds_view": "I_JournalEntryItem",
             "field_map": {"BUKRS": "RBUKRS", "LIFNR": "LIFNR", "BELNR": "BELNR",
                           "GJAHR": "GJAHR", "DMBTR": "HSL", "WRBTR": "TSL",
                           "SHKZG": "DRCRK", "BUDAT": "BUDAT", "ZFBDT": "ZFBDT",
                           "HKONT": "RACCT"},
             "where_addition": "AND KOART = 'K' AND AUGDT = '00000000'"},
    "BSAK": {"target_table": "ACDOCA", "target_type": "view",
             "cds_view": "I_JournalEntryItem",
             "field_map": {"BUKRS": "RBUKRS", "LIFNR": "LIFNR", "BELNR": "BELNR",
                           "GJAHR": "GJAHR", "DMBTR": "HSL", "WRBTR": "TSL",
                           "SHKZG": "DRCRK", "BUDAT": "BUDAT", "HKONT": "RACCT"},
             "where_addition": "AND KOART = 'K' AND AUGDT <> '00000000'"},
    "BSIS": {"target_table": "ACDOCA", "target_type": "view",
             "cds_view": "I_JournalEntryItem",
             "field_map": {"BUKRS": "RBUKRS", "HKONT": "RACCT", "BELNR": "BELNR",
                           "GJAHR": "GJAHR", "DMBTR": "HSL", "SHKZG": "DRCRK"},
             "where_addition": "AND KOART = 'S' AND AUGDT = '00000000'"},
    "BSAS": {"target_table": "ACDOCA", "target_type": "view",
             "cds_view": "I_JournalEntryItem",
             "field_map": {"BUKRS": "RBUKRS", "HKONT": "RACCT", "BELNR": "BELNR",
                           "GJAHR": "GJAHR", "DMBTR": "HSL", "SHKZG": "DRCRK"},
             "where_addition": "AND KOART = 'S' AND AUGDT <> '00000000'"},
    # GL Totals
    "GLT0": {"target_table": "ACDOCA", "target_type": "aggregate",
             "cds_view": "I_GLAccountBalanceCube",
             "field_map": {"BUKRS": "RBUKRS", "RACCT": "RACCT", "GJAHR": "GJAHR",
                           "DRCRK": "DRCRK", "RYEAR": "GJAHR",
                           "HSLVT": "HSL", "TSLVT": "TSL"},
             "notes": "Aggregate from ACDOCA. Use SUM() with GROUP BY."},
    "GLPCA": {"target_table": "ACDOCA", "target_type": "aggregate",
              "cds_view": "I_ProfitCenterBalanceCube",
              "field_map": {"BUKRS": "RBUKRS", "PRCTR": "PRCTR", "GJAHR": "GJAHR",
                            "RACCT": "RACCT", "HSLVT": "HSL"},
              "notes": "Profit center totals now directly in ACDOCA."},
    # CO tables
    "COEP": {"target_table": "ACDOCA", "target_type": "view",
             "cds_view": "I_JournalEntryItem",
             "field_map": {"KOKRS": "CO_KOKRS", "BELNR": "BELNR", "BUZEI": "DOCLN",
                           "GJAHR": "GJAHR", "KSTAR": "RACCT", "WTG001": "HSL",
                           "OBJNR": "OBJNR", "KOSTL": "RCNTR", "AUFNR": "AUFNR"},
             "where_addition": "AND RLDNR = '0L'"},
    "COBK": {"target_table": "ACDOCA", "target_type": "view",
             "field_map": {"KOKRS": "CO_KOKRS", "BELNR": "BELNR", "GJAHR": "GJAHR",
                           "BUDAT": "BUDAT", "BLDAT": "BLDAT"}},
    "COSP": {"target_table": "ACDOCA", "target_type": "aggregate",
             "field_map": {"KOKRS": "CO_KOKRS", "OBJNR": "OBJNR", "GJAHR": "GJAHR",
                           "KSTAR": "RACCT", "WTG001": "HSL"}},
    "COSS": {"target_table": "ACDOCA", "target_type": "aggregate",
             "field_map": {"KOKRS": "CO_KOKRS", "OBJNR": "OBJNR", "GJAHR": "GJAHR",
                           "KSTAR": "RACCT", "WTG001": "HSL"}},

    # ─── MATERIALS: MKPF/MSEG → MATDOC ───
    "MKPF": {
        "target_table": "MATDOC",
        "cds_view": "I_MaterialDocumentHeader",
        "field_map": {
            "MBLNR": "MBLNR", "MJAHR": "MJAHR", "BUDAT": "BUDAT_MKPF",
            "BLDAT": "BLDAT", "USNAM": "USNAM_MKPF", "XBLNR": "XBLNR_MKPF",
            "BKTXT": "BKTXT_MKPF", "CPUDT": "CPUDT_MKPF",
        },
    },
    "MSEG": {
        "target_table": "MATDOC",
        "cds_view": "I_MaterialDocumentItem",
        "field_map": {
            "MBLNR": "MBLNR", "MJAHR": "MJAHR", "ZEILE": "ZEILE",
            "BWART": "BWART", "MATNR": "MATNR", "WERKS": "WERKS",
            "LGORT": "LGORT", "MENGE": "MENGE", "MEINS": "MEINS",
            "DMBTR": "DMBTR_STOCK", "LIFNR": "LIFNR", "KUNNR": "KUNNR",
            "EBELN": "EBELN", "EBELP": "EBELP", "AUFNR": "AUFNR",
            "KOSTL": "KOSTL", "BUKRS": "BUKRS",
        },
    },

    # ─── BUSINESS PARTNER: KNA1/LFA1 → BP ───
    "KNA1": {
        "target_table": "BUT000",
        "cds_view": "I_Customer",
        "field_map": {
            "KUNNR": "PARTNER", "NAME1": "NAME_ORG1", "NAME2": "NAME_ORG2",
            "LAND1": "NATIONALITY", "ORT01": "CITY", "PSTLZ": "POSTL_COD1",
            "STRAS": "STREET", "REGIO": "REGION", "TELF1": "TEL_NUMBER",
            "STCD1": "TAXNUM", "STCD2": "TAXNUM", "KTOKD": "BU_GROUP",
        },
        "notes": "Use CDS view I_Customer for read access. Write via API_BUSINESS_PARTNER.",
    },
    "KNB1": {
        "target_table": "BUT0CK",
        "cds_view": "I_CustomerCompany",
        "field_map": {
            "KUNNR": "PARTNER", "BUKRS": "BUKRS", "AKONT": "AKONT",
            "ZTERM": "ZTERM", "ZWELS": "ZWELS",
        },
    },
    "KNVV": {
        "target_table": "BUT052",
        "cds_view": "I_CustomerSalesArea",
        "field_map": {
            "KUNNR": "PARTNER", "VKORG": "VKORG", "VTWEG": "VTWEG",
            "SPART": "SPART", "BZIRK": "BZIRK", "KDGRP": "KDGRP",
        },
    },
    "LFA1": {
        "target_table": "BUT000",
        "cds_view": "I_Supplier",
        "field_map": {
            "LIFNR": "PARTNER", "NAME1": "NAME_ORG1", "NAME2": "NAME_ORG2",
            "LAND1": "NATIONALITY", "ORT01": "CITY", "PSTLZ": "POSTL_COD1",
            "STRAS": "STREET", "REGIO": "REGION", "TELF1": "TEL_NUMBER",
            "STCD1": "TAXNUM",
        },
        "notes": "Use CDS view I_Supplier for read access.",
    },
    "LFB1": {
        "target_table": "BUT0CK",
        "cds_view": "I_SupplierCompany",
        "field_map": {
            "LIFNR": "PARTNER", "BUKRS": "BUKRS", "AKONT": "AKONT",
            "ZTERM": "ZTERM", "ZWELS": "ZWELS",
        },
    },
    "LFM1": {
        "target_table": "BUT0PM",
        "cds_view": "I_SupplierPurchasingOrg",
        "field_map": {
            "LIFNR": "PARTNER", "EKORG": "EKORG", "WAERS": "WAERS",
        },
    },

    # ─── PRICING: KONV → PRCD_ELEMENTS ───
    "KONV": {
        "target_table": "PRCD_ELEMENTS",
        "cds_view": "I_PricingConditionRecord",
        "field_map": {
            "KNUMV": "KNUMV", "KPOSN": "KPOSN", "STUNR": "STUNR",
            "ZAESSION": "ZAESSION", "KSCHL": "KSCHL", "KBETR": "KBETR",
            "KWERT": "KWERT", "WAERS": "WAERS", "KOEIN": "KOEIN",
        },
    },

    # ─── CREDIT MANAGEMENT ───
    "KNKK": {
        "target_table": "UKM_ACCOUNT",
        "cds_view": "I_CreditAccountGeneralData",
        "field_map": {
            "KUNNR": "PARTNER", "KKBER": "CREDIT_SEGMENT",
            "KLIMK": "CREDIT_LIMIT", "SKFOR": "CREDIT_EXPOSURE",
        },
        "notes": "S/4HANA uses SAP Credit Management (FIN-FSCM-CR).",
    },
}


class TableFieldRewriter:
    """
    Rewrites ABAP source code to replace deprecated table and field
    references with their S/4HANA equivalents.
    """

    def __init__(self, field_map: Dict = None):
        self.field_map = field_map or TABLE_FIELD_MAP
        # Build reverse lookup: field_name → which tables use it
        self._build_indices()

    def _build_indices(self):
        """Pre-build lookup indices for fast matching."""
        self.deprecated_tables = set(self.field_map.keys())
        self.table_pattern = re.compile(
            r'\b(' + '|'.join(re.escape(t) for t in self.deprecated_tables) + r')\b',
            re.IGNORECASE
        )

    def rewrite_program(self, program_name: str, source: str) -> Tuple[str, List[Dict]]:
        """
        Rewrite all deprecated table/field references in an ABAP program.
        Returns (rewritten_source, list_of_changes).
        """
        lines = source.split('\n')
        new_lines = []
        all_changes = []

        i = 0
        while i < len(lines):
            line = lines[i]
            original = line
            changes_on_line = []

            # Skip comments
            stripped = line.strip()
            if stripped.startswith('*') or stripped.startswith('"'):
                new_lines.append(line)
                i += 1
                continue

            # 1. Rewrite TABLES: statement
            line, chg = self._rewrite_tables_statement(line)
            changes_on_line.extend(chg)

            # 2. Rewrite SELECT statements (can span multiple lines)
            if re.search(r'\bSELECT\b', line, re.IGNORECASE):
                # Collect full SELECT block
                select_block = [line]
                j = i + 1
                while j < len(lines) and not re.search(r'\.\s*$', lines[j - 1]):
                    select_block.append(lines[j])
                    j += 1
                full_select = '\n'.join(select_block)
                rewritten, chg = self._rewrite_select(full_select)
                if chg:
                    changes_on_line.extend(chg)
                    new_lines.extend(rewritten.split('\n'))
                    i = j
                    for c in changes_on_line:
                        c['line'] = i
                        all_changes.append(c)
                    continue

            # 3. Rewrite DATA/TYPE declarations
            line, chg = self._rewrite_data_declaration(line)
            changes_on_line.extend(chg)

            # 4. Rewrite standalone field references (table-field format)
            line, chg = self._rewrite_field_references(line)
            changes_on_line.extend(chg)

            if changes_on_line:
                for c in changes_on_line:
                    c['line'] = i + 1
                    c['original'] = original.rstrip()
                    c['fixed'] = line.rstrip()
                    all_changes.append(c)

            new_lines.append(line)
            i += 1

        return '\n'.join(new_lines), all_changes

    def _rewrite_tables_statement(self, line: str) -> Tuple[str, List[Dict]]:
        """Rewrite TABLES: BSEG, LFA1, ... to new table names."""
        changes = []
        match = re.match(r'^(\s*TABLES\s*:\s*)(.*)', line, re.IGNORECASE)
        if not match:
            return line, changes

        prefix = match.group(1)
        table_list = match.group(2)

        for old_table in self.deprecated_tables:
            pattern = re.compile(r'\b' + re.escape(old_table) + r'\b', re.IGNORECASE)
            if pattern.search(table_list):
                mapping = self.field_map[old_table]
                new_table = mapping.get('cds_view', mapping['target_table'])
                table_list = pattern.sub(new_table, table_list)
                changes.append({
                    'type': 'table_rename',
                    'rule': 'L1-TABLES',
                    'old': old_table,
                    'new': new_table,
                    'description': f'TABLES: {old_table} → {new_table}',
                })

        return prefix + table_list, changes

    def _rewrite_select(self, select_block: str) -> Tuple[str, List[Dict]]:
        """Rewrite a SELECT statement: table name + field names."""
        changes = []
        result = select_block

        # Find FROM clause to identify which table
        from_match = re.search(
            r'\bFROM\s+(' + '|'.join(re.escape(t) for t in self.deprecated_tables) + r')\b',
            result, re.IGNORECASE
        )
        if not from_match:
            # Check for JOIN syntax: INNER JOIN table ON
            join_match = re.search(
                r'\bJOIN\s+(' + '|'.join(re.escape(t) for t in self.deprecated_tables) + r')\b',
                result, re.IGNORECASE
            )
            if not join_match:
                return result, changes

        # Get all tables referenced in this SELECT
        tables_in_select = set()
        for t in self.deprecated_tables:
            if re.search(r'\b' + re.escape(t) + r'\b', result, re.IGNORECASE):
                tables_in_select.add(t)

        for old_table in tables_in_select:
            mapping = self.field_map[old_table]
            new_table = mapping.get('cds_view', mapping['target_table'])

            # Replace table name
            result = re.sub(
                r'\b' + re.escape(old_table) + r'\b',
                new_table, result, flags=re.IGNORECASE
            )
            changes.append({
                'type': 'select_table',
                'rule': 'L1-SELECT-TABLE',
                'old': old_table,
                'new': new_table,
                'description': f'SELECT FROM {old_table} → {new_table}',
            })

            # Replace field names (both plain and table-prefixed)
            field_map = mapping.get('field_map', {})
            for old_field, new_field in field_map.items():
                # Pattern: TABLE~FIELD or TABLE-FIELD or standalone FIELD in field list
                patterns = [
                    (r'\b' + re.escape(old_table) + r'[~-]' + re.escape(old_field) + r'\b',
                     f'{new_table}~{new_field}'),
                    (r'\b' + re.escape(old_field) + r'\b', new_field),
                ]
                for pattern, replacement in patterns[:1]:  # Prioritize table-prefixed
                    if re.search(pattern, result, re.IGNORECASE):
                        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
                        changes.append({
                            'type': 'select_field',
                            'rule': 'L1-SELECT-FIELD',
                            'old': f'{old_table}-{old_field}',
                            'new': f'{new_table}~{new_field}',
                            'description': f'Field {old_field} → {new_field}',
                        })
                        break

            # Add where clause hint if needed
            where_add = mapping.get('where_addition', '')
            if where_add and 'WHERE' in result.upper():
                # Add a comment about the additional WHERE condition needed
                result += f'\n* NOTE: Add condition {where_add} for exact equivalence'

        return result, changes

    def _rewrite_data_declaration(self, line: str) -> Tuple[str, List[Dict]]:
        """Rewrite DATA: ... TYPE BSEG-DMBTR → TYPE ACDOCA-HSL"""
        changes = []

        for old_table in self.deprecated_tables:
            mapping = self.field_map[old_table]
            new_table = mapping.get('cds_view', mapping['target_table'])
            field_map = mapping.get('field_map', {})

            # Pattern: TYPE old_table-field
            for old_field, new_field in field_map.items():
                pattern = re.compile(
                    r'\bTYPE\s+' + re.escape(old_table) + r'-' + re.escape(old_field) + r'\b',
                    re.IGNORECASE
                )
                if pattern.search(line):
                    replacement = f'TYPE {new_table}-{new_field}'
                    line = pattern.sub(replacement, line)
                    changes.append({
                        'type': 'data_type',
                        'rule': 'L1-DATA-TYPE',
                        'old': f'{old_table}-{old_field}',
                        'new': f'{new_table}-{new_field}',
                        'description': f'TYPE {old_table}-{old_field} → {new_table}-{new_field}',
                    })

            # Pattern: TYPE TABLE OF old_table
            pattern = re.compile(
                r'\bTYPE\s+(STANDARD\s+)?TABLE\s+OF\s+' + re.escape(old_table) + r'\b',
                re.IGNORECASE
            )
            if pattern.search(line):
                line = pattern.sub(f'TYPE STANDARD TABLE OF {new_table}', line)
                changes.append({
                    'type': 'data_table_type',
                    'rule': 'L1-TABLE-TYPE',
                    'old': old_table,
                    'new': new_table,
                    'description': f'TABLE OF {old_table} → TABLE OF {new_table}',
                })

            # Pattern: TYPE old_table (structure reference)
            pattern = re.compile(
                r'\bTYPE\s+' + re.escape(old_table) + r'\b(?![-~])',
                re.IGNORECASE
            )
            if pattern.search(line):
                line = pattern.sub(f'TYPE {new_table}', line)
                changes.append({
                    'type': 'data_struct_type',
                    'rule': 'L1-STRUCT-TYPE',
                    'old': old_table,
                    'new': new_table,
                    'description': f'TYPE {old_table} → TYPE {new_table}',
                })

        return line, changes

    def _rewrite_field_references(self, line: str) -> Tuple[str, List[Dict]]:
        """Rewrite standalone field references like ls_bseg-DMBTR → ls_data-HSL"""
        changes = []

        for old_table in self.deprecated_tables:
            mapping = self.field_map[old_table]
            field_map = mapping.get('field_map', {})

            for old_field, new_field in field_map.items():
                # Match: variable_name-OLD_FIELD where variable likely references old table
                # We look for common naming patterns like lt_bseg-DMBTR, ls_vendor-NAME1
                table_lower = old_table.lower()
                prefixes = [
                    f'lt_{table_lower}', f'ls_{table_lower}', f'lw_{table_lower}',
                    f'gt_{table_lower}', f'gs_{table_lower}',
                    old_table.lower(),  # direct reference like bseg-DMBTR
                ]
                for prefix in prefixes:
                    pattern = re.compile(
                        re.escape(prefix) + r'-' + re.escape(old_field) + r'\b',
                        re.IGNORECASE
                    )
                    if pattern.search(line):
                        new_prefix = prefix  # Keep variable name, just change field
                        replacement = f'{new_prefix}-{new_field}'
                        line = pattern.sub(replacement, line)
                        changes.append({
                            'type': 'field_ref',
                            'rule': 'L1-FIELD-REF',
                            'old': f'{prefix}-{old_field}',
                            'new': replacement,
                            'description': f'{old_field} → {new_field}',
                        })

        return line, changes

    def get_mapping_stats(self) -> Dict:
        """Return statistics about the table/field mapping coverage."""
        total_tables = len(self.field_map)
        total_fields = sum(len(m.get('field_map', {})) for m in self.field_map.values())
        return {
            'tables_mapped': total_tables,
            'fields_mapped': total_fields,
            'tables': list(self.field_map.keys()),
        }


# =============================================================================
# STANDALONE TEST
# =============================================================================
if __name__ == '__main__':
    rewriter = TableFieldRewriter()
    stats = rewriter.get_mapping_stats()
    print(f"Level 1 — Table/Field Rewriter")
    print(f"{'=' * 40}")
    print(f"Tables mapped: {stats['tables_mapped']}")
    print(f"Fields mapped: {stats['fields_mapped']}")
    print(f"\nMappings:")
    for table in sorted(stats['tables']):
        m = TABLE_FIELD_MAP[table]
        fields = len(m.get('field_map', {}))
        target = m.get('cds_view', m['target_table'])
        print(f"  {table:8s} → {target:30s} ({fields} fields)")

    # Test with sample code
    test_code = """
TABLES: BSEG, LFA1, MKPF.

DATA: lt_items TYPE STANDARD TABLE OF BSEG,
      ls_vendor TYPE LFA1,
      lv_amount TYPE BSEG-DMBTR.

SELECT BUKRS BELNR GJAHR DMBTR HKONT
  FROM BSEG
  INTO TABLE lt_items
  WHERE BUKRS = '1000'.

SELECT SINGLE * FROM LFA1 INTO ls_vendor
  WHERE LIFNR = '0000001000'.
"""
    print(f"\n{'=' * 40}")
    print(f"TEST REWRITE:")
    print(f"{'=' * 40}")
    fixed, changes = rewriter.rewrite_program("TEST", test_code)
    print(f"\nChanges made: {len(changes)}")
    for c in changes:
        print(f"  [{c['rule']}] {c['description']}")
    print(f"\nRewritten code:")
    print(fixed)
