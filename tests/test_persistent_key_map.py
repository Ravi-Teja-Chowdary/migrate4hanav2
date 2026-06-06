"""
Unit tests for PersistentKeyMap — the DynamoDB-backed cross-run key registry.

These run with NO live AWS — DynamoDB is mocked via a small in-memory stand-in
that enforces the ConditionExpression semantics we depend on for idempotency.

Run:  python tests/test_persistent_key_map.py
"""
from __future__ import annotations
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lambda" / "utils"))

from key_map import KeyMap, PersistentKeyMap, TokenBucket  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# In-memory DynamoDB stand-in
# ─────────────────────────────────────────────────────────────────────────────
class FakeConditionalCheckFailedException(Exception):
    """Stand-in for botocore.exceptions.ClientError(ConditionalCheckFailedException)."""
    def __str__(self):
        return "ConditionalCheckFailedException: " + super().__str__()


class FakeDynamoDB:
    """Minimal DDB client mock. Honours ConditionExpression on PutItem and exposes
    inspection helpers (.items, .put_calls)."""

    def __init__(self):
        # storage keyed by (object, source_key) -> raw item dict in DDB format
        self.items: dict = {}
        self.put_calls = 0
        self.get_calls = 0
        self.batch_get_calls = 0
        self.query_calls = 0
        # Simulate transient failures for tests that want to exercise error paths
        self.fail_next_put = False
        self._lock = threading.Lock()

    @staticmethod
    def _key(item):
        return (item["object"]["S"], item["source_key"]["S"])

    def put_item(self, *, TableName, Item, ConditionExpression=None):
        with self._lock:
            if self.fail_next_put:
                self.fail_next_put = False
                raise RuntimeError("simulated transient DDB error")
            self.put_calls += 1
            k = self._key(Item)
            if ConditionExpression and "attribute_not_exists" in ConditionExpression and k in self.items:
                raise FakeConditionalCheckFailedException(
                    f"ConditionalCheckFailedException for {k}"
                )
            self.items[k] = Item
            return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def get_item(self, *, TableName, Key, ConsistentRead=False):
        with self._lock:
            self.get_calls += 1
            k = (Key["object"]["S"], Key["source_key"]["S"])
            item = self.items.get(k)
            return {"Item": item} if item else {}

    def batch_get_item(self, *, RequestItems):
        with self._lock:
            self.batch_get_calls += 1
            responses = {}
            for table, req in RequestItems.items():
                rows = []
                for key in req["Keys"]:
                    k = (key["object"]["S"], key["source_key"]["S"])
                    if k in self.items:
                        rows.append(self.items[k])
                responses[table] = rows
            return {"Responses": responses, "UnprocessedKeys": {}}

    def query(self, *, TableName, KeyConditionExpression,
              ExpressionAttributeNames, ExpressionAttributeValues, ExclusiveStartKey=None):
        with self._lock:
            self.query_calls += 1
            obj = ExpressionAttributeValues[":o"]["S"]
            matching = [item for (o, _), item in self.items.items() if o == obj]
            return {"Items": matching}


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────
def test_in_memory_subclass_compat():
    """PersistentKeyMap IS a KeyMap — existing in-memory contract preserved."""
    pk = PersistentKeyMap(table_name=None, dynamodb_client=None, run_id="run-1")
    pk.add("Customer", "0001000123", "BP_500", "created")
    assert pk.resolve("Customer", "0001000123") == "BP_500"
    assert pk.disposition("Customer", "0001000123") == "created"
    rows = pk.to_rows()
    assert len(rows) == 1
    assert rows[0]["OBJECT"] == "Customer"
    assert rows[0]["TARGET_KEY"] == "BP_500"
    print("  [OK]in-memory subclass compatibility")


def test_add_writes_through_to_ddb():
    """add(...) hits DDB after the in-memory mutation."""
    ddb = FakeDynamoDB()
    pk = PersistentKeyMap(table_name="m4h-key-map-test", dynamodb_client=ddb, run_id="run-2")
    pk.add("Vendor", "L_900", "BP_VEN_1", "harmonized")

    assert ddb.put_calls == 1
    k = ("Vendor", "L_900")
    assert k in ddb.items
    item = ddb.items[k]
    assert item["target_key"]["S"] == "BP_VEN_1"
    assert item["disposition"]["S"] == "harmonized"
    assert item["run_id"]["S"] == "run-2"
    assert "written_at" in item
    print("  [OK]add() persists to DDB with full item payload")


def test_resolve_falls_through_to_ddb_on_miss():
    """Cold-cache resolve() finds the mapping via DDB and hydrates memory."""
    ddb = FakeDynamoDB()
    # Pre-populate DDB as if a previous run wrote this
    ddb.items[("Customer", "C100")] = {
        "object":      {"S": "Customer"},
        "source_key":  {"S": "C100"},
        "target_key":  {"S": "BP_888"},
        "disposition": {"S": "matched_existing"},
        "written_at":  {"S": "2026-06-02T18:00:00Z"},
    }
    pk = PersistentKeyMap(table_name="m4h-key-map-test", dynamodb_client=ddb, run_id="run-3")

    # in-memory cache is empty, so this hits DDB
    assert pk.resolve("Customer", "C100") == "BP_888"
    assert ddb.get_calls == 1

    # Second resolve hits the in-memory cache (no extra DDB call)
    assert pk.resolve("Customer", "C100") == "BP_888"
    assert ddb.get_calls == 1
    print("  [OK]resolve() falls through to DDB and hydrates the cache")


def test_negative_cache_avoids_repeat_ddb_calls():
    """resolve() for an unknown key checks DDB once, then uses the negative cache."""
    ddb = FakeDynamoDB()
    pk = PersistentKeyMap(table_name="m4h-key-map-test", dynamodb_client=ddb)

    # first call: DDB miss
    assert pk.resolve("Material", "MAT_404") is None
    assert ddb.get_calls == 1

    # 50 more calls for the same missing key — must not hit DDB again
    for _ in range(50):
        assert pk.resolve("Material", "MAT_404") is None
    assert ddb.get_calls == 1
    print("  [OK]negative cache prevents repeat DDB GetItem calls")


def test_conditional_write_handles_idempotency():
    """Re-adding the same (object, source) doesn't crash — ConditionalCheckFailed
    is treated as 'someone else won this race, that's fine'."""
    ddb = FakeDynamoDB()
    pk = PersistentKeyMap(table_name="m4h-key-map-test", dynamodb_client=ddb, run_id="r1")

    pk.add("Customer", "C200", "BP_A", "created")
    assert ddb.put_calls == 1

    # Second add: in-memory will accept, DDB will conditional-fail (already present)
    pk.add("Customer", "C200", "BP_B", "created")
    assert ddb.put_calls == 2
    # Original DDB value is preserved (first-writer-wins)
    assert ddb.items[("Customer", "C200")]["target_key"]["S"] == "BP_A"

    stats = pk.persistence_stats()
    assert stats["writes"] == 1
    assert stats["conditional_skips"] == 1
    print("  [OK]ConditionalCheckFailed is handled as idempotency, not error")


def test_transient_error_does_not_crash_loader():
    """A DDB blip doesn't take down the run — in-memory state is preserved."""
    ddb = FakeDynamoDB()
    ddb.fail_next_put = True
    pk = PersistentKeyMap(table_name="m4h-key-map-test", dynamodb_client=ddb)

    pk.add("Customer", "C300", "BP_X", "created")
    # in-memory still has it (caller sees a successful add())
    assert pk.resolve("Customer", "C300") == "BP_X"
    # but DDB did NOT persist it (the put failed)
    assert ("Customer", "C300") not in ddb.items
    print("  [OK]transient DDB error preserved in-memory state without crashing")


def test_prefetch_object_bulk_loads_known_keys():
    """prefetch_object hydrates the cache via BatchGetItem for a known key set."""
    ddb = FakeDynamoDB()
    for i in range(150):
        ddb.items[("Customer", f"C{i}")] = {
            "object":      {"S": "Customer"},
            "source_key":  {"S": f"C{i}"},
            "target_key":  {"S": f"BP_{i}"},
            "disposition": {"S": "harmonized"},
            "written_at":  {"S": "2026-06-02T18:00:00Z"},
        }

    pk = PersistentKeyMap(table_name="m4h-key-map-test", dynamodb_client=ddb)
    keys_we_care_about = [f"C{i}" for i in range(0, 150, 3)]  # 50 keys
    hydrated = pk.prefetch_object("Customer", source_keys=keys_we_care_about)

    assert hydrated == 50
    # Now resolves for those keys are FREE — no extra DDB calls
    gets_before = ddb.get_calls
    for k in keys_we_care_about:
        assert pk.resolve("Customer", k) is not None
    assert ddb.get_calls == gets_before
    # And BatchGetItem (not 50 individual GetItem) was used
    assert ddb.batch_get_calls >= 1
    print("  [OK]prefetch_object uses BatchGetItem and hydrates the cache cleanly")


def test_prefetch_object_full_query():
    """prefetch_object(obj, source_keys=None) full-Query'es the partition."""
    ddb = FakeDynamoDB()
    for i in range(7):
        ddb.items[("Vendor", f"V{i}")] = {
            "object":      {"S": "Vendor"},
            "source_key":  {"S": f"V{i}"},
            "target_key":  {"S": f"BP_VEN_{i}"},
            "disposition": {"S": "created"},
            "written_at":  {"S": "2026-06-02T18:00:00Z"},
        }

    pk = PersistentKeyMap(table_name="m4h-key-map-test", dynamodb_client=ddb)
    hydrated = pk.prefetch_object("Vendor")
    assert hydrated == 7
    assert ddb.query_calls == 1
    for i in range(7):
        assert pk.resolve("Vendor", f"V{i}") == f"BP_VEN_{i}"
    print("  [OK]prefetch_object full-Query hydrates entire partition")


def test_concurrent_add_safe_under_threads():
    """Many threads adding mappings simultaneously: in-memory consistency + DDB items."""
    ddb = FakeDynamoDB()
    pk = PersistentKeyMap(table_name="m4h-key-map-test", dynamodb_client=ddb, run_id="rcon")

    def worker(start, count):
        for i in range(start, start + count):
            pk.add("Material", f"M{i:06d}", f"NEW_M{i:06d}", "created")

    threads = [threading.Thread(target=worker, args=(t * 200, 200)) for t in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert pk.stats()["total_mappings"] == 2000
    # Every mapping made it to DDB (no ConditionalCheckFailed because keys are unique)
    assert len(ddb.items) == 2000
    print("  [OK]concurrent adds preserved invariants (2000 keys across 10 threads)")


def test_persistence_stats_observability():
    """Stats include both write-path and read-path counters."""
    ddb = FakeDynamoDB()
    pk = PersistentKeyMap(table_name="m4h-key-map-test", dynamodb_client=ddb, run_id="rstats")
    pk.add("Customer", "C1", "BP1", "created")
    pk.resolve("Customer", "C1")            # in-memory hit; not counted as ddb_get
    pk.resolve("Customer", "MISSING")        # ddb miss → negative cache
    pk.resolve("Customer", "MISSING")        # negative cache hit; not counted as ddb_get

    s = pk.persistence_stats()
    assert s["writes"] == 1
    assert s["ddb_gets"] == 1
    assert s["ddb_hits"] == 0
    assert s["negative_cache_size"] == 1
    print("  [OK]persistence_stats() exposes write/read/cache counters")


def test_rate_limiter_pluggability():
    """The optional TokenBucket throttles writes through the PersistentKeyMap path."""
    import time
    ddb = FakeDynamoDB()
    bucket = TokenBucket(rate_per_sec=100, capacity=10)
    pk = PersistentKeyMap(table_name="m4h-key-map-test", dynamodb_client=ddb,
                          rate_limiter=bucket)

    n = 60
    t0 = time.monotonic()
    for i in range(n):
        pk.add("Customer", f"R{i}", f"BP_R{i}", "created")
    elapsed = time.monotonic() - t0
    expected_min = (n - bucket.capacity) / bucket.rate   # ~0.5s
    assert elapsed >= expected_min * 0.5, "TokenBucket failed to throttle the burst"
    assert ddb.put_calls == n
    print(f"  [OK] TokenBucket throttled {n} writes (elapsed {elapsed:.2f}s >= ~{expected_min:.2f}s)")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("PersistentKeyMap — unit tests")
    print("=" * 70)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll PersistentKeyMap tests passed.")
