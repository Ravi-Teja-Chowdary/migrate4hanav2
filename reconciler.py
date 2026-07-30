"""
reconciler — source↔target reconciliation, the gate that earns the verified ✅.

A migration you cannot reconcile to the source is not a migration you can trust —
especially for the financial/inventory/asset balances of Bucket 3. This module is
the generic proof primitive: given a source scope and a target scope, it reports
key match (did every intended record land?), counts, and optional numeric-sum
reconciliation (do the balances tie to the cent?).

Spec (JSON):
  {
    "object": "GLAccount",
    "source": {"conn":"ecc",    "table":"SKA1", "keys":["KTOPL","SAKNR"], "where":"KTOPL = 'INT'"},
    "target": {"conn":"target", "table":"SKA1", "keys":["KTOPL","SAKNR"], "where":"KTOPL = 'INT'"},
    "sum":    {"source_field":"...", "target_field":"...", "over":"matched"}   // optional
  }

Reads use the Engine's connection layer + RFC_READ_TABLE. Keys are normalised
(trimmed, leading zeros stripped) so ECC↔S/4 numbering lines up. Run:
    py -3.7 reconciler.py recon/<name>.json
"""
import sys, json
from migration_engine import Engine


class Reconciler:
    def __init__(self, eng: Engine):
        self.eng = eng

    def _norm(self, r, keys):
        return "~".join((r.get(k, "") or "").strip().lstrip("0") for k in keys)

    def _rows(self, side):
        conn = self.eng.conn(side.get("conn", "ecc"))
        fields = list(side["keys"]) + ([side["sum_field"]] if side.get("sum_field") else [])
        return self.eng.read_table(conn, side["table"], fields, side.get("where", ""))

    def reconcile(self, spec):
        s_side, t_side = spec["source"], spec["target"]
        sumspec = spec.get("sum")
        if sumspec:
            s_side = dict(s_side, sum_field=sumspec["source_field"])
            t_side = dict(t_side, sum_field=sumspec["target_field"])
        s_rows, t_rows = self._rows(s_side), self._rows(t_side)
        s = {self._norm(r, s_side["keys"]) for r in s_rows}
        t = {self._norm(r, t_side["keys"]) for r in t_rows}
        matched, missing, extra = s & t, s - t, t - s
        out = {
            "object": spec.get("object", "?"),
            "source_count": len(s), "target_count": len(t),
            "matched": len(matched), "missing_in_target": len(missing),
            "extra_in_target": len(extra),
            "match_pct": round(100.0 * len(matched) / len(s), 2) if s else 0.0,
            "missing_samples": sorted(missing)[:10],
        }
        if sumspec:
            def total(rows, side, keyset=None):
                tot = 0.0
                for r in rows:
                    if keyset is not None and self._norm(r, side["keys"]) not in keyset:
                        continue
                    v = (r.get(side["sum_field"], "") or "").strip().replace(",", "")
                    try:
                        tot += float(v or 0)
                    except ValueError:
                        pass
                return round(tot, 2)
            keyset = matched if sumspec.get("over", "matched") == "matched" else None
            ssum, tsum = total(s_rows, s_side, keyset), total(t_rows, t_side, keyset)
            out["sum_source"], out["sum_target"] = ssum, tsum
            out["sum_delta"] = round(ssum - tsum, 2)
            out["sum_ties"] = abs(ssum - tsum) < 0.01
        return out


def _verdict(r):
    ok = r["missing_in_target"] == 0 and r.get("sum_ties", True)
    return ("RECONCILED ✅" if ok else "GAPS ⚠️")


if __name__ == "__main__":
    spec = json.load(open(sys.argv[1]))
    specs = spec if isinstance(spec, list) else [spec]
    eng = Engine()
    try:
        rc = Reconciler(eng)
        for sp in specs:
            r = rc.reconcile(sp)
            print(f"\n== {r['object']} — {_verdict(r)} ==")
            print(f"   source={r['source_count']} target={r['target_count']} "
                  f"matched={r['matched']} ({r['match_pct']}%) "
                  f"missing_in_target={r['missing_in_target']} extra_in_target={r['extra_in_target']}")
            if r["missing_in_target"]:
                print(f"   missing samples: {r['missing_samples']}")
            if "sum_source" in r:
                print(f"   sum source={r['sum_source']} target={r['sum_target']} "
                      f"delta={r['sum_delta']} ties={r['sum_ties']}")
    finally:
        eng.close()
