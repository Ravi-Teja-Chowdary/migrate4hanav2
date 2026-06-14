#!/usr/bin/env python
"""
recover_access.py — diagnose + unlock S/4 users, and restore MIGRATE_ADMI to a
Dialog user so SAP GUI logon works again.

Connects over RFC (whichever account still works), reports lock status for the
key admin users, unlocks them, and optionally converts MIGRATE_ADMI back to a
Dialog user.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("SAPNWRFC_HOME", str(ROOT / "sapnwrfc"))
from pyrfc import Connection

# Parse the configuration file dynamically
conns = json.loads((ROOT / "connections.json").read_text())

# Robust Fallback Check: Safely catch either connection structure variant
if "lift_and_shift_target" in conns:
    t = conns["lift_and_shift_target"]
    HOST = t.get("target_ashost") or t.get("ashost")
    SYSNR = str(t.get("target_sysnr") or t.get("sysnr", "00"))
    CLIENT = str(t.get("target_client") or t.get("client", "100"))
elif "ecc" in conns:
    t = conns["ecc"]
    HOST = t.get("ashost")
    SYSNR = str(t.get("sysnr", "00"))
    CLIENT = str(t.get("client", "100"))
else:
    # Manual extraction fallback if structure is top-level flat
    HOST = conns.get("target_ashost") or conns.get("ashost")
    SYSNR = str(conns.get("target_sysnr") or conns.get("sysnr", "00"))
    CLIENT = str(conns.get("target_client") or conns.get("client", "100"))

# Ensure no hidden whitespace or trailing line breaks ruin connection properties
HOST = HOST.strip() if HOST else ""
NEWPW = os.environ.get("M4H_TARGET_PASSWD", "Parupalliajayteja@2020")
ADMINPW = "Parupallitejaajay#92"
USERS = ["SAP*", "MIGRATE_ADMI", "DDIC"]


def connect():
    for user, pw in [("MIGRATE_ADMI", NEWPW), ("SAP*", ADMINPW), ("DDIC", ADMINPW)]:
        try:
            # Using absolute lowercase standard connection tags required by pyrfc core
            c = Connection(ashost=HOST, sysnr=SYSNR, client=CLIENT, user=user, passwd=pw, lang="EN")
            print(f"connected over RFC as {user}")
            return c, user
        except Exception as e:
            print(f"   cannot connect as {user}: {getattr(e, 'key', type(e).__name__)}")
    return None, None


def status(c):
    print("\n=== user status (UFLAG: 0=ok, 64=admin-lock, 128=failed-logon-lock, 192=both) ===")
    for u in USERS:
        try:
            d = c.call("BAPI_USER_GET_DETAIL", USERNAME=u)
            ld = d.get("LOGONDATA", {})
            isl = d.get("ISLOCKED", {})
            print(f"  {u:<14} USTYP={ld.get('USTYP')!r}  locks={isl}")
        except Exception as e:
            print(f"  {u:<14} -> {getattr(e, 'key', type(e).__name__)}")


def unlock_all(c):
    print("\n=== unlocking ===")
    for u in USERS:
        try:
            r = c.call("BAPI_USER_UNLOCK", USERNAME=u)
            err = [m.get("MESSAGE") for m in r.get("RETURN", []) if m.get("TYPE") in ("E", "A")]
            print(f"  {u:<14} {'unlocked' if not err else err}")
        except Exception as e:
            print(f"  {u:<14} -> {getattr(e, 'key', type(e).__name__)}: {str(e)[:80]}")
    c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")


def make_dialog(c, user, start_pw):
    """Convert a user to Dialog (A) and set a known starting password so SAP GUI
    logon works. The password is admin-set => 'initial' => first GUI logon forces
    a one-time change (unavoidable SAP rule for a GUI-capable user)."""
    print(f"\n=== converting {user} to Dialog (A) for GUI, with known start password ===")
    r = c.call("BAPI_USER_CHANGE", USERNAME=user,
               LOGONDATA={"USTYP": "A"}, LOGONDATAX={"USTYP": "X"},
               PASSWORD={"BAPIPWD": start_pw}, PASSWORDX={"BAPIPWD": "X"})
    err = [m.get("MESSAGE") for m in r.get("RETURN", []) if m.get("TYPE") in ("E", "A")]
    if err:
        print(f"  ERROR: {err}"); c.call("BAPI_TRANSACTION_ROLLBACK"); return
    c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
    print(f"  DONE. {user} is now a Dialog user with start password: {start_pw}")
    print("  --> In SAP GUI, log on (client 100) as user MIGRATE_ADMI with that")
    print("      password; SAP will prompt you to set a NEW password. Set your final")
    print("      one, then tell the tool that new password.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--make-migrate-dialog", action="store_true",
                    help="convert MIGRATE_ADMI back to Dialog (enables GUI; first logon forces pwd change)")
    args = ap.parse_args()

    print(f"Target system metrics derived -> Host: {HOST}, Sysnr: {SYSNR}, Client: {CLIENT}")
    c, who = connect()
    if not c:
        print("\nERROR: no RFC login works. Recovery needs OS-level access (SSH) instead.")
        return 1
    status(c)
    unlock_all(c)
    status(c)
    if args.make_migrate_dialog:
        make_dialog(c, "MIGRATE_ADMI", NEWPW)
    c.close()
    print("\nDone. Try SAP GUI again (see the notes printed by this script).")
    return 0


if __name__ == "__main__":
    sys.exit(main())