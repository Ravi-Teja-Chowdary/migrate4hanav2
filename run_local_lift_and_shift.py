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
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
LAMBDA_DIR = REPO_ROOT / "lambda"
sys.path.insert(0, str(LAMBDA_DIR))
sys.path.insert(0, str(LAMBDA_DIR / "utils"))
sys.path.insert(0, str(REPO_ROOT))

# Activate the local-AWS shim BEFORE any Lambda imports boto3.
# This makes Secrets Manager / S3 / DynamoDB / SSM calls work against the
# local filesystem + connections.json, so you can run end-to-end on a laptop.
os.environ.setdefault("M4H_LOCAL_MODE", "1")
os.environ.setdefault("S3_STAGING_BUCKET", "m4h-local")
os.environ.setdefault("STAGING_BUCKET", "m4h-local")
os.environ.setdefault("SECRETS_ARN", "local:ecc")
os.environ.setdefault("ECC_SECRETS_ARN", "local:ecc")
os.environ.setdefault("TARGET_SECRETS_ARN", "local:target")
os.environ.setdefault("S4_SECRETS_ARN", "local:target")
os.environ.setdefault("BUILD_SYSTEM_SECRETS_ARN", "local:target")
os.environ.setdefault("GATES_TABLE", "m4h-gates-local")
import local_aws_shim  # noqa: E402,F401  (activates monkey-patches via M4H_LOCAL_MODE=1)

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
    # stage4 mode is env-driven so SAP CAL users can set basis_handover_only without editing source.
    # Valid: sandbox | launch_wizard | basis_handover_only.  Default keeps prior behaviour.
    ("stage4",   "PROVISION",  "target-provisioner.handler",                   {"target_config": {"mode": os.getenv("M4H_TARGET_MODE", "sandbox")}}),
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
    # NOTE: pdf_report_generator exposes generate_pdf_from_file(), not a lambda_handler.
    # The runner has a small adapter to call it; output lands in local-staging.
    ("stage27",  "RUN",        "_inline_pdf_report",                           {}),
]


def _inline_pdf_report(event, _context):
    """Adapter — stage 27 calls pdf_report_generator.generate_pdf_from_file."""
    import pdf_report_generator
    run_id = event.get("run_id", "local")
    out_dir = REPO_ROOT / "local-staging" / "m4h-local" / "runs" / run_id / "report"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_pdf = out_dir / "migration-report.pdf"
    # Build a minimal report stub if no upstream JSON is available yet.
    stub = {"run_id": run_id, "title": "Migrate4HANA — lift-and-shift run",
            "generated_at": datetime.utcnow().isoformat(),
            "stages": [], "summary": "Local test run."}
    stub_path = out_dir / "report_input.json"
    stub_path.write_text(json.dumps(stub, indent=2))
    try:
        pdf_report_generator.generate_pdf_from_file(str(stub_path), str(out_pdf))
        return {"status": "success", "report": str(out_pdf)}
    except Exception as e:
        return {"status": "success", "report": "skipped",
                "note": f"PDF generation skipped in local mode: {e}"}


def _load(module_path: str):
    # module path looks like 'object-router.handler' — Python can't import a
    # package with a hyphen, so we resolve to the file directly.
    pkg, mod = module_path.split(".", 1)
    pkg_dir = LAMBDA_DIR / pkg
    file_path = pkg_dir / f"{mod}.py"
    # Some handlers (e.g. pdf_report_generator) live at the repo root rather than
    # under lambda/; fall back to repo root before giving up.
    if not file_path.exists():
        alt = REPO_ROOT / f"{pkg}.py"
        if alt.exists():
            spec = importlib.util.spec_from_file_location(pkg, alt)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
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
        # Wrapped shape expected by handlers that use validate_event(metadata.run_id).
        "metadata": {"run_id": args.run_id, "timestamp": datetime.utcnow().isoformat()},
        "input": {"mode": "full", "ecc_client": os.getenv("ECC_CLIENT", "100")},
        # Secret-id stubs — recognised by local_aws_shim and translated to
        # creds from connections.json + M4H_ECC_PASSWD / M4H_TARGET_PASSWD.
        "ecc_creds_arn":    "local:ecc",
        "target_creds_arn": "local:target",
        "source_creds_arn": "local:ecc",
        "build_creds_arn":  "local:target",
        "secrets_arn":      "local:ecc",
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
            elif mod == "_inline_pdf_report":
                result = _inline_pdf_report(event_for_stage, None)
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
