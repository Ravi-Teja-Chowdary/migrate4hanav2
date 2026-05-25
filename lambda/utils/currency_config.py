"""
currency_config — exchange-rate CUSTOMIZING reconciliation (production-grade).

Exchange rates (TCURR) can only post when their supporting *customizing* exists in
the target: the rate TYPE in TCURV and a translation FACTOR in TCURF for the exact
(rate-type, from-curr, to-curr). That config is client-specific customizing — in a
real S/4 project it is moved through the transport system, NOT written behind the
business's back. So this module does what a world-class migration tool does:

    DETECT the gap  ->  QUANTIFY its impact  ->  PACKAGE a reviewable artifact

It reads source + target config, computes the *minimal* delta actually needed by the
rates being migrated (never over-provisions), and emits a deploy package the config
team applies via standard channels (OB07 for rate types, OBBS/"translation ratios"
for factors, or an SE16/LSMW load in non-prod). The data load then reaches ~100%.

Pure read + compute: no writes here. I/O is the caller's job (handler owns staging).
"""
from __future__ import annotations
from collections import Counter

# TCURV = exchange-rate types; TCURF = translation factors (both customizing).
TCURV_FIELDS = ["KURST", "XINVR", "BWAER", "XBWRL", "GKUZU", "BKUZU", "XFIXD", "XEURO", "XNORL"]
TCURF_FIELDS = ["KURST", "FCURR", "TCURR", "GDATU", "FFACT", "TFACT", "ABWCT", "ABWGA"]


class CurrencyConfigReconciler:
    def __init__(self, src_conn, tgt_conn):
        self.s = src_conn
        self.t = tgt_conn

    @staticmethod
    def _columns(conn, table: str) -> list:
        r = conn.call("RFC_READ_TABLE", QUERY_TABLE=table, DELIMITER="|", ROWCOUNT=1)
        return [f["FIELDNAME"] for f in r["FIELDS"]]

    def _read(self, conn, table: str, fields: list, n: int = 1000000) -> list:
        # Read only fields that actually exist on this system (TCURV differs across
        # releases — e.g. ECC 740 has no XNORL). Keeps the reconciler release-proof.
        present = [f for f in fields if f in set(self._columns(conn, table))]
        r = conn.call("RFC_READ_TABLE", QUERY_TABLE=table, DELIMITER="|",
                      FIELDS=[{"FIELDNAME": f} for f in present], ROWCOUNT=n)
        rows = []
        for d in r.get("DATA", []):
            vals = d["WA"].split("|")
            row = {f: (vals[i].strip() if i < len(vals) else "") for i, f in enumerate(present)}
            for f in fields:                       # absent columns default blank
                row.setdefault(f, "")
            rows.append(row)
        return rows

    def diff(self, rate_rows: list = None) -> dict:
        """Compute the minimal TCURV/TCURF delta needed for the source's rates to
        load into the target, with per-gap impact (rate rows unblocked).
        Pass rate_rows (already-extracted TCURR dicts) to skip re-reading TCURR."""
        # What the source rates actually require
        src_rates = rate_rows if rate_rows is not None else self._read(self.s, "TCURR", ["KURST", "FCURR", "TCURR"])
        total_rates = len(src_rates)
        combo_rows = Counter((r["KURST"], r["FCURR"], r["TCURR"]) for r in src_rates)
        type_rows = Counter(r["KURST"] for r in src_rates)

        # Source config (to copy from) and target config (what already exists)
        src_tcurv = {r["KURST"]: r for r in self._read(self.s, "TCURV", TCURV_FIELDS)}
        tgt_tcurv = {r["KURST"] for r in self._read(self.t, "TCURV", ["KURST"])}
        src_tcurf = {(r["KURST"], r["FCURR"], r["TCURR"]): r
                     for r in self._read(self.s, "TCURF", TCURF_FIELDS)}
        tgt_tcurf = {(r["KURST"], r["FCURR"], r["TCURR"])
                     for r in self._read(self.t, "TCURF", ["KURST", "FCURR", "TCURR"])}

        # Gap 1: rate types used by rates but absent from target TCURV
        missing_types = []
        for kt, cnt in type_rows.most_common():
            if kt and kt not in tgt_tcurv:
                base = src_tcurv.get(kt, {"KURST": kt})
                missing_types.append({**base, "rows_unblocked": cnt,
                                      "source_defined": kt in src_tcurv})

        # Gap 2: (type, from, to) factor combos used by rates but absent from target TCURF
        missing_factors, no_source = [], 0
        for (kt, fc, tc), cnt in combo_rows.most_common():
            if (kt, fc, tc) in tgt_tcurf:
                continue                                   # factor already present
            src = src_tcurf.get((kt, fc, tc))
            if src:
                missing_factors.append({**src, "rows_unblocked": cnt})
            else:
                no_source += 1                             # source has no factor either
                missing_factors.append({"KURST": kt, "FCURR": fc, "TCURR": tc,
                                        "FFACT": "1", "TFACT": "1",
                                        "GDATU": "81999898", "ABWCT": "", "ABWGA": "",
                                        "no_source_factor": True, "rows_unblocked": cnt})

        # Coverage math: a rate becomes loadable once BOTH its type and factor exist
        will_provision_types = tgt_tcurv | {m["KURST"] for m in missing_types}
        will_provision_facts = tgt_tcurf | {(m["KURST"], m["FCURR"], m["TCURR"]) for m in missing_factors}
        loadable_before = sum(c for (kt, fc, tc), c in combo_rows.items()
                              if kt in tgt_tcurv and (kt, fc, tc) in tgt_tcurf)
        loadable_after = sum(c for (kt, fc, tc), c in combo_rows.items()
                             if kt in will_provision_types and (kt, fc, tc) in will_provision_facts)

        return {
            "total_source_rate_rows": total_rates,
            "coverage_before": {"rows": loadable_before,
                                "pct": round(100 * loadable_before / total_rates, 1) if total_rates else 0},
            "coverage_after_provisioning": {"rows": loadable_after,
                                "pct": round(100 * loadable_after / total_rates, 1) if total_rates else 0},
            "missing_rate_types": missing_types,
            "missing_factors": missing_factors,
            "missing_rate_type_count": len(missing_types),
            "missing_factor_count": len(missing_factors),
            "factors_without_source": no_source,
        }

    @staticmethod
    def build_artifact(report: dict) -> tuple:
        """Turn a diff() report into a deploy package: a JSON manifest (full attrs,
        impact, ready for an SE16/LSMW non-prod load) and a flat CSV for review/OB07.
        Returns (manifest_dict, csv_text)."""
        lines = ["TABLE,KURST,FCURR,TCURR,GDATU,FFACT,TFACT,ROWS_UNBLOCKED,NOTE"]
        for m in report["missing_rate_types"]:
            note = "rate type (TCURV) via OB07" + ("" if m.get("source_defined") else "; not in source TCURV")
            lines.append(f"TCURV,{m['KURST']},,,,,,{m['rows_unblocked']},{note}")
        for m in report["missing_factors"]:
            note = "translation factor (TCURF) via OBBS" + ("; default 1:1 (no source)" if m.get("no_source_factor") else "")
            lines.append(f"TCURF,{m['KURST']},{m['FCURR']},{m['TCURR']},{m.get('GDATU','')},"
                         f"{m.get('FFACT','')},{m.get('TFACT','')},{m['rows_unblocked']},{note}")
        manifest = {
            "artifact": "currency_customizing_delta",
            "purpose": "Prerequisite customizing for exchange-rate (TCURR) migration. "
                       "Apply via transport/BC-Set (prod) or SE16/LSMW (non-prod), then re-run the rate load.",
            "coverage_before": report["coverage_before"],
            "coverage_after_provisioning": report["coverage_after_provisioning"],
            "apply_order": ["TCURV (rate types) - OB07", "TCURF (translation factors) - OBBS"],
            "tcurv_entries": report["missing_rate_types"],
            "tcurf_entries": report["missing_factors"],
        }
        return manifest, "\n".join(lines) + "\n"
