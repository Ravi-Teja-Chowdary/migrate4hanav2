"""
Migrate4HANA — Level 2: ABAP Structure Transformer
====================================================
Structural ABAP code transformations requiring statement-level understanding.

19 transforms covering HEADER LINE, SELECT...ENDSELECT, OCCURS,
MOVE...TO, COMPUTE, CREATE OBJECT, ALV, GUI_DOWNLOAD, EXEC SQL, etc.

.. deprecated::
    This regex-based transformer is superseded by the AST-based engine
    in ``abap_ast_engine.py``, which provides structural parsing and
    25+ transformation rules with full grammar coverage. This module
    is retained for backward compatibility but will be removed in a
    future release. Migrate callers to:
        ``from abap_ast_engine import process_abap_file``
"""

import warnings
import re

warnings.warn(
    "level2_structure_transformer is deprecated — use abap_ast_engine.process_abap_file() instead",
    DeprecationWarning,
    stacklevel=2,
)
from typing import Tuple, List, Dict


class ABAPStructureTransformer:
    def __init__(self):
        self.transforms = [
            ('L2-OCCURS', self._fix_occurs),
            ('L2-HEADER-LINE', self._fix_header_line),
            ('L2-MOVE-TO', self._fix_move_to),
            ('L2-COMPUTE', self._fix_compute),
            ('L2-ADD-TO', self._fix_add_subtract),
            ('L2-MULTIPLY-DIVIDE', self._fix_multiply_divide),
            ('L2-REFRESH', self._fix_refresh),
            ('L2-DESCRIBE-LINES', self._fix_describe_lines),
            ('L2-LIKE-TO-TYPE', self._fix_like_to_type),
            ('L2-CREATE-OBJECT', self._fix_create_object),
            ('L2-POPUP-FM', self._fix_deprecated_popups),
            ('L2-GUI-IO', self._fix_gui_download_upload),
            ('L2-WS-IO', self._fix_ws_download_upload),
            ('L2-ALV-FM', self._fix_alv_function_modules),
            ('L2-SELECT-STAR', self._fix_select_star_warning),
            ('L2-CONCATENATE', self._fix_concatenate),
            ('L2-SELECT-ENDSELECT', self._fix_select_endselect),
            ('L2-EXEC-SQL', self._fix_exec_sql),
            ('L2-BAPI-CUSTOMER', self._fix_deprecated_bapis),
        ]

    def transform_program(self, name: str, source: str) -> Tuple[str, List[Dict]]:
        all_changes = []
        current = source
        for tid, fn in self.transforms:
            current, changes = fn(current)
            for c in changes:
                c['transform_id'] = tid
                c['program'] = name
            all_changes.extend(changes)
        return current, all_changes

    def _fix_occurs(self, s):
        ch = []
        p = re.compile(r'\bOCCURS\s+(\d+)\b', re.I)
        for m in p.finditer(s): ch.append({'description': f'OCCURS {m.group(1)} -> INITIAL SIZE {m.group(1)}', 'severity': 'high'})
        return p.sub(r'INITIAL SIZE \1', s), ch

    def _fix_header_line(self, s):
        ch = []
        p = re.compile(r'\bWITH\s+HEADER\s+LINE\b', re.I)
        for m in p.finditer(s): ch.append({'description': 'Removed WITH HEADER LINE — use explicit work area', 'severity': 'high'})
        return p.sub('', s), ch

    def _fix_move_to(self, s):
        ch = []
        p = re.compile(r'^(\s*)MOVE\s+([\w-]+)\s+TO\s+([\w-]+)\s*\.', re.I | re.M)
        def r(m):
            ch.append({'description': f'MOVE→assignment: {m.group(3)} = {m.group(2)}', 'severity': 'medium'})
            return f'{m.group(1)}{m.group(3)} = {m.group(2)}.'
        return p.sub(r, s), ch

    def _fix_compute(self, s):
        ch = []
        p = re.compile(r'^(\s*)COMPUTE\s+', re.I | re.M)
        for m in p.finditer(s): ch.append({'description': 'Removed COMPUTE keyword', 'severity': 'low'})
        return p.sub(r'\1', s), ch

    def _fix_add_subtract(self, s):
        ch = []
        p1 = re.compile(r'^(\s*)ADD\s+([\w-]+)\s+TO\s+([\w-]+)\s*\.', re.I | re.M)
        def r1(m):
            ch.append({'description': f'ADD→ {m.group(3)} = {m.group(3)} + {m.group(2)}', 'severity': 'low'})
            return f'{m.group(1)}{m.group(3)} = {m.group(3)} + {m.group(2)}.'
        s = p1.sub(r1, s)
        p2 = re.compile(r'^(\s*)SUBTRACT\s+([\w-]+)\s+FROM\s+([\w-]+)\s*\.', re.I | re.M)
        def r2(m):
            ch.append({'description': f'SUBTRACT→ {m.group(3)} = {m.group(3)} - {m.group(2)}', 'severity': 'low'})
            return f'{m.group(1)}{m.group(3)} = {m.group(3)} - {m.group(2)}.'
        return p2.sub(r2, s), ch

    def _fix_multiply_divide(self, s):
        ch = []
        p1 = re.compile(r'^(\s*)MULTIPLY\s+([\w-]+)\s+BY\s+([\w\'-]+)\s*\.', re.I | re.M)
        def r1(m):
            ch.append({'description': f'MULTIPLY→ *= operator', 'severity': 'low'})
            return f'{m.group(1)}{m.group(2)} = {m.group(2)} * {m.group(3)}.'
        s = p1.sub(r1, s)
        p2 = re.compile(r'^(\s*)DIVIDE\s+([\w-]+)\s+BY\s+([\w\'-]+)\s*\.', re.I | re.M)
        def r2(m):
            ch.append({'description': f'DIVIDE→ /= operator', 'severity': 'low'})
            return f'{m.group(1)}{m.group(2)} = {m.group(2)} / {m.group(3)}.'
        return p2.sub(r2, s), ch

    def _fix_refresh(self, s):
        ch = []
        p = re.compile(r'^(\s*)REFRESH\s+(\w+)\s*\.', re.I | re.M)
        def r(m):
            ch.append({'description': f'REFRESH→CLEAR {m.group(2)}', 'severity': 'low'})
            return f'{m.group(1)}CLEAR {m.group(2)}.'
        return p.sub(r, s), ch

    def _fix_describe_lines(self, s):
        ch = []
        p = re.compile(r'^(\s*)DESCRIBE\s+TABLE\s+(\w+)\s+LINES\s+(\w+)\s*\.', re.I | re.M)
        def r(m):
            ch.append({'description': f'DESCRIBE TABLE→lines( {m.group(2)} )', 'severity': 'low'})
            return f'{m.group(1)}{m.group(3)} = lines( {m.group(2)} ).'
        return p.sub(r, s), ch

    def _fix_like_to_type(self, s):
        ch = []
        p = re.compile(r'\bLIKE\s+(\w+-\w+)', re.I)
        for m in p.finditer(s): ch.append({'description': f'LIKE→TYPE {m.group(1)}', 'severity': 'medium'})
        return p.sub(r'TYPE \1', s), ch

    def _fix_create_object(self, s):
        ch = []
        p = re.compile(r'^(\s*)CREATE\s+OBJECT\s+(\w+)\s+TYPE\s+(\w+)', re.I | re.M)
        def r(m):
            ch.append({'description': f'CREATE OBJECT→NEW {m.group(3)}( )', 'severity': 'info'})
            return f'{m.group(1)}{m.group(2)} = NEW {m.group(3)}( )'
        return p.sub(r, s), ch

    def _fix_deprecated_popups(self, s):
        ch = []
        if 'POPUP_TO_CONFIRM_STEP' in s.upper():
            ch.append({'description': 'POPUP_TO_CONFIRM_STEP→POPUP_TO_CONFIRM', 'severity': 'low'})
        return re.sub(r'POPUP_TO_CONFIRM_STEP', 'POPUP_TO_CONFIRM', s, flags=re.I), ch

    def _fix_gui_download_upload(self, s):
        ch = []
        for fm in ['GUI_DOWNLOAD', 'GUI_UPLOAD']:
            p = re.compile(rf"(CALL\s+FUNCTION\s+['\"]" + fm + r"['\"].*?\.)", re.I | re.DOTALL)
            if p.search(s):
                ch.append({'description': f'{fm}→server-side alternative (Fiori compatible)', 'severity': 'medium'})
                s = p.sub(f"* [MIGRATE4HANA] {fm} removed for Fiori compatibility.\n"
                         f"* Use CL_SALV_BS_LEX (Excel) or CL_BCS (email) for downloads.\n"
                         f"* Use CL_FDT_XL_SPREADSHEET or UI5 FileUploader for uploads.\n* \\1", s)
        return s, ch

    def _fix_ws_download_upload(self, s):
        ch = []
        for fm in ['WS_DOWNLOAD', 'WS_UPLOAD']:
            p = re.compile(rf"(CALL\s+FUNCTION\s+['\"]" + fm + r"['\"].*?\.)", re.I | re.DOTALL)
            if p.search(s):
                ch.append({'description': f'{fm} obsolete→removed', 'severity': 'high'})
                s = p.sub(f"* [MIGRATE4HANA] {fm} removed (obsolete since 4.6C).\n* \\1", s)
        return s, ch

    def _fix_alv_function_modules(self, s):
        ch = []
        for fm in ['REUSE_ALV_GRID_DISPLAY', 'REUSE_ALV_LIST_DISPLAY', 'REUSE_ALV_HIERSEQ_LIST_DISPLAY']:
            p = re.compile(rf"(CALL\s+FUNCTION\s+['\"]" + fm + r"['\"].*?\.)", re.I | re.DOTALL)
            if p.search(s):
                ch.append({'description': f'{fm}→CL_SALV_TABLE', 'severity': 'medium'})
                s = p.sub(
                    f"* [MIGRATE4HANA] {fm} → CL_SALV_TABLE.\n"
                    "    TRY.\n"
                    "        cl_salv_table=>factory( IMPORTING r_salv_table = DATA(lo_alv)\n"
                    "                                CHANGING  t_table      = lt_output ).\n"
                    "        lo_alv->display( ).\n"
                    "      CATCH cx_salv_msg INTO DATA(lx_msg).\n"
                    "        MESSAGE lx_msg->get_text( ) TYPE 'E'.\n"
                    "    ENDTRY.", s)
        return s, ch

    def _fix_select_star_warning(self, s):
        ch = []
        p = re.compile(r'^(\s*)(SELECT\s+SINGLE\s+\*\s+FROM)', re.I | re.M)
        cnt = len(p.findall(s))
        if cnt > 0:
            ch.append({'description': f'{cnt}x SELECT SINGLE *→add HANA optimization note', 'severity': 'medium'})
        return p.sub(r'\1* [MIGRATE4HANA] HANA: Select specific fields instead of *\n\1\2', s), ch

    def _fix_concatenate(self, s):
        ch = []
        p = re.compile(r"^(\s*)CONCATENATE\s+(\w+)\s+(\w+)\s+INTO\s+(\w+)\s+SEPARATED\s+BY\s+['\"]([^'\"]*?)['\"]\s*\.", re.I | re.M)
        def r(m):
            ch.append({'description': 'CONCATENATE→string template', 'severity': 'info'})
            return f"{m.group(1)}{m.group(4)} = |{{ {m.group(2)} }}{m.group(5)}{{ {m.group(3)} }}|."
        return p.sub(r, s), ch

    def _fix_select_endselect(self, s):
        ch = []
        p = re.compile(r'^(\s*)(SELECT\s+.+?\s+INTO\s+(?:DATA\()?(\w+)\)?\s*\.)\s*\n(.*?)^(\s*ENDSELECT\s*\.)', re.I | re.M | re.DOTALL)
        def r(m):
            indent, sel, wa, body, _ = m.groups()
            tbl = f'lt_{wa[3:]}' if wa.startswith('ls_') else f'lt_{wa}'
            new_sel = re.sub(r'\bINTO\s+(?:DATA\()?' + re.escape(wa) + r'\)?\s*\.', f'INTO TABLE @DATA({tbl}).', sel, flags=re.I)
            ch.append({'description': 'SELECT...ENDSELECT→SELECT INTO TABLE + LOOP', 'severity': 'high'})
            return f"{indent}{new_sel}\n{indent}LOOP AT {tbl} INTO DATA({wa}).\n{body}{indent}ENDLOOP."
        return p.sub(r, s), ch

    def _fix_exec_sql(self, s):
        ch = []
        p = re.compile(r'^(\s*)(EXEC\s+SQL\s*\..*?ENDEXEC\s*\.)', re.I | re.M | re.DOTALL)
        if p.search(s):
            ch.append({'description': 'EXEC SQL→removed (forbidden in S/4HANA Cloud)', 'severity': 'critical'})
        return p.sub(r'\1* [MIGRATE4HANA] EXEC SQL removed — use ABAP SQL or AMDP.\n\1* \2', s), ch

    def _fix_deprecated_bapis(self, s):
        ch = []
        for old, new in [
            ('BAPI_CUSTOMER_CREATEFROMDATA1', 'CL_MDG_BS_BP_API=>create'),
            ('BAPI_CUSTOMER_CREATEFROMDATA2', 'CL_MDG_BS_BP_API=>create'),
            ('BAPI_VENDOR_CREATE', 'CL_MDG_BS_BP_API=>create'),
        ]:
            p = re.compile(rf"(CALL\s+FUNCTION\s+['\"]" + old + r"['\"].*?\.)", re.I | re.DOTALL)
            if p.search(s):
                ch.append({'description': f'{old}→{new} (Business Partner API)', 'severity': 'critical'})
                s = p.sub(f"* [MIGRATE4HANA] {old} deprecated.\n"
                         f"* Use {new} or API_BUSINESS_PARTNER OData service.\n* \\1", s)
        return s, ch

    def get_transform_stats(self):
        return {'total_transforms': len(self.transforms), 'transforms': [t[0] for t in self.transforms]}


if __name__ == '__main__':
    t = ABAPStructureTransformer()
    print(f"Level 2 — {t.get_transform_stats()['total_transforms']} transforms")
    for x in t.get_transform_stats()['transforms']:
        print(f"  {x}")
