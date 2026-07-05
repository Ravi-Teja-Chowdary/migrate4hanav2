"""
connection_validator - Test ECC/S4 connections AND verify SAP authorisations.

PURPOSE
-------
The wizard's "test connections" page must do more than just answer "did the
TCP socket open?" — it must confirm the SAP user has the right authorisation
profile to drive the migration the wizard chose:

  * FULL migration       => needs RFC_READ_TABLE + JOB_OPEN/SUBMIT/CLOSE +
                              create-BAPI auths on the target object set
                              (S_BTCH_JOB, S_TABU_DIS, S_RFC, S_DEVELOP rd).
                              On the target: same plus the per-object
                              S_DATASET / S_TCODE / S_TABU_NAM rows.

  * SELECTIVE migration  => the user picked specific objects; we probe only
                              for those objects' RFC/BAPI auths so a
                              read-only user isn't rejected just because
                              they can't see EVERYTHING.

A failing probe returns a structured list of missing auths the basis team
can paste straight into PFCG. The wizard refuses to advance past page 5
until every required probe passes.

INTERFACE
---------
    res = validate_ecc(creds, migration_type="full")
    res = validate_s4(creds, migration_type="selective",
                       selected_objects=["Customer","Vendor"])
    # res = {
    #   "ok": bool,
    #   "system":         "ECC" | "S4",
    #   "host_reachable": bool,
    #   "login_ok":       bool,
    #   "probes":         [{name, expected, actual, ok, fix_hint}, ...],
    #   "missing_auths":  ["S_RFC: FUGR=SDIF_INTERNAL_TAB", ...],
    #   "recommended_role": "Z_M4H_FULL" | "Z_M4H_SELECTIVE",
    # }

DESIGN
------
- Accepts a `rfc_factory` callable for testing (no pyrfc dependency
  needed by the test fake). Production calls pass a real
  `pyrfc.Connection`-shaped factory.
- Each probe is one RFC call against a function the migration loop
  actually depends on. The probe records the actual response shape
  so the operator can see exactly what came back.
- Authorisation errors (RFC return type 'E' with code 'AUTHORIZATION_FAILED')
  are recognised and translated into PFCG fix hints.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("connection_validator")


def _resolve_host_alias(creds: dict) -> dict:
    """Rewrite user-facing SAP host aliases to their real network target.

    Motivation: laptop-hosted ECC lives on a private VMware host-only IP
    (e.g. 192.168.100.170) which Fargate cannot reach. We tunnel it through
    ngrok (public tcp://…ngrok.io:<random_port>) or a bastion, but the
    wizard user shouldn't have to know that. The api-server task ships an
    env var `M4H_HOST_ALIASES` (JSON: {vm_ip: {ashost, gwhost, gwserv}})
    that this function consults; the wizard sees the VM IP, pyrfc sees the
    tunnel target. If no alias is configured, creds pass through unchanged.

    Keys allowed in an alias entry: ashost, gwhost, gwserv, sysnr. Anything
    else in the entry is ignored. The caller's dict is NOT mutated.
    """
    ashost = (creds.get("ashost") or "").strip()
    if not ashost:
        return creds
    raw = os.environ.get("M4H_HOST_ALIASES", "").strip()
    if not raw:
        return creds
    try:
        alias_map = json.loads(raw)
    except Exception as e:
        logger.warning("M4H_HOST_ALIASES parse failed (%s) — passing creds through", e)
        return creds
    entry = alias_map.get(ashost)
    if not isinstance(entry, dict):
        return creds
    rewritten = dict(creds)
    for k in ("ashost", "gwhost", "gwserv", "sysnr"):
        v = entry.get(k)
        if v:
            rewritten[k] = str(v)
    logger.info(
        "host alias applied: %s -> ashost=%s gwhost=%s gwserv=%s",
        ashost, rewritten.get("ashost"), rewritten.get("gwhost"),
        rewritten.get("gwserv"))
    return rewritten
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


# ─────────────────────────────────────────────────────────────────────────────
# Probe catalog
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Probe:
    name:        str
    rfc_fn:      str
    args:        Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    required_for: Tuple[str, ...] = ("full", "selective")
    fix_hint:    str = ""
    # critical=True  -> must pass; failure blocks the wizard's Next button.
    # critical=False -> reported but informational only; doesn't block.
    #                   Use for probes that confirm something nice-to-have
    #                   (e.g. a read API the migration loop doesn't need).
    critical:    bool = True


# Probes the ECC source must answer. Read-only side; lighter requirements.
_ECC_PROBES_FULL: List[Probe] = [
    Probe("system_info", "RFC_SYSTEM_INFO", {},
          "Read source SID, release, host. Smoke test that the RFC channel works.",
          fix_hint="Grant S_RFC FUGR=SYST + ACTVT=16 in PFCG"),
    Probe("read_t000", "RFC_READ_TABLE",
          {"QUERY_TABLE": "T000", "ROWCOUNT": 1,
           "FIELDS": [{"FIELDNAME": "MANDT"}, {"FIELDNAME": "MTEXT"}]},
          "Read T000 (clients). Confirms the user can read system-level tables.",
          fix_hint="Grant S_TABU_DIS DICBERCLS=&NC& + ACTVT=03"),
    Probe("read_dd02l", "RFC_READ_TABLE",
          {"QUERY_TABLE": "DD02L", "ROWCOUNT": 1,
           "FIELDS": [{"FIELDNAME": "TABNAME"}]},
          "Read DD02L (table catalog). Confirms DDIC read for extract planning.",
          fix_hint="Grant S_TABU_DIS DICBERCLS=DDIC + ACTVT=03"),
    Probe("read_kna1", "RFC_READ_TABLE",
          {"QUERY_TABLE": "KNA1", "ROWCOUNT": 1,
           "FIELDS": [{"FIELDNAME": "KUNNR"}]},
          "Read KNA1 (customer master). Confirms customer-object extract is possible.",
          required_for=("full", "selective"),  # if customer is in the picked set
          fix_hint="Grant S_TABU_DIS DICBERCLS=FK + ACTVT=03"),
    Probe("read_lfa1", "RFC_READ_TABLE",
          {"QUERY_TABLE": "LFA1", "ROWCOUNT": 1,
           "FIELDS": [{"FIELDNAME": "LIFNR"}]},
          "Read LFA1 (vendor master). Confirms vendor-object extract is possible.",
          required_for=("full",),
          fix_hint="Grant S_TABU_DIS DICBERCLS=FK + ACTVT=03"),
    Probe("read_mara", "RFC_READ_TABLE",
          {"QUERY_TABLE": "MARA", "ROWCOUNT": 1,
           "FIELDS": [{"FIELDNAME": "MATNR"}]},
          "Read MARA (material master). Confirms material-object extract is possible.",
          required_for=("full",),
          fix_hint="Grant S_TABU_DIS DICBERCLS=MM + ACTVT=03"),
]


# Probes the S/4 target must answer. Write-side; heavier requirements.
_S4_PROBES_FULL: List[Probe] = [
    Probe("system_info", "RFC_SYSTEM_INFO", {},
          "Read target SID/release. Confirms basic RFC.",
          fix_hint="Grant S_RFC FUGR=SYST + ACTVT=16"),
    Probe("read_t000", "RFC_READ_TABLE",
          {"QUERY_TABLE": "T000", "ROWCOUNT": 1,
           "FIELDS": [{"FIELDNAME": "MANDT"}]},
          "Read T000 on target. Confirms read on system tables.",
          fix_hint="Grant S_TABU_DIS DICBERCLS=&NC& + ACTVT=03"),
    Probe("read_t001", "RFC_READ_TABLE",
          {"QUERY_TABLE": "T001", "ROWCOUNT": 1,
           "FIELDS": [{"FIELDNAME": "BUKRS"}]},
          "Read T001 (company codes). Anchor discovery uses this.",
          fix_hint="Grant S_TABU_DIS DICBERCLS=FBU + ACTVT=03"),
    Probe("read_t001w", "RFC_READ_TABLE",
          {"QUERY_TABLE": "T001W", "ROWCOUNT": 1,
           "FIELDS": [{"FIELDNAME": "WERKS"}]},
          "Read T001W (plants). Anchor discovery + plant-bound objects.",
          fix_hint="Grant S_TABU_DIS DICBERCLS=&NC& + ACTVT=03"),
    Probe("bapi_call_xbp_job", "BAPI_XBP_JOB_OPEN",
          {"JOBNAME": "M4H_PROBE", "EXTERNAL_USER_NAME": "M4H_PROBE"},
          "Open a background job. Required for spool capture (FAGLB03/MB5B).",
          required_for=("full",),
          # Advisory because spool capture is itself optional on CAL / dev
          # landscapes; the migration loop runs without it (just no auditor
          # spool sealed into the chain). Auditor closes still require it
          # in real prod - the gate alert is the right place to enforce.
          critical=False,
          fix_hint="Grant S_BTCH_JOB + S_BTCH_NAM with JOBGROUP=M4H_*"),
    Probe("bapi_call_currency", "BAPI_EXCHANGERATE_GETLIST",
          {"DATE_FROM": "20260101", "MAX_NUMBER_OF_RECORDS": 1},
          "Read exchange rates. Advisory - the ExchangeRate spine WRITES "
          "via BAPI_EXCHANGERATE_CREATEMULTIPLE; this read probe just "
          "confirms the customising-read surface.",
          # Advisory: the migration uses the CREATE BAPI on write side; the
          # read side runs through RFC_READ_TABLE on TCURR which is already
          # covered by the read_t000 / read_t001 probes above. FU_NOT_FOUND
          # on this read endpoint is common on locked-down S/4 and does NOT
          # block the migration.
          critical=False,
          fix_hint="Grant S_TABU_DIS DICBERCLS=FC + ACTVT=03 (only if you "
                    "plan to use the live read-rates lookup; not required for "
                    "migration)"),
]


# Selective probes: smaller, object-keyed.
_SELECTIVE_PROBES_BY_OBJECT: Dict[str, List[Probe]] = {
    "Customer": [
        Probe("bapi_customer_getlist", "BAPI_CUSTOMER_GETLIST", {"MAXROWS": 1},
              "List one customer to confirm S_TCODE + S_TABU_NAM auths.",
              fix_hint="Grant S_TCODE XD03 + S_TABU_NAM TABLE=KNA1"),
    ],
    "Vendor": [
        Probe("bapi_vendor_getlist", "BAPI_VENDOR_GETLIST", {"MAXROWS": 1},
              "List one vendor to confirm S_TCODE + S_TABU_NAM auths.",
              fix_hint="Grant S_TCODE FK03 + S_TABU_NAM TABLE=LFA1"),
    ],
    "Material": [
        Probe("bapi_material_getlist", "BAPI_MATERIAL_GETLIST",
              {"MAXROWS_RETURNED": 1},
              "List one material to confirm S_TCODE auth.",
              fix_hint="Grant S_TCODE MM03 + S_TABU_DIS DICBERCLS=MM ACTVT=03"),
    ],
    "ExchangeRate": [
        Probe("bapi_exchangerate", "BAPI_EXCHANGERATE_GETLIST",
              {"DATE_FROM": "20260101", "MAX_NUMBER_OF_RECORDS": 1},
              "Read exchange rates. Required for exchange-rate spine.",
              fix_hint="Grant S_TABU_DIS DICBERCLS=FC + ACTVT=03"),
    ],
    # Default for any selective object we don't have a tailored probe for:
    # require read-only access on T000 + system_info as a baseline.
    "__default__": [],
}


# ─────────────────────────────────────────────────────────────────────────────
# Validator
# ─────────────────────────────────────────────────────────────────────────────
RfcFactory = Callable[[Dict[str, Any]], Any]


def _open_connection(creds: dict) -> Any:
    """Default factory: open a real pyrfc.Connection. Tests pass their
    own factory and never reach this code path.

    Windows note: the bundled SAP NW RFC SDK ships with our `sapnwrfc`
    package; importing it sets SAPNWRFC_HOME + PATH so pyrfc finds the
    DLLs. Without this, `from pyrfc import Connection` raises on Windows
    even when the host is fully reachable, which the wizard then surfaces
    as "host unreachable". Linux Lambdas also work — the package no-ops
    when the SDK is already on LD_LIBRARY_PATH.
    """
    try:
        import sapnwrfc  # noqa: F401 - side-effect import: configures DLL paths
    except Exception:
        pass   # not bundled in this env → let pyrfc try with system PATH
    from pyrfc import Connection
    # Server-side alias translation: laptop VM IP → ngrok/bastion target.
    # See _resolve_host_alias docstring for the M4H_HOST_ALIASES env var.
    creds = _resolve_host_alias(creds)
    # pyrfc.Connection() does not tolerate kwargs whose value is None - it
    # passes them straight to the SAP NW RFC SDK which calls .encode() and
    # raises AttributeError. Drop empty/None optionals BEFORE calling.
    raw = {
        "ashost":    creds.get("ashost"),
        "sysnr":     creds.get("sysnr"),
        "client":    creds.get("client"),
        "user":      creds.get("user"),
        "passwd":    creds.get("passwd"),
        "saprouter": creds.get("saprouter"),
        "gwhost":    creds.get("gwhost"),
        "gwserv":    creds.get("gwserv"),
        "lang":      creds.get("lang") or "EN",
    }
    kw = {k: str(v) for k, v in raw.items() if v not in (None, "")}
    # Required: ashost + user + passwd. If anything is missing we'd rather
    # surface a clean error here than let pyrfc throw NoneType.encode.
    for required in ("ashost", "user", "passwd"):
        if required not in kw:
            raise ValueError(
                f"missing required connection field: {required} "
                f"(supplied keys: {sorted(kw)})")
    return Connection(**kw)


def _run_probes(probes: List[Probe], conn: Any) -> Tuple[List[dict], List[str], List[str]]:
    """Run each probe; return (per-probe results, blocking_failures,
    advisory_warnings).

    A blocking failure means a critical probe failed -> the wizard cannot
    advance. An advisory warning is an informational probe that failed
    but does NOT block the migration loop.
    """
    results: List[dict] = []
    blocking: List[str] = []
    advisory: List[str] = []
    for p in probes:
        rec: Dict[str, Any] = {
            "name": p.name, "rfc": p.rfc_fn, "description": p.description,
            "critical": p.critical,
        }
        try:
            resp = conn.call(p.rfc_fn, **p.args)
            ret = resp.get("RETURN") if isinstance(resp, dict) else None
            err_rows = []
            if isinstance(ret, list):
                err_rows = [r for r in ret
                            if (r.get("TYPE") or "").upper() in ("E", "A")]
            elif isinstance(ret, dict):
                if (ret.get("TYPE") or "").upper() in ("E", "A"):
                    err_rows = [ret]
            if err_rows:
                rec["ok"] = False
                rec["error"] = err_rows[0].get("MESSAGE", "")[:200]
                rec["fix_hint"] = p.fix_hint
                rec["error_class"] = "sap_error"
                _route(rec, p, blocking, advisory)
            else:
                rec["ok"] = True
                rec["sample"] = _trim_sample(resp)
        except Exception as e:
            err_str = str(e)
            rec["ok"] = False
            rec["error"] = f"{type(e).__name__}: {err_str[:200]}"
            rec["fix_hint"] = p.fix_hint
            low = err_str.lower()
            # Tell the operator WHICH category they're in. FU_NOT_FOUND
            # means the function module is not released for RFC on this
            # S/4 - not an auth issue, the SAP basis team has to expose it
            # in SE37 / SAP table TFDIR. The MC RFC layer is the same shape.
            if "fu_not_found" in low or "function module" in low:
                rec["error_class"] = "fu_not_found"
                rec["error"] = (rec["error"] +
                                 "  |  hint: this RFC is not exposed on this "
                                 "S/4; basis team would activate it in SE37, "
                                 "but the migration does not require it.")
            elif "authorization" in low or "auth_check_failed" in low:
                rec["error_class"] = "auth_denied"
            elif "rfc_error_communication" in low or "partner not reached" in low:
                rec["error_class"] = "rfc_comm"
            else:
                rec["error_class"] = "unknown"
            _route(rec, p, blocking, advisory)
        results.append(rec)
    return results, blocking, advisory


def _route(rec: dict, p: Probe, blocking: List[str], advisory: List[str]) -> None:
    line = f"{p.name}: {rec.get('error', '')}"
    (blocking if p.critical else advisory).append(line)


def _trim_sample(resp: Any) -> Any:
    """Return a small redacted slice of the response for the UI."""
    if isinstance(resp, dict):
        return {k: (v[:3] if isinstance(v, list) else v)
                for k, v in list(resp.items())[:6]}
    return str(resp)[:200]


def validate_ecc(creds: dict, migration_type: str = "full",
                  selected_objects: Optional[List[str]] = None,
                  rfc_factory: Optional[RfcFactory] = None) -> dict:
    return _validate_system("ECC", creds, migration_type,
                             selected_objects, rfc_factory,
                             full_probes=_ECC_PROBES_FULL)


def validate_s4(creds: dict, migration_type: str = "full",
                 selected_objects: Optional[List[str]] = None,
                 rfc_factory: Optional[RfcFactory] = None) -> dict:
    return _validate_system("S4", creds, migration_type,
                             selected_objects, rfc_factory,
                             full_probes=_S4_PROBES_FULL)


def _validate_system(label: str, creds: dict, migration_type: str,
                      selected_objects: Optional[List[str]],
                      rfc_factory: Optional[RfcFactory],
                      full_probes: List[Probe]) -> dict:
    out = {
        "ok": False, "system": label,
        "host_reachable": False, "login_ok": False,
        "probes": [], "missing_auths": [],
        "recommended_role": f"Z_M4H_{migration_type.upper()}",
    }
    factory = rfc_factory or _open_connection
    try:
        conn = factory(creds)
        out["host_reachable"] = True
        out["login_ok"] = True
    except Exception as e:
        msg = f"{type(e).__name__}: {str(e)[:300]}"
        out["error"] = msg
        # Classify the failure so the UI can render the right message instead
        # of always saying "host unreachable" - which is misleading when
        # the host IS reachable but the credentials or the SDK are wrong.
        low = msg.lower()
        if any(s in low for s in ("name or password is incorrect",
                                    "user is locked",
                                    "password logon no longer possible",
                                    "rfc_error_logon_failure")):
            out["host_reachable"] = True
            out["login_ok"] = False
            out["failure_class"] = "login_failed"
        elif any(s in low for s in ("dll", "sapnwrfc", "could not be loaded",
                                     "library", "no module named 'pyrfc'")):
            out["failure_class"] = "sdk_missing"
            out["error"] = (msg + "  |  hint: SAP NW RFC SDK not loaded; "
                             "on Windows ensure sapnwrfc package + DLLs are "
                             "installed, or run inside the Lambda where they "
                             "are bundled")
        elif "attributeerror" in low and "encode" in low:
            # Classic pyrfc symptom for a None or wrong-typed connection
            # field. Don't lie and say the host is unreachable.
            out["failure_class"] = "bad_input"
            out["error"] = (msg + "  |  hint: one of the connection fields "
                             "is empty or not a string. Re-check ashost / "
                             "sysnr / client / user / passwd are all filled in.")
        elif "missing required connection field" in low:
            out["failure_class"] = "bad_input"
        elif any(s in low for s in ("timed out", "connection refused",
                                     "connection reset", "host not found",
                                     "no route to host", "network is unreachable",
                                     "partner not reached")):
            out["failure_class"] = "host_unreachable"
        else:
            out["failure_class"] = "unknown"
        return out

    try:
        # Pick the probe list based on migration_type and selected objects.
        if migration_type == "selective" and selected_objects:
            probes: List[Probe] = []
            # Always do the bedrock baseline (system_info + T000)
            probes.append(full_probes[0])
            if len(full_probes) > 1:
                probes.append(full_probes[1])
            for obj in selected_objects:
                probes.extend(_SELECTIVE_PROBES_BY_OBJECT.get(
                    obj, _SELECTIVE_PROBES_BY_OBJECT["__default__"]))
        else:
            probes = [p for p in full_probes
                       if migration_type in p.required_for]
        results, blocking, advisory = _run_probes(probes, conn)
        out["probes"] = results
        out["missing_auths"]      = blocking   # blocking (back-compat key)
        out["advisory_warnings"]  = advisory   # informational only
        # ok=True iff no CRITICAL probe failed. Advisory failures are
        # surfaced in the UI but do not block the wizard's Next button.
        out["ok"] = len(blocking) == 0
    finally:
        try:
            if hasattr(conn, "close"):
                conn.close()
        except Exception:
            pass
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Self-test (no SAP)
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("connection_validator  self-test")
    print("=" * 70)

    class FakeConn:
        """Returns canned RFC responses. The optional `deny` set names RFC
        functions that should fail with an AUTHORIZATION_FAILED row."""
        def __init__(self, deny=None, dead_host=False):
            self.deny = set(deny or [])
            self.dead_host = dead_host

        def call(self, fn, **kw):
            if self.dead_host:
                raise ConnectionError("host unreachable")
            if fn in self.deny:
                return {"RETURN": [{"TYPE": "E",
                                      "MESSAGE": f"User has no auth for {fn}"}]}
            if fn == "RFC_SYSTEM_INFO":
                return {"RFCSI_EXPORT": {"RFCSYSID": "S4D", "RFCSAPRL": "S4HANA2023"}}
            if fn == "RFC_READ_TABLE":
                return {"DATA": [{"WA": "100|ACME Inc"}], "FIELDS": kw.get("FIELDS", [])}
            if fn == "BAPI_XBP_JOB_OPEN":
                return {"JOBNAME": kw["JOBNAME"], "JOBCOUNT": "07561234"}
            if fn == "BAPI_EXCHANGERATE_GETLIST":
                return {"EXCH_RATE_LIST": [{"FROM_CURR": "USD", "TO_CURRNCY": "EUR"}]}
            if fn.startswith("BAPI_CUSTOMER") or fn.startswith("BAPI_VENDOR") \
                    or fn.startswith("BAPI_MATERIAL"):
                return {"RETURN": [], "ADDRESSES": [], "EXTENSIONIN": []}
            return {}

        def close(self): pass

    def factory(creds, conn=None):
        return conn

    # ── 1) Happy path ECC, full migration
    conn = FakeConn()
    res = validate_ecc({"ashost": "x"}, migration_type="full",
                        rfc_factory=lambda c: conn)
    print(f"\n[1] ECC full: ok={res['ok']} probes={len(res['probes'])} "
          f"missing={len(res['missing_auths'])}")
    assert res["ok"]
    assert all(p["ok"] for p in res["probes"])

    # ── 2) ECC missing one auth (RFC_READ_TABLE on KNA1)
    # We deny RFC_READ_TABLE entirely -> all T000/DD02L/KNA1/LFA1/MARA fail.
    conn = FakeConn(deny=["RFC_READ_TABLE"])
    res = validate_ecc({"ashost": "x"}, migration_type="full",
                        rfc_factory=lambda c: conn)
    assert not res["ok"]
    assert len(res["missing_auths"]) >= 1
    print(f"[2] ECC denied RFC_READ_TABLE: ok={res['ok']} "
          f"missing={len(res['missing_auths'])}")
    print(f"    sample missing: {res['missing_auths'][0][:80]}")

    # ── 3) S4 full happy path
    conn = FakeConn()
    res = validate_s4({"ashost": "y"}, migration_type="full",
                       rfc_factory=lambda c: conn)
    print(f"[3] S4 full: ok={res['ok']} probes={len(res['probes'])}")
    assert res["ok"]

    # ── 4) S4 selective, only Customer
    conn = FakeConn()
    res = validate_s4({"ashost": "y"}, migration_type="selective",
                       selected_objects=["Customer"],
                       rfc_factory=lambda c: conn)
    print(f"[4] S4 selective (Customer): ok={res['ok']} probes={len(res['probes'])}")
    assert res["ok"]
    assert any(p["name"] == "bapi_customer_getlist" for p in res["probes"])
    # XBP probe should NOT fire (full-only)
    assert not any(p["name"] == "bapi_call_xbp_job" for p in res["probes"])

    # ── 5) S4 full but XBP job auth denied -- XBP is now ADVISORY so this
    # should still produce ok=True with a warning in advisory_warnings.
    conn = FakeConn(deny=["BAPI_XBP_JOB_OPEN"])
    res = validate_s4({"ashost": "y"}, migration_type="full",
                       rfc_factory=lambda c: conn)
    assert res["ok"]   # advisory failure does NOT block
    assert res["advisory_warnings"]
    xbp = [p for p in res["probes"] if p["name"] == "bapi_call_xbp_job"][0]
    assert not xbp["ok"] and xbp["critical"] is False
    print(f"[5] S4 XBP advisory: ok={res['ok']} advisory={len(res['advisory_warnings'])} critical=False")

    # ── 6) Dead host
    res = validate_s4({"ashost": "z"}, migration_type="full",
                       rfc_factory=lambda c: FakeConn(dead_host=True).call("RFC_SYSTEM_INFO"))
    assert not res["host_reachable"]
    print(f"[6] dead host: host_reachable={res['host_reachable']} "
          f"err={res.get('error','')[:60]}")

    # ── 7) Recommended role is per migration type
    conn = FakeConn()
    res = validate_ecc({"ashost": "x"}, migration_type="selective",
                        selected_objects=["Customer"],
                        rfc_factory=lambda c: conn)
    assert res["recommended_role"] == "Z_M4H_SELECTIVE"
    print(f"[7] selective role: {res['recommended_role']}")

    print("\nOK  connection_validator: probes both systems, captures "
          "per-probe failures + PFCG hints, scopes selective probes to "
          "selected objects, refuses 'ok' when any required probe fails.")
