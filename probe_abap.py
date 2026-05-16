"""Probe: read a few ABAP programs from ECC and run analyze_program on them."""
import os, sys
os.environ.setdefault("M4H_LOCAL_MODE", "1")
sys.path.insert(0, ".")
import local_aws_shim  # noqa: activates shim
sys.path.insert(0, "lambda/code-analyzer")
sys.path.insert(0, "lambda/utils")
from handler import get_sap_connection, read_abap_source, analyze_program  # noqa

os.environ["SECRETS_ARN"] = "local:ecc"
conn = get_sap_connection()

# Inspect return shape
r = conn.call("RPY_PROGRAM_READ", PROGRAM_NAME="SAPMV45A", WITH_LOWERCASE="X")
print("--- RPY_PROGRAM_READ keys for SAPMV45A ---")
for k, v in r.items():
    if isinstance(v, list):
        print(f"  {k}: list len={len(v)}", "first:", v[0] if v else None)
    else:
        print(f"  {k}: {v!r}")

# Try alternate FM RPY_PROGRAM_READ_NEW or READ_REPORT
print("\n--- READ_REPORT for SAPMV45A ---")
try:
    r2 = conn.call("READ_REPORT", PROGRAM="SAPMV45A")
    for k, v in r2.items():
        if isinstance(v, list):
            print(f"  {k}: list len={len(v)} first={v[0] if v else None}")
        else:
            print(f"  {k}: {v!r}")
except Exception as e:
    print("  READ_REPORT failed:", e)

