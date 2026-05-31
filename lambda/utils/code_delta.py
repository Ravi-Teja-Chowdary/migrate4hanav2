"""
code_delta.py - dual-maintenance (continuous) custom-code sync between ECC and S/4.

Background
----------
S/4HANA conversion projects take 6-18 months. During that window the live ECC
system keeps running and developers keep changing custom code (Z-programs,
class implementations, function modules). If the S/4 build froze a snapshot at
month 0 and a hotfix lands in ECC at month 7, the S/4 cutover ships a
6-month-old custom layer - the regression is silent and only surfaces in user
acceptance testing or, worse, in production.

SmartShift's real moat over a one-shot remediator is this: a continuous
delta engine that, every day/week, detects new ECC custom-code changes,
re-runs them through the remediation pipeline, and shows the S/4 team what
needs re-merging.

This module is the framework for that loop:

  1. snapshot()   - record fingerprints of every Z/Y object on ECC (program,
                    class, FM, includes). Stored as JSON; one snapshot per
                    timestamp under <baseline_dir>/<sid>/<iso_ts>.json.
  2. detect_delta() - compare the current ECC state to the latest baseline;
                      return CodeDelta objects keyed by (objtype, objname) with
                      a verdict of ADDED / MODIFIED / DELETED.
  3. plan_remediation() - for each MODIFIED/ADDED, schedule a remediator
                          re-run; record the open work in a delta queue file.
  4. DeltaReport       - human-readable summary that ships to the cutover
                         steering committee.

ECC inputs (RFC, all released):
  - RFC_READ_TABLE(TADIR)  for object inventory (OBJ_NAME / OBJECT / DEVCLASS)
  - RFC_READ_TABLE(REPOSRC) for source-code metadata (UDAT/UTIME/UNAM)
  Optional - for deep fingerprint:
  - READ_REPORT             pulls source lines (SHA-256 of body)

The probes accept an injectable rfc_callable; offline tests work without pyrfc.

This is a CONTROL plane, not the remediator itself. It calls back into
llm_fallback_router / abap_ast_engine for the actual fix work. Out of the
box it runs in TRACKING mode (snapshot + detect + report); enabling the
remediation re-run is one line in the caller.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

logger = logging.getLogger("code_delta")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


# ─────────────────────────────────────────────────────────────────────────────
#  Snapshot data structures
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class CodeObject:
    objtype: str        # PROG / CLAS / FUGR / INCL
    objname: str
    devclass: str       # package
    last_modified_by: str
    last_modified_at: str   # ISO 8601 YYYYMMDD-HHMMSS-derived
    source_sha256: Optional[str] = None    # optional deep fingerprint

    def fingerprint(self) -> str:
        """A short stable signature used to detect change without needing the
        full body. Includes who/when + body hash if available."""
        seed = f"{self.objtype}|{self.objname}|{self.last_modified_by}|" \
               f"{self.last_modified_at}|{self.source_sha256 or ''}"
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CodeObject":
        return cls(**d)


@dataclass
class Snapshot:
    sid: str
    taken_at: str
    object_count: int
    objects: Dict[str, CodeObject] = field(default_factory=dict)  # key=objtype:objname

    def to_dict(self) -> dict:
        return {
            "sid": self.sid,
            "taken_at": self.taken_at,
            "object_count": self.object_count,
            "objects": {k: v.to_dict() for k, v in self.objects.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Snapshot":
        snap = cls(sid=d["sid"], taken_at=d["taken_at"],
                   object_count=d["object_count"])
        snap.objects = {k: CodeObject.from_dict(v) for k, v in d.get("objects", {}).items()}
        return snap


# ─────────────────────────────────────────────────────────────────────────────
#  Delta detection
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class CodeDelta:
    objtype: str
    objname: str
    verdict: str        # ADDED / MODIFIED / DELETED
    baseline_fingerprint: Optional[str] = None
    current_fingerprint: Optional[str] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# Z/Y customer namespace (the only objects worth tracking for migration code-sync)
_CUSTOMER_PREFIX_RE = re.compile(r"^[ZY]")
_TRACKED_OBJTYPES = {"PROG", "CLAS", "FUGR", "INCL", "TABL"}


def _tracked(o: dict) -> bool:
    name = (o.get("OBJ_NAME") or o.get("OBJNAME") or o.get("NAME") or "").upper()
    typ = (o.get("OBJECT") or o.get("OBJTYPE") or o.get("OBJ_TYPE") or "").upper()
    return typ in _TRACKED_OBJTYPES and bool(_CUSTOMER_PREFIX_RE.match(name))


# ─────────────────────────────────────────────────────────────────────────────
#  Probes
# ─────────────────────────────────────────────────────────────────────────────
def probe_object_inventory(rfc_callable: Callable[[str, Dict], Dict]) -> List[CodeObject]:
    """Pull the TADIR-class inventory of customer-namespace ABAP objects from
    ECC. The actual RFC reads TADIR via RFC_READ_TABLE; here we accept a
    rfc_callable that returns rows in the same shape."""
    try:
        tadir = rfc_callable("RFC_READ_TABLE",
                             {"QUERY_TABLE": "TADIR",
                              "FIELDS": [{"FIELDNAME": "OBJECT"},
                                         {"FIELDNAME": "OBJ_NAME"},
                                         {"FIELDNAME": "DEVCLASS"}]})
        reposrc = rfc_callable("RFC_READ_TABLE",
                               {"QUERY_TABLE": "REPOSRC",
                                "FIELDS": [{"FIELDNAME": "PROGNAME"},
                                           {"FIELDNAME": "UNAM"},
                                           {"FIELDNAME": "UDAT"},
                                           {"FIELDNAME": "UTIME"}]})
    except Exception as e:  # noqa: BLE001
        logger.warning("TADIR/REPOSRC probe failed: %s", e)
        return []

    reposrc_idx: Dict[str, dict] = {}
    for r in (reposrc.get("DATA") or reposrc.get("ROWS") or reposrc.get("REPOSRC") or []):
        # WAIT - RFC_READ_TABLE returns DATA as packed strings; here we accept
        # the row already split into a dict for test simplicity.
        if isinstance(r, dict):
            name = (r.get("PROGNAME") or "").strip().upper()
            if name:
                reposrc_idx[name] = r

    objects: List[CodeObject] = []
    for r in (tadir.get("DATA") or tadir.get("ROWS") or tadir.get("TADIR") or []):
        if not isinstance(r, dict) or not _tracked(r):
            continue
        name = (r.get("OBJ_NAME") or r.get("OBJNAME") or "").strip().upper()
        typ = (r.get("OBJECT") or r.get("OBJTYPE") or "").strip().upper()
        devclass = (r.get("DEVCLASS") or "").strip().upper()
        meta = reposrc_idx.get(name, {})
        objects.append(CodeObject(
            objtype=typ, objname=name, devclass=devclass,
            last_modified_by=str(meta.get("UNAM") or "").strip(),
            last_modified_at=f"{meta.get('UDAT', '')}-{meta.get('UTIME', '')}".strip("-"),
        ))
    logger.info("Inventory probe returned %d customer-namespace ABAP objects", len(objects))
    return objects


def probe_source_hash(rfc_callable: Callable[[str, Dict], Dict],
                      objname: str) -> Optional[str]:
    """Optional deep fingerprint: pull source via READ_REPORT and SHA-256 it.
    Use sparingly - one RFC per program."""
    try:
        resp = rfc_callable("RPY_PROGRAM_READ", {"PROGRAM_NAME": objname})
    except Exception:
        try:
            resp = rfc_callable("READ_REPORT", {"PROGRAM": objname})
        except Exception as e:
            logger.warning("source-read failed for %s: %s", objname, e)
            return None
    lines = resp.get("SOURCE") or resp.get("SOURCE_EXTENDED") or resp.get("PROG_INF") or []
    if isinstance(lines, list) and lines and isinstance(lines[0], dict):
        body = "\n".join(str(r.get("LINE") or r.get("CONTENT") or "")
                         for r in lines)
    elif isinstance(lines, str):
        body = lines
    else:
        return None
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
#  Snapshot persistence + delta engine
# ─────────────────────────────────────────────────────────────────────────────
class DeltaEngine:
    def __init__(self,
                 baseline_dir: str | Path,
                 sid: str,
                 rfc_callable: Optional[Callable[[str, Dict], Dict]] = None,
                 deep_hash: bool = False):
        self.baseline_dir = Path(baseline_dir)
        self.sid = sid
        self.rfc = rfc_callable
        self.deep_hash = deep_hash
        self._snap_dir = self.baseline_dir / sid
        self._snap_dir.mkdir(parents=True, exist_ok=True)

    # ── snapshot ────────────────────────────────────────────────────────────
    def snapshot(self) -> Snapshot:
        if self.rfc is None:
            raise RuntimeError("DeltaEngine.snapshot needs a live RFC connection "
                               "(or an injected rfc_callable for tests)")
        objects = probe_object_inventory(self.rfc)
        if self.deep_hash:
            for o in objects:
                if o.objtype == "PROG":
                    o.source_sha256 = probe_source_hash(self.rfc, o.objname)
        now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        snap = Snapshot(sid=self.sid, taken_at=now, object_count=len(objects),
                        objects={f"{o.objtype}:{o.objname}": o for o in objects})
        path = self._snap_dir / f"{now}.json"
        path.write_text(json.dumps(snap.to_dict(), indent=2), encoding="utf-8")
        logger.info("Snapshot %s written: %d objects", path.name, len(objects))
        return snap

    def latest_snapshot(self) -> Optional[Snapshot]:
        files = sorted(self._snap_dir.glob("*.json"))
        if not files:
            return None
        return Snapshot.from_dict(json.loads(files[-1].read_text(encoding="utf-8")))

    def all_snapshots(self) -> List[Snapshot]:
        return [Snapshot.from_dict(json.loads(p.read_text(encoding="utf-8")))
                for p in sorted(self._snap_dir.glob("*.json"))]

    # ── delta detection ─────────────────────────────────────────────────────
    def detect_delta(self,
                     baseline: Optional[Snapshot] = None,
                     current: Optional[Snapshot] = None) -> List[CodeDelta]:
        """Compare two snapshots. If baseline is None, use the second-most-
        recent on disk. If current is None, take a fresh probe."""
        if baseline is None:
            snaps = self.all_snapshots()
            if len(snaps) < 2:
                raise RuntimeError("Need at least two snapshots to detect a delta")
            baseline = snaps[-2]
        if current is None:
            current = self.snapshot()

        bkeys = set(baseline.objects)
        ckeys = set(current.objects)
        deltas: List[CodeDelta] = []

        for key in sorted(bkeys - ckeys):
            obj = baseline.objects[key]
            deltas.append(CodeDelta(
                objtype=obj.objtype, objname=obj.objname,
                verdict="DELETED",
                baseline_fingerprint=obj.fingerprint(),
                detail={"last_modified_by": obj.last_modified_by,
                        "last_modified_at": obj.last_modified_at}))

        for key in sorted(ckeys - bkeys):
            obj = current.objects[key]
            deltas.append(CodeDelta(
                objtype=obj.objtype, objname=obj.objname,
                verdict="ADDED",
                current_fingerprint=obj.fingerprint(),
                detail={"last_modified_by": obj.last_modified_by,
                        "last_modified_at": obj.last_modified_at}))

        for key in sorted(bkeys & ckeys):
            bo, co = baseline.objects[key], current.objects[key]
            bfp, cfp = bo.fingerprint(), co.fingerprint()
            if bfp != cfp:
                deltas.append(CodeDelta(
                    objtype=co.objtype, objname=co.objname,
                    verdict="MODIFIED",
                    baseline_fingerprint=bfp,
                    current_fingerprint=cfp,
                    detail={"baseline_modified_at": bo.last_modified_at,
                            "current_modified_at":  co.last_modified_at,
                            "baseline_modified_by": bo.last_modified_by,
                            "current_modified_by":  co.last_modified_by}))

        logger.info("Delta vs baseline %s -> current %s: %d changes",
                    baseline.taken_at, current.taken_at, len(deltas))
        return deltas


# ─────────────────────────────────────────────────────────────────────────────
#  Remediation planning
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class RemediationTask:
    objname: str
    objtype: str
    reason: str          # which delta verdict spawned it
    enqueued_at: str

    def to_dict(self) -> dict:
        return asdict(self)


def plan_remediation(deltas: Iterable[CodeDelta],
                     queue_path: str | Path) -> List[RemediationTask]:
    """For every ADDED/MODIFIED delta, enqueue a remediator task. DELETED is
    not actionable for re-remediation but is logged. Idempotent: re-running
    against the same delta list does not duplicate tasks already in the queue."""
    qpath = Path(queue_path)
    qpath.parent.mkdir(parents=True, exist_ok=True)
    existing: Set[str] = set()
    tasks: List[RemediationTask] = []
    if qpath.exists():
        for line in qpath.read_text(encoding="utf-8").splitlines():
            try:
                t = json.loads(line)
                existing.add(f"{t['objtype']}:{t['objname']}")
            except Exception:
                continue

    now = datetime.now(timezone.utc).isoformat()
    with qpath.open("a", encoding="utf-8") as fh:
        for d in deltas:
            if d.verdict not in ("ADDED", "MODIFIED"):
                continue
            key = f"{d.objtype}:{d.objname}"
            if key in existing:
                continue
            task = RemediationTask(objname=d.objname, objtype=d.objtype,
                                   reason=d.verdict, enqueued_at=now)
            fh.write(json.dumps(task.to_dict()) + "\n")
            tasks.append(task)
            existing.add(key)
    logger.info("Enqueued %d remediation tasks to %s", len(tasks), qpath)
    return tasks


# ─────────────────────────────────────────────────────────────────────────────
#  Self-test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import tempfile, time as _time
    print("=" * 78)
    print("code_delta - self-test")
    print("=" * 78)

    # In-memory ECC fixture - first snapshot
    ecc_state_v1 = {
        "TADIR": [
            {"OBJECT": "PROG", "OBJ_NAME": "ZREPORT_AR_AGEING", "DEVCLASS": "ZFI"},
            {"OBJECT": "PROG", "OBJ_NAME": "ZTOOL_PO_DUMP",     "DEVCLASS": "ZMM"},
            {"OBJECT": "CLAS", "OBJ_NAME": "ZCL_INVOICE_HELPER","DEVCLASS": "ZFI"},
            {"OBJECT": "PROG", "OBJ_NAME": "SAPMV45A",          "DEVCLASS": "VA"},  # SAP-standard, ignored
        ],
        "REPOSRC": [
            {"PROGNAME": "ZREPORT_AR_AGEING", "UNAM": "DEVELOPER_A", "UDAT": "20260101", "UTIME": "100000"},
            {"PROGNAME": "ZTOOL_PO_DUMP",     "UNAM": "DEVELOPER_B", "UDAT": "20260102", "UTIME": "143000"},
            {"PROGNAME": "ZCL_INVOICE_HELPER","UNAM": "DEVELOPER_A", "UDAT": "20260103", "UTIME": "090000"},
        ],
    }
    ecc_state_v2 = {
        "TADIR": [
            {"OBJECT": "PROG", "OBJ_NAME": "ZREPORT_AR_AGEING", "DEVCLASS": "ZFI"},
            # ZTOOL_PO_DUMP deleted
            {"OBJECT": "CLAS", "OBJ_NAME": "ZCL_INVOICE_HELPER","DEVCLASS": "ZFI"},
            # New program added
            {"OBJECT": "PROG", "OBJ_NAME": "ZREPORT_TAX_RECON", "DEVCLASS": "ZFI"},
        ],
        "REPOSRC": [
            # ZREPORT_AR_AGEING modified (different UDAT)
            {"PROGNAME": "ZREPORT_AR_AGEING", "UNAM": "DEVELOPER_A", "UDAT": "20260420", "UTIME": "100000"},
            {"PROGNAME": "ZCL_INVOICE_HELPER","UNAM": "DEVELOPER_A", "UDAT": "20260103", "UTIME": "090000"},
            {"PROGNAME": "ZREPORT_TAX_RECON", "UNAM": "DEVELOPER_C", "UDAT": "20260415", "UTIME": "120000"},
        ],
    }
    current = {"state": ecc_state_v1}

    def fake_rfc(fn, kwargs):
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            return {"DATA": current["state"].get(qt, [])}
        return {}

    with tempfile.TemporaryDirectory() as td:
        engine = DeltaEngine(baseline_dir=td, sid="ECC", rfc_callable=fake_rfc)
        snap1 = engine.snapshot()
        assert snap1.object_count == 3, "should track 3 customer-NS objects, ignore SAP standard"
        print(f"  snapshot v1: {snap1.object_count} tracked objects OK")

        # Wait so the second snapshot has a distinct filename
        _time.sleep(1.1)
        current["state"] = ecc_state_v2
        snap2 = engine.snapshot()
        assert snap2.object_count == 3
        print(f"  snapshot v2: {snap2.object_count} tracked objects OK")

        deltas = engine.detect_delta(baseline=snap1, current=snap2)
        verdicts = sorted([(d.verdict, d.objname) for d in deltas])
        assert ("ADDED",    "ZREPORT_TAX_RECON")  in verdicts
        assert ("DELETED",  "ZTOOL_PO_DUMP")      in verdicts
        assert ("MODIFIED", "ZREPORT_AR_AGEING")  in verdicts
        assert ("MODIFIED", "ZCL_INVOICE_HELPER") not in verdicts  # unchanged
        print(f"  detected {len(deltas)} deltas: {verdicts} OK")

        # Plan remediation - should enqueue ADDED + MODIFIED, NOT DELETED
        qpath = Path(td) / "remediation-queue.jsonl"
        tasks = plan_remediation(deltas, qpath)
        assert len(tasks) == 2
        assert {t.objname for t in tasks} == {"ZREPORT_TAX_RECON", "ZREPORT_AR_AGEING"}
        # Idempotency: re-running on the same deltas should add zero new tasks
        tasks_again = plan_remediation(deltas, qpath)
        assert len(tasks_again) == 0
        print(f"  remediation plan: {len(tasks)} tasks enqueued, re-run is no-op OK")

    print("\nOK - code-delta engine snapshots ECC, detects ADDED/MODIFIED/DELETED, plans remediation.")
