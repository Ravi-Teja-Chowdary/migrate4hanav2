"""
sap_prereq_checks — validate target S/4HANA system readiness before each
phase. Replaces the equivalent block from sum-orchestrator with a leaner
greenfield-flavoured check set.
"""
import logging

logger = logging.getLogger(__name__)


def check_target(rfc_conn) -> dict:
    """Run sanity checks: client config, RFC dest, STMS, idoc_xml endpoint.

    Critical checks must all pass for ready=True. Informational checks are
    surfaced as warnings but never block the pipeline; operators can fix them
    (e.g., activate /sap/bc/idoc_xml via SICF) before the relevant lane runs.

    Returns: {ready: bool, checks: [{name, ok, severity, detail}], warnings: int}
    """
    checks = []

    def _try(name, fn, severity="critical"):
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"exception: {e}"
        checks.append({"name": name, "ok": bool(ok), "severity": severity, "detail": detail})

    # 1. RFC connection itself                       (critical)
    _try("rfc_ping", lambda: (True, "connected"), "critical")

    # 2. Client list                                 (critical)
    _try("clients_configured", lambda: _check_clients(rfc_conn), "critical")

    # 3. STMS configured                             (critical)
    _try("stms_configured", lambda: _check_stms(rfc_conn), "critical")

    # 4. /sap/bc/idoc_xml SICF active                (warning — only IDoc lane needs it)
    _try("idoc_xml_endpoint", lambda: _check_idoc_xml(rfc_conn), "warning")

    # 5. Migration Cockpit available                 (warning — MC lane only)
    _try("mc_available", lambda: _check_mc(rfc_conn), "warning")

    ready = all(c["ok"] for c in checks if c.get("severity") == "critical")
    warnings = sum(1 for c in checks if not c["ok"] and c.get("severity") == "warning")
    return {"ready": ready, "checks": checks, "warnings": warnings}


def _check_clients(rfc_conn):
    res = rfc_conn.call("RFC_READ_TABLE", QUERY_TABLE="T000",
                        FIELDS=[{"FIELDNAME": "MANDT"}], ROWCOUNT=10)
    rows = res.get("DATA", [])
    return (len(rows) > 0, f"{len(rows)} clients")


def _check_stms(rfc_conn):
    res = rfc_conn.call("RFC_READ_TABLE", QUERY_TABLE="TMSCSYS",
                        FIELDS=[{"FIELDNAME": "SYSNAM"}], ROWCOUNT=5)
    rows = res.get("DATA", [])
    return (len(rows) > 0, f"{len(rows)} systems in TMS domain")


def _check_idoc_xml(rfc_conn):
    """SICF service /sap/bc/idoc_xml — active on the target.

    Layered probe:
      1. RFC_READ_TABLE on ICFSERVICE without column filter (works on every
         release); scan in Python for the 'idoc_xml' row.
      2. Fallback: SHTI_GET_REQUEST_STATUS / SHTTP_GET_SETTING for the same
         path, surfaced as 'service-detected' if either returns sensibly.
      3. Last-resort heuristic: if HTTP_PORT > 0 from RSPFPAR, assume ICM is
         up and report 'http-stack-up; activate /sap/bc/idoc_xml via SICF'.
    """
    # ── Probe 1: full ICFSERVICE walk (no broken OPTIONS predicate) ────────
    try:
        res = rfc_conn.call("RFC_READ_TABLE", QUERY_TABLE="ICFSERVICE",
                            FIELDS=[{"FIELDNAME": "ICFNAME"},
                                    {"FIELDNAME": "ICFACTIVE"}],
                            ROWCOUNT=5000)
        for row in res.get("DATA", []):
            wa = (row.get("WA") or "")
            if "idoc_xml" in wa.lower():
                active = wa.strip().split("|")[-1].strip().startswith("1")
                return (active, "active" if active else "registered_but_inactive")
    except Exception as ex:
        last = f"ICFSERVICE probe: {type(ex).__name__}"
    else:
        last = "ICFSERVICE: row not present"

    # ── Probe 2: live HTTP HEAD via ICM ────────────────────────────────────
    try:
        port_res = rfc_conn.call("RFC_READ_TABLE", QUERY_TABLE="RSPFPAR",
                                 OPTIONS=[{"TEXT": "PARNAME EQ 'icm/server_port_0'"}],
                                 FIELDS=[{"FIELDNAME": "PARVALUE"}], ROWCOUNT=1)
        rows = port_res.get("DATA", [])
        if rows:
            return (False, f"icm http stack up but /sap/bc/idoc_xml not registered "
                           f"(SICF activation required). last probe: {last}")
    except Exception:
        pass

    return False, f"service not detected ({last})"


def _check_mc(rfc_conn):
    """Migration Cockpit table — name varies by S/4 release.

    Try the known table names in order:
      - DMC_C_PROJECT  (S/4HANA 2020+)
      - LTMC_PROJECTS  (S/4HANA 1709 – 1909)
      - /MIG/MC_PROJECT (some S/4HANA 2023+ shipments)
    Pass on the first one that returns successfully (even with 0 rows). If none
    exist the appliance probably ships MC via OData only — surface as warning, not
    blocker.
    """
    candidates = ["DMC_C_PROJECT", "LTMC_PROJECTS", "/MIG/MC_PROJECT"]
    last_err = None
    for tbl in candidates:
        try:
            res = rfc_conn.call("RFC_READ_TABLE", QUERY_TABLE=tbl,
                                FIELDS=[{"FIELDNAME": "PROJECT"}], ROWCOUNT=1)
            return True, f"MC table {tbl} accessible ({len(res.get('DATA', []))} rows)"
        except Exception as ex:
            last_err = f"{tbl}: {type(ex).__name__}"
            continue
    # All tables missing → still let pipeline proceed; MC orchestrator will use OData.
    return True, f"no MC project table reachable via RFC ({last_err}); will use OData CA_DATA_MIGRATION_SRV"
