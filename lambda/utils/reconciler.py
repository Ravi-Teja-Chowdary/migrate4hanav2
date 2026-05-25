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
