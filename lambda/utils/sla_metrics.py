"""
sla_metrics -- per-tenant SLA tracker, the publisher half.

Lambda handlers call publish_*() helpers to emit custom CloudWatch metrics
into the Migrate4HANA/* namespaces. The observability module's alarms +
dashboards subscribe to those namespaces.

Custom metrics (per-tenant + global aggregates):

  Migrate4HANA/Throughput        RowsPerSecond                tenant + object_type
  Migrate4HANA/BAPI              CallDurationMs               tenant + object_type
  Migrate4HANA/Reconciliation    LagSeconds                   tenant
  Migrate4HANA/DQ                ViolationRatePct             tenant + object_type
                                  ScannedRecords               tenant
                                  ViolationRecords             tenant
  Migrate4HANA/Compliance        ChainBrokenCount             tenant
                                  ArchivedRecords              tenant + object_type

All publishers are no-op when boto3 is unavailable (offline tests). All
failures are caught -- a metrics emit must never break a real workload.
"""
from __future__ import annotations

import os
import time
from typing import Optional

_NAMESPACE_THROUGHPUT     = "Migrate4HANA/Throughput"
_NAMESPACE_BAPI           = "Migrate4HANA/BAPI"
_NAMESPACE_RECONCILIATION = "Migrate4HANA/Reconciliation"
_NAMESPACE_DQ             = "Migrate4HANA/DQ"
_NAMESPACE_COMPLIANCE     = "Migrate4HANA/Compliance"


def _client():
    """Lazy CloudWatch client. Returns None when boto3 missing (offline tests)."""
    if os.environ.get("M4H_DISABLE_CLOUDWATCH_METRICS") == "1":
        return None
    try:
        import boto3
        return boto3.client("cloudwatch")
    except Exception:
        return None


def _put(namespace: str, metric_name: str, value: float,
         unit: str = "Count", dims: Optional[list] = None) -> None:
    """Best-effort PutMetricData. Failures are swallowed."""
    cw = _client()
    if cw is None:
        return
    try:
        cw.put_metric_data(
            Namespace=namespace,
            MetricData=[{
                "MetricName": metric_name,
                "Value":      float(value),
                "Unit":       unit,
                "Dimensions": dims or [],
                "Timestamp":  _now(),
            }])
    except Exception:
        pass    # never break a workload on telemetry failure


def _now():
    import datetime
    return datetime.datetime.utcnow()


# ─────────────────────────────────────────────────────────────────────────────
# Throughput
# ─────────────────────────────────────────────────────────────────────────────
def publish_throughput(rows: int, elapsed_sec: float, *,
                        tenant_id: str = "default",
                        object_type: str = "Unknown") -> None:
    if elapsed_sec <= 0 or rows <= 0:
        return
    rps = rows / elapsed_sec
    _put(_NAMESPACE_THROUGHPUT, "RowsPerSecond", rps, "Count/Second",
         dims=[{"Name": "TenantId", "Value": tenant_id},
               {"Name": "ObjectType", "Value": object_type}])


# ─────────────────────────────────────────────────────────────────────────────
# BAPI latency
# ─────────────────────────────────────────────────────────────────────────────
def publish_bapi_latency(duration_ms: float, *,
                          tenant_id: str = "default",
                          object_type: str = "Unknown") -> None:
    _put(_NAMESPACE_BAPI, "CallDurationMs", duration_ms, "Milliseconds",
         dims=[{"Name": "TenantId", "Value": tenant_id},
               {"Name": "ObjectType", "Value": object_type}])


# ─────────────────────────────────────────────────────────────────────────────
# Reconciliation lag
# ─────────────────────────────────────────────────────────────────────────────
def publish_recon_lag(lag_seconds: float, *,
                      tenant_id: str = "default") -> None:
    _put(_NAMESPACE_RECONCILIATION, "LagSeconds", lag_seconds, "Seconds",
         dims=[{"Name": "TenantId", "Value": tenant_id}])


# ─────────────────────────────────────────────────────────────────────────────
# DQ
# ─────────────────────────────────────────────────────────────────────────────
def publish_dq_violation_rate(scanned: int, violations: int, *,
                                tenant_id: str = "default",
                                object_type: str = "Unknown") -> None:
    if scanned <= 0:
        return
    pct = 100.0 * violations / scanned
    _put(_NAMESPACE_DQ, "ViolationRatePct", pct, "Percent",
         dims=[{"Name": "TenantId", "Value": tenant_id},
               {"Name": "ObjectType", "Value": object_type}])
    _put(_NAMESPACE_DQ, "ScannedRecords", scanned, "Count",
         dims=[{"Name": "TenantId", "Value": tenant_id}])
    _put(_NAMESPACE_DQ, "ViolationRecords", violations, "Count",
         dims=[{"Name": "TenantId", "Value": tenant_id}])


# ─────────────────────────────────────────────────────────────────────────────
# Compliance
# ─────────────────────────────────────────────────────────────────────────────
def publish_chain_broken(*, tenant_id: str = "default") -> None:
    """Emit a ChainBrokenCount=1 -- the observability alarm threshold is 0,
    so a single emission immediately pages on-call."""
    _put(_NAMESPACE_COMPLIANCE, "ChainBrokenCount", 1, "Count",
         dims=[{"Name": "TenantId", "Value": tenant_id}])


def publish_archived(rows: int, *, tenant_id: str = "default",
                      object_type: str = "Unknown") -> None:
    if rows <= 0:
        return
    _put(_NAMESPACE_COMPLIANCE, "ArchivedRecords", rows, "Count",
         dims=[{"Name": "TenantId", "Value": tenant_id},
               {"Name": "ObjectType", "Value": object_type}])


# ─────────────────────────────────────────────────────────────────────────────
# Timer context manager (BAPI / sink-fanout latency)
# ─────────────────────────────────────────────────────────────────────────────
class TimedBlock:
    """Context manager that records elapsed milliseconds. Pair with
    publish_bapi_latency / publish_throughput as needed."""

    def __init__(self):
        self._t0 = 0.0
        self.elapsed_ms = 0.0
        self.elapsed_sec = 0.0

    def __enter__(self):
        self._t0 = time.time()
        return self

    def __exit__(self, *exc):
        self.elapsed_sec = max(time.time() - self._t0, 0.0)
        self.elapsed_ms  = self.elapsed_sec * 1000.0
        return False    # don't swallow exceptions
