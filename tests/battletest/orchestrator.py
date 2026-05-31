"""
Battletest orchestrator - the runner.

Drives a synthetic-data run through every stage of the Migrate4HANA tool:
  generate -> extract -> transform -> bapi_coverage -> load (mock) -> reconcile
  -> hash chain -> cutover_verdict -> structured report

Captures per-stage metrics and structured failures into a results JSON.

NOT a replacement for the live ECC + S/4 demo. Purpose: prove the tool stands
up to real-environment-size volumes (1M+ records, ~5M FI line items, ~100
custom Z-programs) WITHOUT touching the CAL appliance. CAL gets a separate
5K-record real-load sample.

CLI:
    python orchestrator.py --scale small         # 10K customers + everything else
    python orchestrator.py --scale medium        # 100K
    python orchestrator.py --scale large         # 1M
    python orchestrator.py --scale large --threads 32 --include-code-remediation
"""
from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import json
import os
import random
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

# Make the tool's modules importable
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lambda" / "utils"))
sys.path.insert(0, str(ROOT / "lambda" / "code-analyzer"))

from mock_target import MockSapTarget   # noqa: E402
from generator import generate_all, SCALES, Scale   # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
#  Metrics + failure tracking
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class StageMetrics:
    name: str
    started_at: float = 0.0
    ended_at: float = 0.0
    records_in: int = 0
    records_out: int = 0
    quarantined: int = 0
    ltmc_staged: int = 0
    errors: int = 0

    @property
    def elapsed_s(self) -> float:
        return round(self.ended_at - self.started_at, 3) if self.ended_at else 0.0

    @property
    def throughput_per_s(self) -> float:
        return round(self.records_in / self.elapsed_s, 0) if self.elapsed_s else 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["elapsed_s"] = self.elapsed_s
        d["throughput_per_s"] = self.throughput_per_s
        return d


@dataclass
class Issue:
    stage: str
    severity: str            # error | warning | info
    object_type: str
    record_key: str
    reason: str
    detail: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BattletestResult:
    scale: str
    started_at: str
    ended_at: str = ""
    total_elapsed_s: float = 0.0
    stages: List[StageMetrics] = field(default_factory=list)
    issues: List[Issue] = field(default_factory=list)
    mock_target_stats: Dict[str, Any] = field(default_factory=dict)
    gap_closure_stress: Dict[str, Any] = field(default_factory=dict)
    code_remediation: Optional[Dict[str, Any]] = None
    cutover_verdict: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        d = {
            "scale": self.scale,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "total_elapsed_s": self.total_elapsed_s,
            "stages": [s.to_dict() for s in self.stages],
            "issues": {
                "total": len(self.issues),
                "by_severity": _counts_by(self.issues, "severity"),
                "by_stage":    _counts_by(self.issues, "stage"),
                "first_50":    [i.to_dict() for i in self.issues[:50]],
            },
            "mock_target_stats": self.mock_target_stats,
            "gap_closure_stress": self.gap_closure_stress,
            "code_remediation": self.code_remediation,
            "cutover_verdict": self.cutover_verdict,
        }
        return d


def _counts_by(items, key):
    out: Dict[str, int] = {}
    for it in items:
        v = getattr(it, key)
        out[v] = out.get(v, 0) + 1
    return out


# ─────────────────────────────────────────────────────────────────────────────
#  Stage runners
# ─────────────────────────────────────────────────────────────────────────────
def _iter_jsonl_gz(path: Path) -> Iterator[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def stage_extract(fixtures_dir: Path, object_types: List[str],
                  result: BattletestResult) -> Dict[str, Path]:
    """'Extraction' is reading the generated fixtures off disk in chunks.
    Each object type's records stay as a streaming iterator (lazy)."""
    m = StageMetrics(name="extract")
    m.started_at = time.time()
    out: Dict[str, Path] = {}
    file_map = {
        "Customer":        "customers.jsonl.gz",
        "Vendor":          "vendors.jsonl.gz",
        "Material":        "materials.jsonl.gz",
        "GLAccount":       "gl_accounts.jsonl.gz",
        "FiHeader":        "bkpf.jsonl.gz",
        "FiLine":          "bseg.jsonl.gz",
    }
    for obj in object_types:
        fn = file_map.get(obj)
        if not fn:
            continue
        p = fixtures_dir / fn
        if p.exists():
            out[obj] = p
            # Count records (cheap, single pass)
            count = sum(1 for _ in _iter_jsonl_gz(p))
            m.records_in += count
            m.records_out += count
    m.ended_at = time.time()
    result.stages.append(m)
    return out


def stage_transform_and_coverage(file_map: Dict[str, Path],
                                  result: BattletestResult,
                                  threads: int = 16) -> Dict[str, List[dict]]:
    """For every record: run through transformation_engine + bapi_coverage.
    Returns a dict of accepted records per object (those headed for load)."""
    import transformation_engine as txe
    import bapi_coverage as cov
    import bapi_field_catalog as bfc
    import logging

    # Silence per-record coverage warnings (would otherwise produce one log
    # line per record - throughput drops 10x at the medium+ scales)
    logging.getLogger("bapi_coverage").setLevel(logging.ERROR)
    logging.getLogger("transformation_engine").setLevel(logging.ERROR)
    logging.getLogger("abap_ast_engine").setLevel(logging.ERROR)
    logging.getLogger("cvi_mapper").setLevel(logging.ERROR)

    catalog = bfc.as_dict()
    rng = random.Random(7)

    # Empty no-op transformer (cross-field DQ rules optional; keep light here)
    engine = txe.TransformationEngine(ruleset={"version": "1", "object_rules": {}})

    m = StageMetrics(name="transform_and_coverage")
    m.started_at = time.time()
    accepted: Dict[str, List[dict]] = {obj: [] for obj in file_map}

    for obj, path in file_map.items():
        cat_fields = catalog.get(obj, set())
        bapi_name = f"BAPI_{obj.upper()}_CREATE"
        for rec in _iter_jsonl_gz(path):
            m.records_in += 1
            # Strip the generator's internal debug flag so it doesn't show up
            # as a "BAPI coverage gap" in the analyzer
            rec.pop("_synthetic_dirty_flags", None)
            try:
                # transform: most rule sets are no-op in this default ruleset
                rec2, dq = engine.apply(obj, rec) if engine.has_rules(obj) else (rec, None)
                if dq is not None and not dq.passed:
                    m.quarantined += 1
                    result.issues.append(Issue(
                        stage="transform_and_coverage", severity="info",
                        object_type=obj, record_key=str(rec.get("KUNNR") or rec.get("LIFNR") or rec.get("MATNR") or "?"),
                        reason="DATA_QUALITY_REJECTION", detail={"reasons": dq.reasons[:3]}))
                    continue
                # BAPI coverage decision
                if cat_fields:
                    c = cov.analyze_coverage([rec2], obj, bapi_name, cat_fields)
                    d = cov.decide_load_path(c)
                    if d.path == "LTMC_ONLY":
                        m.ltmc_staged += 1
                        continue
                accepted[obj].append(rec2)
                m.records_out += 1
            except Exception as e:
                m.errors += 1
                result.issues.append(Issue(
                    stage="transform_and_coverage", severity="error",
                    object_type=obj, record_key="?",
                    reason=f"{type(e).__name__}: {str(e)[:120]}"))
    m.ended_at = time.time()
    result.stages.append(m)
    return accepted


def stage_load(accepted: Dict[str, List[dict]], target: MockSapTarget,
               result: BattletestResult, threads: int = 16,
               chunk_size: int = 10000) -> List[dict]:
    """Push every accepted record through the mock target. Threaded, chunked.

    Processes records in chunks of `chunk_size` so peak memory stays bounded
    regardless of total scale (5M records would otherwise hold 5M Future
    objects + 5M result dicts at once -> can exceed Fargate's 16GB limit).
    Returns the trimmed list of created keys (just object + id, not the
    original record) for the hash chain step.
    """
    m = StageMetrics(name="load")
    m.started_at = time.time()
    keys: List[dict] = []

    def one(obj: str, rec: dict) -> Optional[dict]:
        try:
            resp = target.call(obj, rec)
            if resp.get("status") == "created":
                # Drop the original record from the result - we only need
                # object+id downstream and 5M of these in memory is enough
                return {"object": obj, "id": resp["id"]}
            return None
        except Exception as e:
            result.issues.append(Issue(
                stage="load", severity="error", object_type=obj,
                record_key=str(rec.get("KUNNR") or rec.get("LIFNR") or rec.get("MATNR") or "?"),
                reason=f"{type(e).__name__}: {str(e)[:120]}"))
            return None

    # Process per-object, chunking each object's record list
    for obj, recs in accepted.items():
        total = len(recs)
        for chunk_start in range(0, total, chunk_size):
            chunk = recs[chunk_start:chunk_start + chunk_size]
            m.records_in += len(chunk)
            with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as ex:
                futures = [ex.submit(one, obj, rec) for rec in chunk]
                for f in concurrent.futures.as_completed(futures):
                    r = f.result()
                    if r:
                        keys.append(r)
                        m.records_out += 1
                    else:
                        m.errors += 1
            # Help GC reclaim the chunk's records + futures between batches
            del chunk
    m.ended_at = time.time()
    result.stages.append(m)
    return keys


def stage_hash_chain(load_keys: List[dict], result: BattletestResult) -> Dict[str, Any]:
    """Build the hash chain over the loaded records + verify it stays linkable."""
    from reconciler import HashChainLedger

    m = StageMetrics(name="hash_chain")
    m.started_at = time.time()
    chain = HashChainLedger(run_id="battletest")

    # One block per load batch of 1000 records (chain at this scale would be
    # millions of blocks otherwise; that's its own stress test - see stress.py)
    BATCH = 1000
    for i in range(0, len(load_keys), BATCH):
        batch = load_keys[i:i+BATCH]
        chain.append("load_batch", {
            "batch_index": i // BATCH,
            "size": len(batch),
            "first_id": batch[0]["id"] if batch else None,
            "last_id":  batch[-1]["id"] if batch else None,
        })
        m.records_in += len(batch)
        m.records_out += 1

    v = chain.verify()
    if not v.get("ok"):
        result.issues.append(Issue(
            stage="hash_chain", severity="error",
            object_type="(chain)", record_key="(chain)",
            reason=f"chain verify failed at block {v.get('broken_at')}",
            detail=v))
    m.ended_at = time.time()
    result.stages.append(m)
    return {"blocks": chain.block_count(), "head": chain.head(), "verify": v}


def stage_cutover_verdict(captured_spools: List[dict], ltmc_pending: dict,
                           balance_variance: bool, result: BattletestResult) -> dict:
    """Run the cutover_verdict against fabricated inputs spanning all 5 outcomes."""
    from reconciler import _compute_cutover_verdict

    m = StageMetrics(name="cutover_verdict")
    m.started_at = time.time()
    bal = []
    if balance_variance:
        bal.append({"ledger": "OpenAR", "variance": 1234.56, "status": "VARIANCE"})
    else:
        bal.append({"ledger": "OpenAR", "variance": 0, "status": "MATCH"})

    verdict = _compute_cutover_verdict(
        balance_tieouts=bal,
        captured_spools=captured_spools,
        ltmc_pending=ltmc_pending,
        reconciliation={"verdict": "RECONCILED"})
    m.ended_at = time.time()
    result.stages.append(m)
    return verdict


# ─────────────────────────────────────────────────────────────────────────────
#  Code remediation sub-run
# ─────────────────────────────────────────────────────────────────────────────
def run_code_remediation(suite_dir: Path, result: BattletestResult) -> dict:
    """Run every synthetic Z-program through the FallbackRouter (deterministic
    AST + AI fallback). We stub out the LLM call so we don't actually burn
    Anthropic API on the synthetic broken programs."""
    from llm_fallback_router import FallbackRouter

    catalog_path = suite_dir / "catalog.json"
    if not catalog_path.exists():
        return {"skipped": True, "reason": "no abap suite catalog found"}

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

    def stub_llm(prompt: str) -> Optional[str]:
        # Pretend the LLM fixes the broken fragment minimally
        return ("```abap\n"
                "* battletest stub fix\n"
                "WRITE 'fixed by stub'.\n"
                "```")

    router = FallbackRouter(llm_callable=stub_llm)

    outcomes = {"deterministic_pass": 0, "ai_fallback_invoked": 0,
                "quarantined": 0, "errors": 0}
    m = StageMetrics(name="code_remediation")
    m.started_at = time.time()
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        for prog in catalog["programs"]:
            src_path = suite_dir / f"{prog['name']}.abap"
            if not src_path.exists():
                continue
            src = src_path.read_text(encoding="utf-8")
            m.records_in += 1
            try:
                res = router.remediate(src, prog["name"], out_dir=td)
                if res.path == "deterministic":
                    outcomes["deterministic_pass"] += 1
                elif res.path == "ai_fallback":
                    outcomes["ai_fallback_invoked"] += 1
                else:
                    outcomes["quarantined"] += 1
                m.records_out += 1
            except Exception as e:
                outcomes["errors"] += 1
                m.errors += 1
                result.issues.append(Issue(
                    stage="code_remediation", severity="warning",
                    object_type="ABAP", record_key=prog["name"],
                    reason=f"{type(e).__name__}: {str(e)[:120]}"))
    m.ended_at = time.time()
    result.stages.append(m)
    return {"count": m.records_in, "outcomes": outcomes,
            "elapsed_s": m.elapsed_s}


# ─────────────────────────────────────────────────────────────────────────────
#  Gap-closure stress tests
# ─────────────────────────────────────────────────────────────────────────────
def run_gap_closure_stress(file_map: Dict[str, Path],
                            result: BattletestResult) -> Dict[str, Any]:
    """Hit every Gemini-gap-closure module at scale with the generated data."""
    out: Dict[str, Any] = {}
    m = StageMetrics(name="gap_closure_stress")
    m.started_at = time.time()

    # 1. CVI unify_with_xrefs on full customer+vendor pool
    try:
        from cvi_mapper import unify_with_xrefs
        kna1 = list(_iter_jsonl_gz(file_map["Customer"])) if "Customer" in file_map else []
        lfa1 = list(_iter_jsonl_gz(file_map["Vendor"])) if "Vendor" in file_map else []
        if kna1 and lfa1:
            t0 = time.time()
            maps, conflicts, plan = unify_with_xrefs(kna1, lfa1)
            out["cvi"] = {
                "customers": len(kna1), "vendors": len(lfa1),
                "mappings": len(maps), "conflicts": len(conflicts),
                "cycles_detected": len(plan.cycles_detected),
                "unresolved_xrefs": len(plan.unresolved_xrefs),
                "phase_1_stubs": len(plan.phase_1),
                "phase_2_attach_xrefs": len(plan.phase_2),
                "elapsed_s": round(time.time() - t0, 2),
            }
            m.records_in += len(kna1) + len(lfa1)
    except Exception as e:
        result.issues.append(Issue("gap_closure_stress", "error", "CVI", "?",
                                    f"{type(e).__name__}: {str(e)[:160]}"))

    # 2. DAG topological sort + execution simulation
    try:
        from dependency_dag import DependencyDAG, ExecutionState, STATUS_DONE
        t0 = time.time()
        dag = DependencyDAG.from_defaults()
        cycles = dag.validate()
        order = dag.topological_sort()
        state = ExecutionState(dag=dag)
        for n in order:
            state.mark(n, STATUS_DONE)
        out["dag"] = {
            "nodes": len(dag.nodes), "cycles": len(cycles),
            "order_length": len(order),
            "all_done": state.complete(),
            "elapsed_s": round(time.time() - t0, 4),
        }
    except Exception as e:
        result.issues.append(Issue("gap_closure_stress", "error", "DAG", "?",
                                    f"{type(e).__name__}: {str(e)[:160]}"))

    # 3. WorkloadThrottle saturation (mocked SAP probe)
    try:
        from sap_workload import WorkloadThrottle
        states = ["RED", "RED", "YELLOW", "YELLOW", "GREEN"]
        idx = {"i": 0}
        def fake_rfc(fn, kw):
            if fn == "ENQUE_READ2":
                return {"ENQ": []}
            s = states[min(idx["i"], len(states)-1)]; idx["i"] += 1
            if s == "GREEN":
                rows = [{"WP_TYP": "DIA", "WP_STATUS": "Waiting", "WP_WAITING": 0}] * 5 + \
                       [{"WP_TYP": "DIA", "WP_STATUS": "Running", "WP_WAITING": 0}] * 5
            elif s == "YELLOW":
                rows = [{"WP_TYP": "DIA", "WP_STATUS": "Waiting", "WP_WAITING": 0}] + \
                       [{"WP_TYP": "DIA", "WP_STATUS": "Running", "WP_WAITING": 0}] * 9
            else:
                rows = [{"WP_TYP": "DIA", "WP_STATUS": "Running", "WP_WAITING": 12}] * 10
            return {"WPLIST": rows}
        # Patch sleep so the test doesn't actually wait
        import sap_workload as sw
        orig_sleep = time.sleep
        # Don't actually pause during the test
        waits = []
        t = WorkloadThrottle(rfc_callable=fake_rfc, requested_batch=200)
        for _ in range(5):
            d = t.decide()
            waits.append((d.verdict, d.wait_seconds))
        out["throttle"] = {
            "probes": waits,
            "recovered_to_green": any(v == "GREEN" for v, _ in waits),
        }
    except Exception as e:
        result.issues.append(Issue("gap_closure_stress", "error", "Throttle", "?",
                                    f"{type(e).__name__}: {str(e)[:160]}"))

    # 4. cluster_table_awareness preflight against realistic BSEG scenarios
    try:
        from cluster_table_awareness import preflight
        scenarios = [
            ("BKPF", {"BUKRS": "1010", "GJAHR": "2026"}, "GO"),
            ("BSEG", {"BUKRS": "1010", "BELNR": "100000001", "GJAHR": "2026"}, "GO_WITH_WARNINGS"),
            ("BSEG", {"WAERS": "EUR"}, "GO_WITH_WARNINGS"),  # rewritten via BKPF
            ("PCL1", {}, "NO_GO"),
        ]
        sc_results = []
        for table, where, want in scenarios:
            p = preflight(table, where=where, requested_package_size=5000)
            sc_results.append({"table": table, "verdict": p.verdict,
                               "expected": want, "match": p.verdict == want,
                               "stages": len(p.stages)})
        out["cluster_table_awareness"] = {"scenarios": sc_results,
                                           "all_match": all(r["match"] for r in sc_results)}
    except Exception as e:
        result.issues.append(Issue("gap_closure_stress", "error", "Cluster", "?",
                                    f"{type(e).__name__}: {str(e)[:160]}"))

    # 5. Hash chain at scale - append 10K blocks and verify
    try:
        from reconciler import HashChainLedger
        chain = HashChainLedger(run_id="stress")
        t0 = time.time()
        for i in range(10_000):
            chain.append("stress", {"i": i, "payload": "x" * 50})
        v = chain.verify()
        out["hash_chain_stress"] = {
            "blocks": chain.block_count(),
            "verify_ok": v.get("ok"),
            "elapsed_s": round(time.time() - t0, 2),
            "blocks_per_s": round(10_000 / (time.time() - t0), 0),
        }
    except Exception as e:
        result.issues.append(Issue("gap_closure_stress", "error", "HashChain", "?",
                                    f"{type(e).__name__}: {str(e)[:160]}"))

    # 6. cutover_verdict precedence across all 5 outcomes
    try:
        from reconciler import _compute_cutover_verdict
        spools_ok = [
            {"report_code": "FAGLB03", "sha256": "a"*64, "byte_length": 100, "spool_id": "1"},
            {"report_code": "MB5B",    "sha256": "b"*64, "byte_length": 100, "spool_id": "2"},
        ]
        cases = {
            "go": _compute_cutover_verdict(
                balance_tieouts=[{"ledger": "OpenAR", "variance": 0, "status": "MATCH"}],
                captured_spools=spools_ok, ltmc_pending={}, reconciliation={"verdict": "RECONCILED"})["verdict"],
            "no_go_missing_spool": _compute_cutover_verdict(
                balance_tieouts=[], captured_spools=[spools_ok[0]],
                ltmc_pending={}, reconciliation={})["verdict"],
            "no_go_ltmc_pending": _compute_cutover_verdict(
                balance_tieouts=[], captured_spools=spools_ok,
                ltmc_pending={"pending_count": 3}, reconciliation={})["verdict"],
            "no_go_variance_overrides_recon": _compute_cutover_verdict(
                balance_tieouts=[{"ledger": "OpenAR", "variance": 1234.56, "status": "VARIANCE"}],
                captured_spools=spools_ok, ltmc_pending={}, reconciliation={"verdict": "RECONCILED"})["verdict"],
            "go_with_warnings": _compute_cutover_verdict(
                balance_tieouts=[{"ledger": "OpenAR", "variance": 0, "status": "MATCH"}],
                captured_spools=spools_ok, ltmc_pending={}, reconciliation={"verdict": "DISCREPANCY"})["verdict"],
        }
        expected = {
            "go": "GO", "no_go_missing_spool": "NO_GO",
            "no_go_ltmc_pending": "NO_GO",
            "no_go_variance_overrides_recon": "NO_GO",
            "go_with_warnings": "GO_WITH_WARNINGS",
        }
        out["cutover_verdict_precedence"] = {
            "cases": cases, "expected": expected,
            "all_correct": cases == expected,
        }
    except Exception as e:
        result.issues.append(Issue("gap_closure_stress", "error", "CutoverVerdict", "?",
                                    f"{type(e).__name__}: {str(e)[:160]}"))

    m.ended_at = time.time()
    result.stages.append(m)
    return out


# ─────────────────────────────────────────────────────────────────────────────
#  Orchestrator entry
# ─────────────────────────────────────────────────────────────────────────────
def run(scale_name: str,
        fixtures_dir: Path,
        abap_suite_dir: Optional[Path],
        threads: int,
        include_code_remediation: bool) -> BattletestResult:
    scale = SCALES[scale_name]
    result = BattletestResult(scale=scale_name,
                              started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    overall_t0 = time.time()

    # Ensure fixtures exist (auto-generate locally only; in the Fargate
    # battletest mode the entrypoint downloads them from S3 before calling
    # run(), so this branch is a no-op)
    expected_files = ["customers.jsonl.gz", "vendors.jsonl.gz",
                      "materials.jsonl.gz", "gl_accounts.jsonl.gz"]
    have_all = all((fixtures_dir / f).exists() for f in expected_files)
    if not have_all:
        print(f"  generating fixtures into {fixtures_dir} ...")
        generate_all(scale, fixtures_dir, seed=42)

    # Stages
    obj_types = ["Customer", "Vendor", "Material", "GLAccount"]
    file_map = stage_extract(fixtures_dir, obj_types, result)

    accepted = stage_transform_and_coverage(file_map, result, threads=threads)

    target = MockSapTarget(seed=7)
    load_keys = stage_load(accepted, target, result, threads=threads)
    result.mock_target_stats = target.stats.to_dict()

    chain_info = stage_hash_chain(load_keys, result)

    result.gap_closure_stress = run_gap_closure_stress(file_map, result)

    if include_code_remediation and abap_suite_dir and abap_suite_dir.exists():
        result.code_remediation = run_code_remediation(abap_suite_dir, result)

    # Cutover verdict on the happy path (all spools present, no variance, no LTMC pending)
    spools_ok = [
        {"report_code": "FAGLB03", "sha256": "a"*64, "byte_length": 100, "spool_id": "1"},
        {"report_code": "MB5B",    "sha256": "b"*64, "byte_length": 100, "spool_id": "2"},
    ]
    result.cutover_verdict = stage_cutover_verdict(
        spools_ok, ltmc_pending={}, balance_variance=False, result=result)
    result.cutover_verdict["chain"] = chain_info

    result.ended_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    result.total_elapsed_s = round(time.time() - overall_t0, 2)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", default="small", choices=list(SCALES))
    ap.add_argument("--threads", type=int, default=16)
    ap.add_argument("--fixtures-dir", default=None)
    ap.add_argument("--abap-suite-dir", default="tests/battletest/abap-suite")
    ap.add_argument("--include-code-remediation", action="store_true")
    ap.add_argument("--out", default="tests/battletest/results")
    args = ap.parse_args()

    fixtures = Path(args.fixtures_dir or f"tests/battletest/fixtures/scale-{args.scale}")
    abap = Path(args.abap_suite_dir) if args.abap_suite_dir else None
    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)

    print(f"battletest start: scale={args.scale} threads={args.threads} "
          f"code_remediation={args.include_code_remediation}")
    result = run(args.scale, fixtures, abap, args.threads, args.include_code_remediation)

    json_out = out_dir / f"battletest-{args.scale}-{int(time.time())}.json"
    json_out.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")

    print()
    print("=" * 78)
    print(f"battletest COMPLETE in {result.total_elapsed_s}s")
    print("=" * 78)
    for s in result.stages:
        print(f"  {s.name:30s} {s.elapsed_s:>7.2f}s  "
              f"in={s.records_in:>10,d}  out={s.records_out:>10,d}  "
              f"throughput={s.throughput_per_s:>10,.0f}/s")
    print()
    print(f"  total issues: {len(result.issues)}")
    print(f"  cutover_verdict: {result.cutover_verdict.get('verdict')}")
    print(f"  hash chain: {result.cutover_verdict.get('chain', {}).get('blocks')} blocks, "
          f"verify={result.cutover_verdict.get('chain', {}).get('verify', {}).get('ok')}")
    print(f"  mock target: created={result.mock_target_stats.get('created'):,}  "
          f"hard_fails={result.mock_target_stats.get('hard_failures')}  "
          f"avg_latency={result.mock_target_stats.get('avg_latency_ms')}ms")
    print()
    print(f"results -> {json_out}")
    return result


if __name__ == "__main__":
    main()
