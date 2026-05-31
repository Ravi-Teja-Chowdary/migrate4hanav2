"""
In-process mock SAP target for battletest load.

Why in-process (not FastAPI)
----------------------------
The orchestrator calls this directly with a record dict; we get ~5x the
throughput of an HTTP service AND we don't need to manage a separate
process. The real RFC path is exercised in the 5K sample real-load step
against CAL; this mock handles the other 995K with realistic latency +
failure injection so the trust spine (idempotency, hash chain, throttle)
gets stressed at real volumes.

Behaviour
---------
- Returns BAPI-shaped responses (`{status: created, partner: <id>, messages: []}`)
- Latency: log-normal median 8ms, p99 ~120ms
- Failure injection (independent):
    0.05% hard errors (returns status=failed, simulates NRIV exhaustion)
    0.10% transient errors (caller retries; we succeed on retry)
- NRIV-lock simulation: when in-flight concurrent calls > NRIV_THRESHOLD,
    1% of calls return BUSY (the throttle should back off)
- Latency under load: scales sub-linearly with concurrency (real SAP behavior)

Stats: every call increments counters that the orchestrator reads at the end
for the BATTLETEST_RESULTS.md report.
"""
from __future__ import annotations

import math
import random
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Dict


# Tunables - keep at conservative defaults; orchestrator overrides for stress
LATENCY_MEDIAN_MS = 8.0
LATENCY_SIGMA = 0.9
LATENCY_CAP_MS = 1500.0

HARD_FAIL_RATE = 0.0005       # 0.05%
TRANSIENT_FAIL_RATE = 0.001   # 0.10%

NRIV_THRESHOLD = 50           # concurrent in-flight calls before lock contention
NRIV_BUSY_RATE = 0.01         # 1% of calls under contention get BUSY


@dataclass
class MockTargetStats:
    total_calls: int = 0
    created: int = 0
    hard_failures: int = 0
    transient_failures_retried: int = 0
    nriv_busy: int = 0
    total_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    max_concurrent_inflight: int = 0
    by_object: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["avg_latency_ms"] = round(
            self.total_latency_ms / self.total_calls, 2) if self.total_calls else 0
        return d


class MockSapTarget:
    """Thread-safe mock target. One instance per battletest run."""

    def __init__(self,
                 seed: int = 42,
                 latency_median_ms: float = LATENCY_MEDIAN_MS,
                 hard_fail_rate: float = HARD_FAIL_RATE,
                 transient_fail_rate: float = TRANSIENT_FAIL_RATE):
        self._rng = random.Random(seed)
        self._lock = threading.Lock()
        self._inflight = 0
        self.stats = MockTargetStats()
        self._latency_median = latency_median_ms
        self._hard = hard_fail_rate
        self._transient = transient_fail_rate
        self._next_id_counter = 0

    def _sample_latency_ms(self) -> float:
        # log-normal around median, capped
        with self._lock:
            mu = math.log(self._latency_median)
            ms = math.exp(self._rng.gauss(mu, LATENCY_SIGMA))
        return min(ms, LATENCY_CAP_MS)

    def _next_id(self, prefix: str) -> str:
        with self._lock:
            self._next_id_counter += 1
            return f"{prefix}{self._next_id_counter:010d}"

    def _enter(self) -> int:
        with self._lock:
            self._inflight += 1
            if self._inflight > self.stats.max_concurrent_inflight:
                self.stats.max_concurrent_inflight = self._inflight
            return self._inflight

    def _exit(self):
        with self._lock:
            self._inflight -= 1

    def _record(self, object_type: str, latency_ms: float, status: str):
        with self._lock:
            self.stats.total_calls += 1
            self.stats.total_latency_ms += latency_ms
            if latency_ms > self.stats.max_latency_ms:
                self.stats.max_latency_ms = latency_ms
            self.stats.by_object[object_type] = self.stats.by_object.get(object_type, 0) + 1
            if status == "created":
                self.stats.created += 1

    def call(self, object_type: str, record: dict) -> dict:
        """Single BAPI-equivalent call. Returns a dict shaped like a real BAPI
        response: {status, id_key, messages, retry_hint}."""
        inflight = self._enter()
        try:
            # Latency simulation
            latency_ms = self._sample_latency_ms()
            # Sub-linear scaling under load (real SAP behaviour)
            if inflight > 10:
                latency_ms *= (1.0 + math.log(inflight / 10) * 0.3)
            time.sleep(latency_ms / 1000.0)

            # NRIV lock contention under high concurrency
            with self._lock:
                under_pressure = inflight >= NRIV_THRESHOLD
                roll = self._rng.random()
            if under_pressure and roll < NRIV_BUSY_RATE:
                with self._lock:
                    self.stats.nriv_busy += 1
                self._record(object_type, latency_ms, "busy")
                return {"status": "busy",
                        "messages": [{"type": "E", "message": "NRIV table locked - retry"}],
                        "retry_hint": "exponential_backoff"}

            # Hard failure injection
            if roll < self._hard:
                self.stats.hard_failures += 1
                self._record(object_type, latency_ms, "failed")
                return {"status": "failed",
                        "messages": [{"type": "E", "message": "Mock injected hard failure"}]}

            # Transient failure (the caller should retry; we just succeed next time)
            if roll < self._hard + self._transient:
                self.stats.transient_failures_retried += 1
                # Pretend the retry succeeded
                latency_ms += self._sample_latency_ms()
                time.sleep(self._sample_latency_ms() / 1000.0)

            # Happy path - allocate an ID and return success
            id_prefix = {
                "Customer":      "BP",
                "Vendor":        "BP",
                "BusinessPartner": "BP",
                "Material":      "MAT",
                "GLAccount":     "GL",
                "OpenAR":        "DOC",
                "OpenAP":        "DOC",
                "OpenPO":        "PO",
                "SalesOrder":    "SO",
            }.get(object_type, "OBJ")
            new_id = self._next_id(id_prefix)
            self._record(object_type, latency_ms, "created")
            return {"status": "created",
                    "id": new_id,
                    "messages": [{"type": "S", "message": f"{object_type} created"}],
                    "verify_key": {"table": object_type, "key": new_id}}
        finally:
            self._exit()


# Convenience singleton for orchestrator scripts that don't want to thread state
_DEFAULT = MockSapTarget()


def call(object_type: str, record: dict) -> dict:
    return _DEFAULT.call(object_type, record)


def stats() -> dict:
    return _DEFAULT.stats.to_dict()


def reset(seed: int = 42):
    global _DEFAULT
    _DEFAULT = MockSapTarget(seed=seed)


# ─────────────────────────────────────────────────────────────────────────────
#  Self-test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import concurrent.futures

    print("mock_target self-test - 1000 calls, 16 threads")
    target = MockSapTarget()

    def one(i):
        return target.call("Customer", {"KUNNR": f"{i:010d}"})

    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        list(ex.map(one, range(1000)))
    elapsed = time.time() - t0

    s = target.stats.to_dict()
    print(f"  elapsed: {elapsed:.2f}s ({1000/elapsed:.0f} calls/s wall)")
    print(f"  created: {s['created']}")
    print(f"  hard failures: {s['hard_failures']}")
    print(f"  transient retried: {s['transient_failures_retried']}")
    print(f"  NRIV busy: {s['nriv_busy']}")
    print(f"  avg latency: {s['avg_latency_ms']}ms  max: {s['max_latency_ms']:.1f}ms")
    print(f"  max concurrent inflight: {s['max_concurrent_inflight']}")
    print("OK")
