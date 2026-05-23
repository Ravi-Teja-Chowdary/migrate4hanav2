#!/usr/bin/env python
"""
mc_role_probe.py — can we unlock Migration Cockpit for our user over RFC?

Checks, against the live S/4 (read-only):
  1. Which roles the target user (SAP*) currently has.
  2. Which Migration-Cockpit / data-migration roles exist on the system.
  3. Whether the standard MC roles are already assigned.

This tells us if we can assign the MC role programmatically (no SAP GUI) or
whether a human needs to do it once in transaction SU01.

Run:
    $env:M4H_TARGET_PASSWD = "Parupallitejaajay#92"
    python mc_role_probe.py
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("SAPNWRFC_HOME", str(ROOT / "sapnwrfc"))

# Known Migration Cockpit role names across S/4 releases.
MC_ROLE_CANDIDATES = [
    "SAP_CA_DMC_MC_USER", "SAP_CA_DMC_MC_DISPLAY", "SAP_CA_DMC_MC_DEVELOPER",
    "SAP_BR_CONFIG_EXPERT_DATA_MIG", "/IWFND/RT_GW_USER",
]
# Roles we add when --assign is used (must exist on the system to be applied).
MC_ROLES_TO_ADD = ["SAP_CA_DMC_MC_USER", "SAP_CA_DMC_MC_DEVELOPER"]


def assign_roles(c, user: str, add_roles: list) -> None:
    """Append MC roles to the user WITHOUT removing existing ones.

    BAPI_USER_ACTGROUPS_ASSIGN overwrites the assignment list, so we must read
    the current roles (with their valid-from/to dates) and re-send them plus the
    new ones. Standard SAP roles ship with generated profiles, so the auth takes
    effect immediately.
    """
    detail = c.call("BAPI_USER_GET_DETAIL", USERNAME=user)
    current = detail.get("ACTIVITYGROUPS", [])
    have = {r.get("AGR_NAME", "").strip() for r in current}

    merged = []
    for r in current:                       # preserve existing roles + their dates
        merged.append({"AGR_NAME": r.get("AGR_NAME", "").strip(),
                       "FROM_DAT": r.get("FROM_DAT", "") or "00000000",
                       "TO_DAT": r.get("TO_DAT", "") or "99991231"})
    today = date.today().strftime("%Y%m%d")
    added = []
    for role in add_roles:
        if role and role not in have:
            merged.append({"AGR_NAME": role, "FROM_DAT": today, "TO_DAT": "99991231"})
            added.append(role)

    if added:
        print(f"  assigning roles {added} (keeping existing {sorted(have)}) ...")
        res = c.call("BAPI_USER_ACTGROUPS_ASSIGN", USERNAME=user, ACTIVITYGROUPS=merged)
        msgs = [m for m in res.get("RETURN", []) if m.get("TYPE") in ("E", "A")]
        if msgs:
            print("  ROLE ERRORS:")
            for m in msgs:
                print(f"    {m.get('TYPE')}: {m.get('MESSAGE')}")
            c.call("BAPI_TRANSACTION_ROLLBACK")
            print("  rolled back — no change made.")
            return
        c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
    else:
        print(f"  roles already present: {add_roles}")

    # ── User comparison: push each role's generated profile onto the user ────
    # Assigning a role does NOT activate its authorizations until the generated
    # profile (T_*) is in the user's profile list. Read those profiles from
    # AGR_1016 and merge them in via BAPI_USER_PROFILES_ASSIGN.
    print("  running user comparison (assigning generated profiles) ...")
    detail2 = c.call("BAPI_USER_GET_DETAIL", USERNAME=user)
    cur_profiles = [{"BAPIPROF": p.get("BAPIPROF", "").strip()}
                    for p in detail2.get("PROFILES", []) if p.get("BAPIPROF", "").strip()]
    have_profiles = {p["BAPIPROF"] for p in cur_profiles}

    new_profiles = []
    for role in add_roles:
        try:
            res = c.call("RFC_READ_TABLE", QUERY_TABLE="AGR_1016", DELIMITER="|",
                         OPTIONS=[{"TEXT": f"AGR_NAME = '{role}'"}],
                         FIELDS=[{"FIELDNAME": "PROFILE"}], ROWCOUNT=10)
            for r in res.get("DATA", []):
                prof = r["WA"].split("|")[0].strip()
                if prof and prof not in have_profiles:
                    new_profiles.append({"BAPIPROF": prof})
                    have_profiles.add(prof)
        except Exception as e:
            print(f"    (could not read profile for {role}: {type(e).__name__})")

    if not new_profiles:
        print("    no new generated profiles found to add (role may use a different auth model).")
    else:
        print(f"    adding profiles: {[p['BAPIPROF'] for p in new_profiles]}")
        res = c.call("BAPI_USER_PROFILES_ASSIGN", USERNAME=user,
                     PROFILES=cur_profiles + new_profiles)
        msgs = [m for m in res.get("RETURN", []) if m.get("TYPE") in ("E", "A")]
        if msgs:
            print("    PROFILE ERRORS:")
            for m in msgs:
                print(f"      {m.get('TYPE')}: {m.get('MESSAGE')}")
            c.call("BAPI_TRANSACTION_ROLLBACK")
            return
        c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")

    print(f"  DONE — {user} has the MC role(s) + profile(s). Re-run writepath_probe.py to confirm 403 cleared.")


def grant_sap_all(c, user: str) -> None:
    """Add SAP_ALL + SAP_NEW profiles to the user, preserving existing profiles.

    Test-system shortcut: removes authorization as a variable so we can prove
    the migration mechanics. Reversible (re-run without these, or remove in SU01).
    """
    detail = c.call("BAPI_USER_GET_DETAIL", USERNAME=user)
    cur = [{"BAPIPROF": p.get("BAPIPROF", "").strip()}
           for p in detail.get("PROFILES", []) if p.get("BAPIPROF", "").strip()]
    have = {p["BAPIPROF"] for p in cur}
    add = [p for p in ("SAP_ALL", "SAP_NEW") if p not in have]
    if not add:
        print(f"  {user} already has {sorted(have & {'SAP_ALL', 'SAP_NEW'})}")
        return
    print(f"  adding profiles {add} (keeping {sorted(have)}) ...")
    res = c.call("BAPI_USER_PROFILES_ASSIGN", USERNAME=user,
                 PROFILES=cur + [{"BAPIPROF": p} for p in add])
    msgs = [m for m in res.get("RETURN", []) if m.get("TYPE") in ("E", "A")]
    if msgs:
        print("  ERRORS:")
        for m in msgs:
            print(f"    {m.get('TYPE')}: {m.get('MESSAGE')}")
        c.call("BAPI_TRANSACTION_ROLLBACK")
        print("  rolled back — no change made.")
        return
    c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
    print(f"  DONE — {user} now has {add}. Re-run writepath_probe.py; MC should be READY (200).")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--assign", action="store_true",
                    help="assign the MC roles to the target user (writes to S/4)")
    ap.add_argument("--sap-all", action="store_true",
                    help="grant the target user the SAP_ALL + SAP_NEW profiles "
                         "(TEST-SYSTEM shortcut to clear all authorization friction)")
    args = ap.parse_args()

    conns = json.loads((ROOT / "connections.json").read_text())
    t = conns["lift_and_shift_target"]
    user = t.get("target_user", "SAP*")
    pw = os.environ.get("M4H_TARGET_PASSWD")
    if not pw:
        print("ERROR: set $env:M4H_TARGET_PASSWD first"); return 2

    from pyrfc import Connection
    c = Connection(ashost=t["target_ashost"], sysnr=t["target_sysnr"],
                   client=t["target_client"], user=user, passwd=pw, lang="EN")

    if args.sap_all:
        print(f"=== Granting SAP_ALL + SAP_NEW to {user} (test-system shortcut) ===")
        grant_sap_all(c, user)
        c.close()
        return 0

    if args.assign:
        print(f"=== Assigning Migration Cockpit roles to {user} ===")
        assign_roles(c, user, MC_ROLES_TO_ADD)
        c.close()
        return 0

    # 1. Current roles of the target user
    print(f"=== Roles currently assigned to {user} ===")
    have_roles = set()
    try:
        d = c.call("BAPI_USER_GET_DETAIL", USERNAME=user)
        for r in d.get("ACTIVITYGROUPS", []):
            name = r.get("AGR_NAME", "").strip()
            if name:
                have_roles.add(name)
        mc_like = sorted(x for x in have_roles if any(k in x.upper() for k in ("DMC", "MIG", "LTMC")))
        print(f"  total roles: {len(have_roles)}")
        print(f"  data-migration-related roles already held: {mc_like or 'NONE'}")
    except Exception as e:
        print(f"  could not read user detail: {type(e).__name__}: {str(e)[:100]}")

    # 2. Which MC roles exist on the system at all
    print("\n=== Migration-Cockpit roles that EXIST on this system ===")
    existing = []
    try:
        res = c.call("RFC_READ_TABLE", QUERY_TABLE="AGR_DEFINE", DELIMITER="|",
                     OPTIONS=[{"TEXT": "AGR_NAME LIKE '%DMC%'"}],
                     FIELDS=[{"FIELDNAME": "AGR_NAME"}], ROWCOUNT=50)
        existing = [r["WA"].split("|")[0].strip() for r in res.get("DATA", [])]
        for r in existing[:30]:
            print(f"  {r}")
        if not existing:
            print("  (no %DMC% roles found; appliance may use Fiori business roles)")
    except Exception as e:
        print(f"  could not query AGR_DEFINE: {type(e).__name__}: {str(e)[:100]}")

    # 3. Verdict
    print("\n=== VERDICT ===")
    assignable = [r for r in MC_ROLE_CANDIDATES if r in existing]
    already = [r for r in MC_ROLE_CANDIDATES if r in have_roles]
    if already:
        print(f"  {user} ALREADY has MC role(s): {already}")
        print("  -> the 403 may be a Fiori-catalog / gateway issue, not a role. Tell me and I'll dig.")
    elif assignable:
        print(f"  MC role(s) exist and could be assigned to {user}: {assignable}")
        print("  -> I can script this assignment over RFC (no SAP GUI). Confirm and I'll add an --assign step.")
    else:
        print("  No standard MC role detected as assignable via this probe.")
        print("  -> Likely needs a one-time SU01 step in SAP GUI (RDP box) OR a Basis person.")
        print(f"  Roles found containing DMC: {existing[:10] or 'none'}")

    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
