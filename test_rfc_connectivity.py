"""Two-sided RFC connectivity test for Migrate4HANA lift-and-shift.

Run with:
    $env:SAPNWRFC_HOME = "$PWD\sapnwrfc"
    python test_rfc_connectivity.py
"""
import os, json, sys

try:
    from pyrfc import Connection
except ImportError as e:
    print("pyrfc not importable:", e)
    sys.exit(1)

with open("connections.json") as f:
    c = json.load(f)

print("=" * 60)
print("Testing local ECC")
print("=" * 60)
e = c["ecc"]
print(f"  host={e['ashost']}  sysnr={e['sysnr']}  client={e['client']}  user={e['user']}")
pwd = os.environ.get("M4H_ECC_PASSWD")
if not pwd:
    print("  SKIP: M4H_ECC_PASSWD not set")
else:
    try:
        ec = Connection(ashost=e["ashost"], sysnr=e["sysnr"],
                        client=e["client"], user=e["user"], passwd=pwd)
        info = ec.call("RFC_SYSTEM_INFO")["RFCSI_EXPORT"]
        print(f"  OK -> SID={info['RFCSYSID']}  release={info['RFCSAPRL']}  host={info['RFCHOST']}")
    except Exception as ex:
        print(f"  FAIL -> {type(ex).__name__}: {ex}")

print()
print("=" * 60)
print("Testing CAL S/4HANA")
print("=" * 60)
t = c["lift_and_shift_target"]
print(f"  host={t['target_ashost']}  sysnr={t['target_sysnr']}  client={t['target_client']}  user={t['target_user']}")
pwd = os.environ.get("M4H_TARGET_PASSWD")
if not pwd:
    print("  SKIP: M4H_TARGET_PASSWD not set")
else:
    try:
        tc = Connection(ashost=t["target_ashost"], sysnr=t["target_sysnr"],
                        client=t["target_client"], user=t["target_user"], passwd=pwd)
        info = tc.call("RFC_SYSTEM_INFO")["RFCSI_EXPORT"]
        print(f"  OK -> SID={info['RFCSYSID']}  release={info['RFCSAPRL']}  host={info['RFCHOST']}")
    except Exception as ex:
        print(f"  FAIL -> {type(ex).__name__}: {ex}")
