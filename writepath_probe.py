#!/usr/bin/env python
"""
writepath_probe.py — find out which "load lanes" into S/4 are already active.

A migration writes into S/4 through one of three SAP-shipped channels:
  1. IDoc inbound   (HTTP POST to /sap/bc/idoc_xml)        — the headless lane
  2. Migration Cockpit (OData service CA_DATA_MIGRATION_SRV) — the bulk-data lane
  3. Transport import  (tp on the S/4 host, needs SSH/OS access) — the code/config lane

This probe checks each one against your live S/4 and prints a plain-English
verdict so we know the easiest lane to prove first.

Run:
    $env:M4H_TARGET_PASSWD = "Parupalliajayteja@2020"
    python writepath_probe.py
"""
from __future__ import annotations
import json
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("SAPNWRFC_HOME", str(ROOT / "sapnwrfc"))


def tcp_open(host: str, port: int, timeout: float = 5.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def main() -> int:
    # Defaults for typical SAP CAL configurations
    host = "35.168.102.2"
    pub = "35.168.102.2"
    user = "MIGRATE_ADMI"
    target_client = "100"
    target_sysnr = "00"

    # Read the live target from connections.json so this tracks whatever appliance
    # is current (a fresh CAL box gets a new IP) — fall back to the defaults above.
    try:
        conns = json.loads((ROOT / "connections.json").read_text())
        t = conns.get("lift_and_shift_target", {})
        host = (t.get("target_ashost") or t.get("target_public_ip") or host).strip()
        pub = (t.get("target_public_ip") or host).strip()
        user = t.get("target_user", user)
        target_client = t.get("target_client", target_client)
        target_sysnr = t.get("target_sysnr", target_sysnr)
    except Exception:
        pass  # Using hardcoded network fallbacks above

    pw = os.environ.get("M4H_TARGET_PASSWD")
    if not pw:
        print("ERROR: set $env:M4H_TARGET_PASSWD first"); return 2

    print(f"Probing S/4 target: {host} (user {user})\n")
    verdict = {}

    # ── Lane 3: transport import needs SSH (port 22) to the S/4 OS ───────────
    ssh = tcp_open(pub, 22) or tcp_open(host, 22)
    verdict["transport (tp via SSH)"] = (
        "READY-ish — SSH port open; needs OS user + STMS route" if ssh
        else "BLOCKED — no SSH (port 22) to S/4 host; transports stay manual")

    # ── HTTP lanes (IDoc + Migration Cockpit) over HTTPS 44300 ───────────────
    try:
        import requests
        from requests.auth import HTTPBasicAuth
        import urllib3
        urllib3.disable_warnings()
        sess = requests.Session()
        sess.auth = HTTPBasicAuth(user, pw)
        sess.verify = False

        base = f"https://{host}:44300"

        def _reason(resp):
            """Pull SAP's human reason out of the HTML/XML error body."""
            import re as _re
            txt = resp.text or ""
            m = _re.search(r"<h1[^>]*>(.*?)</h1>", txt, _re.I | _re.S) or \
                _re.search(r"<title>(.*?)</title>", txt, _re.I | _re.S) or \
                _re.search(r"(not active|not authorized|cannot be reached|forbidden|inactive)", txt, _re.I)
            return _re.sub(r"\s+", " ", (m.group(1) if m and m.lastindex else txt[:200])).strip()[:160]

        # Lane 2: Migration Cockpit OData metadata
        try:
            r = sess.get(f"{base}/sap/opu/odata/sap/CA_DATA_MIGRATION_SRV/$metadata",
                         params={"sap-client": target_client}, timeout=20)
            if r.status_code == 200:
                verdict["migration cockpit (OData)"] = "READY — published & authorized (200)"
            else:
                verdict["migration cockpit (OData)"] = f"HTTP {r.status_code} — reason: {_reason(r)}"
        except Exception as e:
            verdict["migration cockpit (OData)"] = f"UNREACHABLE — {type(e).__name__}"

        # Lane 1: IDoc inbound endpoint
        try:
            r = sess.get(f"{base}/sap/bc/idoc_xml", params={"sap-client": target_client}, timeout=20)
            if r.status_code == 404:
                verdict["idoc inbound (HTTP)"] = "SETUP — /sap/bc/idoc_xml not active (404); activate in SICF"
            elif r.status_code == 200:
                verdict["idoc inbound (HTTP)"] = "READY — endpoint live (200)"
            else:
                verdict["idoc inbound (HTTP)"] = f"HTTP {r.status_code} — reason: {_reason(r)}"
        except Exception as e:
            verdict["idoc inbound (HTTP)"] = f"UNREACHABLE — {type(e).__name__}"

    except ImportError:
        verdict["migration cockpit (OData)"] = "skipped — 'requests' not installed (pip install requests)"
        verdict["idoc inbound (HTTP)"] = "skipped — 'requests' not installed"

    # ── RFC sanity: confirm we can read on the target (proves login + base) ──
    try:
        from pyrfc import Connection
        c = Connection(ashost=host, sysnr=target_sysnr, client=target_client,
                       user=user, passwd=pw, lang="EN")
        info = c.call("RFC_SYSTEM_INFO")["RFCSI_EXPORT"]
        verdict["rfc login"] = f"OK — {info['RFCSYSID']} release {info['RFCSAPRL']}"
        c.close()
    except Exception as e:
        verdict["rfc login"] = f"FAIL — {type(e).__name__}: {str(e)[:80]}"

    print("=== S/4 WRITE-PATH READINESS ===")
    for lane, v in verdict.items():
        print(f"  {lane:28}: {v}")
    print("\nEasiest lane to prove first = whichever says READY with the fewest words after it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# #!/usr/bin/env python
# """
# writepath_probe.py — find out which "load lanes" into S/4 are already active.

# A migration writes into S/4 through one of three SAP-shipped channels:
#   1. IDoc inbound   (HTTP POST to /sap/bc/idoc_xml)        — the headless lane
#   2. Migration Cockpit (OData service CA_DATA_MIGRATION_SRV) — the bulk-data lane
#   3. Transport import  (tp on the S/4 host, needs SSH/OS access) — the code/config lane

# This probe checks each one against your live S/4 and prints a plain-English
# verdict so we know the easiest lane to prove first.

# Run:
#     $env:M4H_TARGET_PASSWD = "Parupalliajayteja@2020"
#     python writepath_probe.py
# """
# from __future__ import annotations
# import json
# import os
# import socket
# import sys
# from pathlib import Path

# ROOT = Path(__file__).resolve().parent
# os.environ.setdefault("SAPNWRFC_HOME", str(ROOT / "sapnwrfc"))


# def tcp_open(host: str, port: int, timeout: float = 5.0) -> bool:
#     try:
#         with socket.create_connection((host, port), timeout=timeout):
#             return True
#     except Exception:
#         return False


# def main() -> int:
#     conns = json.loads((ROOT / "connections.json").read_text())
#     t = conns["lift_and_shift_target"]
#     host = t["target_ashost"]                      # vhcals4hci.dummy.nodomain
#     pub = t.get("target_public_ip", host)
#     user = t.get("target_user", "MIGRATE_ADMI")
#     pw = os.environ.get("M4H_TARGET_PASSWD")
#     if not pw:
#         print("ERROR: set $env:M4H_TARGET_PASSWD first"); return 2

#     print(f"Probing S/4 target: {host}  (user {user})\n")
#     verdict = {}

#     # ── Lane 3: transport import needs SSH (port 22) to the S/4 OS ───────────
#     ssh = tcp_open(pub, 22) or tcp_open(host, 22)
#     verdict["transport (tp via SSH)"] = (
#         "READY-ish — SSH port open; needs OS user + STMS route" if ssh
#         else "BLOCKED — no SSH (port 22) to S/4 host; transports stay manual")

#     # ── HTTP lanes (IDoc + Migration Cockpit) over HTTPS 44300 ───────────────
#     try:
#         import requests
#         from requests.auth import HTTPBasicAuth
#         import urllib3
#         urllib3.disable_warnings()
#         sess = requests.Session()
#         sess.auth = HTTPBasicAuth(user, pw)
#         sess.verify = False

#         base = f"https://{host}:44300"

#         def _reason(resp):
#             """Pull SAP's human reason out of the HTML/XML error body."""
#             import re as _re
#             txt = resp.text or ""
#             m = _re.search(r"<h1[^>]*>(.*?)</h1>", txt, _re.I | _re.S) or \
#                 _re.search(r"<title>(.*?)</title>", txt, _re.I | _re.S) or \
#                 _re.search(r"(not active|not authorized|cannot be reached|forbidden|inactive)", txt, _re.I)
#             return _re.sub(r"\s+", " ", (m.group(1) if m and m.lastindex else txt[:200])).strip()[:160]

#         # Lane 2: Migration Cockpit OData metadata
#         try:
#             r = sess.get(f"{base}/sap/opu/odata/sap/CA_DATA_MIGRATION_SRV/$metadata",
#                          params={"sap-client": t["target_client"]}, timeout=20)
#             if r.status_code == 200:
#                 verdict["migration cockpit (OData)"] = "READY — published & authorized (200)"
#             else:
#                 verdict["migration cockpit (OData)"] = f"HTTP {r.status_code} — reason: {_reason(r)}"
#         except Exception as e:
#             verdict["migration cockpit (OData)"] = f"UNREACHABLE — {type(e).__name__}"

#         # Lane 1: IDoc inbound endpoint
#         try:
#             r = sess.get(f"{base}/sap/bc/idoc_xml", params={"sap-client": t["target_client"]}, timeout=20)
#             if r.status_code == 404:
#                 verdict["idoc inbound (HTTP)"] = "SETUP — /sap/bc/idoc_xml not active (404); activate in SICF"
#             elif r.status_code == 200:
#                 verdict["idoc inbound (HTTP)"] = "READY — endpoint live (200)"
#             else:
#                 verdict["idoc inbound (HTTP)"] = f"HTTP {r.status_code} — reason: {_reason(r)}"
#         except Exception as e:
#             verdict["idoc inbound (HTTP)"] = f"UNREACHABLE — {type(e).__name__}"

#     except ImportError:
#         verdict["migration cockpit (OData)"] = "skipped — 'requests' not installed (pip install requests)"
#         verdict["idoc inbound (HTTP)"] = "skipped — 'requests' not installed"

#     # ── RFC sanity: confirm we can read on the target (proves login + base) ──
#     try:
#         from pyrfc import Connection
#         c = Connection(ashost=host, sysnr=t["target_sysnr"], client=t["target_client"],
#                        user=user, passwd=pw, lang="EN")
#         info = c.call("RFC_SYSTEM_INFO")["RFCSI_EXPORT"]
#         verdict["rfc login"] = f"OK — {info['RFCSYSID']} release {info['RFCSAPRL']}"
#         c.close()
#     except Exception as e:
#         verdict["rfc login"] = f"FAIL — {type(e).__name__}: {str(e)[:80]}"

#     print("=== S/4 WRITE-PATH READINESS ===")
#     for lane, v in verdict.items():
#         print(f"  {lane:28}: {v}")
#     print("\nEasiest lane to prove first = whichever says READY with the fewest words after it.")
#     return 0


# if __name__ == "__main__":
#     sys.exit(main())
