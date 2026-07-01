"""Aggregation utilities that turn per-run artefacts into slim UI payloads.

The UI never scrapes raw stderr or reads the runner's per-stage JSON directly.
Instead every dashboard call goes through one of these three pure functions,
which read the run directory + optional in-memory pipeline state and emit the
minimal JSON shape the frontend needs.

Keeping this out of api_server.py means:
  * we can unit-test the aggregation without spinning up FastAPI
  * the api layer stays thin (each endpoint is 3-5 lines)
  * every payload has a single source of truth for schema
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import time
from pathlib import Path
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Remediation hint catalog
# ─────────────────────────────────────────────────────────────────────────────
# Every hint is a short imperative sentence, phrased for the operator who will
# fix the underlying data or customizing. Kept as a table so it is trivial to
# extend when new dead-letter codes surface in the field.
_REMEDIATION_HINTS: dict[str, str] = {
    # Data-quality rejections (spine refused the row before BAPI call)
    "NAME is required":
        "Populate KNA1.NAME1 / LFA1.NAME1 on the source rows and re-run.",
    "cc_org missing: COMP_CODE,CLEARING":
        "Enrich BSID/BSIK line items with COMP_CODE + CLEARING via source view before extract.",
    "cc_org missing: COMP_CODE":
        "Enrich source open items with COMP_CODE via BUKRS lookup before extract.",
    # Target customizing gaps
    "rate type 001 not defined in target (TCURV)":
        "Import the exchange-rate customizing transport (adds TCURV rate types) via STMS, "
        "then re-run.",
    "Locked Number Range":
        "Unlock the number range on the target (SNRO) and retry the failed rows.",
    "Duplicate material":
        "Source is proposing a MATNR that already exists on S/4. Re-map to the existing "
        "target key or skip the row via idempotency ledger.",
    # BAPI-side generic
    "BAPI_FAILURE":
        "Inspect the BAPI response; usually a customizing prerequisite missing on target.",
}


def _remediation_for(code: str, first_message: str) -> str:
    """Best-effort hint lookup — first exact message, then code prefix, then default."""
    if first_message and first_message in _REMEDIATION_HINTS:
        return _REMEDIATION_HINTS[first_message]
    # Try the leading tokens of the message
    for key, hint in _REMEDIATION_HINTS.items():
        if key and key in (first_message or ""):
            return hint
    if code in _REMEDIATION_HINTS:
        return _REMEDIATION_HINTS[code]
    return "Review the failed-records CSV; correct source data or target customizing and retry."


# ─────────────────────────────────────────────────────────────────────────────
# Path helpers
# ─────────────────────────────────────────────────────────────────────────────
def _run_root(run_dir: str | os.PathLike) -> Path:
    return Path(run_dir)


def _load_json(p: Path) -> dict | list | None:
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 1. Aggregated telemetry
# ─────────────────────────────────────────────────────────────────────────────
def aggregate_run_telemetry(run_dir: str | os.PathLike,
                             *,
                             active_state: dict | None = None) -> dict:
    """Return the slim JSON the dashboard polls.

    Shape (spec-locked; do not add fields without a UI change):

        {
          "status": "Processing" | "Completed" | "Failed" | "Simulating" | "Idle",
          "percentage_complete": 0-100,
          "total_records": int,
          "processed_successfully": int,
          "failed_records": int,
          "runtime_elapsed_seconds": int,
        }

    Sources:
      * `<run>/data-migrator/summary.json` for record counts (authoritative)
      * `active_state` (the api_server's in-memory run tracker) for status +
        wall-clock start, since summary.json only lands at the end
    """
    active = active_state or {}
    summary = _load_json(_run_root(run_dir) / "data-migrator" / "summary.json") or {}

    # ── Record counts ───────────────────────────────────────────────────────
    results = summary.get("results") or []
    total = 0
    ok = 0
    for r in results:
        if not isinstance(r, dict):
            continue
        rc = int(r.get("row_count") or 0)
        total += rc
        status = str(r.get("status") or "").lower()
        if status in ("ok", "partial"):
            ok += rc
    dq = summary.get("data_quality") or {}
    failed = int(dq.get("total_dead_letter") or 0)
    # If load-to-s4 was actually enabled, the "processed successfully" number
    # the operator wants is BAPI-succeeded creates, not staged CSV rows.
    if summary.get("load_to_s4_enabled"):
        # Attempted = created + matched_existing + dead_letter (per spine ledger).
        # `objects_created_in_s4` is authoritative for successful writes.
        ok = int(summary.get("objects_created_in_s4") or 0)
        total = int(dq.get("total_attempted") or ok + failed)

    # ── Percentage ──────────────────────────────────────────────────────────
    if total > 0:
        pct = round(100.0 * (ok + failed) / total, 1)
    else:
        pct = float(active.get("percentage_complete") or 0)
    pct = max(0.0, min(100.0, pct))

    # ── Status ──────────────────────────────────────────────────────────────
    raw_status = str(active.get("status") or "").lower()
    if raw_status == "running":
        status = "Simulating" if active.get("simulation_mode") else "Processing"
    elif raw_status == "completed":
        status = "Completed"
    elif raw_status == "failed":
        status = "Failed"
    elif summary:  # No active state but summary on disk = finished before we booted
        status = "Failed" if summary.get("error_count") else "Completed"
    else:
        status = "Idle"

    # ── Elapsed ─────────────────────────────────────────────────────────────
    started = active.get("started")
    if isinstance(started, (int, float)) and started > 0:
        elapsed = int(max(0, time.time() - started))
    elif "duration" in active and isinstance(active["duration"], (int, float)):
        elapsed = int(active["duration"])
    else:
        elapsed = 0

    return {
        "status": status,
        "percentage_complete": pct,
        "total_records": total,
        "processed_successfully": ok,
        "failed_records": failed,
        "runtime_elapsed_seconds": elapsed,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. Error-bucketing
# ─────────────────────────────────────────────────────────────────────────────
_SIGNATURE_MSG_TRIM = re.compile(r"\s+")


def _normalise_message(m: str) -> str:
    """Strip variable substrings (row ids, timestamps) so identical-shape errors
    collapse into one bucket. Deliberately conservative — we'd rather show one
    extra bucket than merge distinct issues."""
    m = _SIGNATURE_MSG_TRIM.sub(" ", (m or "")).strip()
    # Drop trailing "row N of M" style noise; keep the semantic prefix.
    m = re.sub(r"\brow \d+.*", "", m).strip()
    return m


def bucket_errors(run_dir: str | os.PathLike, sample_size: int = 3) -> list[dict]:
    """Group `dead-letter/failed_records.json` entries by error signature.

    Returns an array (sorted by count desc) of:

        {
          "error": "<short signature shown in the UI card>",
          "code": "<original code>",
          "count": int,
          "remediation": "<one-sentence operator hint>",
          "objects": ["Customer", ...],       # which objects hit this error
          "sample_source_keys": ["...", ...], # up to `sample_size` example row IDs
        }
    """
    dl_path = _run_root(run_dir) / "data-migrator" / "dead-letter" / "failed_records.json"
    records = _load_json(dl_path)
    if not isinstance(records, list):
        return []

    buckets: dict[str, dict] = {}
    for r in records:
        if not isinstance(r, dict):
            continue
        code = str(r.get("code") or "UNCLASSIFIED")
        messages = r.get("messages") or []
        first_msg = _normalise_message(messages[0] if messages else "")
        signature = f"{code}::{first_msg}" if first_msg else code
        b = buckets.get(signature)
        if b is None:
            b = {
                "error": first_msg or code,
                "code": code,
                "count": 0,
                "remediation": _remediation_for(code, first_msg),
                "objects": set(),
                "sample_source_keys": [],
            }
            buckets[signature] = b
        b["count"] += 1
        obj = r.get("object")
        if obj:
            b["objects"].add(obj)
        src = r.get("source_key")
        if src and len(b["sample_source_keys"]) < sample_size:
            b["sample_source_keys"].append(src)

    # Freeze sets → sorted lists for JSON, and sort buckets by descending count
    out = []
    for b in buckets.values():
        b["objects"] = sorted(b["objects"])
        out.append(b)
    out.sort(key=lambda b: (-b["count"], b["error"]))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 3. Failed-records CSV export
# ─────────────────────────────────────────────────────────────────────────────
_CSV_COLUMNS = ("object", "source_key", "code", "messages", "lane")


def failed_records_csv(run_dir: str | os.PathLike) -> bytes:
    """Emit exactly the failing rows as a CSV the operator can open in Excel,
    fix, and hand back to the migration lead. Multi-line `messages` are
    semicolon-joined into a single cell to keep the row shape clean.
    """
    dl_path = _run_root(run_dir) / "data-migrator" / "dead-letter" / "failed_records.json"
    records = _load_json(dl_path)
    if not isinstance(records, list):
        records = []
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(_CSV_COLUMNS)
    for r in records:
        if not isinstance(r, dict):
            continue
        messages = r.get("messages") or []
        if isinstance(messages, list):
            messages = "; ".join(str(m) for m in messages)
        w.writerow([
            r.get("object", ""),
            r.get("source_key", ""),
            r.get("code", ""),
            messages,
            r.get("lane", ""),
        ])
    return buf.getvalue().encode("utf-8")
