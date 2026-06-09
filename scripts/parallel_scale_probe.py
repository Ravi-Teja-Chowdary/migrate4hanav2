"""
parallel_scale_probe — measures 32-way concurrent throughput against live S/4.

Roadmap B: the SCALE_BENCHMARK extrapolation says 1M records ~34min at
32-way Fargate. That's pure math from the single-threaded measurement.
This script proves (or disproves) it by launching N concurrent lambda
invocations -- each opening its own pyrfc connection to the same S/4 --
and measuring whether throughput scales linearly or S/4 serializes.

What's being measured:
  - per-invocation wall_clock and throughput
  - aggregate throughput (total records / max wall_clock observed)
  - parallel efficiency (aggregate / (single_threaded * N))
  - S/4 error rate under concurrency (dead-letter spike = contention)

This is a CHEAP equivalent of the Fargate fan-out: each Lambda invocation
runs in its own runtime, gets its own pyrfc connection, hits the same
S/4 target. From S/4's perspective these are 32 distinct sessions exactly
as if they were 32 Fargate tasks.

Usage:
    python scripts/parallel_scale_probe.py --concurrency 32 --records-per 50

Total records loaded = concurrency * records-per. Each invocation gets a
unique prefix so they don't collide on source keys.
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
from botocore.config import Config

FUNCTION_NAME = "migrate4hana-data-migrator-prod"
REGION = "us-east-1"


def invoke_one(lambda_client, idx: int, records_per: int, run_tag: str) -> dict:
    """Invoke one lambda instance synchronously; return its result + timing."""
    prefix = f"PSCALE_{run_tag}_{idx:02d}"
    payload = {
        "mode":    "phase_b_validate_f5",
        "count":   records_per,
        "prefix":  prefix,
        "run_id":  f"pscale-{run_tag}-{idx:02d}",
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
    return {
        "idx":            idx,
        "prefix":         prefix,
        "observed_wall":  round(wall, 2),
        "status":         parsed.get("status"),
        "lambda_wall":    parsed.get("wall_clock_s"),
        "throughput":     parsed.get("throughput_per_sec"),
        "count":          parsed.get("count"),
        "p50_ms":         parsed.get("p50_ms"),
        "p90_ms":         parsed.get("p90_ms"),
        "p99_ms":         parsed.get("p99_ms"),
        "dead_letter":    (parsed.get("spine_stats") or {}).get("dead_letter", 0),
        "failed":         (parsed.get("spine_stats") or {}).get("failed", 0),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency",   type=int, default=32)
    ap.add_argument("--records-per",   type=int, default=50)
    ap.add_argument("--tag",           type=str, default=None)
    args = ap.parse_args()

    tag = args.tag or f"r{int(time.time()) % 100000}"
    total_records = args.concurrency * args.records_per
    print(f"Driving {args.concurrency}-way fan-out, {args.records_per} records each")
    print(f"Total records: {total_records}, run tag: {tag}")
    print(f"Function:      {FUNCTION_NAME}")
    print()

    cfg = Config(retries={"max_attempts": 0},
                  connect_timeout=60, read_timeout=300,
                  max_pool_connections=max(args.concurrency, 64))
    lam = boto3.client("lambda", region_name=REGION, config=cfg)

    t0 = time.perf_counter()
    results = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futs = [pool.submit(invoke_one, lam, i, args.records_per, tag)
                 for i in range(args.concurrency)]
        for f in as_completed(futs):
            try:
                r = f.result()
                results.append(r)
                print(f"  [{r['idx']:2d}] wall={r['observed_wall']:6.2f}s  "
                       f"throughput={r['throughput']}  p50={r['p50_ms']}ms  "
                       f"status={r['status']}  dead={r['dead_letter']}")
            except Exception as e:
                print(f"  [FAIL] {e}")
    total_wall = time.perf_counter() - t0

    successes = [r for r in results if r.get("status") == "ok"]
    n_success = len(successes)
    total_created = sum(r.get("count", 0) for r in successes)
    total_dead = sum(r.get("dead_letter", 0) for r in successes)

    if successes:
        single_throughput = sum(r.get("throughput", 0) for r in successes) / n_success
        max_lambda_wall  = max((r.get("lambda_wall") or 0) for r in successes)
        agg_throughput = total_created / total_wall if total_wall else 0
        scaling_factor = agg_throughput / single_throughput if single_throughput else 0
        parallel_eff   = scaling_factor / args.concurrency if args.concurrency else 0
        avg_p50 = sum(r.get("p50_ms", 0) for r in successes) / n_success
        avg_p99 = sum(r.get("p99_ms", 0) for r in successes) / n_success
    else:
        single_throughput = max_lambda_wall = agg_throughput = 0
        scaling_factor = parallel_eff = avg_p50 = avg_p99 = 0

    print()
    print("=" * 70)
    print(f"Aggregate over {args.concurrency}-way fan-out:")
    print(f"  invocations succeeded:    {n_success}/{args.concurrency}")
    print(f"  total records loaded:     {total_created}")
    print(f"  total dead-letter:        {total_dead}")
    print(f"  total wall clock:         {total_wall:.2f}s")
    print(f"  max single-lambda wall:   {max_lambda_wall:.2f}s")
    print(f"  average single-thread tp: {single_throughput:.2f} rec/sec")
    print(f"  AGGREGATE throughput:     {agg_throughput:.2f} rec/sec")
    print(f"  scaling factor:           {scaling_factor:.2f}x (ideal = {args.concurrency})")
    print(f"  parallel efficiency:      {parallel_eff*100:.1f}% of ideal")
    print(f"  avg per-record p50:       {avg_p50:.1f}ms")
    print(f"  avg per-record p99:       {avg_p99:.1f}ms")
    print()
    # Verdict
    if n_success == args.concurrency and total_dead == 0:
        if parallel_eff >= 0.7:
            print("VERDICT: Linear scaling under concurrency. S/4 does not serialize.")
        elif parallel_eff >= 0.4:
            print("VERDICT: Sub-linear scaling. S/4 has partial contention.")
        else:
            print("VERDICT: Poor parallel scaling. S/4 serializes under concurrency.")
    else:
        print(f"VERDICT: {args.concurrency - n_success} invocation failures + {total_dead} dead-letters. "
               "Re-run with diagnostics.")

    out = {
        "tag":              tag,
        "concurrency":      args.concurrency,
        "records_per":      args.records_per,
        "total_records":    total_records,
        "total_wall_clock_s": round(total_wall, 2),
        "invocations_ok":   n_success,
        "total_created":    total_created,
        "total_dead_letter": total_dead,
        "single_thread_throughput_per_sec": round(single_throughput, 2),
        "aggregate_throughput_per_sec":     round(agg_throughput, 2),
        "scaling_factor":   round(scaling_factor, 2),
        "parallel_efficiency_pct": round(parallel_eff * 100, 1),
        "avg_p50_ms":       round(avg_p50, 1),
        "avg_p99_ms":       round(avg_p99, 1),
        "per_invocation":   results,
    }
    with open(f"parallel-scale-{tag}.json", "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nFull results: parallel-scale-{tag}.json")


if __name__ == "__main__":
    main()
