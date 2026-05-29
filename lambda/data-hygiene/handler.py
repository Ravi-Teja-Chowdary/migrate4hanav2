"""
data-hygiene — Phase 4, Stage 14
==================================
Data quality, cleansing, and integrity before migration. This stage embeds the
**Syniti-class data spine** (data_spine_orchestrator.DataSpineOrchestrator):

- Multi-table entity-tree foreign-key integrity (e.g. Business Partner
  BUT000 / BUT020 / BUT100) — child rows whose parent is missing are quarantined,
  never silently loaded.
- Deterministic self-healing of orphaned organisational attributes (profit
  center, company code, …) against target configuration reference data.
- Cryptographic (SHA-256) append-only idempotency ledger so a re-run resumes
  instantly and never re-processes a record.

It operates on real extracted entity-tree data (no mock). When no entity-tree
data is available (e.g. an extract-only assessment pass) it reports
`objects_processed: 0` honestly rather than fabricating results.

Entity-tree input is taken from `event["entity_trees"]` (object → {table: [rows]})
or read from `runs/<run_id>/data-migrator/entity_trees.json` in staging if present.
"""
import json
import logging
import os
import sys
import tempfile

import boto3

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "utils")))
# Repo root, so the Syniti-class data spine engine is importable.
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from logger import log_stage_event  # type: ignore

try:
    from data_spine_orchestrator import DataSpineOrchestrator, ReferenceData  # type: ignore
except Exception:  # pragma: no cover
    DataSpineOrchestrator = None
    ReferenceData = None

logger = logging.getLogger()
logger.setLevel(logging.INFO)
s3 = boto3.client("s3")
STAGING_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hana-staging-dev")


def _read_extracted_trees(run_id: str) -> dict:
    """Read entity-tree JSON emitted upstream, if any. Returns {} when absent."""
    key = f"runs/{run_id}/data-migrator/entity_trees.json"
    try:
        body = s3.get_object(Bucket=STAGING_BUCKET, Key=key)["Body"].read()
        data = json.loads(body)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def lambda_handler(event, context):
    """Run data hygiene via the embedded Syniti-class data spine."""
    run_id = event.get("run_id", "local")
    log_stage_event(run_id, "data-hygiene", "started", {})

    try:
        trees = event.get("entity_trees") or _read_extracted_trees(run_id)

        if not DataSpineOrchestrator or not trees:
            result = {
                "status": "success",
                "mode": "no_data" if DataSpineOrchestrator else "engine_unavailable",
                "engine": "Syniti-class data spine (FK integrity + self-heal + idempotency ledger)",
                "objects_processed": 0,
                "self_healed": 0,
                "orphans_quarantined": 0,
                "reused_from_ledger": 0,
                "note": ("no entity-tree data to cleanse (extract-only pass) — "
                         "spine is wired and runs when trees are present"
                         if DataSpineOrchestrator else "data_spine_orchestrator not importable"),
            }
            log_stage_event(run_id, "data-hygiene", "completed", result)
            return result

        reference = (ReferenceData(**event["reference_data"])
                     if event.get("reference_data") else ReferenceData())
        run_dir = os.path.join(
            os.environ.get("M4H_HYGIENE_DIR") or tempfile.gettempdir(),
            "m4h-hygiene", run_id)
        spine = DataSpineOrchestrator(run_dir, reference=reference)

        reports = []
        for obj, tables in trees.items():
            try:
                rep = spine.process_tree(obj, tables)
                reports.append({k: v for k, v in rep.items() if k != "cleansed"})
            except Exception as e:  # one bad object must not sink the stage
                reports.append({"object": obj, "error": str(e)})

        scored = [r for r in reports if "counters" in r]
        result = {
            "status": "success",
            "mode": "data_spine",
            "engine": "Syniti-class data spine (FK integrity + self-heal + idempotency ledger)",
            "objects_processed": len(reports),
            "self_healed": sum(r["counters"].get("healed", 0) for r in scored),
            "orphans_quarantined": sum(
                sum((r.get("fk_integrity", {}).get("orphans") or {}).values()) for r in scored),
            "unhealable_quarantined": sum(r["counters"].get("quarantined", 0) for r in scored),
            "reused_from_ledger": sum(r.get("reused_from_ledger", 0) for r in scored),
            "fk_integrity": {r["object"]: r["fk_integrity"]["status"] for r in scored},
            "objects": reports,
        }
        # Persist the spine report alongside other stage artifacts.
        try:
            s3.put_object(
                Bucket=STAGING_BUCKET,
                Key=f"runs/{run_id}/data-hygiene/spine_report.json",
                Body=json.dumps(result, default=str, indent=2).encode(),
                ContentType="application/json")
        except Exception:
            pass
        log_stage_event(run_id, "data-hygiene", "completed", result)
        return result

    except Exception as e:
        logger.exception("data-hygiene failed")
        log_stage_event(run_id, "data-hygiene", "failed", {"error": str(e)})
        return {"status": "failed", "error": str(e)}
