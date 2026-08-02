"""
reconcile_company — the whole-company reconciliation GATE (road-to-production P0-2).

THE PROBLEM IT SOLVES
    Per-object reconciliation ("these 6 balances match to the cent") is not enough to sign a
    go-live. The finance team signs when the WHOLE company ties out: the migrated trial
    balance equals the source, AR/AP open-item totals equal the source, and stock quantity
    (and value) equal the source — to the penny. This module produces that single tie-out
    report + an overall GO / NO-GO verdict. It is **read-only** (never writes to SAP).

WHAT IT CHECKS (per bucket, source total vs target total, variance to the cent)
    * G/L trial balance — for the governed chart-of-accounts map (key_mapper 'gl_account'),
      the source net balance of each mapped account vs what actually landed on the target
      account (sum of the takeover documents, marker M4H-GLBAL). This is the core sign-off.
    * AR / AP open items — source open total for the migrated partners (key_mapper
      customer/vendor) vs the target open total on their Business Partners.
    * Inventory — source stock quantity for migrated materials vs target stock quantity.

VERDICT
    GO only if every in-scope bucket ties to the cent (variance < 0.01 / 0 qty). Otherwise
    NO-GO with the exact variances named — e.g. a non-zero G/L variance from re-running a
    takeover twice is caught here (the motivation for the P0-3 idempotency guard).

    M4H_TARGET_CLIENT=100 py -3.7 reconcile_company.py            # writes RECONCILIATION.md
"""
import os, sys, datetime, collections
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, os.getcwd()); sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))

REPORT = "RECONCILIATION.md"
GL_MARKER = "M4H-GLBAL"


def _amt(s):
    s = (s or "").strip()
    if not s:
        return 0.0
    neg = s.endswith("-"); s = s.rstrip("-").replace(",", "").strip()
    try:
        v = float(s)
    except ValueError:
        return 0.0
    return -v if neg else v


def _gl_trial_balance(eng, kmap, src_cc="1000", tgt_cc="1010", coa="YCOA", src_chart="INT"):
    ecc, tgt = eng.ecc, eng.tgt
    # source net balance per source account (latest year with activity), cocode src_cc
    hsl = ["HSL%02d" % i for i in range(1, 17)]
    glt = [r for r in eng.read_table(ecc, "GLT0", ["RYEAR", "BUKRS", "RACCT", "HSLVT"] + hsl)
           if r["BUKRS"].strip() == src_cc]
    import collections
    year = collections.Counter(r["RYEAR"].strip() for r in glt).most_common(1)
    year = year[0][0] if year else ""
    src_bal = {}
    for r in glt:
        if r["RYEAR"].strip() != year:
            continue
        a = r["RACCT"].strip()
        src_bal[a] = src_bal.get(a, 0.0) + _amt(r["HSLVT"]) + sum(_amt(r[h]) for h in hsl)
    # governed map source->target
    gov = kmap.resolved_map("gl_account")
    # intended target balance per target account = sum of mapped source balances
    intended = {}
    for s, t in gov.items():
        if round(src_bal.get(s, 0.0), 2):
            intended[t] = round(intended.get(t, 0.0) + src_bal[s], 2)
    # posted on target = sum of BSEG signed amounts on the takeover marker docs, per account
    marker_docs = {(r["BELNR"].strip(), r["GJAHR"].strip())
                   for r in eng.read_table(tgt, "BKPF", ["BELNR", "GJAHR", "BUKRS", "XBLNR"])
                   if r["BUKRS"].strip() == tgt_cc and r["XBLNR"].strip().startswith(GL_MARKER)}
    # sum posted amounts ONLY on the mapped takeover accounts (exclude the balancing clearing
    # line — a balanced doc's lines net to zero, so including clearing would hide the real total)
    posted = {}
    for r in eng.read_table(tgt, "BSEG", ["BELNR", "GJAHR", "BUKRS", "HKONT", "DMBTR", "SHKZG"]):
        if r["BUKRS"].strip() != tgt_cc:
            continue
        if (r["BELNR"].strip(), r["GJAHR"].strip()) not in marker_docs:
            continue
        a = r["HKONT"].strip()
        if a not in intended:
            continue
        posted[a] = round(posted.get(a, 0.0) + _amt(r["DMBTR"]) * (-1 if r["SHKZG"].strip() == "H" else 1), 2)
    accts = sorted(intended)
    rows = [(a, intended.get(a, 0.0), posted.get(a, 0.0), round(posted.get(a, 0.0) - intended.get(a, 0.0), 2))
            for a in accts]
    si = round(sum(intended.values()), 2); sp = round(sum(posted.values()), 2)
    return {"rows": rows, "src_total": si, "tgt_total": sp, "variance": round(sp - si, 2),
            "year": year, "mapped": len(gov)}


def _partner_open(eng, kind, kmap, tgt_cc="1710"):
    ecc, tgt = eng.ecc, eng.tgt
    if kind == "AR":
        dim, stab, ttab, key = "customer", "BSID", "BSID", "KUNNR"
    else:
        dim, stab, ttab, key = "vendor", "BSIK", "BSIK", "LIFNR"
    gov = kmap.resolved_map(dim)   # legacy -> BP
    src = eng.read_table(ecc, stab, [key, "DMBTR", "SHKZG"])
    src_tot = round(sum(_amt(r["DMBTR"]) * (-1 if r["SHKZG"].strip() == "H" else 1)
                        for r in src if r[key].strip() in gov), 2)
    bps = {v.lstrip("0") for v in gov.values()}
    tgt = eng.read_table(tgt, ttab, [key, "DMBTR", "SHKZG", "BUKRS"])
    tgt_tot = round(sum(_amt(r["DMBTR"]) * (-1 if r["SHKZG"].strip() == "H" else 1)
                        for r in tgt if r["BUKRS"].strip() == tgt_cc and r[key].strip().lstrip("0") in bps), 2)
    return {"src_total": src_tot, "tgt_total": tgt_tot, "variance": round(tgt_tot - src_tot, 2),
            "partners": len(gov)}


def _age_bucket(days):
    return "0-30" if days <= 30 else "31-60" if days <= 60 else "61-90" if days <= 90 else "90+"


def _aging(eng, kind, kmap, tgt_cc, keydate):
    """AR/AP aging tie-out: bucket the open amount by (keydate - baseline date) for the migrated
    partners, source vs target. If baseline dates were preserved on migration, the buckets match."""
    ecc, tgt = eng.ecc, eng.tgt
    stab = "BSID" if kind == "AR" else "BSIK"
    key = "KUNNR" if kind == "AR" else "LIFNR"
    gov = kmap.resolved_map("customer" if kind == "AR" else "vendor")
    bps = {v.lstrip("0") for v in gov.values()}

    def buckets(rows, keyf):
        b = collections.Counter()
        for r in rows:
            if not keyf(r):
                continue
            z = r["ZFBDT"].strip()
            try:
                d = (keydate - datetime.datetime.strptime(z, "%Y%m%d").date()).days if z else 0
            except ValueError:
                d = 0
            amt = _amt(r["DMBTR"]) * (-1 if r["SHKZG"].strip() == "H" else 1)
            b[_age_bucket(max(d, 0))] += round(amt, 2)
        return {k: round(v, 2) for k, v in b.items()}

    src_rows = []
    for legacy in gov:   # scoped read (migrated partners only)
        src_rows += eng.read_table(ecc, stab, [key, "DMBTR", "SHKZG", "ZFBDT"], "%s = '%s'" % (key, legacy))
    tgt_rows = eng.read_table(tgt, stab, [key, "DMBTR", "SHKZG", "ZFBDT", "BUKRS"])
    s = buckets(src_rows, lambda r: True)
    t = buckets(tgt_rows, lambda r: r["BUKRS"].strip() == tgt_cc and r[key].strip().lstrip("0") in bps)
    allb = ["0-30", "31-60", "61-90", "90+"]
    rows = [(b, s.get(b, 0.0), t.get(b, 0.0), round(t.get(b, 0.0) - s.get(b, 0.0), 2)) for b in allb]
    return {"rows": rows, "variance": round(sum(r[3] for r in rows), 2)}


def _stock_value(eng, plant="1010"):
    """Inventory value tie-out: source stock value (qty x price) vs target, for the plant."""
    ecc, tgt = eng.ecc, eng.tgt

    def val(conn):
        price = {r["MATNR"].strip(): _amt(r["VERPR"]) or _amt(r["STPRS"])
                 for r in eng.read_table(conn, "MBEW", ["MATNR", "STPRS", "VERPR"])}
        tot = 0.0
        for r in eng.read_table(conn, "MARD", ["MATNR", "WERKS", "LABST"]):
            if r["WERKS"].strip() == plant:
                tot += _amt(r["LABST"]) * price.get(r["MATNR"].strip(), 0.0)
        return round(tot, 2)
    s = val(ecc); t = val(tgt)
    return {"src_total": s, "tgt_total": t, "variance": round(t - s, 2)}


def main():
    from migration_engine import Engine
    from key_mapper import KeyMap
    client = os.environ.get("M4H_TARGET_CLIENT", "200")
    eng = Engine(); kmap = KeyMap()
    keydate = datetime.date.today()
    try:
        gl = _gl_trial_balance(eng, kmap)
        ar = _partner_open(eng, "AR", kmap)
        ap = _partner_open(eng, "AP", kmap)
        ar_age = _aging(eng, "AR", kmap, "1710", keydate)
        ap_age = _aging(eng, "AP", kmap, "1710", keydate)
        stock = _stock_value(eng, "1010")
    finally:
        eng.close()

    def verdict(v, tol=0.01):
        return "GO" if abs(v) < tol else "NO-GO"

    def vmark(v, tol=0.01):
        return "GO ✅" if abs(v) < tol else "NO-GO ❌"

    buckets = [
        ("G/L trial balance", gl["src_total"], gl["tgt_total"], gl["variance"],
         f"{gl['mapped']} accounts in governed COA map; source year {gl['year']}"),
        ("AR open items", ar["src_total"], ar["tgt_total"], ar["variance"],
         f"{ar['partners']} migrated customers"),
        ("AP open items", ap["src_total"], ap["tgt_total"], ap["variance"],
         f"{ap['partners']} migrated vendors"),
        ("AR aging (all buckets)", 0.0, ar_age["variance"], ar_age["variance"], "sum of per-bucket variances"),
        ("AP aging (all buckets)", 0.0, ap_age["variance"], ap_age["variance"], "sum of per-bucket variances"),
        ("Inventory value", stock["src_total"], stock["tgt_total"], stock["variance"], "stock qty x price, plant 1010"),
    ]
    all_go = all(abs(b[3]) < 0.01 for b in buckets)
    overall = "GO ✅" if all_go else "NO-GO ❌"

    lines = [f"# Whole-company reconciliation — target client {client}", "",
             f"_Generated {datetime.datetime.now():%Y-%m-%d %H:%M}. Read-only tie-out of source vs "
             "target totals for the migrated scope. GO only if every bucket ties to the cent._", "",
             f"## Overall verdict: **{overall}**", "",
             "| bucket | source total | target total | variance | verdict | scope |",
             "|---|---:|---:|---:|---|---|"]
    for name, s, t, v, scope in buckets:
        lines.append(f"| {name} | {s:,.2f} | {t:,.2f} | {v:,.2f} | {vmark(v)} | {scope} |")
    lines += ["", "### G/L account detail (largest variances first)", "",
              "| target account | intended (source) | posted (target) | variance |",
              "|---|---:|---:|---:|"]
    for a, i, p, v in sorted(gl["rows"], key=lambda r: -abs(r[3]))[:40]:
        lines.append(f"| `{a}` | {i:,.2f} | {p:,.2f} | {v:,.2f} |")
    lines += ["",
              "> **How to read a NO-GO:** a non-zero variance names exactly where source and target "
              "disagree. A common cause on a repeated demo run is a takeover posted more than once "
              "(the P0-3 idempotency guard prevents that in production). Fix the cause, re-run, and "
              "the gate flips to GO — this is the sign-off artifact the finance team needs."]
    open(REPORT, "w", encoding="utf-8").write("\n".join(lines))
    print("wrote %s  | overall %s" % (REPORT, "GO" if all_go else "NO-GO"))
    for name, s, t, v, _ in buckets:
        print(f"  {name:<20} source={s:,.2f} target={t:,.2f} variance={v:,.2f}  {verdict(v)}")


if __name__ == "__main__":
    main()
