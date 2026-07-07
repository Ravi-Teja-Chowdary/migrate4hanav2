"""
dependency_dag.py - object dependency graph + ordered execution + key resolution.

Background
----------
A faithful SAP migration is not just "load every object." It is a DAG:
masters before transactionals, GL accounts before AR/AP postings, materials
+ customers before sales orders, cost centers + profit centers before fixed
asset depreciation areas. Skipping the DAG is what makes naive migrations
produce silent dependent-record failures that surface in reconciliation as
"orphan" rows whose root cause is "we never loaded the master."

This module models the dependency graph declaratively, computes a safe
topological execution order, and provides the cross-object key-lookup
helper that downstream loaders use to translate "the source SO's sold-to
KUNNR" into "the S/4 BP ID that the BP migration produced for that KUNNR
yesterday."

Two collaborators:

  - DependencyDAG    : declares edges; topological_sort(); validate (cycle
                       detection); subset for a partial migration scope.
  - KeyResolver      : reads from the cross-run keymap (the same store used
                       by data-migrator) so downstream loaders look up
                       "give me the S/4 BP for source KUNNR=100001" without
                       needing to know about the BP migration internals.
  - ExecutionState   : tracks per-object status (pending / running / done /
                       failed); next_ready() returns objects whose deps are
                       all done; integrates with the HashChainLedger so each
                       state transition is auditable.

Out of scope: actually invoking the loaders. The caller pulls ready objects
off next_ready() and dispatches to its own pipeline.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

logger = logging.getLogger("dependency_dag")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


# ─────────────────────────────────────────────────────────────────────────────
#  The graph
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class DependencyDAG:
    """Declarative object-type dependency graph.

    Use `from_defaults()` for the curated default for greenfield SAP migrations
    or pass `edges` explicitly to override. Each edge is `dependent -> required`
    so SalesOrder depends on (Customer, Material). Cycles raise at validate().
    """
    edges: Dict[str, Set[str]] = field(default_factory=dict)  # dependent -> {required, ...}
    nodes: Set[str] = field(default_factory=set)

    @classmethod
    def from_defaults(cls) -> "DependencyDAG":
        # Curated SAP migration order. Conservative - if in doubt, the dep is
        # declared so the later object waits. Override by mutating in caller.
        # Expanded 2026-07-03 to cover the full transactional envelope needed
        # for a production-grade cutover (was 28 nodes; now covers the
        # ~60 objects that actually gate on order-of-operations).
        edges = {
            # ── Foundation masters ─────────────────────────────────────────
            "Plant":              set(),
            "GLAccount":          set(),
            "Bank":               set(),
            "ExchangeRates":      set(),
            "Characteristic":     set(),
            "FunctionalLocation": set(),

            # ── Core master data ───────────────────────────────────────────
            "BusinessPartner":    set(),
            "Customer":           {"BusinessPartner"},
            "Vendor":             {"BusinessPartner"},
            "Material":           set(),
            "MaterialClassification": {"Material", "Class"},

            # ── CO objects ─────────────────────────────────────────────────
            "CostCenter":         {"GLAccount"},
            "ProfitCenter":       {"GLAccount"},
            "CostElementGroup":   {"GLAccount"},
            "ProfitCenterGroup":  {"ProfitCenter"},
            "InternalOrder":      {"CostCenter"},

            # ── FI (extended) ──────────────────────────────────────────────
            "FixedAsset":         {"CostCenter", "GLAccount"},

            # ── PS / project ───────────────────────────────────────────────
            "ProjectDefinition":  set(),
            "WBS":                {"ProjectDefinition", "CostCenter"},
            "Project":            {"WBS"},
            "NetworkActivity":    {"WBS"},
            "NetworkComponent":   {"NetworkActivity", "Material"},

            # ── Classification / batches ──────────────────────────────────
            "Class":              {"Characteristic"},
            "Batch":              {"Material"},
            "BatchClassification": {"Batch", "Class"},

            # ── Inventory ──────────────────────────────────────────────────
            "InventoryBalance":   {"Material", "Plant"},
            "InventoryReservation": {"Material", "Plant"},
            "MovementType":       {"Material"},
            "ProjectStock":       {"Material", "Plant", "WBS"},
            "SerialNumber":       {"Material"},
            "HandlingUnit":       {"Material", "Plant"},

            # ── PM / EAM ───────────────────────────────────────────────────
            "Equipment":          {"Material", "FunctionalLocation"},
            "MeasurementPoint":   {"Equipment"},
            "MeasurementDocument": {"MeasurementPoint"},
            "MaintenancePlan":    {"Equipment"},
            "MaintenanceItem":    {"MaintenancePlan"},
            "Notification":       {"Equipment"},
            "Warranty":           {"Equipment"},

            # ── MM: PR / PO / IR ───────────────────────────────────────────
            "InfoRecord":         {"Material", "Vendor"},
            "SourceListLegacy":   {"Material", "Vendor"},
            "PurchaseRequisition": {"Material"},
            "PurchaseContract":   {"Material", "Vendor"},
            "OpenPO":             {"Material", "Vendor"},
            "ScheduleAgreementMM": {"Material", "Vendor"},
            "SubcontractingPO":   {"OpenPO"},
            "StockTransferOrder": {"Material", "Plant"},
            "GoodsReceipt":       {"OpenPO"},
            "IncomingInvoice":    {"OpenPO", "GoodsReceipt"},
            "ServiceEntrySheet":  {"OpenPO"},

            # ── SD ─────────────────────────────────────────────────────────
            "Inquiry":            {"Material", "Customer"},
            "Quotation":          {"Inquiry", "Material", "Customer"},
            "SalesContract":      {"Material", "Customer"},
            "ScheduleAgreementSD": {"Material", "Customer"},
            "SalesOrder":         {"Material", "Customer"},
            "OutboundDelivery":   {"SalesOrder", "Plant"},
            "Shipment":           {"OutboundDelivery"},
            "CreditMemoRequest":  {"SalesOrder"},
            "ReturnsOrderSD":     {"SalesOrder"},
            "RebateAgreement":    {"Customer"},

            # ── PP / manufacturing ─────────────────────────────────────────
            "BOMItem":            {"Material"},
            "ProductionVersion":  {"Material"},
            "MasterRecipe":       {"Material"},
            "PlannedOrder":       {"Material", "Plant"},
            "ProductionOrder":    {"Material", "Plant"},
            "ProcessOrder":       {"MasterRecipe", "Material", "Plant"},
            "ProductionOrderConfirmation": {"ProductionOrder"},
            "ProductionOrderTimeTicket":   {"ProductionOrder"},

            # ── QM ─────────────────────────────────────────────────────────
            "CatalogCode":        set(),
            "InspectionCharacteristic": {"Material"},
            "SamplingProcedure":  set(),
            "ControlPlan":        {"Material", "InspectionCharacteristic"},

            # ── Documents ──────────────────────────────────────────────────
            "DocumentInfoRecord": set(),

            # ── HR (rare-lane) ─────────────────────────────────────────────
            "HRMaster":           set(),

            # ── FI open items / postings ───────────────────────────────────
            "OpenAR":             {"GLAccount", "Customer"},
            "OpenAP":             {"GLAccount", "Vendor"},
            "AccountingDocument": {"GLAccount"},

            # ── Legacy / requirements ──────────────────────────────────────
            "Requirement":        {"Material", "Plant"},
            "RequisitionLegacy":  {"Material"},

            # ── 2026-07-07 breadth wire-up: remaining registered spines ────
            # Objects whose spine files exist but weren't in the DAG yet.
            # Dependencies chosen conservatively: masters before transactionals,
            # and any FK the BAPI resolves through the key map is declared.
            # These are wired even when Tier-2 (extract-and-stage) so the
            # topological order still respects them for MC-lane deployments.
            "BillingDocument":    {"SalesOrder"},          # VBRK/VBRP, refs SO or delivery
            "WorkCenter":         {"Plant"},               # CRHD, plant-scoped
            "Network":            {"Project"},             # AUFK/AUTYP=20, PS network
            "WBSElement":         {"WBS", "CostCenter"},   # PRPS row-level element
            "ProductionBOM":      {"Material", "Plant"},   # STKO
            "WarrantyClaim":      {"Equipment"},           # BAPI_WARRANTY_CREATE
            "FixedAssetOvertake": {"FixedAsset"},          # asset takeover variant
            "ServiceMaster":      set(),                   # ASMD, standalone
            "SourceList":         {"Material", "Vendor"},  # EORD, MM lane
            "PurchaseOrder":      {"Material", "Vendor"},  # EKKO general (vs OpenPO's BSTYP='F' filter)
        }
        nodes = set(edges) | {n for deps in edges.values() for n in deps}
        return cls(edges=edges, nodes=nodes)

    def add_edge(self, dependent: str, requires: str) -> None:
        self.edges.setdefault(dependent, set()).add(requires)
        self.nodes.add(dependent); self.nodes.add(requires)

    def deps_of(self, node: str) -> Set[str]:
        return set(self.edges.get(node, ()))

    def dependents_of(self, node: str) -> Set[str]:
        return {n for n, deps in self.edges.items() if node in deps}

    # ── validation ──────────────────────────────────────────────────────────
    def validate(self) -> List[str]:
        """Return a list of cycle paths (empty list = no cycles)."""
        cycles: List[str] = []
        WHITE, GRAY, BLACK = 0, 1, 2
        colors = {n: WHITE for n in self.nodes}
        stack: List[str] = []

        def dfs(n: str) -> None:
            colors[n] = GRAY
            stack.append(n)
            for dep in self.edges.get(n, ()):
                if dep not in self.nodes:
                    continue
                if colors[dep] == GRAY:
                    i = stack.index(dep)
                    cycles.append(" -> ".join(stack[i:] + [dep]))
                elif colors[dep] == WHITE:
                    dfs(dep)
            stack.pop()
            colors[n] = BLACK

        for n in sorted(self.nodes):
            if colors[n] == WHITE:
                dfs(n)
        return cycles

    # ── topological sort ────────────────────────────────────────────────────
    def topological_sort(self, scope: Optional[Iterable[str]] = None) -> List[str]:
        """Kahn's algorithm. If scope is given, only those nodes are returned
        (with their transitively-required deps still respected)."""
        cycles = self.validate()
        if cycles:
            raise ValueError(f"DAG has cycles: {cycles}")

        scope_set = set(scope) if scope is not None else set(self.nodes)
        # Include any deps that scope nodes transitively need
        frontier = list(scope_set)
        while frontier:
            n = frontier.pop()
            for d in self.edges.get(n, ()):
                if d not in scope_set:
                    scope_set.add(d); frontier.append(d)

        in_degree = {n: 0 for n in scope_set}
        for n in scope_set:
            for d in self.edges.get(n, ()):
                if d in scope_set:
                    in_degree[n] += 1

        ready = sorted([n for n, d in in_degree.items() if d == 0])
        order: List[str] = []
        while ready:
            n = ready.pop(0)
            order.append(n)
            for dependent in sorted(self.dependents_of(n)):
                if dependent not in scope_set:
                    continue
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    ready.append(dependent)
                    ready.sort()
        if len(order) != len(scope_set):
            missing = scope_set - set(order)
            raise ValueError(f"topological sort incomplete - missing {missing}")
        return order


# ─────────────────────────────────────────────────────────────────────────────
#  Cross-object key lookup (the actual "faithful migration" enabler)
# ─────────────────────────────────────────────────────────────────────────────
class KeyResolver:
    """Tiny wrapper over the cross-run keymap.

    The contract:
      - When a master loader writes a record, it calls
            resolver.record("Customer", legacy_key="100001", target_key="BP00ABCDEF")
        so downstream transactional loaders can call
            resolver.lookup("Customer", legacy_key="100001")  -> "BP00ABCDEF"

    Backed by a dict in this module (for tests + local runs); pass a callable
    pair (lookup_fn, record_fn) to delegate to DynamoDB (the production
    cross-run ledger)."""

    def __init__(self,
                 lookup_fn: Optional[Callable[[str, str], Optional[str]]] = None,
                 record_fn: Optional[Callable[[str, str, str], None]] = None):
        self._store: Dict[Tuple[str, str], str] = {}
        self._lookup_fn = lookup_fn
        self._record_fn = record_fn
        self._lock = threading.Lock()

    def record(self, object_type: str, legacy_key: str, target_key: str) -> None:
        with self._lock:
            self._store[(object_type, str(legacy_key))] = str(target_key)
        if self._record_fn:
            try:
                self._record_fn(object_type, str(legacy_key), str(target_key))
            except Exception as e:  # noqa: BLE001
                logger.warning("KeyResolver.record delegate failed: %s", e)

    def lookup(self, object_type: str, legacy_key: str) -> Optional[str]:
        with self._lock:
            hit = self._store.get((object_type, str(legacy_key)))
        if hit is not None:
            return hit
        if self._lookup_fn:
            try:
                return self._lookup_fn(object_type, str(legacy_key))
            except Exception as e:  # noqa: BLE001
                logger.warning("KeyResolver.lookup delegate failed: %s", e)
        return None

    def resolve_record(self, record: dict, mappings: List[dict]) -> Tuple[dict, List[str]]:
        """Apply a list of {field, lookup_object} translations to a record.
        Returns (resolved_copy, missing_lookups) - missing means the master
        for that legacy key is not yet loaded; the caller should defer or
        quarantine the record."""
        out = dict(record)
        missing: List[str] = []
        for m in mappings:
            fld = m["field"]
            obj = m["lookup_object"]
            legacy = record.get(fld)
            if legacy is None or legacy == "":
                continue
            target = self.lookup(obj, str(legacy))
            if target is None:
                missing.append(f"{obj}:{legacy}")
                continue
            out[fld] = target
        return out, missing


# ─────────────────────────────────────────────────────────────────────────────
#  Execution state machine
# ─────────────────────────────────────────────────────────────────────────────
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


@dataclass
class ExecutionState:
    dag: DependencyDAG
    status: Dict[str, str] = field(default_factory=dict)
    _audit_callback: Optional[Callable[[str, str, str], None]] = None  # (obj, new_status, ts)

    def __post_init__(self):
        for n in self.dag.nodes:
            self.status.setdefault(n, STATUS_PENDING)

    def with_audit(self, cb: Callable[[str, str, str], None]) -> "ExecutionState":
        self._audit_callback = cb
        return self

    def next_ready(self, only: Optional[Iterable[str]] = None) -> List[str]:
        """Return all objects whose deps are all done and which are still pending."""
        ready: List[str] = []
        candidates = set(only) if only is not None else set(self.dag.nodes)
        for n in sorted(candidates):
            if self.status.get(n) != STATUS_PENDING:
                continue
            deps = self.dag.deps_of(n)
            if all(self.status.get(d) == STATUS_DONE for d in deps):
                ready.append(n)
        return ready

    def mark(self, obj: str, new_status: str) -> None:
        if new_status not in (STATUS_PENDING, STATUS_RUNNING, STATUS_DONE, STATUS_FAILED):
            raise ValueError(f"bad status: {new_status}")
        old = self.status.get(obj)
        self.status[obj] = new_status
        ts = datetime.now(timezone.utc).isoformat()
        if self._audit_callback:
            try:
                self._audit_callback(obj, new_status, ts)
            except Exception as e:  # noqa: BLE001
                logger.warning("audit callback failed: %s", e)
        logger.info("DAG state: %s %s -> %s", obj, old, new_status)

    def complete(self) -> bool:
        return all(s in (STATUS_DONE, STATUS_FAILED) for s in self.status.values())

    def downstream_blocked_by_failure(self) -> Dict[str, List[str]]:
        """For each FAILED node, list the downstream pending nodes that can
        never run because of it."""
        blocked: Dict[str, List[str]] = {}
        for failed in [n for n, s in self.status.items() if s == STATUS_FAILED]:
            # BFS downstream
            queue = [failed]
            seen: Set[str] = set()
            while queue:
                n = queue.pop(0)
                for dep_of_n in self.dag.dependents_of(n):
                    if dep_of_n in seen:
                        continue
                    seen.add(dep_of_n)
                    if self.status.get(dep_of_n) == STATUS_PENDING:
                        blocked.setdefault(failed, []).append(dep_of_n)
                    queue.append(dep_of_n)
        return blocked


# ─────────────────────────────────────────────────────────────────────────────
#  Self-test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 78)
    print("dependency_dag - self-test")
    print("=" * 78)

    dag = DependencyDAG.from_defaults()
    cycles = dag.validate()
    assert not cycles, f"unexpected cycles: {cycles}"
    print(f"  default DAG has {len(dag.nodes)} nodes, 0 cycles OK")

    # Sort
    order = dag.topological_sort()
    # SalesOrder must come AFTER both Material and Customer (which comes after BP)
    assert order.index("BusinessPartner") < order.index("Customer")
    assert order.index("Customer") < order.index("SalesOrder")
    assert order.index("Material") < order.index("SalesOrder")
    assert order.index("GLAccount") < order.index("CostCenter")
    assert order.index("CostCenter") < order.index("FixedAsset")
    print(f"  topological order respects masters-before-transactionals OK")

    # Cycle detection
    bad = DependencyDAG()
    bad.add_edge("A", "B")
    bad.add_edge("B", "C")
    bad.add_edge("C", "A")
    assert bad.validate(), "should detect cycle"
    try:
        bad.topological_sort()
        assert False, "should have raised"
    except ValueError as e:
        assert "cycle" in str(e).lower()
        print(f"  cycle detection: A->B->C->A correctly rejected OK")

    # Scope subset
    order2 = dag.topological_sort(scope=["SalesOrder"])
    assert "BusinessPartner" in order2  # transitively required
    assert "OpenAR" not in order2       # not in scope, not required by SalesOrder
    assert order2[-1] == "SalesOrder"
    print(f"  scope subset: SalesOrder pulled in transitive deps "
          f"({len(order2)} nodes), excluded OpenAR OK")

    # Execution state machine
    audit_log: List[Tuple[str, str, str]] = []
    state = ExecutionState(dag=dag).with_audit(
        lambda obj, s, ts: audit_log.append((obj, s, ts)))
    ready = state.next_ready()
    # First ready set = leaves (no deps): Material, GLAccount, etc.
    assert "Material" in ready and "GLAccount" in ready
    assert "Customer" not in ready  # depends on BusinessPartner
    print(f"  initial next_ready: {len(ready)} no-dep masters available OK")

    # Walk a real path
    for obj in ["Material", "GLAccount", "BusinessPartner", "Customer", "Vendor"]:
        state.mark(obj, STATUS_RUNNING)
        state.mark(obj, STATUS_DONE)
    ready = state.next_ready()
    assert "OpenAR" in ready  # GLAccount + Customer both done
    assert "OpenAP" in ready  # GLAccount + Vendor both done
    print(f"  after loading masters: OpenAR + OpenAP are ready OK")

    # Failure propagation
    state.mark("Plant", STATUS_FAILED)
    blocked = state.downstream_blocked_by_failure()
    assert "Plant" in blocked
    assert "InventoryBalance" in blocked["Plant"]
    print(f"  failure propagation: Plant FAIL blocks {blocked['Plant']} OK")

    # Key resolver
    resolver = KeyResolver()
    resolver.record("Customer", "100001", "BP00ABCDEF")
    resolver.record("Material", "MAT-X", "S4MAT-001")
    record = {"VBELN": "5000001", "KUNNR": "100001", "MATNR": "MAT-X", "MENGE": 5}
    resolved, missing = resolver.resolve_record(record, [
        {"field": "KUNNR", "lookup_object": "Customer"},
        {"field": "MATNR", "lookup_object": "Material"},
    ])
    assert resolved["KUNNR"] == "BP00ABCDEF"
    assert resolved["MATNR"] == "S4MAT-001"
    assert not missing
    # Missing lookup
    record_bad = {"VBELN": "5000002", "KUNNR": "999999", "MATNR": "MAT-X"}
    _, missing = resolver.resolve_record(record_bad, [
        {"field": "KUNNR", "lookup_object": "Customer"},
        {"field": "MATNR", "lookup_object": "Material"},
    ])
    assert missing == ["Customer:999999"], missing
    print(f"  KeyResolver: hits resolved, misses surfaced as {missing} OK")

    print("\nOK - DAG resolver: validates, sorts, gates execution, propagates failures, "
          "translates legacy -> target keys.")
