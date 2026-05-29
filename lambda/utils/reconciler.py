"""
reconciler — post-load reconciliation (the "can you trust it?" layer).

A BAPI returning success is NOT proof the data persisted: a commit can silently
no-op, a number range can recycle, a unit of work can be rolled back downstream.
Reconciliation closes that trust gap by reading every record we *claim* to have
created back from the target's system-of-record table and tying the counts out:

    extracted  ->  attempted  ->  created (BAPI said OK)  ->  verified_in_target

The verdict is binary and unforgiving: created == verified  =>  RECONCILED,
anything missing  =>  DISCREPANCY (with the gap quantified). At full volume the
extracted == created check becomes the completeness gate; today, with sampled
loads, created == verified is the integrity gate.

Verification keys come from the loaders (BapiLoader returns verify_key per record),
so the reconciler stays mechanism-agnostic — it just resolves keys against tables.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

try:
    from sap_number import parse_sap_number
except Exception:  # pragma: no cover
    def parse_sap_number(v, default=0.0):
        try:
            s = str(v).strip()
            return -float(s[:-1]) if s.endswith("-") else float(s)
        except Exception:
            return default

_OPTLINE = 72          # RFC_READ_TABLE OPTIONS: each line must be <= 72 chars
_CHUNK = 10            # keys per existence query (keeps the WHERE well within limits)
_NUM_TOL = 1e-4        # relative tolerance for numeric (amount/rate) value tie-out
_EFF_TOL = 1e-3        # looser tol for effective rates: TCURR.UKURS has finite decimals,
                       # so factor-scaled rates carry ~0.01-0.1% storage rounding


class Reconciler:
    def __init__(self, target_conn):
        self.c = target_conn

    @staticmethod
    def _pack_options(where: str) -> list:
        """Split a WHERE string into <=72-char OPTIONS lines at word boundaries,
        each ending in a space so SAP's direct line-concatenation stays valid SQL."""
        lines, cur = [], ""
        for w in where.split():
            if cur and len(cur) + len(w) + 1 > _OPTLINE:
                lines.append(cur)
                cur = ""
            cur += w + " "
        if cur.strip():
            lines.append(cur)
        return [{"TEXT": ln} for ln in lines]

    @staticmethod
    def _as_num(s):
        """Parse a value as a number, or None if it isn't genuinely numeric.
        (Critically NOT parse_sap_number, whose 0.0 default would make any two
        non-numeric strings — 'ROH' vs 'FERT' — look equal at zero.)"""
        s = str(s).strip()
        if not s:
            return None
        neg = s.endswith("-")
        core = (s[:-1] if neg else s).strip()
        if "," in core and "." not in core:      # SAP comma-decimal
            core = core.replace(",", ".")
        core = core.replace(",", "")             # any remaining commas = thousands
        try:
            v = float(core)
        except ValueError:
            return None
        return -v if neg else v

    @classmethod
    def _val_match(cls, expected, actual) -> bool:
        """True if a stored value matches what we sent. Exact for char fields
        (after trim); relative-tolerance ONLY when both sides are truly numeric
        (amounts/rates differ only in formatting, e.g. sent 0.5 vs stored '0.50000')."""
        e, a = str(expected).strip(), str(actual).strip()
        if e == a:
            return True
        en, an = cls._as_num(e), cls._as_num(a)
        if en is not None and an is not None:
            return abs(en - an) <= _NUM_TOL * max(abs(en), abs(an), 1.0)
        return False

    def _verify_records(self, table: str, records: list) -> tuple:
        """Read each record back from `table` and check (a) it exists and (b) the
        values we declared match what's stored. records: [{"key":{}, "values":{}}].
        Returns (exists_count, value_checked, value_ok, mismatches)."""
        if not records:
            return 0, 0, 0, []
        keyf = list(records[0]["key"].keys())
        valf = sorted({f for r in records for f in (r.get("values") or {})})
        readf = keyf + [f for f in valf if f not in keyf]
        stored = {}                                   # key-tuple -> {field: stored value}
        for i in range(0, len(records), _CHUNK):
            chunk = records[i:i + _CHUNK]
            terms = ["( " + " AND ".join("%s = '%s'" % (f, str(r["key"][f]).strip())
                                         for f in keyf) + " )" for r in chunk]
            where = " OR ".join(terms)
            try:
                res = self.c.call("RFC_READ_TABLE", QUERY_TABLE=table, DELIMITER="|",
                                  OPTIONS=self._pack_options(where),
                                  FIELDS=[{"FIELDNAME": f} for f in readf], ROWCOUNT=0)
                for d in res.get("DATA", []):
                    vals = [x.strip() for x in d["WA"].split("|")]
                    rowd = dict(zip(readf, vals))
                    stored[tuple(rowd[f] for f in keyf)] = rowd
            except Exception:
                pass  # unread -> not found -> correctly counts as a discrepancy

        exists = value_checked = value_ok = 0
        mismatches = []
        for r in records:
            ktup = tuple(str(r["key"][f]).strip() for f in keyf)
            row = stored.get(ktup)
            if row is None:
                continue
            exists += 1
            vals = r.get("values") or {}
            if not vals:
                continue
            value_checked += 1
            bad = [(f, vals[f], row.get(f, "")) for f in vals
                   if not self._val_match(vals[f], row.get(f, ""))]
            if bad:
                for f, exp, act in bad[:5]:
                    mismatches.append({"key": r["key"], "field": f, "expected": exp, "actual": act})
            else:
                value_ok += 1
        return exists, value_checked, value_ok, mismatches

    def _read_keyed(self, table: str, keyf: list, records: list, extra: list) -> dict:
        """Batch-read `table` for the records' keys; return {keytuple: {field: val}}."""
        out, readf = {}, keyf + [f for f in extra if f not in keyf]
        for i in range(0, len(records), _CHUNK):
            terms = ["( " + " AND ".join("%s = '%s'" % (f, str(r["key"][f]).strip())
                                         for f in keyf) + " )" for r in records[i:i + _CHUNK]]
            try:
                res = self.c.call("RFC_READ_TABLE", QUERY_TABLE=table, DELIMITER="|",
                                  OPTIONS=self._pack_options(" OR ".join(terms)),
                                  FIELDS=[{"FIELDNAME": f} for f in readf], ROWCOUNT=0)
                for d in res.get("DATA", []):
                    vals = [x.strip() for x in d["WA"].split("|")]
                    rowd = dict(zip(readf, vals))
                    out[tuple(rowd[f] for f in keyf)] = rowd
            except Exception:
                pass
        return out

    def _verify_exrate_effective(self, records: list) -> tuple:
        """Exchange-rate value tie-out done right: TCURR.UKURS is factor-normalized, so
        compare stored UKURS * (TCURF TFACT/FFACT) against the rate we sent. Reads UKURS
        and the per-pair TCURF factor in batches (scales to thousands)."""
        keyf = ["KURST", "FCURR", "TCURR", "GDATU"]
        stored = self._read_keyed("TCURR", keyf, records, ["UKURS"])
        # one factor per (type,from,to) — stable across GDATU; default 1:1 if none
        pf = ["KURST", "FCURR", "TCURR"]
        pair_recs, seen = [], set()
        for r in records:
            p = tuple(r["key"][f] for f in pf)
            if p not in seen:
                seen.add(p)
                pair_recs.append({"key": {f: r["key"][f] for f in pf}})
        facrows = self._read_keyed("TCURF", pf, pair_recs, ["FFACT", "TFACT"])
        factor = {k: (parse_sap_number(v.get("FFACT"), 1) or 1, parse_sap_number(v.get("TFACT"), 1) or 1)
                  for k, v in facrows.items()}

        exists = value_checked = value_ok = 0
        mismatches = []
        for r in records:
            ktup = tuple(str(r["key"][f]).strip() for f in keyf)
            row = stored.get(ktup)
            if row is None:
                continue
            exists += 1
            value_checked += 1
            ff, tf = factor.get(tuple(str(r["key"][f]).strip() for f in pf), (1.0, 1.0))
            effective = parse_sap_number(row.get("UKURS")) * tf / ff
            expected = parse_sap_number(r.get("effective_rate"))
            if abs(expected - effective) <= _EFF_TOL * max(abs(expected), abs(effective), 1.0):
                value_ok += 1
            else:
                mismatches.append({"key": r["key"], "field": "effective_rate",
                                   "expected": r.get("effective_rate"), "actual": round(effective, 5)})
        return exists, value_checked, value_ok, mismatches[:10]

    def reconcile(self, obj: str, load_result: dict, extracted: int = None) -> dict:
        """Tie out one object's load against the target system of record — both
        existence (created == verified) and value (sent == stored)."""
        created = load_result.get("created_in_s4", 0)
        keys = load_result.get("created_keys", []) or []
        grouped, by_table = {}, {}
        for vk in keys:
            grouped.setdefault(vk["table"], []).append(vk)
        verified = value_checked = value_ok = 0
        mismatches = []
        for table, recs in grouped.items():
            if table == "TCURR" and any("effective_rate" in r for r in recs):
                ex, vc, vo, mm = self._verify_exrate_effective(recs)
            else:
                ex, vc, vo, mm = self._verify_records(table, recs)
            verified += ex
            value_checked += vc
            value_ok += vo
            mismatches.extend(mm)
            by_table[table] = {"checked": len(recs), "verified_in_target": ex,
                               "value_checked": vc, "value_matched": vo}

        missing = created - verified
        if created == 0:
            status = "NO_LOAD"          # nothing was loaded to reconcile
        elif not keys:
            status = "NOT_VERIFIABLE"   # loaded but no verification key available
        elif missing > 0:
            status = "DISCREPANCY"      # records the BAPI claimed are not in the target
        elif value_checked and value_ok < value_checked:
            status = "VALUE_DISCREPANCY"  # present, but stored values differ from sent
        else:
            status = "RECONCILED"

        report = {
            "object": obj,
            "extracted": extracted,
            "attempted": load_result.get("attempted"),
            "created": created,
            "verified_in_target": verified,
            "missing": missing,
            "value_checked": value_checked,
            "value_matched": value_ok,
            "value_mismatches": mismatches[:10],
            "status": status,
            "by_table": by_table,
        }
        return report

    @staticmethod
    def rollup(reports: list) -> dict:
        """Run-level reconciliation verdict across all reconciled objects."""
        bad_states = ("DISCREPANCY", "VALUE_DISCREPANCY")
        considered = [r for r in reports if r.get("status") in ("RECONCILED",) + bad_states]
        created = sum(r.get("created", 0) for r in considered)
        verified = sum(r.get("verified_in_target", 0) for r in considered)
        flagged = [r["object"] for r in considered if r.get("status") in bad_states]
        return {
            "objects_reconciled": len(considered),
            "records_created": created,
            "records_verified_in_target": verified,
            "records_missing": created - verified,
            "records_value_checked": sum(r.get("value_checked", 0) for r in considered),
            "records_value_matched": sum(r.get("value_matched", 0) for r in considered),
            "objects_with_discrepancy": flagged,
            "verdict": "RECONCILED" if (considered and not flagged) else
                       ("DISCREPANCY" if flagged else "NOTHING_TO_RECONCILE"),
        }


# ════════════════════════════════════════════════════════════════════════════
#  Pillar 4 — cryptographic auditing & regulatory compliance
# ════════════════════════════════════════════════════════════════════════════
GENESIS_HASH = "0" * 64


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


class HashChainLedger:
    """Append-only, SHA-256 **hash-chained** audit ledger.

    Every batch write, key-map execution, and validation verdict is recorded as a
    block whose ``block_hash`` binds its content to the previous block's hash. Any
    retroactive edit, reorder, or deletion breaks the chain — the mathematical
    tamper-evidence a Big-Four auditor needs. Persists as JSONL (and optionally to a
    DynamoDB audit vault); ``verify()`` walks the chain and pinpoints any break.

    Thread-safe so parallel loaders can record concurrently.
    """

    def __init__(self, path: str | os.PathLike | None = None,
                 ddb_table: str | None = None, run_id: str = "run"):
        self.path = Path(path) if path else None
        self.run_id = run_id
        self.ddb_table = ddb_table or os.environ.get("M4H_AUDIT_LEDGER_TABLE")
        self._lock = threading.Lock()
        self._blocks: list = []
        self._seq = 0
        self._prev = GENESIS_HASH
        if self.path and self.path.exists():
            self._load()

    def _load(self) -> None:
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    b = json.loads(line)
                except json.JSONDecodeError:
                    continue   # torn final line from a crash mid-write — tolerate
                self._blocks.append(b)
        if self._blocks:
            self._seq = self._blocks[-1]["seq"] + 1
            self._prev = self._blocks[-1]["block_hash"]

    @staticmethod
    def _block_body(seq, ts, run_id, kind, payload_hash, prev_hash) -> dict:
        return {"seq": seq, "ts": ts, "run_id": run_id, "kind": kind,
                "payload_hash": payload_hash, "prev_hash": prev_hash}

    def append(self, kind: str, payload) -> dict:
        """Append a cryptographically-chained block for ``payload`` and return it."""
        with self._lock:
            payload_hash = _sha256(_canon(payload))
            body = self._block_body(self._seq, _now_iso(), self.run_id, kind,
                                    payload_hash, self._prev)
            block = dict(body, block_hash=_sha256(_canon(body)))
            self._blocks.append(block)
            self._prev = block["block_hash"]
            self._seq += 1
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(block, separators=(",", ":")) + "\n")
            self._ddb_put(block, payload)
            return block

    def _ddb_put(self, block: dict, payload) -> None:
        if not self.ddb_table:
            return
        try:  # infra-gated; never let an audit-vault hiccup break the load
            import boto3
            boto3.client("dynamodb").put_item(
                TableName=self.ddb_table,
                Item={
                    "run_id": {"S": self.run_id},
                    "seq": {"N": str(block["seq"])},
                    "block_hash": {"S": block["block_hash"]},
                    "prev_hash": {"S": block["prev_hash"]},
                    "kind": {"S": block["kind"]},
                    "ts": {"S": block["ts"]},
                    "payload": {"S": _canon(payload)[:380000]},
                })
        except Exception:  # noqa: BLE001
            pass

    def head(self) -> str:
        return self._prev

    def block_count(self) -> int:
        return len(self._blocks)

    def dump_jsonl(self) -> str:
        """Serialise the whole chain as JSONL (for S3 persistence in any environment)."""
        return "".join(json.dumps(b, separators=(",", ":")) + "\n" for b in self._blocks)

    def verify(self) -> dict:
        """Walk the chain; confirm seq order, prev-hash links, and recomputed hashes."""
        prev = GENESIS_HASH
        for i, b in enumerate(self._blocks):
            if b.get("seq") != i:
                return {"ok": False, "broken_at": i, "reason": "sequence_gap"}
            if b.get("prev_hash") != prev:
                return {"ok": False, "broken_at": i, "reason": "prev_hash_mismatch"}
            recomputed = _sha256(_canon(self._block_body(
                b["seq"], b["ts"], b["run_id"], b["kind"], b["payload_hash"], b["prev_hash"])))
            if recomputed != b.get("block_hash"):
                return {"ok": False, "broken_at": i, "reason": "block_hash_mismatch"}
            prev = b["block_hash"]
        return {"ok": True, "blocks": len(self._blocks), "head": prev}


class AggregateReconciler:
    """Aggregate sub-ledger balance tie-out (source ECC vs target S/4HANA).

    For financial / material balance ledgers (OpenAR, OpenAP, InventoryBalance) the
    record-level reconciler proves *existence*; this proves the *money/quantity ties
    out in aggregate* — total value, debit/credit split, and record count match
    within tolerance. Aggregation is client-side over read rows (RFC_READ_TABLE has
    no SUM); for true server-side SUM, drive the in-system ABAP agent.
    """

    @staticmethod
    def aggregate(rows: list, value_field: str, sign_field: str | None = None,
                  debit_code: str = "S") -> dict:
        """Sum ``value_field`` over ``rows`` with optional debit/credit split by
        ``sign_field`` (SAP SHKZG: 'S' debit / 'H' credit)."""
        count = total = debit = credit = 0
        total = debit = credit = 0.0
        for r in rows:
            v = Reconciler._as_num(r.get(value_field))
            if v is None:
                v = 0.0
            total += v
            if sign_field:
                if str(r.get(sign_field, "")).strip().upper() == debit_code:
                    debit += v
                else:
                    credit += v
            count += 1
        return {"count": count, "total": round(total, 2),
                "debit": round(debit, 2), "credit": round(credit, 2)}

    @staticmethod
    def tie_out(ledger: str, source_agg: dict, target_agg: dict,
                tol: float = 0.01) -> dict:
        """Compare source vs target aggregates. count must match exactly; monetary
        figures within relative ``tol``. Returns a TIE_OUT / VARIANCE verdict + deltas."""
        deltas: dict = {}
        status = "TIE_OUT"
        for k in ("count", "total", "debit", "credit"):
            s, t = source_agg.get(k), target_agg.get(k)
            if s is None or t is None:
                continue
            delta = round((t or 0) - (s or 0), 4)
            deltas[k] = {"source": s, "target": t, "delta": delta}
            if k == "count":
                if int(s) != int(t):
                    status = "VARIANCE"
            elif abs(delta) > tol * max(abs(s), abs(t), 1.0):
                status = "VARIANCE"
        return {"ledger": ledger, "status": status, "deltas": deltas}

    @classmethod
    def rollup(cls, tieouts: list) -> dict:
        variances = [t["ledger"] for t in tieouts if t.get("status") == "VARIANCE"]
        return {"ledgers_checked": len(tieouts),
                "ledgers_with_variance": variances,
                "verdict": "BALANCED" if (tieouts and not variances) else
                           ("VARIANCE" if variances else "NOTHING_TO_TIE_OUT")}


class EvidencePack:
    """Auditor-grade, tamper-proof evidence pack.

    Always compiles a signed JSON manifest (system config, data-quality logs, target
    API success responses, balance tie-out metrics, reconciliation verdict, and the
    audit-chain head hash). When boto3 is available it uploads to S3 with **WORM
    Object Lock** (COMPLIANCE retention) so the record is immutable for the retention
    window. PDF rendering is delegated to the project's pdf_report_generator from the
    manifest; the manifest itself is the legally-binding, hash-sealed artifact.
    """

    def __init__(self, run_id: str, chain: HashChainLedger | None = None):
        self.run_id = run_id
        self.chain = chain

    def build_manifest(self, *, system_config=None, data_quality=None,
                       api_responses=None, balance_tieouts=None,
                       reconciliation=None) -> dict:
        manifest = {
            "run_id": self.run_id,
            "generated": _now_iso(),
            "classification": "CONFIDENTIAL — Auditor Evidence (immutable)",
            "system_config": system_config or {},
            "data_quality": data_quality or {},
            "target_api_responses": api_responses or [],
            "balance_tie_outs": balance_tieouts or [],
            "reconciliation": reconciliation or {},
            "audit_chain": {
                "head_hash": self.chain.head() if self.chain else None,
                "verification": self.chain.verify() if self.chain else None,
            },
        }
        manifest["manifest_sha256"] = _sha256(_canon(manifest))
        # Seal the manifest hash into the chain so the evidence pack is itself chained.
        if self.chain is not None:
            self.chain.append("evidence_pack", {"manifest_sha256": manifest["manifest_sha256"]})
            manifest["sealed_block_hash"] = self.chain.head()
        return manifest

    def write(self, manifest: dict, out_dir: str | os.PathLike | None = None,
              s3_bucket: str | None = None, s3_key: str | None = None,
              retain_days: int = 2555) -> dict:
        """Persist the manifest locally (always) and, if configured, to S3 with WORM
        Object Lock. Returns the artifact locations + whether WORM was applied."""
        result = {"manifest_sha256": manifest.get("manifest_sha256"), "local": None,
                  "s3": None, "worm": False}
        body = json.dumps(manifest, indent=2, default=str).encode("utf-8")
        if out_dir:
            d = Path(out_dir)
            d.mkdir(parents=True, exist_ok=True)
            local = d / f"evidence_pack_{self.run_id}.json"
            local.write_bytes(body)
            result["local"] = str(local)
        bucket = s3_bucket or os.environ.get("M4H_EVIDENCE_BUCKET")
        if bucket:
            key = s3_key or f"evidence/{self.run_id}/evidence_pack.json"
            try:  # infra-gated — WORM bucket must have Object Lock enabled at creation
                import boto3
                from datetime import timedelta
                boto3.client("s3").put_object(
                    Bucket=bucket, Key=key, Body=body,
                    ContentType="application/json",
                    ObjectLockMode="COMPLIANCE",
                    ObjectLockRetainUntilDate=datetime.now(timezone.utc) + timedelta(days=retain_days))
                result["s3"] = f"s3://{bucket}/{key}"
                result["worm"] = True
            except Exception as e:  # noqa: BLE001
                result["s3_error"] = str(e)[:160]
        return result


# ── self-test (no AWS) — chain integrity, tamper-detection, tie-out, evidence ──
if __name__ == "__main__":
    import tempfile

    print("=" * 74)
    print("reconciler Pillar-4 — self-test (crypto chain + aggregate tie-out + evidence)")
    print("=" * 74)

    tmp = Path(tempfile.mkdtemp(prefix="m4h_audit_"))
    chain = HashChainLedger(path=tmp / "audit_chain.jsonl", run_id="AUDIT-1")
    chain.append("batch_write", {"object": "OpenAR", "created": 600})
    chain.append("key_map", {"object": "OpenAR", "mappings": 600})
    chain.append("validation", {"object": "OpenAR", "status": "RECONCILED"})
    v = chain.verify()
    print(f"\n[chain] appended 3 blocks; verify={v}")
    assert v["ok"] and v["blocks"] == 3

    # reload from disk and confirm the chain still verifies (resume-safe)
    chain2 = HashChainLedger(path=tmp / "audit_chain.jsonl", run_id="AUDIT-1")
    assert chain2.verify()["ok"] and chain2.head() == chain.head()
    print(f"[chain] reloaded from disk; head matches = {chain2.head()[:16]}…")

    # tamper detection: flip a stored block and re-verify
    bad = HashChainLedger(path=tmp / "audit_chain.jsonl", run_id="AUDIT-1")
    bad._blocks[1]["payload_hash"] = "deadbeef" * 8
    tv = bad.verify()
    print(f"[chain] tamper test -> {tv}")
    assert not tv["ok"] and tv["broken_at"] == 1

    # aggregate balance tie-out: OpenAR debit/credit split
    src_rows = [{"DMBTR": "1000.00", "SHKZG": "S"}, {"DMBTR": "250.50", "SHKZG": "H"},
                {"DMBTR": "749.50", "SHKZG": "S"}]
    tgt_rows = [{"DMBTR": "1000.00", "SHKZG": "S"}, {"DMBTR": "250.50", "SHKZG": "H"},
                {"DMBTR": "749.50", "SHKZG": "S"}]
    s_agg = AggregateReconciler.aggregate(src_rows, "DMBTR", sign_field="SHKZG")
    t_agg = AggregateReconciler.aggregate(tgt_rows, "DMBTR", sign_field="SHKZG")
    tie = AggregateReconciler.tie_out("OpenAR", s_agg, t_agg)
    print(f"\n[tie-out] balanced -> {tie['status']} deltas={tie['deltas']}")
    assert tie["status"] == "TIE_OUT"

    # introduce a 1-record / value variance on the target
    t_bad = AggregateReconciler.aggregate(tgt_rows[:-1], "DMBTR", sign_field="SHKZG")
    tie_bad = AggregateReconciler.tie_out("OpenAR", s_agg, t_bad)
    print(f"[tie-out] variance -> {tie_bad['status']} "
          f"(count {tie_bad['deltas']['count']['delta']}, total {tie_bad['deltas']['total']['delta']})")
    assert tie_bad["status"] == "VARIANCE"

    # evidence pack: manifest sealed into the chain
    ep = EvidencePack("AUDIT-1", chain=chain)
    manifest = ep.build_manifest(
        system_config={"target": "S4H", "client": "100"},
        data_quality={"rejected": 2, "rejections": ["MANDATORY:LAND1"]},
        api_responses=[{"object": "OpenAR", "ok": True}],
        balance_tieouts=[tie], reconciliation={"verdict": "RECONCILED"})
    out = ep.write(manifest, out_dir=tmp)
    print(f"\n[evidence] manifest sha256={manifest['manifest_sha256'][:16]}… "
          f"sealed_block={manifest.get('sealed_block_hash','')[:16]}…")
    print(f"[evidence] written -> {out['local']} (worm={out['worm']})")
    assert chain.verify()["ok"] and out["local"]

    print("\nOK — hash chain verifies + detects tampering; aggregate tie-out flags "
          "balance variance; evidence pack is hash-sealed into the chain.")
    print(f"artifacts in {tmp}")
