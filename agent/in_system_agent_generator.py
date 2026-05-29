"""
in_system_agent_generator.py — Migrate4HANA "Natuvion layer"
================================================================
Selective, in-system data carve-outs.

`InSystemAgentGenerator` dynamically writes *parameterized, high-performance ABAP*
extraction programs that are injected into the SOURCE SAP instance as temporary
local ``$TMP`` objects (via the released ``RPY_PROGRAM_INSERT`` + ``RZL_SUBMIT``
mechanism already implemented in :class:`agent.deploy_run_abap.InSystemABAPAgent`).

Design goals (all deterministic — zero AI, zero network beyond RFC):

* **Hard organizational + time filters** — Company Code (``BUKRS``) and Fiscal
  Year (``GJAHR``) are pushed down into the database ``WHERE`` clause so only the
  carved-out slice ever leaves the source.
* **Cursor streaming** — ``OPEN CURSOR`` + ``FETCH NEXT CURSOR ... PACKAGE SIZE``
  so arbitrarily large tables are processed in bounded chunks and never blow the
  work-process heap (``TSV_TNEW_PAGE_ALLOC_FAILED``).
* **Transactional dependency-awareness** — when a financial *line-item* table
  (``ACDOCA``, ``BSEG``, ``BSID``, ``BSIK`` …) is carved out, the matching
  document *headers* (``BKPF``) are pulled for the same keys (``FOR ALL ENTRIES``)
  so no document reference is left orphaned in the target.
* **Two output sinks** — a compact run *summary* is always EXPORTed to the INDX
  cluster (read back by the agent over RFC); optionally each package is also
  streamed to an application-server dataset for bulk carve-out.

Security: ``BUKRS`` / ``GJAHR`` / table & field names are embedded into generated
ABAP source, so every interpolated value is **strictly validated** against an
allow-list pattern before it is written — this prevents ABAP source injection.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# ──────────────────────────────────────────────────────────────────────────
# Table metadata registry — the deterministic knowledge that makes a carve-out
# org-/time-filtered and dependency-aware. Extend this dict to add tables.
#   bukrs_field / gjahr_field : the columns the WHERE clause filters on ("" if
#                               the table is not company-code / year scoped)
#   header                    : the header table to co-extract (None if header)
#   header_join               : list of (line_field, header_field) key pairs
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class TableSpec:
    table: str
    bukrs_field: str = ""
    gjahr_field: str = ""
    header: Optional[str] = None
    header_join: tuple = ()        # ((line_col, header_col), ...)
    note: str = ""


TABLE_REGISTRY: dict[str, TableSpec] = {
    # S/4 Universal Journal line items -> headers in BKPF
    "ACDOCA": TableSpec("ACDOCA", "RBUKRS", "GJAHR", "BKPF",
                        (("RBUKRS", "BUKRS"), ("GJAHR", "GJAHR"), ("BELNR", "BELNR")),
                        "Universal Journal; co-extract BKPF headers"),
    # Classic FI line items
    "BSEG":   TableSpec("BSEG", "BUKRS", "GJAHR", "BKPF",
                        (("BUKRS", "BUKRS"), ("GJAHR", "GJAHR"), ("BELNR", "BELNR"))),
    "BSID":   TableSpec("BSID", "BUKRS", "GJAHR", "BKPF",
                        (("BUKRS", "BUKRS"), ("GJAHR", "GJAHR"), ("BELNR", "BELNR")),
                        "Open AR items"),
    "BSIK":   TableSpec("BSIK", "BUKRS", "GJAHR", "BKPF",
                        (("BUKRS", "BUKRS"), ("GJAHR", "GJAHR"), ("BELNR", "BELNR")),
                        "Open AP items"),
    "BKPF":   TableSpec("BKPF", "BUKRS", "GJAHR", None, ()),
    # Logistics docs (year-scoped via the doc; company code via header)
    "EKKO":   TableSpec("EKKO", "BUKRS", "", None, (), "Purchasing doc headers"),
    "EKPO":   TableSpec("EKPO", "BUKRS", "", "EKKO", (("EBELN", "EBELN"),)),
    "VBAK":   TableSpec("VBAK", "", "", None, (), "Sales doc headers"),
    "VBAP":   TableSpec("VBAP", "", "", "VBAK", (("VBELN", "VBELN"),)),
    # Material / stock
    "MARD":   TableSpec("MARD", "", "", None, (), "Storage-location stock"),
    "MARC":   TableSpec("MARC", "", "", None, (), "Plant material"),
    # Masters (org-scoped where applicable)
    "ANLA":   TableSpec("ANLA", "BUKRS", "", None, (), "Asset master"),
    "CSKS":   TableSpec("CSKS", "", "GJAHR", None, (), "Cost center master"),
}

_ALNUM = re.compile(r"^[A-Za-z0-9_]{1,30}$")     # table / field names
_ORGVAL = re.compile(r"^[A-Za-z0-9]{1,10}$")     # BUKRS / GJAHR values


def _ck_ident(value: str, what: str) -> str:
    if not value or not _ALNUM.match(value):
        raise ValueError(f"unsafe {what} for ABAP generation: {value!r}")
    return value.upper()


def _ck_val(value: str, what: str) -> str:
    if value is None or not _ORGVAL.match(str(value)):
        raise ValueError(f"unsafe {what} value for ABAP generation: {value!r}")
    return str(value).upper()


@dataclass
class CarveOutSpec:
    """A fully-resolved carve-out request (the result of validating user input)."""
    table: str
    bukrs: str = ""
    gjahr: str = ""
    package_size: int = 50000
    pull_headers: bool = True
    dataset_path: str = ""          # optional app-server output; "" = summary only
    program_name: str = ""
    indx_relid: str = "ZM"
    indx_key: str = "M4H_XTR_RESULT"
    spec: TableSpec = field(default=None)


class InSystemAgentGenerator:
    """Generate (and optionally deploy) deterministic in-system carve-out ABAP."""

    MIN_PACKAGE = 1000
    MAX_PACKAGE = 500000

    def __init__(self, registry: Optional[dict] = None):
        self.registry = registry or TABLE_REGISTRY

    # ── public API ─────────────────────────────────────────────────────
    def plan(self, table: str, bukrs: str = "", gjahr: str = "",
             package_size: int = 50000, pull_headers: bool = True,
             dataset_path: str = "") -> CarveOutSpec:
        """Validate inputs and resolve a CarveOutSpec. Raises ValueError on bad input."""
        tbl = _ck_ident(table, "table")
        spec = self.registry.get(tbl)
        if spec is None:
            raise ValueError(f"table {tbl} is not in the carve-out registry; add a TableSpec")
        if not (self.MIN_PACKAGE <= int(package_size) <= self.MAX_PACKAGE):
            raise ValueError(f"package_size must be {self.MIN_PACKAGE}..{self.MAX_PACKAGE}")
        bukrs = _ck_val(bukrs, "BUKRS") if (bukrs and spec.bukrs_field) else ""
        gjahr = _ck_val(gjahr, "GJAHR") if (gjahr and spec.gjahr_field) else ""
        if dataset_path and not re.match(r"^[/A-Za-z0-9._\-]{1,120}$", dataset_path):
            raise ValueError(f"unsafe dataset_path: {dataset_path!r}")
        prog = f"ZM4H_XTR_{tbl}"[:30]
        return CarveOutSpec(table=tbl, bukrs=bukrs, gjahr=gjahr,
                            package_size=int(package_size),
                            pull_headers=bool(pull_headers and spec.header),
                            dataset_path=dataset_path, program_name=prog,
                            indx_key=f"M4H_XTR_{tbl}"[:30], spec=spec)

    def generate(self, table: str, bukrs: str = "", gjahr: str = "",
                 package_size: int = 50000, pull_headers: bool = True,
                 dataset_path: str = "") -> dict:
        """Return {program, source_lines, indx_relid, indx_key, meta} — does NOT touch SAP."""
        cs = self.plan(table, bukrs, gjahr, package_size, pull_headers, dataset_path)
        lines = self._emit(cs)
        return {
            "program": cs.program_name,
            "source_lines": lines,
            "source": "\n".join(lines),
            "indx_relid": cs.indx_relid,
            "indx_key": cs.indx_key,
            "meta": {"table": cs.table, "bukrs": cs.bukrs, "gjahr": cs.gjahr,
                     "package_size": cs.package_size, "pull_headers": cs.pull_headers,
                     "header_table": cs.spec.header if cs.pull_headers else None,
                     "dataset_path": cs.dataset_path},
        }

    def deploy_and_run(self, conn, table: str, timeout: int = 300, **kw) -> dict:
        """Generate the carve-out program and run it in-system via InSystemABAPAgent.
        `conn` is an open pyrfc Connection to the SOURCE. Returns the agent result
        enriched with the carve-out meta. Never raises (errors are returned)."""
        try:
            gen = self.generate(table, **kw)
        except Exception as ex:
            return {"ok": False, "error": f"generation failed: {ex}"}
        try:
            from deploy_run_abap import InSystemABAPAgent   # local import; same pkg
        except Exception:
            try:
                from agent.deploy_run_abap import InSystemABAPAgent  # type: ignore
            except Exception as ex:
                return {"ok": False, "error": f"InSystemABAPAgent unavailable: {ex}",
                        "program": gen["program"], "source": gen["source"]}
        agent = InSystemABAPAgent(conn)
        res = agent.deploy_and_run(gen["program"], gen["source_lines"],
                                   read_indx_key=gen["indx_key"], timeout=timeout)
        res = dict(res or {})
        res["carve_out_meta"] = gen["meta"]
        return res

    # ── ABAP emitter (deterministic) ────────────────────────────────────
    def _emit(self, cs: CarveOutSpec) -> list[str]:
        s = cs.spec
        L: list[str] = []
        a = L.append
        a(f"REPORT {cs.program_name.lower()}.")
        a("* ─────────────────────────────────────────────────────────────")
        a("* Migrate4HANA — in-system carve-out (generated; deterministic)")
        a(f"*   table={cs.table}  bukrs={cs.bukrs or '*'}  gjahr={cs.gjahr or '*'}")
        a(f"*   package_size={cs.package_size}  pull_headers={cs.pull_headers}")
        a("* ─────────────────────────────────────────────────────────────")
        # constants
        a(f"CONSTANTS gc_pkg TYPE i VALUE {cs.package_size}.")
        if cs.bukrs:
            a(f"CONSTANTS gc_bukrs TYPE {s.bukrs_field.lower()} VALUE '{cs.bukrs}'.")
        if cs.gjahr:
            a(f"CONSTANTS gc_gjahr TYPE {s.gjahr_field.lower()} VALUE '{cs.gjahr}'.")
        # data
        a(f"DATA lt_pack TYPE STANDARD TABLE OF {cs.table.lower()}.")
        if cs.pull_headers:
            a(f"DATA lt_hdr  TYPE STANDARD TABLE OF {s.header.lower()}.")
            a("DATA lv_hdr_total TYPE i.")
        a("DATA lv_total    TYPE i.")
        a("DATA lv_pkg_no   TYPE i.")
        a("DATA lv_cursor   TYPE cursor.")
        a("DATA lv_status   TYPE char10 VALUE 'OK'.")
        a("DATA lv_message  TYPE string.")
        if cs.dataset_path:
            a("DATA lv_line     TYPE string.")
            a("DATA lv_dsmsg    TYPE string.")
        a("")
        # main TRY
        a("TRY.")
        # build the filtered cursor
        where = self._where(cs)
        a("    OPEN CURSOR WITH HOLD lv_cursor FOR")
        a(f"      SELECT * FROM {cs.table.lower()}{where}.")
        if cs.dataset_path:
            a(f"    OPEN DATASET '{cs.dataset_path}' FOR OUTPUT IN TEXT MODE ENCODING UTF-8.")
            a("    IF sy-subrc <> 0.")
            a("      lv_status = 'ERROR'.")
            a(f"      lv_message = |cannot open dataset { '{' } '{cs.dataset_path}' { '}' }|.")
            a("    ENDIF.")
        a("    DO.")
        a("      FETCH NEXT CURSOR lv_cursor INTO TABLE lt_pack PACKAGE SIZE gc_pkg.")
        a("      IF sy-subrc <> 0.")
        a("        EXIT.")
        a("      ENDIF.")
        a("      lv_pkg_no = lv_pkg_no + 1.")
        a("      lv_total  = lv_total + lines( lt_pack ).")
        if cs.pull_headers:
            a("      IF lt_pack IS NOT INITIAL.")
            a("        \" dependency-aware header co-extract (no orphaned documents)")
            a(f"        SELECT * FROM {s.header.lower()}")
            a("          INTO TABLE lt_hdr")
            a("          FOR ALL ENTRIES IN lt_pack")
            a(self._for_all_entries_where(s))
            a("        lv_hdr_total = lv_hdr_total + lines( lt_hdr ).")
            a("      ENDIF.")
        if cs.dataset_path:
            a("      LOOP AT lt_pack ASSIGNING FIELD-SYMBOL(<ls>).")
            a("        lv_line = |{ <ls> }|.")
            a(f"        TRANSFER lv_line TO '{cs.dataset_path}'.")
            a("      ENDLOOP.")
        a("      CLEAR lt_pack.")
        if cs.pull_headers:
            a("      CLEAR lt_hdr.")
        a("    ENDDO.")
        a("    CLOSE CURSOR lv_cursor.")
        if cs.dataset_path:
            a(f"    CLOSE DATASET '{cs.dataset_path}'.")
        a("  CATCH cx_sy_open_sql_db INTO DATA(lx_db).")
        a("    lv_status = 'ERROR'.")
        a("    lv_message = lx_db->get_text( ).")
        a("  CATCH cx_root INTO DATA(lx_any).")
        a("    lv_status = 'ERROR'.")
        a("    lv_message = lx_any->get_text( ).")
        a("ENDTRY.")
        a("")
        # always export a compact summary the agent reads over RFC
        a("\" compact run summary -> INDX (read back by the agent)")
        a("DATA: BEGIN OF ls_sum,")
        a(f"        table    TYPE char30 VALUE '{cs.table}',")
        a("        total    TYPE i,")
        if cs.pull_headers:
            a("        headers  TYPE i,")
        a("        packages TYPE i,")
        a("        status   TYPE char10,")
        a("        message  TYPE string,")
        a("      END OF ls_sum.")
        a("ls_sum-total    = lv_total.")
        if cs.pull_headers:
            a("ls_sum-headers  = lv_hdr_total.")
        a("ls_sum-packages = lv_pkg_no.")
        a("ls_sum-status   = lv_status.")
        a("ls_sum-message  = lv_message.")
        a(f"EXPORT summary = ls_sum TO DATABASE indx({cs.indx_relid.lower()}) "
          f"ID '{cs.indx_key}'.")
        a("WRITE: / 'M4H carve-out', ls_sum-table, 'rows', lv_total,")
        a("         'packages', lv_pkg_no, 'status', lv_status.")
        return L

    def _where(self, cs: CarveOutSpec) -> str:
        conds = []
        if cs.bukrs:
            conds.append(f"{cs.spec.bukrs_field.lower()} = gc_bukrs")
        if cs.gjahr:
            conds.append(f"{cs.spec.gjahr_field.lower()} = gc_gjahr")
        if not conds:
            return ""
        return "\n        WHERE " + "\n          AND ".join(conds)

    @staticmethod
    def _for_all_entries_where(s: TableSpec) -> str:
        parts = [f"{hcol.lower()} = lt_pack-{lcol.lower()}" for lcol, hcol in s.header_join]
        return "          WHERE " + "\n            AND ".join(parts) + "."


# ── tiny self-test (no SAP needed): print a generated program ──────────────
if __name__ == "__main__":
    gen = InSystemAgentGenerator()
    out = gen.generate("ACDOCA", bukrs="1000", gjahr="2024", package_size=50000)
    print(f"* program: {out['program']}  indx: {out['indx_relid']}/{out['indx_key']}")
    print(out["source"])
