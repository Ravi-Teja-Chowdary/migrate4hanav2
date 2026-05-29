"""
data_spine_orchestrator.py — Migrate4HANA "Syniti layer"
==========================================================
High-volume, **zero-runtime-AI** data cleansing / transformation / ledger engine.

This is the data spine that the master orchestrator drives between the Natuvion
carve-out (extraction) and the SmartShift code-fix (remediation) phases. It owns
the extracted SAP entity trees *locally* — no payload ever leaves the process for
an LLM — which keeps enterprise data private and the throughput network-free.

Three guarantees, each fully deterministic:

1. **Multi-table relationship mapping** — SAP objects are entity *trees*, not flat
   rows. For Business Partner we hold absolute foreign-key integrity between
   ``BUT000`` (general / root), ``BUT020`` (addresses) and ``BUT100`` (roles):
   every child row must resolve to a parent ``PARTNER``; orphans are quarantined,
   never silently loaded. The tree model is generic (see ``ENTITY_TREES``) so new
   objects (e.g. material MARA→MARC→MARD) plug in by declaring their edges.

2. **Deterministic self-healing** — when an extracted record carries an orphaned
   *organisational* attribute (a profit center / company code / cost center that
   does not exist in the target hierarchy), a local lookup against target
   configuration reference tables heals the defect: a valid substitute is chosen
   by a declared strategy and the change is recorded for audit. No guessing, no AI.

3. **Cryptographic idempotency ledger** — an append-only ledger SHA-256-hashes
   every processed record and logs it. On restart after a network / infrastructure
   timeout the engine reloads the ledger and *resumes instantly* — already-applied
   records are skipped (counted into ``reused_from_ledger``) so re-runs never write
   duplicates. The ledger is the resume + audit substrate.

Standard-library only (hashlib / json / dataclasses) so it runs unchanged on a
laptop or inside a Fargate task with no extra wheels.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional


# ════════════════════════════════════════════════════════════════════════════
#  Entity-tree model — declares the foreign-key edges that make an SAP object a
#  tree. Add an entry to extend the spine to a new object.
# ════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class TreeEdge:
    """A parent→child foreign-key edge inside an entity tree."""
    child: str                 # child table, e.g. "BUT020"
    parent: str                # parent table, e.g. "BUT000"
    on: tuple                  # ((child_col, parent_col), ...) join key


@dataclass(frozen=True)
class EntityTree:
    """An SAP object modelled as a root table plus dependent child tables."""
    name: str                  # logical object, e.g. "BusinessPartner"
    root: str                  # root table whose key anchors the tree
    key: tuple                 # primary-key columns of the root (e.g. ("PARTNER",))
    edges: tuple               # tuple[TreeEdge]


ENTITY_TREES: dict[str, EntityTree] = {
    "BusinessPartner": EntityTree(
        name="BusinessPartner",
        root="BUT000",
        key=("PARTNER",),
        edges=(
            TreeEdge("BUT020", "BUT000", (("PARTNER", "PARTNER"),)),   # addresses
            TreeEdge("BUT100", "BUT000", (("PARTNER", "PARTNER"),)),   # roles
        ),
    ),
    # Example of a second tree — material master and its plant/storage children.
    "Material": EntityTree(
        name="Material",
        root="MARA",
        key=("MATNR",),
        edges=(
            TreeEdge("MARC", "MARA", (("MATNR", "MATNR"),)),           # plant data
            TreeEdge("MARD", "MARC", (("MATNR", "MATNR"), ("WERKS", "WERKS"))),
        ),
    ),
}


# ════════════════════════════════════════════════════════════════════════════
#  Target configuration reference tables — the deterministic knowledge used to
#  validate and heal organisational attributes. In production these are populated
#  from the live target via config_discovery; here they are injected so the engine
#  stays pure and testable.
# ════════════════════════════════════════════════════════════════════════════
@dataclass
class ReferenceData:
    """Allow-lists of valid target organisational values, keyed by domain.

    A *domain* is a logical organisational dimension (e.g. ``PRCTR`` profit
    center, ``BUKRS`` company code). ``defaults`` supplies the substitute value a
    healer falls back to when a record's value is not in the target.
    """
    valid: dict[str, set] = field(default_factory=dict)       # domain -> {values}
    defaults: dict[str, str] = field(default_factory=dict)    # domain -> fallback
    remap: dict[str, dict[str, str]] = field(default_factory=dict)  # domain -> {src:tgt}

    def is_valid(self, domain: str, value: Any) -> bool:
        allowed = self.valid.get(domain)
        # No allow-list configured for the domain ⇒ treat as unconstrained.
        if allowed is None:
            return True
        return _norm(value) in allowed

    def resolve(self, domain: str, value: Any) -> Optional[str]:
        """Return a valid target value for ``value`` in ``domain`` or None.

        Resolution order: explicit source→target remap, then domain default.
        """
        v = _norm(value)
        mapped = self.remap.get(domain, {}).get(v)
        if mapped is not None and self.is_valid(domain, mapped):
            return mapped
        default = self.defaults.get(domain)
        if default is not None and self.is_valid(domain, default):
            return default
        return None

    @classmethod
    def from_discovered_config(cls, cfg: dict) -> "ReferenceData":
        """Build reference data from a config_discovery discovered-config dict.

        Tolerant of partial config — only the domains present are constrained.
        """
        cfg = cfg or {}
        valid: dict[str, set] = {}
        defaults: dict[str, str] = {}
        for domain, spec in (cfg.get("reference_domains") or {}).items():
            values = spec.get("valid") if isinstance(spec, dict) else spec
            if values:
                valid[domain] = {_norm(x) for x in values}
            if isinstance(spec, dict) and spec.get("default") is not None:
                defaults[domain] = _norm(spec["default"])
        return cls(valid=valid, defaults=defaults,
                   remap={k: {_norm(a): _norm(b) for a, b in v.items()}
                          for k, v in (cfg.get("reference_remap") or {}).items()})


# ════════════════════════════════════════════════════════════════════════════
#  Healable-attribute registry — which fields, on which tables, map to which
#  organisational domain, and how aggressively to heal.
# ════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class HealRule:
    table: str
    column: str
    domain: str
    required: bool = True       # if the healed value cannot be resolved, quarantine


HEAL_RULES: tuple = (
    HealRule("BUT000", "PRCTR", "PRCTR"),
    HealRule("ACDOCA", "RPRCTR", "PRCTR"),
    HealRule("ACDOCA", "RBUKRS", "BUKRS"),
    HealRule("BSEG",   "PRCTR", "PRCTR"),
    HealRule("CSKS",   "PRCTR", "PRCTR"),
    HealRule("CSKS",   "KOKRS", "KOKRS"),
    HealRule("MARC",   "WERKS", "WERKS"),
)


# ════════════════════════════════════════════════════════════════════════════
#  Canonicalisation + hashing helpers
# ════════════════════════════════════════════════════════════════════════════
def _norm(value: Any) -> str:
    """Canonical scalar form: trimmed, upper-cased string (SAP keys are CHAR)."""
    if value is None:
        return ""
    return str(value).strip().upper()


def canonical_record(record: dict) -> str:
    """Stable, order-independent JSON for hashing. None and "" collapse equal."""
    clean = {k: ("" if v is None else v) for k, v in record.items()}
    return json.dumps(clean, sort_keys=True, separators=(",", ":"), default=str)


def record_hash(record: dict) -> str:
    return hashlib.sha256(canonical_record(record).encode("utf-8")).hexdigest()


def business_key(table: str, record: dict, key_cols: Iterable[str]) -> str:
    """Identity of a record independent of its mutable attributes."""
    parts = [table] + [_norm(record.get(c)) for c in key_cols]
    return "|".join(parts)


# ════════════════════════════════════════════════════════════════════════════
#  Cryptographic idempotency ledger (append-only, resume-safe)
# ════════════════════════════════════════════════════════════════════════════
class IdempotencyLedger:
    """Append-only SHA-256 ledger of processed records.

    Each entry: ``{ts, table, business_key, content_hash, status}``. The ledger
    is the resume substrate — on construction it replays the file into an index
    so a re-run after a timeout skips anything already applied (no duplicates).

    Thread-safe: the master orchestrator paces parallel RFC workers, but several
    may still resolve into the ledger concurrently.
    """

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # business_key -> content_hash of the last applied version
        self._index: dict[str, str] = {}
        self._reused = 0
        self._appended = 0
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    # A torn final line from a crash mid-write — tolerate it.
                    continue
                bk = entry.get("business_key")
                if bk and entry.get("status") in ("applied", "healed"):
                    self._index[bk] = entry.get("content_hash", "")

    def seen(self, bk: str, content_hash: str) -> bool:
        """True if this exact record version was already applied."""
        return self._index.get(bk) == content_hash

    def known_key(self, bk: str) -> bool:
        """True if the business key exists (any version) — i.e. an update."""
        return bk in self._index

    def append(self, table: str, bk: str, content_hash: str,
               status: str = "applied", note: str = "") -> str:
        """Record a processed record. Returns the action taken:
        ``reused`` (identical version already applied) | ``written``.
        """
        with self._lock:
            if self.seen(bk, content_hash):
                self._reused += 1
                return "reused"
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "table": table,
                "business_key": bk,
                "content_hash": content_hash,
                "status": status,
            }
            if note:
                entry["note"] = note
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, separators=(",", ":")) + "\n")
            self._index[bk] = content_hash
            self._appended += 1
            return "written"

    @property
    def reused_from_ledger(self) -> int:
        return self._reused

    @property
    def newly_written(self) -> int:
        return self._appended

    def reused_score(self, total_seen: int) -> float:
        """Fraction of processed records served from the ledger (0.0–1.0)."""
        return (self._reused / total_seen) if total_seen else 0.0


# ════════════════════════════════════════════════════════════════════════════
#  Deterministic self-healer
# ════════════════════════════════════════════════════════════════════════════
@dataclass
class Defect:
    table: str
    business_key: str
    column: str
    domain: str
    bad_value: str
    healed_value: Optional[str]
    action: str               # "healed" | "quarantined" | "ok"


class SelfHealer:
    """Heal orphaned organisational attributes against target reference data."""

    def __init__(self, reference: ReferenceData, rules: Iterable[HealRule] = HEAL_RULES):
        self.reference = reference
        # index rules by table for O(1) lookup
        self._by_table: dict[str, list[HealRule]] = {}
        for r in rules:
            self._by_table.setdefault(r.table, []).append(r)

    def heal(self, table: str, record: dict, bk: str) -> tuple[dict, list[Defect]]:
        """Return (possibly-modified record, defects). The record is copied; the
        original is never mutated. A defect with action ``quarantined`` means the
        record must NOT be loaded.
        """
        rules = self._by_table.get(table)
        if not rules:
            return record, []
        healed = dict(record)
        defects: list[Defect] = []
        for rule in rules:
            if rule.column not in healed:
                continue
            value = healed[rule.column]
            # Empty optional org attribute is fine; empty required one is a defect.
            if _norm(value) == "" and not rule.required:
                continue
            if self.reference.is_valid(rule.domain, value):
                continue
            substitute = self.reference.resolve(rule.domain, value)
            if substitute is not None:
                healed[rule.column] = substitute
                defects.append(Defect(table, bk, rule.column, rule.domain,
                                      _norm(value), substitute, "healed"))
            elif rule.required:
                defects.append(Defect(table, bk, rule.column, rule.domain,
                                      _norm(value), None, "quarantined"))
        return healed, defects


# ════════════════════════════════════════════════════════════════════════════
#  Foreign-key integrity over an entity tree
# ════════════════════════════════════════════════════════════════════════════
class EntityTreeValidator:
    """Enforce parent→child FK integrity for an entity tree."""

    def __init__(self, tree: EntityTree):
        self.tree = tree

    def validate(self, tables: dict[str, list[dict]]) -> dict:
        """``tables`` maps table-name → list[record]. Returns a report and, in
        ``kept``, the child rows whose parents resolve. Orphans are returned in
        ``orphans`` and excluded from ``kept``.
        """
        # Build the set of present parent keys per parent table.
        parent_index: dict[str, set] = {}
        root = self.tree.root
        parent_index[root] = {
            self._key_tuple(r, self.tree.key) for r in tables.get(root, [])
        }
        kept: dict[str, list[dict]] = {root: list(tables.get(root, []))}
        orphans: dict[str, list[dict]] = {}
        edge_reports: list[dict] = []

        for edge in self.tree.edges:
            child_rows = tables.get(edge.child, [])
            child_cols = [c for c, _ in edge.on]
            parent_cols = [p for _, p in edge.on]
            # Parent keys for this edge come from the parent table's rows.
            pkeys = {
                self._key_tuple(r, parent_cols) for r in tables.get(edge.parent, [])
            }
            kept_rows, orphan_rows = [], []
            for row in child_rows:
                if self._key_tuple(row, child_cols) in pkeys:
                    kept_rows.append(row)
                else:
                    orphan_rows.append(row)
            kept[edge.child] = kept_rows
            if orphan_rows:
                orphans[edge.child] = orphan_rows
            edge_reports.append({
                "child": edge.child, "parent": edge.parent,
                "total": len(child_rows), "kept": len(kept_rows),
                "orphans": len(orphan_rows),
            })

        return {
            "tree": self.tree.name,
            "root_rows": len(parent_index[root]),
            "edges": edge_reports,
            "kept": kept,
            "orphans": orphans,
            "integrity": "INTACT" if not orphans else "ORPHANS_QUARANTINED",
        }

    @staticmethod
    def _key_tuple(record: dict, cols: Iterable[str]) -> tuple:
        return tuple(_norm(record.get(c)) for c in cols)


# ════════════════════════════════════════════════════════════════════════════
#  The orchestrator
# ════════════════════════════════════════════════════════════════════════════
class DataSpineOrchestrator:
    """Cleanse + transform + ledger an extracted SAP entity tree, deterministically.

    Typical use (driven by pipeline_spine_master):

        spine = DataSpineOrchestrator(run_dir, reference=ReferenceData(...))
        result = spine.process_tree("BusinessPartner", {
            "BUT000": [...], "BUT020": [...], "BUT100": [...],
        })
    """

    def __init__(self, run_dir: str | os.PathLike,
                 reference: Optional[ReferenceData] = None,
                 heal_rules: Iterable[HealRule] = HEAL_RULES,
                 trees: Optional[dict[str, EntityTree]] = None):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.reference = reference or ReferenceData()
        self.healer = SelfHealer(self.reference, heal_rules)
        self.trees = trees or ENTITY_TREES
        self.ledger = IdempotencyLedger(self.run_dir / "idempotency_ledger.jsonl")

    def process_tree(self, object_name: str,
                     tables: dict[str, list[dict]]) -> dict:
        """Run the full spine over one entity tree. Never raises on data defects —
        defects are classified into the report. Raises only on a misconfigured
        request (unknown object).
        """
        tree = self.trees.get(object_name)
        if tree is None:
            raise ValueError(f"unknown entity tree {object_name!r}; "
                             f"known: {sorted(self.trees)}")

        # 1) Foreign-key integrity — quarantine orphans before anything else.
        fk = EntityTreeValidator(tree).validate(tables)
        kept = fk["kept"]

        # 2) Self-heal + 3) idempotency ledger, per table, root first.
        ordered = [tree.root] + [e.child for e in tree.edges]
        key_for = {tree.root: list(tree.key)}
        for e in tree.edges:
            key_for[e.child] = [c for c, _ in e.on]  # child side of the FK = its key prefix

        healed_out: dict[str, list[dict]] = {}
        defects: list[Defect] = []
        counters = {"seen": 0, "applied": 0, "healed": 0,
                    "reused": 0, "quarantined": 0}

        for table in ordered:
            rows = kept.get(table, [])
            out_rows: list[dict] = []
            for row in rows:
                counters["seen"] += 1
                bk = business_key(table, row, key_for.get(table, list(row.keys())))

                healed_row, row_defects = self.healer.heal(table, row, bk)
                quarantined = any(d.action == "quarantined" for d in row_defects)
                defects.extend(row_defects)
                if quarantined:
                    counters["quarantined"] += 1
                    self.ledger.append(table, bk, record_hash(healed_row),
                                       status="quarantined",
                                       note="unhealable org attribute")
                    continue

                was_healed = any(d.action == "healed" for d in row_defects)
                if was_healed:
                    counters["healed"] += 1

                chash = record_hash(healed_row)
                action = self.ledger.append(
                    table, bk, chash,
                    status="healed" if was_healed else "applied")
                if action == "reused":
                    counters["reused"] += 1
                else:
                    counters["applied"] += 1
                out_rows.append(healed_row)
            healed_out[table] = out_rows

        report = {
            "object": object_name,
            "fk_integrity": {
                "status": fk["integrity"],
                "root_rows": fk["root_rows"],
                "edges": fk["edges"],
                "orphans": {t: len(rows) for t, rows in fk["orphans"].items()},
            },
            "counters": counters,
            "reused_from_ledger": self.ledger.reused_from_ledger,
            "reused_score": round(self.ledger.reused_score(counters["seen"]), 4),
            "defects": [asdict(d) for d in defects],
            "cleansed": healed_out,
        }
        self._write_report(object_name, report)
        return report

    def _write_report(self, object_name: str, report: dict) -> None:
        # Persist the report WITHOUT the bulk cleansed payload (kept separate).
        summary = {k: v for k, v in report.items() if k != "cleansed"}
        (self.run_dir / f"spine_{object_name}.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8")
        (self.run_dir / f"cleansed_{object_name}.json").write_text(
            json.dumps(report["cleansed"], indent=2, default=str), encoding="utf-8")


# ════════════════════════════════════════════════════════════════════════════
#  Self-test (no SAP, no network) — proves FK integrity, self-heal, idempotency.
# ════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import tempfile

    print("=" * 78)
    print("data_spine_orchestrator — self-test")
    print("=" * 78)

    # Target reference: only profit centers YB600 / YB700 exist; default YB600.
    reference = ReferenceData(
        valid={"PRCTR": {"YB600", "YB700"}, "BUKRS": {"1710"}},
        defaults={"PRCTR": "YB600", "BUKRS": "1710"},
        remap={"PRCTR": {"3000": "YB700"}},     # legacy 3000 maps to YB700
    )

    but000 = [
        {"PARTNER": "BP01", "NAME_ORG1": "Acme GmbH",  "PRCTR": "YB600"},  # ok
        {"PARTNER": "BP02", "NAME_ORG1": "Globex SA",  "PRCTR": "3000"},   # remap→YB700
        {"PARTNER": "BP03", "NAME_ORG1": "Initech",    "PRCTR": "9999"},   # heal→default YB600
        {"PARTNER": "BP04", "NAME_ORG1": "Umbrella",   "PRCTR": ""},       # required→default
    ]
    but020 = [
        {"PARTNER": "BP01", "ADDRNUMBER": "0001", "CITY1": "Berlin"},
        {"PARTNER": "BP02", "ADDRNUMBER": "0002", "CITY1": "Paris"},
        {"PARTNER": "BP99", "ADDRNUMBER": "0099", "CITY1": "Nowhere"},     # ORPHAN
    ]
    but100 = [
        {"PARTNER": "BP01", "RLTYP": "FLCU01"},
        {"PARTNER": "BP03", "RLTYP": "FLVN01"},
    ]

    tmp = Path(tempfile.mkdtemp(prefix="m4h_spine_"))
    spine = DataSpineOrchestrator(tmp, reference=reference)

    print("\n[Run A] first pass")
    rep = spine.process_tree("BusinessPartner",
                             {"BUT000": but000, "BUT020": but020, "BUT100": but100})
    print(f"  FK integrity     : {rep['fk_integrity']['status']} "
          f"(orphans={rep['fk_integrity']['orphans']})")
    print(f"  counters         : {rep['counters']}")
    print(f"  reused_from_ledger: {rep['reused_from_ledger']}  "
          f"score={rep['reused_score']}")
    print("  defects:")
    for d in rep["defects"]:
        print(f"    - {d['table']}.{d['column']} {d['bad_value']!r} "
              f"-> {d['healed_value']!r} [{d['action']}]")

    assert rep["fk_integrity"]["orphans"].get("BUT020") == 1, "orphan not caught"
    assert rep["counters"]["healed"] == 3, "expected 3 healed PRCTRs"
    assert rep["counters"]["reused"] == 0, "first pass should reuse nothing"

    print("\n[Run B] resume (same engine, same ledger) — must be fully idempotent")
    spine2 = DataSpineOrchestrator(tmp, reference=reference)   # reload ledger
    rep2 = spine2.process_tree("BusinessPartner",
                               {"BUT000": but000, "BUT020": but020, "BUT100": but100})
    print(f"  counters         : {rep2['counters']}")
    print(f"  reused_from_ledger: {rep2['reused_from_ledger']}  "
          f"score={rep2['reused_score']}")
    assert rep2["counters"]["reused"] == rep2["counters"]["seen"] - rep2["counters"]["quarantined"], \
        "resume run should reuse every applicable record"
    assert rep2["counters"]["applied"] == 0, "resume must write zero new records"

    print("\nOK — FK orphan quarantined, 3 PRCTRs self-healed, re-run 100% reused.")
    print(f"artifacts in {tmp}")
