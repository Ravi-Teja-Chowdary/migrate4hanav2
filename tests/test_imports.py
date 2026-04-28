"""Smoke import-test for every active Lambda handler."""
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAMBDA_DIR = ROOT / "lambda"
sys.path.insert(0, str(LAMBDA_DIR / "utils"))

errors = []
for sub in sorted(os.listdir(LAMBDA_DIR)):
    if sub.startswith("_") or sub == "utils":
        continue
    p = LAMBDA_DIR / sub / "handler.py"
    if not p.exists():
        continue
    try:
        spec = importlib.util.spec_from_file_location(f"h_{sub.replace('-', '_')}", p)
        m = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(p.parent))
        spec.loader.exec_module(m)
        sys.path.pop(0)
        print(f"  OK   {sub}")
    except Exception as e:
        print(f"  FAIL {sub}: {type(e).__name__}: {e}")
        errors.append(sub)

print(f"\nTotal errors: {len(errors)}")
sys.exit(1 if errors else 0)
