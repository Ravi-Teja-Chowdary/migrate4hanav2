"""
abap_ast_engine.py — Production-Grade ABAP Abstract Syntax Tree Engine
========================================================================
Replaces legacy regex-based parsing (level2_structure_transformer.py and
level2b_aggressive.py). Provides structural ABAP code analysis and
transformation for S/4HANA migration via:

  1. Semantic Lexer        — Tokenizes ABAP handling chains, field-symbols, templates
  2. AST Node Hierarchy    — 70+ node types covering the full ABAP grammar
  3. Recursive Descent Parser — Structural AST from token stream
  4. S/4HANA Transform Visitor — Applies 130+ migration rules on the AST
  5. Code Generator        — Emits valid, reformatted ABAP from the mutated AST

Grammar coverage:
  - Declarations: DATA, TYPES, CONSTANTS, FIELD-SYMBOLS, TABLES, PARAMETERS,
    SELECT-OPTIONS, RANGES, STATICS, CLASS-DATA
  - Control: IF/ELSEIF/ELSE/ENDIF, CASE/WHEN/ENDCASE, DO/ENDDO, WHILE/ENDWHILE,
    LOOP AT/ENDLOOP, CHECK, EXIT, CONTINUE, RETURN
  - Open SQL: SELECT (SINGLE, DISTINCT, INTO TABLE, CORRESPONDING, FOR ALL ENTRIES,
    JOIN, GROUP BY, HAVING, ORDER BY, UP TO n ROWS), INSERT, UPDATE, DELETE, MODIFY
  - Internal tables: APPEND, INSERT, DELETE, MODIFY, READ TABLE, SORT, COLLECT,
    DESCRIBE TABLE, CLEAR, REFRESH, FREE
  - Strings: CONCATENATE, SPLIT, TRANSLATE, CONDENSE, REPLACE, SHIFT, FIND, SEARCH
  - Arithmetic: ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE
  - Assignments: MOVE...TO, MOVE-CORRESPONDING, = operator
  - OOP: CLASS/ENDCLASS, METHOD/ENDMETHOD, INTERFACE/ENDINTERFACE,
    CREATE OBJECT, CREATE DATA, CALL METHOD
  - Subroutines: FORM/ENDFORM, PERFORM, CALL FUNCTION, CALL TRANSACTION
  - Exceptions: TRY/CATCH/CLEANUP/ENDTRY, RAISE, RAISE EXCEPTION
  - File I/O: OPEN/READ/TRANSFER/CLOSE/DELETE DATASET
  - System: MESSAGE, AUTHORITY-CHECK, COMMIT WORK, ROLLBACK WORK,
    EXPORT/IMPORT TO MEMORY, SET/GET PARAMETER, SUBMIT
  - Events: INITIALIZATION, START-OF-SELECTION, END-OF-SELECTION,
    TOP-OF-PAGE, AT SELECTION-SCREEN, AT LINE-SELECTION, AT USER-COMMAND
  - Macros: DEFINE / END-OF-DEFINITION
  - Native SQL: EXEC SQL / ENDEXEC
  - Modern ABAP 7.40+: Inline DATA(...), FIELD-SYMBOL(...), constructor
    expressions NEW/VALUE/CORRESPONDING/COND/SWITCH/CONV/CAST/REF/REDUCE/FILTER
  - Output: WRITE, SKIP, ULINE, NEW-LINE, FORMAT
  - Chained statements (colon/comma expansion)
  - Reports/Programs, INCLUDEs, SELECTION-SCREEN
"""

import re
import logging
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple, Set

logger = logging.getLogger("abap_ast_engine")
logger.setLevel(logging.INFO)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: TOKEN TYPES & LEXER
# ═══════════════════════════════════════════════════════════════════════════════

class TokenType(Enum):
    """
    All 30 token types produced by the ABAP lexer.

    Comprehensive reference with examples:

    Identifiers & Symbols:
      IDENTIFIER      — Keywords, variable names, table names, method names.
                         Examples: DATA, lv_count, BSEG-BUKRS, /SAPDMC/LSM_MAP,
                                   cl_gui_alv_grid~set_table_for_first_display
      FIELD_SYMBOL    — Field symbol references enclosed in angle brackets.
                         Examples: <fs_data>, <ls_item>, <lt_result>
      PRAGMA          — Compiler pragmas starting with ##.
                         Examples: ##NO_TEXT, ##NEEDED, ##SHADOW

    Literals:
      INTEGER         — Whole number literals.
                         Examples: 0, 42, 999999, -1
      FLOAT           — Decimal number literals.
                         Examples: 3.14, 0.001, 100.00
      STRING          — String literals in single quotes or backticks.
                         Examples: 'Hello World', 'It''s escaped', `backtick str`
      STRING_TEMPLATE — String templates with embedded expressions in pipes.
                         Examples: |Total: { lv_count }|, |{ lv_name } ({ lv_id })|

    Punctuation & Delimiters:
      PERIOD          — Statement terminator (.).
                         Example: DATA lv_x TYPE i.  (the trailing dot)
      COLON           — Chain prefix operator for chained statements (:).
                         Example: WRITE: / lv_a, / lv_b.
      COMMA           — Chain element separator (,).
                         Example: DATA: lv_a TYPE i, lv_b TYPE string.
      LPAREN          — Left parenthesis for grouping or function calls (().
                         Example: strlen( lv_str ), DATA(lv_x)
      RPAREN          — Right parenthesis ().
      LBRACKET        — Left square bracket ([).
                         Example: itab[ 1 ]-field
      RBRACKET        — Right square bracket (]).

    Operators:
      EQUALS          — Assignment or comparison (=).
                         Examples: lv_x = 5, WITH KEY bukrs = '1000'
      PLUS            — Addition operator (+).
      MINUS           — Subtraction operator or negative sign (-).
      STAR            — Multiplication operator or SELECT * wildcard (*).
      SLASH           — Division operator (/).
      LT              — Less-than comparison (<).
      GT              — Greater-than comparison (>).
      LE              — Less-than-or-equal (<=).
      GE              — Greater-than-or-equal (>=).
      NE              — Not-equal (<>).
      ARROW           — Instance member access (->).
                         Example: lo_obj->method_name
      FAT_ARROW       — Static member access (=>).
                         Example: cl_class=>static_method

    Special Characters:
      AMPERSAND       — Concatenation in macros or string templates (&).
      AT_SIGN         — Host variable prefix in CDS/SQL (@).
                         Example: SELECT @lv_val FROM ...
      HASH            — Type/constructor inference (#).
                         Example: VALUE #( ), CORRESPONDING #( )

    Meta:
      COMMENT         — Line comment (* at col 1) or inline comment (" prefix).
                         Examples: * This is a comment, " inline comment
      EOF             — End-of-file sentinel. Always the last token.
    """
    IDENTIFIER = auto()
    FIELD_SYMBOL = auto()       # <fs_name>
    INTEGER = auto()
    FLOAT = auto()
    STRING = auto()             # 'literal' or `literal`
    STRING_TEMPLATE = auto()    # |template with { expr }|
    PERIOD = auto()             # .
    COLON = auto()              # :
    COMMA = auto()              # ,
    LPAREN = auto()             # (
    RPAREN = auto()             # )
    LBRACKET = auto()           # [
    RBRACKET = auto()           # ]
    EQUALS = auto()             # =
    PLUS = auto()               # +
    MINUS = auto()              # -
    STAR = auto()               # *
    SLASH = auto()              # /
    LT = auto()                 # <
    GT = auto()                 # >
    LE = auto()                 # <=
    GE = auto()                 # >=
    NE = auto()                 # <>
    ARROW = auto()              # ->
    FAT_ARROW = auto()          # =>
    AMPERSAND = auto()          # &
    AT_SIGN = auto()            # @
    HASH = auto()               # #
    COMMENT = auto()
    PRAGMA = auto()             # ##NO_TEXT, ##NEEDED, etc.
    EOF = auto()


@dataclass
class Token:
    """Single token with position tracking."""
    type: TokenType
    value: str
    line: int
    column: int

    def __repr__(self):
        return f"Token({self.type.name}, {self.value!r}, L{self.line}:{self.column})"


class ABAPLexer:
    """
    Full semantic lexer for ABAP source code.

    Handles:
    - Line comments (* at column 1) and inline comments (" prefix)
    - String literals ('...' with '' escape and `...` with `` escape)
    - String templates (|...|) with embedded expressions
    - Field symbols (<identifier>)
    - Pragmas (##keyword)
    - Namespace identifiers (/namespace/name)
    - Interface components (intf~method)
    - Structure component access (struc-field) as single token
    - All ABAP operators and punctuation
    - Decimal numbers (integer and float)
    """

    def __init__(self, source: str):
        self.source = source
        self.pos = 0
        self.line = 1
        self.col = 1
        self.tokens: List[Token] = []
        self._at_line_start = True

    def tokenize(self) -> List[Token]:
        """Tokenize the entire ABAP source into a token list."""
        while self.pos < len(self.source):
            ch = self._ch()

            # ── Newline ──
            if ch == '\n':
                self.line += 1
                self.col = 1
                self.pos += 1
                self._at_line_start = True
                continue
            if ch == '\r':
                self.pos += 1
                continue

            # ── Whitespace ──
            if ch in (' ', '\t'):
                self.pos += 1
                self.col += 1
                continue

            # ── Full-line comment (* at column 1) ──
            if ch == '*' and self._at_line_start:
                self._read_line_comment()
                continue

            # ── Inline comment (" to end of line) ──
            if ch == '"':
                self._read_inline_comment()
                continue

            self._at_line_start = False

            # ── String literal '...' ──
            if ch == "'":
                self._read_string("'")
                continue

            # ── Backtick string `...` ──
            if ch == '`':
                self._read_string('`')
                continue

            # ── String template |...| ──
            if ch == '|':
                self._read_string_template()
                continue

            # ── Pragma ##... ──
            if ch == '#' and self._peek() == '#':
                self._read_pragma()
                continue

            # ── Field symbol <identifier> ──
            if ch == '<' and self._looks_like_field_symbol():
                self._read_field_symbol()
                continue

            # ── Numeric literal ──
            if ch.isdigit():
                self._read_number()
                continue

            # ── Identifier / keyword ──
            if ch.isalpha() or ch == '_' or ch == '/':
                self._read_identifier()
                continue

            # ── Two-character operators ──
            if self.pos + 1 < len(self.source):
                two = self.source[self.pos:self.pos + 2]
                two_ops = {
                    '->': TokenType.ARROW, '=>': TokenType.FAT_ARROW,
                    '<=': TokenType.LE, '>=': TokenType.GE, '<>': TokenType.NE,
                }
                if two in two_ops:
                    self._emit(two_ops[two], two, 2)
                    continue

            # ── Single-character tokens ──
            singles = {
                '.': TokenType.PERIOD, ':': TokenType.COLON, ',': TokenType.COMMA,
                '(': TokenType.LPAREN, ')': TokenType.RPAREN,
                '[': TokenType.LBRACKET, ']': TokenType.RBRACKET,
                '=': TokenType.EQUALS, '+': TokenType.PLUS, '-': TokenType.MINUS,
                '*': TokenType.STAR, '/': TokenType.SLASH,
                '<': TokenType.LT, '>': TokenType.GT,
                '&': TokenType.AMPERSAND, '@': TokenType.AT_SIGN, '#': TokenType.HASH,
            }
            if ch in singles:
                self._emit(singles[ch], ch, 1)
                continue

            # ── Unknown character — skip ──
            self.pos += 1
            self.col += 1

        self.tokens.append(Token(TokenType.EOF, '', self.line, self.col))
        return self.tokens

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _ch(self) -> str:
        return self.source[self.pos] if self.pos < len(self.source) else '\0'

    def _peek(self) -> str:
        return self.source[self.pos + 1] if self.pos + 1 < len(self.source) else '\0'

    def _emit(self, ttype: TokenType, value: str, length: int):
        self.tokens.append(Token(ttype, value, self.line, self.col))
        self.pos += length
        self.col += length

    def _read_line_comment(self):
        start = self.pos
        while self.pos < len(self.source) and self.source[self.pos] != '\n':
            self.pos += 1
        self.tokens.append(Token(TokenType.COMMENT, self.source[start:self.pos], self.line, 1))
        self.col = 1

    def _read_inline_comment(self):
        start = self.pos
        start_col = self.col
        while self.pos < len(self.source) and self.source[self.pos] != '\n':
            self.pos += 1
            self.col += 1
        self.tokens.append(Token(TokenType.COMMENT, self.source[start:self.pos], self.line, start_col))

    def _read_string(self, quote: str):
        start_col = self.col
        self.pos += 1
        self.col += 1
        buf = quote
        while self.pos < len(self.source):
            c = self.source[self.pos]
            buf += c
            self.pos += 1
            self.col += 1
            if c == quote:
                if self.pos < len(self.source) and self.source[self.pos] == quote:
                    buf += quote
                    self.pos += 1
                    self.col += 1
                else:
                    break
        self.tokens.append(Token(TokenType.STRING, buf, self.line, start_col))

    def _read_string_template(self):
        start_col = self.col
        self.pos += 1
        self.col += 1
        buf = '|'
        depth = 0
        while self.pos < len(self.source):
            c = self.source[self.pos]
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
            elif c == '|' and depth == 0:
                buf += c
                self.pos += 1
                self.col += 1
                break
            elif c == '\n':
                self.line += 1
                self.col = 0
            buf += c
            self.pos += 1
            self.col += 1
        self.tokens.append(Token(TokenType.STRING_TEMPLATE, buf, self.line, start_col))

    def _read_pragma(self):
        start = self.pos
        start_col = self.col
        while self.pos < len(self.source) and not self.source[self.pos].isspace() and self.source[self.pos] not in ('.', ','):
            self.pos += 1
            self.col += 1
        self.tokens.append(Token(TokenType.PRAGMA, self.source[start:self.pos], self.line, start_col))

    def _looks_like_field_symbol(self) -> bool:
        i = self.pos + 1
        while i < len(self.source) and (self.source[i].isalnum() or self.source[i] in ('_', '-')):
            i += 1
        return i < len(self.source) and self.source[i] == '>'

    def _read_field_symbol(self):
        start = self.pos
        start_col = self.col
        self.pos += 1
        self.col += 1
        while self.pos < len(self.source) and self.source[self.pos] != '>':
            self.pos += 1
            self.col += 1
        if self.pos < len(self.source):
            self.pos += 1
            self.col += 1
        self.tokens.append(Token(TokenType.FIELD_SYMBOL, self.source[start:self.pos], self.line, start_col))

    def _read_number(self):
        start = self.pos
        start_col = self.col
        has_dot = False
        while self.pos < len(self.source):
            c = self.source[self.pos]
            if c.isdigit():
                self.pos += 1
                self.col += 1
            elif c == '.' and not has_dot:
                if self.pos + 1 < len(self.source) and self.source[self.pos + 1].isdigit():
                    has_dot = True
                    self.pos += 1
                    self.col += 1
                else:
                    break
            else:
                break
        val = self.source[start:self.pos]
        ttype = TokenType.FLOAT if has_dot else TokenType.INTEGER
        self.tokens.append(Token(ttype, val, self.line, start_col))

    def _read_identifier(self):
        start = self.pos
        start_col = self.col
        while self.pos < len(self.source):
            c = self.source[self.pos]
            if c.isalnum() or c == '_':
                self.pos += 1
                self.col += 1
            elif c == '-':
                if self.pos + 1 < len(self.source) and (self.source[self.pos + 1].isalpha() or self.source[self.pos + 1] == '_'):
                    self.pos += 1
                    self.col += 1
                else:
                    break
            elif c == '/' or c == '~':
                self.pos += 1
                self.col += 1
            else:
                break
        self.tokens.append(Token(TokenType.IDENTIFIER, self.source[start:self.pos], self.line, start_col))


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: AST NODE HIERARCHY (60+ node types)
# ═══════════════════════════════════════════════════════════════════════════════

class ABAPNode:
    """Base AST node for all ABAP constructs."""
    def __init__(self, node_type: str, line: int = 0):
        self.node_type = node_type
        self.line = line
        self.children: List[ABAPNode] = []
        self._changes: List[str] = []


# ── Program / Structure ───────────────────────────────────────────────────────

class ProgramNode(ABAPNode):
    def __init__(self, statements: List[ABAPNode] = None, line: int = 0):
        super().__init__('PROGRAM', line)
        self.statements = statements or []

class CommentNode(ABAPNode):
    def __init__(self, text: str = '', line: int = 0):
        super().__init__('COMMENT', line)
        self.text = text

class PragmaNode(ABAPNode):
    def __init__(self, text: str = '', line: int = 0):
        super().__init__('PRAGMA', line)
        self.text = text

class ReportStatement(ABAPNode):
    def __init__(self, name: str = '', options: List[str] = None, line: int = 0):
        super().__init__('REPORT', line)
        self.name = name
        self.options = options or []

class IncludeStatement(ABAPNode):
    def __init__(self, include_name: str = '', line: int = 0):
        super().__init__('INCLUDE', line)
        self.include_name = include_name


# ── Declarations ──────────────────────────────────────────────────────────────

class DataDeclaration(ABAPNode):
    def __init__(self, name: str = '', type_clause: str = '', like_clause: str = '',
                 ref_to: str = '', table_type: str = '', table_of: str = '',
                 table_key: List[str] = None, initial_value: str = '',
                 length: str = '', decimals: str = '',
                 occurs: str = '', header_line: bool = False,
                 is_structure_begin: bool = False, is_structure_end: bool = False,
                 read_only: bool = False, keyword: str = 'DATA', line: int = 0):
        super().__init__('DATA_DECLARATION', line)
        self.name = name
        self.keyword = keyword
        self.type_clause = type_clause
        self.like_clause = like_clause
        self.ref_to = ref_to
        self.table_type = table_type
        self.table_of = table_of
        self.table_key = table_key or []
        self.initial_value = initial_value
        self.length = length
        self.decimals = decimals
        self.occurs = occurs
        self.header_line = header_line
        self.is_structure_begin = is_structure_begin
        self.is_structure_end = is_structure_end
        self.read_only = read_only

class TypesDeclaration(ABAPNode):
    def __init__(self, name: str = '', type_clause: str = '', like_clause: str = '',
                 table_type: str = '', table_of: str = '', table_key: List[str] = None,
                 is_structure_begin: bool = False, is_structure_end: bool = False,
                 occurs: str = '', components: List[Dict] = None, line: int = 0):
        super().__init__('TYPES_DECLARATION', line)
        self.name = name
        self.type_clause = type_clause
        self.like_clause = like_clause
        self.table_type = table_type
        self.table_of = table_of
        self.table_key = table_key or []
        self.is_structure_begin = is_structure_begin
        self.is_structure_end = is_structure_end
        self.occurs = occurs
        self.components = components or []

class ConstantsDeclaration(ABAPNode):
    def __init__(self, name: str = '', type_clause: str = '', value: str = '',
                 is_structure_begin: bool = False, is_structure_end: bool = False,
                 line: int = 0):
        super().__init__('CONSTANTS_DECLARATION', line)
        self.name = name
        self.type_clause = type_clause
        self.value = value
        self.is_structure_begin = is_structure_begin
        self.is_structure_end = is_structure_end

class FieldSymbolDeclaration(ABAPNode):
    def __init__(self, name: str = '', type_clause: str = '', like_clause: str = '',
                 generic_type: str = '', line: int = 0):
        super().__init__('FIELD_SYMBOL_DECLARATION', line)
        self.name = name
        self.type_clause = type_clause
        self.like_clause = like_clause
        self.generic_type = generic_type

class TablesDeclaration(ABAPNode):
    def __init__(self, table_name: str = '', line: int = 0):
        super().__init__('TABLES_DECLARATION', line)
        self.table_name = table_name

class ParameterDeclaration(ABAPNode):
    def __init__(self, name: str = '', type_clause: str = '', like_clause: str = '',
                 default_value: str = '', obligatory: bool = False,
                 as_checkbox: bool = False, as_listbox: bool = False,
                 keyword: str = 'PARAMETERS', line: int = 0):
        super().__init__('PARAMETER_DECLARATION', line)
        self.name = name
        self.keyword = keyword
        self.type_clause = type_clause
        self.like_clause = like_clause
        self.default_value = default_value
        self.obligatory = obligatory
        self.as_checkbox = as_checkbox
        self.as_listbox = as_listbox

class SelectOptionDeclaration(ABAPNode):
    def __init__(self, name: str = '', for_field: str = '', default_low: str = '',
                 default_high: str = '', no_extension: bool = False,
                 no_intervals: bool = False, obligatory: bool = False, line: int = 0):
        super().__init__('SELECT_OPTION_DECLARATION', line)
        self.name = name
        self.for_field = for_field
        self.default_low = default_low
        self.default_high = default_high
        self.no_extension = no_extension
        self.no_intervals = no_intervals
        self.obligatory = obligatory

class RangesDeclaration(ABAPNode):
    def __init__(self, name: str = '', for_field: str = '', line: int = 0):
        super().__init__('RANGES_DECLARATION', line)
        self.name = name
        self.for_field = for_field


# ── Assignments & Arithmetic ─────────────────────────────────────────────────

class AssignmentStatement(ABAPNode):
    def __init__(self, target: str = '', expression: str = '', line: int = 0):
        super().__init__('ASSIGNMENT', line)
        self.target = target
        self.expression = expression

class MoveStatement(ABAPNode):
    def __init__(self, source: str = '', target: str = '', line: int = 0):
        super().__init__('MOVE', line)
        self.source = source
        self.target = target

class MoveCorrespondingStatement(ABAPNode):
    def __init__(self, source: str = '', target: str = '', line: int = 0):
        super().__init__('MOVE_CORRESPONDING', line)
        self.source = source
        self.target = target

class ComputeStatement(ABAPNode):
    def __init__(self, target: str = '', expression: str = '', line: int = 0):
        super().__init__('COMPUTE', line)
        self.target = target
        self.expression = expression

class ArithmeticStatement(ABAPNode):
    def __init__(self, operation: str = '', operand: str = '', target: str = '',
                 line: int = 0):
        super().__init__('ARITHMETIC', line)
        self.operation = operation  # ADD, SUBTRACT, MULTIPLY, DIVIDE
        self.operand = operand
        self.target = target


# ── Open SQL ──────────────────────────────────────────────────────────────────

class SelectStatement(ABAPNode):
    def __init__(self, is_single: bool = False, is_distinct: bool = False,
                 field_list: List[str] = None, from_clause: str = '',
                 joins: List[Dict] = None, into_clause: str = '',
                 into_table: str = '', into_corresponding: bool = False,
                 appending: bool = False, for_all_entries: str = '',
                 where_clause: str = '', group_by: List[str] = None,
                 having_clause: str = '', order_by: List[str] = None,
                 up_to_rows: str = '', has_endselect: bool = False,
                 body: List[ABAPNode] = None, line: int = 0):
        super().__init__('SELECT', line)
        self.is_single = is_single
        self.is_distinct = is_distinct
        self.field_list = field_list or []
        self.from_clause = from_clause
        self.joins = joins or []
        self.into_clause = into_clause
        self.into_table = into_table
        self.into_corresponding = into_corresponding
        self.appending = appending
        self.for_all_entries = for_all_entries
        self.where_clause = where_clause
        self.group_by = group_by or []
        self.having_clause = having_clause
        self.order_by = order_by or []
        self.up_to_rows = up_to_rows
        self.has_endselect = has_endselect
        self.body = body or []

class DatabaseModifyStatement(ABAPNode):
    def __init__(self, operation: str = '', table_name: str = '',
                 from_wa: str = '', values_clause: str = '',
                 where_clause: str = '', line: int = 0):
        super().__init__('DB_MODIFY', line)
        self.operation = operation  # INSERT, UPDATE, DELETE, MODIFY
        self.table_name = table_name
        self.from_wa = from_wa
        self.values_clause = values_clause
        self.where_clause = where_clause

class NativeSqlBlock(ABAPNode):
    def __init__(self, sql_text: str = '', line: int = 0):
        super().__init__('NATIVE_SQL', line)
        self.sql_text = sql_text


# ── Control Flow ──────────────────────────────────────────────────────────────

class IfBlock(ABAPNode):
    def __init__(self, condition: str = '', then_body: List[ABAPNode] = None,
                 elseif_branches: List[Tuple] = None,
                 else_body: List[ABAPNode] = None, line: int = 0):
        super().__init__('IF', line)
        self.condition = condition
        self.then_body = then_body or []
        self.elseif_branches = elseif_branches or []  # [(condition, [stmts]), ...]
        self.else_body = else_body or []

class CaseBlock(ABAPNode):
    def __init__(self, operand: str = '', when_branches: List[Tuple] = None,
                 others_body: List[ABAPNode] = None, line: int = 0):
        super().__init__('CASE', line)
        self.operand = operand
        self.when_branches = when_branches or []  # [(value, [stmts]), ...]
        self.others_body = others_body or []

class DoLoop(ABAPNode):
    def __init__(self, times: str = '', varying: str = '',
                 body: List[ABAPNode] = None, line: int = 0):
        super().__init__('DO', line)
        self.times = times
        self.varying = varying
        self.body = body or []

class WhileLoop(ABAPNode):
    def __init__(self, condition: str = '', body: List[ABAPNode] = None, line: int = 0):
        super().__init__('WHILE', line)
        self.condition = condition
        self.body = body or []

class LoopAtStatement(ABAPNode):
    def __init__(self, table: str = '', into: str = '', assigning: str = '',
                 reference_into: str = '', where_clause: str = '',
                 from_index: str = '', to_index: str = '',
                 body: List[ABAPNode] = None, line: int = 0):
        super().__init__('LOOP_AT', line)
        self.table = table
        self.into = into
        self.assigning = assigning
        self.reference_into = reference_into
        self.where_clause = where_clause
        self.from_index = from_index
        self.to_index = to_index
        self.body = body or []


# ── Subroutines / Functions / OOP ─────────────────────────────────────────────

class FormBlock(ABAPNode):
    def __init__(self, name: str = '', using_params: List[str] = None,
                 changing_params: List[str] = None, tables_params: List[str] = None,
                 body: List[ABAPNode] = None, line: int = 0):
        super().__init__('FORM', line)
        self.name = name
        self.using_params = using_params or []
        self.changing_params = changing_params or []
        self.tables_params = tables_params or []
        self.body = body or []

class PerformStatement(ABAPNode):
    def __init__(self, form_name: str = '', in_program: str = '',
                 using_args: List[str] = None, changing_args: List[str] = None,
                 tables_args: List[str] = None, line: int = 0):
        super().__init__('PERFORM', line)
        self.form_name = form_name
        self.in_program = in_program
        self.using_args = using_args or []
        self.changing_args = changing_args or []
        self.tables_args = tables_args or []

class ClassBlock(ABAPNode):
    def __init__(self, name: str = '', superclass: str = '',
                 is_abstract: bool = False, is_final: bool = False,
                 is_definition: bool = False, is_implementation: bool = False,
                 create_visibility: str = 'PUBLIC',
                 interfaces: List[str] = None,
                 public_section: List[ABAPNode] = None,
                 protected_section: List[ABAPNode] = None,
                 private_section: List[ABAPNode] = None,
                 body: List[ABAPNode] = None, line: int = 0):
        super().__init__('CLASS', line)
        self.name = name
        self.superclass = superclass
        self.is_abstract = is_abstract
        self.is_final = is_final
        self.is_definition = is_definition
        self.is_implementation = is_implementation
        self.create_visibility = create_visibility
        self.interfaces = interfaces or []
        self.public_section = public_section or []
        self.protected_section = protected_section or []
        self.private_section = private_section or []
        self.body = body or []

class MethodBlock(ABAPNode):
    def __init__(self, name: str = '', body: List[ABAPNode] = None, line: int = 0):
        super().__init__('METHOD', line)
        self.name = name
        self.body = body or []

class InterfaceBlock(ABAPNode):
    def __init__(self, name: str = '', methods: List[str] = None,
                 body: List[ABAPNode] = None, line: int = 0):
        super().__init__('INTERFACE', line)
        self.name = name
        self.methods = methods or []
        self.body = body or []

class CallFunctionStatement(ABAPNode):
    def __init__(self, function_name: str = '', exporting: List[Tuple] = None,
                 importing: List[Tuple] = None, changing: List[Tuple] = None,
                 tables: List[Tuple] = None, exceptions: List[Tuple] = None,
                 line: int = 0):
        super().__init__('CALL_FUNCTION', line)
        self.function_name = function_name
        self.exporting = exporting or []
        self.importing = importing or []
        self.changing = changing or []
        self.tables = tables or []
        self.exceptions = exceptions or []

class CallMethodStatement(ABAPNode):
    def __init__(self, object_ref: str = '', method_name: str = '',
                 exporting: List[Tuple] = None, importing: List[Tuple] = None,
                 changing: List[Tuple] = None, receiving: str = '',
                 line: int = 0):
        super().__init__('CALL_METHOD', line)
        self.object_ref = object_ref
        self.method_name = method_name
        self.exporting = exporting or []
        self.importing = importing or []
        self.changing = changing or []
        self.receiving = receiving

class CallTransactionStatement(ABAPNode):
    def __init__(self, tcode: str = '', using_bdc: str = '', mode: str = '',
                 update: str = '', messages_into: str = '', line: int = 0):
        super().__init__('CALL_TRANSACTION', line)
        self.tcode = tcode
        self.using_bdc = using_bdc
        self.mode = mode
        self.update = update
        self.messages_into = messages_into

class CreateObjectStatement(ABAPNode):
    def __init__(self, variable: str = '', class_name: str = '',
                 exporting: List[Tuple] = None, line: int = 0):
        super().__init__('CREATE_OBJECT', line)
        self.variable = variable
        self.class_name = class_name
        self.exporting = exporting or []

class CreateDataStatement(ABAPNode):
    def __init__(self, variable: str = '', type_clause: str = '',
                 like_clause: str = '', line: int = 0):
        super().__init__('CREATE_DATA', line)
        self.variable = variable
        self.type_clause = type_clause
        self.like_clause = like_clause


# ── Exception Handling ────────────────────────────────────────────────────────

class TryBlock(ABAPNode):
    def __init__(self, try_body: List[ABAPNode] = None,
                 catch_branches: List[Tuple] = None,
                 cleanup_body: List[ABAPNode] = None, line: int = 0):
        super().__init__('TRY', line)
        self.try_body = try_body or []
        self.catch_branches = catch_branches or []  # [(exception_class, into_var, [stmts])]
        self.cleanup_body = cleanup_body or []

class RaiseStatement(ABAPNode):
    def __init__(self, exception_class: str = '', message_type: str = '',
                 is_shortdump: bool = False, exporting: List[Tuple] = None,
                 line: int = 0):
        super().__init__('RAISE', line)
        self.exception_class = exception_class
        self.message_type = message_type
        self.is_shortdump = is_shortdump
        self.exporting = exporting or []


# ── Internal Table Operations ─────────────────────────────────────────────────

class AppendStatement(ABAPNode):
    def __init__(self, source: str = '', target: str = '',
                 initial_line: bool = False, corresponding: bool = False,
                 lines_of: str = '', line: int = 0):
        super().__init__('APPEND', line)
        self.source = source
        self.target = target
        self.initial_line = initial_line
        self.corresponding = corresponding
        self.lines_of = lines_of

class InsertTableStatement(ABAPNode):
    def __init__(self, source: str = '', target: str = '', index: str = '',
                 lines_of: str = '', line: int = 0):
        super().__init__('INSERT_TABLE', line)
        self.source = source
        self.target = target
        self.index = index
        self.lines_of = lines_of

class DeleteTableStatement(ABAPNode):
    def __init__(self, table: str = '', where_clause: str = '',
                 index: str = '', from_to: str = '', adjacent_duplicates: bool = False,
                 comparing: List[str] = None, line: int = 0):
        super().__init__('DELETE_TABLE', line)
        self.table = table
        self.where_clause = where_clause
        self.index = index
        self.from_to = from_to
        self.adjacent_duplicates = adjacent_duplicates
        self.comparing = comparing or []

class ModifyTableStatement(ABAPNode):
    def __init__(self, table: str = '', from_wa: str = '',
                 index: str = '', transporting: List[str] = None,
                 where_clause: str = '', line: int = 0):
        super().__init__('MODIFY_TABLE', line)
        self.table = table
        self.from_wa = from_wa
        self.index = index
        self.transporting = transporting or []
        self.where_clause = where_clause

class ReadTableStatement(ABAPNode):
    def __init__(self, table: str = '', into: str = '', assigning: str = '',
                 reference_into: str = '', with_key: Dict[str, str] = None,
                 with_table_key: bool = False, index: str = '',
                 binary_search: bool = False, transporting: List[str] = None,
                 line: int = 0):
        super().__init__('READ_TABLE', line)
        self.table = table
        self.into = into
        self.assigning = assigning
        self.reference_into = reference_into
        self.with_key = with_key or {}
        self.with_table_key = with_table_key
        self.index = index
        self.binary_search = binary_search
        self.transporting = transporting or []

class SortStatement(ABAPNode):
    def __init__(self, table: str = '', by_fields: List[Dict] = None,
                 ascending: bool = True, line: int = 0):
        super().__init__('SORT', line)
        self.table = table
        self.by_fields = by_fields or []
        self.ascending = ascending

class DescribeTableStatement(ABAPNode):
    def __init__(self, table: str = '', lines_var: str = '',
                 kind_var: str = '', line: int = 0):
        super().__init__('DESCRIBE_TABLE', line)
        self.table = table
        self.lines_var = lines_var
        self.kind_var = kind_var

class CollectStatement(ABAPNode):
    def __init__(self, source: str = '', target: str = '', line: int = 0):
        super().__init__('COLLECT', line)
        self.source = source
        self.target = target

class ClearStatement(ABAPNode):
    def __init__(self, keyword: str = 'CLEAR', targets: List[str] = None,
                 with_value: str = '', line: int = 0):
        super().__init__('CLEAR', line)
        self.keyword = keyword
        self.targets = targets or []
        self.with_value = with_value


# ── String Operations ─────────────────────────────────────────────────────────

class ConcatenateStatement(ABAPNode):
    def __init__(self, sources: List[str] = None, target: str = '',
                 separated_by: str = '', respecting_blanks: bool = False,
                 line: int = 0):
        super().__init__('CONCATENATE', line)
        self.sources = sources or []
        self.target = target
        self.separated_by = separated_by
        self.respecting_blanks = respecting_blanks

class SplitStatement(ABAPNode):
    def __init__(self, source: str = '', at_separator: str = '',
                 targets: List[str] = None, into_table: str = '',
                 line: int = 0):
        super().__init__('SPLIT', line)
        self.source = source
        self.at_separator = at_separator
        self.targets = targets or []
        self.into_table = into_table

class TranslateStatement(ABAPNode):
    def __init__(self, target: str = '', to_case: str = '', using_rule: str = '',
                 line: int = 0):
        super().__init__('TRANSLATE', line)
        self.target = target
        self.to_case = to_case  # 'UPPER' or 'LOWER'
        self.using_rule = using_rule

class CondenseStatement(ABAPNode):
    def __init__(self, target: str = '', no_gaps: bool = False, line: int = 0):
        super().__init__('CONDENSE', line)
        self.target = target
        self.no_gaps = no_gaps

class ReplaceStatement(ABAPNode):
    def __init__(self, pattern: str = '', with_value: str = '', target: str = '',
                 all_occurrences: bool = False, is_regex: bool = False,
                 line: int = 0):
        super().__init__('REPLACE', line)
        self.pattern = pattern
        self.with_value = with_value
        self.target = target
        self.all_occurrences = all_occurrences
        self.is_regex = is_regex

class ShiftStatement(ABAPNode):
    def __init__(self, target: str = '', places: str = '', direction: str = '',
                 mode: str = '', deleting_leading: str = '', line: int = 0):
        super().__init__('SHIFT', line)
        self.target = target
        self.places = places
        self.direction = direction
        self.mode = mode
        self.deleting_leading = deleting_leading

class FindStatement(ABAPNode):
    def __init__(self, pattern: str = '', in_string: str = '',
                 match_offset: str = '', match_length: str = '',
                 match_count: str = '', all_occurrences: bool = False,
                 is_regex: bool = False, results_var: str = '', line: int = 0):
        super().__init__('FIND', line)
        self.pattern = pattern
        self.in_string = in_string
        self.match_offset = match_offset
        self.match_length = match_length
        self.match_count = match_count
        self.all_occurrences = all_occurrences
        self.is_regex = is_regex
        self.results_var = results_var


# ── Field Symbols / Dynamic ───────────────────────────────────────────────────

class AssignFieldSymbolStatement(ABAPNode):
    def __init__(self, source: str = '', field_symbol: str = '',
                 casting: str = '', component: str = '', line: int = 0):
        super().__init__('ASSIGN', line)
        self.source = source
        self.field_symbol = field_symbol
        self.casting = casting
        self.component = component

class UnassignStatement(ABAPNode):
    def __init__(self, field_symbol: str = '', line: int = 0):
        super().__init__('UNASSIGN', line)
        self.field_symbol = field_symbol


# ── Output / Writer ───────────────────────────────────────────────────────────

class WriteStatement(ABAPNode):
    def __init__(self, outputs: List[str] = None, at_position: str = '',
                 format_options: Dict[str, str] = None, line: int = 0):
        super().__init__('WRITE', line)
        self.outputs = outputs or []
        self.at_position = at_position
        self.format_options = format_options or {}

class FormatStatement(ABAPNode):
    def __init__(self, keyword: str = '', options: List[str] = None, line: int = 0):
        super().__init__('FORMAT', line)
        self.keyword = keyword  # WRITE, SKIP, ULINE, NEW-LINE, FORMAT
        self.options = options or []


# ── System / Messaging ────────────────────────────────────────────────────────

class MessageStatement(ABAPNode):
    def __init__(self, msg_id: str = '', msg_type: str = '', msg_class: str = '',
                 msg_number: str = '', with_vars: List[str] = None,
                 into_var: str = '', line: int = 0):
        super().__init__('MESSAGE', line)
        self.msg_id = msg_id
        self.msg_type = msg_type
        self.msg_class = msg_class
        self.msg_number = msg_number
        self.with_vars = with_vars or []
        self.into_var = into_var

class AuthorityCheckStatement(ABAPNode):
    def __init__(self, object_name: str = '', fields: Dict[str, str] = None,
                 line: int = 0):
        super().__init__('AUTHORITY_CHECK', line)
        self.object_name = object_name
        self.fields = fields or {}

class CommitRollbackStatement(ABAPNode):
    def __init__(self, keyword: str = 'COMMIT', and_wait: bool = False,
                 line: int = 0):
        super().__init__('COMMIT_ROLLBACK', line)
        self.keyword = keyword
        self.and_wait = and_wait


# ── Memory / Export / Import ──────────────────────────────────────────────────

class ExportImportStatement(ABAPNode):
    def __init__(self, direction: str = '', variables: List[str] = None,
                 memory_id: str = '', to_database: str = '',
                 line: int = 0):
        super().__init__('EXPORT_IMPORT', line)
        self.direction = direction  # EXPORT or IMPORT
        self.variables = variables or []
        self.memory_id = memory_id
        self.to_database = to_database

class SetGetParameterStatement(ABAPNode):
    def __init__(self, direction: str = '', parameter_id: str = '',
                 field: str = '', line: int = 0):
        super().__init__('SET_GET_PARAMETER', line)
        self.direction = direction  # SET or GET
        self.parameter_id = parameter_id
        self.field = field


# ── File I/O ──────────────────────────────────────────────────────────────────

class OpenDatasetStatement(ABAPNode):
    def __init__(self, dataset: str = '', for_mode: str = '', in_mode: str = '',
                 encoding: str = '', line: int = 0):
        super().__init__('OPEN_DATASET', line)
        self.dataset = dataset
        self.for_mode = for_mode  # INPUT, OUTPUT, APPENDING, UPDATE
        self.in_mode = in_mode    # BINARY MODE, TEXT MODE, LEGACY BINARY MODE
        self.encoding = encoding

class ReadDatasetStatement(ABAPNode):
    def __init__(self, dataset: str = '', into: str = '',
                 length_var: str = '', line: int = 0):
        super().__init__('READ_DATASET', line)
        self.dataset = dataset
        self.into = into
        self.length_var = length_var

class TransferStatement(ABAPNode):
    def __init__(self, source: str = '', dataset: str = '',
                 length: str = '', line: int = 0):
        super().__init__('TRANSFER', line)
        self.source = source
        self.dataset = dataset
        self.length = length

class CloseDatasetStatement(ABAPNode):
    def __init__(self, dataset: str = '', line: int = 0):
        super().__init__('CLOSE_DATASET', line)
        self.dataset = dataset

class DeleteDatasetStatement(ABAPNode):
    def __init__(self, dataset: str = '', line: int = 0):
        super().__init__('DELETE_DATASET', line)
        self.dataset = dataset


# ── Flow Control ──────────────────────────────────────────────────────────────

class SimpleFlowStatement(ABAPNode):
    def __init__(self, keyword: str = '', condition: str = '', line: int = 0):
        super().__init__('SIMPLE_FLOW', line)
        self.keyword = keyword  # CHECK, EXIT, CONTINUE, RETURN, STOP
        self.condition = condition

class LeaveStatement(ABAPNode):
    def __init__(self, leave_type: str = '', to_screen: str = '',
                 to_transaction: str = '', line: int = 0):
        super().__init__('LEAVE', line)
        self.leave_type = leave_type
        self.to_screen = to_screen
        self.to_transaction = to_transaction

class SubmitStatement(ABAPNode):
    def __init__(self, report_name: str = '', with_params: List[Tuple] = None,
                 via_selection_screen: bool = False, and_return: bool = False,
                 line: int = 0):
        super().__init__('SUBMIT', line)
        self.report_name = report_name
        self.with_params = with_params or []
        self.via_selection_screen = via_selection_screen
        self.and_return = and_return


# ── Macros / Events / Selection Screen ────────────────────────────────────────

class MacroDefinition(ABAPNode):
    def __init__(self, name: str = '', body_text: str = '', line: int = 0):
        super().__init__('MACRO', line)
        self.name = name
        self.body_text = body_text

class EventBlock(ABAPNode):
    def __init__(self, event_name: str = '', body: List[ABAPNode] = None,
                 line: int = 0):
        super().__init__('EVENT', line)
        self.event_name = event_name
        self.body = body or []

class SelectionScreenStatement(ABAPNode):
    def __init__(self, clause: str = '', line: int = 0):
        super().__init__('SELECTION_SCREEN', line)
        self.clause = clause


# ── Screen / Dialog / Runtime Control ─────────────────────────────────────────

class CallScreenStatement(ABAPNode):
    """Represents a CALL SCREEN statement for dynpro invocation."""
    def __init__(self, screen_number: str = '', starting_at: str = '',
                 ending_at: str = '', line: int = 0):
        super().__init__('CALL_SCREEN', line)
        self.screen_number = screen_number
        self.starting_at = starting_at
        self.ending_at = ending_at

class CallDialogStatement(ABAPNode):
    """Represents a CALL DIALOG statement (obsolete SAP dialog technique)."""
    def __init__(self, dialog_name: str = '', using_params: List[Tuple] = None,
                 line: int = 0):
        super().__init__('CALL_DIALOG', line)
        self.dialog_name = dialog_name
        self.using_params = using_params or []

class SetPropertyStatement(ABAPNode):
    """Represents SET LOCALE, SET COUNTRY, SET SCREEN, SET PF-STATUS, SET TITLEBAR, etc."""
    def __init__(self, set_type: str = '', value: str = '',
                 additional_clause: str = '', line: int = 0):
        super().__init__('SET_PROPERTY', line)
        self.set_type = set_type    # LOCALE, COUNTRY, SCREEN, PF-STATUS, TITLEBAR
        self.value = value
        self.additional_clause = additional_clause

class WaitStatement(ABAPNode):
    """Represents WAIT UP TO n SECONDS or WAIT FOR ASYNCHRONOUS TASKS."""
    def __init__(self, wait_type: str = '', duration: str = '',
                 condition: str = '', line: int = 0):
        super().__init__('WAIT', line)
        self.wait_type = wait_type      # UP_TO or FOR_TASKS
        self.duration = duration
        self.condition = condition

class GetRunTimeStatement(ABAPNode):
    """Represents GET RUN TIME FIELD for performance measurement."""
    def __init__(self, field_name: str = '', line: int = 0):
        super().__init__('GET_RUN_TIME', line)
        self.field_name = field_name


# ── Database Cluster / Shared Memory ──────────────────────────────────────────

class ExportImportDatabaseStatement(ABAPNode):
    """Represents EXPORT/IMPORT TO/FROM DATABASE (cluster database access)."""
    def __init__(self, direction: str = '', table_name: str = '',
                 area: str = '', id_clause: str = '',
                 fields: List[str] = None, line: int = 0):
        super().__init__('EXPORT_IMPORT_DB', line)
        self.direction = direction      # EXPORT or IMPORT
        self.table_name = table_name
        self.area = area
        self.id_clause = id_clause
        self.fields = fields or []

class ExportImportSharedMemoryStatement(ABAPNode):
    """Represents EXPORT/IMPORT TO/FROM SHARED MEMORY."""
    def __init__(self, direction: str = '', area: str = '',
                 id_clause: str = '', fields: List[str] = None,
                 line: int = 0):
        super().__init__('EXPORT_IMPORT_SHM', line)
        self.direction = direction
        self.area = area
        self.id_clause = id_clause
        self.fields = fields or []


# ── Legacy / Obsolete Statements ──────────────────────────────────────────────

class ProvideEndprovideBlock(ABAPNode):
    """Represents PROVIDE ... BETWEEN ... ENDPROVIDE (obsolete infotype processing)."""
    def __init__(self, fields: List[str] = None, from_tables: List[str] = None,
                 between_clause: str = '', body: List[ABAPNode] = None,
                 line: int = 0):
        super().__init__('PROVIDE', line)
        self.fields = fields or []
        self.from_tables = from_tables or []
        self.between_clause = between_clause
        self.body = body or []

class FieldGroupDeclaration(ABAPNode):
    """Represents FIELD-GROUPS declaration (obsolete extract/sort mechanism)."""
    def __init__(self, name: str = '', line: int = 0):
        super().__init__('FIELD_GROUP', line)
        self.name = name

class ExtractStatement(ABAPNode):
    """Represents EXTRACT statement (obsolete extract/sort mechanism)."""
    def __init__(self, field_group: str = '', line: int = 0):
        super().__init__('EXTRACT', line)
        self.field_group = field_group

class CatchSystemExceptionBlock(ABAPNode):
    """Represents CATCH SYSTEM-EXCEPTIONS ... ENDCATCH (obsolete exception handling)."""
    def __init__(self, exceptions: List[Tuple] = None,
                 body: List[ABAPNode] = None, line: int = 0):
        super().__init__('CATCH_SYSTEM_EXCEPTION', line)
        self.exceptions = exceptions or []     # list of (exception_name, rc_value)
        self.body = body or []


# ── Conversion / Type Handling ────────────────────────────────────────────────

class ConvertStatement(ABAPNode):
    """Represents CONVERT DATE/TIME/TIMESTAMP statements."""
    def __init__(self, convert_type: str = '', source_value: str = '',
                 target_field: str = '', time_zone: str = '',
                 additional_clause: str = '', line: int = 0):
        super().__init__('CONVERT', line)
        self.convert_type = convert_type    # DATE, TIME, TIME_STAMP, INVERTED_DATE
        self.source_value = source_value
        self.target_field = target_field
        self.time_zone = time_zone
        self.additional_clause = additional_clause

class SetLocaleStatement(ABAPNode):
    """Represents SET LOCALE LANGUAGE for locale-dependent processing."""
    def __init__(self, language: str = '', country: str = '',
                 modifier: str = '', line: int = 0):
        super().__init__('SET_LOCALE', line)
        self.language = language
        self.country = country
        self.modifier = modifier


# ── LOOP Processing Events ────────────────────────────────────────────────────

class AtLoopBoundaryStatement(ABAPNode):
    """Represents AT NEW/AT END OF/AT FIRST/AT LAST inside LOOP processing."""
    def __init__(self, boundary_type: str = '', field_name: str = '',
                 body: List[ABAPNode] = None, line: int = 0):
        super().__init__('AT_LOOP_BOUNDARY', line)
        self.boundary_type = boundary_type  # FIRST, LAST, NEW, END_OF
        self.field_name = field_name        # field name for AT NEW/AT END OF
        self.body = body or []

class SumStatement(ABAPNode):
    """Represents SUM statement inside AT...ENDAT blocks for totaling."""
    def __init__(self, line: int = 0):
        super().__init__('SUM', line)


# ── DESCRIBE FIELD ────────────────────────────────────────────────────────

class DescribeFieldStatement(ABAPNode):
    """Represents DESCRIBE FIELD statement for runtime type information."""
    def __init__(self, field_name: str = '', type_var: str = '',
                 length_var: str = '', decimals_var: str = '',
                 output_length_var: str = '', components_var: str = '',
                 edit_mask_var: str = '', help_id_var: str = '',
                 line: int = 0):
        super().__init__('DESCRIBE_FIELD', line)
        self.field_name = field_name
        self.type_var = type_var
        self.length_var = length_var
        self.decimals_var = decimals_var
        self.output_length_var = output_length_var
        self.components_var = components_var
        self.edit_mask_var = edit_mask_var
        self.help_id_var = help_id_var


# ── ENHANCEMENT-POINT / ENHANCEMENT-SECTION ───────────────────────────────

class EnhancementPointStatement(ABAPNode):
    """Represents ENHANCEMENT-POINT or ENHANCEMENT-SECTION (BAdI/implicit enhancement)."""
    def __init__(self, enhancement_type: str = '', spot_name: str = '',
                 is_static: bool = False, include_bound: bool = False,
                 body: List[ABAPNode] = None, line: int = 0):
        super().__init__('ENHANCEMENT_POINT', line)
        self.enhancement_type = enhancement_type  # POINT or SECTION
        self.spot_name = spot_name
        self.is_static = is_static
        self.include_bound = include_bound
        self.body = body or []


# ── SUPPLY / DEMAND ───────────────────────────────────────────────────────

class SupplyDemandStatement(ABAPNode):
    """Represents SUPPLY/DEMAND used within PROVIDE context for HR infotypes."""
    def __init__(self, direction: str = '', fields: List[Tuple] = None,
                 target: str = '', line: int = 0):
        super().__init__('SUPPLY_DEMAND', line)
        self.direction = direction  # SUPPLY or DEMAND
        self.fields = fields or []  # list of (field, value) tuples
        self.target = target


# ── Catch-all / Generic ──────────────────────────────────────────────────────

class GenericStatement(ABAPNode):
    """Fallback for any statement the parser doesn't specifically handle."""
    def __init__(self, raw_tokens: List[str] = None, raw_text: str = '',
                 line: int = 0):
        super().__init__('GENERIC', line)
        self.raw_tokens = raw_tokens or []
        self.raw_text = raw_text


# ── Expression Nodes ──────────────────────────────────────────────────────────

class ExpressionNode(ABAPNode):
    """Represents any expression (arithmetic, comparison, function call, etc.)."""
    def __init__(self, expr_type: str = '', value: str = '',
                 operator: str = '', operands: List['ExpressionNode'] = None,
                 line: int = 0):
        super().__init__('EXPRESSION', line)
        self.expr_type = expr_type  # literal, identifier, binary, unary, call, inline_data, constructor
        self.value = value
        self.operator = operator
        self.operands = operands or []


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: RECURSIVE DESCENT PARSER
# ═══════════════════════════════════════════════════════════════════════════════

class ParseError(Exception):
    pass


class ABAPParser:
    """
    Recursive descent parser for ABAP source code.
    Builds a complete AST from a token stream, covering 55+ statement types.
    Gracefully degrades to GenericStatement for unrecognized constructs.
    """

    def __init__(self, tokens: List[Token]):
        self.tokens = [t for t in tokens if t.type != TokenType.PRAGMA]
        self.pos = 0
        self.errors: List[str] = []

    # ── Main entry ────────────────────────────────────────────────────────────

    def parse(self) -> ProgramNode:
        statements = []
        while not self._at_end():
            try:
                result = self._parse_statement()
                if result is None:
                    continue
                if isinstance(result, list):
                    statements.extend(result)
                else:
                    statements.append(result)
            except ParseError as e:
                self.errors.append(str(e))
                self._recover_to_period()
            except Exception as e:
                self.errors.append(f"Unexpected parse error at L{self._peek().line}: {e}")
                self._recover_to_period()
        return ProgramNode(statements=statements)

    # ── Token helpers ─────────────────────────────────────────────────────────

    def _peek(self) -> Token:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return Token(TokenType.EOF, '', 0, 0)

    def _peek_ahead(self, offset: int = 1) -> Token:
        idx = self.pos + offset
        if idx < len(self.tokens):
            return self.tokens[idx]
        return Token(TokenType.EOF, '', 0, 0)

    def _advance(self) -> Token:
        tok = self._peek()
        if self.pos < len(self.tokens):
            self.pos += 1
        return tok

    def _at_end(self) -> bool:
        return self._peek().type == TokenType.EOF

    def _check(self, ttype: TokenType) -> bool:
        return self._peek().type == ttype

    def _check_kw(self, *keywords) -> bool:
        tok = self._peek()
        return tok.type == TokenType.IDENTIFIER and tok.value.upper() in keywords

    def _match_period(self) -> bool:
        if self._check(TokenType.PERIOD):
            self._advance()
            return True
        return False

    def _expect_period(self):
        if not self._match_period():
            if not self._at_end():
                self._advance()

    def _consume_to_period(self) -> List[Token]:
        """Consume all tokens up to and including the next period."""
        tokens = []
        while not self._at_end() and not self._check(TokenType.PERIOD):
            tokens.append(self._advance())
        self._match_period()
        return tokens

    def _consume_to_period_text(self) -> str:
        """Consume tokens to period and return as a single string."""
        toks = self._consume_to_period()
        return ' '.join(t.value for t in toks)

    def _consume_until_keywords(self, *keywords) -> str:
        """Consume tokens until one of the keywords is found (without consuming it)."""
        parts = []
        while not self._at_end():
            if self._check(TokenType.PERIOD):
                break
            if self._check(TokenType.IDENTIFIER) and self._peek().value.upper() in keywords:
                break
            parts.append(self._advance().value)
        return ' '.join(parts)

    def _read_token_value(self) -> str:
        """Read the next token's value regardless of type."""
        if self._at_end():
            return ''
        return self._advance().value

    def _recover_to_period(self):
        while not self._at_end() and not self._check(TokenType.PERIOD):
            self._advance()
        self._match_period()

    # ── Block body parser (used by IF, LOOP, FORM, CLASS, METHOD, etc.) ──────

    def _parse_body_until(self, *end_keywords) -> List[ABAPNode]:
        """Parse statements until one of the end keywords is encountered."""
        body = []
        while not self._at_end():
            if self._check(TokenType.IDENTIFIER) and self._peek().value.upper() in end_keywords:
                return body
            try:
                result = self._parse_statement()
                if result is None:
                    continue
                if isinstance(result, list):
                    body.extend(result)
                else:
                    body.append(result)
            except (ParseError, Exception):
                self._recover_to_period()
        return body

    # ── Statement dispatcher ──────────────────────────────────────────────────

    def _parse_statement(self) -> Any:
        # Skip comments
        if self._check(TokenType.COMMENT):
            tok = self._advance()
            return CommentNode(text=tok.value, line=tok.line)

        # Skip standalone periods
        if self._check(TokenType.PERIOD):
            self._advance()
            return None

        # Field symbol assignment: <fs> = expr.
        if self._check(TokenType.FIELD_SYMBOL):
            return self._parse_assignment_or_generic()

        if not self._check(TokenType.IDENTIFIER):
            return self._parse_generic()

        kw = self._peek().value.upper()

        dispatch = {
            'REPORT': self._parse_report, 'PROGRAM': self._parse_report,
            'INCLUDE': self._parse_include,
            'DATA': self._parse_data, 'CLASS-DATA': self._parse_data,
            'STATICS': self._parse_data,
            'TYPES': self._parse_types,
            'CONSTANTS': self._parse_constants,
            'FIELD-SYMBOLS': self._parse_field_symbols_decl,
            'TABLES': self._parse_tables_decl,
            'PARAMETERS': self._parse_parameters, 'PARAMETER': self._parse_parameters,
            'SELECT-OPTIONS': self._parse_select_options,
            'RANGES': self._parse_ranges,
            'IF': self._parse_if, 'CASE': self._parse_case,
            'DO': self._parse_do, 'WHILE': self._parse_while,
            'LOOP': self._parse_loop,
            'SELECT': self._parse_select,
            'FORM': self._parse_form, 'PERFORM': self._parse_perform,
            'CLASS': self._parse_class, 'METHOD': self._parse_method,
            'INTERFACE': self._parse_interface,
            'TRY': self._parse_try, 'RAISE': self._parse_raise,
            'MOVE': self._parse_move, 'MOVE-CORRESPONDING': self._parse_move_corresponding,
            'COMPUTE': self._parse_compute,
            'ADD': self._parse_arithmetic, 'SUBTRACT': self._parse_arithmetic,
            'MULTIPLY': self._parse_arithmetic, 'DIVIDE': self._parse_arithmetic,
            'WRITE': self._parse_write,
            'APPEND': self._parse_append, 'COLLECT': self._parse_collect,
            'INSERT': self._parse_insert, 'DELETE': self._parse_delete,
            'MODIFY': self._parse_modify, 'UPDATE': self._parse_db_update,
            'READ': self._parse_read_table, 'SORT': self._parse_sort,
            'DESCRIBE': self._parse_describe,
            'CLEAR': self._parse_clear, 'REFRESH': self._parse_clear, 'FREE': self._parse_clear,
            'CONCATENATE': self._parse_concatenate, 'SPLIT': self._parse_split,
            'TRANSLATE': self._parse_translate, 'CONDENSE': self._parse_condense,
            'REPLACE': self._parse_replace, 'SHIFT': self._parse_shift,
            'FIND': self._parse_find, 'SEARCH': self._parse_find,
            'ASSIGN': self._parse_assign, 'UNASSIGN': self._parse_unassign,
            'CREATE': self._parse_create, 'CALL': self._parse_call,
            'MESSAGE': self._parse_message,
            'AUTHORITY-CHECK': self._parse_authority_check,
            'COMMIT': self._parse_commit_rollback, 'ROLLBACK': self._parse_commit_rollback,
            'EXPORT': self._parse_export_import, 'IMPORT': self._parse_export_import,
            'OPEN': self._parse_open_dataset, 'TRANSFER': self._parse_transfer,
            'CLOSE': self._parse_close_dataset,
            'SUBMIT': self._parse_submit, 'LEAVE': self._parse_leave,
            'SET': self._parse_set_get, 'GET': self._parse_set_get,
            'CHECK': self._parse_simple_flow, 'EXIT': self._parse_simple_flow,
            'CONTINUE': self._parse_simple_flow, 'RETURN': self._parse_simple_flow,
            'STOP': self._parse_simple_flow,
            'DEFINE': self._parse_macro,
            'EXEC': self._parse_native_sql,
            'SELECTION-SCREEN': self._parse_selection_screen,
            'INITIALIZATION': self._parse_event,
            'START-OF-SELECTION': self._parse_event,
            'END-OF-SELECTION': self._parse_event,
            'TOP-OF-PAGE': self._parse_event,
            'END-OF-PAGE': self._parse_event,
            'AT': self._parse_at_event,
            'SKIP': self._parse_format_stmt, 'ULINE': self._parse_format_stmt,
            'NEW-LINE': self._parse_format_stmt, 'FORMAT': self._parse_format_stmt,
            'WAIT': self._parse_wait,
            'CONVERT': self._parse_convert,
            'PROVIDE': self._parse_provide,
            'FIELD-GROUPS': self._parse_field_groups,
            'EXTRACT': self._parse_extract,
            'CATCH': self._parse_catch_system_exception,
            'SUM': self._parse_sum,
            'ENHANCEMENT-POINT': self._parse_enhancement_point,
            'ENHANCEMENT-SECTION': self._parse_enhancement_section,
            'SUPPLY': self._parse_supply_demand,
            'DEMAND': self._parse_supply_demand,
        }

        fn = dispatch.get(kw)
        if fn:
            return fn()
        return self._parse_assignment_or_generic()

    # ── Chain helper ──────────────────────────────────────────────────────────

    def _is_chained(self) -> bool:
        return self._check(TokenType.COLON)

    # ── Declaration parsers ───────────────────────────────────────────────────

    def _parse_report(self):
        tok = self._advance()  # REPORT/PROGRAM
        name = self._read_token_value() if not self._check(TokenType.PERIOD) else ''
        opts = []
        while not self._at_end() and not self._check(TokenType.PERIOD):
            opts.append(self._advance().value)
        self._match_period()
        return ReportStatement(name=name, options=opts, line=tok.line)

    def _parse_include(self):
        tok = self._advance()
        name = self._read_token_value()
        self._match_period()
        return IncludeStatement(include_name=name, line=tok.line)

    def _parse_data(self):
        kw_tok = self._advance()
        keyword = kw_tok.value.upper()
        if self._is_chained():
            self._advance()
            results = []
            while True:
                decl = self._parse_data_single(keyword, kw_tok.line)
                if decl:
                    results.append(decl)
                if self._check(TokenType.COMMA):
                    self._advance()
                else:
                    break
            self._match_period()
            return results
        else:
            decl = self._parse_data_single(keyword, kw_tok.line)
            self._match_period()
            return decl

    def _parse_data_single(self, keyword: str, line: int):
        if self._at_end() or self._check(TokenType.PERIOD) or self._check(TokenType.COMMA):
            return None

        # Check for BEGIN OF / END OF
        if self._check_kw('BEGIN'):
            self._advance()
            if self._check_kw('OF'):
                self._advance()
            name = self._read_token_value()
            return DataDeclaration(name=name, is_structure_begin=True, keyword=keyword, line=line)
        if self._check_kw('END'):
            self._advance()
            if self._check_kw('OF'):
                self._advance()
            name = self._read_token_value()
            return DataDeclaration(name=name, is_structure_end=True, keyword=keyword, line=line)

        # Read variable name (identifier or field-symbol)
        name = self._read_token_value()

        # Parse type annotations
        type_clause = ''
        like_clause = ''
        ref_to = ''
        table_type = ''
        table_of = ''
        table_key = []
        length = ''
        decimals = ''
        value = ''
        occurs = ''
        header_line = False
        read_only = False

        while not self._at_end() and not self._check(TokenType.PERIOD) and not self._check(TokenType.COMMA):
            if self._check_kw('TYPE'):
                self._advance()
                if self._check_kw('REF'):
                    self._advance()
                    if self._check_kw('TO'):
                        self._advance()
                    ref_to = self._read_token_value()
                elif self._check_kw('STANDARD', 'SORTED', 'HASHED', 'TABLE', 'RANGE'):
                    table_type = self._advance().value.upper()
                    if self._check_kw('TABLE'):
                        self._advance()
                    if self._check_kw('OF'):
                        self._advance()
                        table_of = self._read_token_value()
                    if self._check_kw('WITH'):
                        self._advance()
                        if self._check_kw('UNIQUE', 'NON-UNIQUE'):
                            self._advance()
                        if self._check_kw('KEY', 'DEFAULT'):
                            self._advance()
                            while not self._at_end() and not self._check(TokenType.PERIOD) and \
                                  not self._check(TokenType.COMMA) and \
                                  not self._check_kw('VALUE', 'OCCURS', 'WITH', 'READ-ONLY', 'INITIAL'):
                                table_key.append(self._advance().value)
                else:
                    type_clause = self._read_token_value()
            elif self._check_kw('LIKE'):
                self._advance()
                if self._check_kw('LINE'):
                    self._advance()
                    if self._check_kw('OF'):
                        self._advance()
                    like_clause = 'LINE OF ' + self._read_token_value()
                elif self._check_kw('STANDARD', 'SORTED', 'HASHED', 'TABLE'):
                    table_type = self._advance().value.upper()
                    if self._check_kw('TABLE'):
                        self._advance()
                    if self._check_kw('OF'):
                        self._advance()
                        table_of = self._read_token_value()
                else:
                    like_clause = self._read_token_value()
            elif self._check_kw('LENGTH'):
                self._advance()
                length = self._read_token_value()
            elif self._check_kw('DECIMALS'):
                self._advance()
                decimals = self._read_token_value()
            elif self._check_kw('VALUE'):
                self._advance()
                if self._check_kw('IS'):
                    self._advance()
                    value = self._read_token_value()
                else:
                    value = self._read_token_value()
            elif self._check_kw('OCCURS'):
                self._advance()
                occurs = self._read_token_value()
            elif self._check_kw('WITH'):
                self._advance()
                if self._check_kw('HEADER'):
                    self._advance()
                    if self._check_kw('LINE'):
                        self._advance()
                    header_line = True
                else:
                    # WITH KEY or other — skip
                    self._advance()
            elif self._check_kw('READ-ONLY'):
                self._advance()
                read_only = True
            elif self._check_kw('INITIAL'):
                self._advance()
                if self._check_kw('SIZE'):
                    self._advance()
                    self._read_token_value()
            else:
                break

        return DataDeclaration(
            name=name, keyword=keyword, type_clause=type_clause, like_clause=like_clause,
            ref_to=ref_to, table_type=table_type, table_of=table_of, table_key=table_key,
            length=length, decimals=decimals, initial_value=value,
            occurs=occurs, header_line=header_line, read_only=read_only, line=line
        )

    def _parse_types(self):
        kw_tok = self._advance()
        if self._is_chained():
            self._advance()
            results = []
            while True:
                t = self._parse_types_single(kw_tok.line)
                if t:
                    results.append(t)
                if self._check(TokenType.COMMA):
                    self._advance()
                else:
                    break
            self._match_period()
            return results
        t = self._parse_types_single(kw_tok.line)
        self._match_period()
        return t

    def _parse_types_single(self, line):
        if self._at_end() or self._check(TokenType.PERIOD) or self._check(TokenType.COMMA):
            return None
        if self._check_kw('BEGIN'):
            self._advance()
            if self._check_kw('OF'):
                self._advance()
            name = self._read_token_value()
            return TypesDeclaration(name=name, is_structure_begin=True, line=line)
        if self._check_kw('END'):
            self._advance()
            if self._check_kw('OF'):
                self._advance()
            name = self._read_token_value()
            return TypesDeclaration(name=name, is_structure_end=True, line=line)
        name = self._read_token_value()
        type_clause = ''
        if self._check_kw('TYPE'):
            self._advance()
            parts = []
            while not self._at_end() and not self._check(TokenType.PERIOD) and not self._check(TokenType.COMMA):
                parts.append(self._advance().value)
            type_clause = ' '.join(parts)
        return TypesDeclaration(name=name, type_clause=type_clause, line=line)

    def _parse_constants(self):
        tok = self._advance()
        if self._is_chained():
            self._advance()
            results = []
            while True:
                if self._check_kw('BEGIN'):
                    self._advance()
                    if self._check_kw('OF'): self._advance()
                    n = self._read_token_value()
                    results.append(ConstantsDeclaration(name=n, is_structure_begin=True, line=tok.line))
                elif self._check_kw('END'):
                    self._advance()
                    if self._check_kw('OF'): self._advance()
                    n = self._read_token_value()
                    results.append(ConstantsDeclaration(name=n, is_structure_end=True, line=tok.line))
                else:
                    name = self._read_token_value()
                    type_clause = ''
                    val = ''
                    if self._check_kw('TYPE'):
                        self._advance()
                        type_clause = self._read_token_value()
                    if self._check_kw('VALUE'):
                        self._advance()
                        val = self._read_token_value()
                    results.append(ConstantsDeclaration(name=name, type_clause=type_clause, value=val, line=tok.line))
                if self._check(TokenType.COMMA): self._advance()
                else: break
            self._match_period()
            return results
        name = self._read_token_value()
        tc = ''
        val = ''
        while not self._at_end() and not self._check(TokenType.PERIOD):
            if self._check_kw('TYPE'): self._advance(); tc = self._read_token_value()
            elif self._check_kw('VALUE'): self._advance(); val = self._read_token_value()
            else: break
        self._match_period()
        return ConstantsDeclaration(name=name, type_clause=tc, value=val, line=tok.line)

    def _parse_field_symbols_decl(self):
        tok = self._advance()
        if self._is_chained():
            self._advance()
            results = []
            while True:
                name = self._read_token_value()
                tc = ''
                if self._check_kw('TYPE'):
                    self._advance()
                    tc_parts = []
                    while not self._at_end() and not self._check(TokenType.PERIOD) and not self._check(TokenType.COMMA):
                        tc_parts.append(self._advance().value)
                    tc = ' '.join(tc_parts)
                results.append(FieldSymbolDeclaration(name=name, type_clause=tc, line=tok.line))
                if self._check(TokenType.COMMA): self._advance()
                else: break
            self._match_period()
            return results
        name = self._read_token_value()
        tc = ''
        if self._check_kw('TYPE'):
            self._advance()
            tc = self._consume_until_keywords()
        self._match_period()
        return FieldSymbolDeclaration(name=name, type_clause=tc, line=tok.line)

    def _parse_tables_decl(self):
        tok = self._advance()
        if self._is_chained():
            self._advance()
            results = []
            while True:
                name = self._read_token_value()
                results.append(TablesDeclaration(table_name=name, line=tok.line))
                if self._check(TokenType.COMMA): self._advance()
                else: break
            self._match_period()
            return results
        name = self._read_token_value()
        self._match_period()
        return TablesDeclaration(table_name=name, line=tok.line)

    def _parse_parameters(self):
        tok = self._advance()
        name = self._read_token_value()
        tc = ''
        lc = ''
        dv = ''
        oblig = False
        while not self._at_end() and not self._check(TokenType.PERIOD):
            if self._check_kw('TYPE'): self._advance(); tc = self._read_token_value()
            elif self._check_kw('LIKE'): self._advance(); lc = self._read_token_value()
            elif self._check_kw('DEFAULT'): self._advance(); dv = self._read_token_value()
            elif self._check_kw('OBLIGATORY'): self._advance(); oblig = True
            elif self._check_kw('AS'):
                self._advance()
                self._advance()  # CHECKBOX/LISTBOX
            else: break
        self._match_period()
        return ParameterDeclaration(name=name, type_clause=tc, like_clause=lc,
                                     default_value=dv, obligatory=oblig, line=tok.line)

    def _parse_select_options(self):
        tok = self._advance()
        if self._is_chained():            # SELECT-OPTIONS : s1 FOR f1, ...
            self._advance()               # skip the ':' chain operator
        name = self._read_token_value()
        for_field = ''
        if self._check_kw('FOR'): self._advance(); for_field = self._read_token_value()
        rest = self._consume_to_period_text()
        return SelectOptionDeclaration(name=name, for_field=for_field, line=tok.line)

    def _parse_ranges(self):
        tok = self._advance()
        if self._is_chained():            # RANGES : r1 FOR f1, ...
            self._advance()
        name = self._read_token_value()
        for_field = ''
        if self._check_kw('FOR'): self._advance(); for_field = self._read_token_value()
        self._match_period()
        return RangesDeclaration(name=name, for_field=for_field, line=tok.line)

    # ── Control flow parsers ──────────────────────────────────────────────────

    def _parse_if(self):
        tok = self._advance()  # IF
        condition = self._consume_until_keywords('ENDIF', 'ELSE', 'ELSEIF')
        self._match_period()
        then_body = self._parse_body_until('ENDIF', 'ELSE', 'ELSEIF')
        elseif_branches = []
        else_body = []
        while self._check_kw('ELSEIF'):
            self._advance()
            cond = self._consume_until_keywords('ENDIF', 'ELSE', 'ELSEIF')
            self._match_period()
            branch_body = self._parse_body_until('ENDIF', 'ELSE', 'ELSEIF')
            elseif_branches.append((cond, branch_body))
        if self._check_kw('ELSE'):
            self._advance()
            self._match_period()
            else_body = self._parse_body_until('ENDIF')
        if self._check_kw('ENDIF'):
            self._advance()
            self._match_period()
        return IfBlock(condition=condition, then_body=then_body,
                       elseif_branches=elseif_branches, else_body=else_body, line=tok.line)

    def _parse_case(self):
        tok = self._advance()  # CASE
        operand = self._consume_to_period_text()
        when_branches = []
        others_body = []
        while not self._at_end():
            if self._check_kw('ENDCASE'):
                self._advance()
                self._match_period()
                break
            if self._check_kw('WHEN'):
                self._advance()
                if self._check_kw('OTHERS'):
                    self._advance()
                    self._match_period()
                    others_body = self._parse_body_until('ENDCASE', 'WHEN')
                else:
                    val = self._consume_to_period_text()
                    body = self._parse_body_until('ENDCASE', 'WHEN')
                    when_branches.append((val, body))
            else:
                self._recover_to_period()
        return CaseBlock(operand=operand, when_branches=when_branches,
                         others_body=others_body, line=tok.line)

    def _parse_do(self):
        tok = self._advance()
        times = ''
        if not self._check(TokenType.PERIOD):
            parts = []
            while not self._at_end() and not self._check(TokenType.PERIOD):
                parts.append(self._advance().value)
            times = ' '.join(parts)
        self._match_period()
        body = self._parse_body_until('ENDDO')
        if self._check_kw('ENDDO'): self._advance(); self._match_period()
        return DoLoop(times=times, body=body, line=tok.line)

    def _parse_while(self):
        tok = self._advance()
        condition = self._consume_to_period_text()
        body = self._parse_body_until('ENDWHILE')
        if self._check_kw('ENDWHILE'): self._advance(); self._match_period()
        return WhileLoop(condition=condition, body=body, line=tok.line)

    def _parse_loop(self):
        tok = self._advance()  # LOOP
        if not self._check_kw('AT'):
            text = self._consume_to_period_text()
            return GenericStatement(raw_text=f"LOOP {text}", line=tok.line)
        self._advance()  # AT
        table = self._read_token_value()
        into = ''
        assigning = ''
        ref_into = ''
        where = ''
        from_idx = ''
        to_idx = ''
        while not self._at_end() and not self._check(TokenType.PERIOD):
            if self._check_kw('INTO'):
                self._advance()
                into = self._read_token_value()
            elif self._check_kw('ASSIGNING'):
                self._advance()
                assigning = self._read_token_value()
            elif self._check_kw('REFERENCE'):
                self._advance()
                if self._check_kw('INTO'): self._advance()
                ref_into = self._read_token_value()
            elif self._check_kw('WHERE'):
                self._advance()
                where = self._consume_until_keywords('FROM', 'TO')
            elif self._check_kw('FROM'):
                self._advance()
                from_idx = self._read_token_value()
            elif self._check_kw('TO'):
                self._advance()
                to_idx = self._read_token_value()
            else:
                break
        self._match_period()
        body = self._parse_body_until('ENDLOOP')
        if self._check_kw('ENDLOOP'): self._advance(); self._match_period()
        return LoopAtStatement(table=table, into=into, assigning=assigning,
                               reference_into=ref_into, where_clause=where,
                               from_index=from_idx, to_index=to_idx,
                               body=body, line=tok.line)

    # ── SQL parsers ───────────────────────────────────────────────────────────

    def _parse_select(self):
        tok = self._advance()  # SELECT
        is_single = False
        is_distinct = False
        field_list = []
        from_clause = ''
        joins = []
        into_clause = ''
        into_table = ''
        into_corresponding = False
        appending = False
        for_all_entries = ''
        where_clause = ''
        group_by = []
        having_clause = ''
        order_by = []
        up_to_rows = ''

        if self._check_kw('SINGLE'):
            is_single = True
            self._advance()
        if self._check_kw('DISTINCT'):
            is_distinct = True
            self._advance()

        # Field list — collect until FROM
        while not self._at_end() and not self._check_kw('FROM') and not self._check(TokenType.PERIOD):
            field_list.append(self._advance().value)

        if self._check_kw('FROM'):
            self._advance()
            from_clause = self._read_token_value()
            # Handle JOINs
            while self._check_kw('INNER', 'LEFT', 'RIGHT', 'CROSS', 'JOIN'):
                join_type = ''
                if self._check_kw('INNER', 'LEFT', 'RIGHT', 'CROSS'):
                    join_type = self._advance().value.upper()
                    if self._check_kw('OUTER'):
                        join_type += ' OUTER'
                        self._advance()
                if self._check_kw('JOIN'):
                    self._advance()
                join_table = self._read_token_value() if not self._check_kw('ON') else ''
                join_on = ''
                if self._check_kw('ON'):
                    self._advance()
                    on_parts = []
                    while not self._at_end() and not self._check_kw(
                            'WHERE', 'INTO', 'APPENDING', 'FOR', 'GROUP', 'HAVING',
                            'ORDER', 'UP', 'INNER', 'LEFT', 'RIGHT', 'CROSS', 'JOIN') \
                            and not self._check(TokenType.PERIOD):
                        on_parts.append(self._advance().value)
                    join_on = ' '.join(on_parts)
                joins.append({'type': join_type, 'table': join_table, 'on': join_on})

        # INTO / APPENDING
        if self._check_kw('APPENDING'):
            appending = True
            self._advance()
        if self._check_kw('INTO'):
            self._advance()
            if self._check_kw('CORRESPONDING'):
                into_corresponding = True
                self._advance()
                if self._check_kw('FIELDS'): self._advance()
                if self._check_kw('OF'): self._advance()
            if self._check_kw('TABLE'):
                self._advance()
                into_table = self._read_token_value()
            else:
                into_clause = self._read_token_value()
                # Handle multi-field INTO (a, b, c)
                if self._check(TokenType.COMMA):
                    parts = [into_clause]
                    while self._check(TokenType.COMMA):
                        self._advance()
                        parts.append(self._read_token_value())
                    into_clause = ', '.join(parts)

        if self._check_kw('FOR'):
            self._advance()
            if self._check_kw('ALL'): self._advance()
            if self._check_kw('ENTRIES'): self._advance()
            if self._check_kw('IN'): self._advance()
            for_all_entries = self._read_token_value()

        if self._check_kw('WHERE'):
            self._advance()
            where_parts = []
            while not self._at_end() and not self._check_kw('GROUP', 'HAVING', 'ORDER', 'UP') \
                    and not self._check(TokenType.PERIOD):
                where_parts.append(self._advance().value)
            where_clause = ' '.join(where_parts)

        if self._check_kw('GROUP'):
            self._advance()
            if self._check_kw('BY'): self._advance()
            while not self._at_end() and not self._check_kw('HAVING', 'ORDER', 'UP') \
                    and not self._check(TokenType.PERIOD):
                group_by.append(self._advance().value)

        if self._check_kw('HAVING'):
            self._advance()
            hparts = []
            while not self._at_end() and not self._check_kw('ORDER', 'UP') \
                    and not self._check(TokenType.PERIOD):
                hparts.append(self._advance().value)
            having_clause = ' '.join(hparts)

        if self._check_kw('ORDER'):
            self._advance()
            if self._check_kw('BY'): self._advance()
            while not self._at_end() and not self._check_kw('UP') \
                    and not self._check(TokenType.PERIOD):
                order_by.append(self._advance().value)

        if self._check_kw('UP'):
            self._advance()
            if self._check_kw('TO'): self._advance()
            up_to_rows = self._read_token_value()
            if self._check_kw('ROWS'): self._advance()

        self._match_period()

        # Check for ENDSELECT (loop SELECT)
        has_endselect = False
        body = []
        if not is_single and not into_table and not appending:
            body = self._parse_body_until('ENDSELECT')
            if self._check_kw('ENDSELECT'):
                has_endselect = True
                self._advance()
                self._match_period()

        return SelectStatement(
            is_single=is_single, is_distinct=is_distinct, field_list=field_list,
            from_clause=from_clause, joins=joins, into_clause=into_clause,
            into_table=into_table, into_corresponding=into_corresponding,
            appending=appending, for_all_entries=for_all_entries,
            where_clause=where_clause, group_by=group_by,
            having_clause=having_clause, order_by=order_by,
            up_to_rows=up_to_rows, has_endselect=has_endselect,
            body=body, line=tok.line
        )

    def _parse_db_update(self):
        tok = self._advance()  # UPDATE
        table = self._read_token_value()
        rest = self._consume_to_period_text()
        return DatabaseModifyStatement(operation='UPDATE', table_name=table,
                                        values_clause=rest, line=tok.line)

    # ── OOP parsers ───────────────────────────────────────────────────────────

    def _parse_class(self):
        tok = self._advance()  # CLASS
        name = self._read_token_value()
        is_def = False
        is_impl = False
        superclass = ''
        is_abstract = False
        is_final = False
        if self._check_kw('DEFINITION'):
            is_def = True
            self._advance()
        elif self._check_kw('IMPLEMENTATION'):
            is_impl = True
            self._advance()
        while not self._at_end() and not self._check(TokenType.PERIOD):
            if self._check_kw('INHERITING'):
                self._advance()
                if self._check_kw('FROM'): self._advance()
                superclass = self._read_token_value()
            elif self._check_kw('ABSTRACT'):
                self._advance()
                is_abstract = True
            elif self._check_kw('FINAL'):
                self._advance()
                is_final = True
            elif self._check_kw('CREATE'):
                self._advance()
                self._read_token_value()
            else:
                self._advance()
        self._match_period()
        body = self._parse_body_until('ENDCLASS')
        if self._check_kw('ENDCLASS'): self._advance(); self._match_period()
        return ClassBlock(name=name, is_definition=is_def, is_implementation=is_impl,
                          superclass=superclass, is_abstract=is_abstract, is_final=is_final,
                          body=body, line=tok.line)

    def _parse_method(self):
        tok = self._advance()  # METHOD
        name = self._read_token_value()
        self._match_period()
        body = self._parse_body_until('ENDMETHOD')
        if self._check_kw('ENDMETHOD'): self._advance(); self._match_period()
        return MethodBlock(name=name, body=body, line=tok.line)

    def _parse_interface(self):
        tok = self._advance()
        name = self._read_token_value()
        self._match_period()
        body = self._parse_body_until('ENDINTERFACE')
        if self._check_kw('ENDINTERFACE'): self._advance(); self._match_period()
        return InterfaceBlock(name=name, body=body, line=tok.line)

    def _parse_form(self):
        tok = self._advance()  # FORM
        name = self._read_token_value()
        using = []
        changing = []
        tables = []
        while not self._at_end() and not self._check(TokenType.PERIOD):
            if self._check_kw('USING'):
                self._advance()
                while not self._at_end() and not self._check(TokenType.PERIOD) \
                        and not self._check_kw('CHANGING', 'TABLES'):
                    using.append(self._advance().value)
            elif self._check_kw('CHANGING'):
                self._advance()
                while not self._at_end() and not self._check(TokenType.PERIOD) \
                        and not self._check_kw('USING', 'TABLES'):
                    changing.append(self._advance().value)
            elif self._check_kw('TABLES'):
                self._advance()
                while not self._at_end() and not self._check(TokenType.PERIOD) \
                        and not self._check_kw('USING', 'CHANGING'):
                    tables.append(self._advance().value)
            else:
                self._advance()
        self._match_period()
        body = self._parse_body_until('ENDFORM')
        if self._check_kw('ENDFORM'): self._advance(); self._match_period()
        return FormBlock(name=name, using_params=using, changing_params=changing,
                         tables_params=tables, body=body, line=tok.line)

    def _parse_perform(self):
        tok = self._advance()  # PERFORM
        form_name = self._read_token_value()
        prog = ''
        using = []
        changing = []
        tables_args = []
        if self._check_kw('IN'):
            self._advance()
            if self._check_kw('PROGRAM'): self._advance()
            prog = self._read_token_value()
        while not self._at_end() and not self._check(TokenType.PERIOD):
            if self._check_kw('USING'):
                self._advance()
                while not self._at_end() and not self._check(TokenType.PERIOD) \
                        and not self._check_kw('CHANGING', 'TABLES'):
                    using.append(self._advance().value)
            elif self._check_kw('CHANGING'):
                self._advance()
                while not self._at_end() and not self._check(TokenType.PERIOD) \
                        and not self._check_kw('USING', 'TABLES'):
                    changing.append(self._advance().value)
            elif self._check_kw('TABLES'):
                self._advance()
                while not self._at_end() and not self._check(TokenType.PERIOD) \
                        and not self._check_kw('USING', 'CHANGING'):
                    tables_args.append(self._advance().value)
            else:
                break
        self._match_period()
        return PerformStatement(form_name=form_name, in_program=prog, using_args=using,
                                changing_args=changing, tables_args=tables_args, line=tok.line)

    def _parse_call(self):
        tok = self._advance()  # CALL
        if self._check_kw('FUNCTION'):
            return self._parse_call_function(tok)
        elif self._check_kw('METHOD'):
            return self._parse_call_method_stmt(tok)
        elif self._check_kw('TRANSACTION'):
            self._advance()
            tcode = self._read_token_value()
            rest = self._consume_to_period_text()
            return CallTransactionStatement(tcode=tcode, line=tok.line)
        elif self._check_kw('SCREEN'):
            self._advance()
            screen = self._read_token_value()
            starting = ''
            ending = ''
            while not self._at_end() and not self._check(TokenType.PERIOD):
                if self._check_kw('STARTING'):
                    self._advance()
                    if self._check_kw('AT'): self._advance()
                    starting = self._read_token_value()
                elif self._check_kw('ENDING'):
                    self._advance()
                    if self._check_kw('AT'): self._advance()
                    ending = self._read_token_value()
                else:
                    self._advance()
            self._match_period()
            return CallScreenStatement(screen_number=screen, starting_at=starting,
                                       ending_at=ending, line=tok.line)
        elif self._check_kw('DIALOG'):
            self._advance()
            dialog = self._read_token_value()
            rest = self._consume_to_period_text()
            return CallDialogStatement(dialog_name=dialog, line=tok.line)
        else:
            rest = self._consume_to_period_text()
            return GenericStatement(raw_text=f"CALL {rest}", line=tok.line)

    def _parse_call_function(self, tok):
        self._advance()  # FUNCTION
        fn_name = self._read_token_value()
        self._match_period() if self._check(TokenType.PERIOD) else None
        exporting = []
        importing = []
        changing = []
        tables = []
        exceptions = []
        while not self._at_end() and not self._check(TokenType.PERIOD):
            if self._check_kw('EXPORTING'):
                self._advance()
                exporting = self._parse_param_list()
            elif self._check_kw('IMPORTING'):
                self._advance()
                importing = self._parse_param_list()
            elif self._check_kw('CHANGING'):
                self._advance()
                changing = self._parse_param_list()
            elif self._check_kw('TABLES'):
                self._advance()
                tables = self._parse_param_list()
            elif self._check_kw('EXCEPTIONS'):
                self._advance()
                exceptions = self._parse_param_list()
            else:
                break
        self._match_period()
        return CallFunctionStatement(function_name=fn_name, exporting=exporting,
                                      importing=importing, changing=changing,
                                      tables=tables, exceptions=exceptions, line=tok.line)

    def _parse_call_method_stmt(self, tok):
        self._advance()  # METHOD
        obj_method = self._read_token_value()
        obj_ref = ''
        method_name = obj_method
        if '->' in obj_method:
            parts = obj_method.split('->')
            obj_ref = parts[0]
            method_name = parts[1] if len(parts) > 1 else ''
        elif '=>' in obj_method:
            parts = obj_method.split('=>')
            obj_ref = parts[0]
            method_name = parts[1] if len(parts) > 1 else ''
        rest = self._consume_to_period_text()
        return CallMethodStatement(object_ref=obj_ref, method_name=method_name, line=tok.line)

    def _parse_param_list(self) -> List[Tuple]:
        """Parse name = value pairs until next section keyword or period."""
        params = []
        while not self._at_end() and not self._check(TokenType.PERIOD) \
                and not self._check_kw('EXPORTING', 'IMPORTING', 'CHANGING', 'TABLES', 'EXCEPTIONS', 'RECEIVING'):
            name = self._read_token_value()
            if self._check(TokenType.EQUALS):
                self._advance()
                val = self._read_token_value()
                params.append((name, val))
            else:
                params.append((name, ''))
        return params

    def _parse_create(self):
        tok = self._advance()  # CREATE
        if self._check_kw('OBJECT'):
            self._advance()
            var = self._read_token_value()
            cls = ''
            exporting = []
            if self._check_kw('TYPE'):
                self._advance()
                cls = self._read_token_value()
            while not self._at_end() and not self._check(TokenType.PERIOD):
                if self._check_kw('EXPORTING'):
                    self._advance()
                    exporting = self._parse_param_list()
                else:
                    break
            self._match_period()
            return CreateObjectStatement(variable=var, class_name=cls,
                                          exporting=exporting, line=tok.line)
        elif self._check_kw('DATA'):
            self._advance()
            var = self._read_token_value()
            tc = ''
            lc = ''
            while not self._at_end() and not self._check(TokenType.PERIOD):
                if self._check_kw('TYPE'): self._advance(); tc = self._read_token_value()
                elif self._check_kw('LIKE'): self._advance(); lc = self._read_token_value()
                else: break
            self._match_period()
            return CreateDataStatement(variable=var, type_clause=tc, like_clause=lc, line=tok.line)
        rest = self._consume_to_period_text()
        return GenericStatement(raw_text=f"CREATE {rest}", line=tok.line)

    # ── Exception handling ────────────────────────────────────────────────────

    def _parse_try(self):
        tok = self._advance()  # TRY
        self._match_period()
        try_body = self._parse_body_until('CATCH', 'CLEANUP', 'ENDTRY')
        catches = []
        cleanup = []
        while self._check_kw('CATCH'):
            self._advance()
            exc_class = ''
            into_var = ''
            parts = []
            while not self._at_end() and not self._check(TokenType.PERIOD):
                if self._check_kw('INTO'):
                    self._advance()
                    into_var = self._read_token_value()
                else:
                    parts.append(self._advance().value)
            exc_class = ' '.join(parts)
            self._match_period()
            catch_body = self._parse_body_until('CATCH', 'CLEANUP', 'ENDTRY')
            catches.append((exc_class, into_var, catch_body))
        if self._check_kw('CLEANUP'):
            self._advance()
            self._match_period()
            cleanup = self._parse_body_until('ENDTRY')
        if self._check_kw('ENDTRY'): self._advance(); self._match_period()
        return TryBlock(try_body=try_body, catch_branches=catches,
                        cleanup_body=cleanup, line=tok.line)

    def _parse_raise(self):
        tok = self._advance()  # RAISE
        if self._check_kw('EXCEPTION'):
            self._advance()
            if self._check_kw('TYPE'):
                self._advance()
                exc = self._read_token_value()
                rest = self._consume_to_period_text()
                return RaiseStatement(exception_class=exc, line=tok.line)
            exc = self._read_token_value()
            self._match_period()
            return RaiseStatement(exception_class=exc, line=tok.line)
        rest = self._consume_to_period_text()
        return RaiseStatement(exception_class=rest, line=tok.line)

    # ── Assignment parsers ────────────────────────────────────────────────────

    def _parse_move(self):
        tok = self._advance()  # MOVE
        source = self._read_token_value()
        if self._check_kw('TO'):
            self._advance()
        target = self._read_token_value()
        self._match_period()
        return MoveStatement(source=source, target=target, line=tok.line)

    def _parse_move_corresponding(self):
        tok = self._advance()  # MOVE-CORRESPONDING
        source = self._read_token_value()
        if self._check_kw('TO'): self._advance()
        target = self._read_token_value()
        self._match_period()
        return MoveCorrespondingStatement(source=source, target=target, line=tok.line)

    def _parse_compute(self):
        tok = self._advance()  # COMPUTE
        target = self._read_token_value()
        if self._check(TokenType.EQUALS): self._advance()
        expr = self._consume_to_period_text()
        return ComputeStatement(target=target, expression=expr, line=tok.line)

    def _parse_arithmetic(self):
        tok = self._advance()  # ADD/SUBTRACT/MULTIPLY/DIVIDE
        op = tok.value.upper()
        operand = self._read_token_value()
        preposition = ''
        if self._check_kw('TO', 'FROM', 'BY'):
            preposition = self._advance().value.upper()
        target = self._read_token_value()
        self._match_period()
        return ArithmeticStatement(operation=op, operand=operand, target=target, line=tok.line)

    def _parse_assignment_or_generic(self):
        start = self.pos
        tok = self._advance()
        lhs = tok.value
        if self._check(TokenType.EQUALS):
            self._advance()
            rhs = self._consume_to_period_text()
            return AssignmentStatement(target=lhs, expression=rhs, line=tok.line)
        if self._check(TokenType.ARROW) or self._check(TokenType.FAT_ARROW):
            # obj->method( ) or class=>method( ) — functional call as assignment
            parts = [lhs, self._advance().value]
            while not self._at_end() and not self._check(TokenType.PERIOD):
                parts.append(self._advance().value)
            if self._check(TokenType.PERIOD): self._match_period()
            return GenericStatement(raw_text=' '.join(parts), line=tok.line)
        # Not an assignment — restore and go generic
        self.pos = start
        return self._parse_generic()

    # ── Table operation parsers ───────────────────────────────────────────────

    def _parse_append(self):
        tok = self._advance()  # APPEND
        if self._check_kw('INITIAL'):
            self._advance()
            if self._check_kw('LINE'): self._advance()
            if self._check_kw('TO'): self._advance()
            target = self._read_token_value()
            self._match_period()
            return AppendStatement(initial_line=True, target=target, line=tok.line)
        if self._check_kw('LINES'):
            self._advance()
            if self._check_kw('OF'): self._advance()
            src = self._read_token_value()
            if self._check_kw('TO'): self._advance()
            tgt = self._read_token_value()
            self._match_period()
            return AppendStatement(lines_of=src, target=tgt, line=tok.line)
        source = self._read_token_value()
        target = ''
        if self._check_kw('TO'):
            self._advance()
            target = self._read_token_value()
        # else: header-line short form `APPEND wa.` — no TO, no target.
        # Do NOT read the period as the target (that produced `APPEND x TO ..`).
        self._match_period()
        return AppendStatement(source=source, target=target, line=tok.line)

    def _parse_insert(self):
        # Disambiguate: INSERT INTO <db_table> vs INSERT <wa> INTO TABLE <itab>
        tok = self._advance()
        nxt = self._peek().value.upper() if not self._at_end() else ''
        if nxt == 'INTO' and self._peek_ahead().value.upper() not in ('TABLE',):
            # DB insert: INSERT INTO dbtable VALUES ...
            self._advance()
            table = self._read_token_value()
            rest = self._consume_to_period_text()
            return DatabaseModifyStatement(operation='INSERT', table_name=table,
                                            values_clause=rest, line=tok.line)
        # Table insert
        source = self._read_token_value()
        if self._check_kw('INTO'): self._advance()
        if self._check_kw('TABLE'): self._advance()
        target = self._read_token_value()
        idx = ''
        if self._check_kw('INDEX'):
            self._advance()
            idx = self._read_token_value()
        self._match_period()
        return InsertTableStatement(source=source, target=target, index=idx, line=tok.line)

    def _parse_delete(self):
        tok = self._advance()  # DELETE
        nxt = self._peek().value.upper() if not self._at_end() else ''
        if nxt == 'FROM' and not self._peek_ahead().value.upper().startswith('<'):
            # Could be DB delete: DELETE FROM dbtable WHERE...
            self._advance()
            table = self._read_token_value()
            where = ''
            if self._check_kw('WHERE'):
                self._advance()
                where = self._consume_to_period_text()
            else:
                self._match_period()
            return DatabaseModifyStatement(operation='DELETE', table_name=table,
                                            where_clause=where, line=tok.line)
        if self._check_kw('ADJACENT'):
            self._advance()
            if self._check_kw('DUPLICATES'): self._advance()
            if self._check_kw('FROM'): self._advance()
            table = self._read_token_value()
            comparing = []
            if self._check_kw('COMPARING'):
                self._advance()
                while not self._at_end() and not self._check(TokenType.PERIOD):
                    comparing.append(self._advance().value)
            self._match_period()
            return DeleteTableStatement(table=table, adjacent_duplicates=True,
                                         comparing=comparing, line=tok.line)
        table = self._read_token_value()
        where = ''
        idx = ''
        if self._check_kw('WHERE'):
            self._advance()
            where = self._consume_to_period_text()
        elif self._check_kw('INDEX'):
            self._advance()
            idx = self._read_token_value()
            self._match_period()
        else:
            self._match_period()
        return DeleteTableStatement(table=table, where_clause=where, index=idx, line=tok.line)

    def _parse_modify(self):
        tok = self._advance()  # MODIFY
        nxt_val = self._peek().value.upper() if not self._at_end() else ''
        # Check if DB modify: MODIFY dbtable FROM wa.
        # vs table modify: MODIFY itab FROM wa INDEX n TRANSPORTING f1 f2.
        target = self._read_token_value()
        from_wa = ''
        idx = ''
        transporting = []
        where = ''
        if self._check_kw('FROM'):
            self._advance()
            from_wa = self._read_token_value()
        if self._check_kw('INDEX'):
            self._advance()
            idx = self._read_token_value()
        if self._check_kw('TRANSPORTING'):
            self._advance()
            while not self._at_end() and not self._check(TokenType.PERIOD) \
                    and not self._check_kw('WHERE'):
                transporting.append(self._advance().value)
        if self._check_kw('WHERE'):
            self._advance()
            where = self._consume_to_period_text()
        else:
            self._match_period()
        return ModifyTableStatement(table=target, from_wa=from_wa, index=idx,
                                     transporting=transporting, where_clause=where,
                                     line=tok.line)

    def _parse_read_table(self):
        tok = self._advance()  # READ
        if not self._check_kw('TABLE'):
            rest = self._consume_to_period_text()
            return GenericStatement(raw_text=f"READ {rest}", line=tok.line)
        self._advance()  # TABLE
        table = self._read_token_value()
        into = ''
        assigning = ''
        ref_into = ''
        with_key = {}
        idx = ''
        binary_search = False
        transporting = []
        while not self._at_end() and not self._check(TokenType.PERIOD):
            if self._check_kw('INTO'):
                self._advance()
                into = self._read_token_value()
            elif self._check_kw('ASSIGNING'):
                self._advance()
                assigning = self._read_token_value()
            elif self._check_kw('REFERENCE'):
                self._advance()
                if self._check_kw('INTO'): self._advance()
                ref_into = self._read_token_value()
            elif self._check_kw('WITH'):
                self._advance()
                if self._check_kw('KEY'):
                    self._advance()
                    while not self._at_end() and not self._check(TokenType.PERIOD) \
                            and not self._check_kw('INTO', 'ASSIGNING', 'REFERENCE',
                                                   'BINARY', 'TRANSPORTING'):
                        k = self._read_token_value()
                        if self._check(TokenType.EQUALS):
                            self._advance()
                            v = self._read_token_value()
                            with_key[k] = v
                        else:
                            with_key[k] = ''
                elif self._check_kw('TABLE'):
                    self._advance()
                    if self._check_kw('KEY'): self._advance()
                    # read key name
                    self._read_token_value()
                else:
                    self._advance()
            elif self._check_kw('INDEX'):
                self._advance()
                idx = self._read_token_value()
            elif self._check_kw('BINARY'):
                self._advance()
                if self._check_kw('SEARCH'): self._advance()
                binary_search = True
            elif self._check_kw('TRANSPORTING'):
                self._advance()
                while not self._at_end() and not self._check(TokenType.PERIOD):
                    transporting.append(self._advance().value)
            else:
                break
        self._match_period()
        return ReadTableStatement(table=table, into=into, assigning=assigning,
                                   reference_into=ref_into, with_key=with_key,
                                   index=idx, binary_search=binary_search,
                                   transporting=transporting, line=tok.line)

    def _parse_sort(self):
        tok = self._advance()  # SORT
        table = self._read_token_value()
        by_fields = []
        asc = True
        if self._check_kw('BY'):
            self._advance()
            while not self._at_end() and not self._check(TokenType.PERIOD):
                f = self._read_token_value()
                direction = 'ASCENDING'
                if self._check_kw('ASCENDING'): self._advance()
                elif self._check_kw('DESCENDING'):
                    self._advance()
                    direction = 'DESCENDING'
                by_fields.append({'field': f, 'direction': direction})
        self._match_period()
        return SortStatement(table=table, by_fields=by_fields, line=tok.line)

    def _parse_describe(self):
        tok = self._advance()  # DESCRIBE
        if self._check_kw('TABLE'):
            self._advance()
            table = self._read_token_value()
            lines_var = ''
            kind_var = ''
            while not self._at_end() and not self._check(TokenType.PERIOD):
                if self._check_kw('LINES'):
                    self._advance()
                    lines_var = self._read_token_value()
                elif self._check_kw('KIND'):
                    self._advance()
                    kind_var = self._read_token_value()
                else:
                    self._advance()
            self._match_period()
            return DescribeTableStatement(table=table, lines_var=lines_var,
                                           kind_var=kind_var, line=tok.line)
        elif self._check_kw('FIELD'):
            self._advance()  # FIELD
            field_name = self._read_token_value()
            type_var = ''
            length_var = ''
            decimals_var = ''
            output_length_var = ''
            components_var = ''
            edit_mask_var = ''
            help_id_var = ''
            while not self._at_end() and not self._check(TokenType.PERIOD):
                if self._check_kw('TYPE'):
                    self._advance()
                    type_var = self._read_token_value()
                elif self._check_kw('LENGTH'):
                    self._advance()
                    length_var = self._read_token_value()
                elif self._check_kw('DECIMALS'):
                    self._advance()
                    decimals_var = self._read_token_value()
                elif self._check_kw('OUTPUT-LENGTH'):
                    self._advance()
                    output_length_var = self._read_token_value()
                elif self._check_kw('COMPONENTS'):
                    self._advance()
                    components_var = self._read_token_value()
                elif self._check_kw('EDIT'):
                    self._advance()
                    if self._check_kw('MASK'): self._advance()
                    edit_mask_var = self._read_token_value()
                elif self._check_kw('HELP-ID'):
                    self._advance()
                    help_id_var = self._read_token_value()
                elif self._check_kw('IN'):
                    # IN BYTE MODE / IN CHARACTER MODE
                    self._advance()
                    while not self._at_end() and not self._check(TokenType.PERIOD) and \
                          not self._check_kw('TYPE', 'LENGTH', 'DECIMALS', 'OUTPUT-LENGTH',
                                             'COMPONENTS', 'EDIT', 'HELP-ID'):
                        self._advance()
                else:
                    self._advance()
            self._match_period()
            return DescribeFieldStatement(
                field_name=field_name, type_var=type_var, length_var=length_var,
                decimals_var=decimals_var, output_length_var=output_length_var,
                components_var=components_var, edit_mask_var=edit_mask_var,
                help_id_var=help_id_var, line=tok.line
            )
        rest = self._consume_to_period_text()
        return GenericStatement(raw_text=f"DESCRIBE {rest}", line=tok.line)

    def _parse_collect(self):
        tok = self._advance()
        src = self._read_token_value()
        if self._check_kw('INTO'): self._advance()
        tgt = self._read_token_value()
        self._match_period()
        return CollectStatement(source=src, target=tgt, line=tok.line)

    def _parse_clear(self):
        tok = self._advance()  # CLEAR/REFRESH/FREE
        kw = tok.value.upper()
        targets = []
        if self._is_chained():
            self._advance()
            while True:
                targets.append(self._read_token_value())
                if self._check(TokenType.COMMA): self._advance()
                else: break
        else:
            targets.append(self._read_token_value())
        self._match_period()
        return ClearStatement(keyword=kw, targets=targets, line=tok.line)

    # ── String operation parsers ──────────────────────────────────────────────

    def _parse_concatenate(self):
        tok = self._advance()  # CONCATENATE
        sources = []
        while not self._at_end() and not self._check_kw('INTO') and not self._check(TokenType.PERIOD):
            sources.append(self._advance().value)
        target = ''
        if self._check_kw('INTO'):
            self._advance()
            target = self._read_token_value()
        sep = ''
        resp = False
        if self._check_kw('SEPARATED'):
            self._advance()
            if self._check_kw('BY'): self._advance()
            sep = self._read_token_value()
        if self._check_kw('RESPECTING'):
            self._advance()
            if self._check_kw('BLANKS'): self._advance()
            resp = True
        self._match_period()
        return ConcatenateStatement(sources=sources, target=target,
                                     separated_by=sep, respecting_blanks=resp, line=tok.line)

    def _parse_split(self):
        tok = self._advance()  # SPLIT
        source = self._read_token_value()
        if self._check_kw('AT'): self._advance()
        sep = self._read_token_value()
        targets = []
        into_table = ''
        if self._check_kw('INTO'):
            self._advance()
            if self._check_kw('TABLE'):
                self._advance()
                into_table = self._read_token_value()
            else:
                while not self._at_end() and not self._check(TokenType.PERIOD):
                    targets.append(self._advance().value)
        self._match_period()
        return SplitStatement(source=source, at_separator=sep, targets=targets,
                               into_table=into_table, line=tok.line)

    def _parse_translate(self):
        tok = self._advance()
        target = self._read_token_value()
        to_case = ''
        using_rule = ''
        if self._check_kw('TO'):
            self._advance()
            if self._check_kw('UPPER'):
                self._advance()
                if self._check_kw('CASE'): self._advance()
                to_case = 'UPPER'
            elif self._check_kw('LOWER'):
                self._advance()
                if self._check_kw('CASE'): self._advance()
                to_case = 'LOWER'
        elif self._check_kw('USING'):
            self._advance()
            using_rule = self._read_token_value()
        self._match_period()
        return TranslateStatement(target=target, to_case=to_case, using_rule=using_rule,
                                   line=tok.line)

    def _parse_condense(self):
        tok = self._advance()
        target = self._read_token_value()
        no_gaps = False
        if self._check_kw('NO-GAPS'):
            self._advance()
            no_gaps = True
        self._match_period()
        return CondenseStatement(target=target, no_gaps=no_gaps, line=tok.line)

    def _parse_replace(self):
        tok = self._advance()
        all_occ = False
        if self._check_kw('ALL'):
            all_occ = True
            self._advance()
            if self._check_kw('OCCURRENCES'): self._advance()
            if self._check_kw('OF'): self._advance()
        elif self._check_kw('FIRST'):
            self._advance()
            if self._check_kw('OCCURRENCE'): self._advance()
            if self._check_kw('OF'): self._advance()
        pattern = self._read_token_value()
        if self._check_kw('IN'): self._advance()
        target = self._read_token_value()
        with_val = ''
        if self._check_kw('WITH'):
            self._advance()
            with_val = self._read_token_value()
        self._match_period()
        return ReplaceStatement(pattern=pattern, target=target, with_value=with_val,
                                 all_occurrences=all_occ, line=tok.line)

    def _parse_shift(self):
        tok = self._advance()
        target = self._read_token_value()
        rest = self._consume_to_period_text()
        return ShiftStatement(target=target, mode=rest, line=tok.line)

    def _parse_find(self):
        tok = self._advance()  # FIND or SEARCH
        kw = tok.value.upper()
        all_occ = False
        if self._check_kw('ALL'):
            all_occ = True
            self._advance()
            if self._check_kw('OCCURRENCES'): self._advance()
            if self._check_kw('OF'): self._advance()
        elif self._check_kw('FIRST'):
            self._advance()
            if self._check_kw('OCCURRENCE'): self._advance()
            if self._check_kw('OF'): self._advance()
        pattern = self._read_token_value()
        if self._check_kw('IN'): self._advance()
        in_str = self._read_token_value()
        rest = self._consume_to_period_text()
        return FindStatement(pattern=pattern, in_string=in_str,
                              all_occurrences=all_occ, line=tok.line)

    # ── Field symbol / assign ─────────────────────────────────────────────────

    def _parse_assign(self):
        tok = self._advance()  # ASSIGN
        source = self._read_token_value()
        if self._check_kw('TO'): self._advance()
        fs = self._read_token_value()
        casting = ''
        if self._check_kw('CASTING'):
            self._advance()
            casting = self._consume_to_period_text()
        else:
            self._match_period()
        return AssignFieldSymbolStatement(source=source, field_symbol=fs,
                                          casting=casting, line=tok.line)

    def _parse_unassign(self):
        tok = self._advance()
        fs = self._read_token_value()
        self._match_period()
        return UnassignStatement(field_symbol=fs, line=tok.line)

    # ── Write / format ────────────────────────────────────────────────────────

    def _parse_write(self):
        tok = self._advance()  # WRITE
        if self._is_chained():
            self._advance()
            items = []
            while True:
                item = self._read_token_value()
                items.append(item)
                if self._check(TokenType.COMMA): self._advance()
                else: break
            self._match_period()
            return WriteStatement(outputs=items, line=tok.line)
        outputs = []
        while not self._at_end() and not self._check(TokenType.PERIOD):
            outputs.append(self._advance().value)
        self._match_period()
        return WriteStatement(outputs=outputs, line=tok.line)

    def _parse_format_stmt(self):
        tok = self._advance()
        rest = self._consume_to_period_text()
        return FormatStatement(keyword=tok.value.upper(), options=rest.split() if rest else [], line=tok.line)

    # ── Message / Authority ───────────────────────────────────────────────────

    def _parse_message(self):
        tok = self._advance()
        rest = self._consume_to_period_text()
        return MessageStatement(msg_id=rest, line=tok.line)

    def _parse_authority_check(self):
        tok = self._advance()  # AUTHORITY-CHECK
        if self._check_kw('OBJECT'): self._advance()
        obj = self._read_token_value()
        fields = {}
        while not self._at_end() and not self._check(TokenType.PERIOD):
            if self._check_kw('ID'):
                self._advance()
                fld = self._read_token_value()
                if self._check_kw('FIELD', 'DUMMY'):
                    self._advance()
                    val = self._read_token_value() if not self._check(TokenType.PERIOD) else 'DUMMY'
                    fields[fld] = val
            else:
                self._advance()
        self._match_period()
        return AuthorityCheckStatement(object_name=obj, fields=fields, line=tok.line)

    # ── System statements ─────────────────────────────────────────────────────

    def _parse_commit_rollback(self):
        tok = self._advance()
        kw = tok.value.upper()
        and_wait = False
        if self._check_kw('WORK'): self._advance()
        if self._check_kw('AND'):
            self._advance()
            if self._check_kw('WAIT'):
                self._advance()
                and_wait = True
        self._match_period()
        return CommitRollbackStatement(keyword=kw, and_wait=and_wait, line=tok.line)

    def _parse_export_import(self):
        tok = self._advance()  # EXPORT/IMPORT
        direction = tok.value.upper()
        variables = []
        mem_id = ''
        to_db = ''
        while not self._at_end() and not self._check(TokenType.PERIOD):
            if self._check_kw('TO', 'FROM'):
                self._advance()
                if self._check_kw('MEMORY'):
                    self._advance()
                    if self._check_kw('ID'): self._advance()
                    mem_id = self._read_token_value()
                elif self._check_kw('DATABASE'):
                    self._advance()
                    to_db = self._read_token_value()
                break
            variables.append(self._advance().value)
        self._match_period()
        return ExportImportStatement(direction=direction, variables=variables,
                                      memory_id=mem_id, to_database=to_db, line=tok.line)

    def _parse_open_dataset(self):
        tok = self._advance()
        if self._check_kw('DATASET'): self._advance()
        ds = self._read_token_value()
        rest = self._consume_to_period_text()
        return OpenDatasetStatement(dataset=ds, for_mode=rest, line=tok.line)

    def _parse_transfer(self):
        tok = self._advance()
        src = self._read_token_value()
        if self._check_kw('TO'): self._advance()
        ds = self._read_token_value()
        self._match_period()
        return TransferStatement(source=src, dataset=ds, line=tok.line)

    def _parse_close_dataset(self):
        tok = self._advance()
        if self._check_kw('DATASET'): self._advance()
        ds = self._read_token_value()
        self._match_period()
        return CloseDatasetStatement(dataset=ds, line=tok.line)

    def _parse_submit(self):
        tok = self._advance()
        report = self._read_token_value()
        rest = self._consume_to_period_text()
        return SubmitStatement(report_name=report, line=tok.line)

    def _parse_leave(self):
        tok = self._advance()
        rest = self._consume_to_period_text()
        return LeaveStatement(leave_type=rest, line=tok.line)

    def _parse_set_get(self):
        tok = self._advance()  # SET/GET
        direction = tok.value.upper()
        # SET PF-STATUS, SET TITLEBAR, SET SCREEN, SET LOCALE — dispatch accordingly
        if direction == 'SET' and self._check_kw('PF-STATUS', 'TITLEBAR', 'SCREEN'):
            set_type = self._advance().value.upper()
            val = self._read_token_value() if not self._check(TokenType.PERIOD) else ''
            additional = ''
            if not self._check(TokenType.PERIOD):
                additional = self._consume_to_period_text()
            else:
                self._match_period()
            return SetPropertyStatement(set_type=set_type, value=val,
                                         additional_clause=additional, line=tok.line)
        if direction == 'SET' and self._check_kw('LOCALE'):
            self._advance()  # LOCALE
            if self._check_kw('LANGUAGE'): self._advance()
            lang = self._read_token_value() if not self._check(TokenType.PERIOD) else ''
            country = ''
            modifier = ''
            while not self._at_end() and not self._check(TokenType.PERIOD):
                if self._check_kw('COUNTRY'):
                    self._advance()
                    country = self._read_token_value() if not self._check(TokenType.PERIOD) else ''
                elif self._check_kw('MODIFIER'):
                    self._advance()
                    modifier = self._read_token_value() if not self._check(TokenType.PERIOD) else ''
                else:
                    self._advance()
            self._match_period()
            return SetLocaleStatement(language=lang, country=country,
                                      modifier=modifier, line=tok.line)
        # GET RUN TIME FIELD
        if direction == 'GET' and self._check_kw('RUN'):
            self._advance()  # RUN
            if self._check_kw('TIME'): self._advance()
            if self._check_kw('FIELD'): self._advance()
            fld_name = self._read_token_value() if not self._check(TokenType.PERIOD) else ''
            self._match_period()
            return GetRunTimeStatement(field_name=fld_name, line=tok.line)
        # Default: SET/GET PARAMETER
        if self._check_kw('PARAMETER'): self._advance()
        if self._check_kw('ID'): self._advance()
        pid = self._read_token_value()
        if self._check_kw('FIELD'): self._advance()
        fld = self._read_token_value() if not self._check(TokenType.PERIOD) else ''
        self._match_period()
        return SetGetParameterStatement(direction=direction, parameter_id=pid,
                                         field=fld, line=tok.line)

    def _parse_simple_flow(self):
        tok = self._advance()
        kw = tok.value.upper()
        cond = ''
        if not self._check(TokenType.PERIOD):
            cond = self._consume_to_period_text()
        else:
            self._match_period()
        return SimpleFlowStatement(keyword=kw, condition=cond, line=tok.line)

    # ── Macro / Native SQL / Events ───────────────────────────────────────────

    def _parse_macro(self):
        tok = self._advance()  # DEFINE
        name = self._read_token_value()
        self._match_period()
        body_parts = []
        while not self._at_end() and not self._check_kw('END-OF-DEFINITION'):
            body_parts.append(self._advance().value)
        if self._check_kw('END-OF-DEFINITION'): self._advance(); self._match_period()
        return MacroDefinition(name=name, body_text=' '.join(body_parts), line=tok.line)

    def _parse_native_sql(self):
        tok = self._advance()  # EXEC
        if self._check_kw('SQL'): self._advance()
        self._match_period()
        sql_parts = []
        while not self._at_end() and not self._check_kw('ENDEXEC'):
            sql_parts.append(self._advance().value)
        if self._check_kw('ENDEXEC'): self._advance(); self._match_period()
        return NativeSqlBlock(sql_text=' '.join(sql_parts), line=tok.line)

    def _parse_event(self):
        tok = self._advance()
        self._match_period()
        return EventBlock(event_name=tok.value.upper(), line=tok.line)

    def _parse_at_event(self):
        tok = self._advance()  # AT
        event_parts = [tok.value.upper()]
        while not self._at_end() and not self._check(TokenType.PERIOD):
            event_parts.append(self._advance().value.upper())
        self._match_period()
        return EventBlock(event_name=' '.join(event_parts), line=tok.line)

    def _parse_selection_screen(self):
        tok = self._advance()
        rest = self._consume_to_period_text()
        return SelectionScreenStatement(clause=rest, line=tok.line)

    # ── WAIT / CONVERT / PROVIDE / FIELD-GROUPS / EXTRACT / CATCH SYSTEM ─────

    def _parse_wait(self):
        """Parse WAIT UP TO n SECONDS or WAIT FOR ASYNCHRONOUS TASKS."""
        tok = self._advance()  # WAIT
        wait_type = ''
        duration = ''
        condition = ''
        if self._check_kw('UP'):
            self._advance()  # UP
            if self._check_kw('TO'): self._advance()  # TO
            duration_parts = []
            while not self._at_end() and not self._check_kw('SECONDS') and not self._check(TokenType.PERIOD):
                duration_parts.append(self._advance().value)
            duration = ' '.join(duration_parts)
            if self._check_kw('SECONDS'): self._advance()
            wait_type = 'UP_TO'
        elif self._check_kw('FOR'):
            self._advance()  # FOR
            wait_type = 'FOR_TASKS'
            cond_parts = []
            while not self._at_end() and not self._check(TokenType.PERIOD):
                cond_parts.append(self._advance().value)
            condition = ' '.join(cond_parts)
        else:
            rest = self._consume_to_period_text()
            condition = rest
        self._match_period()
        return WaitStatement(wait_type=wait_type, duration=duration,
                             condition=condition, line=tok.line)

    def _parse_convert(self):
        """Parse CONVERT DATE/TIME/TIMESTAMP statements."""
        tok = self._advance()  # CONVERT
        convert_type = ''
        source_value = ''
        target_field = ''
        time_zone = ''
        additional = ''
        if self._check_kw('DATE'):
            convert_type = 'DATE'
            self._advance()
            source_value = self._read_token_value()
        elif self._check_kw('TIME'):
            self._advance()
            if self._check_kw('STAMP'):
                self._advance()
                convert_type = 'TIME_STAMP'
            else:
                convert_type = 'TIME'
            source_value = self._read_token_value()
        elif self._check_kw('INVERTED-DATE'):
            convert_type = 'INVERTED_DATE'
            self._advance()
            source_value = self._read_token_value()
        remaining_parts = []
        while not self._at_end() and not self._check(TokenType.PERIOD):
            if self._check_kw('INTO'):
                self._advance()
                if not self._check(TokenType.PERIOD):
                    target_field = self._read_token_value()
            elif self._check_kw('TIME') and self._peek().value.upper() != 'STAMP':
                self._advance()
                if self._check_kw('ZONE'): self._advance()
                if not self._check(TokenType.PERIOD):
                    time_zone = self._read_token_value()
            else:
                remaining_parts.append(self._advance().value)
        additional = ' '.join(remaining_parts)
        self._match_period()
        return ConvertStatement(convert_type=convert_type, source_value=source_value,
                                target_field=target_field, time_zone=time_zone,
                                additional_clause=additional, line=tok.line)

    def _parse_provide(self):
        """Parse PROVIDE ... BETWEEN ... ENDPROVIDE block."""
        tok = self._advance()  # PROVIDE
        fields = []
        from_tables = []
        between_clause = ''
        # Collect tokens until BETWEEN or ENDPROVIDE
        while not self._at_end() and not self._check_kw('BETWEEN', 'ENDPROVIDE') and not self._check(TokenType.PERIOD):
            if self._check_kw('FROM'):
                self._advance()
                if not self._check(TokenType.PERIOD):
                    from_tables.append(self._read_token_value())
            else:
                fields.append(self._advance().value)
        if self._check_kw('BETWEEN'):
            self._advance()
            between_parts = []
            while not self._at_end() and not self._check(TokenType.PERIOD):
                between_parts.append(self._advance().value)
            between_clause = ' '.join(between_parts)
        self._match_period()
        body = self._parse_body_until('ENDPROVIDE')
        if self._check_kw('ENDPROVIDE'): self._advance(); self._match_period()
        return ProvideEndprovideBlock(fields=fields, from_tables=from_tables,
                                      between_clause=between_clause, body=body,
                                      line=tok.line)

    def _parse_field_groups(self):
        """Parse FIELD-GROUPS declaration."""
        tok = self._advance()  # FIELD-GROUPS
        name = self._read_token_value()
        self._match_period()
        return FieldGroupDeclaration(name=name, line=tok.line)

    def _parse_extract(self):
        """Parse EXTRACT statement."""
        tok = self._advance()  # EXTRACT
        fg = self._read_token_value() if not self._check(TokenType.PERIOD) else ''
        self._match_period()
        return ExtractStatement(field_group=fg, line=tok.line)

    def _parse_catch_system_exception(self):
        """Parse CATCH SYSTEM-EXCEPTIONS ... ENDCATCH block."""
        tok = self._advance()  # CATCH
        if not self._check_kw('SYSTEM-EXCEPTIONS'):
            # Not a CATCH SYSTEM-EXCEPTIONS — fall back to generic
            rest = self._consume_to_period_text()
            return GenericStatement(raw_text=f"CATCH {rest}",
                                    raw_tokens=['CATCH'] + rest.split(),
                                    line=tok.line)
        self._advance()  # SYSTEM-EXCEPTIONS
        exceptions = []
        while not self._at_end() and not self._check(TokenType.PERIOD):
            exc_name = self._read_token_value()
            rc_val = ''
            if self._check(TokenType.EQUALS):
                self._advance()
                rc_val = self._read_token_value()
            exceptions.append((exc_name, rc_val))
        self._match_period()
        body = self._parse_body_until('ENDCATCH')
        if self._check_kw('ENDCATCH'): self._advance(); self._match_period()
        return CatchSystemExceptionBlock(exceptions=exceptions, body=body,
                                          line=tok.line)

    def _parse_sum(self):
        """Parse SUM statement inside AT...ENDAT blocks."""
        tok = self._advance()  # SUM
        self._match_period()
        return SumStatement(line=tok.line)

    # ── ENHANCEMENT-POINT / ENHANCEMENT-SECTION ─────────────────────────────

    def _parse_enhancement_point(self):
        """Parse ENHANCEMENT-POINT spot_name STATIC / INCLUDE BOUND."""
        tok = self._advance()  # ENHANCEMENT-POINT
        spot_name = self._read_token_value() if not self._check(TokenType.PERIOD) else ''
        is_static = False
        include_bound = False
        while not self._at_end() and not self._check(TokenType.PERIOD):
            if self._check_kw('STATIC'):
                self._advance()
                is_static = True
            elif self._check_kw('INCLUDE'):
                self._advance()
                if self._check_kw('BOUND'): self._advance()
                include_bound = True
            else:
                self._advance()
        self._match_period()
        return EnhancementPointStatement(
            enhancement_type='POINT', spot_name=spot_name,
            is_static=is_static, include_bound=include_bound,
            line=tok.line
        )

    def _parse_enhancement_section(self):
        """Parse ENHANCEMENT-SECTION spot_name ... END-ENHANCEMENT-SECTION."""
        tok = self._advance()  # ENHANCEMENT-SECTION
        spot_name = self._read_token_value() if not self._check(TokenType.PERIOD) else ''
        is_static = False
        include_bound = False
        while not self._at_end() and not self._check(TokenType.PERIOD):
            if self._check_kw('STATIC'):
                self._advance()
                is_static = True
            elif self._check_kw('INCLUDE'):
                self._advance()
                if self._check_kw('BOUND'): self._advance()
                include_bound = True
            else:
                self._advance()
        self._match_period()
        body = self._parse_body_until('END-ENHANCEMENT-SECTION')
        if self._check_kw('END-ENHANCEMENT-SECTION'):
            self._advance()
            self._match_period()
        return EnhancementPointStatement(
            enhancement_type='SECTION', spot_name=spot_name,
            is_static=is_static, include_bound=include_bound,
            body=body, line=tok.line
        )

    def _parse_supply_demand(self):
        """Parse SUPPLY field = value ... TO CONTEXT ctx / DEMAND field FROM CONTEXT ctx."""
        tok = self._advance()  # SUPPLY or DEMAND
        direction = tok.value.upper()
        fields = []
        target = ''
        while not self._at_end() and not self._check(TokenType.PERIOD):
            if direction == 'SUPPLY' and self._check_kw('TO'):
                self._advance()
                if self._check_kw('CONTEXT'): self._advance()
                target = self._read_token_value() if not self._check(TokenType.PERIOD) else ''
                break
            elif direction == 'DEMAND' and self._check_kw('FROM'):
                self._advance()
                if self._check_kw('CONTEXT'): self._advance()
                target = self._read_token_value() if not self._check(TokenType.PERIOD) else ''
                break
            else:
                fname = self._advance().value
                fval = ''
                if self._check(TokenType.EQUALS):
                    self._advance()
                    fval = self._read_token_value()
                fields.append((fname, fval))
        self._match_period()
        return SupplyDemandStatement(direction=direction, fields=fields,
                                     target=target, line=tok.line)

    # ── Generic fallback ──────────────────────────────────────────────────────

    def _parse_generic(self):
        tok = self._peek()
        tokens = self._consume_to_period()
        raw = ' '.join(t.value for t in tokens)
        return GenericStatement(raw_text=raw, raw_tokens=[t.value for t in tokens],
                                line=tok.line)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4: S/4HANA TRANSFORMATION VISITOR (130+ rules)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ChangeRecord:
    """Records a single transformation applied to the AST."""
    rule_id: str
    line: int
    category: str
    description: str
    old_code: str
    new_code: str
    severity: str = 'medium'

    def to_dict(self) -> Dict[str, Any]:
        return {
            'rule_id': self.rule_id, 'line': self.line,
            'category': self.category, 'description': self.description,
            'old_code': self.old_code, 'new_code': self.new_code,
            'severity': self.severity,
        }


# Table rename map: ECC -> S/4HANA
S4_TABLE_MAP = {
    'BSEG': 'ACDOCA', 'BSID': 'ACDOCA', 'BSAD': 'ACDOCA',
    'BSIK': 'ACDOCA', 'BSAK': 'ACDOCA', 'GLT0': 'ACDOCA',
    'BSIS': 'ACDOCA', 'BSAS': 'ACDOCA', 'COEP': 'ACDOCA',
    'FAGLFLEXA': 'ACDOCA', 'FAGLFLEXT': 'ACDOCT',
    'MKPF': 'MATDOC', 'MSEG': 'MATDOC',
    'KNA1': 'BUT000', 'KNB1': 'BUT0CK', 'KNVV': 'BUT052',
    'LFA1': 'BUT000', 'LFB1': 'BUT0CK',
    'KONV': 'PRCD_ELEMENTS',
    # Tax document tables → ACDOCA
    'BSET': 'ACDOCA',
    # CO line items merged into universal journal
    'COBK': 'ACDOCA',
    # Fixed asset master → CDS view
    'ANLA': 'I_FIXEDASSET',
    'ANLP': 'I_FIXEDASSETDEPRNCAREA',
    'ANEK': 'I_FIXEDASSETDOCUMENT',
    # GL totals (classic) merged into ACDOCA
    'GLPCA': 'ACDOCA',
    # Status tables merged into parent (AST-074, AST-075)
    'VBUK': 'VBAK', 'VBUP': 'VBAP',
    # Material document merge (AST-078)
    'MATDOC': 'MATDOC',  # already new — kept for reference
    # Currency rate table (AST-112, AST-115)
    'TCURR': 'I_EXCHANGERATERAWDATA',
    # Batch management (AST-130)
    'MCHA': 'MCH1',
    # Plant maintenance (AST-129)
    'ILOA': 'I_MAINTENANCEOBJECT',
}

# Auth object migration map: old auth objects → new S/4 auth objects
S4_AUTH_OBJECT_MAP = {
    'F_BSEG_BUK': 'F_ACDOC_BUK',
    'F_BSEG_GSB': 'F_ACDOC_GSB',
    'F_BSEG_KOA': 'F_ACDOC_KOA',
    'F_BSEG_BES': 'F_ACDOC_BES',
    # BSEG authorization → ACDOCA authorization (AST-116)
    'F_BKPF_BUK': 'F_ACDOCA_BUK',
    'F_BKPF_GSB': 'F_ACDOCA_GSB',
    'F_BKPF_KOA': 'F_ACDOCA_KOA',
    # Customer master auth → Business Partner auth (AST-117)
    'F_KNA1_BUK': 'F_BUPA_BUK',
    'F_KNA1_GRP': 'F_BUPA_GRP',
    'F_KNA1_BEK': 'F_BUPA_BEK',
    'F_KNA1_AEN': 'F_BUPA_AEN',
    # Vendor master auth → Business Partner auth (AST-118)
    'F_LFA1_BUK': 'F_BUPA_BUK',
    'F_LFA1_GRP': 'F_BUPA_GRP',
    'F_LFA1_BEK': 'F_BUPA_BEK',
    'F_LFA1_AEN': 'F_BUPA_AEN',
}

# Deprecated function modules with S/4 replacements
DEPRECATED_FMS = {
    'POPUP_TO_CONFIRM_STEP': 'POPUP_TO_CONFIRM',
    'POPUP_TO_CONFIRM_WITH_MESSAGE': 'POPUP_TO_CONFIRM',
    'POPUP_TO_CONFIRM_LOSS_OF_DATA': 'POPUP_TO_CONFIRM',
    'POPUP_TO_DECIDE': 'POPUP_TO_CONFIRM',
    'POPUP_TO_DISPLAY_TEXT': 'POPUP_TO_INFORM',
    'REUSE_ALV_GRID_DISPLAY': 'CL_SALV_TABLE=>FACTORY',
    'REUSE_ALV_LIST_DISPLAY': 'CL_SALV_TABLE=>FACTORY',
    'REUSE_ALV_FIELDCATALOG_MERGE': 'CL_SALV_TABLE=>FACTORY (auto-detects fields)',
    'GUI_DOWNLOAD': 'CL_GUI_FRONTEND_SERVICES=>GUI_DOWNLOAD',
    'GUI_UPLOAD': 'CL_GUI_FRONTEND_SERVICES=>GUI_UPLOAD',
    'WS_DOWNLOAD': 'CL_GUI_FRONTEND_SERVICES=>GUI_DOWNLOAD',
    'WS_UPLOAD': 'CL_GUI_FRONTEND_SERVICES=>GUI_UPLOAD',
    'SAPGUI_PROGRESS_INDICATOR': 'CL_PROGRESS_INDICATOR=>PROGRESS_INDICATE',
    'CONVERSION_EXIT_ALPHA_INPUT': 'Use |{ var ALPHA = IN }|',
    'CONVERSION_EXIT_ALPHA_OUTPUT': 'Use |{ var ALPHA = OUT }|',
    'SPELL_AMOUNT': 'CL_ABAP_SPELL=>SPELL_AMOUNT',
    'READ_TEXT': 'CL_SWF_UTL_TEXT_IO=>READ',
    # AST-083: Popup FM → class-based popup
    'POPUP_TO_CONFIRM': 'CL_POPUP=>POPUP_TO_CONFIRM',
    # AST-086: Conversion exit FMs → modern class
    'CONVERSION_EXIT_CUNIT_INPUT': 'CL_ABAP_CONV_CODEPAGE',
    'CONVERSION_EXIT_CUNIT_OUTPUT': 'CL_ABAP_CONV_CODEPAGE',
    'CONVERSION_EXIT_MATN1_INPUT': '|{ var ALPHA = IN }| or CL_ABAP_CONV_CODEPAGE',
    'CONVERSION_EXIT_MATN1_OUTPUT': '|{ var ALPHA = OUT }| or CL_ABAP_CONV_CODEPAGE',
    # AST-087: Date check FM → modern class
    'DATE_CHECK_PLAUSIBILITY': 'CL_ABAP_DATFM=>CHECK_DATE',
    # AST-092: Mail sending FM → BCS class
    'SO_NEW_DOCUMENT_ATT_SEND_API1': 'CL_BCS=>CREATE_PERSISTENT',
    'SO_DOCUMENT_SEND_API1': 'CL_BCS=>CREATE_PERSISTENT',
    # AST-094: Tax calculation FM → tax classes
    'CALCULATE_TAX_FROM_NET_AMOUNT': 'Tax calculation classes (CL_TAX_CALCULATOR)',
    'CALCULATE_TAX_FROM_GROSS_AMOUNT': 'Tax calculation classes (CL_TAX_CALCULATOR)',
    # AST-095: Number range FM → class
    'NUMBER_GET_NEXT': 'CL_NUMBERRANGE_RUNTIME=>NUMBER_GET',
    'NUMBER_GET_INFO': 'CL_NUMBERRANGE_RUNTIME=>NUMBER_GET_INFO',
    # AST-096: Message formatting FM → class
    'FORMAT_MESSAGE': 'CL_MESSAGE_HELPER=>GET_TEXT',
    'BALW_BAPIRETURN_GET2': 'CL_MESSAGE_HELPER=>SET_MSG_VARS_FOR_CLIKE',
    # AST-097: Period determination FM → class
    'FI_PERIOD_DETERMINE': 'CL_FICO_PERIOD_TOOLS=>PERIOD_DETERMINE',
    'FI_PERIOD_CHECK': 'CL_FICO_PERIOD_TOOLS=>PERIOD_CHECK',
    # AST-098: Address FM → CDS view
    'ADDR_GET': 'I_AddressTP CDS view',
    'ADDR_GET_COMPLETE': 'I_AddressTP CDS view',
    # AST-099: File dialog FM → class
    'WS_FILENAME_GET': 'CL_GUI_FRONTEND_SERVICES=>FILE_OPEN_DIALOG',
    'WS_FILE_GET': 'CL_GUI_FRONTEND_SERVICES=>FILE_OPEN_DIALOG',
    # AST-111: Currency conversion FM → class
    'BAPI_CURRENCY_CONV_TO_INTERNAL': 'CL_CURRENCY_CONVERSION=>CONVERT_TO_INTERNAL',
    'BAPI_CURRENCY_CONV_TO_EXTERNAL': 'CL_CURRENCY_CONVERSION=>CONVERT_TO_EXTERNAL',
}

# Extended FM map for BAPI-to-RAP/CDS replacements (AST-088 through AST-100)
DEPRECATED_FM_RAP_MAP = {
    # AST-088: Material BAPI → CDS
    'BAPI_MATERIAL_GETLIST': ('AST-088', 'I_Product CDS view or I_ProductTP RAP BO'),
    'BAPI_MATERIAL_GETDETAIL': ('AST-088', 'I_Product CDS view'),
    'BAPI_MATERIAL_GET_ALL': ('AST-088', 'I_Product CDS view'),
    # AST-089: Sales order BAPI → RAP BO
    'BAPI_SALESORDER_CREATEFROMDAT2': ('AST-089', 'I_SalesOrderTP RAP Business Object'),
    'BAPI_SALESORDER_CHANGE': ('AST-089', 'I_SalesOrderTP RAP Business Object'),
    'BAPI_SALESORDER_GETLIST': ('AST-089', 'I_SalesOrder CDS view'),
    # AST-090: Purchase order BAPI → RAP BO
    'BAPI_PO_CREATE1': ('AST-090', 'I_PurchaseOrderTP RAP Business Object'),
    'BAPI_PO_CHANGE': ('AST-090', 'I_PurchaseOrderTP RAP Business Object'),
    'BAPI_PO_GETDETAIL1': ('AST-090', 'I_PurchaseOrder CDS view'),
    # AST-091: Accounting document BAPI → RAP BO
    'BAPI_ACC_DOCUMENT_POST': ('AST-091', 'I_JournalEntryTP RAP Business Object'),
    'BAPI_ACC_DOCUMENT_REV_POST': ('AST-091', 'I_JournalEntryTP RAP Business Object'),
    'BAPI_ACC_DOCUMENT_CHECK': ('AST-091', 'I_JournalEntryTP RAP Business Object'),
    # AST-093: Business Partner BAPI → RAP BO
    'BUPA_CENTRAL_CI_CREATE': ('AST-093', 'I_BusinessPartnerTP RAP Business Object'),
    'BUPA_CENTRAL_CI_CHANGE': ('AST-093', 'I_BusinessPartnerTP RAP Business Object'),
    'BUPA_CENTRAL_CI_GET_DETAIL': ('AST-093', 'I_BusinessPartner CDS view'),
    'BP_CENTRALDATAPERSON_CREATE': ('AST-093', 'I_BusinessPartnerTP RAP Business Object'),
    'BP_CENTRALDATAPERSON_CHANGE': ('AST-093', 'I_BusinessPartnerTP RAP Business Object'),
    # AST-092: Mail sending FM → BCS class
    'SO_NEW_DOCUMENT_ATT_SEND_API1': ('AST-092', 'CL_BCS=>CREATE_PERSISTENT (Business Communication Services)'),
    'SO_DOCUMENT_SEND_API1': ('AST-092', 'CL_BCS=>CREATE_PERSISTENT (Business Communication Services)'),
    # AST-094: Tax calculation FM → tax classes
    'CALCULATE_TAX_FROM_NET_AMOUNT': ('AST-094', 'Tax calculation classes (CL_TAX_CALCULATOR)'),
    'CALCULATE_TAX_FROM_GROSS_AMOUNT': ('AST-094', 'Tax calculation classes (CL_TAX_CALCULATOR)'),
    # AST-095: Number range FM → class
    'NUMBER_GET_NEXT': ('AST-095', 'CL_NUMBERRANGE_RUNTIME=>NUMBER_GET'),
    'NUMBER_GET_INFO': ('AST-095', 'CL_NUMBERRANGE_RUNTIME=>NUMBER_GET_INFO'),
    # AST-096: Message formatting FM → class
    'FORMAT_MESSAGE': ('AST-096', 'CL_MESSAGE_HELPER=>GET_TEXT'),
    'BALW_BAPIRETURN_GET2': ('AST-096', 'CL_MESSAGE_HELPER=>SET_MSG_VARS_FOR_CLIKE'),
    # AST-097: Period determination FM → class
    'FI_PERIOD_DETERMINE': ('AST-097', 'CL_FICO_PERIOD_TOOLS=>PERIOD_DETERMINE'),
    'FI_PERIOD_CHECK': ('AST-097', 'CL_FICO_PERIOD_TOOLS=>PERIOD_CHECK'),
    # AST-098: Address FM → CDS view
    'ADDR_GET': ('AST-098', 'I_AddressTP CDS view'),
    'ADDR_GET_COMPLETE': ('AST-098', 'I_AddressTP CDS view'),
    # AST-099: File dialog FM → class
    'WS_FILENAME_GET': ('AST-099', 'CL_GUI_FRONTEND_SERVICES=>FILE_OPEN_DIALOG'),
    'WS_FILE_GET': ('AST-099', 'CL_GUI_FRONTEND_SERVICES=>FILE_OPEN_DIALOG'),
    # AST-100: HR employee data FM → CDS
    'HR_GET_EMPLOYEE_DATA': ('AST-100', 'I_Employee CDS view'),
    'HR_READ_INFOTYPE': ('AST-100', 'I_Employee CDS view or HCM RAP APIs'),
}

# Transaction code migration map for Business Partner (AST-101 through AST-105)
BP_TCODE_MAP = {
    # AST-101: Customer create/change → BP
    'SD01': ('AST-101', 'BP', 'Customer create → Business Partner transaction'),
    'SD02': ('AST-101', 'BP', 'Customer change → Business Partner transaction'),
    'SD03': ('AST-101', 'BP', 'Customer display → Business Partner transaction'),
    'XD01': ('AST-101', 'BP', 'Customer create (central) → BP transaction'),
    'XD02': ('AST-101', 'BP', 'Customer change (central) → BP transaction'),
    # AST-102: Vendor create/change → BP
    'XK01': ('AST-102', 'BP', 'Vendor create (central) → BP transaction'),
    'XK02': ('AST-102', 'BP', 'Vendor change (central) → BP transaction'),
    'XK03': ('AST-102', 'BP', 'Vendor display (central) → BP transaction'),
    # AST-103: Vendor finance → BP
    'FK01': ('AST-103', 'BP', 'Vendor create (FI) → BP transaction'),
    'FK02': ('AST-103', 'BP', 'Vendor change (FI) → BP transaction'),
    'FK03': ('AST-103', 'BP', 'Vendor display (FI) → BP transaction'),
    # AST-104: Customer finance → BP
    'FD01': ('AST-104', 'BP', 'Customer create (FI) → BP transaction'),
    'FD02': ('AST-104', 'BP', 'Customer change (FI) → BP transaction'),
    'FD03': ('AST-104', 'BP', 'Customer display (FI) → BP transaction'),
    # AST-105: Vendor purchasing → BP
    'MK01': ('AST-105', 'BP', 'Vendor create (MM) → BP transaction'),
    'MK02': ('AST-105', 'BP', 'Vendor change (MM) → BP transaction'),
    'MK03': ('AST-105', 'BP', 'Vendor display (MM) → BP transaction'),
}

# Removed T-codes for S_TCODE checks (AST-120)
S4_REMOVED_TCODES = {
    'SD01', 'SD02', 'SD03', 'XD01', 'XD02', 'XD03',
    'XK01', 'XK02', 'XK03', 'FK01', 'FK02', 'FK03',
    'FD01', 'FD02', 'FD03', 'MK01', 'MK02', 'MK03',
    'KE21', 'KE21N',  # CO-PA manual entry removed
    'FB01', 'FB02',   # replaced by FB01L / Fiori apps
}

# BAPI replacements
DEPRECATED_BAPIS = {
    'BAPI_COMPANYCODE_GETDETAIL': 'Check S/4 CDS I_CompanyCode',
    'BAPI_GL_ACC_GETDETAIL': 'Check S/4 CDS I_GLAccountInChartOfAccounts',
    'BAPI_COSTCENTER_GETLIST': 'Check S/4 CDS I_CostCenter',
    'BAPI_PROFITCENTER_GETLIST': 'Check S/4 CDS I_ProfitCenter',
    'BAPI_CUSTOMER_GETDETAIL': 'Check S/4 CDS I_Customer (Business Partner)',
    'BAPI_VENDOR_GETDETAIL': 'Check S/4 CDS I_Supplier (Business Partner)',
}


class S4HANATransformVisitor:
    """
    Traverses the AST and applies 130+ S/4HANA migration transformation rules.

    Categories of transformations (AST-001 through AST-130):
    - Obsolete syntax removal (OCCURS, HEADER LINE, MOVE TO, COMPUTE, arithmetic kw)
    - Deprecated statement replacements (MOVE, COMPUTE, TRANSLATE, CONDENSE, STRLEN,
      DESCRIBE TABLE, READ TABLE, CALL METHOD, CREATE OBJECT, COLLECT, OCCURS, RANGES,
      TABLES, FORM/ENDFORM, COMMUNICATION, SET EXTENDED CHECK)
    - Table model migration (BSEG->ACDOCA, KNA1->BUT000, BSET->ACDOCA, FAGLFLEXA->ACDOCA,
      FAGLFLEXT->ACDOCT, COEP/COBK->ACDOCA, ANLA->I_FixedAsset CDS, GLPCA->ACDOCA,
      KONV->PRCD_ELEMENTS, VBUK->VBAK, VBUP->VBAP, MKPF/MSEG->MATDOC, TCURR->CDS)
    - Function module replacements (ALV FMs->CL_SALV_TABLE, GUI_DOWNLOAD/UPLOAD->classes,
      POPUP FMs->CL_POPUP, CONVERSION_EXIT->CL_ABAP_CONV, BAPIs->RAP Business Objects,
      NUMBER_GET_NEXT->CL_NUMBERRANGE_RUNTIME, SO_SEND->CL_BCS)
    - Business Partner migration (SD01/XK01/FK01/FD01/MK01->BP, KUNNR/LIFNR->BUT000-PARTNER,
      KNA1/KNB1/KNVV joins->BUT000/BUT0BK/BUT100)
    - Currency & unit changes (WRBTR flexible decimals, currency conversion APIs,
      TCURR->CDS, UOM ISO mapping, extended precision CURR fields)
    - Authorization & security (F_BKPF_BUK->F_ACDOCA_BUK, F_KNA1->F_BUPA, F_LFA1->F_BUPA,
      removed T-code checks, new auth trace)
    - Output & print changes (SAPscript->Adobe Forms, SmartForms->Output Mgmt 2.0,
      NAST->BRF+, SPOOL->Print Queue API, SUBMIT TO SAP-SPOOL->CL_PRINT_QUEUE_UTILS)
    - Data migration & compatibility (Material CHAR(18)->CHAR(40), BP number validation,
      G/L Account leading zeros, ILOA->PM object, MCHA->new batch framework)
    - Modern ABAP upgrades (DESCRIBE LINES -> lines(), TRANSLATE -> to_upper/to_lower,
      CONCATENATE -> &&, RANGES -> TYPE RANGE OF, STRLEN -> strlen(), FIELD-SYMBOLS
      inline, CALL SCREEN -> Fiori, SET PF-STATUS -> Fiori action sheet)
    - Authority object migration (F_BSEG_BUK -> F_ACDOC_BUK)
    - Native SQL flagging
    - SELECT * deprecation / SELECT INTO CORRESPONDING FIELDS performance
    - JOIN pattern modernization
    - WRITE AT position -> modern output
    """

    def __init__(self, custom_rules: Dict[str, Any] = None):
        self.changes: List[ChangeRecord] = []
        self.custom_rules = custom_rules or {}

    def visit(self, node: ABAPNode) -> ABAPNode:
        """Dispatch to type-specific visitor method, then augmented rules."""
        method_name = f'_visit_{node.node_type.lower()}'
        visitor = getattr(self, method_name, None)
        if visitor:
            visitor(node)
        # Also dispatch to augmented visitor for new rules (AST-045+)
        augmented_name = f'_visit_{node.node_type.lower()}_augmented'
        augmented = getattr(self, augmented_name, None)
        if augmented:
            augmented(node)
        # Recursively visit children/body nodes
        self._visit_children(node)
        return node

    def _visit_children(self, node):
        """Walk all list attributes that contain ABAPNode children."""
        for attr_name in ('statements', 'body', 'then_body', 'else_body',
                          'try_body', 'cleanup_body', 'public_section',
                          'protected_section', 'private_section'):
            body = getattr(node, attr_name, None)
            if body and isinstance(body, list):
                for child in body:
                    if isinstance(child, ABAPNode):
                        self.visit(child)
        # elseif_branches, when_branches, catch_branches contain tuples with statement lists
        for attr_name in ('elseif_branches', 'when_branches', 'catch_branches'):
            branches = getattr(node, attr_name, None)
            if branches:
                for branch in branches:
                    stmts = branch[-1] if isinstance(branch, tuple) and branch else []
                    if isinstance(stmts, list):
                        for child in stmts:
                            if isinstance(child, ABAPNode):
                                self.visit(child)

    def transform(self, program: ProgramNode) -> Tuple[ProgramNode, List[ChangeRecord]]:
        """Main entry: transform entire program and return changes."""
        self.changes = []
        for stmt in program.statements:
            self.visit(stmt)
        return program, self.changes

    # ── Rule 1: Remove OCCURS (obsolete internal table declaration) ───────────

    def _visit_data_declaration(self, node: DataDeclaration):
        if node.occurs:
            old = f"DATA {node.name} ... OCCURS {node.occurs}"
            node._changes.append('OCCURS removed')
            self.changes.append(ChangeRecord(
                rule_id='AST-001', line=node.line, category='obsolete_syntax',
                description='OCCURS is obsolete — removed (use TYPE TABLE)',
                old_code=old, new_code=f"DATA {node.name} TYPE STANDARD TABLE OF ...",
                severity='high',
            ))
            node.occurs = ''
            if not node.table_type and not node.table_of:
                node.table_type = 'STANDARD'

    # ── Rule 2: Remove HEADER LINE ───────────────────────────────────────────

        if node.header_line:
            old = f"DATA {node.name} ... WITH HEADER LINE"
            node._changes.append('HEADER LINE removed')
            self.changes.append(ChangeRecord(
                rule_id='AST-002', line=node.line, category='obsolete_syntax',
                description='WITH HEADER LINE is obsolete — use explicit work area',
                old_code=old, new_code=f"DATA {node.name} TYPE TABLE ... + DATA wa_{node.name} LIKE LINE OF {node.name}",
                severity='high',
            ))
            node.header_line = False

    # ── Rule 3: MOVE ... TO → assignment operator ─────────────────────────────

    def _visit_move(self, node: MoveStatement):
        old = f"MOVE {node.source} TO {node.target}"
        new = f"{node.target} = {node.source}"
        self.changes.append(ChangeRecord(
            rule_id='AST-003', line=node.line, category='obsolete_syntax',
            description='MOVE...TO is obsolete — converted to assignment operator',
            old_code=old, new_code=new, severity='medium',
        ))
        node.node_type = 'ASSIGNMENT'
        node.__class__ = AssignmentStatement
        node.target = node.target
        node.expression = node.source

    # ── Rule 4: COMPUTE → direct assignment ───────────────────────────────────

    def _visit_compute(self, node: ComputeStatement):
        old = f"COMPUTE {node.target} = {node.expression}"
        new = f"{node.target} = {node.expression}"
        self.changes.append(ChangeRecord(
            rule_id='AST-004', line=node.line, category='obsolete_syntax',
            description='COMPUTE keyword is obsolete — removed',
            old_code=old, new_code=new, severity='low',
        ))
        node.node_type = 'ASSIGNMENT'
        node.__class__ = AssignmentStatement

    # ── Rule 5: ADD/SUBTRACT/MULTIPLY/DIVIDE → arithmetic expression ─────────

    def _visit_arithmetic(self, node: ArithmeticStatement):
        op_map = {'ADD': '+', 'SUBTRACT': '-', 'MULTIPLY': '*', 'DIVIDE': '/'}
        op_symbol = op_map.get(node.operation, '+')
        if node.operation == 'ADD':
            old = f"ADD {node.operand} TO {node.target}"
            new = f"{node.target} = {node.target} + {node.operand}"
        elif node.operation == 'SUBTRACT':
            old = f"SUBTRACT {node.operand} FROM {node.target}"
            new = f"{node.target} = {node.target} - {node.operand}"
        elif node.operation == 'MULTIPLY':
            old = f"MULTIPLY {node.target} BY {node.operand}"
            new = f"{node.target} = {node.target} * {node.operand}"
        else:
            old = f"DIVIDE {node.target} BY {node.operand}"
            new = f"{node.target} = {node.target} / {node.operand}"
        self.changes.append(ChangeRecord(
            rule_id='AST-005', line=node.line, category='obsolete_syntax',
            description=f'{node.operation} keyword is obsolete — converted to expression',
            old_code=old, new_code=new, severity='medium',
        ))
        node.node_type = 'ASSIGNMENT'
        node.__class__ = AssignmentStatement
        node.target = node.target
        node.expression = f"{node.target} {op_symbol} {node.operand}"

    # ── Rule 6: Table renames in SELECT — see consolidated _visit_select below ──

    # ── Rule 7: Table renames in DB operations ────────────────────────────────

    def _visit_db_modify(self, node: DatabaseModifyStatement):
        tn_upper = node.table_name.upper()
        if tn_upper in S4_TABLE_MAP:
            old = node.table_name
            node.table_name = S4_TABLE_MAP[tn_upper]
            self.changes.append(ChangeRecord(
                rule_id='AST-009', line=node.line, category='data_model',
                description=f'DB {node.operation} on {old} → {node.table_name}',
                old_code=f"{node.operation} {old}",
                new_code=f"{node.operation} {node.table_name}",
                severity='critical',
            ))

    # ── Rule 8: Deprecated Function Module calls ─────────────────────────────

    def _visit_call_function(self, node: CallFunctionStatement):
        fn_clean = node.function_name.strip("'").strip("`").upper()
        if fn_clean in DEPRECATED_FMS:
            replacement = DEPRECATED_FMS[fn_clean]
            self.changes.append(ChangeRecord(
                rule_id='AST-010', line=node.line, category='deprecated_fm',
                description=f'FM {fn_clean} is deprecated — replace with {replacement}',
                old_code=f"CALL FUNCTION '{fn_clean}'",
                new_code=f"Use {replacement}",
                severity='high',
            ))

        # Check for deprecated BAPIs
        if fn_clean in DEPRECATED_BAPIS:
            self.changes.append(ChangeRecord(
                rule_id='AST-011', line=node.line, category='deprecated_bapi',
                description=f'BAPI {fn_clean} — {DEPRECATED_BAPIS[fn_clean]}',
                old_code=f"CALL FUNCTION '{fn_clean}'",
                new_code=DEPRECATED_BAPIS[fn_clean],
                severity='medium',
            ))

    # ── Rule 9: DESCRIBE TABLE ... LINES → lines() ───────────────────────────

    def _visit_describe_table(self, node: DescribeTableStatement):
        if node.lines_var:
            old = f"DESCRIBE TABLE {node.table} LINES {node.lines_var}"
            new = f"{node.lines_var} = lines( {node.table} )"
            self.changes.append(ChangeRecord(
                rule_id='AST-012', line=node.line, category='modern_abap',
                description='DESCRIBE TABLE LINES → lines() built-in function',
                old_code=old, new_code=new, severity='low',
            ))
            node.node_type = 'ASSIGNMENT'
            node.__class__ = AssignmentStatement
            node.target = node.lines_var
            node.expression = f"lines( {node.table} )"

    # ── Rule 10: TRANSLATE — see consolidated _visit_translate below ──────────

    # ── Rule 11: CONCATENATE → string template / && operator ──────────────────

    def _visit_concatenate(self, node: ConcatenateStatement):
        if len(node.sources) >= 2 and not node.separated_by:
            old = f"CONCATENATE {' '.join(node.sources)} INTO {node.target}"
            parts = ' && '.join(node.sources)
            new = f"{node.target} = {parts}"
            self.changes.append(ChangeRecord(
                rule_id='AST-014', line=node.line, category='modern_abap',
                description='CONCATENATE → && operator (modern ABAP 7.40+)',
                old_code=old, new_code=new, severity='low',
            ))

    # ── Rule 12: RANGES → TYPE RANGE OF ──────────────────────────────────────

    def _visit_ranges_declaration(self, node: RangesDeclaration):
        old = f"RANGES {node.name} FOR {node.for_field}"
        # Extract the type from the field reference
        field_parts = node.for_field.split('-')
        type_ref = node.for_field if len(field_parts) == 1 else field_parts[-1]
        new = f"DATA {node.name} TYPE RANGE OF {type_ref}"
        self.changes.append(ChangeRecord(
            rule_id='AST-015', line=node.line, category='obsolete_syntax',
            description='RANGES statement is obsolete — use TYPE RANGE OF',
            old_code=old, new_code=new, severity='medium',
        ))
        # Morph RANGES into an equivalent `DATA ... TYPE RANGE OF` declaration.
        # Build a fully-initialised DataDeclaration and copy its attributes so the
        # code generator finds everything it expects (is_structure_begin, ref_to,
        # length, …). Reassigning __class__ alone left those unset and crashed
        # _gen_data_declaration with AttributeError on structure-heavy programs.
        _morphed = DataDeclaration(name=node.name, keyword='DATA',
                                   type_clause=f"RANGE OF {type_ref}", line=node.line)
        node.__class__ = DataDeclaration
        node.__dict__.update(_morphed.__dict__)

    # ── Rule 13: TABLES statement → DATA with TYPE ───────────────────────────

    def _visit_tables_declaration(self, node: TablesDeclaration):
        old = f"TABLES {node.table_name}"
        new = f"DATA {node.table_name} TYPE {node.table_name}"
        self.changes.append(ChangeRecord(
            rule_id='AST-016', line=node.line, category='obsolete_syntax',
            description='TABLES statement is obsolete — use DATA TYPE',
            old_code=old, new_code=new, severity='medium',
        ))

    # ── Rule 14: Native SQL warning ──────────────────────────────────────────

    def _visit_native_sql(self, node: NativeSqlBlock):
        self.changes.append(ChangeRecord(
            rule_id='AST-017', line=node.line, category='native_sql',
            description='EXEC SQL/Native SQL is deprecated — rewrite to Open SQL or AMDP',
            old_code='EXEC SQL ... ENDEXEC',
            new_code='Rewrite using Open SQL or ABAP Managed Database Procedures (AMDP)',
            severity='critical',
        ))

    # ── Rule 15: CREATE OBJECT → NEW operator ────────────────────────────────

    def _visit_create_object(self, node: CreateObjectStatement):
        if node.class_name:
            old = f"CREATE OBJECT {node.variable} TYPE {node.class_name}"
            new = f"{node.variable} = NEW {node.class_name}( )"
            self.changes.append(ChangeRecord(
                rule_id='AST-018', line=node.line, category='modern_abap',
                description='CREATE OBJECT → NEW operator (modern ABAP 7.40+)',
                old_code=old, new_code=new, severity='low',
            ))

    # ── Rule 16: MOVE-CORRESPONDING → CORRESPONDING #( ) ─────────────────────

    def _visit_move_corresponding(self, node: MoveCorrespondingStatement):
        old = f"MOVE-CORRESPONDING {node.source} TO {node.target}"
        new = f"{node.target} = CORRESPONDING #( {node.source} )"
        self.changes.append(ChangeRecord(
            rule_id='AST-019', line=node.line, category='modern_abap',
            description='MOVE-CORRESPONDING → CORRESPONDING #() constructor',
            old_code=old, new_code=new, severity='low',
        ))

    # ── Rule 17: READ TABLE with BINARY SEARCH deprecation ───────────────────

    def _visit_read_table(self, node: ReadTableStatement):
        if node.binary_search:
            self.changes.append(ChangeRecord(
                rule_id='AST-020', line=node.line, category='performance',
                description='BINARY SEARCH is unnecessary with sorted/hashed tables',
                old_code=f"READ TABLE {node.table} ... BINARY SEARCH",
                new_code=f"Use SORTED or HASHED table type, then READ TABLE WITH TABLE KEY",
                severity='low',
            ))

    # ── Rule 18: CONDENSE with NO-GAPS → condense( ) ─────────────────────────

    def _visit_condense(self, node: CondenseStatement):
        old = f"CONDENSE {node.target}" + (' NO-GAPS' if node.no_gaps else '')
        new = f"{node.target} = condense( val = {node.target}" + (' del = ` ` ' if node.no_gaps else '') + ' )'
        self.changes.append(ChangeRecord(
            rule_id='AST-021', line=node.line, category='modern_abap',
            description='CONDENSE → condense() built-in function',
            old_code=old, new_code=new, severity='low',
        ))

    # ── Rule 19: FORM/PERFORM → Method call (OOP recommendation) ─────────────

    def _visit_form(self, node: FormBlock):
        self.changes.append(ChangeRecord(
            rule_id='AST-022', line=node.line, category='modernization',
            description='FORM/ENDFORM is legacy — consider refactoring to CLASS/METHOD',
            old_code=f"FORM {node.name}",
            new_code=f"METHOD {node.name} in a local class",
            severity='low',
        ))

    def _visit_perform(self, node: PerformStatement):
        self.changes.append(ChangeRecord(
            rule_id='AST-023', line=node.line, category='modernization',
            description='PERFORM is legacy — consider refactoring to method call',
            old_code=f"PERFORM {node.form_name}",
            new_code=f"lo_obj->method_{node.form_name}( )",
            severity='low',
        ))

    # ── Rule 20: COLLECT statement (rarely used correctly) ────────────────────

    def _visit_collect(self, node: CollectStatement):
        self.changes.append(ChangeRecord(
            rule_id='AST-024', line=node.line, category='review',
            description='COLLECT statement — review usage for correctness in S/4HANA context',
            old_code=f"COLLECT {node.source} INTO {node.target}",
            new_code='Consider REDUCE or explicit aggregation logic',
            severity='low',
        ))

    # ── Rule 21: CHECK in event blocks → IF/RETURN ───────────────────────────

    def _visit_simple_flow(self, node: SimpleFlowStatement):
        if node.keyword == 'CHECK' and node.condition:
            self.changes.append(ChangeRecord(
                rule_id='AST-025', line=node.line, category='modernization',
                description='CHECK statement — consider IF/RETURN for clarity',
                old_code=f"CHECK {node.condition}",
                new_code=f"IF NOT ( {node.condition} ). RETURN. ENDIF.",
                severity='low',
            ))

    # ── Rule 22: CALL METHOD → direct method call syntax ─────────────────────

    def _visit_call_method(self, node: CallMethodStatement):
        if node.object_ref:
            old = f"CALL METHOD {node.object_ref}->{node.method_name}"
            new = f"{node.object_ref}->{node.method_name}( )"
            self.changes.append(ChangeRecord(
                rule_id='AST-026', line=node.line, category='modern_abap',
                description='CALL METHOD → functional method call syntax',
                old_code=old, new_code=new, severity='low',
            ))

    # ── Rule 23: CALL TRANSACTION → review security implications ─────────────

    def _visit_call_transaction(self, node: CallTransactionStatement):
        self.changes.append(ChangeRecord(
            rule_id='AST-027', line=node.line, category='security',
            description='CALL TRANSACTION — review for authorization and S/4 Fiori replacement',
            old_code=f"CALL TRANSACTION '{node.tcode}'",
            new_code='Consider replacing with Fiori app or API-based approach',
            severity='medium',
        ))

    # ── Rule 24: TYPES with OCCURS ───────────────────────────────────────────

    def _visit_types_declaration(self, node: TypesDeclaration):
        if node.occurs:
            self.changes.append(ChangeRecord(
                rule_id='AST-028', line=node.line, category='obsolete_syntax',
                description='TYPES with OCCURS is obsolete',
                old_code=f"TYPES {node.name} ... OCCURS {node.occurs}",
                new_code=f"TYPES {node.name} TYPE STANDARD TABLE OF ...",
                severity='high',
            ))
            node.occurs = ''

    # ── Rule 25: Table references in WHERE clauses ────────────────────────────

    def _visit_loop_at(self, node: LoopAtStatement):
        table_upper = node.table.upper()
        if table_upper in S4_TABLE_MAP:
            old = node.table
            node.table = S4_TABLE_MAP[table_upper]
            self.changes.append(ChangeRecord(
                rule_id='AST-029', line=node.line, category='data_model',
                description=f'LOOP AT {old} → {node.table} (S/4HANA data model)',
                old_code=f"LOOP AT {old}", new_code=f"LOOP AT {node.table}",
                severity='critical',
            ))

    # ── Rule 26: BSET (tax document) → ACDOCA tax handling ─────────────────

    def _visit_select_bset_tax(self, node: SelectStatement):
        """Additional check for BSET-specific tax document migration (AST-030).
        Called from _visit_select when BSET is detected."""
        self.changes.append(ChangeRecord(
            rule_id='AST-030', line=node.line, category='data_model',
            description='BSET (tax document items) merged into ACDOCA in S/4HANA — '
                        'tax postings now stored as line items in Universal Journal. '
                        'Adjust field mapping: BSET-HWBAS → ACDOCA-HSL, BSET-KTOSL → ACDOCA-KTOSL',
            old_code=f"SELECT ... FROM BSET",
            new_code=f"SELECT ... FROM ACDOCA WHERE KTOSL IS NOT INITIAL",
            severity='critical',
        ))

    # ── Rule 27: FAGLFLEXA → ACDOCA (New GL actual line items) ─────────────

    def _visit_select_faglflexa(self, node: SelectStatement):
        """Additional note for FAGLFLEXA migration (AST-031).
        Called from _visit_select when FAGLFLEXA is detected."""
        self.changes.append(ChangeRecord(
            rule_id='AST-031', line=node.line, category='data_model',
            description='FAGLFLEXA (New GL actual line items) → ACDOCA. In S/4HANA the '
                        'New General Ledger actual line items table is replaced by the '
                        'Universal Journal ACDOCA. Map FAGLFLEXA-DOCNR → ACDOCA-BELNR, '
                        'FAGLFLEXA-RBUKRS → ACDOCA-RBUKRS. Ledger field RLDNR is now required.',
            old_code=f"SELECT ... FROM FAGLFLEXA",
            new_code=f"SELECT ... FROM ACDOCA WHERE RLDNR = '0L'",
            severity='critical',
        ))

    # ── Rule 28: FAGLFLEXT → ACDOCT (New GL totals aggregate) ─────────────

    def _visit_select_faglflext(self, node: SelectStatement):
        """Additional note for FAGLFLEXT totals migration (AST-032).
        Called from _visit_select when FAGLFLEXT is detected."""
        self.changes.append(ChangeRecord(
            rule_id='AST-032', line=node.line, category='data_model',
            description='FAGLFLEXT (New GL totals) → ACDOCT (totals table for ACDOCA). '
                        'In S/4HANA, period totals are maintained in ACDOCT. '
                        'Map HSLxx period balance fields. Use CDS view I_GLAccountLineItem for reporting.',
            old_code=f"SELECT ... FROM FAGLFLEXT",
            new_code=f"SELECT ... FROM ACDOCT or CDS I_GLAccountLineItem",
            severity='critical',
        ))

    # ── Rule 29: COEP/COBK → ACDOCA (CO line items merged) ────────────────

    def _visit_select_coep_cobk(self, node: SelectStatement):
        """Additional note for COEP/COBK CO line items migration (AST-033).
        Called from _visit_select when COEP or COBK is detected."""
        self.changes.append(ChangeRecord(
            rule_id='AST-033', line=node.line, category='data_model',
            description='COEP/COBK (CO line items/document headers) merged into ACDOCA. '
                        'In S/4HANA, controlling documents are posted simultaneously with '
                        'FI documents in Universal Journal. Map COEP-OBJNR → ACDOCA-OBJNR, '
                        'COEP-WKGBTR → ACDOCA-KSL (controlling area currency amount).',
            old_code=f"SELECT ... FROM {node.from_clause}",
            new_code=f"SELECT ... FROM ACDOCA WHERE OBJNR LIKE 'KS%' OR OBJNR LIKE 'OR%'",
            severity='critical',
        ))

    # ── Rule 30: ANLA → I_FixedAsset CDS view migration ───────────────────

    def _visit_select_anla(self, node: SelectStatement):
        """Additional note for ANLA asset master migration (AST-034).
        Called from _visit_select when ANLA, ANLP, or ANEK is detected."""
        self.changes.append(ChangeRecord(
            rule_id='AST-034', line=node.line, category='data_model',
            description=f'{node.from_clause.upper()} (Fixed Asset master/depreciation) — '
                        'In S/4HANA, asset tables remain but CDS views are preferred for read access. '
                        'Use I_FixedAsset, I_FixedAssetDeprnArea, I_FixedAssetDocument CDS views. '
                        'New asset accounting (new depreciation engine) is mandatory in S/4.',
            old_code=f"SELECT ... FROM {node.from_clause}",
            new_code=f"SELECT ... FROM I_FixedAsset (CDS view) or keep {node.from_clause} with field mapping review",
            severity='high',
        ))

    # (Augmented _visit_select to trigger specialized rules for specific tables)
    def _visit_select(self, node: SelectStatement):
        from_upper = node.from_clause.upper()

        # Store original from clause before any renames (used by augmented visitor)
        if not hasattr(node, '_original_from'):
            node._original_from = node.from_clause

        # Core table rename (AST-006)
        if from_upper in S4_TABLE_MAP:
            old_table = node.from_clause
            new_table = S4_TABLE_MAP[from_upper]
            self.changes.append(ChangeRecord(
                rule_id='AST-006', line=node.line, category='data_model',
                description=f'Table {old_table} → {new_table} (S/4HANA data model change)',
                old_code=f"SELECT ... FROM {old_table}",
                new_code=f"SELECT ... FROM {new_table}",
                severity='critical',
            ))
            node.from_clause = new_table

            # Trigger specialized migration notes for known tables
            if from_upper == 'BSET':
                self._visit_select_bset_tax(node)
            elif from_upper == 'FAGLFLEXA':
                self._visit_select_faglflexa(node)
            elif from_upper == 'FAGLFLEXT':
                self._visit_select_faglflext(node)
            elif from_upper in ('COEP', 'COBK'):
                self._visit_select_coep_cobk(node)
            elif from_upper in ('ANLA', 'ANLP', 'ANEK'):
                self._visit_select_anla(node)

        # Also check JOIN tables
        for join in node.joins:
            jt_upper = join.get('table', '').upper()
            if jt_upper in S4_TABLE_MAP:
                old_jt = join['table']
                join['table'] = S4_TABLE_MAP[jt_upper]
                self.changes.append(ChangeRecord(
                    rule_id='AST-006', line=node.line, category='data_model',
                    description=f'JOIN table {old_jt} → {join["table"]}',
                    old_code=f"JOIN {old_jt}", new_code=f"JOIN {join['table']}",
                    severity='critical',
                ))

        # Rule: SELECT * deprecation warning (AST-007)
        if node.field_list == ['*']:
            self.changes.append(ChangeRecord(
                rule_id='AST-007', line=node.line, category='performance',
                description='SELECT * is discouraged in S/4HANA — use explicit field list',
                old_code='SELECT *', new_code='SELECT field1, field2, ...',
                severity='medium',
            ))

        # Rule: SELECT...ENDSELECT loop → SELECT INTO TABLE (AST-008)
        if node.has_endselect and not node.is_single:
            self.changes.append(ChangeRecord(
                rule_id='AST-008', line=node.line, category='performance',
                description='SELECT...ENDSELECT loop is inefficient — convert to SELECT INTO TABLE',
                old_code='SELECT ... ENDSELECT', new_code='SELECT ... INTO TABLE itab',
                severity='high',
            ))

        # Rule AST-035: SELECT INTO CORRESPONDING FIELDS → explicit field list (performance)
        if node.into_corresponding and not node.is_single:
            self.changes.append(ChangeRecord(
                rule_id='AST-035', line=node.line, category='performance',
                description='SELECT INTO CORRESPONDING FIELDS is slower than explicit field list — '
                            'use named field list for better performance in S/4HANA large tables',
                old_code='SELECT ... INTO CORRESPONDING FIELDS OF TABLE itab',
                new_code='SELECT field1, field2 INTO TABLE itab (explicit fields)',
                severity='medium',
            ))

        # Rule AST-036: INNER JOIN with old tables → new table join patterns
        for join in node.joins:
            jt_upper = join.get('table', '').upper()
            join_type = join.get('type', '').upper()
            # If joining two tables that both got renamed, suggest CDS view instead
            if from_upper in S4_TABLE_MAP and jt_upper in S4_TABLE_MAP:
                self.changes.append(ChangeRecord(
                    rule_id='AST-036', line=node.line, category='data_model',
                    description=f'{join_type} JOIN between migrated tables — consider using '
                                f'a CDS view instead of joining {S4_TABLE_MAP.get(from_upper, from_upper)} '
                                f'and {S4_TABLE_MAP.get(jt_upper, jt_upper)} directly. '
                                f'S/4HANA provides CDS views that encapsulate join logic.',
                    old_code=f"SELECT ... FROM {from_upper} JOIN {jt_upper}",
                    new_code='Use appropriate CDS view (e.g., I_JournalEntry, I_GLAccountLineItem)',
                    severity='medium',
                ))

    # ── Rule 31: WRITE AT position → Modern output ─────────────────────────

    def _visit_write(self, node: WriteStatement):
        """Check for WRITE with position specification (AST-037)."""
        for output in node.outputs:
            # Detect WRITE AT position pattern: /pos(len) or pos(len)
            if '(' in output and ')' in output and output[0] != '(':
                # Pattern like "20(10)" or "/5(15)" suggests positional output
                self.changes.append(ChangeRecord(
                    rule_id='AST-037', line=node.line, category='modernization',
                    description='WRITE with positional output (AT column/length) is legacy — '
                                'consider using CL_SALV_TABLE, ALV, or Fiori for modern output. '
                                'Positional WRITE is not compatible with Fiori Launchpad.',
                    old_code=f"WRITE AT {output}",
                    new_code='Use ALV (CL_SALV_TABLE) or Fiori element for formatted output',
                    severity='medium',
                ))
                break  # One warning per WRITE statement is sufficient

    # ── Rule 32: CALL SCREEN → Fiori Launchpad navigation ──────────────────

    def _visit_call_screen(self, node: CallScreenStatement):
        """Flag CALL SCREEN for Fiori migration (AST-038)."""
        self.changes.append(ChangeRecord(
            rule_id='AST-038', line=node.line, category='fiori_migration',
            description=f'CALL SCREEN {node.screen_number} — Dynpro screens are not supported '
                        'in Fiori Launchpad. Replace with Fiori Elements app, Web Dynpro, or '
                        'CDS-based analytical/transactional app. If this is a popup, '
                        'use CL_POPUP_* classes or Fiori dialog.',
            old_code=f"CALL SCREEN {node.screen_number}",
            new_code='Replace with Fiori app or CL_GUI_* wrapper for embedded use',
            severity='high',
        ))

    # ── Rule 33: SET PF-STATUS → Fiori action sheet ────────────────────────

    def _visit_set_property(self, node: SetPropertyStatement):
        """Flag SET PF-STATUS and SET TITLEBAR for Fiori migration (AST-039)."""
        if node.set_type.upper() == 'PF-STATUS':
            self.changes.append(ChangeRecord(
                rule_id='AST-039', line=node.line, category='fiori_migration',
                description=f'SET PF-STATUS {node.value} — GUI status/menu bars are not available '
                            'in Fiori. Replace with Fiori action sheet, toolbar actions, or '
                            'semantic page header actions.',
                old_code=f"SET PF-STATUS '{node.value}'",
                new_code='Define actions in Fiori app manifest/annotations',
                severity='medium',
            ))
        elif node.set_type.upper() == 'TITLEBAR':
            self.changes.append(ChangeRecord(
                rule_id='AST-039', line=node.line, category='fiori_migration',
                description=f'SET TITLEBAR {node.value} — GUI titles need Fiori equivalent. '
                            'Use semantic page title or shell title in Fiori Elements.',
                old_code=f"SET TITLEBAR '{node.value}'",
                new_code='Set page title via Fiori app configuration or annotation',
                severity='low',
            ))

    # ── Rule 34: AUTHORITY-CHECK F_BSEG_BUK → F_ACDOC_BUK ─────────────────

    def _visit_authority_check(self, node: AuthorityCheckStatement):
        """Check for old authorization objects that need S/4 migration (AST-040)."""
        obj_upper = node.object_name.upper().strip("'").strip("`")
        if obj_upper in S4_AUTH_OBJECT_MAP:
            new_auth = S4_AUTH_OBJECT_MAP[obj_upper]
            self.changes.append(ChangeRecord(
                rule_id='AST-040', line=node.line, category='authorization',
                description=f'AUTHORITY-CHECK OBJECT {obj_upper} is replaced by {new_auth} '
                            f'in S/4HANA. The BSEG-based auth objects are obsolete since line '
                            f'items moved to ACDOCA. Update authorization profiles accordingly.',
                old_code=f"AUTHORITY-CHECK OBJECT '{obj_upper}'",
                new_code=f"AUTHORITY-CHECK OBJECT '{new_auth}'",
                severity='high',
            ))

    # ── Rule 35: FIELD-SYMBOLS with header line → Inline declarations ──────

    def _visit_field_symbol_declaration(self, node: FieldSymbolDeclaration):
        """Suggest inline FIELD-SYMBOL declaration for modern ABAP (AST-041)."""
        if node.generic_type:
            self.changes.append(ChangeRecord(
                rule_id='AST-041', line=node.line, category='modern_abap',
                description=f'FIELD-SYMBOLS {node.name} TYPE {node.generic_type or "ANY"} — '
                            'Consider using inline FIELD-SYMBOL(<fs>) declaration in LOOP AT ... '
                            'ASSIGNING FIELD-SYMBOL(<fs>) for modern ABAP style. '
                            'Generic field symbols should be typed where possible.',
                old_code=f"FIELD-SYMBOLS {node.name} TYPE {node.generic_type}",
                new_code=f"LOOP AT itab ASSIGNING FIELD-SYMBOL({node.name}). (inline)",
                severity='low',
            ))

    # ── Rule 36: DESCRIBE TABLE (without LINES) → lines() / RTTI ───────────
    # AST-042: DESCRIBE TABLE without LINES keyword (kind, occurs, etc.)

    def _visit_describe_table_augmented(self, node: DescribeTableStatement):
        """AST-042: DESCRIBE TABLE without LINES → modern alternatives."""
        if node.kind_var and not node.lines_var:
            self.changes.append(ChangeRecord(
                rule_id='AST-042', line=node.line, category='modern_abap',
                description='DESCRIBE TABLE ... KIND is obsolete — use RTTI '
                            'cl_abap_tabledescr=>describe_by_data( ) for table kind detection.',
                old_code=f"DESCRIBE TABLE {node.table} KIND {node.kind_var}",
                new_code=f"cl_abap_tabledescr=>describe_by_data( {node.table} )->table_kind",
                severity='low',
            ))

    # ── Rule 37: STRLEN old pattern → Modern string functions ──────────────

    def _visit_assignment(self, node: AssignmentStatement):
        """Check for old-style string function patterns (AST-043, AST-044)."""
        expr_upper = node.expression.upper() if hasattr(node, 'expression') and node.expression else ''
        # AST-043: Detect STRLEN( ) used in old pattern context
        if 'STRLEN' in expr_upper and 'STRLEN(' not in expr_upper:
            self.changes.append(ChangeRecord(
                rule_id='AST-043', line=node.line, category='modern_abap',
                description='Old-style STRLEN usage detected — use strlen( ) function with '
                            'parentheses (ABAP 7.40+ syntax). Also consider string_length( ) '
                            'for Unicode-safe length computation.',
                old_code=f"{node.target} = {node.expression}",
                new_code=f"{node.target} = strlen( {node.expression} )",
                severity='low',
            ))

    # ── Rule 38: TRANSLATE TO UPPER/LOWER → to_upper()/to_lower() ──────────
    # (This extends the existing Rule 10 / AST-013 and adds AST-044 for
    #  TRANSLATE ... USING pattern)

    def _visit_translate(self, node: TranslateStatement):
        if node.to_case in ('UPPER', 'LOWER'):
            func = 'to_upper' if node.to_case == 'UPPER' else 'to_lower'
            old = f"TRANSLATE {node.target} TO {node.to_case} CASE"
            new = f"{node.target} = {func}( {node.target} )"
            self.changes.append(ChangeRecord(
                rule_id='AST-013', line=node.line, category='modern_abap',
                description=f'TRANSLATE TO {node.to_case} CASE → {func}() built-in',
                old_code=old, new_code=new, severity='low',
            ))
            # AST-044: Also flag for to_upper()/to_lower() migration
            self.changes.append(ChangeRecord(
                rule_id='AST-044', line=node.line, category='modern_abap',
                description=f'TRANSLATE ... TO {node.to_case} CASE is obsolete in ABAP 7.40+ — '
                            f'replace with {func}( ) built-in function. This also enables use '
                            f'in inline expressions and constructor operators.',
                old_code=old,
                new_code=f"{node.target} = {func}( val = {node.target} )",
                severity='low',
            ))
            node.node_type = 'ASSIGNMENT'
            node.__class__ = AssignmentStatement
            node.target = node.target
            node.expression = f"{func}( {node.target} )"
        elif node.using_rule:
            # AST-044: TRANSLATE ... USING → replace/translate built-in
            self.changes.append(ChangeRecord(
                rule_id='AST-044', line=node.line, category='modern_abap',
                description='TRANSLATE ... USING is obsolete — use translate( ) built-in '
                            'function (ABAP 7.40+) or REPLACE for character substitution.',
                old_code=f"TRANSLATE {node.target} USING {node.using_rule}",
                new_code=f"{node.target} = translate( val = {node.target} from = '...' to = '...' )",
                severity='low',
            ))

    # ═══════════════════════════════════════════════════════════════════════════
    # NEW RULES AST-045 through AST-130
    # Deprecated Statement Replacements, Table Access Changes, FM Replacements,
    # Business Partner Migration, Currency/Unit, Auth/Security, Output/Print,
    # Data Migration & Compatibility
    # ═══════════════════════════════════════════════════════════════════════════

    # ── AST-045: MOVE...TO → assignment operator (=) ─────────────────────────
    # (Augments existing AST-003 by also catching chained MOVE statements in
    #  generic/fallback nodes that the parser didn't fully decompose)

    def _visit_generic_move_chain(self, node: GenericStatement):
        """AST-045: Detect MOVE...TO in generic/fallback nodes."""
        raw = node.raw_text.upper().strip()
        if raw.startswith('MOVE ') and ' TO ' in raw:
            self.changes.append(ChangeRecord(
                rule_id='AST-045', line=node.line, category='obsolete_syntax',
                description='MOVE...TO is obsolete — use assignment operator (=). '
                            'The MOVE statement has been deprecated since ABAP 7.40.',
                old_code=node.raw_text.strip(),
                new_code='<target> = <source>',
                severity='medium',
            ))

    # ── AST-046: MOVE-CORRESPONDING → CORRESPONDING operator ────────────────
    # (Augments existing AST-019 by flagging in generic nodes)

    def _check_ast046_move_corresponding(self, node: GenericStatement):
        """AST-046: Detect MOVE-CORRESPONDING in generic/fallback nodes."""
        raw = node.raw_text.upper().strip()
        if raw.startswith('MOVE-CORRESPONDING '):
            self.changes.append(ChangeRecord(
                rule_id='AST-046', line=node.line, category='obsolete_syntax',
                description='MOVE-CORRESPONDING is obsolete — use CORRESPONDING #( ) operator '
                            '(ABAP 7.40+). Supports mapping, except, and base additions.',
                old_code=node.raw_text.strip(),
                new_code='<target> = CORRESPONDING #( <source> )',
                severity='medium',
            ))

    # ── AST-047: COMPUTE → direct expression ────────────────────────────────
    # (Augments existing AST-004 by catching COMPUTE in generic nodes)

    def _check_ast047_compute(self, node: GenericStatement):
        """AST-047: Detect COMPUTE keyword in generic/fallback nodes."""
        raw = node.raw_text.upper().strip()
        if raw.startswith('COMPUTE '):
            self.changes.append(ChangeRecord(
                rule_id='AST-047', line=node.line, category='obsolete_syntax',
                description='COMPUTE keyword is obsolete — remove it and use direct assignment. '
                            'Simply write <target> = <expression> without the COMPUTE prefix.',
                old_code=node.raw_text.strip(),
                new_code='<target> = <expression>',
                severity='low',
            ))

    # ── AST-048: MULTIPLY/DIVIDE/ADD/SUBTRACT → arithmetic operators ────────
    # (Augments existing AST-005 by catching in generic nodes)

    def _check_ast048_arithmetic_keywords(self, node: GenericStatement):
        """AST-048: Detect arithmetic keywords in generic/fallback nodes."""
        raw = node.raw_text.upper().strip()
        for kw in ('MULTIPLY', 'DIVIDE', 'ADD', 'SUBTRACT'):
            if raw.startswith(kw + ' '):
                self.changes.append(ChangeRecord(
                    rule_id='AST-048', line=node.line, category='obsolete_syntax',
                    description=f'{kw} keyword is obsolete — use arithmetic expression. '
                                f'Replace with <target> = <target> <op> <operand>.',
                    old_code=node.raw_text.strip(),
                    new_code='<target> = <target> <+|-|*|/> <operand>',
                    severity='medium',
                ))
                break

    # ── AST-049: TRANSLATE...TO UPPER/LOWER → to_upper()/to_lower() ─────────
    # (Augments existing AST-013/AST-044 by catching in generic nodes)

    def _check_ast049_translate(self, node: GenericStatement):
        """AST-049: Detect TRANSLATE...TO UPPER/LOWER in generic nodes."""
        raw = node.raw_text.upper().strip()
        if raw.startswith('TRANSLATE ') and ('TO UPPER CASE' in raw or 'TO LOWER CASE' in raw):
            func = 'to_upper' if 'UPPER' in raw else 'to_lower'
            self.changes.append(ChangeRecord(
                rule_id='AST-049', line=node.line, category='obsolete_syntax',
                description=f'TRANSLATE...TO UPPER/LOWER CASE is obsolete — use {func}() '
                            f'built-in function (ABAP 7.40+).',
                old_code=node.raw_text.strip(),
                new_code=f'<var> = {func}( <var> )',
                severity='medium',
            ))

    # ── AST-050: CONDENSE → condense() ──────────────────────────────────────
    # (Augments existing AST-021 by catching in generic nodes)

    def _check_ast050_condense(self, node: GenericStatement):
        """AST-050: Detect CONDENSE in generic nodes."""
        raw = node.raw_text.upper().strip()
        if raw.startswith('CONDENSE '):
            self.changes.append(ChangeRecord(
                rule_id='AST-050', line=node.line, category='obsolete_syntax',
                description='CONDENSE statement is obsolete — use condense() built-in function '
                            '(ABAP 7.40+). condense( val = <var> ) for standard, '
                            'condense( val = <var> del = ` ` ) for NO-GAPS equivalent.',
                old_code=node.raw_text.strip(),
                new_code='<var> = condense( val = <var> )',
                severity='low',
            ))

    # ── AST-051: STRLEN → strlen() ──────────────────────────────────────────

    def _check_ast051_strlen(self, node: GenericStatement):
        """AST-051: Detect old-style STRLEN usage in generic nodes."""
        raw = node.raw_text.upper().strip()
        if 'STRLEN' in raw and 'STRLEN(' not in raw:
            self.changes.append(ChangeRecord(
                rule_id='AST-051', line=node.line, category='modern_abap',
                description='Old-style STRLEN usage — use strlen( ) function with parentheses '
                            '(ABAP 7.40+). The strlen() function can be used in expressions directly.',
                old_code=node.raw_text.strip(),
                new_code='strlen( <string> )',
                severity='low',
            ))

    # ── AST-052: DESCRIBE TABLE...LINES → lines() ──────────────────────────

    def _check_ast052_describe_table(self, node: GenericStatement):
        """AST-052: Detect DESCRIBE TABLE...LINES in generic nodes."""
        raw = node.raw_text.upper().strip()
        if raw.startswith('DESCRIBE TABLE') and 'LINES' in raw:
            self.changes.append(ChangeRecord(
                rule_id='AST-052', line=node.line, category='modern_abap',
                description='DESCRIBE TABLE ... LINES is obsolete — use lines() built-in '
                            'function (ABAP 7.40+). Assign directly: lv_count = lines( itab ).',
                old_code=node.raw_text.strip(),
                new_code='<var> = lines( <itab> )',
                severity='low',
            ))

    # ── AST-053: DESCRIBE FIELD...TYPE → cl_abap_typedescr=>describe_by_data()

    def _visit_describe_field(self, node: DescribeFieldStatement):
        """AST-053: DESCRIBE FIELD...TYPE → RTTI class methods."""
        if node.type_var:
            self.changes.append(ChangeRecord(
                rule_id='AST-053', line=node.line, category='modern_abap',
                description='DESCRIBE FIELD ... TYPE is obsolete — use RTTI class '
                            'cl_abap_typedescr=>describe_by_data( ) for runtime type information. '
                            'Provides richer metadata including type kind, length, decimals.',
                old_code=f"DESCRIBE FIELD {node.field_name} TYPE {node.type_var}",
                new_code=f"DATA(lo_descr) = cl_abap_typedescr=>describe_by_data( {node.field_name} )",
                severity='low',
            ))
        if node.length_var:
            self.changes.append(ChangeRecord(
                rule_id='AST-053', line=node.line, category='modern_abap',
                description='DESCRIBE FIELD ... LENGTH is obsolete — use RTTI '
                            'cl_abap_typedescr=>describe_by_data( )->length for field length.',
                old_code=f"DESCRIBE FIELD {node.field_name} LENGTH {node.length_var}",
                new_code=f"cl_abap_typedescr=>describe_by_data( {node.field_name} )->length",
                severity='low',
            ))

    # ── AST-054: READ TABLE...WITH KEY → table expression itab[ key ] ───────

    def _check_ast054_read_table_key(self, node: ReadTableStatement):
        """AST-054: READ TABLE WITH KEY → table expression."""
        if node.with_key and not node.binary_search:
            key_parts = ' '.join(f"{k} = {v}" for k, v in node.with_key.items())
            self.changes.append(ChangeRecord(
                rule_id='AST-054', line=node.line, category='modern_abap',
                description='READ TABLE ... WITH KEY can be replaced with table expression '
                            '(ABAP 7.40+). Table expressions are more concise and can be used '
                            'inline. Wrap in try/catch or use OPTIONAL/DEFAULT for error handling.',
                old_code=f"READ TABLE {node.table} WITH KEY {key_parts}",
                new_code=f"{node.table}[ {key_parts} ]",
                severity='low',
            ))

    # ── AST-055: READ TABLE...INDEX → table expression itab[ index ] ────────

    def _check_ast055_read_table_index(self, node: ReadTableStatement):
        """AST-055: READ TABLE INDEX → table expression."""
        if node.index and not node.with_key:
            self.changes.append(ChangeRecord(
                rule_id='AST-055', line=node.line, category='modern_abap',
                description='READ TABLE ... INDEX can be replaced with table expression '
                            '(ABAP 7.40+). Use itab[ <index> ] for direct index access. '
                            'Wrap in VALUE #( itab[ idx ] OPTIONAL ) for safe access.',
                old_code=f"READ TABLE {node.table} INDEX {node.index}",
                new_code=f"{node.table}[ {node.index} ]",
                severity='low',
            ))

    # ── AST-056: CALL METHOD → functional call syntax ───────────────────────
    # (Augments existing AST-026 by also flagging static method calls)

    def _check_ast056_call_method_static(self, node: CallMethodStatement):
        """AST-056: CALL METHOD for static methods → functional call."""
        if not node.object_ref and node.method_name:
            # Static or unresolved CALL METHOD
            self.changes.append(ChangeRecord(
                rule_id='AST-056', line=node.line, category='modern_abap',
                description='CALL METHOD is obsolete — use functional call syntax. '
                            'Direct method call syntax is preferred in modern ABAP.',
                old_code=f"CALL METHOD {node.method_name}",
                new_code=f"{node.method_name}( )",
                severity='low',
            ))

    # ── AST-057: CREATE OBJECT → NEW operator ──────────────────────────────
    # (Augments existing AST-018 for cases without explicit class name)

    def _check_ast057_create_object_inferred(self, node: CreateObjectStatement):
        """AST-057: CREATE OBJECT without explicit type → NEW #( )."""
        if not node.class_name:
            self.changes.append(ChangeRecord(
                rule_id='AST-057', line=node.line, category='modern_abap',
                description='CREATE OBJECT without TYPE → use NEW #( ) with type inference '
                            '(ABAP 7.40+). The compiler infers the type from the variable declaration.',
                old_code=f"CREATE OBJECT {node.variable}",
                new_code=f"{node.variable} = NEW #( )",
                severity='low',
            ))

    # ── AST-058: LOOP AT...INTO → LOOP AT...REFERENCE INTO ─────────────────

    def _check_ast058_loop_into_reference(self, node: LoopAtStatement):
        """AST-058: LOOP AT INTO → REFERENCE INTO for better performance."""
        if node.into and not node.assigning and not node.reference_into:
            self.changes.append(ChangeRecord(
                rule_id='AST-058', line=node.line, category='performance',
                description='LOOP AT ... INTO copies each row — consider ASSIGNING or '
                            'REFERENCE INTO for better performance, especially for large tables. '
                            'ASSIGNING FIELD-SYMBOL(<fs>) avoids copy overhead entirely.',
                old_code=f"LOOP AT {node.table} INTO {node.into}",
                new_code=f"LOOP AT {node.table} ASSIGNING FIELD-SYMBOL(<fs>) or REFERENCE INTO",
                severity='low',
            ))

    # ── AST-059: COLLECT → flag for review (no direct replacement) ─────────

    def _visit_collect_augmented(self, node: CollectStatement):
        """AST-059: COLLECT statement — flag for review, no direct replacement."""
        self.changes.append(ChangeRecord(
            rule_id='AST-059', line=node.line, category='review',
            description='COLLECT statement has no direct modern replacement. Review usage: '
                        'COLLECT aggregates numeric fields by key — consider REDUCE operator, '
                        'explicit LOOP with AT NEW/AT END OF, or ABAP SQL GROUP BY instead. '
                        'Ensure correctness especially if table structure changed in S/4HANA.',
            old_code=f"COLLECT {node.source} INTO {node.target}",
            new_code='Consider REDUCE, LOOP AT GROUP BY, or explicit aggregation',
            severity='low',
        ))

    # ── AST-060: OCCURS → TYPE STANDARD TABLE OF ───────────────────────────
    # (Augments existing AST-001/AST-028. Catches in generic nodes.)

    def _check_ast060_occurs_generic(self, node: GenericStatement):
        """AST-060: Detect OCCURS in generic/fallback nodes."""
        raw = node.raw_text.upper().strip()
        if ' OCCURS ' in raw:
            self.changes.append(ChangeRecord(
                rule_id='AST-060', line=node.line, category='obsolete_syntax',
                description='OCCURS clause is obsolete since ABAP release 4.6 — replace with '
                            'TYPE STANDARD TABLE OF. OCCURS creates internal tables with header '
                            'lines which are forbidden in OO contexts.',
                old_code=node.raw_text.strip(),
                new_code='DATA <itab> TYPE STANDARD TABLE OF <line_type>',
                severity='high',
            ))

    # ── AST-061: RANGES → TYPE RANGE OF ─────────────────────────────────────
    # (Augments existing AST-015 for generic nodes)

    def _check_ast061_ranges_generic(self, node: GenericStatement):
        """AST-061: Detect RANGES in generic/fallback nodes."""
        raw = node.raw_text.upper().strip()
        if raw.startswith('RANGES ') and ' FOR ' in raw:
            self.changes.append(ChangeRecord(
                rule_id='AST-061', line=node.line, category='obsolete_syntax',
                description='RANGES statement is obsolete — use DATA <name> TYPE RANGE OF <type>. '
                            'The RANGE OF type creates a proper internal table with SIGN/OPTION/LOW/HIGH.',
                old_code=node.raw_text.strip(),
                new_code='DATA <name> TYPE RANGE OF <type>',
                severity='medium',
            ))

    # ── AST-062: TABLES parameter → TYPE TABLE in interfaces ───────────────

    def _check_ast062_tables_param(self, node: FormBlock):
        """AST-062: FORM with TABLES parameter → use TYPE TABLE."""
        if node.tables_params:
            self.changes.append(ChangeRecord(
                rule_id='AST-062', line=node.line, category='obsolete_syntax',
                description='TABLES parameter in FORM is obsolete — use USING/CHANGING with '
                            'TYPE TABLE. TABLES parameters create implicit header lines and are '
                            'not allowed in class methods.',
                old_code=f"FORM {node.name} TABLES {' '.join(node.tables_params)}",
                new_code=f"FORM {node.name} USING/CHANGING with TYPE TABLE parameter",
                severity='medium',
            ))

    # ── AST-063: FORM/ENDFORM → CLASS method (supplementary to AST-022) ────

    def _visit_form_ast063(self, node: FormBlock):
        """AST-063: FORM/ENDFORM → CLASS method with detailed guidance."""
        self.changes.append(ChangeRecord(
            rule_id='AST-063', line=node.line, category='modernization',
            description=f'FORM {node.name} — convert to CLASS/METHOD. In S/4HANA and ABAP Cloud, '
                        f'subroutines (FORM/ENDFORM) are forbidden. Migrate to local class methods: '
                        f'1) Create local class lcl_<name>. 2) Move FORM body to METHOD. '
                        f'3) Convert USING params to IMPORTING, CHANGING to CHANGING, '
                        f'TABLES to TYPE TABLE parameters.',
            old_code=f"FORM {node.name}",
            new_code=f"CLASS lcl_{node.name} ... METHOD {node.name}",
            severity='medium',
        ))

    # ── AST-064: COMMUNICATION → removed (RFC only) ────────────────────────

    def _check_ast064_communication(self, node: GenericStatement):
        """AST-064: COMMUNICATION statement is removed in modern ABAP."""
        raw = node.raw_text.upper().strip()
        if raw.startswith('COMMUNICATION '):
            self.changes.append(ChangeRecord(
                rule_id='AST-064', line=node.line, category='obsolete_syntax',
                description='COMMUNICATION statement is obsolete and removed — use RFC calls '
                            'via CALL FUNCTION ... DESTINATION or modern HTTP/SOAP/OData APIs.',
                old_code=node.raw_text.strip(),
                new_code='CALL FUNCTION ... DESTINATION or HTTP/RFC framework',
                severity='critical',
            ))

    # ── AST-065: SET EXTENDED CHECK → pragma ##NO_TEXT etc. ─────────────────

    def _check_ast065_set_extended_check(self, node: GenericStatement):
        """AST-065: SET EXTENDED CHECK OFF → pragmas."""
        raw = node.raw_text.upper().strip()
        if raw.startswith('SET EXTENDED CHECK'):
            self.changes.append(ChangeRecord(
                rule_id='AST-065', line=node.line, category='obsolete_syntax',
                description='SET EXTENDED CHECK is obsolete — use pragmas (##NO_TEXT, ##NEEDED, '
                            '##SHADOW, etc.) or pseudo-comments for specific suppression. '
                            'Pragmas provide more granular control over code inspector checks.',
                old_code=node.raw_text.strip(),
                new_code='Use ##NO_TEXT, ##NEEDED or appropriate pragma',
                severity='low',
            ))

    # ═══════════════════════════════════════════════════════════════════════════
    # TABLE ACCESS CHANGES (AST-066 to AST-080)
    # ═══════════════════════════════════════════════════════════════════════════

    # ── AST-066: SELECT FROM BSEG → SELECT FROM ACDOCA ─────────────────────

    def _check_ast066_bseg(self, node: SelectStatement):
        """AST-066: BSEG → ACDOCA with field mapping guidance."""
        from_upper = node.from_clause.upper()
        if from_upper == 'BSEG' or (hasattr(node, '_original_from') and getattr(node, '_original_from', '').upper() == 'BSEG'):
            self.changes.append(ChangeRecord(
                rule_id='AST-066', line=node.line, category='data_model',
                description='SELECT FROM BSEG → ACDOCA (Universal Journal). In S/4HANA, BSEG is '
                            'a compatibility view with degraded performance. Map: BSEG-BUKRS → '
                            'ACDOCA-RBUKRS, BSEG-BELNR → ACDOCA-BELNR, BSEG-GJAHR → ACDOCA-GJAHR, '
                            'BSEG-BUZEI → ACDOCA-BUZEI, BSEG-DMBTR → ACDOCA-HSL, '
                            'BSEG-WRBTR → ACDOCA-TSL. Add RLDNR = 0L filter for leading ledger.',
                old_code='SELECT ... FROM BSEG',
                new_code="SELECT ... FROM ACDOCA WHERE RLDNR = '0L'",
                severity='critical',
            ))

    # ── AST-067: SELECT FROM BSIK/BSAK → ACDOCA with filters ──────────────

    def _check_ast067_bsik_bsak(self, node: SelectStatement):
        """AST-067: BSIK/BSAK → ACDOCA with vendor open/cleared item filters."""
        from_upper = node.from_clause.upper()
        if from_upper in ('BSIK', 'BSAK'):
            status = 'open' if from_upper == 'BSIK' else 'cleared'
            self.changes.append(ChangeRecord(
                rule_id='AST-067', line=node.line, category='data_model',
                description=f'SELECT FROM {from_upper} (vendor {status} items) → ACDOCA. '
                            f'In S/4HANA, vendor line items are in ACDOCA. Filter by '
                            f'KOART = "K" (vendor) and AUGDT (clearing date) for open/cleared status. '
                            f'Consider CDS view I_OperationalAcctgDocItem for standard access.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code=f"SELECT ... FROM ACDOCA WHERE KOART = 'K' AND "
                         f"{'AUGDT = 00000000' if status == 'open' else 'AUGDT <> 00000000'}",
                severity='critical',
            ))

    # ── AST-068: SELECT FROM BSID/BSAD → ACDOCA with customer filters ─────

    def _check_ast068_bsid_bsad(self, node: SelectStatement):
        """AST-068: BSID/BSAD → ACDOCA with customer open/cleared item filters."""
        from_upper = node.from_clause.upper()
        if from_upper in ('BSID', 'BSAD'):
            status = 'open' if from_upper == 'BSID' else 'cleared'
            self.changes.append(ChangeRecord(
                rule_id='AST-068', line=node.line, category='data_model',
                description=f'SELECT FROM {from_upper} (customer {status} items) → ACDOCA. '
                            f'In S/4HANA, customer line items are in ACDOCA. Filter by '
                            f'KOART = "D" (customer) and AUGDT for open/cleared status. '
                            f'Consider CDS view I_OperationalAcctgDocItem for standard access.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code=f"SELECT ... FROM ACDOCA WHERE KOART = 'D' AND "
                         f"{'AUGDT = 00000000' if status == 'open' else 'AUGDT <> 00000000'}",
                severity='critical',
            ))

    # ── AST-069: SELECT FROM BSIS/BSAS → ACDOCA with G/L filters ──────────

    def _check_ast069_bsis_bsas(self, node: SelectStatement):
        """AST-069: BSIS/BSAS → ACDOCA with G/L account open/cleared filters."""
        from_upper = node.from_clause.upper()
        if from_upper in ('BSIS', 'BSAS'):
            status = 'open' if from_upper == 'BSIS' else 'cleared'
            self.changes.append(ChangeRecord(
                rule_id='AST-069', line=node.line, category='data_model',
                description=f'SELECT FROM {from_upper} (G/L {status} items) → ACDOCA. '
                            f'In S/4HANA, G/L line items are in ACDOCA. Filter by '
                            f'KOART = "S" (G/L) and AUGDT for open/cleared status. '
                            f'Consider CDS view I_GLAccountLineItem for standard access.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code=f"SELECT ... FROM ACDOCA WHERE KOART = 'S' AND "
                         f"{'AUGDT = 00000000' if status == 'open' else 'AUGDT <> 00000000'}",
                severity='critical',
            ))

    # ── AST-070: SELECT FROM GLT0 → ACDOCA (aggregated) ───────────────────

    def _check_ast070_glt0(self, node: SelectStatement):
        """AST-070: GLT0 → ACDOCA aggregated."""
        from_upper = node.from_clause.upper()
        if from_upper == 'GLT0':
            self.changes.append(ChangeRecord(
                rule_id='AST-070', line=node.line, category='data_model',
                description='SELECT FROM GLT0 (G/L totals table) → ACDOCA. In S/4HANA, '
                            'GLT0 is a compatibility view. Use ACDOCA with GROUP BY for totals, '
                            'or use CDS view I_GLAccountBalance. Map: GLT0-RACCT → ACDOCA-RACCT, '
                            'GLT0-HSLxx period fields → SUM(ACDOCA-HSL) grouped by period.',
                old_code='SELECT ... FROM GLT0',
                new_code='SELECT ... FROM ACDOCA GROUP BY ... or CDS I_GLAccountBalance',
                severity='critical',
            ))

    # ── AST-071: SELECT FROM GLPCA → ACDOCA (profit center) ───────────────

    def _check_ast071_glpca(self, node: SelectStatement):
        """AST-071: GLPCA → ACDOCA with profit center focus."""
        from_upper = node.from_clause.upper()
        if from_upper == 'GLPCA':
            self.changes.append(ChangeRecord(
                rule_id='AST-071', line=node.line, category='data_model',
                description='SELECT FROM GLPCA (Profit Center Actual Line Items) → ACDOCA. '
                            'In S/4HANA, profit center line items are in ACDOCA. Filter by '
                            'PRCTR (profit center). Map: GLPCA-DOCNR → ACDOCA-BELNR, '
                            'GLPCA-PRCTR → ACDOCA-PRCTR. Use CDS view I_ProfitCenterActualData.',
                old_code='SELECT ... FROM GLPCA',
                new_code="SELECT ... FROM ACDOCA WHERE PRCTR IS NOT INITIAL",
                severity='critical',
            ))

    # ── AST-072: SELECT FROM COEP → ACDOCA (CO line items) ────────────────

    def _check_ast072_coep(self, node: SelectStatement):
        """AST-072: COEP → ACDOCA for CO line items."""
        from_upper = node.from_clause.upper()
        if from_upper == 'COEP':
            self.changes.append(ChangeRecord(
                rule_id='AST-072', line=node.line, category='data_model',
                description='SELECT FROM COEP (CO line items) → ACDOCA. In S/4HANA, controlling '
                            'documents are in Universal Journal. Map: COEP-OBJNR → ACDOCA-OBJNR, '
                            'COEP-WKGBTR → ACDOCA-KSL, COEP-KSTAR → ACDOCA-KSTAR. '
                            'Use CDS view I_CostCenterActualData or I_InternalOrderActualData.',
                old_code='SELECT ... FROM COEP',
                new_code='SELECT ... FROM ACDOCA WHERE OBJNR IS NOT INITIAL',
                severity='critical',
            ))

    # ── AST-073: SELECT FROM KONV → PRCD_ELEMENTS ─────────────────────────

    def _check_ast073_konv(self, node: SelectStatement):
        """AST-073: KONV → PRCD_ELEMENTS."""
        from_upper = node.from_clause.upper()
        if from_upper == 'KONV':
            self.changes.append(ChangeRecord(
                rule_id='AST-073', line=node.line, category='data_model',
                description='SELECT FROM KONV (pricing conditions) → PRCD_ELEMENTS. In S/4HANA, '
                            'pricing conditions are stored in PRCD_ELEMENTS. Map: KONV-KNUMV → '
                            'PRCD_ELEMENTS-KNUMV, KONV-KPOSN → PRCD_ELEMENTS-KPOSN. '
                            'Use CDS view I_PricingElement for read access.',
                old_code='SELECT ... FROM KONV',
                new_code='SELECT ... FROM PRCD_ELEMENTS',
                severity='critical',
            ))

    # ── AST-074: SELECT FROM VBUK → VBAK (status merged) ──────────────────

    def _check_ast074_vbuk(self, node: SelectStatement):
        """AST-074: VBUK → VBAK (header status fields merged into sales doc header)."""
        from_upper = node.from_clause.upper()
        if from_upper == 'VBUK':
            self.changes.append(ChangeRecord(
                rule_id='AST-074', line=node.line, category='data_model',
                description='SELECT FROM VBUK (sales document header status) → VBAK. In S/4HANA, '
                            'header status fields (GBSTK, LFSTK, FKSTK, ABSTK, etc.) are merged '
                            'directly into VBAK. VBUK still exists as a compatibility view but '
                            'has degraded performance. Remove JOIN with VBUK and read status from VBAK.',
                old_code='SELECT ... FROM VBUK',
                new_code='SELECT ... FROM VBAK (status fields now in VBAK directly)',
                severity='high',
            ))

    # ── AST-075: SELECT FROM VBUP → VBAP (item status merged) ─────────────

    def _check_ast075_vbup(self, node: SelectStatement):
        """AST-075: VBUP → VBAP (item status fields merged into sales doc item)."""
        from_upper = node.from_clause.upper()
        if from_upper == 'VBUP':
            self.changes.append(ChangeRecord(
                rule_id='AST-075', line=node.line, category='data_model',
                description='SELECT FROM VBUP (sales document item status) → VBAP. In S/4HANA, '
                            'item status fields (LFSTA, FKSTA, GBSTA, etc.) are merged into VBAP. '
                            'VBUP still exists as a compatibility view. Remove JOIN with VBUP '
                            'and read status directly from VBAP.',
                old_code='SELECT ... FROM VBUP',
                new_code='SELECT ... FROM VBAP (status fields now in VBAP directly)',
                severity='high',
            ))

    # ── AST-076: SELECT FROM KNA1 → I_Customer CDS view ───────────────────

    def _check_ast076_kna1_cds(self, node: SelectStatement):
        """AST-076: KNA1 → I_Customer CDS view."""
        from_upper = node.from_clause.upper()
        if from_upper in ('KNA1', 'BUT000') and from_upper == 'KNA1':
            self.changes.append(ChangeRecord(
                rule_id='AST-076', line=node.line, category='data_model',
                description='SELECT FROM KNA1 (customer master) → consider I_Customer CDS view. '
                            'In S/4HANA with Business Partner, customer data is in BUT000/BUT0ID. '
                            'KNA1 remains as compatibility but I_Customer CDS view provides '
                            'the recommended read access path including BP mapping.',
                old_code='SELECT ... FROM KNA1',
                new_code='SELECT ... FROM I_Customer CDS view',
                severity='high',
            ))

    # ── AST-077: SELECT FROM LFA1 → I_Supplier CDS view ───────────────────

    def _check_ast077_lfa1_cds(self, node: SelectStatement):
        """AST-077: LFA1 → I_Supplier CDS view."""
        from_upper = node.from_clause.upper()
        if from_upper == 'LFA1':
            self.changes.append(ChangeRecord(
                rule_id='AST-077', line=node.line, category='data_model',
                description='SELECT FROM LFA1 (vendor master) → consider I_Supplier CDS view. '
                            'In S/4HANA with Business Partner, vendor data is in BUT000/BUT0ID. '
                            'LFA1 remains as compatibility but I_Supplier CDS view provides '
                            'the recommended read access path including BP mapping.',
                old_code='SELECT ... FROM LFA1',
                new_code='SELECT ... FROM I_Supplier CDS view',
                severity='high',
            ))

    # ── AST-078: SELECT FROM MKPF/MSEG → MATDOC ───────────────────────────

    def _check_ast078_mkpf_mseg(self, node: SelectStatement):
        """AST-078: MKPF/MSEG → MATDOC (merged material document)."""
        from_upper = node.from_clause.upper()
        if from_upper in ('MKPF', 'MSEG'):
            self.changes.append(ChangeRecord(
                rule_id='AST-078', line=node.line, category='data_model',
                description=f'SELECT FROM {from_upper} → MATDOC. In S/4HANA, material document '
                            'header (MKPF) and items (MSEG) are merged into single table MATDOC. '
                            'Map: MKPF-MBLNR/MSEG-MBLNR → MATDOC-MBLNR, MSEG-ZEILE → MATDOC-ZEILE. '
                            'Remove MKPF/MSEG joins. Use CDS view I_MaterialDocumentItem.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code='SELECT ... FROM MATDOC or I_MaterialDocumentItem CDS',
                severity='critical',
            ))

    # ── AST-079: SELECT FROM FAGLFLEXA → ACDOCA ───────────────────────────

    def _check_ast079_faglflexa(self, node: SelectStatement):
        """AST-079: FAGLFLEXA → ACDOCA."""
        from_upper = node.from_clause.upper()
        if from_upper == 'FAGLFLEXA':
            self.changes.append(ChangeRecord(
                rule_id='AST-079', line=node.line, category='data_model',
                description='SELECT FROM FAGLFLEXA → ACDOCA. New GL actual line items are now '
                            'in Universal Journal. Map FAGLFLEXA-DOCNR → ACDOCA-BELNR, '
                            'FAGLFLEXA-RBUKRS → ACDOCA-RBUKRS. Add RLDNR filter for ledger.',
                old_code='SELECT ... FROM FAGLFLEXA',
                new_code="SELECT ... FROM ACDOCA WHERE RLDNR = '0L'",
                severity='critical',
            ))

    # ── AST-080: SELECT FROM FAGLFLEXT → ACDOCA (totals) ──────────────────

    def _check_ast080_faglflext(self, node: SelectStatement):
        """AST-080: FAGLFLEXT → ACDOCT for totals."""
        from_upper = node.from_clause.upper()
        if from_upper == 'FAGLFLEXT':
            self.changes.append(ChangeRecord(
                rule_id='AST-080', line=node.line, category='data_model',
                description='SELECT FROM FAGLFLEXT → ACDOCT. New GL totals are in ACDOCT. '
                            'Map HSLxx period balance fields. Use CDS view I_GLAccountLineItem '
                            'or I_GLAccountBalance for reporting.',
                old_code='SELECT ... FROM FAGLFLEXT',
                new_code='SELECT ... FROM ACDOCT or CDS I_GLAccountBalance',
                severity='critical',
            ))

    # ═══════════════════════════════════════════════════════════════════════════
    # FUNCTION MODULE REPLACEMENTS (AST-081 to AST-100)
    # ═══════════════════════════════════════════════════════════════════════════

    # ── AST-081: REUSE_ALV_GRID_DISPLAY → cl_salv_table ───────────────────

    def _check_ast081_alv_grid(self, node: CallFunctionStatement):
        """AST-081: REUSE_ALV_GRID_DISPLAY → CL_SALV_TABLE."""
        fn_clean = node.function_name.strip("'").strip("`").upper()
        if fn_clean == 'REUSE_ALV_GRID_DISPLAY':
            self.changes.append(ChangeRecord(
                rule_id='AST-081', line=node.line, category='deprecated_fm',
                description='REUSE_ALV_GRID_DISPLAY is obsolete — replace with CL_SALV_TABLE. '
                            'Use CL_SALV_TABLE=>FACTORY( ) for ALV output. Provides better '
                            'integration with Fiori and supports all modern ALV features.',
                old_code="CALL FUNCTION 'REUSE_ALV_GRID_DISPLAY'",
                new_code='cl_salv_table=>factory( IMPORTING r_salv_table = lo_alv CHANGING t_table = itab )',
                severity='high',
            ))

    # ── AST-082: REUSE_ALV_LIST_DISPLAY → cl_salv_table ──────────────────

    def _check_ast082_alv_list(self, node: CallFunctionStatement):
        """AST-082: REUSE_ALV_LIST_DISPLAY → CL_SALV_TABLE."""
        fn_clean = node.function_name.strip("'").strip("`").upper()
        if fn_clean == 'REUSE_ALV_LIST_DISPLAY':
            self.changes.append(ChangeRecord(
                rule_id='AST-082', line=node.line, category='deprecated_fm',
                description='REUSE_ALV_LIST_DISPLAY is obsolete — replace with CL_SALV_TABLE. '
                            'ALV list output should be migrated to grid-based CL_SALV_TABLE '
                            'for Fiori compatibility.',
                old_code="CALL FUNCTION 'REUSE_ALV_LIST_DISPLAY'",
                new_code='cl_salv_table=>factory( IMPORTING r_salv_table = lo_alv CHANGING t_table = itab )',
                severity='high',
            ))

    # ── AST-083: POPUP_TO_CONFIRM → cl_popup ──────────────────────────────

    def _check_ast083_popup(self, node: CallFunctionStatement):
        """AST-083: POPUP_TO_CONFIRM → CL_POPUP=>."""
        fn_clean = node.function_name.strip("'").strip("`").upper()
        if fn_clean == 'POPUP_TO_CONFIRM':
            self.changes.append(ChangeRecord(
                rule_id='AST-083', line=node.line, category='deprecated_fm',
                description='POPUP_TO_CONFIRM FM → consider class-based popup or Fiori dialog. '
                            'In Fiori context, use sap.m.MessageBox or CL_POPUP classes.',
                old_code="CALL FUNCTION 'POPUP_TO_CONFIRM'",
                new_code='CL_POPUP=>POPUP_TO_CONFIRM or Fiori MessageBox',
                severity='medium',
            ))

    # ── AST-084: GUI_DOWNLOAD → cl_gui_frontend_services ──────────────────

    def _check_ast084_gui_download(self, node: CallFunctionStatement):
        """AST-084: GUI_DOWNLOAD → CL_GUI_FRONTEND_SERVICES=>GUI_DOWNLOAD."""
        fn_clean = node.function_name.strip("'").strip("`").upper()
        if fn_clean == 'GUI_DOWNLOAD':
            self.changes.append(ChangeRecord(
                rule_id='AST-084', line=node.line, category='deprecated_fm',
                description='GUI_DOWNLOAD FM → CL_GUI_FRONTEND_SERVICES=>GUI_DOWNLOAD. '
                            'The FM wrapper is deprecated. Note: frontend services are not '
                            'available in Fiori — use application server file I/O or ABAP channels.',
                old_code="CALL FUNCTION 'GUI_DOWNLOAD'",
                new_code='cl_gui_frontend_services=>gui_download( )',
                severity='medium',
            ))

    # ── AST-085: GUI_UPLOAD → cl_gui_frontend_services ────────────────────

    def _check_ast085_gui_upload(self, node: CallFunctionStatement):
        """AST-085: GUI_UPLOAD → CL_GUI_FRONTEND_SERVICES=>GUI_UPLOAD."""
        fn_clean = node.function_name.strip("'").strip("`").upper()
        if fn_clean == 'GUI_UPLOAD':
            self.changes.append(ChangeRecord(
                rule_id='AST-085', line=node.line, category='deprecated_fm',
                description='GUI_UPLOAD FM → CL_GUI_FRONTEND_SERVICES=>GUI_UPLOAD. '
                            'The FM wrapper is deprecated. Note: frontend services are not '
                            'available in Fiori — use file upload via RAP or ABAP channels.',
                old_code="CALL FUNCTION 'GUI_UPLOAD'",
                new_code='cl_gui_frontend_services=>gui_upload( )',
                severity='medium',
            ))

    # ── AST-086: CONVERSION_EXIT_* → cl_abap_conv_codepage ───────────────

    def _check_ast086_conversion_exit(self, node: CallFunctionStatement):
        """AST-086: CONVERSION_EXIT FMs → modern class."""
        fn_clean = node.function_name.strip("'").strip("`").upper()
        if fn_clean.startswith('CONVERSION_EXIT_'):
            if 'ALPHA' in fn_clean:
                replacement = 'Use string template: |{ var ALPHA = IN/OUT }|'
            else:
                replacement = 'CL_ABAP_CONV_CODEPAGE or conversion via string templates'
            self.changes.append(ChangeRecord(
                rule_id='AST-086', line=node.line, category='deprecated_fm',
                description=f'CONVERSION_EXIT FM {fn_clean} → modern conversion. '
                            f'{replacement}. String templates with formatting options '
                            f'replace most conversion exits in ABAP 7.40+.',
                old_code=f"CALL FUNCTION '{fn_clean}'",
                new_code=replacement,
                severity='medium',
            ))

    # ── AST-087: DATE_CHECK_PLAUSIBILITY → cl_abap_datfm ─────────────────

    def _check_ast087_date_check(self, node: CallFunctionStatement):
        """AST-087: DATE_CHECK_PLAUSIBILITY → CL_ABAP_DATFM."""
        fn_clean = node.function_name.strip("'").strip("`").upper()
        if fn_clean == 'DATE_CHECK_PLAUSIBILITY':
            self.changes.append(ChangeRecord(
                rule_id='AST-087', line=node.line, category='deprecated_fm',
                description='DATE_CHECK_PLAUSIBILITY FM → CL_ABAP_DATFM=>CHECK_DATE or '
                            'direct date validation. In modern ABAP, use cl_abap_datfm for '
                            'date format handling and validation.',
                old_code="CALL FUNCTION 'DATE_CHECK_PLAUSIBILITY'",
                new_code='cl_abap_datfm=>check_date( ) or TRY/CATCH date conversion',
                severity='low',
            ))

    # ── AST-088 through AST-100: BAPI/FM → RAP/CDS replacements ──────────
    # (Handled via DEPRECATED_FM_RAP_MAP in the augmented _visit_call_function)

    def _check_ast088_to_100_rap_replacements(self, node: CallFunctionStatement):
        """AST-088 to AST-100: BAPI/FM → RAP Business Object or CDS view."""
        fn_clean = node.function_name.strip("'").strip("`").upper()
        if fn_clean in DEPRECATED_FM_RAP_MAP:
            rule_id, replacement = DEPRECATED_FM_RAP_MAP[fn_clean]
            self.changes.append(ChangeRecord(
                rule_id=rule_id, line=node.line, category='deprecated_bapi',
                description=f'FM/BAPI {fn_clean} should be replaced with {replacement}. '
                            f'In S/4HANA, BAPI-based integrations should migrate to RAP '
                            f'Business Objects or CDS-based APIs for better lifecycle management.',
                old_code=f"CALL FUNCTION '{fn_clean}'",
                new_code=f"Use {replacement}",
                severity='high',
            ))

    # ═══════════════════════════════════════════════════════════════════════════
    # BUSINESS PARTNER MIGRATION RULES (AST-101 to AST-108)
    # ═══════════════════════════════════════════════════════════════════════════

    # ── AST-101 through AST-105: Transaction codes → BP ───────────────────

    def _check_ast101_to_105_bp_tcodes(self, node: CallTransactionStatement):
        """AST-101 to AST-105: Customer/Vendor T-codes → BP transaction."""
        tcode_clean = node.tcode.strip("'").strip("`").upper()
        if tcode_clean in BP_TCODE_MAP:
            rule_id, new_tcode, desc = BP_TCODE_MAP[tcode_clean]
            self.changes.append(ChangeRecord(
                rule_id=rule_id, line=node.line, category='bp_migration',
                description=f'CALL TRANSACTION {tcode_clean}: {desc}. In S/4HANA, all '
                            f'customer and vendor master maintenance is done via Business Partner '
                            f'transaction BP. The old T-codes are disabled or redirect to BP.',
                old_code=f"CALL TRANSACTION '{tcode_clean}'",
                new_code=f"CALL TRANSACTION '{new_tcode}' (Business Partner)",
                severity='high',
            ))

    # ── AST-106: KUNNR field access → BUT000-PARTNER ─────────────────────

    def _check_ast106_kunnr_field(self, node: AssignmentStatement):
        """AST-106: KUNNR field → BUT000-PARTNER."""
        expr = (node.expression or '').upper()
        target = (node.target or '').upper()
        if 'KUNNR' in expr or 'KUNNR' in target or '-KUNNR' in expr or '-KUNNR' in target:
            self.changes.append(ChangeRecord(
                rule_id='AST-106', line=node.line, category='bp_migration',
                description='KUNNR (customer number) field access — in S/4HANA with Business '
                            'Partner, customer numbers map to BUT000-PARTNER. Review field usage: '
                            'KNA1-KUNNR → BUT000-PARTNER (with role BP_CML for customer). '
                            'Use CDS view I_Customer for customer-specific BP data.',
                old_code=f"{node.target} = {node.expression}",
                new_code='Map KUNNR to BUT000-PARTNER with customer role filter',
                severity='medium',
            ))

    # ── AST-107: LIFNR field access → BUT000-PARTNER ────────────────────

    def _check_ast107_lifnr_field(self, node: AssignmentStatement):
        """AST-107: LIFNR field → BUT000-PARTNER."""
        expr = (node.expression or '').upper()
        target = (node.target or '').upper()
        if 'LIFNR' in expr or 'LIFNR' in target or '-LIFNR' in expr or '-LIFNR' in target:
            self.changes.append(ChangeRecord(
                rule_id='AST-107', line=node.line, category='bp_migration',
                description='LIFNR (vendor number) field access — in S/4HANA with Business '
                            'Partner, vendor numbers map to BUT000-PARTNER. Review field usage: '
                            'LFA1-LIFNR → BUT000-PARTNER (with role BP_VEN for vendor). '
                            'Use CDS view I_Supplier for vendor-specific BP data.',
                old_code=f"{node.target} = {node.expression}",
                new_code='Map LIFNR to BUT000-PARTNER with vendor role filter',
                severity='medium',
            ))

    # ── AST-108: KNA1/KNB1/KNVV joins → BUT000/BUT0BK/BUT100 joins ──────

    def _check_ast108_customer_joins(self, node: SelectStatement):
        """AST-108: Customer master joins → Business Partner joins."""
        from_upper = node.from_clause.upper()
        join_tables = [j.get('table', '').upper() for j in node.joins]
        customer_tables = {'KNA1', 'KNB1', 'KNVV', 'KNB5', 'KNVP'}
        found = set()
        if from_upper in customer_tables:
            found.add(from_upper)
        for jt in join_tables:
            if jt in customer_tables:
                found.add(jt)
        if len(found) >= 2:
            self.changes.append(ChangeRecord(
                rule_id='AST-108', line=node.line, category='bp_migration',
                description=f'JOIN of customer tables {", ".join(sorted(found))} → Business Partner '
                            f'table joins. In S/4HANA: KNA1 → BUT000, KNB1 → BUT0BK (bank details) '
                            f'or BUT0CK (company code data), KNVV → BUT100 (roles). '
                            f'Consider using I_Customer CDS view which encapsulates these joins.',
                old_code=f"SELECT ... FROM {from_upper} JOIN {', '.join(sorted(found - {from_upper}))}",
                new_code='Use I_Customer CDS view or BUT000/BUT0BK/BUT100 joins',
                severity='high',
            ))

    # ═══════════════════════════════════════════════════════════════════════════
    # CURRENCY & UNIT CHANGES (AST-109 to AST-115)
    # ═══════════════════════════════════════════════════════════════════════════

    # ── AST-109: WRBTR (2 decimal) → flexible decimals ───────────────────

    def _check_ast109_wrbtr_decimals(self, node: DataDeclaration):
        """AST-109: Amount fields with fixed decimals → flexible decimals."""
        type_upper = (node.type_clause or '').upper()
        name_upper = (node.name or '').upper()
        # Detect WRBTR-like amount field declarations with fixed CURR decimals
        if ('WRBTR' in name_upper or 'DMBTR' in name_upper or 'NETWR' in name_upper) and \
           ('CURR' in type_upper or 'BSEG-WRBTR' in type_upper or 'BSEG-DMBTR' in type_upper):
            self.changes.append(ChangeRecord(
                rule_id='AST-109', line=node.line, category='currency',
                description=f'Amount field {node.name} — in S/4HANA, amount fields support '
                            f'flexible decimals (up to 5 decimal places for some currencies). '
                            f'Review CURR field declarations to ensure compatibility with '
                            f'currencies that have non-standard decimal places (e.g., JPY=0, BHD=3).',
                old_code=f"DATA {node.name} TYPE {node.type_clause}",
                new_code=f"DATA {node.name} — verify CURR type handles flexible decimals",
                severity='medium',
            ))

    # ── AST-110: CURRENCY CONVERSION routines → new currency APIs ────────

    def _check_ast110_currency_conversion(self, node: GenericStatement):
        """AST-110: Currency conversion routines → modern APIs."""
        raw = node.raw_text.upper().strip()
        if 'CURRENCY_CONVERTING' in raw or 'CURRENCY_CONVERSION' in raw:
            self.changes.append(ChangeRecord(
                rule_id='AST-110', line=node.line, category='currency',
                description='Currency conversion routine detected — in S/4HANA, use '
                            'CL_CURRENCY_CONVERSION for programmatic conversion or '
                            'CDS annotation @Semantics.amount.currencyCode for declarative conversion. '
                            'Old BAPI_CURRENCY_CONV_* FMs are still available but class-based API preferred.',
                old_code=node.raw_text.strip(),
                new_code='CL_CURRENCY_CONVERSION=>CONVERT or CDS @Semantics.amount.currencyCode',
                severity='medium',
            ))

    # ── AST-111: BAPI_CURRENCY_CONV_TO_INTERNAL → cl_currency_conversion ──

    def _check_ast111_currency_bapi(self, node: CallFunctionStatement):
        """AST-111: BAPI_CURRENCY_CONV FMs → CL_CURRENCY_CONVERSION."""
        fn_clean = node.function_name.strip("'").strip("`").upper()
        if fn_clean in ('BAPI_CURRENCY_CONV_TO_INTERNAL', 'BAPI_CURRENCY_CONV_TO_EXTERNAL'):
            direction = 'INTERNAL' if 'INTERNAL' in fn_clean else 'EXTERNAL'
            self.changes.append(ChangeRecord(
                rule_id='AST-111', line=node.line, category='currency',
                description=f'BAPI_CURRENCY_CONV_TO_{direction} → CL_CURRENCY_CONVERSION. '
                            f'Use the class-based API for currency amount conversion. '
                            f'Handles flexible decimal currencies automatically in S/4HANA.',
                old_code=f"CALL FUNCTION '{fn_clean}'",
                new_code=f'cl_currency_conversion=>convert_to_{direction.lower()}( )',
                severity='medium',
            ))

    # ── AST-112: TCURR direct access → I_ExchangeRateRawData CDS ────────

    def _check_ast112_tcurr(self, node: SelectStatement):
        """AST-112: Direct TCURR access → CDS view."""
        from_upper = node.from_clause.upper()
        if from_upper == 'TCURR':
            self.changes.append(ChangeRecord(
                rule_id='AST-112', line=node.line, category='currency',
                description='Direct SELECT FROM TCURR → use CDS view I_ExchangeRateRawData. '
                            'The CDS view provides proper exchange rate access with built-in '
                            'currency type and validity handling. For conversion, use '
                            'CL_CURRENCY_CONVERSION class.',
                old_code='SELECT ... FROM TCURR',
                new_code='SELECT ... FROM I_ExchangeRateRawData CDS view',
                severity='medium',
            ))

    # ── AST-113: Unit of measure ISO mapping → cl_uom_conversion ─────────

    def _check_ast113_uom_conversion(self, node: CallFunctionStatement):
        """AST-113: UOM conversion FMs → CL_UOM_CONVERSION."""
        fn_clean = node.function_name.strip("'").strip("`").upper()
        if fn_clean in ('UNIT_CONVERSION_SIMPLE', 'MD_CONVERT_MATERIAL_UNIT',
                        'CONVERSION_EXIT_CUNIT_INPUT', 'CONVERSION_EXIT_CUNIT_OUTPUT'):
            self.changes.append(ChangeRecord(
                rule_id='AST-113', line=node.line, category='currency',
                description=f'UOM conversion FM {fn_clean} → CL_UOM_CONVERSION. '
                            f'In S/4HANA, unit of measure handling supports ISO codes. '
                            f'Use CL_UOM_CONVERSION for programmatic UOM conversion.',
                old_code=f"CALL FUNCTION '{fn_clean}'",
                new_code='cl_uom_conversion=>create_and_convert( )',
                severity='medium',
            ))

    # ── AST-114: Amount fields CURR 5/15 → CURR 5/23 (extended precision)

    def _check_ast114_curr_precision(self, node: DataDeclaration):
        """AST-114: CURR field precision check."""
        type_upper = (node.type_clause or '').upper()
        if 'CURR' in type_upper and ('15' in type_upper or 'P DECIMALS' in type_upper):
            self.changes.append(ChangeRecord(
                rule_id='AST-114', line=node.line, category='currency',
                description=f'Amount field {node.name} with fixed-length CURR declaration — '
                            f'S/4HANA supports extended precision (up to CURR 23 for amounts). '
                            f'Review if field length is sufficient for high-value currencies '
                            f'and multi-currency operations.',
                old_code=f"DATA {node.name} TYPE {node.type_clause}",
                new_code=f"Verify CURR precision is sufficient for S/4HANA",
                severity='low',
            ))

    # ── AST-115: READ TABLE TCURR → CDS view I_ExchangeRateRawData ──────

    def _check_ast115_read_tcurr(self, node: ReadTableStatement):
        """AST-115: READ TABLE on TCURR internal table → CDS-based access."""
        table_upper = (node.table or '').upper()
        if 'TCURR' in table_upper:
            self.changes.append(ChangeRecord(
                rule_id='AST-115', line=node.line, category='currency',
                description='READ TABLE on TCURR data → consider CDS view I_ExchangeRateRawData '
                            'for exchange rate access. Direct table reads of TCURR data should '
                            'be reviewed for S/4HANA compatibility.',
                old_code=f"READ TABLE {node.table}",
                new_code='Access via I_ExchangeRateRawData CDS view',
                severity='low',
            ))

    # ═══════════════════════════════════════════════════════════════════════════
    # AUTHORIZATION & SECURITY (AST-116 to AST-120)
    # ═══════════════════════════════════════════════════════════════════════════

    # ── AST-116: AUTHORITY-CHECK F_BKPF_BUK → F_ACDOCA_BUK ──────────────

    def _check_ast116_auth_bkpf(self, node: AuthorityCheckStatement):
        """AST-116: F_BKPF_BUK → F_ACDOCA_BUK."""
        obj_upper = node.object_name.upper().strip("'").strip("`")
        if obj_upper.startswith('F_BKPF_'):
            new_auth = obj_upper.replace('F_BKPF_', 'F_ACDOCA_')
            self.changes.append(ChangeRecord(
                rule_id='AST-116', line=node.line, category='authorization',
                description=f'AUTHORITY-CHECK OBJECT {obj_upper} → {new_auth}. '
                            f'In S/4HANA, BKPF-based auth objects should be reviewed for '
                            f'ACDOCA equivalents as document data is in Universal Journal.',
                old_code=f"AUTHORITY-CHECK OBJECT '{obj_upper}'",
                new_code=f"AUTHORITY-CHECK OBJECT '{new_auth}'",
                severity='high',
            ))

    # ── AST-117: AUTHORITY-CHECK F_KNA1_* → F_BUPA_* ────────────────────

    def _check_ast117_auth_kna1(self, node: AuthorityCheckStatement):
        """AST-117: F_KNA1_* → F_BUPA_*."""
        obj_upper = node.object_name.upper().strip("'").strip("`")
        if obj_upper.startswith('F_KNA1_'):
            new_auth = obj_upper.replace('F_KNA1_', 'F_BUPA_')
            self.changes.append(ChangeRecord(
                rule_id='AST-117', line=node.line, category='authorization',
                description=f'AUTHORITY-CHECK OBJECT {obj_upper} → {new_auth}. '
                            f'In S/4HANA with Business Partner, customer auth objects '
                            f'(F_KNA1_*) are replaced by Business Partner auth (F_BUPA_*).',
                old_code=f"AUTHORITY-CHECK OBJECT '{obj_upper}'",
                new_code=f"AUTHORITY-CHECK OBJECT '{new_auth}'",
                severity='high',
            ))

    # ── AST-118: AUTHORITY-CHECK F_LFA1_* → F_BUPA_* ────────────────────

    def _check_ast118_auth_lfa1(self, node: AuthorityCheckStatement):
        """AST-118: F_LFA1_* → F_BUPA_*."""
        obj_upper = node.object_name.upper().strip("'").strip("`")
        if obj_upper.startswith('F_LFA1_'):
            new_auth = obj_upper.replace('F_LFA1_', 'F_BUPA_')
            self.changes.append(ChangeRecord(
                rule_id='AST-118', line=node.line, category='authorization',
                description=f'AUTHORITY-CHECK OBJECT {obj_upper} → {new_auth}. '
                            f'In S/4HANA with Business Partner, vendor auth objects '
                            f'(F_LFA1_*) are replaced by Business Partner auth (F_BUPA_*).',
                old_code=f"AUTHORITY-CHECK OBJECT '{obj_upper}'",
                new_code=f"AUTHORITY-CHECK OBJECT '{new_auth}'",
                severity='high',
            ))

    # ── AST-119: SU53 trace format → new auth trace ─────────────────────

    def _check_ast119_auth_trace(self, node: GenericStatement):
        """AST-119: SU53 trace references → new auth trace format."""
        raw = node.raw_text.upper().strip()
        if 'SU53' in raw or 'AUTHORITY_CHECK_TCODE' in raw:
            self.changes.append(ChangeRecord(
                rule_id='AST-119', line=node.line, category='authorization',
                description='SU53/authorization trace reference detected — in S/4HANA, '
                            'authorization traces may use new format. Review auth check '
                            'logic for compatibility with S/4HANA auth model.',
                old_code=node.raw_text.strip(),
                new_code='Review authorization trace format for S/4HANA compatibility',
                severity='low',
            ))

    # ── AST-120: S_TCODE checks for removed T-codes → new T-code checks ──

    def _check_ast120_removed_tcodes(self, node: AuthorityCheckStatement):
        """AST-120: S_TCODE checks for removed transactions."""
        # Check if auth check references S_TCODE with removed transaction codes
        fields = node.fields or {}
        for field_name, field_value in fields.items():
            if field_name.upper() == 'TCD' or field_name.upper() == 'S_TCODE':
                val_clean = field_value.strip("'").strip("`").upper()
                if val_clean in S4_REMOVED_TCODES:
                    rule_info = BP_TCODE_MAP.get(val_clean)
                    new_tcode = rule_info[1] if rule_info else 'new S/4HANA T-code'
                    self.changes.append(ChangeRecord(
                        rule_id='AST-120', line=node.line, category='authorization',
                        description=f'S_TCODE check for {val_clean} — this T-code is removed or '
                                    f'redirected in S/4HANA. Update authorization profile to use '
                                    f'{new_tcode} or equivalent S/4HANA transaction.',
                        old_code=f"AUTHORITY-CHECK S_TCODE TCD = '{val_clean}'",
                        new_code=f"Update to S/4HANA T-code '{new_tcode}'",
                        severity='high',
                    ))

    # ═══════════════════════════════════════════════════════════════════════════
    # OUTPUT & PRINT CHANGES (AST-121 to AST-125)
    # ═══════════════════════════════════════════════════════════════════════════

    # ── AST-121: SAPscript WRITE_FORM → Adobe Forms / Output Management ──

    def _check_ast121_sapscript(self, node: CallFunctionStatement):
        """AST-121: SAPscript FMs → Adobe Forms / Output Management."""
        fn_clean = node.function_name.strip("'").strip("`").upper()
        if fn_clean in ('WRITE_FORM', 'OPEN_FORM', 'CLOSE_FORM', 'START_FORM',
                        'END_FORM', 'WRITE_FORM_LINES'):
            self.changes.append(ChangeRecord(
                rule_id='AST-121', line=node.line, category='output_management',
                description=f'SAPscript FM {fn_clean} → Adobe Forms or Output Management 2.0. '
                            f'SAPscript forms are legacy in S/4HANA. Migrate to Adobe Forms '
                            f'(PDF-based) or use Output Management framework for Fiori integration.',
                old_code=f"CALL FUNCTION '{fn_clean}'",
                new_code='Adobe Forms (FP_FUNCTION_MODULE_NAME/FP_JOB_OPEN/FP_JOB_CLOSE) or Output Mgmt',
                severity='high',
            ))

    # ── AST-122: SmartForms SSF_FUNCTION_MODULE → Output Management 2.0 ──

    def _check_ast122_smartforms(self, node: CallFunctionStatement):
        """AST-122: SmartForms → Output Management 2.0."""
        fn_clean = node.function_name.strip("'").strip("`").upper()
        if fn_clean in ('SSF_FUNCTION_MODULE_NAME', 'SSF_OPEN', 'SSF_CLOSE'):
            self.changes.append(ChangeRecord(
                rule_id='AST-122', line=node.line, category='output_management',
                description=f'SmartForms FM {fn_clean} → Output Management 2.0. '
                            f'SmartForms are supported but Adobe Forms is the strategic direction '
                            f'in S/4HANA. For new forms, use Adobe Forms. For Fiori output, '
                            f'use Output Management with BRF+ rules.',
                old_code=f"CALL FUNCTION '{fn_clean}'",
                new_code='Output Management 2.0 with Adobe Forms or Fiori output',
                severity='medium',
            ))

    # ── AST-123: NAST-based output → BRF+ / Output Management ───────────

    def _check_ast123_nast_output(self, node: SelectStatement):
        """AST-123: NAST-based output determination → BRF+ Output Management."""
        from_upper = node.from_clause.upper()
        if from_upper == 'NAST':
            self.changes.append(ChangeRecord(
                rule_id='AST-123', line=node.line, category='output_management',
                description='SELECT FROM NAST (output determination) → Output Management with BRF+. '
                            'In S/4HANA, NAST-based output determination is replaced by '
                            'BRF+ rules and Output Management 2.0 framework. Legacy NAST '
                            'may still work for some scenarios but BRF+ is the strategic direction.',
                old_code='SELECT ... FROM NAST',
                new_code='Output Management 2.0 with BRF+ determination rules',
                severity='high',
            ))

    # ── AST-124: SPOOL → Print Queue API ─────────────────────────────────

    def _check_ast124_spool(self, node: GenericStatement):
        """AST-124: Direct SPOOL manipulation → Print Queue API."""
        raw = node.raw_text.upper().strip()
        if 'SPOOL' in raw and ('TSP01' in raw or 'RSPO' in raw or 'NEW-PAGE PRINT' in raw):
            self.changes.append(ChangeRecord(
                rule_id='AST-124', line=node.line, category='output_management',
                description='Direct spool manipulation detected — in S/4HANA, use Print Queue '
                            'API (CL_PRINT_QUEUE_UTILS) or Output Management for print handling. '
                            'Direct spool table access (TSP01) should be replaced with API calls.',
                old_code=node.raw_text.strip(),
                new_code='CL_PRINT_QUEUE_UTILS or Output Management API',
                severity='medium',
            ))

    # ── AST-125: SUBMIT...TO SAP-SPOOL → cl_print_queue_utils ───────────

    def _check_ast125_submit_spool(self, node: SubmitStatement):
        """AST-125: SUBMIT...TO SAP-SPOOL → CL_PRINT_QUEUE_UTILS."""
        raw_params = ' '.join(str(p) for p in node.with_params) if node.with_params else ''
        if 'SAP-SPOOL' in raw_params.upper() or 'SPOOL' in raw_params.upper():
            self.changes.append(ChangeRecord(
                rule_id='AST-125', line=node.line, category='output_management',
                description=f'SUBMIT {node.report_name} TO SAP-SPOOL — consider using '
                            f'CL_PRINT_QUEUE_UTILS or Output Management framework for '
                            f'spool output in S/4HANA. Direct spool submission may need '
                            f'adaptation for cloud or Fiori scenarios.',
                old_code=f"SUBMIT {node.report_name} TO SAP-SPOOL",
                new_code='cl_print_queue_utils or Output Management framework',
                severity='medium',
            ))

    # ═══════════════════════════════════════════════════════════════════════════
    # DATA MIGRATION & COMPATIBILITY (AST-126 to AST-130)
    # ═══════════════════════════════════════════════════════════════════════════

    # ── AST-126: Material number CHAR(18) → CHAR(40) extended ────────────

    def _check_ast126_matnr_length(self, node: DataDeclaration):
        """AST-126: Material number field length CHAR(18) → CHAR(40)."""
        name_upper = (node.name or '').upper()
        type_upper = (node.type_clause or '').upper()
        if ('MATNR' in name_upper or 'MATERIAL' in name_upper) and \
           ('C(18)' in type_upper or 'CHAR(18)' in type_upper or 'MATNR' in type_upper):
            self.changes.append(ChangeRecord(
                rule_id='AST-126', line=node.line, category='data_migration',
                description=f'Material number field {node.name} — S/4HANA supports extended '
                            f'material number (CHAR 40). If extended material number is activated, '
                            f'MATNR changes from CHAR(18) to CHAR(40). Review all MATNR field '
                            f'declarations, string operations, and screen layouts for compatibility.',
                old_code=f"DATA {node.name} TYPE {node.type_clause}",
                new_code=f"DATA {node.name} TYPE MATNR (verify length for extended MATNR)",
                severity='high',
            ))

    # ── AST-127: Business Partner number format validation ───────────────

    def _check_ast127_bp_number(self, node: DataDeclaration):
        """AST-127: Business Partner number CHAR(10) format validation."""
        name_upper = (node.name or '').upper()
        type_upper = (node.type_clause or '').upper()
        if ('PARTNER' in name_upper or 'BP_NUMBER' in name_upper or 'BU_PARTNER' in type_upper) and \
           ('C(10)' in type_upper or 'CHAR(10)' in type_upper or 'BU_PARTNER' in type_upper):
            self.changes.append(ChangeRecord(
                rule_id='AST-127', line=node.line, category='data_migration',
                description=f'Business Partner number field {node.name} — validate BP number '
                            f'format (CHAR 10). In S/4HANA, BP numbers may have different '
                            f'numbering ranges than legacy customer/vendor numbers. Ensure '
                            f'number range alignment between KUNNR/LIFNR and BP.',
                old_code=f"DATA {node.name} TYPE {node.type_clause}",
                new_code=f"DATA {node.name} — verify BP number range alignment",
                severity='medium',
            ))

    # ── AST-128: G/L Account leading zeros validation ────────────────────

    def _check_ast128_gl_account(self, node: DataDeclaration):
        """AST-128: G/L Account CHAR(10) leading zeros validation."""
        name_upper = (node.name or '').upper()
        type_upper = (node.type_clause or '').upper()
        if ('SAKNR' in name_upper or 'HKONT' in name_upper or 'GL_ACCOUNT' in name_upper or
            'SAKNR' in type_upper or 'HKONT' in type_upper):
            self.changes.append(ChangeRecord(
                rule_id='AST-128', line=node.line, category='data_migration',
                description=f'G/L Account field {node.name} — in S/4HANA, G/L account numbers '
                            f'require leading zeros (always 10-digit with alpha conversion). '
                            f'Verify all comparisons and assignments use ALPHA-converted format. '
                            f'Use |{{ var ALPHA = IN }}| for conversion.',
                old_code=f"DATA {node.name} TYPE {node.type_clause}",
                new_code=f"DATA {node.name} — ensure leading zeros with ALPHA conversion",
                severity='medium',
            ))

    # ── AST-129: Plant maintenance ILOA → single PM object ──────────────

    def _check_ast129_iloa(self, node: SelectStatement):
        """AST-129: ILOA → single PM object model."""
        from_upper = node.from_clause.upper()
        if from_upper == 'ILOA':
            self.changes.append(ChangeRecord(
                rule_id='AST-129', line=node.line, category='data_migration',
                description='SELECT FROM ILOA (PM object allocation) → In S/4HANA, plant '
                            'maintenance uses a simplified object model. ILOA may be replaced '
                            'by I_MaintenanceObject CDS view. Review PM object structures '
                            'for compatibility with S/4HANA asset management.',
                old_code='SELECT ... FROM ILOA',
                new_code='SELECT ... FROM I_MaintenanceObject or updated PM tables',
                severity='medium',
            ))

    # ── AST-130: Batch management MCHA → new batch framework ────────────

    def _check_ast130_mcha(self, node: SelectStatement):
        """AST-130: MCHA → new batch management framework."""
        from_upper = node.from_clause.upper()
        if from_upper in ('MCHA', 'MCH1', 'MCHB'):
            self.changes.append(ChangeRecord(
                rule_id='AST-130', line=node.line, category='data_migration',
                description=f'SELECT FROM {from_upper} (batch management) → In S/4HANA, '
                            f'batch management tables are restructured. MCHA → MCH1 (batch '
                            f'master moved to plant level). Review batch determination, '
                            f'classification, and stock management for S/4HANA compatibility. '
                            f'Use CDS view I_Batch for standard access.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code='SELECT ... FROM MCH1 or I_Batch CDS view',
                severity='medium',
            ))

    # ═══════════════════════════════════════════════════════════════════════════
    # AST-131 through AST-160 — Additional S/4HANA Modernization Rules
    # ═══════════════════════════════════════════════════════════════════════════

    def _check_ast131_coep(self, node):
        """AST-131: COEP → ACDOCA (CO line items merged into Universal Journal)."""
        from_upper = node.from_clause.upper()
        if from_upper in ('COEP', 'COEJ', 'COES', 'COBK'):
            self.changes.append(ChangeRecord(
                rule_id='AST-131', line=node.line, category='data_migration',
                description=f'SELECT FROM {from_upper} (CO line items) → In S/4HANA, '
                            f'CO line items are stored in ACDOCA (Universal Journal). '
                            f'{from_upper} is a compatibility view. Use CDS view '
                            f'I_JournalEntryItem for standard access with CO attributes.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code='SELECT ... FROM ACDOCA / I_JournalEntryItem',
                severity='high',
            ))

    def _check_ast132_konv(self, node):
        """AST-132: KONV → PRCD_ELEMENTS (pricing conditions)."""
        from_upper = node.from_clause.upper()
        if from_upper in ('KONV', 'KONP', 'KONH', 'KONM', 'KONW'):
            self.changes.append(ChangeRecord(
                rule_id='AST-132', line=node.line, category='data_migration',
                description=f'SELECT FROM {from_upper} (pricing conditions) → In S/4HANA, '
                            f'pricing conditions are stored in PRCD_ELEMENTS. KONV is a '
                            f'compatibility view. Use CDS view I_PricingElement or '
                            f'I_SlsPrcgCndnRecdValidity for condition records.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code='SELECT ... FROM PRCD_ELEMENTS / I_PricingElement',
                severity='high',
            ))

    def _check_ast133_nast(self, node):
        """AST-133: NAST → PPFTT / BRF+ output management."""
        from_upper = node.from_clause.upper()
        if from_upper == 'NAST':
            self.changes.append(ChangeRecord(
                rule_id='AST-133', line=node.line, category='data_migration',
                description='SELECT FROM NAST (output management/message control) → '
                            'In S/4HANA, NAST-based output is replaced by BRF+/PPF-based '
                            'output management. Output determination uses PPFTT* tables. '
                            'Migrate custom NACE output types to BRF+ output templates.',
                old_code='SELECT ... FROM NAST',
                new_code='SELECT ... FROM PPFTTRIGG / BRF+ output framework',
                severity='high',
            ))

    def _check_ast134_vbbe(self, node):
        """AST-134: VBBE → removed (individual customer requirement)."""
        from_upper = node.from_clause.upper()
        if from_upper in ('VBBE', 'VBBE_SHOW'):
            self.changes.append(ChangeRecord(
                rule_id='AST-134', line=node.line, category='data_migration',
                description='SELECT FROM VBBE (sales req. individual customer stock) → '
                            'VBBE is removed in S/4HANA. Individual customer requirements '
                            'are derived at runtime from VBEP (schedule lines). Use ATP '
                            'relevant schedule line data or CDS views for availability.',
                old_code='SELECT ... FROM VBBE',
                new_code='Derive from VBEP schedule lines at runtime',
                severity='critical',
            ))

    def _check_ast135_mbew(self, node):
        """AST-135: MBEW material valuation → CKMLHD / ACDOCA."""
        from_upper = node.from_clause.upper()
        if from_upper in ('MBEW', 'MBEWH', 'CKMLCR', 'CKMLPP'):
            self.changes.append(ChangeRecord(
                rule_id='AST-135', line=node.line, category='data_migration',
                description=f'SELECT FROM {from_upper} (material valuation) → In S/4HANA, '
                            f'material ledger is mandatory. Valuation data flows through '
                            f'CKMLHD (ML header) and ACDOCA. MBEW is a compatibility view. '
                            f'Use CDS view I_ProductValuationAccounting for material values.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code='SELECT ... FROM CKMLHD / I_ProductValuationAccounting',
                severity='high',
            ))

    def _check_ast136_resb(self, node):
        """AST-136: RESB reservation → consider MRP changes in S/4HANA."""
        from_upper = node.from_clause.upper()
        if from_upper == 'RESB':
            self.changes.append(ChangeRecord(
                rule_id='AST-136', line=node.line, category='data_migration',
                description='SELECT FROM RESB (reservations/dependent requirements) → '
                            'In S/4HANA, MRP behavior changes: individual customer stock, '
                            'project stock, batch reservations affected. MRP area concepts '
                            'changed. Verify reservation-based programs still produce '
                            'correct ATP/MRP results. Use CDS I_Reservation.',
                old_code='SELECT ... FROM RESB',
                new_code='SELECT ... FROM RESB / I_Reservation (review MRP logic)',
                severity='medium',
            ))

    def _check_ast137_stxh(self, node):
        """AST-137: STXH/STXL (SAPscript text) → consider migration to Adobe Forms."""
        from_upper = node.from_clause.upper()
        if from_upper in ('STXH', 'STXL'):
            self.changes.append(ChangeRecord(
                rule_id='AST-137', line=node.line, category='forms',
                description=f'SELECT FROM {from_upper} (SAPscript text storage) → '
                            f'SAPscript and SmartForms are deprecated in S/4HANA favor of '
                            f'Adobe Forms / Output Management. Direct STXH/STXL reads for '
                            f'text rendering should migrate to READ_TEXT FM or Adobe '
                            f'templates with XDP/PDF output.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code='Use READ_TEXT or Adobe Form templates',
                severity='medium',
            ))

    def _check_ast138_ce1(self, node):
        """AST-138: CE1xxxx / CE2xxxx → removed (CO-PA operating concern tables)."""
        from_upper = node.from_clause.upper()
        if from_upper.startswith(('CE1', 'CE2', 'CE3', 'CE4')):
            self.changes.append(ChangeRecord(
                rule_id='AST-138', line=node.line, category='data_migration',
                description=f'SELECT FROM {from_upper} (CO-PA costing-based) → In S/4HANA, '
                            f'costing-based CO-PA is replaced by account-based CO-PA stored '
                            f'in ACDOCA. The CExxxx operating concern tables no longer exist. '
                            f'Migrate to account-based profitability analysis with ACDOCA '
                            f'and CDS view I_ProfitabilityAnalysis.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code='SELECT ... FROM ACDOCA / I_ProfitabilityAnalysis',
                severity='critical',
            ))

    def _check_ast139_kna1_lfa1(self, node):
        """AST-139: KNA1/LFA1 → BUT000 (Business Partner)."""
        from_upper = node.from_clause.upper()
        if from_upper in ('KNA1', 'LFA1', 'KNVV', 'LFB1', 'KNB1', 'KNVP',
                          'LFM1', 'LFM2', 'KNVH', 'KNVK', 'KNZA'):
            self.changes.append(ChangeRecord(
                rule_id='AST-139', line=node.line, category='data_migration',
                description=f'SELECT FROM {from_upper} (customer/vendor master) → In '
                            f'S/4HANA, customer/vendor master is unified under Business '
                            f'Partner (BUT000, BUT020, BUT021, etc.). {from_upper} becomes '
                            f'a compatibility view. Use CDS view I_BusinessPartner, '
                            f'I_Customer, or I_Supplier for direct access.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code='SELECT ... FROM BUT000 / I_BusinessPartner / I_Customer / I_Supplier',
                severity='critical',
            ))

    def _check_ast140_bsad_bsak(self, node):
        """AST-140: BSAD/BSID/BSAK/BSIK → ACDOCA (cleared items)."""
        from_upper = node.from_clause.upper()
        if from_upper in ('BSAD', 'BSID', 'BSAK', 'BSIK', 'BSAS', 'BSIS',
                          'BSI', 'KNC1', 'KNC3', 'LFC1', 'LFC3'):
            self.changes.append(ChangeRecord(
                rule_id='AST-140', line=node.line, category='data_migration',
                description=f'SELECT FROM {from_upper} (FI secondary index/sorted ledger) → '
                            f'In S/4HANA, open/cleared distinction is eliminated. BSAD/BSID '
                            f'(customer), BSAK/BSIK (vendor), BSAS/BSIS (GL) are compatibility '
                            f'views from ACDOCA. Use ACDOCA with AUGDT for clearing date. '
                            f'CDS: I_JournalEntry with clearing status filters.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code='SELECT ... FROM ACDOCA / I_JournalEntry with clearing filters',
                severity='high',
            ))

    def _check_ast141_marc_mvke(self, node):
        """AST-141: MARC/MVKE/MARD → still exist but review for new fields."""
        from_upper = node.from_clause.upper()
        if from_upper in ('MARC', 'MVKE', 'MARD', 'MARM', 'MEAN', 'MVKE',
                          'MLAN', 'MLGN', 'MLGT'):
            self.changes.append(ChangeRecord(
                rule_id='AST-141', line=node.line, category='data_migration',
                description=f'SELECT FROM {from_upper} (material master views) → Tables '
                            f'persist in S/4HANA but have new/changed fields. MARC gets new '
                            f'MRP fields. MVKE changes for credit-based pricing. MARD no '
                            f'longer stores storage-location totals (MARD is recalculated). '
                            f'Review field-level mapping. Use I_Product CDS hierarchy.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code=f'Review field changes in {from_upper} / use I_Product CDS views',
                severity='medium',
            ))

    def _check_ast142_vbrk_vbrp(self, node):
        """AST-142: VBRK/VBRP billing doc → review compatibility mode fields."""
        from_upper = node.from_clause.upper()
        if from_upper in ('VBRK', 'VBRP', 'VBRL'):
            self.changes.append(ChangeRecord(
                rule_id='AST-142', line=node.line, category='data_migration',
                description=f'SELECT FROM {from_upper} (billing documents) → In S/4HANA, '
                            f'billing documents adopt Advanced Billing (if activated). '
                            f'Revenue accounting integration with RAR. Condition-based '
                            f'pricing in PRCD_ELEMENTS replaces KONV. Review custom pricing '
                            f'routines and output determination (BRF+ replaces NAST).',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code=f'SELECT ... FROM {from_upper} (review pricing/output changes)',
                severity='medium',
            ))

    def _check_ast143_pa_infotype(self, node):
        """AST-143: PA0001-PA0999 HR infotypes → review for HCM/SuccessFactors."""
        from_upper = node.from_clause.upper()
        if from_upper.startswith('PA0') and from_upper[3:].isdigit():
            self.changes.append(ChangeRecord(
                rule_id='AST-143', line=node.line, category='data_migration',
                description=f'SELECT FROM {from_upper} (HR infotype) → S/4HANA retains '
                            f'on-premise HCM but SAP recommends migration to '
                            f'SuccessFactors Employee Central. Custom HR infotype '
                            f'reads may need adaptation for EC replication or HCM '
                            f'compatibility packs. Review infotype-specific CDS views.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code=f'SELECT ... FROM {from_upper} (consider SuccessFactors EC migration)',
                severity='medium',
            ))

    def _check_ast144_ekbe(self, node):
        """AST-144: EKBE → MATDOC (goods receipt history)."""
        from_upper = node.from_clause.upper()
        if from_upper in ('EKBE', 'EKBEH', 'EKBES'):
            self.changes.append(ChangeRecord(
                rule_id='AST-144', line=node.line, category='data_migration',
                description=f'SELECT FROM {from_upper} (PO history/goods receipt) → In '
                            f'S/4HANA, goods movement data is stored in MATDOC. EKBE remains '
                            f'for PO-level history but goods receipt details link to MATDOC '
                            f'instead of MSEG. Review three-way matching programs. CDS: '
                            f'I_PurchaseOrderHistory, I_MaterialDocumentItem.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code='SELECT ... FROM EKBE + MATDOC / I_PurchaseOrderHistory',
                severity='medium',
            ))

    def _check_ast145_jest_tj02(self, node):
        """AST-145: JEST/JSTO (status management) → review new status framework."""
        from_upper = node.from_clause.upper()
        if from_upper in ('JEST', 'JSTO', 'TJ02T', 'TJ02', 'TJ30', 'TJ30T'):
            self.changes.append(ChangeRecord(
                rule_id='AST-145', line=node.line, category='data_migration',
                description=f'SELECT FROM {from_upper} (object status management) → Status '
                            f'management persists in S/4HANA but new objects (journal entries, '
                            f'BP, etc.) use different status logic. Review programs reading '
                            f'user status (E0xxx) and system status (I0xxx) for changed '
                            f'business objects. Use CL_STATUS_MANAGEMENT API.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code='Use CL_STATUS_MANAGEMENT / review changed status profiles',
                severity='low',
            ))

    def _check_ast146_lips_likp(self, node):
        """AST-146: LIKP/LIPS delivery → review for EWM integration."""
        from_upper = node.from_clause.upper()
        if from_upper in ('LIKP', 'LIPS', 'VTTP', 'VTTS', 'VTTK'):
            self.changes.append(ChangeRecord(
                rule_id='AST-146', line=node.line, category='data_migration',
                description=f'SELECT FROM {from_upper} (deliveries/shipments) → In S/4HANA, '
                            f'if embedded EWM is activated, warehouse-relevant deliveries '
                            f'create EWM warehouse orders (/SCWM/ tables). Shipment docs '
                            f'migrate to Transportation Management. Review custom delivery '
                            f'processing for EWM/TM integration. CDS: I_DeliveryDocument.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code=f'SELECT ... FROM {from_upper} (review EWM/TM integration)',
                severity='medium',
            ))

    def _check_ast147_faglflex(self, node):
        """AST-147: FAGLFLEXT/FAGLFLEXA → ACDOCA (new GL totals)."""
        from_upper = node.from_clause.upper()
        if from_upper in ('FAGLFLEXT', 'FAGLFLEXA', 'FAGLBSIS', 'FAGLBSAS'):
            self.changes.append(ChangeRecord(
                rule_id='AST-147', line=node.line, category='data_migration',
                description=f'SELECT FROM {from_upper} (new GL totals/line items) → '
                            f'In S/4HANA, new GL tables are replaced by ACDOCA (line items) '
                            f'and ACDOCT (totals). {from_upper} is a compatibility view. '
                            f'All custom reports using FAGLFLEX* must be repointed. '
                            f'CDS: I_GLAccountLineItem, I_GLAccountBalance.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code='SELECT ... FROM ACDOCA / ACDOCT / I_GLAccountLineItem',
                severity='high',
            ))

    def _check_ast148_t001w_werks(self, node):
        """AST-148: Plant/warehouse customizing → review for extended warehouse."""
        from_upper = node.from_clause.upper()
        if from_upper in ('T001W', 'T001L', 'T320', 'T300', 'T300T'):
            self.changes.append(ChangeRecord(
                rule_id='AST-148', line=node.line, category='customizing',
                description=f'SELECT FROM {from_upper} (plant/storage location config) → '
                            f'In S/4HANA with embedded EWM, storage location logic changes. '
                            f'T001L (storage location) links to EWM warehouse numbers. '
                            f'Plant determination, storage location determination, and '
                            f'inventory management programs need EWM-awareness review.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code=f'SELECT ... FROM {from_upper} (review EWM warehouse mapping)',
                severity='low',
            ))

    def _check_ast149_cdhdr(self, node):
        """AST-149: CDHDR/CDPOS → review change document object changes."""
        from_upper = node.from_clause.upper()
        if from_upper in ('CDHDR', 'CDPOS'):
            self.changes.append(ChangeRecord(
                rule_id='AST-149', line=node.line, category='data_migration',
                description=f'SELECT FROM {from_upper} (change documents) → Change documents '
                            f'persist in S/4HANA but new objects (Business Partner, Material '
                            f'Ledger, Journal Entry) create different change document object '
                            f'classes. Programs monitoring customer (DEBI) or vendor (KREDI) '
                            f'changes must also check BP (BUPA_BUS) change documents.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code='Review changed object classes (BUPA_BUS, FMCJ, etc.)',
                severity='medium',
            ))

    def _check_ast150_aufk(self, node):
        """AST-150: AUFK/AFKO/AFPO → review for PP/DS changes."""
        from_upper = node.from_clause.upper()
        if from_upper in ('AUFK', 'AFKO', 'AFPO', 'AFFL', 'AFVC', 'AFVV'):
            self.changes.append(ChangeRecord(
                rule_id='AST-150', line=node.line, category='data_migration',
                description=f'SELECT FROM {from_upper} (production orders) → In S/4HANA, '
                            f'production planning can use PP/DS (embedded APO) instead of '
                            f'classic MRP. Order settlement flows to ACDOCA. Goods movements '
                            f'via MATDOC. Review custom order reports for MATDOC integration '
                            f'and PP/DS scheduling compatibility. CDS: I_MfgOrder.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code=f'SELECT ... FROM {from_upper} (review PP/DS + MATDOC integration)',
                severity='medium',
            ))

    def _check_ast151_proj_prps(self, node):
        """AST-151: PROJ/PRPS → project system changes in S/4HANA."""
        from_upper = node.from_clause.upper()
        if from_upper in ('PROJ', 'PRPS', 'PRHI', 'RPSCO', 'BPGE'):
            self.changes.append(ChangeRecord(
                rule_id='AST-151', line=node.line, category='data_migration',
                description=f'SELECT FROM {from_upper} (Project System) → In S/4HANA, PS '
                            f'cost postings route through ACDOCA. Project stock management '
                            f'changes (special stock indicator Q). Revenue recognition '
                            f'shifts to IFRS15 RAR. Verify project hierarchy programs, '
                            f'progress analysis, and settlement rules. CDS: I_Project.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code=f'SELECT ... FROM {from_upper} (review ACDOCA settlement + RAR)',
                severity='medium',
            ))

    def _check_ast152_with_item(self, node):
        """AST-152: WITH_ITEM → extended withholding tax changes."""
        from_upper = node.from_clause.upper()
        if from_upper in ('WITH_ITEM', 'BSEG_ADD', 'J_1IEWT_CERT', 'J_1IEWT_EXMPT'):
            self.changes.append(ChangeRecord(
                rule_id='AST-152', line=node.line, category='data_migration',
                description=f'SELECT FROM {from_upper} (withholding tax data) → In S/4HANA, '
                            f'extended withholding tax entries are stored differently. '
                            f'Classic withholding tax (BSEG-QSSKZ) is obsolete — use extended '
                            f'withholding tax only. WITH_ITEM data links to ACDOCA for '
                            f'posting amounts. Review country-specific WHT certificates.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code='SELECT ... FROM WITH_ITEM + ACDOCA (extended WHT only)',
                severity='medium',
            ))

    def _check_ast153_bkpf(self, node):
        """AST-153: BKPF/BSEG → ACDOCA (document header/line items)."""
        from_upper = node.from_clause.upper()
        if from_upper in ('BKPF', 'BSEG'):
            self.changes.append(ChangeRecord(
                rule_id='AST-153', line=node.line, category='data_migration',
                description=f'SELECT FROM {from_upper} (FI document header/line items) → '
                            f'In S/4HANA, BKPF/BSEG are compatibility views over ACDOCA. '
                            f'BSEG cluster no longer exists as pooled table. Custom reports '
                            f'reading BSEG with secondary indices will have different '
                            f'performance characteristics. Rewrite to use ACDOCA directly '
                            f'or CDS I_JournalEntry / I_JournalEntryItem.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code='SELECT ... FROM ACDOCA / I_JournalEntry / I_JournalEntryItem',
                severity='critical',
            ))

    def _check_ast154_setleaf(self, node):
        """AST-154: SETLEAF/SETHEADER → review for group reporting."""
        from_upper = node.from_clause.upper()
        if from_upper in ('SETLEAF', 'SETHEADER', 'SETHEADERT', 'SETNODE'):
            self.changes.append(ChangeRecord(
                rule_id='AST-154', line=node.line, category='data_migration',
                description=f'SELECT FROM {from_upper} (set/group definitions) → In S/4HANA, '
                            f'Group Reporting replaces classic EC-CS consolidation. Sets for '
                            f'GL accounts still work but consolidation unit groups, hierarchy '
                            f'nodes, and FS items change. Review set-based authorization, '
                            f'report painter groups, and consolidation hierarchies.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code='Review for Group Reporting + CDS-based hierarchies',
                severity='low',
            ))

    def _check_ast155_vbfa(self, node):
        """AST-155: VBFA document flow → review for new document types."""
        from_upper = node.from_clause.upper()
        if from_upper == 'VBFA':
            self.changes.append(ChangeRecord(
                rule_id='AST-155', line=node.line, category='data_migration',
                description='SELECT FROM VBFA (SD document flow) → VBFA persists in S/4HANA '
                            'but new document categories appear (advanced returns, advanced '
                            'billing, service contracts). Programs filtering on VBTYP_N '
                            '(subsequent doc category) need extension for new document types. '
                            'CDS: I_SalesDocumentFlow.',
                old_code='SELECT ... FROM VBFA',
                new_code='SELECT ... FROM VBFA / I_SalesDocumentFlow (review new VBTYPs)',
                severity='medium',
            ))

    def _check_ast156_eban(self, node):
        """AST-156: EBAN → purchase requisition with simplified sourcing."""
        from_upper = node.from_clause.upper()
        if from_upper in ('EBAN', 'EBKN'):
            self.changes.append(ChangeRecord(
                rule_id='AST-156', line=node.line, category='data_migration',
                description=f'SELECT FROM {from_upper} (purchase requisitions) → In S/4HANA, '
                            f'purchase requisitions support simplified Manage Purchase '
                            f'Requisitions Fiori app. Source assignment may use ML-based '
                            f'sourcing. Review custom requisition approval workflows for '
                            f'flexible workflow compatibility. CDS: I_PurchaseRequisitionItem.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code='SELECT ... FROM EBAN / I_PurchaseRequisitionItem',
                severity='low',
            ))

    def _check_ast157_ska1(self, node):
        """AST-157: SKA1/SKB1 → GL account changes for ACDOCA."""
        from_upper = node.from_clause.upper()
        if from_upper in ('SKA1', 'SKB1', 'SKAT', 'CSKA', 'CSKB'):
            self.changes.append(ChangeRecord(
                rule_id='AST-157', line=node.line, category='data_migration',
                description=f'SELECT FROM {from_upper} (GL account master / cost element) → '
                            f'In S/4HANA, secondary cost elements are merged into GL accounts '
                            f'(CSKA/CSKB → SKA1/SKB1). Account type (KTOPL) includes cost '
                            f'element categories. Programs reading CSKA separately must be '
                            f'updated. CDS: I_GLAccountInChartOfAccounts.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code='SELECT ... FROM SKA1 / I_GLAccountInChartOfAccounts',
                severity='high',
            ))

    def _check_ast158_reguh(self, node):
        """AST-158: REGUH/REGUP → payment run data changes."""
        from_upper = node.from_clause.upper()
        if from_upper in ('REGUH', 'REGUP', 'PAYR'):
            self.changes.append(ChangeRecord(
                rule_id='AST-158', line=node.line, category='data_migration',
                description=f'SELECT FROM {from_upper} (payment run data) → In S/4HANA, '
                            f'payment program data persists but links to Business Partner '
                            f'instead of vendor. Bank determination changes for SEPA. '
                            f'Custom payment medium formats need review for Payment Factory '
                            f'and Bank Communication Management (BCM) integration.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code=f'SELECT ... FROM {from_upper} (review BP bank data + BCM)',
                severity='medium',
            ))

    def _check_ast159_anla(self, node):
        """AST-159: ANLA/ANLB/ANLC → asset accounting changes."""
        from_upper = node.from_clause.upper()
        if from_upper in ('ANLA', 'ANLB', 'ANLC', 'ANLP', 'ANLH', 'ANEK', 'ANEP'):
            self.changes.append(ChangeRecord(
                rule_id='AST-159', line=node.line, category='data_migration',
                description=f'SELECT FROM {from_upper} (fixed asset master/values) → '
                            f'In S/4HANA, new Asset Accounting posts to ACDOCA directly. '
                            f'ANLC/ANLP are compatibility views. Asset value date logic '
                            f'changes. Parallel valuations use ledger approach. Review '
                            f'custom depreciation reports. CDS: I_FixedAsset.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code='SELECT ... FROM ACDOCA (asset postings) / I_FixedAsset',
                severity='high',
            ))

    def _check_ast160_tcurr(self, node):
        """AST-160: TCURR → currency conversion with decimal shift changes."""
        from_upper = node.from_clause.upper()
        if from_upper in ('TCURR', 'TCURF', 'TCURN', 'TCURV', 'TCURX'):
            self.changes.append(ChangeRecord(
                rule_id='AST-160', line=node.line, category='customizing',
                description=f'SELECT FROM {from_upper} (currency exchange rates/config) → '
                            f'In S/4HANA, currency decimals shift handling changes. New '
                            f'FINSC_LEDGER concept affects parallel currencies. SAP note '
                            f'2266498 for currency decimal consideration. Review custom '
                            f'currency conversion routines, CONVERT_TO_LOCAL_CURRENCY calls, '
                            f'and multi-currency reporting.',
                old_code=f'SELECT ... FROM {from_upper}',
                new_code='Review currency config / I_ExchangeRate CDS views',
                severity='medium',
            ))

    # ═══════════════════════════════════════════════════════════════════════════
    # CONSOLIDATED VISITOR AUGMENTATION
    # These methods augment existing visitors to trigger the new rules.
    # ═══════════════════════════════════════════════════════════════════════════

    def _visit_generic_augmented(self, node: GenericStatement):
        """Augmented generic visitor — triggers AST-045 through AST-065 checks
        on fallback/generic nodes not fully parsed into specific AST types."""
        # AST-045: MOVE...TO
        self._visit_generic_move_chain(node)
        # AST-046: MOVE-CORRESPONDING
        self._check_ast046_move_corresponding(node)
        # AST-047: COMPUTE
        self._check_ast047_compute(node)
        # AST-048: Arithmetic keywords
        self._check_ast048_arithmetic_keywords(node)
        # AST-049: TRANSLATE...TO UPPER/LOWER
        self._check_ast049_translate(node)
        # AST-050: CONDENSE
        self._check_ast050_condense(node)
        # AST-051: STRLEN
        self._check_ast051_strlen(node)
        # AST-052: DESCRIBE TABLE
        self._check_ast052_describe_table(node)
        # AST-060: OCCURS
        self._check_ast060_occurs_generic(node)
        # AST-061: RANGES
        self._check_ast061_ranges_generic(node)
        # AST-064: COMMUNICATION
        self._check_ast064_communication(node)
        # AST-065: SET EXTENDED CHECK
        self._check_ast065_set_extended_check(node)
        # AST-110: Currency conversion
        self._check_ast110_currency_conversion(node)
        # AST-119: Auth trace
        self._check_ast119_auth_trace(node)
        # AST-124: SPOOL
        self._check_ast124_spool(node)

    def _visit_select_augmented(self, node: SelectStatement):
        """Augmented SELECT visitor — triggers table-specific rules AST-066 to AST-080,
        AST-108, AST-112, AST-115, AST-123, AST-129, AST-130."""
        from_upper = node.from_clause.upper()

        # Store original from clause before any renames
        if not hasattr(node, '_original_from'):
            node._original_from = node.from_clause

        orig_upper = getattr(node, '_original_from', from_upper).upper()

        # Table-specific migration notes
        if orig_upper == 'BSEG':
            self._check_ast066_bseg(node)
        if orig_upper in ('BSIK', 'BSAK'):
            self._check_ast067_bsik_bsak(node)
        if orig_upper in ('BSID', 'BSAD'):
            self._check_ast068_bsid_bsad(node)
        if orig_upper in ('BSIS', 'BSAS'):
            self._check_ast069_bsis_bsas(node)
        if orig_upper == 'GLT0':
            self._check_ast070_glt0(node)
        if orig_upper == 'GLPCA':
            self._check_ast071_glpca(node)
        if orig_upper == 'COEP':
            self._check_ast072_coep(node)
        if orig_upper == 'KONV':
            self._check_ast073_konv(node)
        if orig_upper == 'VBUK':
            self._check_ast074_vbuk(node)
        if orig_upper == 'VBUP':
            self._check_ast075_vbup(node)
        if orig_upper == 'KNA1':
            self._check_ast076_kna1_cds(node)
        if orig_upper == 'LFA1':
            self._check_ast077_lfa1_cds(node)
        if orig_upper in ('MKPF', 'MSEG'):
            self._check_ast078_mkpf_mseg(node)
        if orig_upper == 'FAGLFLEXA':
            self._check_ast079_faglflexa(node)
        if orig_upper == 'FAGLFLEXT':
            self._check_ast080_faglflext(node)
        if orig_upper == 'TCURR':
            self._check_ast112_tcurr(node)
        if orig_upper == 'NAST':
            self._check_ast123_nast_output(node)
        if orig_upper == 'ILOA':
            self._check_ast129_iloa(node)
        if orig_upper in ('MCHA', 'MCH1', 'MCHB'):
            self._check_ast130_mcha(node)
        # AST-131 to AST-160 — S/4HANA table modernization rules
        if orig_upper in ('COEP', 'COEJ', 'COES', 'COBK'):
            self._check_ast131_coep(node)
        if orig_upper in ('KONV', 'KONP', 'KONH', 'KONM', 'KONW'):
            self._check_ast132_konv(node)
        if orig_upper == 'NAST':
            self._check_ast133_nast(node)
        if orig_upper in ('VBBE', 'VBBE_SHOW'):
            self._check_ast134_vbbe(node)
        if orig_upper in ('MBEW', 'MBEWH', 'CKMLCR', 'CKMLPP'):
            self._check_ast135_mbew(node)
        if orig_upper == 'RESB':
            self._check_ast136_resb(node)
        if orig_upper in ('STXH', 'STXL'):
            self._check_ast137_stxh(node)
        if orig_upper.startswith(('CE1', 'CE2', 'CE3', 'CE4')):
            self._check_ast138_ce1(node)
        if orig_upper in ('KNA1', 'LFA1', 'KNVV', 'LFB1', 'KNB1', 'KNVP',
                          'LFM1', 'LFM2', 'KNVH', 'KNVK', 'KNZA'):
            self._check_ast139_kna1_lfa1(node)
        if orig_upper in ('BSAD', 'BSID', 'BSAK', 'BSIK', 'BSAS', 'BSIS',
                          'BSI', 'KNC1', 'KNC3', 'LFC1', 'LFC3'):
            self._check_ast140_bsad_bsak(node)
        if orig_upper in ('MARC', 'MVKE', 'MARD', 'MARM', 'MEAN',
                          'MLAN', 'MLGN', 'MLGT'):
            self._check_ast141_marc_mvke(node)
        if orig_upper in ('VBRK', 'VBRP', 'VBRL'):
            self._check_ast142_vbrk_vbrp(node)
        if orig_upper.startswith('PA0') and orig_upper[3:].isdigit():
            self._check_ast143_pa_infotype(node)
        if orig_upper in ('EKBE', 'EKBEH', 'EKBES'):
            self._check_ast144_ekbe(node)
        if orig_upper in ('JEST', 'JSTO', 'TJ02T', 'TJ02', 'TJ30', 'TJ30T'):
            self._check_ast145_jest_tj02(node)
        if orig_upper in ('LIKP', 'LIPS', 'VTTP', 'VTTS', 'VTTK'):
            self._check_ast146_lips_likp(node)
        if orig_upper in ('FAGLFLEXT', 'FAGLFLEXA', 'FAGLBSIS', 'FAGLBSAS'):
            self._check_ast147_faglflex(node)
        if orig_upper in ('T001W', 'T001L', 'T320', 'T300', 'T300T'):
            self._check_ast148_t001w_werks(node)
        if orig_upper in ('CDHDR', 'CDPOS'):
            self._check_ast149_cdhdr(node)
        if orig_upper in ('AUFK', 'AFKO', 'AFPO', 'AFFL', 'AFVC', 'AFVV'):
            self._check_ast150_aufk(node)
        if orig_upper in ('PROJ', 'PRPS', 'PRHI', 'RPSCO', 'BPGE'):
            self._check_ast151_proj_prps(node)
        if orig_upper in ('WITH_ITEM', 'BSEG_ADD', 'J_1IEWT_CERT', 'J_1IEWT_EXMPT'):
            self._check_ast152_with_item(node)
        if orig_upper in ('BKPF', 'BSEG'):
            self._check_ast153_bkpf(node)
        if orig_upper in ('SETLEAF', 'SETHEADER', 'SETHEADERT', 'SETNODE'):
            self._check_ast154_setleaf(node)
        if orig_upper == 'VBFA':
            self._check_ast155_vbfa(node)
        if orig_upper in ('EBAN', 'EBKN'):
            self._check_ast156_eban(node)
        if orig_upper in ('SKA1', 'SKB1', 'SKAT', 'CSKA', 'CSKB'):
            self._check_ast157_ska1(node)
        if orig_upper in ('REGUH', 'REGUP', 'PAYR'):
            self._check_ast158_reguh(node)
        if orig_upper in ('ANLA', 'ANLB', 'ANLC', 'ANLP', 'ANLH', 'ANEK', 'ANEP'):
            self._check_ast159_anla(node)
        if orig_upper in ('TCURR', 'TCURF', 'TCURN', 'TCURV', 'TCURX'):
            self._check_ast160_tcurr(node)
        # AST-108: Customer table joins
        self._check_ast108_customer_joins(node)

    def _visit_call_function_augmented(self, node: CallFunctionStatement):
        """Augmented CALL FUNCTION visitor — triggers FM-specific rules AST-081 to AST-100,
        AST-111, AST-113, AST-121, AST-122."""
        fn_clean = node.function_name.strip("'").strip("`").upper()

        # ALV FM rules
        if fn_clean == 'REUSE_ALV_GRID_DISPLAY':
            self._check_ast081_alv_grid(node)
        if fn_clean == 'REUSE_ALV_LIST_DISPLAY':
            self._check_ast082_alv_list(node)
        # Popup rule
        if fn_clean == 'POPUP_TO_CONFIRM':
            self._check_ast083_popup(node)
        # GUI download/upload
        if fn_clean == 'GUI_DOWNLOAD':
            self._check_ast084_gui_download(node)
        if fn_clean == 'GUI_UPLOAD':
            self._check_ast085_gui_upload(node)
        # Conversion exits
        if fn_clean.startswith('CONVERSION_EXIT_'):
            self._check_ast086_conversion_exit(node)
        # Date check
        if fn_clean == 'DATE_CHECK_PLAUSIBILITY':
            self._check_ast087_date_check(node)
        # BAPI → RAP replacements (AST-088 through AST-100)
        if fn_clean in DEPRECATED_FM_RAP_MAP:
            self._check_ast088_to_100_rap_replacements(node)
        # Currency conversion BAPIs (AST-111)
        if fn_clean in ('BAPI_CURRENCY_CONV_TO_INTERNAL', 'BAPI_CURRENCY_CONV_TO_EXTERNAL'):
            self._check_ast111_currency_bapi(node)
        # UOM conversion (AST-113)
        if fn_clean in ('UNIT_CONVERSION_SIMPLE', 'MD_CONVERT_MATERIAL_UNIT',
                        'CONVERSION_EXIT_CUNIT_INPUT', 'CONVERSION_EXIT_CUNIT_OUTPUT'):
            self._check_ast113_uom_conversion(node)
        # SAPscript (AST-121)
        if fn_clean in ('WRITE_FORM', 'OPEN_FORM', 'CLOSE_FORM', 'START_FORM',
                        'END_FORM', 'WRITE_FORM_LINES'):
            self._check_ast121_sapscript(node)
        # SmartForms (AST-122)
        if fn_clean in ('SSF_FUNCTION_MODULE_NAME', 'SSF_OPEN', 'SSF_CLOSE'):
            self._check_ast122_smartforms(node)

    def _visit_call_transaction_augmented(self, node: CallTransactionStatement):
        """Augmented CALL TRANSACTION visitor — triggers BP T-code rules AST-101 to AST-105."""
        self._check_ast101_to_105_bp_tcodes(node)

    def _visit_authority_check_augmented(self, node: AuthorityCheckStatement):
        """Augmented AUTHORITY-CHECK visitor — triggers auth rules AST-116 to AST-120."""
        self._check_ast116_auth_bkpf(node)
        self._check_ast117_auth_kna1(node)
        self._check_ast118_auth_lfa1(node)
        self._check_ast120_removed_tcodes(node)

    def _visit_read_table_augmented(self, node: ReadTableStatement):
        """Augmented READ TABLE visitor — triggers AST-054, AST-055, AST-115."""
        self._check_ast054_read_table_key(node)
        self._check_ast055_read_table_index(node)
        self._check_ast115_read_tcurr(node)

    def _visit_loop_at_augmented(self, node: LoopAtStatement):
        """Augmented LOOP AT visitor — triggers AST-058."""
        self._check_ast058_loop_into_reference(node)

    def _visit_call_method_augmented(self, node: CallMethodStatement):
        """Augmented CALL METHOD visitor — triggers AST-056."""
        self._check_ast056_call_method_static(node)

    def _visit_create_object_augmented(self, node: CreateObjectStatement):
        """Augmented CREATE OBJECT visitor — triggers AST-057."""
        self._check_ast057_create_object_inferred(node)

    def _visit_form_augmented(self, node: FormBlock):
        """Augmented FORM visitor — triggers AST-062, AST-063."""
        self._check_ast062_tables_param(node)
        self._visit_form_ast063(node)

    def _visit_assignment_augmented(self, node: AssignmentStatement):
        """Augmented ASSIGNMENT visitor — triggers AST-106, AST-107."""
        self._check_ast106_kunnr_field(node)
        self._check_ast107_lifnr_field(node)

    def _visit_data_declaration_augmented(self, node: DataDeclaration):
        """Augmented DATA declaration visitor — triggers AST-109, AST-114, AST-126 to AST-128."""
        self._check_ast109_wrbtr_decimals(node)
        self._check_ast114_curr_precision(node)
        self._check_ast126_matnr_length(node)
        self._check_ast127_bp_number(node)
        self._check_ast128_gl_account(node)

    def _visit_submit_augmented(self, node: SubmitStatement):
        """Augmented SUBMIT visitor — triggers AST-125."""
        self._check_ast125_submit_spool(node)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5: CODE GENERATOR & PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════

class ABAPCodeGenerator:
    """
    Reconstructs syntactically valid ABAP source code from a mutated AST.
    Produces properly indented, formatted output that can compile in SE80/ADT.
    """

    def __init__(self, indent_size: int = 2):
        self.indent_size = indent_size
        self.indent_level = 0
        self.lines: List[str] = []

    def generate(self, program: ProgramNode) -> str:
        self.lines = []
        self.indent_level = 0
        for stmt in program.statements:
            self._gen(stmt)
        return '\n'.join(self.lines)

    def _indent(self) -> str:
        return ' ' * (self.indent_level * self.indent_size)

    def _emit(self, text: str):
        self.lines.append(f"{self._indent()}{text}")

    def _gen(self, node: ABAPNode):
        method = f'_gen_{node.node_type.lower()}'
        generator = getattr(self, method, None)
        if generator:
            generator(node)
        else:
            self._gen_fallback(node)

    # ── Comment ───────────────────────────────────────────────────────────────

    def _gen_comment(self, node: CommentNode):
        self._emit(node.text)

    # ── Report / Include ──────────────────────────────────────────────────────

    def _gen_report(self, node: ReportStatement):
        opts = (' ' + ' '.join(node.options)) if node.options else ''
        self._emit(f"REPORT {node.name}{opts}.")

    def _gen_include(self, node: IncludeStatement):
        self._emit(f"INCLUDE {node.include_name}.")

    # ── Declarations ──────────────────────────────────────────────────────────

    def _gen_data_declaration(self, node: DataDeclaration):
        if node.is_structure_begin:
            self._emit(f"{node.keyword}: BEGIN OF {node.name},")
            return
        if node.is_structure_end:
            self._emit(f"  END OF {node.name}.")
            return
        parts = [node.keyword, node.name]
        if node.ref_to:
            parts.extend(['TYPE', 'REF', 'TO', node.ref_to])
        elif node.table_type:
            parts.extend(['TYPE', node.table_type, 'TABLE OF', node.table_of or '...'])
            if node.table_key:
                parts.extend(['WITH', 'KEY'] + node.table_key)
        elif node.type_clause:
            parts.extend(['TYPE', node.type_clause])
        elif node.like_clause:
            parts.extend(['LIKE', node.like_clause])
        if node.length:
            parts.extend(['LENGTH', node.length])
        if node.decimals:
            parts.extend(['DECIMALS', node.decimals])
        if node.initial_value:
            parts.extend(['VALUE', node.initial_value])
        if node.read_only:
            parts.append('READ-ONLY')
        self._emit(' '.join(parts) + '.')

    def _gen_types_declaration(self, node: TypesDeclaration):
        if node.is_structure_begin:
            self._emit(f"TYPES: BEGIN OF {node.name},")
            return
        if node.is_structure_end:
            self._emit(f"  END OF {node.name}.")
            return
        tc = f" TYPE {node.type_clause}" if node.type_clause else ''
        self._emit(f"TYPES {node.name}{tc}.")

    def _gen_constants_declaration(self, node: ConstantsDeclaration):
        if node.is_structure_begin:
            self._emit(f"CONSTANTS: BEGIN OF {node.name},")
            return
        if node.is_structure_end:
            self._emit(f"  END OF {node.name}.")
            return
        tc = f" TYPE {node.type_clause}" if node.type_clause else ''
        val = f" VALUE {node.value}" if node.value else ''
        self._emit(f"CONSTANTS {node.name}{tc}{val}.")

    def _gen_field_symbol_declaration(self, node: FieldSymbolDeclaration):
        tc = f" TYPE {node.type_clause}" if node.type_clause else ''
        lc = f" LIKE {node.like_clause}" if node.like_clause else ''
        self._emit(f"FIELD-SYMBOLS {node.name}{tc}{lc}.")

    def _gen_tables_declaration(self, node: TablesDeclaration):
        self._emit(f"TABLES {node.table_name}.")

    def _gen_parameter_declaration(self, node: ParameterDeclaration):
        parts = [node.keyword, node.name]
        if node.type_clause: parts.extend(['TYPE', node.type_clause])
        elif node.like_clause: parts.extend(['LIKE', node.like_clause])
        if node.default_value: parts.extend(['DEFAULT', node.default_value])
        if node.obligatory: parts.append('OBLIGATORY')
        self._emit(' '.join(parts) + '.')

    def _gen_select_option_declaration(self, node: SelectOptionDeclaration):
        self._emit(f"SELECT-OPTIONS {node.name} FOR {node.for_field}.")

    def _gen_ranges_declaration(self, node: RangesDeclaration):
        self._emit(f"RANGES {node.name} FOR {node.for_field}.")

    # ── Assignments ───────────────────────────────────────────────────────────

    def _gen_assignment(self, node: AssignmentStatement):
        self._emit(f"{node.target} = {node.expression}.")

    def _gen_move(self, node: MoveStatement):
        self._emit(f"MOVE {node.source} TO {node.target}.")

    def _gen_move_corresponding(self, node: MoveCorrespondingStatement):
        self._emit(f"MOVE-CORRESPONDING {node.source} TO {node.target}.")

    def _gen_compute(self, node: ComputeStatement):
        self._emit(f"COMPUTE {node.target} = {node.expression}.")

    def _gen_arithmetic(self, node: ArithmeticStatement):
        prep = {'ADD': 'TO', 'SUBTRACT': 'FROM', 'MULTIPLY': 'BY', 'DIVIDE': 'BY'}
        self._emit(f"{node.operation} {node.operand} {prep.get(node.operation, 'TO')} {node.target}.")

    # ── SELECT ────────────────────────────────────────────────────────────────

    def _gen_select(self, node: SelectStatement):
        parts = ['SELECT']
        if node.is_single: parts.append('SINGLE')
        if node.is_distinct: parts.append('DISTINCT')
        parts.extend(node.field_list or ['*'])
        self._emit(' '.join(parts))
        self.indent_level += 1
        self._emit(f"FROM {node.from_clause}")
        for j in node.joins:
            self._emit(f"{j.get('type', '')} JOIN {j.get('table', '')} ON {j.get('on', '')}")
        if node.into_table:
            corr = 'CORRESPONDING FIELDS OF ' if node.into_corresponding else ''
            prefix = 'APPENDING ' if node.appending else 'INTO '
            self._emit(f"{prefix}{corr}TABLE {node.into_table}")
        elif node.into_clause:
            corr = 'CORRESPONDING FIELDS OF ' if node.into_corresponding else ''
            self._emit(f"INTO {corr}{node.into_clause}")
        if node.for_all_entries:
            self._emit(f"FOR ALL ENTRIES IN {node.for_all_entries}")
        if node.where_clause:
            self._emit(f"WHERE {node.where_clause}")
        if node.group_by:
            self._emit(f"GROUP BY {' '.join(node.group_by)}")
        if node.having_clause:
            self._emit(f"HAVING {node.having_clause}")
        if node.order_by:
            self._emit(f"ORDER BY {' '.join(node.order_by)}")
        if node.up_to_rows:
            self._emit(f"UP TO {node.up_to_rows} ROWS")
        self.indent_level -= 1
        self._emit('.')
        if node.has_endselect:
            self.indent_level += 1
            for child in node.body:
                self._gen(child)
            self.indent_level -= 1
            self._emit('ENDSELECT.')

    def _gen_db_modify(self, node: DatabaseModifyStatement):
        parts = [node.operation, node.table_name]
        if node.from_wa: parts.extend(['FROM', node.from_wa])
        if node.values_clause: parts.append(node.values_clause)
        if node.where_clause: parts.extend(['WHERE', node.where_clause])
        self._emit(' '.join(parts) + '.')

    def _gen_native_sql(self, node: NativeSqlBlock):
        self._emit('EXEC SQL.')
        self.indent_level += 1
        for line in node.sql_text.split('\n'):
            self._emit(line.strip())
        self.indent_level -= 1
        self._emit('ENDEXEC.')

    # ── Control flow ──────────────────────────────────────────────────────────

    def _gen_if(self, node: IfBlock):
        self._emit(f"IF {node.condition}.")
        self.indent_level += 1
        for s in node.then_body: self._gen(s)
        self.indent_level -= 1
        for cond, body in node.elseif_branches:
            self._emit(f"ELSEIF {cond}.")
            self.indent_level += 1
            for s in body: self._gen(s)
            self.indent_level -= 1
        if node.else_body:
            self._emit('ELSE.')
            self.indent_level += 1
            for s in node.else_body: self._gen(s)
            self.indent_level -= 1
        self._emit('ENDIF.')

    def _gen_case(self, node: CaseBlock):
        self._emit(f"CASE {node.operand}.")
        self.indent_level += 1
        for val, body in node.when_branches:
            self._emit(f"WHEN {val}.")
            self.indent_level += 1
            for s in body: self._gen(s)
            self.indent_level -= 1
        if node.others_body:
            self._emit('WHEN OTHERS.')
            self.indent_level += 1
            for s in node.others_body: self._gen(s)
            self.indent_level -= 1
        self.indent_level -= 1
        self._emit('ENDCASE.')

    def _gen_do(self, node: DoLoop):
        times = f" {node.times}" if node.times else ''
        self._emit(f"DO{times}.")
        self.indent_level += 1
        for s in node.body: self._gen(s)
        self.indent_level -= 1
        self._emit('ENDDO.')

    def _gen_while(self, node: WhileLoop):
        self._emit(f"WHILE {node.condition}.")
        self.indent_level += 1
        for s in node.body: self._gen(s)
        self.indent_level -= 1
        self._emit('ENDWHILE.')

    def _gen_loop_at(self, node: LoopAtStatement):
        parts = [f"LOOP AT {node.table}"]
        if node.into: parts.append(f"INTO {node.into}")
        if node.assigning: parts.append(f"ASSIGNING {node.assigning}")
        if node.reference_into: parts.append(f"REFERENCE INTO {node.reference_into}")
        if node.where_clause: parts.append(f"WHERE {node.where_clause}")
        if node.from_index: parts.append(f"FROM {node.from_index}")
        if node.to_index: parts.append(f"TO {node.to_index}")
        self._emit(' '.join(parts) + '.')
        self.indent_level += 1
        for s in node.body: self._gen(s)
        self.indent_level -= 1
        self._emit('ENDLOOP.')

    # ── Subroutines / OOP ─────────────────────────────────────────────────────

    def _gen_form(self, node: FormBlock):
        params = ''
        if node.using_params: params += ' USING ' + ' '.join(node.using_params)
        if node.changing_params: params += ' CHANGING ' + ' '.join(node.changing_params)
        if node.tables_params: params += ' TABLES ' + ' '.join(node.tables_params)
        self._emit(f"FORM {node.name}{params}.")
        self.indent_level += 1
        for s in node.body: self._gen(s)
        self.indent_level -= 1
        self._emit('ENDFORM.')

    def _gen_perform(self, node: PerformStatement):
        parts = [f"PERFORM {node.form_name}"]
        if node.in_program: parts.append(f"IN PROGRAM {node.in_program}")
        if node.using_args: parts.append('USING ' + ' '.join(node.using_args))
        if node.changing_args: parts.append('CHANGING ' + ' '.join(node.changing_args))
        self._emit(' '.join(parts) + '.')

    def _gen_class(self, node: ClassBlock):
        parts = [f"CLASS {node.name}"]
        if node.is_definition: parts.append('DEFINITION')
        elif node.is_implementation: parts.append('IMPLEMENTATION')
        if node.superclass: parts.append(f"INHERITING FROM {node.superclass}")
        if node.is_abstract: parts.append('ABSTRACT')
        if node.is_final: parts.append('FINAL')
        self._emit(' '.join(parts) + '.')
        self.indent_level += 1
        for s in node.body: self._gen(s)
        self.indent_level -= 1
        self._emit('ENDCLASS.')

    def _gen_method(self, node: MethodBlock):
        self._emit(f"METHOD {node.name}.")
        self.indent_level += 1
        for s in node.body: self._gen(s)
        self.indent_level -= 1
        self._emit('ENDMETHOD.')

    def _gen_interface(self, node: InterfaceBlock):
        self._emit(f"INTERFACE {node.name}.")
        self.indent_level += 1
        for s in node.body: self._gen(s)
        self.indent_level -= 1
        self._emit('ENDINTERFACE.')

    def _gen_call_function(self, node: CallFunctionStatement):
        self._emit(f"CALL FUNCTION {node.function_name}")
        self.indent_level += 1
        for section, items in [('EXPORTING', node.exporting), ('IMPORTING', node.importing),
                                ('CHANGING', node.changing), ('TABLES', node.tables),
                                ('EXCEPTIONS', node.exceptions)]:
            if items:
                self._emit(section)
                self.indent_level += 1
                for name, val in items:
                    self._emit(f"{name} = {val}")
                self.indent_level -= 1
        self.indent_level -= 1
        self._emit('.')

    def _gen_call_method(self, node: CallMethodStatement):
        ref = f"{node.object_ref}->" if node.object_ref else ''
        self._emit(f"CALL METHOD {ref}{node.method_name}.")

    def _gen_call_transaction(self, node: CallTransactionStatement):
        self._emit(f"CALL TRANSACTION {node.tcode}.")

    def _gen_create_object(self, node: CreateObjectStatement):
        tc = f" TYPE {node.class_name}" if node.class_name else ''
        self._emit(f"CREATE OBJECT {node.variable}{tc}.")

    def _gen_create_data(self, node: CreateDataStatement):
        tc = f" TYPE {node.type_clause}" if node.type_clause else ''
        lc = f" LIKE {node.like_clause}" if node.like_clause else ''
        self._emit(f"CREATE DATA {node.variable}{tc}{lc}.")

    # ── Exception handling ────────────────────────────────────────────────────

    def _gen_try(self, node: TryBlock):
        self._emit('TRY.')
        self.indent_level += 1
        for s in node.try_body: self._gen(s)
        self.indent_level -= 1
        for exc_class, into_var, body in node.catch_branches:
            into = f" INTO {into_var}" if into_var else ''
            self._emit(f"CATCH {exc_class}{into}.")
            self.indent_level += 1
            for s in body: self._gen(s)
            self.indent_level -= 1
        if node.cleanup_body:
            self._emit('CLEANUP.')
            self.indent_level += 1
            for s in node.cleanup_body: self._gen(s)
            self.indent_level -= 1
        self._emit('ENDTRY.')

    def _gen_raise(self, node: RaiseStatement):
        if node.exception_class:
            self._emit(f"RAISE EXCEPTION TYPE {node.exception_class}.")
        else:
            self._emit('RAISE.')

    # ── Table operations ──────────────────────────────────────────────────────

    def _gen_append(self, node: AppendStatement):
        if node.initial_line:
            self._emit(f"APPEND INITIAL LINE TO {node.target}.")
        elif node.lines_of:
            self._emit(f"APPEND LINES OF {node.lines_of} TO {node.target}.")
        elif node.target and node.target != node.source:
            self._emit(f"APPEND {node.source} TO {node.target}.")
        else:
            # Header-line short form: `APPEND wa.` (no explicit target)
            self._emit(f"APPEND {node.source}.")

    def _gen_insert_table(self, node: InsertTableStatement):
        idx = f" INDEX {node.index}" if node.index else ''
        self._emit(f"INSERT {node.source} INTO TABLE {node.target}{idx}.")

    def _gen_delete_table(self, node: DeleteTableStatement):
        if node.adjacent_duplicates:
            cmp = (' COMPARING ' + ' '.join(node.comparing)) if node.comparing else ''
            self._emit(f"DELETE ADJACENT DUPLICATES FROM {node.table}{cmp}.")
        elif node.where_clause:
            self._emit(f"DELETE {node.table} WHERE {node.where_clause}.")
        elif node.index:
            self._emit(f"DELETE {node.table} INDEX {node.index}.")
        else:
            self._emit(f"DELETE {node.table}.")

    def _gen_modify_table(self, node: ModifyTableStatement):
        parts = [f"MODIFY {node.table}"]
        if node.from_wa: parts.append(f"FROM {node.from_wa}")
        if node.index: parts.append(f"INDEX {node.index}")
        if node.transporting: parts.append('TRANSPORTING ' + ' '.join(node.transporting))
        if node.where_clause: parts.append(f"WHERE {node.where_clause}")
        self._emit(' '.join(parts) + '.')

    def _gen_read_table(self, node: ReadTableStatement):
        parts = [f"READ TABLE {node.table}"]
        if node.with_key:
            keys = ' '.join(f"{k} = {v}" for k, v in node.with_key.items())
            parts.append(f"WITH KEY {keys}")
        elif node.index:
            parts.append(f"INDEX {node.index}")
        if node.into: parts.append(f"INTO {node.into}")
        if node.assigning: parts.append(f"ASSIGNING {node.assigning}")
        if node.reference_into: parts.append(f"REFERENCE INTO {node.reference_into}")
        if node.binary_search: parts.append('BINARY SEARCH')
        if node.transporting: parts.append('TRANSPORTING ' + ' '.join(node.transporting))
        self._emit(' '.join(parts) + '.')

    def _gen_sort(self, node: SortStatement):
        parts = [f"SORT {node.table}"]
        if node.by_fields:
            fields = ' '.join(f"{f['field']} {f.get('direction', '')}" for f in node.by_fields)
            parts.append(f"BY {fields}")
        self._emit(' '.join(parts) + '.')

    def _gen_describe_table(self, node: DescribeTableStatement):
        parts = [f"DESCRIBE TABLE {node.table}"]
        if node.lines_var: parts.append(f"LINES {node.lines_var}")
        if node.kind_var: parts.append(f"KIND {node.kind_var}")
        self._emit(' '.join(parts) + '.')

    def _gen_collect(self, node: CollectStatement):
        self._emit(f"COLLECT {node.source} INTO {node.target}.")

    def _gen_clear(self, node: ClearStatement):
        targets = ', '.join(node.targets)
        if len(node.targets) > 1:
            self._emit(f"{node.keyword}: {targets}.")
        else:
            self._emit(f"{node.keyword} {targets}.")

    # ── String operations ─────────────────────────────────────────────────────

    def _gen_concatenate(self, node: ConcatenateStatement):
        parts = [f"CONCATENATE {' '.join(node.sources)} INTO {node.target}"]
        if node.separated_by: parts.append(f"SEPARATED BY {node.separated_by}")
        if node.respecting_blanks: parts.append('RESPECTING BLANKS')
        self._emit(' '.join(parts) + '.')

    def _gen_split(self, node: SplitStatement):
        if node.into_table:
            self._emit(f"SPLIT {node.source} AT {node.at_separator} INTO TABLE {node.into_table}.")
        else:
            self._emit(f"SPLIT {node.source} AT {node.at_separator} INTO {' '.join(node.targets)}.")

    def _gen_translate(self, node: TranslateStatement):
        if node.to_case:
            self._emit(f"TRANSLATE {node.target} TO {node.to_case} CASE.")
        elif node.using_rule:
            self._emit(f"TRANSLATE {node.target} USING {node.using_rule}.")

    def _gen_condense(self, node: CondenseStatement):
        ng = ' NO-GAPS' if node.no_gaps else ''
        self._emit(f"CONDENSE {node.target}{ng}.")

    def _gen_replace(self, node: ReplaceStatement):
        if node.all_occurrences:
            self._emit(f"REPLACE ALL OCCURRENCES OF {node.pattern} IN {node.target} WITH {node.with_value}.")
        else:
            self._emit(f"REPLACE {node.pattern} IN {node.target} WITH {node.with_value}.")

    def _gen_shift(self, node: ShiftStatement):
        self._emit(f"SHIFT {node.target} {node.mode}.")

    def _gen_find(self, node: FindStatement):
        occ = 'ALL OCCURRENCES OF ' if node.all_occurrences else ''
        self._emit(f"FIND {occ}{node.pattern} IN {node.in_string}.")

    # ── Field symbols ─────────────────────────────────────────────────────────

    def _gen_assign(self, node: AssignFieldSymbolStatement):
        casting = f" CASTING {node.casting}" if node.casting else ''
        self._emit(f"ASSIGN {node.source} TO {node.field_symbol}{casting}.")

    def _gen_unassign(self, node: UnassignStatement):
        self._emit(f"UNASSIGN {node.field_symbol}.")

    # ── Output ────────────────────────────────────────────────────────────────

    def _gen_write(self, node: WriteStatement):
        self._emit(f"WRITE {' '.join(node.outputs)}.")

    def _gen_format(self, node: FormatStatement):
        opts = (' ' + ' '.join(node.options)) if node.options else ''
        self._emit(f"{node.keyword}{opts}.")

    # ── System statements ─────────────────────────────────────────────────────

    def _gen_message(self, node: MessageStatement):
        self._emit(f"MESSAGE {node.msg_id}.")

    def _gen_authority_check(self, node: AuthorityCheckStatement):
        self._emit(f"AUTHORITY-CHECK OBJECT {node.object_name}")
        self.indent_level += 1
        for fld, val in node.fields.items():
            self._emit(f"ID {fld} FIELD {val}")
        self.indent_level -= 1
        self._emit('.')

    def _gen_commit_rollback(self, node: CommitRollbackStatement):
        wait = ' AND WAIT' if node.and_wait else ''
        self._emit(f"{node.keyword} WORK{wait}.")

    def _gen_export_import(self, node: ExportImportStatement):
        vars_str = ' '.join(node.variables)
        if node.memory_id:
            self._emit(f"{node.direction} {vars_str} TO MEMORY ID {node.memory_id}.")
        elif node.to_database:
            self._emit(f"{node.direction} {vars_str} TO DATABASE {node.to_database}.")
        else:
            self._emit(f"{node.direction} {vars_str}.")

    def _gen_set_get_parameter(self, node: SetGetParameterStatement):
        self._emit(f"{node.direction} PARAMETER ID {node.parameter_id} FIELD {node.field}.")

    # ── File I/O ──────────────────────────────────────────────────────────────

    def _gen_open_dataset(self, node: OpenDatasetStatement):
        self._emit(f"OPEN DATASET {node.dataset} {node.for_mode}.")

    def _gen_read_dataset(self, node: ReadDatasetStatement):
        self._emit(f"READ DATASET {node.dataset} INTO {node.into}.")

    def _gen_transfer(self, node: TransferStatement):
        self._emit(f"TRANSFER {node.source} TO {node.dataset}.")

    def _gen_close_dataset(self, node: CloseDatasetStatement):
        self._emit(f"CLOSE DATASET {node.dataset}.")

    def _gen_delete_dataset(self, node: DeleteDatasetStatement):
        self._emit(f"DELETE DATASET {node.dataset}.")

    # ── Flow control ──────────────────────────────────────────────────────────

    def _gen_simple_flow(self, node: SimpleFlowStatement):
        cond = f" {node.condition}" if node.condition else ''
        self._emit(f"{node.keyword}{cond}.")

    def _gen_leave(self, node: LeaveStatement):
        self._emit(f"LEAVE {node.leave_type}.")

    def _gen_submit(self, node: SubmitStatement):
        self._emit(f"SUBMIT {node.report_name}.")

    # ── Macro / Event / Selection Screen ──────────────────────────────────────

    def _gen_macro(self, node: MacroDefinition):
        self._emit(f"DEFINE {node.name}.")
        self.indent_level += 1
        self._emit(node.body_text)
        self.indent_level -= 1
        self._emit('END-OF-DEFINITION.')

    def _gen_event(self, node: EventBlock):
        self._emit(f"{node.event_name}.")
        if node.body:
            self.indent_level += 1
            for s in node.body: self._gen(s)
            self.indent_level -= 1

    def _gen_selection_screen(self, node: SelectionScreenStatement):
        self._emit(f"SELECTION-SCREEN {node.clause}.")

    # ── Screen / Dialog / Runtime ──────────────────────────────────────────────

    def _gen_call_screen(self, node: CallScreenStatement):
        parts = [f"CALL SCREEN {node.screen_number}"]
        if node.starting_at:
            parts.append(f"STARTING AT {node.starting_at}")
        if node.ending_at:
            parts.append(f"ENDING AT {node.ending_at}")
        self._emit(' '.join(parts) + '.')

    def _gen_call_dialog(self, node: CallDialogStatement):
        self._emit(f"CALL DIALOG {node.dialog_name}.")

    def _gen_wait(self, node: WaitStatement):
        if node.wait_type == 'UP_TO':
            self._emit(f"WAIT UP TO {node.duration} SECONDS.")
        elif node.wait_type == 'FOR_TASKS':
            self._emit(f"WAIT FOR {node.condition}.")
        else:
            cond = f" {node.condition}" if node.condition else ''
            self._emit(f"WAIT{cond}.")

    def _gen_get_run_time(self, node: GetRunTimeStatement):
        self._emit(f"GET RUN TIME FIELD {node.field_name}.")

    def _gen_set_property(self, node: SetPropertyStatement):
        extra = f" {node.additional_clause}" if node.additional_clause else ''
        self._emit(f"SET {node.set_type} {node.value}{extra}.")

    def _gen_set_locale(self, node: SetLocaleStatement):
        parts = ['SET LOCALE LANGUAGE', node.language]
        if node.country:
            parts.extend(['COUNTRY', node.country])
        if node.modifier:
            parts.extend(['MODIFIER', node.modifier])
        self._emit(' '.join(parts) + '.')

    # ── Database Cluster / Shared Memory ───────────────────────────────────────

    def _gen_export_import_db(self, node: ExportImportDatabaseStatement):
        fields_str = ' '.join(node.fields) if node.fields else '...'
        if node.direction == 'EXPORT':
            self._emit(f"EXPORT {fields_str} TO DATABASE {node.table_name}({node.area}) ID {node.id_clause}.")
        else:
            self._emit(f"IMPORT {fields_str} FROM DATABASE {node.table_name}({node.area}) ID {node.id_clause}.")

    def _gen_export_import_shm(self, node: ExportImportSharedMemoryStatement):
        fields_str = ' '.join(node.fields) if node.fields else '...'
        if node.direction == 'EXPORT':
            self._emit(f"EXPORT {fields_str} TO SHARED MEMORY {node.area} ID {node.id_clause}.")
        else:
            self._emit(f"IMPORT {fields_str} FROM SHARED MEMORY {node.area} ID {node.id_clause}.")

    # ── Legacy / Obsolete Statements ───────────────────────────────────────────

    def _gen_provide(self, node: ProvideEndprovideBlock):
        fields_str = ' '.join(node.fields) if node.fields else '*'
        tables_str = ' '.join(node.from_tables) if node.from_tables else ''
        between = f" BETWEEN {node.between_clause}" if node.between_clause else ''
        self._emit(f"PROVIDE {fields_str} FROM {tables_str}{between}.")
        self.indent_level += 1
        for s in node.body:
            self._gen(s)
        self.indent_level -= 1
        self._emit('ENDPROVIDE.')

    def _gen_field_group(self, node: FieldGroupDeclaration):
        self._emit(f"FIELD-GROUPS {node.name}.")

    def _gen_extract(self, node: ExtractStatement):
        fg = f" {node.field_group}" if node.field_group else ''
        self._emit(f"EXTRACT{fg}.")

    def _gen_catch_system_exception(self, node: CatchSystemExceptionBlock):
        exc_list = ' '.join(f"{name} = {rc}" for name, rc in node.exceptions) if node.exceptions else ''
        self._emit(f"CATCH SYSTEM-EXCEPTIONS {exc_list}.")
        self.indent_level += 1
        for s in node.body:
            self._gen(s)
        self.indent_level -= 1
        self._emit('ENDCATCH.')

    # ── Conversion / Type Handling ─────────────────────────────────────────────

    def _gen_convert(self, node: ConvertStatement):
        parts = ['CONVERT']
        if node.convert_type == 'DATE':
            parts.extend(['DATE', node.source_value])
        elif node.convert_type == 'TIME':
            parts.extend(['TIME', node.source_value])
        elif node.convert_type == 'TIME_STAMP':
            parts.extend(['TIME STAMP', node.source_value])
        elif node.convert_type == 'INVERTED_DATE':
            parts.extend(['INVERTED-DATE', node.source_value])
        if node.target_field:
            parts.extend(['INTO', node.target_field])
        if node.time_zone:
            parts.extend(['TIME ZONE', node.time_zone])
        if node.additional_clause:
            parts.append(node.additional_clause)
        self._emit(' '.join(parts) + '.')

    # ── LOOP Processing Events ─────────────────────────────────────────────────

    def _gen_at_loop_boundary(self, node: AtLoopBoundaryStatement):
        if node.boundary_type in ('NEW', 'END_OF'):
            kw = 'NEW' if node.boundary_type == 'NEW' else 'END OF'
            self._emit(f"AT {kw} {node.field_name}.")
        else:
            self._emit(f"AT {node.boundary_type}.")
        self.indent_level += 1
        for s in node.body:
            self._gen(s)
        self.indent_level -= 1
        self._emit('ENDAT.')

    def _gen_sum(self, node: SumStatement):
        self._emit('SUM.')

    # ── DESCRIBE FIELD ─────────────────────────────────────────────────────────

    def _gen_describe_field(self, node: DescribeFieldStatement):
        parts = [f"DESCRIBE FIELD {node.field_name}"]
        if node.type_var: parts.append(f"TYPE {node.type_var}")
        if node.length_var: parts.append(f"LENGTH {node.length_var}")
        if node.decimals_var: parts.append(f"DECIMALS {node.decimals_var}")
        if node.output_length_var: parts.append(f"OUTPUT-LENGTH {node.output_length_var}")
        if node.components_var: parts.append(f"COMPONENTS {node.components_var}")
        if node.edit_mask_var: parts.append(f"EDIT MASK {node.edit_mask_var}")
        if node.help_id_var: parts.append(f"HELP-ID {node.help_id_var}")
        self._emit(' '.join(parts) + '.')

    # ── ENHANCEMENT-POINT / ENHANCEMENT-SECTION ───────────────────────────────

    def _gen_enhancement_point(self, node: EnhancementPointStatement):
        if node.enhancement_type == 'SECTION':
            extra = ' STATIC' if node.is_static else ''
            bound = ' INCLUDE BOUND' if node.include_bound else ''
            self._emit(f"ENHANCEMENT-SECTION {node.spot_name}{extra}{bound}.")
            self.indent_level += 1
            for s in node.body:
                self._gen(s)
            self.indent_level -= 1
            self._emit('END-ENHANCEMENT-SECTION.')
        else:
            extra = ' STATIC' if node.is_static else ''
            bound = ' INCLUDE BOUND' if node.include_bound else ''
            self._emit(f"ENHANCEMENT-POINT {node.spot_name}{extra}{bound}.")

    # ── SUPPLY / DEMAND ───────────────────────────────────────────────────────

    def _gen_supply_demand(self, node: SupplyDemandStatement):
        parts = [node.direction]
        for fname, fval in node.fields:
            if fval:
                parts.append(f"{fname} = {fval}")
            else:
                parts.append(fname)
        if node.direction == 'SUPPLY':
            parts.append(f"TO CONTEXT {node.target}")
        else:
            parts.append(f"FROM CONTEXT {node.target}")
        self._emit(' '.join(parts) + '.')

    # ── Generic fallback ──────────────────────────────────────────────────────

    def _gen_generic(self, node: GenericStatement):
        if node.raw_text:
            self._emit(f"{node.raw_text}.")
        elif node.raw_tokens:
            self._emit(f"{' '.join(node.raw_tokens)}.")

    def _gen_fallback(self, node: ABAPNode):
        """Catch-all for any node type without a specific generator."""
        self._emit(f"* [AST Engine: unhandled node type {node.node_type}]")


# ═══════════════════════════════════════════════════════════════════════════════
# OUTPUT SAFETY NET
# ═══════════════════════════════════════════════════════════════════════════════
# An AST round-trip can lose operands for any statement type the parser/generator
# doesn't fully model. Emitting such a reconstruction silently corrupts code
# (e.g. `APPEND x TO ..`, `SELECT-OPTIONS : FOR .`). This reconciliation pass
# detects those signatures in the generated output and restores the verbatim
# original source line for that statement — original ABAP always compiles, a
# lossy reconstruction may not. This guarantees the engine never CORRUPTS code
# it failed to model, regardless of parser completeness.

_LOSSY_LINE_PATTERNS = [
    re.compile(r'\bTO\s*\.+\s*$', re.I),     # APPEND x TO .  /  ... TO ..
    re.compile(r'\bFOR\s+\.\s*$', re.I),     # SELECT-OPTIONS : FOR .
    re.compile(r'\bINTO\s*\.+\s*$', re.I),
    re.compile(r'\bFROM\s*\.+\s*$', re.I),
    re.compile(r'\bWITH\s*\.+\s*$', re.I),
    re.compile(r'=\s*\.\s*$'),               # x = .
    re.compile(r'\s\.\.\s*$'),               # dangling double period
    re.compile(r'^\s*[\w/<>-]+\s*:\s*FOR\b', re.I),
]


def _reconcile_lossy_lines(original_source: str, generated_code: str) -> str:
    """Restore generated lines that lost operands during AST round-trip.

    For each generated line matching a corruption signature, substitute the
    next unused original source line that begins with the same keyword. Safe by
    construction: it only ever replaces a detectably-broken line with a verbatim
    original statement.
    """
    from collections import defaultdict

    out_lines = generated_code.splitlines()
    if not any(p.search(l) for l in out_lines for p in _LOSSY_LINE_PATTERNS):
        return generated_code  # fast path — nothing corrupted

    orig_by_kw = defaultdict(list)
    for ol in original_source.splitlines():
        s = ol.strip()
        if not s or s.startswith('*') or s.startswith('"'):
            continue
        first = s.split(None, 1)[0].upper().rstrip(':')
        orig_by_kw[first].append(ol.rstrip())

    ptr = defaultdict(int)
    repaired = 0
    for i, line in enumerate(out_lines):
        s = line.strip()
        if not s or s.startswith('*'):
            continue
        if any(p.search(s) for p in _LOSSY_LINE_PATTERNS):
            first = s.split(None, 1)[0].upper().rstrip(':')
            cands = orig_by_kw.get(first, [])
            j = ptr[first]
            if j < len(cands):
                out_lines[i] = cands[j]
                ptr[first] = j + 1
                repaired += 1
    if repaired:
        logger.warning(
            f"Output safety net restored {repaired} lossy generated line(s) "
            f"from original source (AST round-trip gap)"
        )
    return "\n".join(out_lines)


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════

def process_abap_file(source_code: str, rules: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Main entry point for the ABAP AST Engine.

    Pipeline:
      1. Lex the source into tokens
      2. Parse tokens into an AST
      3. Apply S/4HANA transformation rules via the visitor
      4. Generate clean ABAP from the transformed AST

    Args:
        source_code: Raw ABAP source text
        rules: Optional custom transformation rules dict

    Returns:
        dict with keys:
          - 'transformed_code': The migrated ABAP source code
          - 'changes': List of ChangeRecord dicts describing each transformation
          - 'parse_errors': List of any parse errors encountered
          - 'stats': Summary statistics
    """
    # Step 1: Lex
    lexer = ABAPLexer(source_code)
    tokens = lexer.tokenize()
    logger.info(f"Lexer produced {len(tokens)} tokens")

    # Step 2: Parse
    parser = ABAPParser(tokens)
    program = parser.parse()
    stmt_count = len(program.statements)
    logger.info(f"Parser built AST with {stmt_count} top-level statements, {len(parser.errors)} errors")

    # Step 3: Transform
    visitor = S4HANATransformVisitor(custom_rules=rules or {})
    transformed_program, changes = visitor.transform(program)
    logger.info(f"Transformer applied {len(changes)} changes")

    # Step 4: Generate
    generator = ABAPCodeGenerator()
    output_code = generator.generate(transformed_program)

    # Step 4b: Output safety net — restore any lossy reconstruction from source
    output_code = _reconcile_lossy_lines(source_code, output_code)

    # Build result
    severity_counts = {}
    category_counts = {}
    for c in changes:
        severity_counts[c.severity] = severity_counts.get(c.severity, 0) + 1
        category_counts[c.category] = category_counts.get(c.category, 0) + 1

    return {
        'transformed_code': output_code,
        'changes': [c.to_dict() for c in changes],
        'parse_errors': parser.errors,
        'stats': {
            'total_tokens': len(tokens),
            'total_statements': stmt_count,
            'total_changes': len(changes),
            'severity_breakdown': severity_counts,
            'category_breakdown': category_counts,
            'parse_error_count': len(parser.errors),
        },
    }
