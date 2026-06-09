"""
bapi_inplace_smoke - CLI smoke test for the BAPI/in-place pipeline.

Mirrors the Step Functions BAPI in-place state machine
(terraform/modules/step-functions/bapi_inplace_pipeline.asl.json) without
requiring the state machine to be deployed. For each object in the input
DAG, invokes the data-migrator lambda's production-path mode (UnifiedLoader
-> spine -> Reconciler), aggregates per-object reconciler verdicts, and
issues the same final RECONCILED / DISCREPANCY gate the SM would.

This is the proof-of-life for roadmap C (Step Functions integration) --
once `terraform apply` deploys the bapi_inplace state machine, the SM will
orchestrate the same calls in parallel via DistributedMap with reliable
retry / catch / state-machine-execution-history; today we prove the
underlying lambda + spine + reconciler chain works for a multi-object
sequence.

Usage:
    python scripts/bapi_inplace_smoke.py --objects Material BusinessPartner --count 3
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import boto3
from botocore.config import Config

FUNCTION_NAME = "migrate4hana-data-migrator-prod"
REGION = "us-east-1"


def invoke(lambda_client, obj: str, count: int, run_id: str) -> dict:
    # Per-invocation unique seed: epoch microseconds in the run_id suffix so
    # each invocation generates DISTINCT synthetic MATNRs / BPs, avoiding the
    # F1 ledger-hit guard from short-circuiting a re-test with the same
    # source keys. (The guard working is the desired production behavior;
    # for a smoke proof we want fresh creates.)
    seed = f"{int(time.time() * 1000) % 1000000:06d}"
    payload = {
        "mode":    "phase_b_validate_production_path",
        "object":  obj,
        "count":   count,
        "run_id":  f"{run_id}-{obj}-{seed}",
    }
    t0 = time.perf_counter()
    resp = lambda_client.invoke(
        FunctionName=FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )
    wall = time.perf_counter() - t0
    body = resp["Payload"].read().decode("utf-8") if resp.get("Payload") else "{}"
    try:
        parsed = json.loads(body)
    except Exception:
        parsed = {"status": "parse_error", "raw": body[:200]}
    parsed["_invoke_wall_s"] = round(wall, 2)
    return parsed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--objects", nargs="+",
                     default=["Material", "BusinessPartner"],
                     help="Objects to load (must have spine subclasses)")
    ap.add_argument("--count", type=int, default=3,
                     help="Records to load per object")
    args = ap.parse_args()

    run_id = f"bapi-smoke-{int(time.time())}"

    cfg = Config(retries={"max_attempts": 0},
                  connect_timeout=60, read_timeout=300)
    lam = boto3.client("lambda", region_name=REGION, config=cfg)

    print(f"BAPI in-place smoke -- run_id={run_id}")
    print(f"  objects: {', '.join(args.objects)}  count: {args.count}")
    print(f"  function: {FUNCTION_NAME}")
    print()

    t0 = time.perf_counter()
    per_object = []
    for obj in args.objects:
        print(f"  loading {obj}...", end=" ", flush=True)
        r = invoke(lam, obj, args.count, run_id)
        report = (r.get("reconciler_report") or {})
        proof = r.get("proof") or {}
        per_object.append({
            "object":            obj,
            "status":            r.get("status"),
            "wall_s":            r.get("_invoke_wall_s"),
            "mechanism":         (r.get("load_result") or {}).get("mechanism"),
            "created":           report.get("created"),
            "verified_in_target": report.get("verified_in_target"),
            "value_checked":     report.get("value_checked"),
            "value_matched":     report.get("value_matched"),
            "reconciler_status": report.get("status"),
            "all_proofs_green":  all(proof.values()) if proof else False,
        })
        verdict = report.get("status") or r.get("status")
        print(f"{verdict}  ({r.get('_invoke_wall_s')}s)")
    total_wall = time.perf_counter() - t0

    # Final gate (matches the state-machine choice gate behavior)
    failures = [p for p in per_object if p["reconciler_status"] != "RECONCILED"]
    overall_status = "RECONCILED" if not failures else "DISCREPANCY"

    print()
    print("=" * 70)
    print(f"Aggregate over {len(args.objects)} object(s):")
    print(f"  total wall clock:       {total_wall:.2f}s")
    print(f"  overall verdict:        {overall_status}")
    for p in per_object:
        print(f"  - {p['object']:20s}  reconciler={p['reconciler_status']:14s}  "
               f"created={p['created']}/{p['verified_in_target']}  "
               f"value_match={p['value_matched']}/{p['value_checked']}")

    out = {
        "run_id":           run_id,
        "objects":          args.objects,
        "count":            args.count,
        "total_wall_s":     round(total_wall, 2),
        "overall_verdict":  overall_status,
        "per_object":       per_object,
    }
    with open(f"bapi-smoke-{run_id}.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nFull results: bapi-smoke-{run_id}.json")
    sys.exit(0 if overall_status == "RECONCILED" else 1)


if __name__ == "__main__":
    main()
