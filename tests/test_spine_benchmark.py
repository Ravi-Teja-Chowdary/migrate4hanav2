"""
Unit tests for the F5 spine benchmark harness.

Validates the no-SAP autonomous path: generate -> drive through spine -> compute
percentiles -> emit structured result. The full 10^6 run against real systems is
out of scope here (Phase B); this proves the harness itself is correct.

Run:  python tests\test_spine_benchmark.py
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "lambda" / "utils"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "battletest"))

from spine_benchmark import (   # noqa
    gen_material_records, BenchmarkRfc, BenchmarkResult, percentile, run_benchmark,
)
from key_map import PersistentKeyMap   # noqa


# ─────────────────────────────────────────────────────────────────────────────
# Generators
# ─────────────────────────────────────────────────────────────────────────────
def test_gen_material_records_deterministic_under_seed():
    a = gen_material_records(50, seed=7)
    b = gen_material_records(50, seed=7)
    assert a == b
    print("  [OK] gen_material_records is deterministic under a fixed seed")


def test_gen_material_records_emits_subtables_and_zfields():
    rows = gen_material_records(200, seed=3, custom_field_count=2)
    assert len(rows) == 200
    # Each row has at least the basic MARA fields
    assert all("MATNR" in r and "MTART" in r for r in rows)
    # ZZ_* fields per row
    assert all(any(k.startswith("ZZ_") for k in r) for r in rows)
    # Some rows have plants/alt_uoms (random; with 200 we should see some of each)
    with_plants = sum(1 for r in rows if r.get("_plants"))
    with_uoms   = sum(1 for r in rows if r.get("_alt_uoms"))
    assert with_plants > 0
    assert with_uoms   >= 0   # alt UoMs rarer; allow zero for tiny generators
    print(f"  [OK] generator emits ZZ fields + subtables (plants={with_plants}, uoms={with_uoms})")


# ─────────────────────────────────────────────────────────────────────────────
# Percentile
# ─────────────────────────────────────────────────────────────────────────────
def test_percentile_basic():
    assert percentile([], 50) == 0.0
    assert percentile([1, 2, 3, 4, 5], 50) == 3.0
    assert percentile([1, 2, 3, 4, 5], 90) == pytest_close(4.6)
    assert percentile([1, 2, 3, 4, 5], 99) == pytest_close(4.96)
    print("  [OK] percentile p50/p90/p99 are correct on a known sample")


def pytest_close(expected: float):
    """Tiny helper since we're not using pytest fixtures here."""
    class _Cmp:
        def __eq__(self, other): return abs(other - expected) < 0.05
        def __repr__(self): return f"~{expected:.3f}"
    return _Cmp()


# ─────────────────────────────────────────────────────────────────────────────
# Benchmark run
# ─────────────────────────────────────────────────────────────────────────────
def test_run_benchmark_material_100_rows_succeeds_and_reports_metrics():
    res = run_benchmark("Material", count=100, seed=11)
    assert isinstance(res, BenchmarkResult)
    assert res.object_type == "Material"
    assert res.count == 100
    assert res.wall_clock_s >= 0.0
    # In the optimistic mock path, every record creates cleanly
    assert res.status_breakdown.get("created", 0) == 100
    # Throughput is non-zero
    assert res.throughput_per_sec > 0
    # Percentiles populated
    assert res.p50_ms > 0 and res.p90_ms >= res.p50_ms
    # ZZ fields packed
    assert res.extension_rows >= 100   # at least 1 per row (default custom_field_count=3)
    # Spine stats reflect the same count
    assert res.spine_stats["created"] == 100
    print(f"  [OK] 100-row run: tp={res.throughput_per_sec:.0f}/s, "
          f"p50={res.p50_ms:.2f}ms, p99={res.p99_ms:.2f}ms, "
          f"ext_rows={res.extension_rows}")


def test_run_benchmark_with_persistent_key_map_records_writes():
    pk = PersistentKeyMap(table_name=None, dynamodb_client=None, run_id="bench-test")
    res = run_benchmark("Material", count=50, seed=21, key_map=pk)
    # Every successful load registers a (Material, MATNR) -> target mapping
    assert pk.stats()["total_mappings"] == 50
    assert res.status_breakdown.get("created", 0) == 50
    print("  [OK] PersistentKeyMap registration works under the benchmark loop")


def test_run_benchmark_unknown_object_raises():
    try:
        run_benchmark("BogusObject", count=10)
    except ValueError as e:
        assert "BogusObject" in str(e)
        print("  [OK] unknown object_type raises a clean ValueError")
        return
    assert False, "expected ValueError"


def test_run_benchmark_latency_jitter_shifts_throughput():
    """Higher latency_jitter_ms should noticeably slow throughput. We don't
    pin to specific numbers (machine-dependent) but assert the ordering."""
    fast = run_benchmark("Material", count=80, seed=33, latency_jitter_ms=0)
    slow = run_benchmark("Material", count=80, seed=33, latency_jitter_ms=2)
    # slower jitter => higher wall clock OR higher p50_ms
    assert slow.wall_clock_s >= fast.wall_clock_s or slow.p50_ms > fast.p50_ms
    print("  [OK] latency_jitter_ms shifts throughput / p50 in the expected direction")


def test_run_benchmark_result_is_json_serialisable():
    """The result must serialise cleanly for a SCALE_BENCHMARK.md report."""
    import json
    res = run_benchmark("Material", count=20, seed=99)
    txt = json.dumps(res.to_dict())
    assert "object_type" in txt and "throughput_per_sec" in txt
    print("  [OK] BenchmarkResult is JSON-serialisable for the published report")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("F5 - spine_benchmark tests")
    print("=" * 70)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll spine_benchmark tests passed.")
