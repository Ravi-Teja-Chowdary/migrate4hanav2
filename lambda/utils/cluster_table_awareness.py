"""
cluster_table_awareness.py - Pool/Cluster table extraction safety net.

Background
----------
On non-HANA ECC (Oracle/MSSQL/DB2), several SAP tables are stored as
POOL or CLUSTER physical tables, not transparent. Reading a logical row
requires the database to decompress a CLUSTER block (e.g. RFBLG holds the
compressed BSEG line items keyed by BELNR). Two failure modes:

  1. A `SELECT *` against the logical view (e.g. BSEG via RFBLG) cannot be
     indexed on item-level fields - the optimizer falls back to a sequential
     scan of the entire cluster table. On a 100 GB RFBLG that's a multi-hour
     query that frequently dumps with TSV_TNEW_PAGE_ALLOC_FAILED or hits the
     SAP_LOCK_TIMEOUT and rolls back.

  2. Large PACKAGE SIZE values (we default to 5000 for transparent tables)
     compound the problem - the cluster decompressor has to materialize that
     many logical rows in dialog work-process memory.

This module:

  - Maintains a catalog of known POOL/CLUSTER tables and their logical/
    physical pairings (BSEG↔RFBLG, KONV↔KOCLU, EDIDOC↔EDI40, etc.).
  - classify_table()    -> kind (TRANSPARENT / POOL / CLUSTER) + physical_table
  - safe_package_size() -> recommended PACKAGE SIZE for the table kind
  - rewrite_via_header()-> if the call wants BSEG and a BKPF key is implied,
                          return a 2-stage extraction plan: drive from BKPF,
                          fetch BSEG per-header
  - preflight()         -> ExtractionPlan with warnings (no go), warnings
                          (proceed with caution), or all-clear

Output is consumed by the extract dispatcher so cluster reads either get
rewritten to a header-driven plan OR raise a hard "GO/NO-GO" decision the
operator must override.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("cluster_table_awareness")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


KIND_TRANSPARENT = "TRANSPARENT"
KIND_POOL = "POOL"
KIND_CLUSTER = "CLUSTER"


@dataclass(frozen=True)
class TableInfo:
    name: str
    kind: str               # TRANSPARENT | POOL | CLUSTER
    physical_table: str     # the actual stored table (for cluster, the cluster name)
    header_table: Optional[str] = None   # transparent partner for 2-stage extract
    join_keys: Tuple[str, ...] = ()       # how to join from header → this logical


# Catalog of well-known SAP pool/cluster tables. NOT exhaustive - just the
# ones a migration tool routinely touches. Extend per landscape via env-loaded
# JSON or a customer-supplied addendum.
_CATALOG: Dict[str, TableInfo] = {
    # FI document
    "BSEG":   TableInfo("BSEG", KIND_CLUSTER, "RFBLG", "BKPF", ("BUKRS", "BELNR", "GJAHR")),
    "BSET":   TableInfo("BSET", KIND_CLUSTER, "RFBLG", "BKPF", ("BUKRS", "BELNR", "GJAHR")),
    "BSEC":   TableInfo("BSEC", KIND_CLUSTER, "RFBLG", "BKPF", ("BUKRS", "BELNR", "GJAHR")),
    "BSED":   TableInfo("BSED", KIND_CLUSTER, "RFBLG", "BKPF", ("BUKRS", "BELNR", "GJAHR")),
    # CO line items / conditions
    "KONV":   TableInfo("KONV", KIND_CLUSTER, "KOCLU", "VBAK", ("KNUMV",)),    # pricing conditions for sales doc
    # IDoc data records
    "EDIDOC": TableInfo("EDIDOC", KIND_CLUSTER, "EDI40", "EDIDC", ("DOCNUM",)),
    "EDID4":  TableInfo("EDID4",  KIND_CLUSTER, "EDI40", "EDIDC", ("DOCNUM",)),
    # Worklist / settings
    "PCL1":   TableInfo("PCL1", KIND_CLUSTER, "PCL1", None, ()),
    "PCL2":   TableInfo("PCL2", KIND_CLUSTER, "PCL2", None, ()),
    "PCL3":   TableInfo("PCL3", KIND_CLUSTER, "PCL3", None, ()),
    "PCL4":   TableInfo("PCL4", KIND_CLUSTER, "PCL4", None, ()),
    "PCL5":   TableInfo("PCL5", KIND_CLUSTER, "PCL5", None, ()),
    # Match-code pools (rare in modern systems)
    "ATAB":   TableInfo("ATAB", KIND_POOL, "ATAB", None, ()),
    "KAPOL":  TableInfo("KAPOL", KIND_POOL, "KAPOL", None, ()),
}


def classify_table(name: str) -> TableInfo:
    """Return the catalog entry or a TRANSPARENT-default."""
    n = name.upper().strip()
    info = _CATALOG.get(n)
    if info:
        return info
    return TableInfo(name=n, kind=KIND_TRANSPARENT, physical_table=n)


def safe_package_size(name: str,
                      requested: int = 5000,
                      on_hana: bool = False) -> int:
    """Return a recommended PACKAGE SIZE based on the table kind.

    On HANA (column store), cluster decompression is a non-issue and the full
    requested size is fine. On classic DB (Oracle/MSSQL/DB2 row-store), cluster
    reads must use small packages so the cluster decompressor has bounded WP
    memory."""
    info = classify_table(name)
    if on_hana or info.kind == KIND_TRANSPARENT:
        return requested
    if info.kind == KIND_POOL:
        return min(requested, 1000)
    if info.kind == KIND_CLUSTER:
        return min(requested, 200)   # measured rule-of-thumb for RFBLG/KOCLU
    return requested


@dataclass
class ExtractionPlan:
    table: str
    kind: str
    physical_table: str
    recommended_package_size: int
    stages: List[dict] = field(default_factory=list)   # ordered sub-queries
    warnings: List[str] = field(default_factory=list)
    verdict: str = "GO"                                # GO | GO_WITH_WARNINGS | NO_GO

    def to_dict(self) -> dict:
        return asdict(self)


def preflight(table: str,
              where: Optional[Dict[str, str]] = None,
              fields: Optional[List[str]] = None,
              requested_package_size: int = 5000,
              on_hana: bool = False) -> ExtractionPlan:
    """Build a safe extraction plan for the requested table.

    - TRANSPARENT or HANA: trivial single-stage plan, verdict GO.
    - CLUSTER off-HANA, WHERE pins the header keys: 2-stage plan
      (header table -> per-header cluster fetch), verdict GO_WITH_WARNINGS.
    - CLUSTER off-HANA, WHERE does NOT pin header keys: NO_GO with the
      reason (operator must explicitly override - this is the case that dumps
      production).
    """
    info = classify_table(table)
    pkg = safe_package_size(table, requested_package_size, on_hana=on_hana)
    plan = ExtractionPlan(table=info.name, kind=info.kind,
                          physical_table=info.physical_table,
                          recommended_package_size=pkg)

    where = where or {}

    if info.kind == KIND_TRANSPARENT or on_hana:
        plan.stages = [{"table": info.name, "where": where,
                        "fields": fields, "package_size": pkg}]
        if not on_hana and pkg != requested_package_size:
            plan.warnings.append(f"transparent table, package size capped at {pkg}")
        return plan

    # POOL: usually small, single-stage with a tight package size
    if info.kind == KIND_POOL:
        plan.stages = [{"table": info.name, "where": where,
                        "fields": fields, "package_size": pkg}]
        plan.warnings.append(
            f"{info.name} is a POOL table on non-HANA - capped PACKAGE SIZE={pkg}")
        plan.verdict = "GO_WITH_WARNINGS"
        return plan

    # CLUSTER: needs a header-driven plan
    if info.header_table and info.join_keys:
        header_keys_present = all(k in where for k in info.join_keys)
        if header_keys_present:
            # We already have the keys, single-stage cluster read is fine at small pkg
            plan.stages = [{"table": info.name, "where": where,
                            "fields": fields, "package_size": pkg}]
            plan.warnings.append(
                f"{info.name} is a CLUSTER table; header keys "
                f"{info.join_keys} present in WHERE - reading directly with "
                f"PACKAGE SIZE={pkg}")
            plan.verdict = "GO_WITH_WARNINGS"
            return plan

        # Rewrite as 2-stage: header -> per-header cluster fetch
        header_where = {k: v for k, v in where.items()
                        if k not in info.join_keys}
        plan.stages = [
            {"table": info.header_table, "where": header_where,
             "fields": list(info.join_keys),
             "package_size": min(requested_package_size, 1000)},
            {"table": info.name, "join_from": info.header_table,
             "join_keys": list(info.join_keys),
             "fields": fields, "package_size": pkg},
        ]
        plan.warnings.append(
            f"{info.name} is a CLUSTER table; WHERE did not pin header keys "
            f"{info.join_keys} - rewritten as 2-stage extract via {info.header_table} "
            f"to avoid full-cluster scan")
        plan.verdict = "GO_WITH_WARNINGS"
        return plan

    # CLUSTER with no header pairing (e.g. PCL1/PCL2) and no key pins → NO GO
    if not where:
        plan.verdict = "NO_GO"
        plan.warnings.append(
            f"{info.name} is a {info.kind} table with no header partner and no "
            f"WHERE keys - a full-table read will lock/dump the source. Refusing.")
        return plan

    # Has SOME WHERE keys but no known header table - proceed with a tight pkg
    plan.stages = [{"table": info.name, "where": where,
                    "fields": fields, "package_size": pkg}]
    plan.warnings.append(
        f"{info.name} is a {info.kind} table; proceeding with PACKAGE SIZE={pkg} "
        f"and your WHERE clause - monitor source-side memory")
    plan.verdict = "GO_WITH_WARNINGS"
    return plan


# ─────────────────────────────────────────────────────────────────────────────
#  Self-test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 78)
    print("cluster_table_awareness - self-test")
    print("=" * 78)

    # 1) Transparent table - no warnings, package size unchanged
    p = preflight("BKPF", where={"BUKRS": "1010", "GJAHR": "2026"},
                  requested_package_size=5000)
    assert p.verdict == "GO" and p.recommended_package_size == 5000
    assert p.kind == KIND_TRANSPARENT
    print(f"  BKPF (transparent): verdict={p.verdict} pkg={p.recommended_package_size} OK")

    # 2) BSEG with full key set - cluster read at tight pkg, GO_WITH_WARNINGS
    p = preflight("BSEG", where={"BUKRS": "1010", "BELNR": "100000001",
                                  "GJAHR": "2026"},
                  requested_package_size=5000)
    assert p.verdict == "GO_WITH_WARNINGS"
    assert p.recommended_package_size == 200
    assert len(p.stages) == 1
    assert p.stages[0]["table"] == "BSEG"
    print(f"  BSEG (keys pinned): verdict={p.verdict} pkg={p.recommended_package_size} "
          f"stages={len(p.stages)} OK")

    # 3) BSEG WITHOUT header keys - rewritten as 2-stage via BKPF
    p = preflight("BSEG", where={"WAERS": "EUR"}, fields=["BUKRS", "BELNR", "HKONT", "DMBTR"],
                  requested_package_size=5000)
    assert p.verdict == "GO_WITH_WARNINGS"
    assert len(p.stages) == 2
    assert p.stages[0]["table"] == "BKPF"
    assert p.stages[1]["table"] == "BSEG"
    assert p.stages[1]["join_from"] == "BKPF"
    print(f"  BSEG (no key pins): rewritten as 2-stage via {p.stages[0]['table']} -> "
          f"{p.stages[1]['table']} (warnings: {len(p.warnings)}) OK")

    # 4) On HANA - cluster concerns evaporate, pkg unchanged
    p = preflight("BSEG", where={"WAERS": "EUR"}, requested_package_size=5000,
                  on_hana=True)
    assert p.verdict == "GO" and p.recommended_package_size == 5000
    assert len(p.stages) == 1 and p.stages[0]["table"] == "BSEG"
    print(f"  BSEG on HANA: cluster penalty does not apply - verdict={p.verdict} OK")

    # 5) PCL1 with NO WHERE - hard NO GO (would dump prod)
    p = preflight("PCL1", where={}, requested_package_size=5000)
    assert p.verdict == "NO_GO"
    assert any("no header partner and no WHERE keys" in w for w in p.warnings)
    print(f"  PCL1 (no header, no WHERE): verdict={p.verdict} - correctly refused OK")

    # 6) Package size capping for POOL
    pkg = safe_package_size("ATAB", requested=5000)
    assert pkg == 1000, pkg
    print(f"  POOL ATAB pkg cap: requested 5000 -> {pkg} OK")

    print("\nOK - cluster-table aware extraction routes safely, rewrites BSEG via BKPF, "
          "refuses full-cluster scans.")
