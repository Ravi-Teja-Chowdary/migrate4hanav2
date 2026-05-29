"""
scaling.py — Pillar 1: infinite-volume stream processing & elastic compute
============================================================================
Two production primitives for processing 10^6–10^8 rows without Lambda 15-minute
timeouts or memory exhaustion:

1. **ComputeDispatcher** — a dynamic dispatcher: when an object's extraction scope
   exceeds a configurable row threshold, the orchestrator bypasses Lambda and runs
   the work as an **AWS ECS Fargate task** (auto-scaled memory). Below threshold it
   stays inline/Lambda. The *decision* is pure and unit-tested; the ECS ``run_task``
   call is gated behind boto3 + Fargate config and degrades to a recorded decision
   when infrastructure is absent.

2. **ODataPager** — strict server-side paging for OData reads using ``$top`` +
   ``$skiptoken`` (follows ``@odata.nextLink`` / v2 ``__next``), so a multi-million
   row entity set is streamed in bounded pages and never materialised whole. The
   pager drives an injected ``fetch`` callable, so it is fully unit-testable and
   works with the project's real ``odata_client``.

(ABAP ``OPEN CURSOR … FETCH … PACKAGE SIZE`` streaming for RFC extraction already
lives in ``agent/in_system_agent_generator.py``; this module covers OData + compute.)
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Optional

logger = logging.getLogger("scaling")

DEFAULT_ROW_THRESHOLD = int(os.environ.get("M4H_FARGATE_ROW_THRESHOLD", "20000"))


@dataclass
class ComputeDecision:
    object_name: str
    est_rows: int
    target: str               # "lambda" | "fargate"
    threshold: int
    memory_mb: int
    reason: str
    dispatched: bool = False
    task_arn: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


class ComputeDispatcher:
    """Route a unit of work to Lambda (inline) or an ECS Fargate task by row volume."""

    # Fargate memory tiers (MiB) — Fargate requires memory from a fixed ladder.
    _MEM_TIERS = [2048, 4096, 8192, 16384, 30720]

    def __init__(self, threshold: int = DEFAULT_ROW_THRESHOLD,
                 cluster: Optional[str] = None, task_def: Optional[str] = None,
                 container: Optional[str] = None, subnets: Optional[list] = None,
                 security_groups: Optional[list] = None, region: Optional[str] = None):
        self.threshold = int(threshold)
        self.cluster = cluster or os.environ.get("M4H_FARGATE_CLUSTER")
        self.task_def = task_def or os.environ.get("M4H_FARGATE_TASKDEF")
        self.container = container or os.environ.get("M4H_FARGATE_CONTAINER", "migrate4hana")
        self.subnets = subnets or [s for s in os.environ.get("M4H_FARGATE_SUBNETS", "").split(",") if s]
        self.security_groups = security_groups or [
            g for g in os.environ.get("M4H_FARGATE_SGS", "").split(",") if g]
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")

    # ── pure decision (unit-tested) ──────────────────────────────────────────
    def memory_for(self, est_rows: int) -> int:
        """Pick a Fargate memory tier that scales with volume (~1 GiB per 250k rows)."""
        want = 2048 + (max(0, est_rows) // 250_000) * 2048
        for tier in self._MEM_TIERS:
            if tier >= want:
                return tier
        return self._MEM_TIERS[-1]

    def decide(self, object_name: str, est_rows: int) -> ComputeDecision:
        est = int(est_rows or 0)
        if est > self.threshold:
            return ComputeDecision(
                object_name=object_name, est_rows=est, target="fargate",
                threshold=self.threshold, memory_mb=self.memory_for(est),
                reason=f"{est} rows > {self.threshold} threshold — offload to Fargate")
        return ComputeDecision(
            object_name=object_name, est_rows=est, target="lambda",
            threshold=self.threshold, memory_mb=0,
            reason=f"{est} rows <= {self.threshold} threshold — run inline/Lambda")

    def fargate_ready(self) -> bool:
        return bool(self.cluster and self.task_def and self.subnets)

    # ── dispatch (infra-gated) ───────────────────────────────────────────────
    def dispatch(self, decision: ComputeDecision, payload: dict) -> ComputeDecision:
        """Execute the decision. For 'lambda' it's a no-op (caller runs inline). For
        'fargate' it launches an ECS task with the payload + memory override. Never
        raises — an infra gap is recorded on the decision and the caller can fall
        back to inline processing."""
        if decision.target != "fargate":
            return decision
        if not self.fargate_ready():
            decision.error = "fargate not configured (cluster/task_def/subnets) — caller must run inline"
            return decision
        try:
            import boto3
            ecs = boto3.client("ecs", region_name=self.region)
            resp = ecs.run_task(
                cluster=self.cluster,
                taskDefinition=self.task_def,
                launchType="FARGATE",
                count=1,
                networkConfiguration={"awsvpcConfiguration": {
                    "subnets": self.subnets,
                    "securityGroups": self.security_groups,
                    "assignPublicIp": "DISABLED"}},
                overrides={
                    "memory": str(decision.memory_mb),
                    "containerOverrides": [{
                        "name": self.container,
                        "environment": [{"name": "M4H_TASK_PAYLOAD", "value": json.dumps(payload)}],
                    }]})
            tasks = resp.get("tasks") or []
            decision.dispatched = bool(tasks)
            decision.task_arn = tasks[0]["taskArn"] if tasks else None
            failures = resp.get("failures") or []
            if failures and not tasks:
                decision.error = f"run_task failures: {failures}"
        except Exception as e:  # noqa: BLE001 — degrade to inline
            decision.error = f"{type(e).__name__}: {str(e)[:160]}"
        return decision


@dataclass
class PageStats:
    pages: int = 0
    rows: int = 0
    skiptokens: list = field(default_factory=list)


class ODataPager:
    """Server-side OData paging via ``$top`` + ``$skiptoken`` (follows next-links).

    ``fetch(params)`` must perform one GET and return a dict shaped like an OData
    response — either v4 ``{"value":[...], "@odata.nextLink": "...$skiptoken=..."}``
    or v2 ``{"d": {"results":[...], "__next": "...$skiptoken=..."}}``. The pager
    yields each page's row list and stops when no next-link remains, so callers
    stream arbitrarily large entity sets in bounded memory.
    """

    def __init__(self, page_size: int = 1000, max_pages: Optional[int] = None):
        if page_size <= 0:
            raise ValueError("page_size must be > 0")
        self.page_size = int(page_size)
        self.max_pages = max_pages
        self.stats = PageStats()

    @staticmethod
    def _extract_rows(resp: dict) -> list:
        if "value" in resp and isinstance(resp["value"], list):       # OData v4
            return resp["value"]
        d = resp.get("d")
        if isinstance(d, dict) and isinstance(d.get("results"), list):  # OData v2
            return d["results"]
        if isinstance(d, list):
            return d
        return []

    @staticmethod
    def _next_skiptoken(resp: dict) -> Optional[str]:
        nxt = resp.get("@odata.nextLink") or (resp.get("d") or {}).get("__next") \
            if isinstance(resp.get("d"), dict) else resp.get("@odata.nextLink")
        if not nxt:
            return None
        # pull the $skiptoken value out of the next-link query string
        for part in str(nxt).split("?", 1)[-1].split("&"):
            if part.startswith("$skiptoken=") or part.startswith("skiptoken="):
                from urllib.parse import unquote
                return unquote(part.split("=", 1)[1])
        return nxt  # opaque next-link — hand it back as-is

    def pages(self, fetch: Callable[[dict], dict], base_params: dict | None = None) -> Iterator[list]:
        """Yield successive page row-lists. ``fetch`` receives params incl. ``$top``
        and (after the first page) ``$skiptoken``."""
        params = dict(base_params or {})
        params["$top"] = self.page_size
        skiptoken = None
        while True:
            if skiptoken is not None:
                params["$skiptoken"] = skiptoken
            resp = fetch(dict(params))
            rows = self._extract_rows(resp)
            self.stats.pages += 1
            self.stats.rows += len(rows)
            yield rows
            skiptoken = self._next_skiptoken(resp)
            if skiptoken:
                self.stats.skiptokens.append(skiptoken)
            if not skiptoken or not rows:
                break
            if self.max_pages and self.stats.pages >= self.max_pages:
                logger.warning("ODataPager hit max_pages=%s", self.max_pages)
                break

    def fetch_all(self, fetch: Callable[[dict], dict], base_params: dict | None = None,
                  sink: Optional[Callable[[list], None]] = None) -> int:
        """Drive paging to exhaustion. If ``sink`` is given, each page is streamed to
        it (bounded memory); otherwise rows accumulate and the total is returned."""
        total = 0
        acc: list = []
        for page in self.pages(fetch, base_params):
            total += len(page)
            if sink is not None:
                sink(page)
            else:
                acc.extend(page)
        self._last_rows = acc
        return total


# ════════════════════════════════════════════════════════════════════════════
#  Self-test (no AWS) — dispatch decision + memory tiers + OData paging
# ════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 72)
    print("scaling — self-test (compute dispatcher + OData pager)")
    print("=" * 72)

    disp = ComputeDispatcher(threshold=20000)
    d_small = disp.decide("Material", 5_000)
    d_big = disp.decide("OpenAR", 1_500_000)
    print(f"\n[dispatch] 5k -> {d_small.target} ({d_small.reason})")
    print(f"[dispatch] 1.5M -> {d_big.target}, mem={d_big.memory_mb}MiB ({d_big.reason})")
    assert d_small.target == "lambda" and d_big.target == "fargate"
    assert d_big.memory_mb >= 8192
    # dispatch with no infra configured -> recorded decision, no crash, caller falls back
    d_big = disp.dispatch(d_big, {"object": "OpenAR"})
    print(f"[dispatch] fargate not configured -> dispatched={d_big.dispatched} error={d_big.error}")
    assert d_big.dispatched is False and d_big.error

    # OData pager over 3 simulated server pages (250 rows total at top=100)
    PAGES = [
        {"value": [{"i": i} for i in range(100)], "@odata.nextLink": "svc?$top=100&$skiptoken=100"},
        {"value": [{"i": i} for i in range(100, 200)], "@odata.nextLink": "svc?$top=100&$skiptoken=200"},
        {"value": [{"i": i} for i in range(200, 250)]},  # last page, no next-link
    ]
    seq = {"n": 0}

    def fake_fetch(params):
        # assert paging params flow through
        assert params["$top"] == 100
        page = PAGES[seq["n"]]
        seq["n"] += 1
        return page

    pager = ODataPager(page_size=100)
    streamed = []
    total = pager.fetch_all(fake_fetch, base_params={"$filter": "BUKRS eq '1710'"},
                            sink=lambda rows: streamed.append(len(rows)))
    print(f"\n[odata] streamed {total} rows over {pager.stats.pages} pages "
          f"(page sizes {streamed}); skiptokens={pager.stats.skiptokens}")
    assert total == 250 and pager.stats.pages == 3 and streamed == [100, 100, 50]
    assert pager.stats.skiptokens == ["100", "200"]

    print("\nOK — dispatcher routes by volume + picks memory tier; OData pager streams "
          "via $top/$skiptoken in bounded pages. (ECS run_task / live OData are infra-gated.)")
