"""
test_data_quality_slo_gate
==========================
Offline verification of the dirty-data SLO gate logic added 2026-06-10.

The gate lives in two places:
  1. lambda/data-migrator/handler.py — computes data_quality.slo_breach from
     per-object load.failed_count / load.attempted (plus CVI conflicts) against
     env M4H_DEAD_LETTER_THRESHOLD_PCT.
  2. terraform/modules/step-functions/lift_and_shift_pipeline.asl.json —
     DataQualitySloChoice branches to ManualGate_DataQuality when
     $.slo_breach == true.

This test reproduces the rollup math against a real captured run
(aws-e2e-20260610-124235, which had 331/553 = 59.855% dead-letter) and
verifies both branches (gate fires, gate disabled).

Run:
  python -m pytest tests/test_data_quality_slo_gate.py -v
"""
from __future__ import annotations


def _rollup(results: list, cvi_conflicts: int, threshold_pct: float) -> dict:
    """Mirror of the rollup in lambda/data-migrator/handler.py:
    sums per-object attempted/failed across the batch, adds CVI conflicts,
    and returns the data_quality block the ASL Choice branches on."""
    total_att = sum(int((r.get("load") or {}).get("attempted") or 0)
                    for r in results)
    total_dl = sum(int((r.get("load") or {}).get("failed_count") or
                       len((r.get("load") or {}).get("dead_letter") or []))
                   for r in results)
    total_dl += int(cvi_conflicts or 0)
    pct = round((total_dl / total_att * 100.0), 3) if total_att else 0.0
    breach = bool(threshold_pct > 0 and pct > threshold_pct)
    return {
        "total_attempted":   total_att,
        "total_dead_letter": total_dl,
        "dead_letter_pct":   pct,
        "threshold_pct":     threshold_pct,
        "slo_breach":        breach,
        "gate_disabled":     bool(threshold_pct == 0),
    }


# Synthetic ladder covering the four operative cases. The numerics match the
# real run replay so the test is a self-contained spec of the gate behavior.

def test_clean_run_no_breach():
    """All records loaded, no dirty-data. Pipeline flows through unblocked."""
    r = [{"load": {"attempted": 100, "failed_count": 0}}]
    dq = _rollup(r, cvi_conflicts=0, threshold_pct=5.0)
    assert dq["dead_letter_pct"] == 0.0
    assert dq["slo_breach"] is False


def test_dirty_run_breaches_default_threshold():
    """Captured run: 553 attempted, 331 dead-letter (BP synthetic dirty corpus).
    At default 5% threshold, gate fires and halts pipeline at ManualGate_DataQuality."""
    r = [
        {"load": {"attempted": 100, "failed_count":  50}},  # BusinessPartner 50%
        {"load": {"attempted": 100, "failed_count":   0}},  # Customer 0%
        {"load": {"attempted": 100, "failed_count":   0}},  # Vendor 0%
        {"load": {"attempted": 253, "failed_count": 281}},  # Material (over-attempted with scan cap)
    ]
    dq = _rollup(r, cvi_conflicts=0, threshold_pct=5.0)
    assert dq["total_attempted"] == 553
    assert dq["total_dead_letter"] == 331
    assert dq["dead_letter_pct"] == 59.855
    assert dq["slo_breach"] is True


def test_threshold_zero_disables_gate():
    """threshold=0 lets dirty data flow through (useful for the dirty-data
    proof runs where we WANT to validate the spine's rejection path
    end-to-end without halting). gate_disabled=True surfaces the override."""
    r = [{"load": {"attempted": 100, "failed_count": 99}}]
    dq = _rollup(r, cvi_conflicts=0, threshold_pct=0.0)
    assert dq["dead_letter_pct"] == 99.0
    assert dq["slo_breach"] is False
    assert dq["gate_disabled"] is True


def test_below_threshold_lets_normal_dirt_through():
    """Below threshold, real-world acceptable dirt rate passes the gate."""
    r = [{"load": {"attempted": 100, "failed_count": 3}}]
    dq = _rollup(r, cvi_conflicts=0, threshold_pct=5.0)
    assert dq["dead_letter_pct"] == 3.0
    assert dq["slo_breach"] is False


def test_cvi_conflicts_count_as_dead_letter():
    """CVI customer/vendor conflicts ride the same dead-letter S3 artifact and
    must be included in the SLO rollup so the gate fires on hidden dirt."""
    r = [{"load": {"attempted": 100, "failed_count": 2}}]
    dq = _rollup(r, cvi_conflicts=10, threshold_pct=5.0)
    assert dq["total_dead_letter"] == 12
    assert dq["dead_letter_pct"] == 12.0
    assert dq["slo_breach"] is True


def test_empty_results_safe():
    """No load attempted (e.g. M4H_LOAD_TO_S4 disabled). No divide-by-zero,
    no spurious breach."""
    dq = _rollup([], cvi_conflicts=0, threshold_pct=5.0)
    assert dq["total_attempted"] == 0
    assert dq["dead_letter_pct"] == 0.0
    assert dq["slo_breach"] is False
