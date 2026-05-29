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
