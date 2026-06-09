"""
Unit tests for WS4 pillar 3 -- Cross-Platform Coexistence + Multi-Cloud Streaming.

Validates the SinkRouter dispatcher + the 4 concrete sinks (Snowflake stage,
S3 Parquet/clean-room, Salesforce REST, EventBridge custom bus).
"""
from __future__ import annotations
import sys, json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lambda" / "utils"))

from sink_router import (   # noqa
    Sink, SinkRouter, SnowflakeSink, S3ParquetSink,
    SalesforceSink, EventBusSink,
)


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.calls = []
    def put_object(self, **kwargs):
        self.calls.append(kwargs["Key"])
        self.objects[kwargs["Key"]] = kwargs["Body"]
        return {}


class FakeEvents:
    def __init__(self):
        self.entries = []
    def put_events(self, Entries):
        self.entries.extend(Entries)
        return {"FailedEntryCount": 0}


# ─────────────────────────────────────────────────────────────────────────────
def test_router_fans_out_to_all_registered_sinks():
    sf = SalesforceSink()
    ev = EventBusSink(events_client=FakeEvents())
    router = SinkRouter(sinks=[sf, ev])
    out = router.fan_out("Customer", "C001",
                          {"NAME1": "Acme Corp", "LAND1": "US"},
                          tenant_id="acme")
    # Each sink replies once
    assert len(out) == 2
    sinks = {o["sink"] for o in out}
    assert sinks == {"salesforce", "eventbridge"}
    # Salesforce queued for Account, EventBridge published
    sf_writes = sf.writes_for_test()
    assert sf_writes[0]["object"] == "Account"
    assert sf_writes[0]["external_id"] == "C001"
    ev_writes = ev.published_for_test()
    assert ev_writes[0]["DetailType"] == "DataLoaded.Customer"
    print("  [OK] SinkRouter fan-outs reach every registered sink once per row")


def test_snowflake_sink_buffers_per_tenant_and_object():
    s3 = FakeS3()
    snow = SnowflakeSink(s3_client=s3, stage_bucket="test-stage")
    snow.write_one("Material", "MAT001", {"MAKTX": "Widget"}, tenant_id="acme")
    snow.write_one("Material", "MAT002", {"MAKTX": "Gadget"}, tenant_id="acme")
    snow.write_one("Material", "MAT003", {"MAKTX": "Hammer"}, tenant_id="globex")
    flush = snow.flush()
    # 3 rows, 2 stages (one per tenant)
    assert flush["flushed"] == 3
    assert len(flush["stages"]) == 2
    tenants = {s["tenant"] for s in flush["stages"]}
    assert tenants == {"acme", "globex"}
    # Per-tenant S3 paths kept separate
    keys = sorted(s3.objects.keys())
    assert any(k.startswith("snowflake-stage/acme/Material/") for k in keys)
    assert any(k.startswith("snowflake-stage/globex/Material/") for k in keys)
    print("  [OK] SnowflakeSink buffers + flushes per-tenant per-object partitions")


def test_s3_parquet_sink_partitions_by_date_object_tenant():
    s3 = FakeS3()
    sink = S3ParquetSink(s3_client=s3, archive_bucket="test-lake")
    sink.write_one("SalesOrder", "SO_001", {"VBELN": "0001"}, tenant_id="acme")
    sink.write_one("SalesOrder", "SO_002", {"VBELN": "0002"}, tenant_id="acme")
    flush = sink.flush()
    assert flush["flushed"] == 2
    parts = flush["partitions"]
    assert len(parts) == 1
    # Path includes Hive-style partitioning
    key = list(s3.objects.keys())[0]
    assert "tenant=acme" in key
    assert "object=SalesOrder" in key
    assert "date=" in key
    print("  [OK] S3ParquetSink Hive-style partitions tenant=/object=/date=")


def test_salesforce_sink_maps_object_types_to_sf_objects():
    sf = SalesforceSink()
    sf.write_one("Customer", "C1", {"NAME1": "Acme"})
    sf.write_one("Vendor", "V1", {"NAME1": "Globex"})
    sf.write_one("SalesOrder", "SO1", {"VBELN": "0001"})
    sf.write_one("UnknownObject", "X", {})    # SHOULD be silently skipped
    writes = sf.writes_for_test()
    assert len(writes) == 3        # UnknownObject was skipped
    objects = [w["object"] for w in writes]
    assert objects == ["Account", "Account", "Order"]
    # External_Id__c populated from source_key
    assert writes[0]["payload"]["External_Id__c"] == "C1"
    assert writes[0]["payload"]["Source_System__c"] == "Migrate4HANA"
    print("  [OK] SalesforceSink object-type mapping + skip-unmapped + External_Id__c")


def test_salesforce_sink_carries_raw_payload_sidecar():
    """The original SAP row is preserved in Raw_Payload__c so SF formula
    fields / Apex triggers can read any SAP column without us having to
    hard-code mapping every field."""
    sf = SalesforceSink()
    row = {"NAME1": "Acme", "LAND1": "US", "STCD1": "12-3456789",
            "ZZ_RISK_TIER": "GOLD"}
    sf.write_one("Customer", "C1", row, tenant_id="acme")
    write = sf.writes_for_test()[0]
    raw = json.loads(write["payload"]["Raw_Payload__c"])
    assert raw["STCD1"] == "12-3456789"
    assert raw["ZZ_RISK_TIER"] == "GOLD"
    print("  [OK] SalesforceSink carries raw payload sidecar (Z fields included)")


def test_event_bus_sink_publishes_DetailType_per_object_type():
    events = FakeEvents()
    sink = EventBusSink(events_client=events)
    sink.write_one("Material", "M1", {"MAKTX": "Test"}, tenant_id="acme")
    sink.write_one("Customer", "C1", {"NAME1": "Acme"}, tenant_id="acme")
    assert len(events.entries) == 2
    detail_types = [e["DetailType"] for e in events.entries]
    assert detail_types == ["DataLoaded.Material", "DataLoaded.Customer"]
    # Each detail carries the SAP row + tenant_id
    detail = json.loads(events.entries[0]["Detail"])
    assert detail["tenant_id"] == "acme"
    assert detail["source_key"] == "M1"
    assert detail["row"]["MAKTX"] == "Test"
    print("  [OK] EventBusSink publishes DetailType=DataLoaded.<obj> + tenant/source/row")


def test_router_continues_on_sink_failure():
    """One sink raising should NOT prevent the others from receiving the
    row -- production reliability requirement."""
    class BoomSink(Sink):
        name = "boom"
        def write_one(self, *a, **kw):
            raise RuntimeError("simulated sink failure")

    sf = SalesforceSink()
    router = SinkRouter(sinks=[BoomSink(), sf])
    out = router.fan_out("Customer", "C1", {"NAME1": "Acme"})
    # Both sinks reported; one with error, one with queued success
    assert any(o.get("error") for o in out)
    assert any(o.get("status") == "queued" for o in out)
    # The Salesforce sink still got the row
    assert len(sf.writes_for_test()) == 1
    print("  [OK] router continues on one sink's failure -- other sinks unaffected")


def test_router_flush_all_returns_per_sink_summaries():
    s3 = FakeS3()
    snow = SnowflakeSink(s3_client=s3, stage_bucket="test")
    parquet = S3ParquetSink(s3_client=s3, archive_bucket="test")
    router = SinkRouter(sinks=[snow, parquet])
    router.fan_out("Material", "M1", {"MAKTX": "T"}, tenant_id="acme")
    router.fan_out("Material", "M2", {"MAKTX": "T2"}, tenant_id="acme")
    flushes = router.flush_all()
    sinks = {f["sink"] for f in flushes}
    assert sinks == {"snowflake", "s3_parquet"}
    for f in flushes:
        assert f["flushed"] == 2
    print("  [OK] router.flush_all returns per-sink summaries with row counts")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("WS4 pillar 3 -- Multi-cloud streaming SinkRouter tests")
    print("=" * 70)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll Multi-cloud Sink tests passed.")
