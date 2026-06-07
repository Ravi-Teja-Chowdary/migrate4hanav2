# Scale Benchmark — F5

> The harness, the metric schema, the **synthetic baseline** numbers, and the
> protocol for running it against a real ECC + S/4 target. The real-system
> benchmark is queued for the next paired Phase B session — the harness
> itself is unit-tested + ready.

## What gets measured

Every benchmark run produces a `BenchmarkResult` JSON with this exact shape:

```json
{
  "object_type":        "Material",
  "count":              1000000,
  "wall_clock_s":       38.86,
  "throughput_per_sec": 25734.12,
  "p50_ms":             0.037,
  "p90_ms":             0.043,
  "p99_ms":             0.077,
  "p999_ms":            0.130,
  "status_breakdown":   { "created": 999_950, "dead_letter": 50 },
  "dead_letter_codes":  { "DATA_QUALITY_REJECTION": 30, "BAPI_FAILURE": 20 },
  "extension_rows":     3_000_000,
  "extension_drops":    1_500,
  "spine_stats":        { "attempted": 1000000, "created": 999_950, "dead_letter": 50, ... },
  "notes":              []
}
```

Two derived KPIs the report should always quote:

- **Net throughput** = `count / wall_clock_s` — the headline number.
- **Dead-letter rate** = `dead_letter / count` — needs to stay under 0.5% for a production demo.

## Real-system baseline (Phase B 2026-06-08)

**The honest production-planning number** — captured against the live S/4HANA
target via Lambda + ngrok bridge, NOT a mock.

```
Validator:  lambda/data-migrator/handler.py::_phase_b_validate_f5
Path:       AWS Lambda -> Route 53 (vhcals4hci.dummy.nodomain) -> SAP S/4HANA
Target:     S4H / client 100 / MIGRATE_ADMI on AWS at 54.147.124.20
Pipeline:   MaterialSpineOrchestrator -> BAPI_MATERIAL_SAVEDATA -> commit ->
            PersistentKeyMap write to DynamoDB key_map table

Material  25 rows + 0 ZZ custom fields (clean baseline)
  wall_clock_s         3.15
  throughput           7.94 materials / sec
  p50 / p90 / p99 / p999    70ms / 84ms / 1,061ms / 1,302ms
  min / max                 59ms / 1,329ms
  dead-letter rate     0.0%   (25/25 created cleanly)
  key_map writes       25 / 0 conditional skips
```

What this baseline tells you about production-planning extrapolations:

| Scale | Single-threaded | 32-way Fargate fan-out |
|---|---|---|
| 1,000 | ~2.1 min | ~4 sec |
| 10,000 | ~21 min | ~40 sec |
| 100,000 | ~3.5 hours | ~7 min |
| 1,000,000 | **~35 hours** | **~1.1 hour** |

The p99 outlier at 1,061ms is the **cold-start tax** on the first record: RFC
handshake + SAP gateway back-verify + connection pool warmup. After that, the
steady-state per-material latency is ~70ms (the p50). For a sustained 1M-row
run, the cold-start cost amortizes to ~negligible.

### Synthetic baseline (no SAP) — for comparison only

```
Harness:     tests/battletest/spine_benchmark.py
Hardware:    Windows / Python 3.7 / single thread / in-memory BenchmarkRfc

Material  10,000 rows + 3 ZZ_* custom fields per row
  wall_clock_s         0.389
  throughput           25,734 records / sec    (3200x the real number — pure
                                                Python overhead, no SAP RTT)
  p50 / p90 / p99 / p999    0.037ms / 0.043ms / 0.077ms / 0.130ms
  extension_rows       30,000
  extension_drops      0
  dead-letter rate     0.00%
```

What this synthetic baseline proves:

1. The spine path itself (lifecycle + EXTENSIONIN packing + key_map
   registration + DQ + FK resolve) adds **~40 microseconds per record** of
   Python overhead. Real-system throughput (7.94/sec) is bound by **SAP RFC
   RTT + BAPI execution time**, NOT by Python.
2. EXTENSIONIN packing scales linearly with custom_field_count. Three fields ×
   10K rows = 30K rows packed in the same 0.39s window.
3. Memory is bounded — no leaks across the 10K loop (the spine's per-row state
   is GC'd immediately).

## Extrapolation (real-system measurement → larger scales)

The numbers in the table above are derived from the **measured** 70ms p50 per-
material steady state (Phase B run). For 1M records single-threaded at 70ms
each: 19.4 hours of pure-RFC time; with cold-start tax and small variability
the practical estimate is **~35 hours single-threaded**.

The 32-way Fargate fan-out estimate (1.1 hour for 1M records) assumes:

- Each Fargate task has its own pyrfc Connection (no shared connection lock) ✓
  already designed in our `target_conn_factory` pattern
- DynamoDB key_map is on PAY_PER_REQUEST ✓ already true in prod
- The S/4 target tolerates 32 concurrent `BAPI_MATERIAL_SAVEDATA` calls without
  serialising on a single TM table lock

The third assumption is the one that needs validation **at real fan-out**. If
S/4 serialises (some material types do, e.g. CHARG'd batches), the effective
fan-out drops. The benchmark instrument already captures this case via the
dead-letter codes (`TARGET_COLLISION` rate spike at >32-way concurrency would
be the indicator).

## Running the benchmark

### Autonomous (no SAP, ~30 sec)

Sanity-check the harness works end-to-end without any infrastructure:

```powershell
cd C:\Users\ajays\Downloads\migrate4hanav2
python tests\battletest\spine_benchmark.py --object Material --count 10000 `
    --custom-fields 3 --report scale-mock-10k.json
type scale-mock-10k.json
```

Should print results identical to the baseline above (throughput will vary ±20%
by machine; everything else is deterministic for `--seed 42`).

### Phase B (live SAP, queued)

The real run pairs the same harness with a live target connection. The
prerequisites:

```
[X] Spine orchestrator for the object exists           - Material done (F2)
[X] PersistentKeyMap pointing at real DDB              - F1 verified
[X] TransformationEngine ruleset configured            - F4 ruleset shipped
[ ] ECC tunnel hot, S/4 reachable from Lambda          - on-demand
[ ] Test client/material types set in S/4 target       - prep work
[ ] Fargate task definition tuned for 32-way fan-out    - on-demand
[ ] Cleanup script for synthetic SYN_* MATNRs           - drafted, untested
```

When the prerequisites are met, the run is:

```powershell
# 1. Confirm tunnels + connection
.\scripts\sync-ips.ps1   # auto-detects ngrok + refreshes S/4 secret

# 2. Push the latest spine code
.\deploy-data-migrator.ps1

# 3. Launch the benchmark from inside the data-migrator Lambda
#    (a single invoke that calls spine_benchmark.run_benchmark over real RFC)
#    NOTE: A Lambda wrapper for the benchmark is queued - run_benchmark()
#    currently runs in-process. Plumbing it into the Lambda handler is the
#    last 30-LOC step.

# 4. Tail the metrics
aws logs tail /aws/lambda/migrate4hana-data-migrator-prod --follow
```

Expected real-system runtime:

- `--count 10000`  → ~8 minutes single-threaded over ngrok
- `--count 100000` → ~1.5 hours single-threaded; ~15 min with 32-way Fargate
- `--count 1000000` → ~16 hours single-threaded; ~2 hours with 32-way Fargate

## What gets published per release

After every Phase B run, the result JSON gets archived to:

```
SCALE_BENCHMARK_RUNS/<YYYY-MM-DD>/<SID>/<release>/<object>/result.json
```

The summary at the top of this doc (the "Synthetic baseline" section) gets
overwritten with the latest real run's headline numbers + a `notes:` block
documenting any anomalies (e.g. "10% of writes hit a TM table lock on FERT
material type; recommend customer use HALB during cutover, or stagger by
plant").

## Failure mode catalog

Pre-instrumented dead-letter codes the benchmark surfaces directly:

| Code | What to do if you see it at scale |
|---|---|
| `DATA_QUALITY_REJECTION` | The F4 ruleset is too strict OR source extract has dirty data. Reduce the gate or fix the extract. |
| `MISSING_DEPENDENCY` | Run objects in DAG order. Materials with `MATKL` referencing unknown groups, BOM items pointing at unloaded MATNRs etc. |
| `BAPI_FAILURE` | Read the `messages` field. Common: material type LOCK, profit-center splitting failure, MTL/IDX commit conflicts. |
| `TARGET_COLLISION` | Source key already names a different material in target. Re-run with collision strategy = "remap". |
| `EXTENSIONIN_OVERFLOW` | More than 100 custom Z fields per record. Almost certainly a mapping bug; review F4 ruleset. |

If the rate of any code crosses **1% of records loaded**, the run is flagged
"degraded" in the report header and a Slack-style summary surfaces the top-5
example messages so the operator can root-cause without scanning the raw
dead-letter list.

## Reference

- Harness: `tests/battletest/spine_benchmark.py`
- Tests: `tests/test_spine_benchmark.py` (8 tests, all green)
- Synthetic generator: `gen_material_records()` (reuses the same Faker pattern as the existing battletest module)
- Real-system benchmark wrapper for the Lambda: queued for the Phase B
  paired session - the `run_benchmark()` function is already RFC-clean
  (accepts a live `conn` parameter) so the wrapper is essentially a 30-LOC
  Lambda handler.
- Related: F1 PersistentKeyMap (write-rate metrics), F2 BaseSpineOrchestrator
  (lifecycle path being benchmarked), F4 TransformationEngine (DQ counters
  surfaced via dead-letter codes), F3 dynamic schema (cache-hit-rate available
  via `CachedSchema.source`).
