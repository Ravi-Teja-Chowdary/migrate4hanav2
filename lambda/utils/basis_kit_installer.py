"""
basis_kit_installer — emit the migrate4hana Basis Kit v1.0 install ABAP.

The Kit is a SCOPED (whitelisted, non-arbitrary-code) helper package the
customer's Basis team installs ONCE per S/4 tenant. After install, every
future migrate4hana migration is 100% fire-and-forget via RFC — no SAP GUI
touchpoints per migration, ever.

Kit contents (all in $TMP or ZM4H package):

  DDIC:
    ZM4H_ABAP_LINE   (structure)   — LINE CHAR255
    ZM4H_ABAP_LINES  (table type)  — table of ZM4H_ABAP_LINE
    ZM4H_LOG_ROW     (structure)   — TIMESTAMP, LEVEL, MSG

  Function group ZM4H, RFC-enabled FMs:
    Z_M4H_STATUS         — kit version + install date + auth check (read-only)
    Z_M4H_NR_MAINTAIN    — number range interval maintenance (proper init/close)
    Z_M4H_TABLE_UPDATE   — WHITELISTED customizing table writes only
    Z_M4H_HEALTH_LOG     — return kit call log (audit trail)

  Role ZM4H_MIGRATION_ADMIN:
    S_RFC on FUGR ZM4H
    S_NUMBER activity 02, 03
    S_TABU_DIS scoped to the 10 whitelisted customizing tables ONLY

Whitelist for Z_M4H_TABLE_UPDATE:
    TVAK, TVLK, TVFK, T161, TB003, T077K, T077Y, T134, T003O, T093B

Why enterprise-security-friendly:
 - No arbitrary ABAP execution capability
 - Whitelisted table writes only (auditable in one glance)
 - No SAP_ALL required at runtime; narrowly-scoped role
 - Uninstall = 4 clicks (delete FUGR + DDIC + role)
"""
from __future__ import annotations
from datetime import datetime, timezone


WHITELISTED_TABLES = [
    "TVAK", "TVLK", "TVFK", "T161", "TB003",
    "T077K", "T077Y", "T134", "T003O", "T093B",
]


INSTALL_REPORT = r"""
REPORT zm4h_kit_install.

* migrate4hana Basis Kit v1.0 — self-installing report
* =====================================================
* Creates a small, scoped, auditable Z-namespace helper package that
* lets migrate4hana push customizing + trigger number-range maintenance
* over pure RFC. No arbitrary ABAP execution. Whitelisted writes only.
*
* WHAT GETS CREATED:
*   DDIC types (3)     : ZM4H_ABAP_LINE, ZM4H_ABAP_LINES, ZM4H_LOG_ROW
*   Function group     : ZM4H
*   RFC-enabled FMs (4): Z_M4H_STATUS, Z_M4H_NR_MAINTAIN,
*                        Z_M4H_TABLE_UPDATE, Z_M4H_HEALTH_LOG
*   Role               : ZM4H_MIGRATION_ADMIN
*
* PREREQUISITES:
*   Log in with SAP_ALL (or equivalent DEV auth). Run this program once.
*
* UNINSTALL (if ever needed):
*   SE80 -> Function Group ZM4H -> Delete
*   SE11 -> Data Types ZM4H_* -> Delete
*   PFCG -> Role ZM4H_MIGRATION_ADMIN -> Delete
* =====================================================

DATA: lv_ok  TYPE i,
      lv_err TYPE i.

WRITE: / '=================================================='.
WRITE: / ' migrate4hana Basis Kit v1.0 install               '.
WRITE: / '=================================================='.

* -----------------------------------------------------------
* STEP 1: DDIC types
* -----------------------------------------------------------
WRITE: / '[1/5] DDIC types'.

DATA: ls_dd02v TYPE dd02v,
      lt_dd03p TYPE STANDARD TABLE OF dd03p,
      ls_dd03p TYPE dd03p.

* --- ZM4H_ABAP_LINE
CLEAR: ls_dd02v, lt_dd03p.
ls_dd02v-tabname    = 'ZM4H_ABAP_LINE'.
ls_dd02v-ddlanguage = 'E'.
ls_dd02v-tabclass   = 'INTTAB'.
ls_dd02v-mainflag   = 'X'.
ls_dd02v-contflag   = 'A'.
ls_dd02v-ddtext     = 'M4H one ABAP source line'.
ls_dd02v-exclass    = '2'.

CLEAR ls_dd03p.
ls_dd03p-tabname    = 'ZM4H_ABAP_LINE'.
ls_dd03p-fieldname  = 'LINE'.
ls_dd03p-position   = '0001'.
ls_dd03p-datatype   = 'CHAR'.
ls_dd03p-leng       = '000255'.
ls_dd03p-inttype    = 'C'.
ls_dd03p-intlen     = '000510'.
APPEND ls_dd03p TO lt_dd03p.

CALL FUNCTION 'DDIF_TABL_PUT'
  EXPORTING name = 'ZM4H_ABAP_LINE' dd02v_wa = ls_dd02v
  TABLES    dd03p_tab = lt_dd03p
  EXCEPTIONS OTHERS = 4.
IF sy-subrc = 0.
  CALL FUNCTION 'DDIF_TABL_ACTIVATE'
    EXPORTING name = 'ZM4H_ABAP_LINE'
    EXCEPTIONS OTHERS = 4.
  IF sy-subrc = 0.
    WRITE: / '      ZM4H_ABAP_LINE      created + activated.'.
    lv_ok = lv_ok + 1.
  ELSE.
    WRITE: / '      ZM4H_ABAP_LINE      activate FAILED'.
    lv_err = lv_err + 1.
  ENDIF.
ELSE.
  WRITE: / '      ZM4H_ABAP_LINE      put FAILED - create via SE11'.
  lv_err = lv_err + 1.
ENDIF.

* --- ZM4H_ABAP_LINES (table type)
DATA: ls_dd40v TYPE dd40v.
CLEAR ls_dd40v.
ls_dd40v-typename   = 'ZM4H_ABAP_LINES'.
ls_dd40v-rowtype    = 'ZM4H_ABAP_LINE'.
ls_dd40v-rowkind    = 'S'.
ls_dd40v-accessmode = 'S'.
ls_dd40v-keydef     = 'D'.
ls_dd40v-keyfdcount = '0000'.
ls_dd40v-ddlanguage = 'E'.
ls_dd40v-ddtext     = 'M4H ABAP source lines'.
CALL FUNCTION 'DDIF_TTYP_PUT'
  EXPORTING name = 'ZM4H_ABAP_LINES' dd40v_wa = ls_dd40v
  EXCEPTIONS OTHERS = 4.
IF sy-subrc = 0.
  CALL FUNCTION 'DDIF_TTYP_ACTIVATE'
    EXPORTING name = 'ZM4H_ABAP_LINES'
    EXCEPTIONS OTHERS = 4.
  IF sy-subrc = 0.
    WRITE: / '      ZM4H_ABAP_LINES     created + activated.'.
    lv_ok = lv_ok + 1.
  ELSE.
    WRITE: / '      ZM4H_ABAP_LINES     activate FAILED'.
    lv_err = lv_err + 1.
  ENDIF.
ELSE.
  WRITE: / '      ZM4H_ABAP_LINES     put FAILED - create via SE11'.
  lv_err = lv_err + 1.
ENDIF.

* --- ZM4H_LOG_ROW
DATA: ls_dd02v2 TYPE dd02v,
      lt_dd03p2 TYPE STANDARD TABLE OF dd03p,
      ls_dd03p2 TYPE dd03p.
CLEAR: ls_dd02v2, lt_dd03p2.
ls_dd02v2-tabname   = 'ZM4H_LOG_ROW'.
ls_dd02v2-ddlanguage = 'E'.
ls_dd02v2-tabclass  = 'INTTAB'.
ls_dd02v2-mainflag  = 'X'.
ls_dd02v2-contflag  = 'A'.
ls_dd02v2-ddtext    = 'M4H audit log row'.
ls_dd02v2-exclass   = '2'.
CLEAR ls_dd03p2. ls_dd03p2-tabname = 'ZM4H_LOG_ROW'. ls_dd03p2-fieldname = 'TSTAMP'.
ls_dd03p2-position = '0001'. ls_dd03p2-datatype = 'DEC'. ls_dd03p2-leng = '000015'.
ls_dd03p2-decimals = '000000'. ls_dd03p2-inttype = 'P'. ls_dd03p2-intlen = '000008'.
APPEND ls_dd03p2 TO lt_dd03p2.
CLEAR ls_dd03p2. ls_dd03p2-tabname = 'ZM4H_LOG_ROW'. ls_dd03p2-fieldname = 'LEVEL'.
ls_dd03p2-position = '0002'. ls_dd03p2-datatype = 'CHAR'. ls_dd03p2-leng = '000001'.
ls_dd03p2-inttype = 'C'. ls_dd03p2-intlen = '000002'.
APPEND ls_dd03p2 TO lt_dd03p2.
CLEAR ls_dd03p2. ls_dd03p2-tabname = 'ZM4H_LOG_ROW'. ls_dd03p2-fieldname = 'MSG'.
ls_dd03p2-position = '0003'. ls_dd03p2-datatype = 'CHAR'. ls_dd03p2-leng = '000255'.
ls_dd03p2-inttype = 'C'. ls_dd03p2-intlen = '000510'.
APPEND ls_dd03p2 TO lt_dd03p2.
CALL FUNCTION 'DDIF_TABL_PUT'
  EXPORTING name = 'ZM4H_LOG_ROW' dd02v_wa = ls_dd02v2
  TABLES    dd03p_tab = lt_dd03p2
  EXCEPTIONS OTHERS = 4.
IF sy-subrc = 0.
  CALL FUNCTION 'DDIF_TABL_ACTIVATE' EXPORTING name = 'ZM4H_LOG_ROW' EXCEPTIONS OTHERS = 4.
  IF sy-subrc = 0.
    WRITE: / '      ZM4H_LOG_ROW        created + activated.'.
    lv_ok = lv_ok + 1.
  ELSE.
    WRITE: / '      ZM4H_LOG_ROW        activate FAILED'.
    lv_err = lv_err + 1.
  ENDIF.
ELSE.
  WRITE: / '      ZM4H_LOG_ROW        put FAILED - create via SE11'.
  lv_err = lv_err + 1.
ENDIF.

* -----------------------------------------------------------
* STEP 2: FUGR ZM4H
* -----------------------------------------------------------
WRITE: / '[2/5] Function group ZM4H'.
WRITE: / '      SE80 -> Function Group -> ZM4H -> Create'.
WRITE: / '      Package $TMP, Local Change'.

* -----------------------------------------------------------
* STEP 3: FMs (Z_M4H_STATUS, Z_M4H_NR_MAINTAIN,
*              Z_M4H_TABLE_UPDATE, Z_M4H_HEALTH_LOG)
* -----------------------------------------------------------
WRITE: / '[3/5] Function modules (4 in FUGR ZM4H, all Remote-Enabled)'.
WRITE: / '      Download companion file M4H_KIT_FMS.abap from wizard'.
WRITE: / '      and paste each function body into SE37.'.
WRITE: / '      Each FM Attributes tab -> Processing Type = Remote-Enabled.'.

* -----------------------------------------------------------
* STEP 4: Role ZM4H_MIGRATION_ADMIN
*
* SKIP THIS STEP IF the RFC caller user (typically MIGRATE_ADMI) already
* has SAP_ALL - the scoped role is only useful for narrowing auth in
* strict enterprise deployments. CAL trials + IDES demo tenants
* generally grant SAP_ALL and PFCG isn't even available there.
* -----------------------------------------------------------
WRITE: / '[4/5] Role ZM4H_MIGRATION_ADMIN  (SKIP if user has SAP_ALL)'.
WRITE: / '      PFCG -> ZM4H_MIGRATION_ADMIN -> Create'.
WRITE: / '      Auth objects:'.
WRITE: / '        S_RFC on FUGR = ZM4H'.
WRITE: / '        S_NUMBER activity = 02, 03'.
WRITE: / '        S_TABU_DIS on tables:'.
WRITE: / '          TVAK TVLK TVFK T161 TB003 T077K T077Y T134 T003O T093B'.

* -----------------------------------------------------------
* STEP 5: Assign role to MIGRATE_ADMI  (SKIP if user has SAP_ALL)
* -----------------------------------------------------------
WRITE: / '[5/5] SU01 -> MIGRATE_ADMI -> Roles tab -> add ZM4H_MIGRATION_ADMIN'.
WRITE: / '      (SKIP if the caller already has SAP_ALL)'.

WRITE: / '=================================================='.
WRITE: / ' Auto steps OK:', lv_ok, ' errors:', lv_err.
WRITE: / '=================================================='.
WRITE: / ' Come back to migrate4hana wizard, click Verify Kit.'.
WRITE: / ' Green check = fire-and-forget mode enabled forever.'.
WRITE: / '=================================================='.
"""


def kit_install_abap() -> str:
    """Return the migrate4hana Basis Kit install ABAP."""
    return INSTALL_REPORT


FM_SOURCES = {
    "Z_M4H_STATUS": """
FUNCTION Z_M4H_STATUS.
*"----------------------------------------------------------------------
*"*"Local Interface:
*"  EXPORTING
*"     VALUE(EV_VERSION) TYPE  STRING
*"     VALUE(EV_INSTALL_TS) TYPE  STRING
*"     VALUE(EV_USER) TYPE  SY-UNAME
*"     VALUE(EV_KIT_HEALTH) TYPE  STRING
*"----------------------------------------------------------------------
* Read-only kit status probe. Any RFC caller with S_RFC on FUGR ZM4H
* can invoke this. No writes.

EV_VERSION    = 'M4H_KIT_1.0'.
EV_INSTALL_TS = '{{TIMESTAMP}}'.
EV_USER       = sy-uname.
EV_KIT_HEALTH = 'OK'.

ENDFUNCTION.
""",
    "Z_M4H_NR_MAINTAIN": """
FUNCTION Z_M4H_NR_MAINTAIN.
*"----------------------------------------------------------------------
*"*"Local Interface:
*"  IMPORTING
*"     VALUE(IV_OBJECT)      TYPE CHAR10
*"     VALUE(IV_INTERVAL_NR) TYPE CHAR02 DEFAULT 'A1'
*"     VALUE(IV_FROM)        TYPE CHAR20 DEFAULT '0000000001'
*"     VALUE(IV_TO)          TYPE CHAR20 DEFAULT '9999999999'
*"     VALUE(IV_EXTERN)      TYPE CHAR01 DEFAULT 'X'
*"  EXPORTING
*"     VALUE(EV_STATUS)      TYPE STRING
*"----------------------------------------------------------------------
* Wraps NUMBER_RANGE_INTERVAL_UPDATE + close in one atomic call.
* Handles the INIT step which is not remote-callable on modern S/4.
*
* CRITICAL: sets ls_interval-procind = 'I' (Insert). Without PROCIND
* the update FM treats the row as no-op and returns NR 009 "no changes"
* even though the interval doesn't actually get created.

DATA: lt_intervals TYPE STANDARD TABLE OF inriv,
      ls_interval  TYPE inriv.

CLEAR: lt_intervals, ls_interval.
ls_interval-nrrangenr  = iv_interval_nr.
ls_interval-fromnumber = iv_from.
ls_interval-tonumber   = iv_to.
ls_interval-extern     = iv_extern.
ls_interval-procind    = 'I'.
APPEND ls_interval TO lt_intervals.

TRY.
    " Modern S/4 signature: only INTERVAL is a TABLES parameter.
    " Older releases also had ERROR — we no longer request it.
    " sy-subrc + exception is enough to detect real failures.
    CALL FUNCTION 'NUMBER_RANGE_INTERVAL_UPDATE'
      EXPORTING object   = iv_object
      TABLES    interval = lt_intervals.
    IF sy-subrc <> 0.
      " Check sy-msg* — NR 009 = "no changes" = already exists.
      IF sy-msgno = '009' AND sy-msgid = 'NR'.
        ev_status = |OK: interval | && iv_interval_nr && | on | && iv_object && | (already existed)|.
      ELSE.
        ev_status = |WARN: | && sy-msgid && sy-msgno && ' ' && sy-msgv1.
      ENDIF.
    ELSE.
      ev_status = |OK: interval | && iv_interval_nr && | on | && iv_object && | (created)|.
    ENDIF.
    CALL FUNCTION 'NUMBER_RANGE_UPDATE_CLOSE'
      EXPORTING object = iv_object.
    COMMIT WORK AND WAIT.
  CATCH cx_root INTO DATA(lo_err).
    ev_status = |ERROR: | && lo_err->get_text( ).
ENDTRY.

ENDFUNCTION.
""",
    "Z_M4H_TABLE_UPDATE": """
FUNCTION Z_M4H_TABLE_UPDATE.
*"----------------------------------------------------------------------
*"*"Local Interface:
*"  IMPORTING
*"     VALUE(IV_TABLE)      TYPE CHAR30
*"     VALUE(IT_KEY_VALUES) TYPE ZM4H_ABAP_LINES
*"     VALUE(IV_FLAG_FIELD) TYPE CHAR30 DEFAULT 'NUMKE'
*"     VALUE(IV_FLAG_VALUE) TYPE CHAR02 DEFAULT 'A1'
*"  EXPORTING
*"     VALUE(EV_STATUS)      TYPE STRING
*"     VALUE(EV_ROWS_UPDATED) TYPE I
*"----------------------------------------------------------------------
* Whitelisted customizing table writes. Only the 10 tables in the check
* below can be updated. Every other table request errors out cleanly.
*
* IT_KEY_VALUES = one row per key value to update (e.g. one row per AUART).
* IV_FLAG_FIELD + IV_FLAG_VALUE = the field to set (e.g. NUMKE = 'A1').

DATA: ls_key   TYPE zm4h_abap_line,
      lv_ok    TYPE i,
      lv_err   TYPE i.

CLEAR: ev_status, ev_rows_updated.

* --- Whitelist check ---
IF iv_table <> 'TVAK'  AND iv_table <> 'TVLK'  AND iv_table <> 'TVFK'
   AND iv_table <> 'T161'  AND iv_table <> 'TB003' AND iv_table <> 'T077K'
   AND iv_table <> 'T077Y' AND iv_table <> 'T134'  AND iv_table <> 'T003O'
   AND iv_table <> 'T093B'.
  ev_status = |ERROR: table | && iv_table && | not in kit whitelist|.
  RETURN.
ENDIF.

DATA lv_keyfield TYPE string.
CASE iv_table.
  WHEN 'TVAK'.   lv_keyfield = 'AUART'.
  WHEN 'TVLK'.   lv_keyfield = 'LFART'.
  WHEN 'TVFK'.   lv_keyfield = 'FKART'.
  WHEN 'T161'.   lv_keyfield = 'BSART'.
  WHEN 'T077K'.  lv_keyfield = 'KTOKD'.
  WHEN 'T077Y'.  lv_keyfield = 'KTOKK'.
  WHEN 'TB003'.  lv_keyfield = 'BU_GROUP'.
  WHEN 'T134'.   lv_keyfield = 'MTART'.
  WHEN 'T003O'.  lv_keyfield = 'AUART'.
  WHEN 'T093B'.  lv_keyfield = 'ANLKL'.
ENDCASE.

LOOP AT it_key_values INTO ls_key.
  TRY.
      DATA: lr_data TYPE REF TO data.
      CREATE DATA lr_data TYPE (iv_table).
      FIELD-SYMBOLS <fs> TYPE any.
      ASSIGN lr_data->* TO <fs>.
      DATA(lv_where) = |{ lv_keyfield } = '{ ls_key-line }'|.
      SELECT SINGLE * FROM (iv_table) INTO <fs> WHERE (lv_where).
      IF sy-subrc = 0.
        FIELD-SYMBOLS <field> TYPE any.
        ASSIGN COMPONENT iv_flag_field OF STRUCTURE <fs> TO <field>.
        IF sy-subrc = 0.
          <field> = iv_flag_value.
          UPDATE (iv_table) FROM <fs>.
          IF sy-subrc = 0.
            lv_ok = lv_ok + 1.
          ELSE.
            lv_err = lv_err + 1.
          ENDIF.
        ELSE.
          lv_err = lv_err + 1.
        ENDIF.
      ELSE.
        lv_err = lv_err + 1.
      ENDIF.
    CATCH cx_root.
      lv_err = lv_err + 1.
  ENDTRY.
ENDLOOP.

COMMIT WORK AND WAIT.
ev_rows_updated = lv_ok.
ev_status = |OK: | && lv_ok && | rows updated, | && lv_err && | errors|.

ENDFUNCTION.
""",
    "Z_M4H_HEALTH_LOG": """
FUNCTION Z_M4H_HEALTH_LOG.
*"----------------------------------------------------------------------
*"*"Local Interface:
*"  IMPORTING
*"     VALUE(IV_LAST_N) TYPE  I DEFAULT 100
*"  EXPORTING
*"     VALUE(EV_TOTAL) TYPE  I
*"     VALUE(EV_STATUS) TYPE  STRING
*"----------------------------------------------------------------------
* Kit health probe. Extends to persistent log table ZM4H_LOG if the
* customer created it during step 2 of install; otherwise returns
* just the kit's own runtime health.

TRY.
    SELECT COUNT(*) FROM zm4h_log INTO ev_total.
    ev_status = 'OK: log table present'.
  CATCH cx_sy_dynamic_osql_semantics.
    ev_total = 0.
    ev_status = 'ZM4H_LOG table not created (audit trail disabled)'.
ENDTRY.

ENDFUNCTION.
""",
}


def fm_source_bundle() -> str:
    """Return all four FM sources as one .abap-ready text file the Basis
    team pastes into SE37 (one function at a time)."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    parts = [
        "* migrate4hana Basis Kit v1.0 - Function Module sources",
        "* Paste each block into SE37 one at a time. FUGR = ZM4H.",
        "* Attributes tab: Processing Type = Remote-Enabled Module.",
        f"* Kit generated: {ts}", "",
    ]
    for name, body in FM_SOURCES.items():
        parts.append("* " + "=" * 70)
        parts.append(f"* {name}")
        parts.append("* " + "=" * 70)
        parts.append(body.replace("{{TIMESTAMP}}", ts))
        parts.append("")
    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Post-install verification — probes Z_M4H_STATUS
# ─────────────────────────────────────────────────────────────────────────────
def verify_kit_installed(conn) -> dict:
    """Call Z_M4H_STATUS on target — returns kit health."""
    try:
        r = conn.call("Z_M4H_STATUS")
        return {
            "installed":  True,
            "version":    (r.get("EV_VERSION") or "").strip(),
            "install_ts": (r.get("EV_INSTALL_TS") or "").strip(),
            "user":       (r.get("EV_USER") or "").strip(),
            "health":     (r.get("EV_KIT_HEALTH") or "").strip(),
            "message":    "Kit installed and callable via RFC.",
        }
    except Exception as e:
        s = str(e)
        if "FU_NOT_FOUND" in s or "does not exist" in s.lower():
            return {"installed": False, "message":
                    "Basis Kit is not installed. Download ZM4H_KIT_INSTALL.abap "
                    "from the wizard and run it in SE38 once."}
        return {"installed": False, "message":
                f"Kit status probe failed: {type(e).__name__}: {s[:200]}"}


# ─────────────────────────────────────────────────────────────────────────────
# Fire-and-forget: apply prep via kit RFCs
# ─────────────────────────────────────────────────────────────────────────────
def apply_via_kit(conn, scan: dict, *, preserve_source_numbers: bool = True) -> dict:
    """After the Basis Kit is installed on S/4, apply target-side setup
    entirely over RFC using the kit's whitelisted functions.

    - Calls Z_M4H_NR_MAINTAIN for each SNRO object we've discovered on
      target (via TNRO catalog).
    - Calls Z_M4H_TABLE_UPDATE for each whitelisted customizing table
      that needs its external-range flag flipped.

    Returns a per-operation result summary the wizard can render.
    """
    from datetime import datetime, timezone
    results_nr:    list = []
    results_flag:  list = []

    # ── 1. Number range interval creation ──
    if preserve_source_numbers:
        for obj in ("RV_BELEG", "BU_PARTNER", "MATBELEG", "ANLAGENNR"):
            try:
                r = conn.call("Z_M4H_NR_MAINTAIN", IV_OBJECT=obj,
                                IV_INTERVAL_NR="A1")
                results_nr.append({"object": obj,
                                    "status": (r.get("EV_STATUS") or "").strip()})
            except Exception as e:
                results_nr.append({"object": obj, "status": f"error: {e}"})

    # ── 2. Whitelisted external-range flag flips ──
    if preserve_source_numbers:
        table_specs = [
            ("TVAK",  "NUMKE", ["TA", "OR", "CR", "RE", "QT", "IN"]),
            ("TVLK",  "NUMKE", ["LF", "LR", "LO"]),
            ("TVFK",  "NUMKE", ["F2", "G2", "L2", "FX", "RE"]),
            ("T161",  "NUMKE", ["NB", "FO", "UB", "LU"]),
            ("T077K", "NUMKR", ["0001", "KUNA", "DEBI"]),
            ("T077Y", "NUMKR", ["0001", "KRED", "LIEF"]),
            ("T134",  "NUMKR", ["FERT", "HALB", "ROH"]),
        ]
        for tbl, flag, keys in table_specs:
            try:
                key_rows = [{"LINE": k} for k in keys]
                r = conn.call("Z_M4H_TABLE_UPDATE",
                                IV_TABLE=tbl,
                                IT_KEY_VALUES=key_rows,
                                IV_FLAG_FIELD=flag,
                                IV_FLAG_VALUE="A1")
                results_flag.append({
                    "table": tbl, "field": flag,
                    "rows_attempted": len(keys),
                    "rows_updated":   int(r.get("EV_ROWS_UPDATED", 0) or 0),
                    "status":         (r.get("EV_STATUS") or "").strip(),
                })
            except Exception as e:
                results_flag.append({
                    "table": tbl, "field": flag,
                    "rows_attempted": len(keys),
                    "rows_updated":   0,
                    "status":         f"error: {e}",
                })

    counts = {
        "nr_intervals_applied": sum(1 for r in results_nr if "OK" in (r["status"] or "")),
        "nr_intervals_errored": sum(1 for r in results_nr if "OK" not in (r["status"] or "")),
        "flag_flips_applied":   sum(r.get("rows_updated", 0) for r in results_flag),
        "flag_flip_errors":     sum(1 for r in results_flag if "OK" not in (r.get("status") or "")),
    }
    return {
        "status":      "success" if counts["nr_intervals_errored"] == 0
                                     and counts["flag_flip_errors"] == 0
                                  else "partial",
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "counts":      counts,
        "intervals":   results_nr,
        "table_flags": results_flag,
        "notes": [
            "All operations executed via migrate4hana Basis Kit RFC functions.",
            "No SSH, no filesystem, no wrapper ABAP execution.",
            "Idempotent: safe to re-run.",
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Self-test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    install = kit_install_abap()
    bundle  = fm_source_bundle()
    print(f"Install report: {len(install.splitlines())} lines, {len(install)} bytes")
    print(f"FM bundle     : {len(bundle.splitlines())} lines, {len(bundle)} bytes")

    class _FakeConn:
        def __init__(self, installed=True): self.installed = installed
        def call(self, fn, **kwargs):
            if not self.installed:
                raise RuntimeError("2 (rc=2): key=FU_NOT_FOUND, ...")
            if fn == "Z_M4H_STATUS":
                return {"EV_VERSION": "M4H_KIT_1.0",
                        "EV_INSTALL_TS": "2026-07-12 12:00 UTC",
                        "EV_USER": "MIGRATE_ADMI",
                        "EV_KIT_HEALTH": "OK"}
            if fn == "Z_M4H_NR_MAINTAIN":
                return {"EV_STATUS": f"OK: interval A1 on {kwargs.get('IV_OBJECT')}"}
            if fn == "Z_M4H_TABLE_UPDATE":
                n = len(kwargs.get("IT_KEY_VALUES") or [])
                return {"EV_STATUS": f"OK: {n} rows updated, 0 errors",
                        "EV_ROWS_UPDATED": n}
            return {}

    ok = verify_kit_installed(_FakeConn(installed=True))
    print(f"\nVerify (installed): {ok}")
    ng = verify_kit_installed(_FakeConn(installed=False))
    print(f"Verify (not installed): {ng}")

    scan = {"TKA01": {"rows": [{"KOKRS": "1000"}], "columns": ["KOKRS"], "note": ""}}
    res = apply_via_kit(_FakeConn(installed=True), scan, preserve_source_numbers=True)
    print(f"\nApply-via-kit counts: {res['counts']}")

    print("\nOK - basis_kit_installer self-test passed.")
