"""
sap_workload.py - SAP target-side backpressure (TH_WPINFO + NRIV lock probe).

Background
----------
The DynamoDB token bucket (key_map.py:TokenBucket) protects AWS write capacity.
It does NOT protect the target SAP system. When Fargate fans out concurrent
BAPI loads at 10^6-row scale, two things break the target:

  1. Dialog/Update work-process exhaustion  - TH_WPINFO shows zero free WPs,
     subsequent RFC calls queue or time out, the database goes red.
  2. Number-range table lock contention     - parallel inserts hammer NRIV,
     causing SAP_LOCK_TIMEOUT or ENQUEUE waits that cascade into the dispatcher.

This module gives the orchestrator a target-side gate it can check BEFORE
releasing the next batch:

  - probe_workprocesses()     -> WorkloadProbe (free WPs, queue depth, verdict)
  - probe_number_range_lock() -> True if NRIV is currently lock-contended for
                                 the object's number-range object
  - WorkloadThrottle          -> the decision wrapper used by the dispatcher:
                                 wait/backoff/proceed with a recommended next
                                 batch size

Calls
-----
- Function module:  TH_WPINFO    (kernel; returns rows of WPLIST)
- Function module:  ENQUE_READ2  (read current ENQUEUE entries for NRIV)
Both are released, support-compliant RFC calls. No raw table reads.

The probes accept an injectable rfc_callable so tests + offline runs don't need
a live pyrfc connection. In Lambda/Fargate the orchestrator passes a partial
that already holds the open pyrfc connection.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("sap_workload")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


@dataclass
class WorkloadProbe:
    """Snapshot of target SAP dialog/update work-process state."""
    total_dia: int = 0       # configured dialog WPs
    free_dia: int = 0        # currently free dialog WPs
    total_upd: int = 0       # configured update WPs (V1)
    free_upd: int = 0        # currently free update WPs
    queue_depth: int = 0     # entries waiting in dispatcher queue
    raw_count: int = 0       # rows returned by TH_WPINFO
    verdict: str = "unknown" # GREEN / YELLOW / RED

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
#  Verdict thresholds. Tunable per landscape; defaults are conservative.
# ─────────────────────────────────────────────────────────────────────────────
GREEN_FREE_RATIO = 0.30   # >= 30% free dialog WPs -> green
YELLOW_FREE_RATIO = 0.10  # >= 10% free dialog WPs -> yellow (back off)
GREEN_QUEUE_MAX = 0       # no queue -> green
YELLOW_QUEUE_MAX = 5      # <= 5 queued -> yellow


def _verdict(free_dia: int, total_dia: int, queue_depth: int) -> str:
    if total_dia <= 0:
        return "unknown"
    ratio = free_dia / total_dia
    if ratio >= GREEN_FREE_RATIO and queue_depth <= GREEN_QUEUE_MAX:
        return "GREEN"
    if ratio >= YELLOW_FREE_RATIO and queue_depth <= YELLOW_QUEUE_MAX:
        return "YELLOW"
    return "RED"


def probe_workprocesses(rfc_callable: Callable[[str, Dict], Dict]) -> WorkloadProbe:
    """Call TH_WPINFO and classify the result.

    rfc_callable signature mirrors pyrfc.Connection.call:
        rfc_callable(function_name: str, kwargs: dict) -> dict
    """
    try:
        resp = rfc_callable("TH_WPINFO", {})
    except Exception as e:  # noqa: BLE001
        logger.warning("TH_WPINFO probe failed (%s) - returning unknown verdict", e)
        return WorkloadProbe(verdict="unknown")

    # TH_WPINFO returns table WPLIST with rows like:
    #   { WP_TYP: "DIA" | "UPD" | "BTC" | "SPO" | ..., WP_STATUS: "Waiting" | "Running" | ..., WP_WAITING: 0 | n, ... }
    rows = resp.get("WPLIST") or resp.get("WPINFO") or []
    total_dia = free_dia = total_upd = free_upd = 0
    queue_depth = 0

    for r in rows:
        wp_typ = (r.get("WP_TYP") or r.get("WPTYP") or "").upper().strip()
        wp_status = (r.get("WP_STATUS") or r.get("WPSTATUS") or "").upper().strip()
        wp_waiting = int(r.get("WP_WAITING") or r.get("WPWAITING") or 0)
        if wp_typ == "DIA":
            total_dia += 1
            if "WAIT" in wp_status:  # "Waiting"
                free_dia += 1
        elif wp_typ == "UPD":
            total_upd += 1
            if "WAIT" in wp_status:
                free_upd += 1
        queue_depth = max(queue_depth, wp_waiting)

    probe = WorkloadProbe(
        total_dia=total_dia, free_dia=free_dia,
        total_upd=total_upd, free_upd=free_upd,
        queue_depth=queue_depth, raw_count=len(rows),
        verdict=_verdict(free_dia, total_dia, queue_depth))
    logger.info("TH_WPINFO: DIA %d/%d free, UPD %d/%d free, queue=%d -> %s",
                probe.free_dia, probe.total_dia,
                probe.free_upd, probe.total_upd,
                probe.queue_depth, probe.verdict)
    return probe


def probe_number_range_lock(rfc_callable: Callable[[str, Dict], Dict],
                            nr_object: str) -> bool:
    """Return True if NRIV currently has an ENQUEUE entry for the named number-
    range object (e.g. 'RV_BELEG' for SD, 'RF_BELEG' for FI). A non-zero count
    means parallel inserts are already serializing on the number range; pushing
    more concurrency in will just deepen the queue."""
    try:
        resp = rfc_callable("ENQUE_READ2", {
            "GCLIENT": "*",
            "GNAME": "NRIV",
            "GARG": f"%{nr_object}%",
        })
    except Exception as e:  # noqa: BLE001
        logger.warning("ENQUE_READ2(NRIV, %s) probe failed (%s)", nr_object, e)
        return False
    locks = resp.get("ENQ") or resp.get("ENQUEUE") or []
    held = len(locks) > 0
    if held:
        logger.warning("NRIV lock held for %s (%d entries) - back off",
                       nr_object, len(locks))
    return held


# ─────────────────────────────────────────────────────────────────────────────
#  The throttle the orchestrator actually calls
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ThrottleDecision:
    verdict: str                       # GREEN / YELLOW / RED / UNKNOWN
    recommended_batch: int             # next batch size (may be 0 = pause)
    wait_seconds: float                # caller should sleep this long first
    probe: WorkloadProbe = field(default_factory=WorkloadProbe)
    nr_locked: bool = False

    def to_dict(self) -> dict:
        return {**asdict(self), "probe": self.probe.to_dict()}


class WorkloadThrottle:
    """Wraps probe + decision into one call the dispatcher uses per batch.

    Usage:
        throttle = WorkloadThrottle(rfc_callable=conn.call,
                                    requested_batch=200,
                                    nr_object="RV_BELEG")
        for chunk in chunks_of(records, throttle.requested_batch):
            d = throttle.decide()
            if d.wait_seconds:
                time.sleep(d.wait_seconds)
            if d.recommended_batch == 0:
                continue  # pause and re-probe next loop
            load(chunk[:d.recommended_batch])
    """

    def __init__(self,
                 rfc_callable: Optional[Callable[[str, Dict], Dict]],
                 requested_batch: int = 200,
                 nr_object: Optional[str] = None,
                 min_batch: int = 10):
        self.rfc = rfc_callable
        self.requested_batch = max(min_batch, requested_batch)
        self.min_batch = min_batch
        self.nr_object = nr_object

    def decide(self) -> ThrottleDecision:
        if self.rfc is None:
            # No connection -> proceed at requested batch (caller is in test mode)
            return ThrottleDecision(verdict="unknown",
                                    recommended_batch=self.requested_batch,
                                    wait_seconds=0.0)

        probe = probe_workprocesses(self.rfc)
        nr_locked = bool(self.nr_object) and probe_number_range_lock(
            self.rfc, self.nr_object)

        # RED wins over everything else - WP exhaustion means even tiny batches
        # will queue. Pause entirely until the next probe shows recovery.
        if probe.verdict == "RED":
            return ThrottleDecision(verdict="RED",
                                    recommended_batch=0,
                                    wait_seconds=10.0,
                                    probe=probe, nr_locked=nr_locked)
        if probe.verdict == "GREEN" and not nr_locked:
            return ThrottleDecision(verdict="GREEN",
                                    recommended_batch=self.requested_batch,
                                    wait_seconds=0.0,
                                    probe=probe, nr_locked=False)
        if probe.verdict == "YELLOW" or nr_locked:
            # Halve the batch, wait a couple of seconds
            half = max(self.min_batch, self.requested_batch // 2)
            return ThrottleDecision(verdict="YELLOW",
                                    recommended_batch=half,
                                    wait_seconds=2.0,
                                    probe=probe, nr_locked=nr_locked)
        # unknown -> proceed cautiously at min_batch
        return ThrottleDecision(verdict="unknown",
                                recommended_batch=self.min_batch,
                                wait_seconds=1.0,
                                probe=probe, nr_locked=nr_locked)


# ─────────────────────────────────────────────────────────────────────────────
#  Self-test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 78)
    print("sap_workload - self-test")
    print("=" * 78)

    def fake_green(fn, kwargs):
        if fn == "TH_WPINFO":
            return {"WPLIST": [
                {"WP_TYP": "DIA", "WP_STATUS": "Waiting", "WP_WAITING": 0},
                {"WP_TYP": "DIA", "WP_STATUS": "Waiting", "WP_WAITING": 0},
                {"WP_TYP": "DIA", "WP_STATUS": "Waiting", "WP_WAITING": 0},
                {"WP_TYP": "DIA", "WP_STATUS": "Running", "WP_WAITING": 0},
                {"WP_TYP": "DIA", "WP_STATUS": "Running", "WP_WAITING": 0},
                {"WP_TYP": "DIA", "WP_STATUS": "Running", "WP_WAITING": 0},
                {"WP_TYP": "DIA", "WP_STATUS": "Running", "WP_WAITING": 0},
                {"WP_TYP": "UPD", "WP_STATUS": "Waiting", "WP_WAITING": 0},
                {"WP_TYP": "UPD", "WP_STATUS": "Waiting", "WP_WAITING": 0},
            ]}
        if fn == "ENQUE_READ2":
            return {"ENQ": []}
        return {}

    def fake_yellow(fn, kwargs):
        if fn == "TH_WPINFO":
            return {"WPLIST": [
                {"WP_TYP": "DIA", "WP_STATUS": "Waiting", "WP_WAITING": 0}] + \
                [{"WP_TYP": "DIA", "WP_STATUS": "Running", "WP_WAITING": 0}] * 9}
        if fn == "ENQUE_READ2":
            return {"ENQ": []}
        return {}

    def fake_red_nr_locked(fn, kwargs):
        if fn == "TH_WPINFO":
            return {"WPLIST": [
                {"WP_TYP": "DIA", "WP_STATUS": "Running", "WP_WAITING": 12}] * 10}
        if fn == "ENQUE_READ2":
            return {"ENQ": [{"GNAME": "NRIV", "GARG": "100RV_BELEG01"}]}
        return {}

    t = WorkloadThrottle(rfc_callable=fake_green, requested_batch=200,
                         nr_object="RV_BELEG").decide()
    assert t.verdict == "GREEN" and t.recommended_batch == 200 and t.wait_seconds == 0.0
    print(f"  GREEN path: batch={t.recommended_batch} wait={t.wait_seconds}s OK")

    t = WorkloadThrottle(rfc_callable=fake_yellow, requested_batch=200,
                         nr_object="RV_BELEG").decide()
    assert t.verdict == "YELLOW" and t.recommended_batch == 100 and t.wait_seconds == 2.0
    print(f"  YELLOW path: batch={t.recommended_batch} (halved) wait={t.wait_seconds}s OK")

    t = WorkloadThrottle(rfc_callable=fake_red_nr_locked, requested_batch=200,
                         nr_object="RV_BELEG").decide()
    assert t.verdict == "RED" and t.recommended_batch == 0 and t.nr_locked is True
    print(f"  RED + NRIV-locked path: batch={t.recommended_batch} (pause) "
          f"wait={t.wait_seconds}s nr_locked={t.nr_locked} OK")

    t = WorkloadThrottle(rfc_callable=None, requested_batch=200).decide()
    assert t.verdict == "unknown" and t.recommended_batch == 200
    print(f"  no-connection path: passes through at requested batch OK")

    print("\nOK - SAP-side throttle classifies green/yellow/red and respects NRIV locks.")
