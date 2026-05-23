#!/usr/bin/env python
"""
fix_migrate_admin.py — make MIGRATE_ADMI usable over RFC.

A freshly-created Dialog user has an *initial* password (SAP forces a change at
first GUI logon), which RFC rejects with RFC_LOGON_FAILURE. This uses a working
admin account (SAP*) to:
  1. set MIGRATE_ADMI's user type to Service ('S') — logs on via RFC *and* GUI,
     password not subject to forced-change,
  2. (re)set its password to a productive value,
so the migration tool can log on over RFC.

Test-appliance note: Service users have a relaxed security posture (password
doesn't expire, multiple logons). Fine for a sandbox migration admin; in
production you'd use a dedicated System/Communication user for RFC and keep a
separate Dialog admin for GUI.

Run (provide the WORKING admin password; new pass defaults to M4H_TARGET_PASSWD):
    python fix_migrate_admin.py --admin-pass "Parupallitejaajay#92"
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("SAPNWRFC_HOME", str(ROOT / "sapnwrfc"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--admin-user", default="SAP*", help="a working admin user")
    ap.add_argument("--admin-pass", required=True, help="that admin's password")
    ap.add_argument("--target-user", default="MIGRATE_ADMI")
    ap.add_argument("--new-pass", default=os.environ.get("M4H_TARGET_PASSWD"),
                    help="productive password to set (default: $M4H_TARGET_PASSWD)")
    ap.add_argument("--user-type", default="S", choices=["S", "A", "B", "C"],
                    help="S=Service (GUI+RFC, no forced change), B=System, A=Dialog")
    args = ap.parse_args()
    if not args.new_pass:
        print("ERROR: provide --new-pass or set $env:M4H_TARGET_PASSWD"); return 2

    conns = json.loads((ROOT / "connections.json").read_text())
    t = conns["lift_and_shift_target"]
    from pyrfc import Connection
    c = Connection(ashost=t["target_ashost"], sysnr=t["target_sysnr"],
                   client=t["target_client"], user=args.admin_user,
                   passwd=args.admin_pass, lang="EN")
    print(f"connected as {args.admin_user}; fixing {args.target_user} ...")

    res = c.call(
        "BAPI_USER_CHANGE",
        USERNAME=args.target_user,
        LOGONDATA={"USTYP": args.user_type},
        LOGONDATAX={"USTYP": "X"},
        PASSWORD={"BAPIPWD": args.new_pass},
        PASSWORDX={"BAPIPWD": "X"},
    )
    print("  BAPI_USER_CHANGE messages:")
    for m in res.get("RETURN", []):
        print(f"    {m.get('TYPE')} {m.get('ID')}{m.get('NUMBER')}: {m.get('MESSAGE')}")
    errs = [m for m in res.get("RETURN", []) if m.get("TYPE") in ("E", "A")]
    if errs:
        print("  -> errors; rolling back, no change committed.")
        c.call("BAPI_TRANSACTION_ROLLBACK")
        c.close()
        return 1
    c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
    print(f"  committed: user type='{args.user_type}', password (re)set.")

    # Read back what actually stuck
    chk = c.call("BAPI_USER_GET_DETAIL", USERNAME=args.target_user)
    ld = chk.get("LOGONDATA", {})
    print(f"  read-back: USTYP={ld.get('USTYP')!r}  "
          f"locks={chk.get('ISLOCKED')}")
    c.close()

    # Verify: open a fresh RFC session AS the target user
    print(f"verifying RFC logon as {args.target_user} ...")
    try:
        c2 = Connection(ashost=t["target_ashost"], sysnr=t["target_sysnr"],
                        client=t["target_client"], user=args.target_user,
                        passwd=args.new_pass, lang="EN")
        info = c2.call("RFC_SYSTEM_INFO")["RFCSI_EXPORT"]
        print(f"  SUCCESS — {args.target_user} logs on via RFC: "
              f"{info['RFCSYSID']} release {info['RFCSAPRL']}")
        c2.close()
    except Exception as e:
        print(f"  STILL FAILING — {type(e).__name__}: {str(e)[:160]}")
        print("  Fallback: log on once in SAP GUI as the user and change the password.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
