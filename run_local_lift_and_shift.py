#!/usr/bin/env python
"""
run_local_lift_and_shift.py
============================
Local runner for the lift-and-shift pipeline (28 stages, 9 phases).

The corresponding Step Functions state machine is
``terraform/modules/step-functions/lift_and_shift_pipeline.asl.json``.
This script invokes each Lambda handler in-process, in sequence,
with the same JSON event shape Step Functions would pass.

Usage:
    python run_local_lift_and_shift.py --run-id RUN-001 \\
        --ecc-host my-ecc.local --target-host my-s4.local \\
        --through stage12c            # stop after the named stage

    python run_local_lift_and_shift.py --list-stages

Branch context:
    This script belongs on the ``aws-lift-and-shift`` branch.
    The legacy in-place SUM/DMO runner is ``run_local_pipeline.py`` on
    ``aws-branch`` and is kept for reference.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
LAMBDA_DIR = REPO_ROOT / "lambda"
sys.path.insert(0, str(LAMBDA_DIR))
sys.path.insert(0, str(LAMBDA_DIR / "utils"))

# ---------------------------------------------------------------------------
# Stage table — keep in sync with lift_and_shift_pipeline.asl.json
# Each entry: (stage_id, phase, handler_module_path, extra_event)
# ---------------------------------------------------------------------------
STAGES = [
    # PHASE 0 — ASSESS
    ("stage1",   "ASSESS",     "discovery-engine.handler",                     {}),
    ("stage2",   "ASSESS",     "sizing-advisor.handler",                       {}),
    ("stage3",   "ASSESS",     "object-router.handler",                        {}),
    # PHASE 1 — PROVISION
    ("stage4",   "PROVISION",  "target-provisioner.handler",                   {"mode": "sandbox"}),
    ("gate1",    "PROVISION",  None,                                           {"gate": "basis_handover"}),
    ("stage5",   "PROVISION",  "basis-validator.handler",                      {}),
    # PHASE 2 — CODE
    ("stage6",   "CODE",       "code-analyzer.handler",                        {"mode": "extract"}),
    ("stage7",   "CODE",       "code-analyzer.handler",                        {"mode": "remediate"}),
    ("stage8",   "CODE",       "transport-artifact-builder.handler",           {"object_kind": "code"}),
    ("stage9a",  "CODE",       "transport-file-placer.handler",                {}),
    ("stage9b",  "CODE",       "transport-import-executor.handler",            {}),
    ("stage9c",  "CODE",       "transport-import-verifier.handler",            {}),
    # PHASE 3 — CONFIG
    ("stage10",  "CONFIG",     "config-replicator.handler",                    {"mode": "extract"}),
    ("stage11",  "CONFIG",     "bc-set-builder.handler",                       {}),
    ("stage12",  "CONFIG",     "transport-artifact-builder.handler",           {"object_kind": "config"}),
    ("stage12a", "CONFIG",     "transport-file-placer.handler",                {}),
    ("stage12b", "CONFIG",     "transport-import-executor.handler",            {}),
    ("stage12c", "CONFIG",     "transport-import-verifier.handler",            {}),
    # PHASE 4 — DATA-PREP
    ("stage13",  "DATA_PREP",  "data-migrator.handler",                        {"mode": "extract"}),
    ("stage14",  "DATA_PREP",  "data-hygiene.handler",                         {}),
    ("stage15",  "DATA_PREP",  "data-migrator.handler",                        {"mode": "generate_templates"}),
    # PHASE 5 — DATA-LOAD (driven by object-router DAG)
    ("stage16",  "DATA_LOAD",  "migration-cockpit-orchestrator.handler",       {}),
    ("stage17",  "DATA_LOAD",  "ltmom-orchestrator.handler",                   {}),
    ("stage18",  "DATA_LOAD",  "idoc-orchestrator.handler",                    {}),
    # PHASE 6 — VALIDATE
    ("stage19",  "VALIDATE",   "migration-validator.handler",                  {}),
    ("stage20",  "VALIDATE",   "test-generator.handler",                       {}),
    ("stage21",  "VALIDATE",   "migration-completeness-analyzer.handler",      {}),
    ("gate2",    "VALIDATE",   None,                                           {"gate": "pre_cutover"}),
    # PHASE 7 — CUTOVER (ECC-lock MUST precede final delta)
    ("stage22",  "CUTOVER",    "cutover-orchestrator.handler",                 {"action": "lock_ecc"}),
    ("stage23",  "CUTOVER",    "delta-extractor.handler",                      {}),
    ("stage24",  "CUTOVER",    "migration-cockpit-orchestrator.handler",       {"mode": "delta_load"}),
    ("stage25",  "CUTOVER",    "migration-validator.handler",                  {"mode": "final"}),
    ("gate3",    "CUTOVER",    None,                                           {"gate": "final_go_live"}),
    ("stage26",  "CUTOVER",    "integration-activator.handler",                {}),
    # PHASE 8 — RUN
    ("stage27",  "RUN",        "pdf_report_generator.handler",                 {}),
]


def _load(module_path: str):
    # module path looks like 'object-router.handler' — Python can't import a
    # package with a hyphen, so we resolve to the file directly.
    pkg, mod = module_path.split(".", 1)
    pkg_dir = LAMBDA_DIR / pkg
    file_path = pkg_dir / f"{mod}.py"
    if not file_path.exists():
        raise FileNotFoundError(f"Handler not found: {file_path}")
    spec = importlib.util.spec_from_file_location(f"{pkg}_{mod}", file_path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(pkg_dir))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _run_gate(stage_id: str, gate: str, event: dict) -> dict:
    print(f"  [MANUAL GATE] {gate} — auto-approve in local mode (--no-gates to skip prompt)")
    return {"gate": gate, "approved": True, "auto": True}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", default=f"local-{int(time.time())}")
    p.add_argument("--ecc-host", default=os.getenv("ECC_HOST", ""))
    p.add_argument("--target-host", default=os.getenv("TARGET_HOST", ""))
    p.add_argument("--from-stage", default=None, help="Skip stages before this id")
    p.add_argument("--through", default=None, help="Stop after this stage id")
    p.add_argument("--only", default=None, help="Run only this single stage")
    p.add_argument("--list-stages", action="store_true")
    p.add_argument("--dry-run", action="store_true",
                   help="Print stage plan without invoking handlers")
    args = p.parse_args()

    if args.list_stages:
        for sid, phase, mod, extra in STAGES:
            print(f"  {sid:<10} {phase:<11} {mod or '(manual gate)'}")
        return 0

    event = {
        "run_id": args.run_id,
        "ecc_host": args.ecc_host,
        "target_host": args.target_host,
        "phase_telemetry": {},
    }

    started = args.from_stage is None
    cur_phase = None
    rc = 0
    for sid, phase, mod, extra in STAGES:
        if args.only and sid != args.only:
            continue
        if not started:
            if sid == args.from_stage:
                started = True
            else:
                continue
        if phase != cur_phase:
            print(f"\n=== PHASE {phase} ===")
            cur_phase = phase

        print(f"[{sid}] {mod or '(manual gate)'}")
        event_for_stage = {**event, **extra}

        if args.dry_run:
            print("  (dry-run)")
            if args.through and sid == args.through:
                break
            continue

        try:
            if mod is None:
                result = _run_gate(sid, extra.get("gate", sid), event_for_stage)
            else:
                module = _load(mod)
                handler = getattr(module, "lambda_handler", None) or getattr(module, "handler", None)
                if handler is None:
                    raise AttributeError(f"No lambda_handler/handler in {mod}")
                result = handler(event_for_stage, None)
            print(f"  status={result.get('status', 'unknown')}")
            event[sid] = result
            if result.get("status") in ("blocked", "error", "failed"):
                print(f"  *** stage halted pipeline: {result.get('reason')}")
                rc = 2
                break
        except Exception as e:
            print(f"  *** EXCEPTION in {sid}: {e}")
            traceback.print_exc()
            rc = 3
            break

        if args.through and sid == args.through:
            break
        if args.only:
            break

    print(f"\nRun {event['run_id']} finished rc={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
