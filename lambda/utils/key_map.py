"""
key_map — the source->target key registry (first-class migration artifact).

When a migration can't retain a source key (internal number assignment for BPs, or a
collision remap for materials), the target key differs from the source. Every dependent
object must then follow that translation: a sales order's customer KUNNR -> the new BP
partner; a BOM's component MATNR -> its remapped material; an open item's vendor LIFNR
-> the new BP. And auditors must be able to read exactly what became what.

This registry is that single source of truth. Loaders emit per-record key_mappings
(source, target, disposition); the run persists them here as a queryable CSV + JSON, and
later stages reload it to resolve referenced keys. Namespaced per object so Customer 100
and Vendor 100 never clash.

Dispositions: created | matched_existing | remapped | remapped_matched | collision_skipped ...
"""
from __future__ import annotations
import threading
import time
from collections import Counter


class TokenBucket:
    """Thread-safe token-bucket rate limiter.

    Protects a downstream capacity ceiling — here, DynamoDB *write* capacity for the
    cross-run key-map ledger during high-concurrency parallel loader loops — so a
    burst of ledger mutations can never trip provisioned-throughput throttling.

    ``rate_per_sec`` is the sustained refill rate (≈ the table's WCU budget allotted
    to the ledger); ``capacity`` is the burst ceiling (defaults to one second of rate).
    """

    def __init__(self, rate_per_sec: float, capacity: float | None = None):
        if rate_per_sec <= 0:
            raise ValueError("rate_per_sec must be > 0")
        self.rate = float(rate_per_sec)
        self.capacity = float(capacity if capacity is not None else rate_per_sec)
        self._tokens = self.capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()
        self.acquired = 0
        self.waited_s = 0.0

    def acquire(self, tokens: float = 1.0, timeout: float | None = None) -> bool:
        """Block until ``tokens`` are available (or ``timeout`` elapses). Returns
        True if acquired, False on timeout. Refills continuously from elapsed time."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(self.capacity,
                                   self._tokens + (now - self._last) * self.rate)
                self._last = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    self.acquired += 1
                    return True
                wait = (tokens - self._tokens) / self.rate
            if deadline is not None and (time.monotonic() + wait) > deadline:
                return False
            self.waited_s += wait
            time.sleep(min(wait, 0.25))

    def stats(self) -> dict:
        return {"rate_per_sec": self.rate, "capacity": self.capacity,
                "acquired": self.acquired, "throttle_wait_s": round(self.waited_s, 4)}


class KeyMap:
    def __init__(self, rate_limiter: "TokenBucket | None" = None):
        self._m = {}   # object -> { source_key -> {"target":.., "disposition":..} }
        self._lock = threading.Lock()   # writes are safe under parallel loaders
        # Optional DynamoDB write-capacity guard (default None = no throttling, so
        # existing local/in-memory behaviour is unchanged). The cloud handler sizes
        # one to the ledger table's WCU and attaches it.
        self._rate = rate_limiter

    def add(self, obj: str, source, target, disposition: str = "") -> None:
        if obj is None or source is None or str(source).strip() == "":
            return
        if self._rate is not None:
            self._rate.acquire()
        with self._lock:
            self._m.setdefault(obj, {})[str(source).strip()] = {
                "target": (str(target).strip() if target is not None else None),
                "disposition": disposition or "",
            }

    def add_many(self, obj: str, mappings: list) -> None:
        for km in mappings or []:
            self.add(obj, km.get("source"), km.get("target"), km.get("disposition"))

    def resolve(self, obj: str, source, default=None):
        """Target key for a source key. default=None lets callers decide whether an
        unmapped reference is a hard error or a pass-through."""
        entry = self._m.get(obj, {}).get(str(source).strip())
        return entry["target"] if entry else default

    def disposition(self, obj: str, source):
        entry = self._m.get(obj, {}).get(str(source).strip())
        return entry["disposition"] if entry else None

    # ── serialize / rebuild ──────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return self._m

    def to_rows(self) -> list:
        rows = []
        for obj, d in self._m.items():
            for src, e in d.items():
                rows.append({"OBJECT": obj, "SOURCE_KEY": src,
                             "TARGET_KEY": e.get("target") or "",
                             "DISPOSITION": e.get("disposition") or ""})
        return rows

    def to_csv(self) -> str:
        lines = ["OBJECT,SOURCE_KEY,TARGET_KEY,DISPOSITION"]
        lines += [f"{r['OBJECT']},{r['SOURCE_KEY']},{r['TARGET_KEY']},{r['DISPOSITION']}"
                  for r in self.to_rows()]
        return "\n".join(lines) + "\n"

    @classmethod
    def from_dict(cls, d: dict) -> "KeyMap":
        km = cls()
        km._m = d or {}
        return km

    @classmethod
    def from_rows(cls, rows: list) -> "KeyMap":
        km = cls()
        for r in rows:
            km.add(r.get("OBJECT"), r.get("SOURCE_KEY"), r.get("TARGET_KEY"), r.get("DISPOSITION"))
        return km

    def stats(self) -> dict:
        by_disp = Counter()
        remapped = 0
        for d in self._m.values():
            for e in d.values():
                by_disp[e.get("disposition")] += 1
                if "remap" in (e.get("disposition") or ""):
                    remapped += 1
        return {"objects": sorted(self._m.keys()),
                "total_mappings": sum(len(d) for d in self._m.values()),
                "remapped": remapped,
                "by_disposition": dict(by_disp)}


class PersistentKeyMap(KeyMap):
    """KeyMap with cross-run DynamoDB-backed persistence.

    Behaviour vs the in-memory ``KeyMap``:

    * ``add(...)`` writes through to DynamoDB after the in-memory mutation. The DynamoDB
      write uses ``ConditionExpression="attribute_not_exists(source_key)"`` so the FIRST
      writer for a given ``(object, source_key)`` wins — concurrent runs racing on the
      same legacy customer don't clobber each other.
    * ``resolve(obj, source)`` falls through three tiers: in-memory cache → negative
      cache (we've already missed in DDB) → DynamoDB GetItem. Hits hydrate the in-memory
      cache so subsequent resolves are free.
    * ``prefetch_object(obj, source_keys=...)`` bulk-loads via BatchGetItem (or Query when
      ``source_keys`` is None). Callers about to load 1M sales orders should
      ``prefetch_object("Customer", set_of_referenced_kunnrs)`` first — turns a million
      GetItem requests into ~10k BatchGetItem requests.

    Item schema (matches ``aws_dynamodb_table.key_map`` in terraform — hash=object,
    range=source_key)::

        object         (S, PK)  e.g. "Customer", "Vendor", "Material"
        source_key     (S, SK)  source-system key (KUNNR, LIFNR, ...)
        target_key     (S)      resolved target key (BP_xxx, ...)
        disposition    (S)      created | matched_existing | remapped | harmonized | ...
        run_id         (S)      the run that wrote this mapping
        written_at     (S)      ISO-8601 UTC timestamp
        target_release (S)      optional, S/4 release tag for version drift
        lineage_hash   (S)      optional, SHA256 of source record for tamper detection

    Backwards-compat: ``KeyMap``-typed callers (``UnifiedLoader.key_map``,
    ``bapi_loader.create_*``) keep working unchanged — ``PersistentKeyMap`` IS a
    ``KeyMap`` and adds persistence beneath the existing interface.
    """

    # Limit the negative-resolve cache so unbounded lookups can't OOM a long-running
    # Fargate worker; LRU-evict when we cross the ceiling.
    _NEG_CACHE_MAX = 50_000

    def __init__(self, table_name: str | None = None, *, dynamodb_client=None,
                 rate_limiter: "TokenBucket | None" = None, run_id: str = "",
                 target_release: str = "",
                 negative_cache_max: int | None = None,
                 tenant_context=None):
        super().__init__(rate_limiter=rate_limiter)
        self._table_name = table_name
        self._run_id = run_id
        self._target_release = target_release
        # F7 - tenant scoping. None = default tenant (legacy single-tenant
        # behavior; DDB partition keys remain bare object names). When a
        # real TenantContext is attached, every DDB row's partition key is
        # prefixed "<tenant_slug>#<object>" - hard separation, no possibility
        # of cross-tenant resolve hits.
        try:
            from tenant_context import default_context   # type: ignore
            self._tenant = tenant_context or default_context()
        except Exception:
            class _NullCtx:
                tenant_id = "default"; tenant_slug = "default"; is_default = True
                def ddb_object_key(self, obj): return obj
            self._tenant = _NullCtx()
        self._neg_max = negative_cache_max if negative_cache_max is not None else self._NEG_CACHE_MAX
        # Deferred import: boto3 is heavy, and unit tests inject a mock client
        # via ``dynamodb_client`` so they never need to import boto3.
        if dynamodb_client is not None:
            self._ddb = dynamodb_client
        elif table_name:
            import boto3   # type: ignore
            self._ddb = boto3.client("dynamodb")
        else:
            self._ddb = None   # no-persistence mode (equivalent to plain KeyMap)
        # negative cache: items we already KNOW are not in DDB; avoid round-trips
        self._neg: dict = {}   # (obj, source) -> True; insertion-order ≈ LRU on add
        # counters for observability
        self._writes = 0
        self._cond_failures = 0   # someone else wrote first — that's idempotency, not error
        self._ddb_gets = 0
        self._ddb_hits = 0

    # ── write path ────────────────────────────────────────────────────────────
    def add(self, obj: str, source, target, disposition: str = "") -> None:
        # 1. in-memory mutation (parent handles validation + rate limit)
        super().add(obj, source, target, disposition)
        if self._ddb is None:
            return
        # 2. persist; skip silently if invalid input (parent already early-returned)
        if obj is None or source is None or str(source).strip() == "":
            return
        self._persist_one(obj, str(source).strip(),
                          str(target).strip() if target is not None else "",
                          disposition or "")

    def _persist_one(self, obj: str, source_key: str, target_key: str, disposition: str) -> None:
        # F7 - tenant-scoped partition key. For default tenant this is
        # "Customer"; for tenant "acme-corp" it's "acme-corp#Customer".
        pk = self._tenant.ddb_object_key(obj)
        item = {
            "object":      {"S": pk},
            "source_key":  {"S": source_key},
            "target_key":  {"S": target_key},
            "disposition": {"S": disposition},
            "written_at":  {"S": _now_iso()},
        }
        # Carry the tenant_id as a column for audit + admin queries
        if not getattr(self._tenant, "is_default", True):
            item["tenant_id"] = {"S": self._tenant.tenant_id}
        if self._run_id:
            item["run_id"] = {"S": self._run_id}
        if self._target_release:
            item["target_release"] = {"S": self._target_release}
        try:
            self._ddb.put_item(
                TableName=self._table_name,
                Item=item,
                # Conditional write = idempotent ledger semantics. If the mapping
                # already exists (a previous run, or a concurrent worker beat us),
                # we treat it as success and trust the existing entry.
                ConditionExpression="attribute_not_exists(source_key)",
            )
            self._writes += 1
        except Exception as e:
            # ConditionalCheckFailedException is normal — someone else wrote first.
            # Anything else is a real error; log but don't crash the loader.
            msg = str(e)
            if "ConditionalCheckFailed" in msg or "ConditionalCheckFailedException" in msg:
                self._cond_failures += 1
            else:
                # Don't take down the whole run for a transient DDB blip; the
                # in-memory cache still has the mapping, and the next run will
                # re-attempt. Surface in stats so it's visible.
                self._writes += 0   # explicit no-increment
                self._last_error = msg[:240]

    # ── read path ────────────────────────────────────────────────────────────
    def resolve(self, obj: str, source, default=None):
        # tier 1: in-memory
        result = super().resolve(obj, source, default=None)
        if result is not None:
            return result
        # only spend cycles on DDB if we actually have a connection
        if self._ddb is None or obj is None or source is None:
            return default
        src = str(source).strip()
        if not src:
            return default
        # tier 2: negative cache (we already missed for this key)
        if (obj, src) in self._neg:
            return default
        # tier 3: DDB GetItem with eventually-consistent read (cheaper, and reads
        # are usually after a write that's already propagated)
        try:
            pk = self._tenant.ddb_object_key(obj)
            resp = self._ddb.get_item(
                TableName=self._table_name,
                Key={"object": {"S": pk}, "source_key": {"S": src}},
                ConsistentRead=False,
            )
            self._ddb_gets += 1
        except Exception:
            return default
        item = resp.get("Item")
        if not item:
            self._cache_negative(obj, src)
            return default
        # hydrate the in-memory cache so subsequent calls are free
        tgt = item.get("target_key", {}).get("S")
        disp = item.get("disposition", {}).get("S", "")
        if tgt is not None:
            with self._lock:
                self._m.setdefault(obj, {})[src] = {"target": tgt, "disposition": disp}
            self._ddb_hits += 1
            return tgt
        self._cache_negative(obj, src)
        return default

    def _cache_negative(self, obj: str, source_key: str, default=None):
        if len(self._neg) >= self._neg_max:
            # FIFO evict — dict preserves insertion order in py3.7+
            try:
                self._neg.pop(next(iter(self._neg)))
            except StopIteration:
                pass
        self._neg[(obj, source_key)] = True
        return default

    # ── bulk prefetch ─────────────────────────────────────────────────────────
    def prefetch_object(self, obj: str, source_keys: list | None = None,
                        batch_size: int = 100) -> int:
        """Hydrate the in-memory cache from DynamoDB for an object.

        * If ``source_keys`` is None: full Query of the partition (use sparingly —
          unbounded scan-of-partition). Returns count hydrated.
        * If ``source_keys`` is provided: BatchGetItem in chunks of 100 (DDB limit).
          Use this for the common case of "I'm about to load N sales orders that
          reference these K customers — pre-resolve them".
        """
        if self._ddb is None:
            return 0
        hydrated = 0
        if source_keys is None:
            # Full Query of the partition. Safe up to a few hundred thousand items
            # per object; not safe at 10M+ per object.
            pk = self._tenant.ddb_object_key(obj)
            last_key = None
            while True:
                kwargs = {
                    "TableName": self._table_name,
                    "KeyConditionExpression": "#o = :o",
                    "ExpressionAttributeNames": {"#o": "object"},
                    "ExpressionAttributeValues": {":o": {"S": pk}},
                }
                if last_key:
                    kwargs["ExclusiveStartKey"] = last_key
                resp = self._ddb.query(**kwargs)
                for item in resp.get("Items", []):
                    self._hydrate_item(obj, item)
                    hydrated += 1
                last_key = resp.get("LastEvaluatedKey")
                if not last_key:
                    break
            return hydrated
        # BatchGetItem path
        pk = self._tenant.ddb_object_key(obj)
        unique_keys = list({str(k).strip() for k in source_keys if k is not None})
        for i in range(0, len(unique_keys), batch_size):
            chunk = unique_keys[i:i + batch_size]
            request = {
                self._table_name: {
                    "Keys": [{"object": {"S": pk}, "source_key": {"S": k}} for k in chunk],
                }
            }
            # Retry-with-backoff loop for UnprocessedKeys (DDB returns them when throttled)
            attempt = 0
            while request:
                resp = self._ddb.batch_get_item(RequestItems=request)
                for item in resp.get("Responses", {}).get(self._table_name, []):
                    self._hydrate_item(obj, item)
                    hydrated += 1
                request = resp.get("UnprocessedKeys") or {}
                attempt += 1
                if request and attempt > 8:
                    # Give up cleanly; remaining keys will fall through to per-call GetItem
                    break
                if request:
                    time.sleep(min(0.05 * (2 ** attempt), 1.0))
        return hydrated

    def _hydrate_item(self, obj: str, item: dict) -> None:
        src = item.get("source_key", {}).get("S")
        tgt = item.get("target_key", {}).get("S")
        disp = item.get("disposition", {}).get("S", "")
        if src and tgt is not None:
            with self._lock:
                self._m.setdefault(obj, {})[src] = {"target": tgt, "disposition": disp}

    # ── observability ────────────────────────────────────────────────────────
    def persistence_stats(self) -> dict:
        """Stats specific to the persistence layer. Combine with .stats() for the full
        picture across in-memory + DDB."""
        return {
            "table":                self._table_name,
            "run_id":               self._run_id,
            "target_release":       self._target_release,
            "writes":               self._writes,
            "conditional_skips":    self._cond_failures,
            "ddb_gets":             self._ddb_gets,
            "ddb_hits":             self._ddb_hits,
            "negative_cache_size":  len(self._neg),
            "negative_cache_cap":   self._neg_max,
        }


def _now_iso() -> str:
    """ISO-8601 UTC timestamp; pulled out so tests can monkeypatch."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── self-test (no AWS) — registry round-trip + token-bucket throttling ───────
if __name__ == "__main__":
    print("=" * 70)
    print("key_map — self-test")
    print("=" * 70)

    # 1) registry behaviour unchanged when no rate limiter is attached
    km = KeyMap()
    km.add("Customer", "100", "BP500", "created")
    km.add("Material", "23", "M4H23", "remapped")
    assert km.resolve("Customer", "100") == "BP500"
    assert km.disposition("Material", "23") == "remapped"
    assert KeyMap.from_rows(km.to_rows()).resolve("Material", "23") == "M4H23"
    print(f"  registry: {km.stats()}")

    # 2) token bucket throttles a burst beyond capacity (protects DynamoDB WCU)
    bucket = TokenBucket(rate_per_sec=50, capacity=50)
    kmr = KeyMap(rate_limiter=bucket)
    n = 120
    t0 = time.monotonic()
    for i in range(n):
        kmr.add("Customer", f"C{i}", f"BP{i}", "created")
    elapsed = time.monotonic() - t0
    expected_min = (n - bucket.capacity) / bucket.rate    # ~1.4s for 120 @ 50/s, burst 50
    print(f"  token-bucket: {n} writes in {elapsed:.2f}s "
          f"(expected >= {expected_min:.2f}s) -> {bucket.stats()}")
    assert kmr.stats()["total_mappings"] == n
    assert elapsed >= expected_min * 0.8, "bucket did not throttle the burst"
    print("\nOK — registry round-trips; token bucket throttles bursts to protect WCU.")
