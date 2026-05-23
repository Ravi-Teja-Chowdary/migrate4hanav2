#!/usr/bin/env python
"""Pinpoint the MIGRATE_ADMI login issue: exact username + which password works."""
from __future__ import annotations
import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
os.environ.setdefault("SAPNWRFC_HOME", str(ROOT / "sapnwrfc"))
from pyrfc import Connection

conns = json.loads((ROOT / "connections.json").read_text())
t = conns["lift_and_shift_target"]
host, sysnr, client = t["target_ashost"], t["target_sysnr"], t["target_client"]
FULL = os.environ.get("M4H_TARGET_PASSWD", "Parupalliajayteja@2020")
ADMIN_PASS = "Parupallitejaajay#92"

# 1. exact stored username from USR02 (via working SAP*)
c = Connection(ashost=host, sysnr=sysnr, client=client, user="SAP*", passwd=ADMIN_PASS, lang="EN")
res = c.call("RFC_READ_TABLE", QUERY_TABLE="USR02", DELIMITER="|",
             OPTIONS=[{"TEXT": "BNAME LIKE 'MIGRATE%'"}],
             FIELDS=[{"FIELDNAME": "BNAME"}, {"FIELDNAME": "USTYP"},
                     {"FIELDNAME": "UFLAG"}], ROWCOUNT=10)
names = []
print("=== USR02 rows matching MIGRATE% ===")
for r in res.get("DATA", []):
    v = [p.strip() for p in r["WA"].split("|")]
    names.append(v[0])
    print(f"  BNAME={v[0]!r}  USTYP={v[1]}  UFLAG(lock)={v[2]}")
c.close()

exact = names[0] if names else "MIGRATE_ADMI"

# 2. try a few logons (limited, to avoid lockout)
attempts = [
    (exact, FULL, "exact name + full password"),
    ("MIGRATE_ADMI", FULL, "13-char name + full password"),
    (exact, FULL[:8], "exact name + first-8-chars (truncation test)"),
]
print("\n=== logon attempts ===")
for user, pw, label in attempts:
    try:
        cc = Connection(ashost=host, sysnr=sysnr, client=client, user=user, passwd=pw, lang="EN")
        info = cc.call("RFC_SYSTEM_INFO")["RFCSI_EXPORT"]
        print(f"  OK   [{label}] user={user!r} -> {info['RFCSYSID']}")
        cc.close()
    except Exception as e:
        key = getattr(e, "key", type(e).__name__)
        print(f"  FAIL [{label}] user={user!r} -> {key}")
