#!/usr/bin/env python
"""
idoc_setup_probe.py — read what's needed to post a test IDoc into S/4.

Read-only. Lists:
  1. The target's own logical system name (the "address" IDocs are sent to).
  2. Existing INBOUND partner profiles (table EDP21) + their message types.
     If any exist, we can craft an IDoc that matches one and it will POST
     cleanly. If none exist, we'll create a minimal one (separate step).

Run:
    $env:M4H_TARGET_PASSWD = "Parupallitejaajay#92"
    python idoc_setup_probe.py
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("SAPNWRFC_HOME", str(ROOT / "sapnwrfc"))


def read_table(c, table, fields, where="", rows=50):
    opts = [{"TEXT": where}] if where else []
    res = c.call("RFC_READ_TABLE", QUERY_TABLE=table, DELIMITER="|",
                 OPTIONS=opts, FIELDS=[{"FIELDNAME": f} for f in fields], ROWCOUNT=rows)
    out = []
    for r in res.get("DATA", []):
        out.append(dict(zip(fields, [p.strip() for p in r["WA"].split("|")])))
    return out


def main() -> int:
    conns = json.loads((ROOT / "connections.json").read_text())
    t = conns["lift_and_shift_target"]
    pw = os.environ.get("M4H_TARGET_PASSWD")
    if not pw:
        print("ERROR: set $env:M4H_TARGET_PASSWD first"); return 2
    from pyrfc import Connection
    c = Connection(ashost=t["target_ashost"], sysnr=t["target_sysnr"],
                   client=t["target_client"], user=t["target_user"], passwd=pw, lang="EN")

    # 1. Own logical system for this client
    print("=== Own logical system (IDoc receiver address) ===")
    try:
        logsys = read_table(c, "T000", ["MANDT", "LOGSYS"],
                            where=f"MANDT = '{t['target_client']}'", rows=1)
        own = logsys[0]["LOGSYS"] if logsys else "(none set)"
        print(f"  client {t['target_client']} logical system = {own}")
    except Exception as e:
        own = ""
        print(f"  could not read T000: {type(e).__name__}: {str(e)[:90]}")

    # 2. Existing inbound partner profiles
    print("\n=== Inbound partner profiles already configured (EDP21) ===")
    try:
        prof = read_table(c, "EDP21", ["RCVPRN", "RCVPRT", "MESTYP"], rows=100)
        if not prof:
            print("  NONE — no inbound partner profiles exist yet.")
        else:
            # group by message type for readability
            seen = []
            for p in prof:
                key = (p["RCVPRN"], p["RCVPRT"], p["MESTYP"])
                if key not in seen:
                    seen.append(key)
            for prn, prt, mes in seen[:40]:
                print(f"  partner={prn:<12} type={prt:<3} message_type={mes}")
            print(f"  ({len(seen)} distinct inbound profiles)")
    except Exception as e:
        print(f"  could not read EDP21: {type(e).__name__}: {str(e)[:90]}")

    # 3. Suggest a candidate (a simple, commonly-present message type)
    print("\n=== VERDICT ===")
    try:
        simple = [s for s in seen if s[2] in ("FLIGHTBOOKING_CREATEFROMDAT",
                                              "MATMAS", "DEBMAS", "CREMAS", "COND_A",
                                              "EXCHANGE_RATE", "SYNCH")]
        if simple:
            print(f"  Good candidate(s) we can post against: {simple[:5]}")
            print("  -> tell me and I'll craft + POST a matching IDoc, then verify it in S/4.")
        elif seen:
            print(f"  Profiles exist; we can target one of: {seen[:5]}")
            print("  -> tell me and I'll craft an IDoc for one of these.")
        else:
            print("  No inbound profiles. Next step: create one minimal partner profile")
            print("  (I can do it over RFC with a function module, or 1 step in WE20).")
    except NameError:
        pass

    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
