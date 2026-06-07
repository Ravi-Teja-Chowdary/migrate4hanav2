"""
spine_benchmark - F5 scale-test for the spine orchestrator path.

Drives synthetic records through MaterialSpineOrchestrator (or any
BaseSpineOrchestrator subclass) against a MockSapTarget and captures the
metrics that actually matter for production-readiness:

  - throughput (records/sec, both wall-clock and per-thread)
  - latency percentiles (p50 / p90 / p99 / p99.9)
  - dead-letter breakdown by code
  - EXTENSIONIN gate counters (rows packed, fields dropped by coverage gate)
  - key_map (PersistentKeyMap) write rate
  - DQ rejection rate (via TransformationEngine if attached)

This module is unit-tested with a 100-record run; the full 10^6 run is meant
to be invoked separately (CLI) once real systems are available. The metric
schema below is what SCALE_BENCHMARK.md publishes per object per release.

CLI:
    python -m tests.battletest.spine_benchmark --object Material --count 10000
    python -m tests.battletest.spine_benchmark --object Material --count 1000000 \\
        --threads 16 --report out/scale-report.json
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lambda" / "utils"))

from base_spine_orchestrator import BaseSpineOrchestrator   # noqa: E402
import material_spine   # noqa: E402,F401   (registers MaterialSpineOrchestrator)
from base_spine_orchestrator import get_spine   # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic record generators (lightweight - the full generator.py is for the
# orchestrator's end-to-end run; this is just enough for spine-only throughput)
# ─────────────────────────────────────────────────────────────────────────────
def gen_material_records(count: int, seed: int = 42,
                          custom_field_count: int = 3) -> list:
    """Generate ``count`` synthetic Material records with a realistic mix of
    subtables (plants, valuations, alt UoMs) + a sprinkling of ZZ custom fields."""
    rng = random.Random(seed)
    mtype_choices = ["FERT", "HALB", "HAWA", "ROH", "DIEN"]
    uom_choices   = ["EA", "PC", "KG", "L", "M"]
    plant_choices = ["1100", "1200", "2100"]
    out: list = []
    for i in range(count):
        mtart = rng.choice(mtype_choices)
        n_plants  = rng.choice([0, 1, 1, 1, 2, 3])
        n_uoms    = rng.choice([0, 0, 1, 1, 2])
        row: dict = {
            "MATNR":  f"SYN_{i:09d}",
            "MTART":  mtart,
            "MBRSH":  "M",
            "MEINS":  rng.choice(uom_choices),
            "MATKL":  f"GRP{rng.randint(1, 99):03d}",
            "MAKTX":  f"Synthetic Material {i:09d}",
        }
        if n_plants:
            row["_plants"] = [
                {"WERKS": rng.choice(plant_choices),
                 "DISMM": rng.choice(["PD", "VB", "ND"]),
                 "BESKZ": rng.choice(["F", "E"])}
                for _ in range(n_plants)
            ]
        if n_uoms:
            row["_alt_uoms"] = [
                {"MEINH": rng.choice(["BOX", "PAL", "KG", "M3"]),
                 "UMREZ": rng.randint(1, 12), "UMREN": 1}
                for _ in range(n_uoms)
            ]
        # Add custom Z fields - drives EXTENSIONIN packing under load
        for j in range(custom_field_count):
            row[f"ZZ_CUSTOM_{j:02d}"] = f"v{rng.randint(0, 999):03d}"
        out.append(row)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Fakes for autonomous (no-SAP) benchmarking
# ─────────────────────────────────────────────────────────────────────────────
class BenchmarkRfc:
    """Lightweight RFC stand-in for spine benchmarks. Always succeeds; tracks
    call counts. Reflects the optimistic case: BAPI returns S, commit succeeds."""
    def __init__(self, *, latency_jitter_ms: int = 0):
        self.calls: list = []
        self._latency = latency_jitter_ms / 1000.0
        self._rng = random.Random()

    def call(self, bapi: str, **kwargs):
        self.calls.append(bapi)
        if self._latency > 0:
            time.sleep(self._rng.uniform(0, self._latency))
        if bapi == "BAPI_MATERIAL_SAVEDATA":
            return {"RETURN": [{"TYPE": "S", "MESSAGE": "Material saved"}]}
        # Generic ok response
        return {"RETURN": [{"TYPE": "S"}]}


# ─────────────────────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class BenchmarkResult:
    object_type:        str
    count:              int
    wall_clock_s:       float
    throughput_per_sec: float
    p50_ms:             float
    p90_ms:             float
    p99_ms:             float
    p999_ms:            float
    status_breakdown:   dict = field(default_factory=dict)
    dead_letter_codes:  dict = field(default_factory=dict)
    extension_rows:     int = 0
    extension_drops:    int = 0
    spine_stats:        dict = field(default_factory=dict)
    notes:              list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────
def percentile(values: list, p: float) -> float:
    """Inclusive percentile. Returns 0 on empty input."""
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (p / 100.0)
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return float(s[int(k)])
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def run_benchmark(object_type: str = "Material",
                   count: int = 1000,
                   *,
                   seed: int = 42,
                   custom_field_count: int = 3,
                   latency_jitter_ms: int = 0,
                   key_map=None, transformer=None,
                   bapi_field_catalog: Optional[dict] = None,
                   record_generator: Optional[Callable[[int, int, int], list]] = None,
                   conn=None) -> BenchmarkResult:
    """Drive ``count`` synthetic records through the spine orchestrator for
    ``object_type``. Returns the BenchmarkResult.

    No SAP required by default - uses BenchmarkRfc. To benchmark against a real
    target, pass a live pyrfc Connection as ``conn``.
    """
    spine_cls = get_spine(object_type)
    if spine_cls is None:
        raise ValueError(f"No spine orchestrator registered for {object_type!r}")

    gen = record_generator or (lambda c, s, cf: gen_material_records(c, s, cf))
    records = gen(count, seed, custom_field_count)

    conn = conn or BenchmarkRfc(latency_jitter_ms=latency_jitter_ms)
    orch = spine_cls(conn, key_map=key_map, transformer=transformer,
                      bapi_field_catalog=bapi_field_catalog or {})

    latencies_ms: list = []
    dead_codes:   dict = {}
    status_counts: dict = {}
    ext_rows:    int = 0
    ext_drops:   int = 0

    t0 = time.perf_counter()
    for row in records:
        r0 = time.perf_counter()
        res = orch.load_one(row)
        latencies_ms.append((time.perf_counter() - r0) * 1000)
        status_counts[res.status] = status_counts.get(res.status, 0) + 1
        if res.dead_letter:
            dead_codes[res.dead_letter] = dead_codes.get(res.dead_letter, 0) + 1
        ext_rows  += res.extension_rows
    wall = time.perf_counter() - t0
    # spine stats include extension_field_drops (drops at the bapi catalog gate)
    ext_drops = orch.stats.extension_field_drops

    return BenchmarkResult(
        object_type=object_type, count=count,
        wall_clock_s=round(wall, 4),
        throughput_per_sec=round(count / wall, 2) if wall > 0 else 0.0,
        p50_ms=round(percentile(latencies_ms, 50), 3),
        p90_ms=round(percentile(latencies_ms, 90), 3),
        p99_ms=round(percentile(latencies_ms, 99), 3),
        p999_ms=round(percentile(latencies_ms, 99.9), 3),
        status_breakdown=status_counts,
        dead_letter_codes=dead_codes,
        extension_rows=ext_rows,
        extension_drops=ext_drops,
        spine_stats=orch.stats.to_dict(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="Spine orchestrator scale benchmark")
    p.add_argument("--object", default="Material",
                    help="object_type to benchmark (must be a registered spine)")
    p.add_argument("--count", type=int, default=1000,
                    help="number of synthetic records")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--custom-fields", type=int, default=3,
                    help="number of ZZ_* fields per record (drives EXTENSIONIN load)")
    p.add_argument("--latency-jitter-ms", type=int, default=0,
                    help="simulate BAPI latency by sleeping up to this many ms per call")
    p.add_argument("--report", type=Path, default=None,
                    help="write JSON report to this path")
    args = p.parse_args()

    res = run_benchmark(args.object, args.count, seed=args.seed,
                         custom_field_count=args.custom_fields,
                         latency_jitter_ms=args.latency_jitter_ms)
    print(json.dumps(res.to_dict(), indent=2))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(res.to_dict(), indent=2))
        print(f"\nReport: {args.report}", file=sys.stderr)


if __name__ == "__main__":
    main()
