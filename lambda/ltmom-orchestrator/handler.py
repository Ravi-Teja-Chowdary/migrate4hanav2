"""
ltmom-orchestrator — Phase 5, Stage 17
=======================================
Custom-object lane. LTMOM model creation is intentionally manual_gate;
once a model is built by Basis, this Lambda hands off execution to the
MC orchestrator (LTMOM runtime IS Migration Cockpit).
"""
import json
import logging
import os
import sys
import boto3

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "utils")))
from logger import log_stage_event  # type: ignore

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
STAGING_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hana-staging-dev")


def lambda_handler(event, context):
    run_id = event.get("run_id", "local")
    obj = event["object"]
    spec = event.get("design_spec", {})
    model_built = event.get("model_already_built", False)

    log_stage_event(run_id, "ltmom-orchestrator", "started",
                    {"object": obj, "model_built": model_built})

    runbook = _build_design_runbook(obj, spec)
    runbook_key = f"runs/{run_id}/ltmom/{obj}/design.md"
    s3.put_object(Bucket=STAGING_BUCKET, Key=runbook_key, Body=runbook.encode())

    if not model_built:
        log_stage_event(run_id, "ltmom-orchestrator", "manual_gate",
                        {"object": obj, "runbook": f"s3://{STAGING_BUCKET}/{runbook_key}"})
        return {"status": "manual_gate", "object": obj,
                "instruction": "Build LTMOM object per spec, then re-invoke with model_already_built=true",
                "runbook": f"s3://{STAGING_BUCKET}/{runbook_key}"}

    log_stage_event(run_id, "ltmom-orchestrator", "delegating_to_mc", {"object": obj})
    return {"status": "delegate_to_mc", "object": obj,
            "next_lambda": "migration-cockpit-orchestrator",
            "mc_project": event.get("mc_project", "M4H_CUSTOM_OBJECTS"),
            "runbook": f"s3://{STAGING_BUCKET}/{runbook_key}"}


def _build_design_runbook(obj, spec) -> str:
    fields = "\n".join(f"  - {f.get('name')}: {f.get('type')}  ({f.get('source_table', '')})"
                       for f in spec.get("fields", []))
    return f"""# LTMOM Design Spec — {obj}

## Source structure
{spec.get('source_table', '?')}

## Target structure
{spec.get('target_table', '?')}

## Fields
{fields or '  (define in LTMOM)'}

## Build steps (in target system)
1. Open transaction LTMOM.
2. Project: `{spec.get('project', 'M4H_CUSTOM_OBJECTS')}`.
3. New migration object: `{obj}`.
4. Define source/target structures.
5. Map fields; add transformation rules.
6. Activate.
7. Re-invoke this Lambda with `model_already_built=true`.

LTMOM model creation is intentionally manual — it requires functional
judgement (rule design, error handling, look-ups). Once activated, the
runtime executes through MC, so support coverage matches MC.
"""
