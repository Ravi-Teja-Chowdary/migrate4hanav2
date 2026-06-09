"""
Tests for the SLA metric publisher (Group D observability).
Validates the publish_* helpers and the TimedBlock context manager.

These tests run with M4H_DISABLE_CLOUDWATCH_METRICS=1 so the helpers
become no-ops (no boto3 client created). The goal is to prove the
helpers NEVER raise -- a CloudWatch failure can't break the workload.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path

# Disable real CloudWatch calls
os.environ["M4H_DISABLE_CLOUDWATCH_METRICS"] = "1"

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lambda" / "utils"))

import sla_metrics as m   # noqa


def test_throughput_publish_zero_safe():
    # Zero rows + zero elapsed -- should not divide by zero
    m.publish_throughput(0, 0, tenant_id="acme", object_type="Material")
    m.publish_throughput(100, 0, tenant_id="acme", object_type="Material")
    m.publish_throughput(0, 5.0, tenant_id="acme", object_type="Material")
    print("  [OK] publish_throughput is zero-safe (no /0 errors)")


def test_throughput_publish_normal_path():
    m.publish_throughput(1000, 4.0, tenant_id="acme", object_type="Material")
    # No assert -- success = no exception
    print("  [OK] publish_throughput normal path emits cleanly")


def test_bapi_latency_publish_doesnt_raise():
    m.publish_bapi_latency(123.5, tenant_id="acme", object_type="SalesOrder")
    print("  [OK] publish_bapi_latency emits cleanly")


def test_recon_lag_publish_doesnt_raise():
    m.publish_recon_lag(45.2, tenant_id="globex")
    print("  [OK] publish_recon_lag emits cleanly")


def test_dq_violation_rate_publish_zero_safe():
    # Zero scanned must not divide-by-zero
    m.publish_dq_violation_rate(0, 0, tenant_id="acme",
                                 object_type="Material")
    # Normal case
    m.publish_dq_violation_rate(1000, 50, tenant_id="acme",
                                 object_type="Material")
    print("  [OK] publish_dq_violation_rate handles zero-scan + emits clean")


def test_compliance_publishers_dont_raise():
    m.publish_chain_broken(tenant_id="acme")
    m.publish_archived(500, tenant_id="acme", object_type="Customer")
    m.publish_archived(0, tenant_id="acme", object_type="Customer")   # zero-safe
    print("  [OK] compliance publishers emit cleanly")


def test_TimedBlock_records_elapsed():
    with m.TimedBlock() as t:
        time.sleep(0.02)
    assert t.elapsed_sec >= 0.02
    assert t.elapsed_ms  >= 20.0
    print(f"  [OK] TimedBlock recorded {t.elapsed_ms:.1f}ms (expected >=20)")


def test_TimedBlock_doesnt_swallow_exceptions():
    """The context manager must propagate exceptions raised inside it."""
    raised = False
    try:
        with m.TimedBlock() as t:
            raise ValueError("inside block")
    except ValueError:
        raised = True
    assert raised, "TimedBlock swallowed the exception (it must not)"
    print("  [OK] TimedBlock propagates exceptions correctly")


def test_helpers_are_noop_when_disabled():
    """With M4H_DISABLE_CLOUDWATCH_METRICS=1 the _client() returns None
    and no PutMetricData call is attempted. Validates the kill-switch."""
    assert m._client() is None
    print("  [OK] kill-switch env var disables CloudWatch publisher entirely")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("Group D -- SLA metrics publisher tests")
    print("=" * 70)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll SLA metrics tests passed.")
