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

_OPTLINE = 72          # RFC_READ_TABLE OPTIONS: each line must be <= 72 chars
_CHUNK = 10            # keys per existence query (keeps the WHERE well within limits)


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

    def _verify_exists(self, table: str, keys: list) -> int:
        """Count how many of `keys` (list of {field: value} dicts) exist in `table`."""
        if not keys:
            return 0
        fields = list(keys[0].keys())
        found = set()
        for i in range(0, len(keys), _CHUNK):
            chunk = keys[i:i + _CHUNK]
            terms = []
            for k in chunk:
                conds = " AND ".join(f"{f} = '{str(k[f]).strip()}'" for f in fields)
                terms.append(f"( {conds} )")
            where = " OR ".join(terms)
            try:
                r = self.c.call("RFC_READ_TABLE", QUERY_TABLE=table, DELIMITER="|",
                                OPTIONS=self._pack_options(where),
                                FIELDS=[{"FIELDNAME": f} for f in fields], ROWCOUNT=0)
                for d in r.get("DATA", []):
                    vals = [x.strip() for x in d["WA"].split("|")]
                    found.add(tuple(vals[:len(fields)]))
            except Exception:
                pass  # leave these keys unverified -> counts as a discrepancy (correctly)
        return sum(1 for k in keys
                   if tuple(str(k[f]).strip() for f in fields) in found)

    def reconcile(self, obj: str, load_result: dict, extracted: int = None) -> dict:
        """Tie out one object's load against the target system of record."""
        created = load_result.get("created_in_s4", 0)
        keys = load_result.get("created_keys", []) or []
        by_table, verified = {}, 0
        grouped = {}
        for vk in keys:
            grouped.setdefault(vk["table"], []).append(vk["key"])
        for table, tkeys in grouped.items():
            v = self._verify_exists(table, tkeys)
            verified += v
            by_table[table] = {"checked": len(tkeys), "verified_in_target": v}

        missing = created - verified
        if created == 0:
            status = "NO_LOAD"          # nothing was loaded to reconcile
        elif not keys:
            status = "NOT_VERIFIABLE"   # loaded but no verification key available
        elif missing == 0:
            status = "RECONCILED"
        else:
            status = "DISCREPANCY"

        report = {
            "object": obj,
            "extracted": extracted,
            "attempted": load_result.get("attempted"),
            "created": created,
            "verified_in_target": verified,
            "missing": missing,
            "status": status,
            "by_table": by_table,
        }
        return report

    @staticmethod
    def rollup(reports: list) -> dict:
        """Run-level reconciliation verdict across all reconciled objects."""
        considered = [r for r in reports if r.get("status") in ("RECONCILED", "DISCREPANCY")]
        created = sum(r.get("created", 0) for r in considered)
        verified = sum(r.get("verified_in_target", 0) for r in considered)
        discrepancies = [r["object"] for r in considered if r.get("status") == "DISCREPANCY"]
        return {
            "objects_reconciled": len(considered),
            "records_created": created,
            "records_verified_in_target": verified,
            "records_missing": created - verified,
            "objects_with_discrepancy": discrepancies,
            "verdict": "RECONCILED" if (considered and not discrepancies) else
                       ("DISCREPANCY" if discrepancies else "NOTHING_TO_RECONCILE"),
        }
