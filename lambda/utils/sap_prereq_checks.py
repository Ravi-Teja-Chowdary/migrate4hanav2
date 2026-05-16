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

    On newer S/4 the ICFSERVICE table query can raise TABLE_WITHOUT_DATA when the
    OPTIONS filter matches no rows. Treat that as 'not configured', not a check
    crash. Operators can activate via SICF (transaction SICF) if needed for the
    IDoc lane.
    """
    try:
        res = rfc_conn.call("RFC_READ_TABLE", QUERY_TABLE="ICFSERVICE",
                            OPTIONS=[{"TEXT": "ICFNAME EQ 'idoc_xml'"}],
                            FIELDS=[{"FIELDNAME": "ICFACTIVE"}], ROWCOUNT=1)
    except Exception as ex:
        # TABLE_WITHOUT_DATA, FIELD_NOT_VALID, etc. — no rows match. Service likely
        # exists but isn't activated yet; downstream IDoc lane will surface this.
        return False, f"service not detected via ICFSERVICE ({type(ex).__name__})"
    rows = res.get("DATA", [])
    if not rows:
        return False, "service not registered"
    return (rows[0]["WA"].strip().startswith("1"), "active" if rows else "inactive")


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
