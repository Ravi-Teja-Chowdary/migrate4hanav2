#!/usr/bin/env python
"""Summarize the engine_error buckets from ast_coverage.json."""
import json
import sys
from collections import Counter
from pathlib import Path

run_id = sys.argv[1] if len(sys.argv) > 1 else "RUN-LIVE-001"
p = Path("local-staging") / "m4h-local" / "migrations" / run_id / "code-analysis" / "ast_coverage.json"
d = json.loads(p.read_text())
samples = d.get("failed_samples", [])

errs = [s for s in samples if "engine_error" in s]
print(f"failed_samples captured: {len(samples)}  (engine_error entries: {len(errs)})")
print("=== distinct engine errors (count x message) ===")
c = Counter(s.get("engine_error", "")[:90] for s in errs)
for msg, n in c.most_common():
    print(f"{n:4} x {msg}")

print("\n=== first 5 offending programs ===")
for s in errs[:5]:
    print(f"  {s.get('program')}: {s.get('engine_error','')[:120]}")
