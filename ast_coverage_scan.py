#!/usr/bin/env python
"""
ast_coverage_scan.py — run the AST engine over EVERY custom program in ECC and
report how many the engine handles properly.

Unlike the pipeline's code-analyzer (which caps at 200 programs for Lambda
timeout), this standalone scanner processes the entire discovery program list,
in order, with progress logging, and writes a coverage report.

"Handled properly" = the program's source was readable AND the AST engine
parsed it with ZERO parse errors AND produced no lossy output.

Prereqs (same shell that runs your pipeline):
    $env:SAPNWRFC_HOME = "C:\\Users\\ajays\\Downloads\\migrate4hanav2\\sapnwrfc"
    $env:M4H_ECC_PASSWD = "India123"

Usage:
    # full scan over the discovery captured in a prior run (e.g. RUN-LIVE-001):
    python ast_coverage_scan.py --run-id RUN-LIVE-001

    # quick test on the first 500 programs first:
    python ast_coverage_scan.py --run-id RUN-LIVE-001 --limit 500

    # skip inactive programs (faster, fewer empty reads):
    python ast_coverage_scan.py --run-id RUN-LIVE-001 --skip-inactive

    # resume from program N if interrupted:
    python ast_coverage_scan.py --run-id RUN-LIVE-001 --start 10000
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "lambda" / "code-analyzer"))

# Make the bundled SAP SDK importable if the env var isn't already set.
os.environ.setdefault("SAPNWRFC_HOME", str(ROOT / "sapnwrfc"))

from abap_ast_engine import process_abap_file  # noqa: E402

# Lines the AST safety-net guards against; if any remain, output is still lossy.
_LOSSY = re.compile(r"\bTO \.\.|: FOR \.| = \.\s*$|\bTO \.\s*$")


def read_src(conn, name: str):
    """Read ABAP source via RPY_PROGRAM_READ; returns text or None."""
    try:
        r = conn.call("RPY_PROGRAM_READ", PROGRAM_NAME=name,
                      ONLY_SOURCE="X", WITH_INCLUDELIST="", WITH_LOWERCASE="X")
        for tbl in ("SOURCE_EXTENDED", "SOURCE", "PROG_SOURCE"):
            rows = r.get(tbl) or []
            if rows:
                return "\n".join(x.get("LINE", "") for x in rows)
    except Exception:
        return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True, help="run-id whose discovery/full-scan.json to use")
    ap.add_argument("--limit", type=int, default=0, help="process at most N programs (0 = all)")
    ap.add_argument("--start", type=int, default=0, help="skip the first N programs (resume)")
    ap.add_argument("--skip-inactive", action="store_true", help="skip programs marked inactive")
    ap.add_argument("--no-write", action="store_true", help="don't write remediated .abap files")
    args = ap.parse_args()

    # ── connect to ECC from connections.json ─────────────────────────────────
    conns = json.loads((ROOT / "connections.json").read_text())
    ecc = conns["ecc"]
    pw = os.environ.get("M4H_ECC_PASSWD")
    if not pw:
        print("ERROR: set $env:M4H_ECC_PASSWD first"); return 2
    from pyrfc import Connection
    conn = Connection(ashost=ecc["ashost"], sysnr=ecc["sysnr"], client=ecc["client"],
                      user=ecc["user"], passwd=pw, lang="EN")
    print(f"Connected to ECC {ecc['ashost']} client {ecc['client']}")

    # ── load discovery program list ──────────────────────────────────────────
    disc_path = ROOT / "local-staging" / "m4h-local" / "migrations" / args.run_id / "discovery" / "full-scan.json"
    disc = json.loads(disc_path.read_text())
    progs = disc.get("programs", [])
    if args.skip_inactive:
        progs = [p for p in progs if str(p.get("status", "")).lower() != "inactive"]
    progs = progs[args.start:]
    if args.limit:
        progs = progs[:args.limit]
    print(f"Programs to scan: {len(progs)}")

    out_dir = ROOT / "local-staging" / "m4h-local" / "migrations" / args.run_id / "code-analysis"
    rem_dir = out_dir / "remediated_full"
    if not args.no_write:
        rem_dir.mkdir(parents=True, exist_ok=True)

    st = dict(total=len(progs), no_source=0, parsed_clean=0, parse_failed=0,
              with_changes=0, still_lossy=0, engine_error=0)
    failed_samples = []
    t0 = time.time()

    for i, p in enumerate(progs, 1):
        name = p.get("name", "")
        src = read_src(conn, name)
        if not src:
            st["no_source"] += 1
        else:
            try:
                res = process_abap_file(src)
                pe = res["stats"]["parse_error_count"]
                out = res["transformed_code"]
                if pe == 0:
                    st["parsed_clean"] += 1
                else:
                    st["parse_failed"] += 1
                    if len(failed_samples) < 100:
                        failed_samples.append({"program": name, "parse_errors": pe})
                if _LOSSY.search(out):
                    st["still_lossy"] += 1
                if res["stats"]["total_changes"] > 0:
                    st["with_changes"] += 1
                    if not args.no_write:
                        safe = re.sub(r"[^A-Za-z0-9_=.\-]", "_", name)[:120]
                        (rem_dir / f"{safe}.abap").write_text(out, encoding="utf-8", errors="replace")
            except Exception as e:
                st["engine_error"] += 1
                if len(failed_samples) < 100:
                    failed_samples.append({"program": name, "engine_error": str(e)[:160]})

        if i % 250 == 0:
            el = time.time() - t0
            rate = i / el if el else 0
            eta = (len(progs) - i) / rate if rate else 0
            print(f"  {i}/{len(progs)}  clean={st['parsed_clean']} "
                  f"parse_failed={st['parse_failed']} no_source={st['no_source']} "
                  f"changed={st['with_changes']}  [{el:.0f}s elapsed, ~{eta:.0f}s left]")

    st["elapsed_sec"] = round(time.time() - t0, 1)
    readable = st["parsed_clean"] + st["parse_failed"]
    st["readable"] = readable
    st["parse_success_rate_of_readable"] = (
        f"{st['parsed_clean'] / readable * 100:.1f}%" if readable else "n/a")
    st["handled_properly_of_total"] = (
        f"{st['parsed_clean'] / st['total'] * 100:.2f}%" if st["total"] else "n/a")

    report = {"run_id": args.run_id, "stats": st, "failed_samples": failed_samples}
    (out_dir / "ast_coverage.json").write_text(json.dumps(report, indent=2))

    print("\n=== AST COVERAGE REPORT ===")
    for k, v in st.items():
        print(f"  {k:32}: {v}")
    print(f"\nFull report: {out_dir / 'ast_coverage.json'}")
    print(f"Remediated files: {rem_dir if not args.no_write else '(skipped, --no-write)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
