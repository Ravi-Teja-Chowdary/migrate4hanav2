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

## Synthetic baseline (no SAP)

```
Harness:     tests/battletest/spine_benchmark.py
Hardware:    Windows / Python 3.7 / single thread / in-memory BenchmarkRfc

Material  10,000 rows + 3 ZZ_* custom fields per row
  wall_clock_s         0.389
  throughput           25,734 records / sec
  p50 / p90 / p99 / p999    0.037ms / 0.043ms / 0.077ms / 0.130ms
  extension_rows       30,000   (3 packed Z-fields per record into BAPI_TE_MARA)
  extension_drops      0
  dead-letter rate     0.00%
```

What this baseline proves:

1. The spine path itself (lifecycle + EXTENSIONIN packing + key_map registration
   + DQ + FK resolve) adds **~40 microseconds per record** of overhead. Real
   throughput will be bound by SAP RFC RTT, **not** by Python code.
2. EXTENSIONIN packing scales linearly with custom_field_count. Three fields ×
   10K rows = 30K rows packed in the same 0.39s window.
3. Memory is bounded — no leaks across the 10K loop (the spine's per-row state
   is GC'd immediately).

## Extrapolation (synthetic → real)

Real SAP throughput will be dominated by RFC RTT:

```
                          synthetic   real (over WAN to CAL S/4)
single-record BAPI         40 us       ~ 80-250ms     (ngrok in-region adds 30-80ms)
                                       
extrapolated 1M-record    ~40 sec      ~ 22-70 HOURS  (single-threaded)
                                       ~ 1.5 - 4 HOURS (32-way Fargate fan-out)
```

The 32-way Fargate number assumes:

- Each Fargate task has its own pyrfc Connection (no shared connection lock)
- DynamoDB key_map is on PAY_PER_REQUEST (already true in prod)
- The S/4 target tolerates 32 concurrent BAPI_MATERIAL_SAVEDATA calls without
  serialising on a single TM table lock

The third assumption is the one that needs to be **validated on the real
target**. If S/4 serialises (some material types do, e.g. CHARG'd batches),
the effective fan-out drops; the benchmark report names this scenario.

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
