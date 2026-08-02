"""
preflight_all — one comprehensive readiness + data-health report BEFORE any migration
(road-to-production P1-3).

THE PROBLEM IT SOLVES
    Dirty source data and target-config gaps were being discovered reactively — one BAPI
    error at a time, mid-run ("bank key must be length 07", "posting period not open",
    "account not classified for document splitting"). Production needs the opposite: a single
    pre-run scan that finds every blocker first and hands the client a fix-list, so the real
    run is boring. This is that scan. It is **read-only** (never writes to SAP).

    It rolls up three things the whole session proved matter:
      1. TARGET CONFIG readiness — the customizing a migration depends on (posting periods,
         document splitting, cost elements, FI-AA transfer phase, plant/sales-extended
         materials, notification types).
      2. SOURCE DATA health — samples the source for values SAP will reject (e.g. bank keys
         that fail the target's country length rule).
      3. MAPPING readiness — how many governed decisions still open in key_mapper / org_mapper.

    Each check is READY / WARN / BLOCKED with a concrete fix. BLOCKED = a real run will fail
    or be incomplete until it's resolved.

    M4H_TARGET_CLIENT=100 py -3.7 preflight_all.py     # writes PREFLIGHT.md
"""
import os, sys, datetime, collections
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, os.getcwd()); sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))

REPORT = "PREFLIGHT.md"


def main():
    from migration_engine import Engine
    client = os.environ.get("M4H_TARGET_CLIENT", "200")
    eng = Engine(); ecc, tgt = eng.ecc, eng.tgt
    checks = []   # (bucket, name, status, detail, fix)

    def add(bucket, name, ok_cond, detail, fix, warn_cond=False):
        st = "READY" if ok_cond else ("WARN" if warn_cond else "BLOCKED")
        checks.append((bucket, name, st, detail, "" if ok_cond else fix))

    def n(conn, tab, fields, where=""):
        try:
            return len(eng.read_table(conn, tab, fields, where))
        except Exception:
            return 0

    # ── TARGET CONFIG ────────────────────────────────────────────────────────────
    # material extension (gates all logistics/SD open docs + inventory)
    marc = n(tgt, "MARC", ["MATNR"]); mvke = n(tgt, "MVKE", ["MATNR"])
    add("Master data / Logistics", "Materials extended to plants (MARC)", marc > 10,
        f"{marc} plant-extended materials on target",
        "Migrate materials COMPLETE (basic+plant+sales) via the cockpit 'Product' object; "
        "plant/stock/PO/production docs cannot reference basic-only materials.")
    add("Sales", "Materials with sales views (MVKE)", mvke > 10,
        f"{mvke} sales-view materials on target",
        "Load material sales views (complete-material migration) before sales orders / AR by material.")
    # chart of accounts + document splitting (gates GL balances)
    ycoa = n(tgt, "SKA1", ["SAKNR"], "KTOPL = 'YCOA'")
    add("Balances", "Operating chart of accounts present (YCOA)", ycoa > 10,
        f"{ycoa} accounts in YCOA", "Confirm the target operating chart before G/L balance takeover.")
    ce = n(tgt, "CSKB", ["KSTAR"], "KOKRS = 'A000' AND KATYP = '01'")
    add("Balances / CO", "Primary cost elements in A000", ce > 0,
        f"{ce} primary cost elements", "Create/activate cost elements before cost-center account assignment.")
    # FI-AA legacy transfer phase (gates asset value takeover)
    aa = [r for r in eng.read_table(tgt, "T093C", ["BUKRS", "XANUEB", "DATUM"])]
    aa_open = [r["BUKRS"].strip() for r in aa if r["XANUEB"].strip() != "X"]
    add("Balances / Assets", "FI-AA legacy transfer phase open", bool(aa_open),
        f"transfer-open company codes: {aa_open or '(none)'}",
        "Open the asset data-transfer phase (OAAQ) before asset VALUE takeover; it is closed here.",
        warn_cond=True)
    # posting periods (spot: can we post to cocode 1010 today?) — informational via T001B presence
    t001b = n(tgt, "T001B", ["BUKRS"])
    add("Balances", "Posting-period variants configured (T001B)", t001b > 0,
        f"{t001b} posting-period ranges", "Open the go-live posting period for each company code.")
    # notification types (bucket 2)
    tq = n(tgt, "TQ80", ["QMART"])
    add("Open transactions", "Notification types configured (TQ80)", tq > 0,
        f"{tq} notification types", "Define notification types before notification migration.")

    # ── SOURCE DATA HEALTH ───────────────────────────────────────────────────────
    # bank keys that will fail a length rule (sample): CA/AU keys are a known offender
    banks = eng.read_table(ecc, "BNKA", ["BANKS", "BANKL"], "LOEVM = ''")
    bad_bank = [b for b in banks if b["BANKS"].strip() in ("CA", "AU") and len(b["BANKL"].strip()) not in (7, 9)]
    add("Master data", "Bank keys pass target length rules", len(bad_bank) == 0,
        f"{len(bad_bank)} bank keys (CA/AU) may violate the target country length rule",
        "Set T005-BNKEY external for the affected countries (governed switch) or cleanse the keys.",
        warn_cond=len(bad_bank) < 50)
    # customers/vendors missing name (would post a blank BP)
    kna1 = eng.read_table(ecc, "KNA1", ["KUNNR", "NAME1"])
    noname = sum(1 for r in kna1 if not r["NAME1"].strip())
    add("Master data", "Customers have a name", noname == 0,
        f"{noname} of {len(kna1)} customers have no NAME1",
        "Cleanse blank customer names before BP creation.", warn_cond=noname < 20)

    # ── MAPPING READINESS ────────────────────────────────────────────────────────
    try:
        from key_mapper import KeyMap
        km = KeyMap()
        for dim in ("gl_account", "customer", "vendor", "material"):
            ents = km.dims.get(dim, {})
            dec = sum(1 for e in ents.values() if not e.get("target"))
            add("Mapping", f"Key map '{dim}' decisions resolved", dec == 0 or not ents,
                f"{len(ents)} keys, {dec} still need a decision" if ents else "not generated yet",
                f"Run key_mapper.py {dim} and confirm the open decisions in KEY_MAPPING.md.",
                warn_cond=True)
    except Exception:
        pass
    if os.path.exists("org_mapper.json"):
        import json
        od = json.load(open("org_mapper.json")).get("dimensions", {})
        dec = sum(1 for dim in od.values() for e in dim.values() if e.get("confidence") == "decision" and not e.get("confirmed"))
        add("Mapping", "Org-unit map decisions resolved", dec == 0,
            f"{dec} org-unit decisions open", "Resolve org decisions in ORG_MAPPING.md.", warn_cond=True)

    eng.close()

    # ── report ───────────────────────────────────────────────────────────────────
    c = collections.Counter(s for _, _, s, _, _ in checks)
    lines = [f"# Migration preflight — target client {client}", "",
             f"_Generated {datetime.datetime.now():%Y-%m-%d %H:%M}. Read-only. Resolve every BLOCKED "
             "item (and review WARNs) before the real run — this turns mid-run failures into a fix-list._", "",
             f"**{c.get('READY',0)} ready · {c.get('WARN',0)} warnings · {c.get('BLOCKED',0)} blocked**", "",
             "| bucket | check | status | detail | fix if not ready |", "|---|---|---|---|---|"]
    mark = {"READY": "✅ READY", "WARN": "🟡 WARN", "BLOCKED": "🔴 BLOCKED"}
    order = {"BLOCKED": 0, "WARN": 1, "READY": 2}
    for bucket, name, st, detail, fix in sorted(checks, key=lambda r: (order[r[2]], r[0])):
        lines.append(f"| {bucket} | {name} | {mark[st]} | {detail} | {fix} |")
    lines += ["", "> A **BLOCKED** check means a real migration will fail or be incomplete until it is "
              "resolved (customizing the client's Basis/functional team does, or a source-data cleanse). "
              "A **WARN** is a governed decision or a partial-data situation to confirm. All checks are "
              "read-only; nothing here changes the systems."]
    open(REPORT, "w", encoding="utf-8").write("\n".join(lines))
    print("wrote %s | %d ready, %d warn, %d blocked" % (REPORT, c.get("READY", 0), c.get("WARN", 0), c.get("BLOCKED", 0)))
    for bucket, name, st, detail, fix in sorted(checks, key=lambda r: (order[r[2]], r[0])):
        if st != "READY":
            print("  [%s] %s — %s" % (st, name, detail))


if __name__ == "__main__":
    main()
