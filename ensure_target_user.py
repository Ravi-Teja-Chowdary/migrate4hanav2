#!/usr/bin/env python
"""
ensure_target_user.py — guarantee the S/4 target user (MIGRATE_ADMI) exists and
is usable over RFC, using a working admin account (SAP*).

On a BRAND-NEW CAL appliance the target user does not exist yet — fix_migrate_admin.py
only *changes* an existing user, so it fails with "01 124: User does not exist".
This script CREATES it if missing (or repairs it if present), sets it to a Service
user with the productive password, and assigns SAP_ALL + SAP_NEW so the rest of the
setup (and the migration) has full authority. Idempotent — safe to re-run.

Env:
    M4H_ADMIN_PASSWD  — password for the admin account (SAP*), e.g. CAL master pw
    M4H_TARGET_PASSWD — password to set on the target user (MIGRATE_ADMI)
    M4H_ADMIN_USER    — admin account to log on with (default SAP*)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("SAPNWRFC_HOME", str(ROOT / "sapnwrfc"))


def _errs(res):
    return [m for m in res.get("RETURN", []) if m.get("TYPE") in ("E", "A")]


def main() -> int:
    conns = json.loads((ROOT / "connections.json").read_text())
    t = conns["lift_and_shift_target"]
    host = t.get("target_ashost")
    sysnr = str(t.get("target_sysnr", "00"))
    client = str(t.get("target_client", "100"))
    user = t.get("target_user", "MIGRATE_ADMI")

    admin_user = os.environ.get("M4H_ADMIN_USER", "SAP*")
    admin_pw = os.environ.get("M4H_ADMIN_PASSWD")
    new_pw = os.environ.get("M4H_TARGET_PASSWD")
    if not admin_pw or not new_pw:
        print("ERROR: set M4H_ADMIN_PASSWD (admin/SAP* pw) and M4H_TARGET_PASSWD")
        return 2

    from pyrfc import Connection
    c = Connection(ashost=host, sysnr=sysnr, client=client,
                   user=admin_user, passwd=admin_pw, lang="EN")
    print(f"connected as {admin_user} -> {host} client {client}")

    # 1. Does the target user exist?
    det = c.call("BAPI_USER_GET_DETAIL", USERNAME=user)
    exists = not any(m.get("ID") == "01" and m.get("NUMBER") == "124"
                     for m in det.get("RETURN", []))
    print(f"{user} exists: {exists}")

    # 2. Create (if missing) or repair (Service type + password)
    if not exists:
        res = c.call("BAPI_USER_CREATE1", USERNAME=user,
                     LOGONDATA={"USTYP": "S"},
                     PASSWORD={"BAPIPWD": new_pw},
                     ADDRESS={"LASTNAME": "Migration"})
        e = _errs(res)
        if e:
            print("  CREATE errors:", [m.get("MESSAGE") for m in e])
            c.call("BAPI_TRANSACTION_ROLLBACK"); c.close(); return 1
        print(f"  created {user} as Service user")
    else:
        try:
            c.call("BAPI_USER_UNLOCK", USERNAME=user)
        except Exception:
            pass
        res = c.call("BAPI_USER_CHANGE", USERNAME=user,
                     LOGONDATA={"USTYP": "S"}, LOGONDATAX={"USTYP": "X"},
                     PASSWORD={"BAPIPWD": new_pw}, PASSWORDX={"BAPIPWD": "X"})
        e = _errs(res)
        if e:
            print("  CHANGE errors:", [m.get("MESSAGE") for m in e])
            c.call("BAPI_TRANSACTION_ROLLBACK"); c.close(); return 1
        print(f"  repaired {user} (Service type + password reset)")

    # 3. Assign SAP_ALL + SAP_NEW (preserve any existing profiles)
    det2 = c.call("BAPI_USER_GET_DETAIL", USERNAME=user)
    cur = [{"BAPIPROF": p.get("BAPIPROF", "").strip()}
           for p in det2.get("PROFILES", []) if p.get("BAPIPROF", "").strip()]
    have = {p["BAPIPROF"] for p in cur}
    add = [p for p in ("SAP_ALL", "SAP_NEW") if p not in have]
    if add:
        res = c.call("BAPI_USER_PROFILES_ASSIGN", USERNAME=user,
                     PROFILES=cur + [{"BAPIPROF": p} for p in add])
        e = _errs(res)
        if e:
            print("  PROFILE errors:", [m.get("MESSAGE") for m in e])
            c.call("BAPI_TRANSACTION_ROLLBACK"); c.close(); return 1
        print(f"  assigned profiles {add}")
    else:
        print("  SAP_ALL/SAP_NEW already present")

    c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
    c.close()

    # 4. Verify the target user can actually log on over RFC
    try:
        c2 = Connection(ashost=host, sysnr=sysnr, client=client,
                        user=user, passwd=new_pw, lang="EN")
        i = c2.call("RFC_SYSTEM_INFO")["RFCSI_EXPORT"]
        print(f"SUCCESS — {user} logs on via RFC: {i['RFCSYSID']} rel {i['RFCSAPRL']}")
        c2.close()
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"VERIFY FAILED — {type(e).__name__}: {str(e)[:160]}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
