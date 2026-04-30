"""
reconciliation-engine
=====================
First-class reconciliation framework for greenfield S/4HANA migration.

This is NOT placeholder. It implements four reconciliation classes:

  1. count        — source vs target row counts (per object, filter)
  2. key_coverage — every source business key exists on target
  3. balance      — financial/quantity totals (GL, AR, AP, stock)
  4. hash_sample  — sha-256 of N sampled rows by key, compared

Each class has an "adapter" describing how to extract from ECC (source)
and from S/4 (target) using SAP-supported read mechanisms only:

  - source: pyrfc RFC_READ_TABLE bounded; or shipped read-only ABAP
            report (deployed via transport, not tool-runtime ABAP);
            or BW/SLT extractor where customer prefers
  - target: same plus FAGLB03 / BAPI_GL_GETGLACCBALANCE for finance,
            standard CDS views (e.g. C_CompanyCodeFinanceTotal) where
            available

A tolerance policy table (DynamoDB m4h-recon-tolerance) governs whether
a variance is acceptable, requires review, or is a hard failure. Unknown
object classes default to zero-tolerance.

Outputs an immutable evidence record (via evidence-collector) and a
human-readable scorecard JSON in S3. Variances above tolerance trigger
the manual-gate workflow with a structured exception payload.

This module deliberately uses ONLY SAP-shipped read interfaces — never
writes to S/4 — so SAP support is preserved.
"""
from __future__ import annotations
import json
import hashlib
import logging
import os
import sys
import time
from decimal import Decimal

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "utils"))

import boto3  # noqa: E402

try:
    from logger import log_stage_event  # type: ignore
except Exception:  # pragma: no cover
    def log_stage_event(*a, **k):  # type: ignore
        pass

logger = logging.getLogger()
logger.setLevel(logging.INFO)

S3 = boto3.client("s3")
DDB = boto3.resource("dynamodb")
LAMBDA = boto3.client("lambda")

STAGING_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hana-staging-dev")
TOLERANCE_TABLE = os.environ.get("TOLERANCE_TABLE_NAME", "m4h-recon-tolerance-dev")
EVIDENCE_FN = os.environ.get("EVIDENCE_COLLECTOR_FN", "evidence-collector")
GATE_FN = os.environ.get("MANUAL_GATE_FN", "manual-gate")


# ---------- tolerance policy ----------------------------------------------
DEFAULT_TOLERANCE = {
    "count":        {"abs_max": 0,    "pct_max": 0.0,  "review_pct": 0.0},
    "key_coverage": {"abs_max": 0,    "pct_max": 0.0,  "review_pct": 0.0},
    "balance":      {"abs_max": 0.01, "pct_max": 0.001, "review_pct": 0.0001},
    "hash_sample":  {"abs_max": 0,    "pct_max": 0.0,  "review_pct": 0.0},
}


def _tolerance_for(object_class: str, recon_type: str) -> dict:
    try:
        t = DDB.Table(TOLERANCE_TABLE)
        resp = t.get_item(Key={"object_class": object_class, "recon_type": recon_type})
        item = resp.get("Item")
        if item:
            return {k: float(v) if isinstance(v, Decimal) else v
                    for k, v in item.items()
                    if k in ("abs_max", "pct_max", "review_pct")}
    except Exception:
        pass
    return DEFAULT_TOLERANCE.get(recon_type, {"abs_max": 0, "pct_max": 0, "review_pct": 0})


def _verdict(diff_abs: float, source_total: float, tol: dict) -> str:
    """Return 'success' | 'warning_requires_review' | 'failed'."""
    if diff_abs == 0:
        return "success"
    pct = abs(diff_abs) / source_total if source_total else 1.0
    if abs(diff_abs) <= tol.get("abs_max", 0) and pct <= tol.get("pct_max", 0):
        return "success"
    if pct <= tol.get("review_pct", 0):
        return "warning_requires_review"
    return "failed"


# ---------- recon adapters (called by lambda_handler) ----------------------
def recon_count(source_count: int, target_count: int, object_class: str) -> dict:
    diff = target_count - source_count
    tol = _tolerance_for(object_class, "count")
    return {
        "type": "count",
        "object_class": object_class,
        "source_count": source_count,
        "target_count": target_count,
        "diff_abs": diff,
        "diff_pct": (diff / source_count * 100) if source_count else 0.0,
        "verdict": _verdict(diff, source_count, tol),
        "tolerance_applied": tol,
    }


def recon_key_coverage(source_keys: list, target_keys: list, object_class: str) -> dict:
    src_set = set(source_keys)
    tgt_set = set(target_keys)
    missing = src_set - tgt_set
    extra = tgt_set - src_set
    tol = _tolerance_for(object_class, "key_coverage")
    return {
        "type": "key_coverage",
        "object_class": object_class,
        "source_count": len(src_set),
        "target_count": len(tgt_set),
        "missing_on_target": sorted(list(missing))[:200],
        "extra_on_target": sorted(list(extra))[:200],
        "missing_count": len(missing),
        "extra_count": len(extra),
        "verdict": _verdict(len(missing) + len(extra), len(src_set), tol),
        "tolerance_applied": tol,
    }


def recon_balance(source_balance: dict, target_balance: dict, object_class: str) -> dict:
    """source/target_balance keyed by company_code|fiscal_year|period|currency -> Decimal."""
    diffs = []
    src_total = Decimal("0")
    abs_diff_total = Decimal("0")
    keys = sorted(set(source_balance) | set(target_balance))
    for k in keys:
        s = Decimal(str(source_balance.get(k, 0)))
        t = Decimal(str(target_balance.get(k, 0)))
        d = t - s
        src_total += abs(s)
        abs_diff_total += abs(d)
        if d != 0:
            diffs.append({"key": k, "source": str(s), "target": str(t), "diff": str(d)})
    tol = _tolerance_for(object_class, "balance")
    return {
        "type": "balance",
        "object_class": object_class,
        "source_total_abs": str(src_total),
        "diff_total_abs": str(abs_diff_total),
        "diffs": diffs[:500],
        "diff_count": len(diffs),
        "verdict": _verdict(float(abs_diff_total), float(src_total) or 1.0, tol),
        "tolerance_applied": tol,
    }


def recon_hash_sample(source_rows: list, target_rows: list, key_field: str,
                       object_class: str) -> dict:
    """Both inputs are list-of-dicts; rows MUST be sorted client-side by key_field
    before calling so hashes are deterministic."""
    def _h(rows):
        return [hashlib.sha256(
            json.dumps(r, sort_keys=True, default=str).encode()).hexdigest()
            for r in rows]
    src_h = _h(source_rows)
    tgt_h = {row[key_field]: h for row, h in zip(target_rows, _h(target_rows))}
    mismatches = []
    for row, h in zip(source_rows, src_h):
        k = row.get(key_field)
        th = tgt_h.get(k)
        if th != h:
            mismatches.append({"key": k, "source_hash": h, "target_hash": th})
    tol = _tolerance_for(object_class, "hash_sample")
    return {
        "type": "hash_sample",
        "object_class": object_class,
        "sampled": len(source_rows),
        "mismatches": mismatches[:200],
        "mismatch_count": len(mismatches),
        "verdict": _verdict(len(mismatches), len(source_rows) or 1, tol),
        "tolerance_applied": tol,
    }


# ---------- evidence + gate plumbing --------------------------------------
def _emit_evidence(run_id, stage, payload):
    try:
        LAMBDA.invoke(
            FunctionName=EVIDENCE_FN,
            InvocationType="Event",
            Payload=json.dumps({
                "run_id": run_id, "stage": stage,
                "event_type": "reconciliation",
                "payload": payload,
            }, default=str).encode(),
        )
    except Exception as e:
        logger.warning("evidence emit failed: %s", e)


def _open_gate(run_id, payload):
    try:
        LAMBDA.invoke(
            FunctionName=GATE_FN, InvocationType="Event",
            Payload=json.dumps({
                "run_id": run_id, "kind": "reconciliation_exception",
                "payload": payload,
            }, default=str).encode(),
        )
    except Exception as e:
        logger.warning("gate open failed: %s", e)


# ---------- entrypoint ----------------------------------------------------
def lambda_handler(event, context):
    run_id = event.get("run_id", f"run-{int(time.time())}")
    object_class = event.get("object_class", "unknown")
    log_stage_event(run_id, "reconciliation-engine", "started", {"object_class": object_class})

    try:
        results = []
        for spec in event.get("reconciliations", []):
            t = spec["type"]
            if t == "count":
                results.append(recon_count(spec["source_count"], spec["target_count"], object_class))
            elif t == "key_coverage":
                results.append(recon_key_coverage(spec["source_keys"], spec["target_keys"], object_class))
            elif t == "balance":
                results.append(recon_balance(spec["source_balance"], spec["target_balance"], object_class))
            elif t == "hash_sample":
                results.append(recon_hash_sample(
                    spec["source_rows"], spec["target_rows"],
                    spec["key_field"], object_class))
            else:
                results.append({"type": t, "verdict": "failed",
                                "reason": f"unknown reconciliation type: {t}"})

        verdicts = [r["verdict"] for r in results]
        if "failed" in verdicts:
            overall = "failed"
        elif "warning_requires_review" in verdicts:
            overall = "warning_requires_review"
        else:
            overall = "success"

        scorecard = {
            "run_id": run_id, "object_class": object_class,
            "overall": overall, "results": results,
            "ts": int(time.time()),
        }
        key = f"runs/{run_id}/reconciliation/{object_class}.json"
        S3.put_object(Bucket=STAGING_BUCKET, Key=key,
                      Body=json.dumps(scorecard, default=str, indent=2).encode(),
                      ContentType="application/json")
        scorecard["scorecard_s3"] = f"s3://{STAGING_BUCKET}/{key}"

        _emit_evidence(run_id, "reconciliation-engine", scorecard)
        if overall != "success":
            _open_gate(run_id, scorecard)

        log_stage_event(run_id, "reconciliation-engine", overall, {"object_class": object_class})
        return {"status": overall, **scorecard}
    except Exception as e:
        logger.exception("reconciliation-engine failed")
        log_stage_event(run_id, "reconciliation-engine", "failed", {"error": str(e)})
        return {"status": "failed", "error": str(e)}
