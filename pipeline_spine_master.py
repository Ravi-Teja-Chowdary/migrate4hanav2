#!/usr/bin/env python
"""
pipeline_spine_master.py — Migrate4HANA unified master orchestrator
====================================================================
Stitches the four execution layers into one resilient spine and emits the
live progress state the Web UI Project Tracker renders.

    Phase 1  NATUVION   selective in-system carve-out      (extraction)
    Phase 2  SYNITI     transformation + self-healing      (data spine)
    Phase 3  SMARTSHIFT deterministic code fix + AI fail-safe
    Phase 4  GOVERNANCE mock-ATC validation + UI progress state

Design principles honoured here:

* **Deterministic-First, AI-as-a-Fail-Safe** — layers 1-3 run programmatically;
  the LLM is only reached inside layer 3's FallbackRouter for fragments the
  deterministic parser cannot resolve.
* **Local ⇄ Cloud parity** — `run(payload)` consumes the *same* state-machine
  payload whether invoked by `run_local_lift_and_shift.py` in-process or by the
  AWS Step Functions state machine. The payload schema is the contract.
* **SAP gateway throttling** — every RFC-bound action is gated by `RFCThrottle`
  (bounded concurrency + minimum inter-call interval) so a high-volume run can
  never self-inflict a Denial-of-Service on the source/target SAP instance.
* **Resilience** — each phase is guarded; a phase failure is captured as a
  non-zero return code, progress is still flushed, and downstream phases are
  marked skipped instead of crashing the process.

The orchestrator is import-safe and runnable offline: pass ``fixtures`` in the
payload to drive it without a live SAP system (used by the self-test). In a real
run the fixtures are replaced by carve-out / RFC reads against the live hosts.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

REPO_ROOT = Path(__file__).resolve().parent
# Make the sibling layer modules importable regardless of cwd.
for p in (REPO_ROOT, REPO_ROOT / "agent", REPO_ROOT / "lambda" / "code-analyzer",
          REPO_ROOT / "lambda" / "utils"):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)


# ════════════════════════════════════════════════════════════════════════════
#  SAP gateway throttle — bounded concurrency + paced inter-call interval
# ════════════════════════════════════════════════════════════════════════════
class RFCThrottle:
    """Protect the SAP gateway from a self-inflicted DoS under volume.

    Two independent guards:
      * a semaphore caps the number of *concurrent* RFC calls in flight;
      * a monotonic pacer enforces a minimum interval between call *starts*.

    Use as a context manager around every RFC-bound unit of work::

        with throttle.slot():
            conn.call("BAPI_…", ...)
    """

    def __init__(self, max_concurrent: int = 4, min_interval_s: float = 0.0):
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        self.max_concurrent = max_concurrent
        self.min_interval_s = max(0.0, float(min_interval_s))
        self._sem = threading.Semaphore(max_concurrent)
        self._pace_lock = threading.Lock()
        self._last_start = 0.0
        self.calls = 0
        self.wait_total_s = 0.0

    @contextmanager
    def slot(self):
        acquired_at = time.monotonic()
        self._sem.acquire()
        try:
            if self.min_interval_s:
                with self._pace_lock:
                    now = time.monotonic()
                    wait = self.min_interval_s - (now - self._last_start)
                    if wait > 0:
                        time.sleep(wait)
                    self._last_start = time.monotonic()
            self.wait_total_s += time.monotonic() - acquired_at
            self.calls += 1
            yield
        finally:
            self._sem.release()

    def stats(self) -> dict:
        return {"max_concurrent": self.max_concurrent,
                "min_interval_s": self.min_interval_s,
                "rfc_calls": self.calls,
                "throttle_wait_s": round(self.wait_total_s, 4)}


# ════════════════════════════════════════════════════════════════════════════
#  Progress model consumed by the Web UI Project Tracker
# ════════════════════════════════════════════════════════════════════════════
SPINE_STAGES = [
    ("natuvion_carveout",  "Natuvion — Selective Carve-Out"),
    ("syniti_dataspine",   "Syniti — Transform & Self-Heal"),
    ("smartshift_codefix", "SmartShift — Code Fix & AI Fail-Safe"),
    ("governance_atc",     "Governance — ATC Validation & Packaging"),
]


@dataclass
class StageState:
    key: str
    name: str
    status: str = "queued"        # queued | running | completed | failed | skipped
    rc: Optional[int] = None      # SAP-style return code; 0 = success
    detail: dict = field(default_factory=dict)
    started: Optional[str] = None
    ended: Optional[str] = None
    elapsed_s: Optional[float] = None


class ProgressTracker:
    """Owns the live state file the UI polls (start/end boards + stage kanban)."""

    def __init__(self, run_dir: Path, source: dict, target: dict):
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path = run_dir / "progress.json"
        self.source = source
        self.target = target
        self.stages: dict[str, StageState] = {
            k: StageState(k, n) for k, n in SPINE_STAGES}
        self.order = [k for k, _ in SPINE_STAGES]
        self._t0: dict[str, float] = {}
        self.flush()

    def start(self, key: str) -> None:
        st = self.stages[key]
        st.status = "running"
        st.started = _now()
        self._t0[key] = time.monotonic()
        self.flush()

    def finish(self, key: str, rc: int, detail: dict) -> None:
        st = self.stages[key]
        st.rc = rc
        st.status = "completed" if rc == 0 else "failed"
        st.detail = detail
        st.ended = _now()
        if key in self._t0:
            st.elapsed_s = round(time.monotonic() - self._t0[key], 3)
        self.flush()

    def skip(self, key: str, reason: str) -> None:
        st = self.stages[key]
        st.status = "skipped"
        st.detail = {"reason": reason}
        self.flush()

    def percent(self) -> float:
        done = sum(1 for s in self.stages.values()
                   if s.status in ("completed", "skipped"))
        return round(100.0 * done / len(self.stages), 1)

    def snapshot(self) -> dict:
        return {
            "updated": _now(),
            "connectivity": {
                "source": {**self.source, "role": "Source ECC"},
                "target": {**self.target, "role": "Target S/4HANA RISE"},
            },
            "percent_complete": self.percent(),
            "stages": [asdict(self.stages[k]) for k in self.order],
        }

    def flush(self) -> None:
        self.path.write_text(json.dumps(self.snapshot(), indent=2),
                             encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ════════════════════════════════════════════════════════════════════════════
#  The master orchestrator
# ════════════════════════════════════════════════════════════════════════════
class PipelineSpineMaster:
    """Run the four-layer spine for one migration payload."""

    def __init__(self, staging_root: str | os.PathLike = None):
        self.staging_root = Path(
            staging_root or os.environ.get(
                "M4H_STAGING_ROOT",
                REPO_ROOT / "local-staging" / "spine-runs"))

    # -- public entry: identical contract local & cloud ----------------------
    def run(self, payload: dict) -> dict:
        """Execute the spine. ``payload`` is the shared state-machine contract.

        Returns the final aggregated state (also persisted as ``state.json``).
        Never raises on data/SAP errors — they surface as phase return codes.
        """
        payload = self._validate(payload)
        run_id = payload["run_id"]
        run_dir = self.staging_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        throttle = RFCThrottle(**payload["throttle"])
        tracker = ProgressTracker(run_dir, payload["source"], payload["target"])

        state = {
            "run_id": run_id,
            "mode": payload["mode"],
            "started": _now(),
            "source": payload["source"],
            "target": payload["target"],
            "phases": {},
        }

        # Phase 1 — Natuvion carve-out
        ok, p1 = self._guarded(tracker, "natuvion_carveout",
                               self._phase_natuvion, payload, run_dir, throttle)
        state["phases"]["natuvion"] = p1

        # Phase 2 — Syniti data spine (needs carve-out output / fixtures)
        if ok:
            ok2, p2 = self._guarded(tracker, "syniti_dataspine",
                                    self._phase_syniti, payload, run_dir, throttle, p1)
            state["phases"]["syniti"] = p2
        else:
            tracker.skip("syniti_dataspine", "upstream carve-out failed")
            ok2 = False

        # Phase 3 — SmartShift code fix + AI fail-safe (independent of data RC)
        ok3, p3 = self._guarded(tracker, "smartshift_codefix",
                                self._phase_smartshift, payload, run_dir, throttle)
        state["phases"]["smartshift"] = p3

        # Phase 4 — Governance / ATC validation + UI progress finalisation
        _, p4 = self._guarded(tracker, "governance_atc",
                              self._phase_governance, payload, run_dir,
                              throttle, p2 if ok2 else {}, p3)
        state["phases"]["governance"] = p4

        state["throttle"] = throttle.stats()
        state["percent_complete"] = tracker.percent()
        state["ended"] = _now()
        state["overall_rc"] = 0 if all(
            (ph.get("rc", 1) == 0) for ph in state["phases"].values()) else 1
        (run_dir / "state.json").write_text(
            json.dumps(state, indent=2, default=str), encoding="utf-8")
        tracker.flush()
        return state

    # -- phase implementations ------------------------------------------------
    def _phase_natuvion(self, payload, run_dir, throttle) -> tuple[int, dict]:
        """Generate (and, with a live conn, deploy+run) carve-out ABAP per table."""
        from in_system_agent_generator import InSystemAgentGenerator
        gen = InSystemAgentGenerator()
        carve = payload["scope"].get("carve_out", [])
        conn = payload.get("_live_source_conn")          # set only in live runs
        # Pillar 1 — elastic compute dispatcher: a carve-out whose scope exceeds the
        # row threshold is routed to Fargate (auto-scaled memory) instead of Lambda.
        try:
            from scaling import ComputeDispatcher
            dispatcher = ComputeDispatcher()
        except Exception:
            dispatcher = None
        programs, errors, fargate_routed = [], [], 0
        out_dir = run_dir / "carveout"
        out_dir.mkdir(parents=True, exist_ok=True)
        for spec in carve:
            try:
                g = gen.generate(
                    spec["table"], bukrs=spec.get("bukrs", ""),
                    gjahr=spec.get("gjahr", ""),
                    package_size=int(spec.get("package_size", 50000)),
                    pull_headers=spec.get("pull_headers", True))
                (out_dir / f"{g['program']}.abap").write_text(
                    g["source"], encoding="utf-8")
                rec = {"table": spec["table"], "program": g["program"],
                       "meta": g["meta"], "deployed": False}
                if dispatcher is not None:
                    decision = dispatcher.decide(spec["table"], int(spec.get("est_rows", 0) or 0))
                    rec["compute"] = decision.to_dict()
                    if decision.target == "fargate":
                        fargate_routed += 1
                if conn is not None:               # live carve-out, paced by throttle
                    with throttle.slot():
                        res = gen.deploy_and_run(conn, spec["table"],
                                                 **{k: v for k, v in spec.items()
                                                    if k != "table"})
                    rec["deployed"] = bool(res.get("ok"))
                    rec["run_result"] = res
                programs.append(rec)
            except Exception as e:  # noqa: BLE001
                errors.append({"table": spec.get("table"), "error": str(e)})
        rc = 0 if not errors else 2
        return rc, {"rc": rc, "programs": programs, "errors": errors,
                    "carved_tables": len(programs), "fargate_routed": fargate_routed}

    def _phase_syniti(self, payload, run_dir, throttle, p1) -> tuple[int, dict]:
        """Cleanse, self-heal, ledger the extracted entity trees."""
        from data_spine_orchestrator import DataSpineOrchestrator, ReferenceData
        ref = ReferenceData.from_discovered_config(
            payload.get("reference_config", {})) \
            if payload.get("reference_config") else \
            ReferenceData(**payload.get("reference_data", {}))
        spine = DataSpineOrchestrator(run_dir / "dataspine", reference=ref)
        fixtures = payload.get("fixtures", {}).get("trees", {})
        reports, errors = [], []

        # DAG-ordered iteration (Gemini gap #8). Reorders the requested object
        # types so masters (Material, GLAccount, CostCenter, BusinessPartner)
        # complete before transactionals (SalesOrder, OpenAR/AP, etc). The
        # `dag_state` block is added to the phase summary so downstream phases
        # and operators can see the order + failure-propagation map.
        requested = list(payload["scope"].get("entity_trees", []))
        dag_state_block = None
        try:
            sys.path.insert(0, str(REPO_ROOT / "lambda" / "utils"))
            from dependency_dag import (DependencyDAG, ExecutionState,
                                        STATUS_DONE, STATUS_FAILED)
            dag = DependencyDAG.from_defaults()
            ordered = dag.topological_sort(scope=requested) if requested else []
            # Keep only what was actually requested (transitive deps may be
            # included even if the caller did not list them; we surface them
            # but don't synthesise fixtures for them).
            ordered = [o for o in ordered if o in requested]
            dag_audit = []
            state = ExecutionState(dag=dag).with_audit(
                lambda obj, s, ts: dag_audit.append({"object": obj, "status": s, "ts": ts}))
            objects_iter = ordered
        except Exception as _e:
            state = None
            objects_iter = requested
            dag_audit = []

        for obj in objects_iter:
            if state is not None:
                state.mark(obj, "running")
            tables = fixtures.get(obj)
            if tables is None:
                errors.append({"object": obj, "error": "no extracted tables "
                               "available (live carve-out read not wired / no fixture)"})
                if state is not None:
                    state.mark(obj, "failed")
                continue
            try:
                rep = spine.process_tree(obj, tables)
                reports.append({k: v for k, v in rep.items() if k != "cleansed"})
                if state is not None:
                    state.mark(obj, "done")
            except Exception as e:  # noqa: BLE001
                errors.append({"object": obj, "error": str(e)})
                if state is not None:
                    state.mark(obj, "failed")

        if state is not None:
            dag_state_block = {
                "execution_order": objects_iter,
                "status": dict(state.status),
                "blocked_by_failures": state.downstream_blocked_by_failure(),
                "transitions": dag_audit,
            }

        rc = 0 if reports and not errors else (1 if errors and not reports else 0)
        healed = sum(r["counters"]["healed"] for r in reports)
        reused = sum(r["reused_from_ledger"] for r in reports)
        summary = {"rc": rc, "objects": reports, "errors": errors,
                   "total_healed": healed, "total_reused_from_ledger": reused}
        if dag_state_block is not None:
            summary["dag_state"] = dag_state_block
        return rc, summary

    def _phase_smartshift(self, payload, run_dir, throttle) -> tuple[int, dict]:
        """Remediate custom ABAP deterministically with AI fail-safe + ATC gate."""
        from llm_fallback_router import FallbackRouter
        router = FallbackRouter()
        objects = payload.get("fixtures", {}).get("abap", {})
        scoped = payload["scope"].get("code_objects", list(objects.keys()))
        out_dir = run_dir / "remediation"
        results, errors = [], []
        for name in scoped:
            src = objects.get(name)
            if src is None:
                errors.append({"object": name, "error": "no ABAP source "
                               "available (live extract not wired / no fixture)"})
                continue
            try:
                r = router.remediate(src, name, out_dir)
                results.append({"object": name, "path": r.path,
                                "ai_fixes": r.ai_fixes,
                                "atc": r.atc.get("verdict"),
                                "governance": r.governance})
            except Exception as e:  # noqa: BLE001
                errors.append({"object": name, "error": str(e)})
        transported = sum(1 for r in results if r["governance"] == "transported")
        quarantined = sum(1 for r in results if r["governance"] == "quarantined")
        rc = 0 if not errors else 2
        return rc, {"rc": rc, "objects": results, "errors": errors,
                    "transported": transported, "quarantined": quarantined}

    def _phase_governance(self, payload, run_dir, throttle, p2, p3) -> tuple[int, dict]:
        """Aggregate ATC verdicts + data integrity into a single go/no-go view."""
        code_quarantined = (p3 or {}).get("quarantined", 0)
        data_errors = len((p2 or {}).get("errors", []))
        # An object tree with quarantined orphans is informational, not blocking.
        verdict = "GO" if (code_quarantined == 0 and data_errors == 0) else "REVIEW"
        rc = 0 if verdict == "GO" else 1
        summary = {
            "rc": rc,
            "verdict": verdict,
            "code_objects_transported": (p3 or {}).get("transported", 0),
            "code_objects_quarantined": code_quarantined,
            "data_objects_processed": len((p2 or {}).get("objects", [])),
            "data_self_healed": (p2 or {}).get("total_healed", 0),
        }
        (run_dir / "go_no_go.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8")
        return rc, summary

    # -- guard wrapper --------------------------------------------------------
    def _guarded(self, tracker: ProgressTracker, stage_key: str,
                 fn: Callable, *args) -> tuple[bool, dict]:
        tracker.start(stage_key)
        try:
            rc, detail = fn(*args)
        except Exception as e:  # noqa: BLE001 — a phase must never crash the spine
            detail = {"rc": 99, "error": str(e),
                      "trace": traceback.format_exc()}
            rc = 99
        tracker.finish(stage_key, rc, detail)
        return rc == 0, {"rc": rc, **{k: v for k, v in detail.items() if k != "rc"}}

    # -- payload contract -----------------------------------------------------
    def _validate(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dict (the state-machine contract)")
        p = dict(payload)
        p.setdefault("run_id", "RUN-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        p.setdefault("mode", "local")
        p.setdefault("source", {"host": "ecc.local", "sysnr": "00", "client": "100"})
        p.setdefault("target", {"host": "s4.rise", "sysnr": "00", "client": "100"})
        p.setdefault("scope", {})
        p["scope"].setdefault("carve_out", [])
        p["scope"].setdefault("entity_trees", [])
        p["scope"].setdefault("code_objects", [])
        thr = dict(p.get("throttle") or {})
        thr.setdefault("max_concurrent", int(os.environ.get("M4H_MAX_RFC", "4")))
        thr.setdefault("min_interval_s",
                       float(os.environ.get("M4H_RFC_MIN_INTERVAL", "0.0")))
        p["throttle"] = thr
        return p


# Step Functions / Lambda-compatible entry (cloud parity)
def lambda_handler(event, _context=None):
    return PipelineSpineMaster().run(event or {})


# ════════════════════════════════════════════════════════════════════════════
#  Self-test — full 4-phase spine, offline (fixtures), proves progress + RCs.
# ════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate4HANA master spine")
    parser.add_argument("--payload", help="path to a JSON payload file")
    parser.add_argument("--selftest", action="store_true",
                        help="run the offline self-test")
    args = parser.parse_args()

    if args.payload:
        data = json.loads(Path(args.payload).read_text(encoding="utf-8"))
        out = PipelineSpineMaster().run(data)
        print(json.dumps(out, indent=2, default=str))
        sys.exit(out.get("overall_rc", 0))

    # default: self-test
    print("=" * 78)
    print("pipeline_spine_master — self-test (offline, fixtures)")
    print("=" * 78)

    payload = {
        "run_id": "SELFTEST-001",
        "mode": "local",
        "source": {"host": "192.168.100.10", "sysnr": "00", "client": "100",
                   "system": "ECC Y01"},
        "target": {"host": "13.220.175.153", "sysnr": "00", "client": "100",
                   "system": "S/4HANA S4H (RISE)"},
        "scope": {
            "carve_out": [
                {"table": "ACDOCA", "bukrs": "1710", "gjahr": "2024",
                 "package_size": 50000},
                {"table": "BSEG", "bukrs": "1710", "gjahr": "2024"},
            ],
            "entity_trees": ["BusinessPartner"],
            "code_objects": ["ZCLEAN", "ZBROKEN"],
        },
        "throttle": {"max_concurrent": 4, "min_interval_s": 0.0},
        "reference_data": {
            "valid": {"PRCTR": ["YB600", "YB700"]},
            "defaults": {"PRCTR": "YB600"},
        },
        "fixtures": {
            "trees": {
                "BusinessPartner": {
                    "BUT000": [
                        {"PARTNER": "BP01", "NAME_ORG1": "Acme", "PRCTR": "YB600"},
                        {"PARTNER": "BP02", "NAME_ORG1": "Globex", "PRCTR": "9999"},
                    ],
                    "BUT020": [
                        {"PARTNER": "BP01", "ADDRNUMBER": "0001"},
                        {"PARTNER": "BP99", "ADDRNUMBER": "0099"},   # orphan
                    ],
                    "BUT100": [{"PARTNER": "BP01", "RLTYP": "FLCU01"}],
                }
            },
            "abap": {
                "ZCLEAN": ("REPORT zclean.\n"
                           "SELECT matnr FROM mara INTO TABLE @DATA(lt).\n"
                           "LOOP AT lt INTO DATA(ls).\n  WRITE ls-matnr.\nENDLOOP.\n"),
                "ZBROKEN": ("REPORT zbroken.\n"
                            "DATA lt TYPE STANDARD TABLE OF mara.\n"
                            "SELECT * FROM mara INTO TABLE lt.\n"),
            },
        },
    }

    master = PipelineSpineMaster()
    result = master.run(payload)

    print(f"\nrun_id          : {result['run_id']}  mode={result['mode']}")
    print(f"START board     : {result['source'].get('system')} "
          f"@ {result['source']['host']}")
    print(f"END board       : {result['target'].get('system')} "
          f"@ {result['target']['host']}")
    print(f"percent_complete: {result['percent_complete']}%   "
          f"overall_rc={result['overall_rc']}")
    print("\nPhase return codes:")
    for name, ph in result["phases"].items():
        print(f"  {name:12s} rc={ph.get('rc')}  "
              f"{ {k: v for k, v in ph.items() if k not in ('rc','trace','errors','objects','programs')} }")
    syn = result["phases"]["syniti"]
    smart = result["phases"]["smartshift"]
    gov = result["phases"]["governance"]
    print(f"\nSyniti     : healed={syn.get('total_healed')} "
          f"reused={syn.get('total_reused_from_ledger')}")
    print(f"SmartShift : transported={smart.get('transported')} "
          f"quarantined={smart.get('quarantined')}")
    print(f"Governance : verdict={gov.get('verdict')}")
    print(f"Throttle   : {result['throttle']}")

    assert result["phases"]["natuvion"]["rc"] == 0, "carve-out should succeed"
    assert syn.get("total_healed", 0) >= 1, "expected at least one self-heal"
    assert smart.get("transported", 0) >= 1, "expected at least one transport"
    print(f"\nOK - 4-phase spine ran end to end. progress.json + state.json under "
          f"{master.staging_root / result['run_id']}")
