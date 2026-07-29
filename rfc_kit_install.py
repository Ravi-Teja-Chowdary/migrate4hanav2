#!/usr/bin/env python
"""
rfc_kit_install.py — install the migrate4hana Basis Kit ENTIRELY over RFC.

Modern S/4 blocks arbitrary ABAP over RFC, but SAP's own repository functions
`RS_FUNCTION_POOL_INSERT` and `RPY_FUNCTIONMODULE_INSERT` are remote-enabled.
This creates the function group ZM4H and all kit function modules (remote-enabled)
without any SAP GUI / SE37 touch. The 3 DDIC types are created first by the SE38
report `ZM4H_KIT_INSTALL.abap` (they can't be made over RFC) — only ZM4H_ABAP_LINE
is actually required, because kit table params here are typed SOLI_TAB (the
RFC-safe standard type, per BASIS_KIT_OPERATIONS.md lesson #14).

Prereqs:
  - SE38 report ZM4H_KIT_INSTALL has been run (creates ZM4H_ABAP_LINE etc.).
  - env: M4H_ADMIN_PASSWD (admin/SAP* pw), connections.json points at the target.

Idempotent: re-running skips objects that already exist. Verifies with safe,
side-effect-free "dry" calls (non-existent keys / empty rows).
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("SAPNWRFC_HOME", str(ROOT / "sapnwrfc"))
sys.path.insert(0, str(ROOT / "lambda" / "utils"))

GROUP = "ZM4H"
TS = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


def _body_from_source(src: str) -> list:
    """Strip FUNCTION header + interface comment + ENDFUNCTION → body lines."""
    out = []
    for ln in src.strip("\n").splitlines():
        s = ln.strip()
        if s.upper().startswith("FUNCTION Z"):
            continue
        if s.startswith('*"'):
            continue
        if s == "ENDFUNCTION.":
            continue
        out.append(ln.replace("{{TIMESTAMP}}", TS))
    return out


# Parameter specs — (name, type, default_or_None, optional_bool)
# Types kept exactly as the live-debugged SE37 versions, EXCEPT table params are
# SOLI_TAB (RFC-safe) and the status FM's user field is STRING.
FM_SPECS = {
    "Z_M4H_STATUS": {
        "short": "M4H kit status",
        "imports": [],
        "exports": [("EV_VERSION", "STRING"), ("EV_INSTALL_TS", "STRING"),
                    ("EV_USER", "STRING"), ("EV_KIT_HEALTH", "STRING")],
        "body": [
            "  EV_VERSION    = 'M4H_KIT_1.1'.",
            f"  EV_INSTALL_TS = '{TS}'.",
            "  EV_USER       = sy-uname.",
            "  EV_KIT_HEALTH = 'OK'.",
        ],
    },
    "Z_M4H_NR_MODIFY": {
        "short": "M4H flip external flag on existing number-range interval",
        "imports": [("IV_OBJECT", "CHAR10", None, False),
                    ("IV_SUBOBJECT", "CHAR6", "SPACE", True),
                    ("IV_INTERVAL_NR", "CHAR02", None, False),
                    ("IV_EXTERN", "CHAR01", "'X'", True)],
        "exports": [("EV_STATUS", "BAPI_MSG")],
    },
    "Z_M4H_NR_MAINTAIN": {
        "short": "M4H create number-range interval",
        "imports": [("IV_OBJECT", "CHAR10", None, False),
                    ("IV_INTERVAL_NR", "CHAR02", "'A1'", True),
                    ("IV_FROM", "CHAR20", "'0000000001'", True),
                    ("IV_TO", "CHAR20", "'9999999999'", True),
                    ("IV_EXTERN", "CHAR01", "'X'", True)],
        "exports": [("EV_STATUS", "BAPI_MSG")],
    },
    "Z_M4H_TABLE_UPDATE": {
        "short": "M4H whitelisted customizing field write",
        "imports": [("IV_TABLE", "CHAR30", None, False),
                    ("IT_KEY_VALUES", "SOLI_TAB", None, False),
                    ("IV_FLAG_FIELD", "CHAR30", "'NUMKE'", True),
                    ("IV_FLAG_VALUE", "CHAR02", "'A1'", True)],
        "exports": [("EV_STATUS", "STRING"), ("EV_ROWS_UPDATED", "I")],
    },
    "Z_M4HTABLE_UPSERT": {
        "short": "M4H full-row customizing upsert",
        "imports": [("IV_TABLE", "CHAR30", None, False),
                    ("IV_FIELDS", "CHAR255", None, False),
                    ("IT_ROWS", "SOLI_TAB", None, False)],
        "exports": [("EV_STATUS", "BAPI_MSG"), ("EV_ROWS_UPSERTED", "I"),
                    ("EV_ROWS_FAILED", "I")],
    },
    "Z_M4H_STAGING_LOAD": {
        "short": "M4H MC staging-table loader (delivery class L only)",
        "imports": [("IV_TABLE", "CHAR30", None, False),
                    ("IV_FIELDS", "CHAR255", None, False),
                    ("IT_ROWS", "SOLI_TAB", None, False)],
        "exports": [("EV_STATUS", "BAPI_MSG"), ("EV_ROWS_UPSERTED", "I"),
                    ("EV_ROWS_FAILED", "I")],
    },
    "Z_M4H_STAGING_CLEAR": {
        "short": "M4H MC staging-table clear (delivery class L only)",
        "imports": [("IV_TABLE", "CHAR30", None, False)],
        "exports": [("EV_STATUS", "BAPI_MSG"), ("EV_ROWS_DELETED", "I")],
    },
    "Z_M4H_HEALTH_LOG": {
        "short": "M4H kit health / audit log",
        "imports": [("IV_LAST_N", "I", "100", True)],
        "exports": [("EV_TOTAL", "I"), ("EV_STATUS", "STRING")],
    },
}


def _rsimp(imports):
    rows = []
    for name, typ, default, optional in imports:
        r = {"PARAMETER": name, "TYP": typ}
        if default is not None:
            r["DEFAULT"] = default
        if optional:
            r["OPTIONAL"] = "X"
        rows.append(r)
    return rows


def _rsexp(exports):
    return [{"PARAMETER": name, "TYP": typ} for name, typ in exports]


def body_for(name: str, spec: dict) -> list:
    """The source body lines for a kit FM (with the SOLI_TAB retype applied)."""
    from basis_kit_installer import FM_SOURCES
    body = spec.get("body")
    if body is None:
        body = _body_from_source(FM_SOURCES[name])
        if name == "Z_M4H_TABLE_UPDATE":
            body = [ln.replace("zm4h_abap_line", "soli") for ln in body]
    return body


def install_kit(c, group: str = GROUP, name_fn=lambda n: n, verbose: bool = True):
    """Create the function group + all kit FMs over RFC (remote-enabled).

    ``name_fn`` maps a canonical FM name to the name to create — pass an aliasing
    function to validate the same bodies in a throwaway group. Source is sent via
    NEW_SOURCE (a table of STRING) so long lines are NOT truncated at 72 chars.
    """
    from pyrfc import ABAPApplicationError, ABAPRuntimeError
    try:
        c.call("RS_FUNCTION_POOL_INSERT", FUNCTION_POOL=group,
               SHORT_TEXT="migrate4hana Basis Kit", DEVCLASS="$TMP",
               SUPPRESS_CORR_CHECK="X", SUPPRESS_LANGUAGE_CHECK="X")
        if verbose: print(f"[grp] {group}: created")
    except (ABAPApplicationError, ABAPRuntimeError) as e:
        if getattr(e, "key", "") in ("FUNCTION_ALREADY_EXISTS", "NAME_ALREADY_EXISTS"):
            if verbose: print(f"[grp] {group}: already exists")
        else:
            if verbose: print(f"[grp] {group}: ERROR {getattr(e,'key','')} {str(e)[:120]}")
            return False
    for name, spec in FM_SPECS.items():
        body = body_for(name, spec)
        try:
            c.call("RPY_FUNCTIONMODULE_INSERT",
                   FUNCNAME=name_fn(name), FUNCTION_POOL=group,
                   SHORT_TEXT=spec["short"], REMOTE_CALL="R",
                   SUPPRESS_CORR_CHECK="X",
                   IMPORT_PARAMETER=_rsimp(spec["imports"]),
                   EXPORT_PARAMETER=_rsexp(spec["exports"]),
                   NEW_SOURCE=[{"": ln} for ln in body])   # STRING rows, no 72-char cap
            if verbose: print(f"[fm ] {name_fn(name)}: created")
        except (ABAPApplicationError, ABAPRuntimeError) as e:
            if verbose: print(f"[fm ] {name_fn(name)}: ERROR {getattr(e,'key','')} {str(e)[:140]}")
    return True


def syntax_check(c, group: str):
    r = c.call("RS_ABAP_SYNTAX_CHECK_E", P_PROGRAM=f"SAPL{group}")
    return r.get("P_SUBRC"), r.get("P_ERRORS", [])


def main() -> int:
    import argparse
    from pyrfc import Connection
    from basis_kit_installer import verify_kit_installed

    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default=GROUP)
    args = ap.parse_args()
    group = args.group

    conns = json.loads((ROOT / "connections.json").read_text())
    t = conns["lift_and_shift_target"]
    admin_user = os.environ.get("M4H_ADMIN_USER", "SAP*")
    admin_pw = os.environ.get("M4H_ADMIN_PASSWD")
    if not admin_pw:
        print("ERROR: set M4H_ADMIN_PASSWD (admin/SAP* password)"); return 2

    c = Connection(ashost=t["target_ashost"], sysnr=str(t.get("target_sysnr", "00")),
                   client=str(t.get("target_client", "100")),
                   user=admin_user, passwd=admin_pw, lang="EN")
    print(f"connected as {admin_user} -> {t['target_ashost']}\n")

    install_kit(c, group)

    print("\n== syntax check ==")
    subrc, errs = syntax_check(c, group)
    print(f"  SAPL{group} SUBRC={subrc}")
    for e in errs:
        print(f"  ERR {e.get('INCNAME')} line {e.get('LINE')}: {e.get('MESSAGE')}")
    if subrc not in (0, None):
        print("  -> group has syntax errors; not verifying calls.")
        c.close(); return 1

    print("\n== dry verification (side-effect-free) ==")
    print("  Z_M4H_STATUS      :", verify_kit_installed(c).get("message"))
    _dry(c, "Z_M4H_NR_MODIFY", IV_OBJECT="ZZM4HPROBE", IV_INTERVAL_NR="99", IV_EXTERN="X")
    _dry(c, "Z_M4H_TABLE_UPDATE", IV_TABLE="TVAK",
         IT_KEY_VALUES=[{"LINE": "ZZNOEXIST"}], IV_FLAG_FIELD="NUMKE", IV_FLAG_VALUE="02")
    _dry(c, "Z_M4HTABLE_UPSERT", IV_TABLE="TCURV", IV_FIELDS="KURST", IT_ROWS=[])
    _dry(c, "Z_M4H_HEALTH_LOG", IV_LAST_N=1)
    print("  Z_M4H_NR_MAINTAIN :", "present" if _exists(c, "Z_M4H_NR_MAINTAIN") else "MISSING")

    c.close()
    return 0


def _dry(c, fm, **kw):
    try:
        r = c.call(fm, **kw)
        msg = (r.get("EV_STATUS") or "").strip() or str({k: r.get(k) for k in r})[:80]
        print(f"  {fm:18}: OK -> {msg[:90]}")
    except Exception as e:  # noqa: BLE001
        print(f"  {fm:18}: FAIL -> {getattr(e,'key',type(e).__name__)}: {str(e)[:110]}")


def _exists(c, fm):
    try:
        r = c.call("RFC_READ_TABLE", QUERY_TABLE="TFDIR", DELIMITER="|",
                   OPTIONS=[{"TEXT": f"FUNCNAME = '{fm}'"}],
                   FIELDS=[{"FIELDNAME": "FUNCNAME"}], ROWCOUNT=1)
        return bool(r.get("DATA"))
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main())
