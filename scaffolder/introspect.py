"""
scaffolder.introspect — live BAPI signature inspector for the JSON authoring loop.

Authoring a correct JSON definition for a new object requires knowing the exact
parameter list of the target BAPI: the header struct name, the items table
name (when present), the return-key field name, and the field shapes of each
struct. Guessing those was the gap that caused the
phase_b_validate_generated live test to dead-letter with
``field 'RESERVATION_HEADER' not found`` until we re-authored the JSON.

This module closes that gap by talking directly to the live S/4 target:

    python -m scaffolder.introspect InventoryReservation

  Loads definitions/InventoryReservation.json, opens an RFC connection to
  the target (creds read from AWS Secrets Manager), calls
  RFC_GET_FUNCTION_INTERFACE on load.bapi.function, fetches the field shapes
  of every referenced struct via DD03L, prints a clean summary, and diffs
  it against the JSON. Findings are printed with severity.

    python -m scaffolder.introspect --bapi BAPI_PR_CREATE

  Raw BAPI introspection — no JSON file needed. Useful when authoring a new
  definition for the first time: copy the printed names verbatim into the
  JSON.

    python -m scaffolder.introspect --all --check

  CI gate: introspect every object's BAPI, fail non-zero on any mismatch
  between JSON and live signature. Needs live S/4 access on the runner
  (or every BAPI cached under scaffolder/introspections/).

    python -m scaffolder.introspect InventoryReservation --save

  After live introspection, write the result to
  scaffolder/introspections/<BAPI>.json so subsequent runs (or CI without
  live access) can use --cache-only.

Connection: by default reads credentials from AWS Secrets Manager
``migrate4hana/prod/s4hana-credentials``. Override with --secret-id, or
pass connection details on the CLI via --ashost/--sysnr/--client/--user/
--passwd for non-AWS targets.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


SCAFFOLDER_DIR        = Path(__file__).resolve().parent
REPO_ROOT             = SCAFFOLDER_DIR.parent
DEFINITIONS_DIR       = REPO_ROOT / "definitions"
INTROSPECTIONS_DIR    = SCAFFOLDER_DIR / "introspections"
DEFAULT_SECRET_ID     = "migrate4hana/prod/s4hana-credentials"


# ─────────────────────────────────────────────────────────────────────────────
# Connection
# ─────────────────────────────────────────────────────────────────────────────
def _read_secret(secret_id: str) -> dict:
    try:
        import boto3
    except ImportError:
        raise SystemExit("boto3 not installed (pip install boto3)")
    sm = boto3.client("secretsmanager")
    resp = sm.get_secret_value(SecretId=secret_id)
    return json.loads(resp["SecretString"])


def _open_connection(args) -> "pyrfc.Connection":
    try:
        import pyrfc
    except ImportError:
        raise SystemExit(
            "pyrfc not installed. Install pyrfc + SAP NW RFC SDK to introspect live BAPIs. "
            "(For offline / CI use, see --cache-only.)"
        )
    if args.ashost:
        kwargs = {
            "ashost": args.ashost,
            "sysnr":  args.sysnr or "00",
            "client": args.client,
            "user":   args.user,
            "passwd": args.passwd,
            "lang":   args.lang or "EN",
        }
    else:
        sec = _read_secret(args.secret_id)
        kwargs = {
            "ashost": sec["ashost"],
            "sysnr":  sec.get("sysnr", "00"),
            "client": sec["client"],
            "user":   sec["user"],
            "passwd": sec.get("passwd") or sec.get("password"),
            "lang":   sec.get("lang", "EN"),
        }
    return pyrfc.Connection(**kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# Introspection — the live BAPI call
# ─────────────────────────────────────────────────────────────────────────────
def introspect_bapi(conn, func_name: str) -> dict:
    """Call RFC_GET_FUNCTION_INTERFACE + DD03L for every referenced struct.

    Returns a deterministic dict shape that can be cached + diffed.
    """
    try:
        r = conn.call("RFC_GET_FUNCTION_INTERFACE", FUNCNAME=func_name, LANGUAGE="E")
    except Exception as e:
        return {"bapi": func_name, "error": f"{type(e).__name__}: {str(e)[:240]}",
                "params": [], "structs": {}}

    params = []
    structs_to_fetch = set()
    for p in r.get("PARAMS", []) or []:
        kind = (p.get("PARAMCLASS") or "").strip()
        struct = (p.get("TABNAME") or "").strip()
        params.append({
            "name":     (p.get("PARAMETER") or "").strip(),
            "kind":     kind,                          # I=import E=export T=table C=changing
            "struct":   struct,
            "optional": (p.get("OPTIONAL") or "").strip() == "X",
            "text":     (p.get("PARAMTEXT") or "").strip(),
        })
        if struct:
            structs_to_fetch.add(struct)

    structs = {}
    for sname in sorted(structs_to_fetch):
        try:
            opt = "TABNAME = '" + sname + "' AND AS4LOCAL = 'A'"
            sr = conn.call(
                "RFC_READ_TABLE",
                QUERY_TABLE="DD03L", DELIMITER="|",
                FIELDS=[{"FIELDNAME": "FIELDNAME"},
                        {"FIELDNAME": "INTTYPE"},
                        {"FIELDNAME": "LENG"},
                        {"FIELDNAME": "KEYFLAG"},
                        {"FIELDNAME": "POSITION"}],
                OPTIONS=[{"TEXT": opt}],
            )
            fields = []
            for row in sr.get("DATA", []):
                parts = [c.strip() for c in row.get("WA", "").split("|")]
                while len(parts) < 5:
                    parts.append("")
                try:
                    pos = int(parts[4]) if parts[4] else 0
                except ValueError:
                    pos = 0
                fields.append({
                    "name":   parts[0],
                    "type":   parts[1],                # C=char N=numc D=date P=packed F=float I=int
                    "len":    int(parts[2]) if parts[2].isdigit() else 0,
                    "is_key": parts[3] == "X",
                    "position": pos,
                })
            fields.sort(key=lambda f: (f["position"], f["name"]))
            structs[sname] = fields
        except Exception as e:
            structs[sname] = [{"_error": f"{type(e).__name__}: {str(e)[:160]}"}]

    return {"bapi": func_name, "params": params, "structs": structs}


# ─────────────────────────────────────────────────────────────────────────────
# Cache
# ─────────────────────────────────────────────────────────────────────────────
def _cache_path(bapi_name: str) -> Path:
    return INTROSPECTIONS_DIR / f"{bapi_name}.json"


def load_cached(bapi_name: str) -> dict | None:
    p = _cache_path(bapi_name)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_cache(bapi_name: str, intro: dict, target_meta: dict) -> Path:
    INTROSPECTIONS_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(intro)
    payload["_target_meta"] = target_meta
    p = _cache_path(bapi_name)
    # Stable canonical-ish JSON: sorted keys, 2-space indent, no trailing space.
    p.write_text(json.dumps(payload, sort_keys=True, indent=2,
                            ensure_ascii=False) + "\n", encoding="utf-8")
    return p


# ─────────────────────────────────────────────────────────────────────────────
# Diff: JSON definition vs live introspection
# ─────────────────────────────────────────────────────────────────────────────
def diff_definition(intro: dict, definition: dict) -> list:
    """Compare load.bapi.* settings + transform.*_field_maps targets against the
    live BAPI's actual parameter list and struct field names.

    Returns a list of dict findings. Each has:
        severity:  "error" | "warning" | "info"
        check:     short id of what was checked
        message:   human-readable explanation
        declared:  what the JSON says
        actual:    what the live BAPI shows
    """
    findings: list = []
    # When the BAPI is a fallback (primary_lane != BAPI), demote introspection
    # failures to warnings — a missing fallback BAPI is informational, not a
    # deployment blocker. Only when the BAPI IS the primary lane should an
    # introspection failure be a hard error.
    primary_lane = (definition.get("load", {}) or {}).get("primary_lane", "")
    is_primary_bapi = primary_lane == "BAPI"
    failure_severity = "error" if is_primary_bapi else "warning"

    if "error" in intro:
        findings.append({
            "severity": failure_severity,
            "check":    "introspection",
            "message":  f"could not introspect BAPI: {intro['error']}",
            "declared": None, "actual": None,
        })
        return findings

    bapi = definition.get("load", {}).get("bapi", {}) or {}
    params = intro["params"]
    structs = intro["structs"]
    import_struct_params = [p for p in params if p["kind"] == "I" and p["struct"]]
    table_struct_params  = [p for p in params if p["kind"] == "T" and p["struct"]]
    export_params        = [p for p in params if p["kind"] == "E"]

    # 1. header_struct must be a real I-kind parameter
    declared_header = bapi.get("header_struct", "")
    if declared_header:
        names = [p["name"] for p in import_struct_params]
        if declared_header not in names:
            findings.append({
                "severity": "error", "check": "header_struct",
                "message":  f"load.bapi.header_struct {declared_header!r} is not an import parameter of {intro['bapi']}",
                "declared": declared_header,
                "actual":   names,
            })

    # 2. item_struct must be a real T-kind parameter (when declared)
    declared_item = bapi.get("item_struct", "")
    if declared_item:
        names = [p["name"] for p in table_struct_params]
        if declared_item not in names:
            findings.append({
                "severity": "error", "check": "item_struct",
                "message":  f"load.bapi.item_struct {declared_item!r} is not a table parameter of {intro['bapi']}",
                "declared": declared_item,
                "actual":   names,
            })

    # 3. return_key_field must be either an export param name OR a field in the
    #    export struct (single-field structs unwrap to the field value).
    declared_return = bapi.get("return_key_field", "")
    if declared_return:
        export_names = [p["name"] for p in export_params]
        export_struct_fields = []
        for ep in export_params:
            sname = ep["struct"]
            if sname and sname in structs:
                export_struct_fields.extend(
                    f["name"] for f in structs[sname] if "_error" not in f
                )
        if declared_return not in export_names and declared_return not in export_struct_fields:
            findings.append({
                "severity": "warning", "check": "return_key_field",
                "message":  f"load.bapi.return_key_field {declared_return!r} is neither an export param name nor a field of the export struct",
                "declared": declared_return,
                "actual":   {"export_params": export_names, "export_fields": export_struct_fields},
            })

    # 4. field_maps targets must be fields in the header struct
    header_param = next((p for p in import_struct_params if p["name"] == declared_header), None)
    if header_param and header_param["struct"] in structs:
        header_field_names = {f["name"] for f in structs[header_param["struct"]] if "_error" not in f}
        for src, tgt in (definition.get("transform", {}).get("field_maps", {}) or {}).items():
            if tgt not in header_field_names:
                findings.append({
                    "severity": "error", "check": "field_maps_target",
                    "message":  f"field_maps {src!r} -> {tgt!r}: target {tgt!r} not in header struct {header_param['struct']}",
                    "declared": tgt,
                    "actual":   sorted(header_field_names),
                })

    # 5. item_field_maps targets must be fields in the item struct
    item_param = next((p for p in table_struct_params if p["name"] == declared_item), None)
    if item_param and item_param["struct"] in structs:
        item_field_names = {f["name"] for f in structs[item_param["struct"]] if "_error" not in f}
        for src, tgt in (definition.get("transform", {}).get("item_field_maps", {}) or {}).items():
            if tgt not in item_field_names:
                findings.append({
                    "severity": "error", "check": "item_field_maps_target",
                    "message":  f"item_field_maps {src!r} -> {tgt!r}: target {tgt!r} not in item struct {item_param['struct']}",
                    "declared": tgt,
                    "actual":   sorted(item_field_names),
                })

    # 6. Info: required imports not covered by header_struct / item_struct
    required_imports = [p["name"] for p in params
                        if p["kind"] in ("I", "T")
                        and not p["optional"]
                        and p["name"] not in (declared_header, declared_item)]
    if required_imports:
        findings.append({
            "severity": "info", "check": "uncovered_required_params",
            "message":  f"BAPI has required parameter(s) not declared in load.bapi: {required_imports}",
            "declared": [declared_header, declared_item],
            "actual":   required_imports,
        })

    return findings


# ─────────────────────────────────────────────────────────────────────────────
# Printing
# ─────────────────────────────────────────────────────────────────────────────
def print_signature(intro: dict) -> None:
    if "error" in intro:
        print(f"ERROR: {intro['error']}")
        return
    print(f"== {intro['bapi']} ==")
    print("  Parameters:")
    for p in intro["params"]:
        opt = " (optional)" if p["optional"] else ""
        struct = f"  struct={p['struct']}" if p["struct"] else ""
        print(f"    [{p['kind']}] {p['name']:30s}{struct:35s}{opt}  // {p['text'][:60]}")
    print()
    print("  Structs:")
    for sname in sorted(intro["structs"].keys()):
        fields = intro["structs"][sname]
        print(f"    {sname} ({len(fields)} fields)")
        for f in fields[:30]:                   # head only to keep summary brief
            if "_error" in f:
                print(f"      <error: {f['_error']}>")
                continue
            keymark = " (key)" if f.get("is_key") else ""
            print(f"      {f['name']:25s} {f['type']:3s} len={f['len']:>4}{keymark}")
        if len(fields) > 30:
            print(f"      ... {len(fields) - 30} more fields")
        print()


def print_findings(findings: list) -> None:
    if not findings:
        print("No findings. JSON matches the live BAPI signature.")
        return
    severities = {"error": 0, "warning": 0, "info": 0}
    print(f"Findings ({len(findings)}):")
    for f in findings:
        sev = f.get("severity", "info")
        severities[sev] = severities.get(sev, 0) + 1
        marker = {"error": "X", "warning": "!", "info": "i"}.get(sev, "?")
        print(f"  [{marker}] ({sev}) {f['check']}: {f['message']}")
        if f.get("declared") is not None:
            print(f"        declared : {f['declared']}")
        if f.get("actual") is not None:
            actual = f["actual"]
            if isinstance(actual, list) and len(actual) > 6:
                actual = actual[:6] + [f"... +{len(actual) - 6} more"]
            print(f"        actual   : {actual}")
    print()
    print(f"Summary: {severities['error']} error(s), {severities['warning']} warning(s), "
          f"{severities['info']} info")


# ─────────────────────────────────────────────────────────────────────────────
# Definition loading
# ─────────────────────────────────────────────────────────────────────────────
def _load_definition(name_or_path: str):
    p = Path(name_or_path)
    if not p.suffix:
        p = DEFINITIONS_DIR / f"{name_or_path}.json"
    if not p.is_absolute():
        if not p.exists():
            p = REPO_ROOT / name_or_path
    if not p.exists():
        raise FileNotFoundError(f"definition not found: {p}")
    return p, json.loads(p.read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────────────────────
# Per-target metadata captured alongside cache so we know WHICH S/4 was probed
# ─────────────────────────────────────────────────────────────────────────────
def _target_meta(conn) -> dict:
    try:
        r = conn.call("RFC_SYSTEM_INFO")
        sys_info = r.get("RFCSI_EXPORT", {}) or {}
        return {
            "sid":          (sys_info.get("RFCSYSID") or "").strip(),
            "release":      (sys_info.get("RFCSAPRL") or "").strip(),
            "host":         (sys_info.get("RFCHOST")  or "").strip(),
            "dbsys":        (sys_info.get("RFCDBSYS") or "").strip(),
        }
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {str(e)[:120]}"}


# ─────────────────────────────────────────────────────────────────────────────
# Command implementations
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_introspection(bapi_name: str, args, conn=None) -> tuple:
    """Return (introspection, target_meta_or_None). Tries cache first if
    --cache-only is set; otherwise live, with cache as fallback on RFC error."""
    if args.cache_only:
        cached = load_cached(bapi_name)
        if cached is None:
            return ({"bapi": bapi_name,
                     "error": f"no cache at {_cache_path(bapi_name).relative_to(REPO_ROOT)}",
                     "params": [], "structs": {}}, None)
        return (cached, cached.get("_target_meta"))

    # Live
    if conn is None:
        conn = _open_connection(args)
    meta = _target_meta(conn)
    intro = introspect_bapi(conn, bapi_name)
    return (intro, meta)


def cmd_object(name: str, args, conn=None) -> int:
    path, defn = _load_definition(name)
    bapi = (defn.get("load", {}).get("bapi", {}) or {}).get("function")
    if not bapi:
        print(f"ERROR: {name} does not declare load.bapi.function — cannot introspect")
        return 1

    intro, meta = _resolve_introspection(bapi, args, conn=conn)

    if args.save and "error" not in intro:
        saved = save_cache(bapi, intro, meta or {})
        print(f"cached to {saved.relative_to(REPO_ROOT)}")
        print()

    if args.print_signature:
        print_signature(intro)

    findings = diff_definition(intro, defn)
    print(f"-- {name} ({bapi}) --")
    if meta:
        print(f"target: SID={meta.get('sid')}  release={meta.get('release')}")
    print()
    print_findings(findings)

    if args.check and any(f.get("severity") == "error" for f in findings):
        return 1
    return 0


def cmd_bapi(bapi_name: str, args, conn=None) -> int:
    intro, meta = _resolve_introspection(bapi_name, args, conn=conn)
    if args.save and "error" not in intro:
        saved = save_cache(bapi_name, intro, meta or {})
        print(f"cached to {saved.relative_to(REPO_ROOT)}")
        print()
    print_signature(intro)
    return 0 if "error" not in intro else 1


def cmd_all(args) -> int:
    if not DEFINITIONS_DIR.exists():
        print(f"definitions/ missing: {DEFINITIONS_DIR}")
        return 1
    overall = 0
    conn = None if args.cache_only else _open_connection(args)
    try:
        for f in sorted(DEFINITIONS_DIR.glob("*.json")):
            if f.name.startswith("_"):
                continue
            try:
                rc = cmd_object(f.stem, args, conn=conn)
            except Exception as e:
                print(f"-- {f.stem} -- ERROR: {type(e).__name__}: {str(e)[:200]}")
                rc = 1
            if rc != 0:
                overall = 1
            print()
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return overall


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="scaffolder.introspect",
        description="Live BAPI signature inspector + JSON-definition diff",
    )
    ap.add_argument("object", nargs="?",
                    help="object name (looks up definitions/<name>.json). "
                         "Omit when using --bapi or --all.")
    ap.add_argument("--bapi", help="raw introspection of any BAPI function module")
    ap.add_argument("--all",  action="store_true", help="introspect + diff every definition")
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if any error-severity finding is reported")
    ap.add_argument("--save", action="store_true",
                    help="cache live introspection to scaffolder/introspections/")
    ap.add_argument("--cache-only", action="store_true",
                    help="never call the live S/4 — use scaffolder/introspections/ only")
    ap.add_argument("--print-signature", action="store_true",
                    help="print the live parameter+struct dump in addition to findings")
    ap.add_argument("--secret-id", default=DEFAULT_SECRET_ID,
                    help=f"AWS Secrets Manager secret id (default: {DEFAULT_SECRET_ID})")
    # Direct connection override (when not using AWS secret)
    ap.add_argument("--ashost", help="SAP application server host")
    ap.add_argument("--sysnr",  help="SAP system number")
    ap.add_argument("--client", help="SAP client")
    ap.add_argument("--user",   help="SAP user")
    ap.add_argument("--passwd", help="SAP password")
    ap.add_argument("--lang",   help="SAP login language (default EN)")
    args = ap.parse_args(argv)

    if args.bapi:
        return cmd_bapi(args.bapi, args)
    if args.all:
        return cmd_all(args)
    if args.object:
        conn = None if args.cache_only else _open_connection(args)
        try:
            return cmd_object(args.object, args, conn=conn)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
