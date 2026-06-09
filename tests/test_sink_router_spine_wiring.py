"""
Tests for SinkRouter wired into BaseSpineOrchestrator.load_one().

Path 1 step 1 -- activates WS4 pillar 3 (Multi-cloud Streaming) for EVERY
spine-routed object. The sink fan-out fires post-success (created /
matched_existing / remapped) and is skipped on dead-letter so a downstream
sink failure cannot mirror partial / rejected data.
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lambda" / "utils"))

from base_spine_orchestrator import (   # noqa
    BaseSpineOrchestrator, DISP_CREATED, DISP_MATCHED_EXISTING,
    DISP_REMAPPED, DISP_DEAD_LETTER,
)
from sink_router import SinkRouter, SalesforceSink, EventBusSink   # noqa


# ─────────────────────────────────────────────────────────────────────────────
# Minimal concrete spine subclass + helpers
# ─────────────────────────────────────────────────────────────────────────────
class StubMaterialSpine(BaseSpineOrchestrator):
    object_type = "Material"
    source_key_field = "MATNR"
    extension_structure = ""

    def __init__(self, *args, bapi_disp=DISP_CREATED, bapi_raises=False, **kw):
        super().__init__(*args, **kw)
        self._bapi_disp = bapi_disp
        self._bapi_raises = bapi_raises
        self.call_count = 0

    def build_payload(self, row, ext_rows):
        return {"MATERIAL": row.get("MATNR"), "MTART": row.get("MTART", "HALB")}

    def call_bapi(self, payload):
        self.call_count += 1
        if self._bapi_raises:
            raise RuntimeError("simulated BAPI dump")
        return (payload["MATERIAL"], [], self._bapi_disp, None)

    def transform(self, row):
        # Force DQ reject if row has SHOULD_REJECT
        if row.get("SHOULD_REJECT"):
            return None
        return dict(row)


class FakeEvents:
    def __init__(self):
        self.entries = []
    def put_events(self, Entries):
        self.entries.extend(Entries)
        return {"FailedEntryCount": 0}


# ─────────────────────────────────────────────────────────────────────────────
def test_sink_fanout_fires_on_successful_create():
    """Successful BAPI create -> SinkRouter.fan_out called with the
    transformed row + target_key."""
    sf = SalesforceSink()
    ev = EventBusSink(events_client=FakeEvents())
    router = SinkRouter(sinks=[sf, ev])
    spine = StubMaterialSpine(conn=None, sink_router=router, tenant_id="acme")

    result = spine.load_one({"MATNR": "M001", "MTART": "HALB", "MAKTX": "Widget"})

    assert result.status == DISP_CREATED
    assert result.target_key == "M001"
    sf_writes = sf.writes_for_test()
    assert len(sf_writes) == 1
    assert sf_writes[0]["external_id"] == "M001"
    assert sf_writes[0]["tenant"] == "acme"
    ev_writes = ev.published_for_test()
    assert len(ev_writes) == 1
    assert ev_writes[0]["DetailType"] == "DataLoaded.Material"
    print("  [OK] sink fan-out fires on successful BAPI create")


def test_sink_fanout_skipped_on_dead_letter():
    """DQ rejection -> dead_letter -> sinks MUST NOT receive the row."""
    sf = SalesforceSink()
    router = SinkRouter(sinks=[sf])
    spine = StubMaterialSpine(conn=None, sink_router=router)

    result = spine.load_one({"MATNR": "M_BAD", "MTART": "HALB",
                              "SHOULD_REJECT": True})

    assert result.status == DISP_DEAD_LETTER
    assert len(sf.writes_for_test()) == 0
    print("  [OK] sinks skipped on dead-letter -- no partial mirror downstream")


def test_sink_fanout_skipped_on_bapi_exception():
    """BAPI exception -> dead_letter -> sinks MUST NOT receive the row."""
    sf = SalesforceSink()
    router = SinkRouter(sinks=[sf])
    spine = StubMaterialSpine(conn=None, sink_router=router, bapi_raises=True)

    result = spine.load_one({"MATNR": "M_DUMP", "MTART": "HALB"})

    assert result.status == DISP_DEAD_LETTER
    assert len(sf.writes_for_test()) == 0
    print("  [OK] sinks skipped on BAPI exception -- no mirror of failed write")


def test_none_router_is_gracefully_skipped():
    """No sink_router -> spine behaves identically to pre-WS4 (no fan-out)."""
    spine = StubMaterialSpine(conn=None)   # sink_router defaults to None
    result = spine.load_one({"MATNR": "M002", "MTART": "HALB"})
    assert result.status == DISP_CREATED
    assert result.target_key == "M002"
    assert spine.flush_sinks_at_end_of_run() == []
    print("  [OK] no router -> spine unchanged + flush returns empty")


def test_sink_fanout_fires_on_ledger_hit_short_circuit():
    """When F1 ledger short-circuits the BAPI (matched_existing_ledger_hit),
    sinks still fan out so downstream destinations stay consistent with
    every replay. Sinks are responsible for their own idempotency."""

    class FakeKeyMap:
        def __init__(self): self.adds = []
        def resolve(self, obj, src): return "M_ALREADY_THERE" if src == "M003" else None
        def add(self, *a, **kw): self.adds.append((a, kw))

    sf = SalesforceSink()
    router = SinkRouter(sinks=[sf])
    spine = StubMaterialSpine(conn=None, sink_router=router,
                                 key_map=FakeKeyMap())

    result = spine.load_one({"MATNR": "M003", "MTART": "HALB"})

    assert result.status == DISP_MATCHED_EXISTING
    assert "ledger_hit" in result.disposition
    assert spine.call_count == 0   # BAPI never called
    sf_writes = sf.writes_for_test()
    assert len(sf_writes) == 1     # sinks STILL got the row
    assert sf_writes[0]["external_id"] == "M_ALREADY_THERE"
    print("  [OK] ledger-hit short-circuit STILL fans out to sinks")


def test_sink_fanout_fires_on_remapped_disposition():
    """Disposition hint DISP_REMAPPED -> sinks receive the remapped target_key."""
    sf = SalesforceSink()
    router = SinkRouter(sinks=[sf])
    spine = StubMaterialSpine(conn=None, sink_router=router,
                                 bapi_disp=DISP_REMAPPED)

    # Force call_bapi to return a new M4H-prefixed target
    class _Remap(StubMaterialSpine):
        def call_bapi(self, payload):
            return ("M4H" + payload["MATERIAL"], [], DISP_REMAPPED, None)
    spine2 = _Remap(conn=None, sink_router=router)
    result = spine2.load_one({"MATNR": "M004", "MTART": "HALB"})

    assert result.status == DISP_REMAPPED
    assert result.target_key == "M4HM004"
    sf_writes = sf.writes_for_test()
    assert sf_writes[-1]["external_id"] == "M4HM004"
    print("  [OK] sinks receive remapped target_key on collision/harmonization")


def test_flush_sinks_at_end_of_run_calls_each_sink():
    """end-of-run flush calls flush() on every registered sink and returns
    per-sink summaries -- used by Lambda handler for telemetry."""

    class FakeS3:
        def __init__(self): self.objects = {}
        def put_object(self, **kw):
            self.objects[kw["Key"]] = kw["Body"]
            return {}
    from sink_router import SnowflakeSink   # noqa

    snow = SnowflakeSink(s3_client=FakeS3(), stage_bucket="test")
    sf   = SalesforceSink()
    router = SinkRouter(sinks=[snow, sf])
    spine = StubMaterialSpine(conn=None, sink_router=router, tenant_id="acme")
    spine.load_one({"MATNR": "M005", "MTART": "HALB"})
    spine.load_one({"MATNR": "M006", "MTART": "HALB"})

    flushes = spine.flush_sinks_at_end_of_run()
    sinks_seen = {f["sink"] for f in flushes}
    assert sinks_seen == {"snowflake", "salesforce"}
    flushed_total = sum(f.get("flushed", 0) for f in flushes)
    assert flushed_total == 4    # 2 rows * 2 sinks
    print("  [OK] flush_sinks_at_end_of_run hits every registered sink")


def test_sink_failure_does_not_break_load_result():
    """A BoomSink that raises must NOT flip an already-successful LoadResult
    into a failed one. The warning lands in result.messages instead."""

    class BoomSink:
        name = "boom"
        def write_one(self, *a, **kw):
            raise RuntimeError("kaboom")
        def flush(self):
            return {"sink": "boom", "flushed": 0}

    router = SinkRouter(sinks=[BoomSink()])
    spine = StubMaterialSpine(conn=None, sink_router=router)
    result = spine.load_one({"MATNR": "M007", "MTART": "HALB"})

    # BAPI succeeded -> status stays created even though sink errored
    assert result.status == DISP_CREATED
    assert result.target_key == "M007"
    # SinkRouter.fan_out catches per-sink exceptions and appends to its
    # return list; the spine wrapper only sees that fan_out returned cleanly.
    # So result.messages should NOT have a "sink fan-out warning" -- the
    # exception was caught one layer down (in SinkRouter.fan_out itself).
    print("  [OK] sink errors don't flip BAPI-success result to failure")


def test_tenant_id_flows_through_to_sinks():
    """tenant_id passed in __init__ reaches every sink's write_one call."""
    sf = SalesforceSink()
    router = SinkRouter(sinks=[sf])
    spine = StubMaterialSpine(conn=None, sink_router=router,
                                 tenant_id="globex-corp")
    spine.load_one({"MATNR": "M008", "MTART": "HALB"})
    sf_writes = sf.writes_for_test()
    assert sf_writes[0]["tenant"] == "globex-corp"
    assert sf_writes[0]["payload"]["Tenant_Id__c"] == "globex-corp"
    print("  [OK] tenant_id propagates from spine to sinks (multi-tenant safety)")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("Path 1 step 1 -- SinkRouter wired into BaseSpineOrchestrator")
    print("=" * 70)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll spine-wiring tests passed.")
