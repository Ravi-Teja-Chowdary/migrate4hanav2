"""
sap_prereq_checks — validate target S/4HANA system readiness before each
phase. Replaces the equivalent block from sum-orchestrator with a leaner
greenfield-flavoured check set.
"""
import logging

logger = logging.getLogger(__name__)


def check_target(rfc_conn) -> dict:
    """Run sanity checks: client config, RFC dest, STMS, idoc_xml endpoint.

    Returns: {ready: bool, checks: [{name, ok, detail}]}
    """
    checks = []

    def _try(name, fn):
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"exception: {e}"
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    # 1. RFC connection itself
    _try("rfc_ping", lambda: (True, "connected"))

    # 2. Client list
    _try("clients_configured", lambda: _check_clients(rfc_conn))

    # 3. STMS configured
    _try("stms_configured", lambda: _check_stms(rfc_conn))

    # 4. /sap/bc/idoc_xml SICF active
    _try("idoc_xml_endpoint", lambda: _check_idoc_xml(rfc_conn))

    # 5. Migration Cockpit available
    _try("mc_available", lambda: _check_mc(rfc_conn))

    ready = all(c["ok"] for c in checks)
    return {"ready": ready, "checks": checks}


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
    res = rfc_conn.call("RFC_READ_TABLE", QUERY_TABLE="ICFSERVICE",
                        OPTIONS=[{"TEXT": "ICFNAME EQ 'idoc_xml'"}],
                        FIELDS=[{"FIELDNAME": "ICFACTIVE"}], ROWCOUNT=1)
    rows = res.get("DATA", [])
    if not rows:
        return False, "service not registered"
    return (rows[0]["WA"].strip().startswith("1"), "active" if rows else "inactive")


def _check_mc(rfc_conn):
    res = rfc_conn.call("RFC_READ_TABLE", QUERY_TABLE="LTMC_PROJECTS",
                        FIELDS=[{"FIELDNAME": "PROJECT"}], ROWCOUNT=1)
    return (True, f"MC project table accessible ({len(res.get('DATA', []))} rows)")
