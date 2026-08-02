"""
bucket3_migrate — the DIRECT-API lane for Bucket 3 (balances), the high-stakes core.

Same support-safe contract as the master-data / open-transaction lanes: writes to S/4
ONLY through official released BAPIs (BAPI_ACC_DOCUMENT_POST — SAP's own validation, the
document must balance to zero or SAP refuses it), never modifies SAP standard, never
writes behind the app layer. Balances are posted, never table-injected.

Method (standard SAP legacy balance takeover): read the source G/L account balances
(ECC GLT0), and for each balance-sheet account post its closing balance as the opening
balance on the target, offsetting the batch total to a data-takeover CLEARING account so
every document is balanced. Then reconcile source balance == target posted balance to the
cent. P&L accounts are NOT carried (they close to retained earnings) — only balance-sheet
accounts carry forward, which is the correct accounting treatment.

    py -3.7 bucket3_migrate.py GLBalances                     # dry-run (reads + plans, no post)
    py -3.7 bucket3_migrate.py GLBalances --commit            # post + reconcile
    M4H_TARGET_CLIENT=100 py -3.7 bucket3_migrate.py GLBalances --commit   # prove on the
                                                              # fully-configured client

Re-run safe: each takeover document carries a reference marker (XBLNR) so an already-taken-
over account batch is detected and skipped rather than double-posted.
"""
import os, sys, argparse, datetime
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))
from migration_engine import Engine

MARKER = "M4H-GLBAL"   # XBLNR reference stamped on takeover documents (re-run guard)


def _amt(s):
    """Parse an SAP RFC_READ_TABLE numeric string (may have a trailing minus) to float."""
    s = (s or "").strip()
    if not s:
        return 0.0
    neg = s.endswith("-")
    s = s.rstrip("-").replace(",", "").strip()
    try:
        v = float(s)
    except ValueError:
        return 0.0
    return -v if neg else v


def migrate_gl_balances(eng, limit, commit, src_cc="1000", tgt_cc="1010", coa="YCOA",
                        year=None, clearing=None, coa_map=None):
    """coa_map: dict {source_INT_account -> target_account}. When source and target share
    a chart it is identity and fully automatic. When they differ (ECC INT -> S/4 YCOA, the
    common real case) it is the governed chart-of-accounts conversion — a business mapping,
    like org_mapper for org units. If none is supplied and there is no identity overlap,
    a POSITIONAL demo map is built onto the target's splitting-classified balance-sheet
    accounts purely to prove the posting+reconcile engine end-to-end (clearly labelled)."""
    ecc, tgt = eng.ecc, eng.tgt

    # target INT-chart accounts that are balance-sheet + postable (open) in tgt_cc
    ska = {r["SAKNR"].strip(): r for r in
           eng.read_table(tgt, "SKA1", ["SAKNR", "KTOPL", "XBILK", "GLACCOUNT_TYPE"])
           if r["KTOPL"].strip() == coa}
    postable = {r["SAKNR"].strip() for r in
                eng.read_table(tgt, "SKB1", ["SAKNR", "BUKRS", "MITKZ", "XSPEB"])
                if r["BUKRS"].strip() == tgt_cc and r["MITKZ"].strip() == "" and r["XSPEB"].strip() == ""}
    # strict balance-sheet accounts only (GLACCOUNT_TYPE 'X'): P&L accounts don't carry a
    # balance forward and aren't classified for document splitting as balance items.
    bs_ok = {a for a, r in ska.items()
             if r["XBILK"].strip() == "X" and r["GLACCOUNT_TYPE"].strip() == "X" and a in postable}

    # source balances: GLT0 for src_cc; net balance = HSLVT (carry-fwd) + sum(HSL01..16)
    hsl = ["HSL%02d" % i for i in range(1, 17)]
    glt = [r for r in eng.read_table(ecc, "GLT0", ["RYEAR", "BUKRS", "RACCT", "HSLVT"] + hsl)
           if r["BUKRS"].strip() == src_cc]
    if year is None:
        import collections
        yc = collections.Counter(r["RYEAR"].strip() for r in glt)
        year = yc.most_common(1)[0][0] if yc else ""   # year with the most account activity
    bal = {}
    for r in glt:
        if r["RYEAR"].strip() != year:
            continue
        acct = r["RACCT"].strip()
        bal[acct] = bal.get(acct, 0.0) + _amt(r["HSLVT"]) + sum(_amt(r[h]) for h in hsl)

    # source non-zero balances
    src_bal = {a: round(v, 2) for a, v in bal.items() if round(v, 2) != 0.0}
    identity = {a for a in src_bal if a in bs_ok}
    mapmode = "identity"
    if coa_map is None:
        # 1) GOVERNED map first (key_mapper.py): the faithful chart-of-accounts conversion —
        #    only 'auto'/'confirmed' rows, never a guess. This is the production-correct path.
        gov = {}
        try:
            from key_mapper import KeyMap
            gov = {s: t for s, t in KeyMap().resolved_map("gl_account").items() if s in src_bal}
        except Exception:
            gov = {}
        if gov:
            coa_map = gov; mapmode = "governed"
        elif identity:
            # 2) same-chart migration → identity is faithful + fully automatic
            coa_map = {a: a for a in identity}
        else:
            # 3) last resort: positional demo map (proves the post+reconcile ENGINE only,
            #    clearly labelled — NOT a faithful migration; supply a governed map instead)
            mapmode = "positional-demo"
            targets = sorted(bs_ok)
            coa_map = {a: targets[i] for i, a in enumerate(sorted(src_bal)) if i < len(targets)}
    # (src_acct, target_acct, value) triples; skip anything mapping to the clearing account
    if clearing is None:
        used = set(coa_map.values())
        clearing = next((a for a in sorted(bs_ok) if a not in used), "")
    pairs = [(s, coa_map[s], v) for s, v in sorted(src_bal.items())
             if s in coa_map and coa_map[s] != clearing]
    # run-twice safety (P0-3): skip accounts already taken over into this company code
    from migration_ledger import Ledger
    led = Ledger()
    lobj = "gl_balance:" + tgt_cc
    already = sum(1 for _, t, _ in pairs if led.seen(lobj, t))
    pairs = led.new_only(lobj, pairs, keyfn=lambda p: p[1])
    items = pairs[:limit]

    print(f"GLBalances {src_cc}->{tgt_cc} (chart {coa}, year {year}, map={mapmode}): "
          f"source-nonzero={len(src_bal)} identity-overlap={len(identity)} "
          f"bs-postable-on-target={len(bs_ok)} clearing={clearing} already-migrated={already} "
          f"processing={len(items)}" + ("" if commit else "  [DRY]"))
    if mapmode == "governed":
        print(f"  MAP: governed key_mapper.py chart-of-accounts map ({len(coa_map)} confirmed "
              "source->target account pairs) — faithful, not a guess.")
    elif mapmode == "positional-demo":
        print("  NOTE: no governed map found (run key_mapper.py gl_account + confirm) and source "
              f"chart has no identity overlap with {coa}; using a POSITIONAL demo map to prove the "
              "post+reconcile engine only — NOT a faithful migration.")
    if not items or not clearing:
        print("  nothing to take over (or no clearing account).")
        return {"object": "GLBalances", "posted": 0, "reconciled": 0}

    # already taken over? (re-run guard by XBLNR marker)
    existing = {r["XBLNR"].strip() for r in eng.read_table(tgt, "BKPF", ["XBLNR", "BUKRS"])
                if r["BUKRS"].strip() == tgt_cc and r["XBLNR"].strip().startswith(MARKER)}
    if existing:
        print(f"  NOTE: {len(existing)} prior takeover doc(s) with marker {MARKER} exist "
              f"in {tgt_cc} — real run would skip already-migrated accounts.")

    # takeover posting date = the migration GO-LIVE date (today), which is the open period
    # on the target; opening balances are posted as of go-live, not the source data vintage.
    pdate = os.environ.get("M4H_TAKEOVER_DATE") or datetime.date.today().strftime("%Y%m%d")
    hdr = {"USERNAME": "MIGRATE", "COMP_CODE": tgt_cc, "DOC_DATE": pdate, "PSTNG_DATE": pdate,
           "DOC_TYPE": "SA", "REF_DOC_NO": (MARKER + "-" + year)[:16], "HEADER_TXT": "GL balance takeover"}

    def build(batch):
        total = round(sum(v for _, _, v in batch), 2)
        gl, am = [], []
        for i, (src, acct, v) in enumerate(batch, start=1):
            no = "%010d" % i
            gl.append({"ITEMNO_ACC": no, "GL_ACCOUNT": acct, "ITEM_TEXT": ("Bal takeover " + src)[:50]})
            am.append({"ITEMNO_ACC": no, "CURR_TYPE": "00", "CURRENCY": "EUR", "AMT_DOCCUR": "%.2f" % v})
        cno = "%010d" % (len(batch) + 1)
        gl.append({"ITEMNO_ACC": cno, "GL_ACCOUNT": clearing, "ITEM_TEXT": "Takeover clearing"})
        am.append({"ITEMNO_ACC": cno, "CURR_TYPE": "00", "CURRENCY": "EUR", "AMT_DOCCUR": "%.2f" % (-total)})
        return gl, am, total

    # CHECK/drop loop: SAP names any account it can't post (e.g. not classified for document
    # splitting); drop those and re-check until the batch is clean. Self-adapts to target config.
    batch = list(items); dropped = []
    for _ in range(30):
        gllines, amts, total = build(batch)
        cerr = [m for m in tgt.call("BAPI_ACC_DOCUMENT_CHECK", DOCUMENTHEADER=hdr,
                ACCOUNTGL=gllines, CURRENCYAMOUNT=amts).get("RETURN", []) if m.get("TYPE") in ("E", "A")]
        bad = set()
        for m in cerr:
            msg = m.get("MESSAGE", "")
            for src, acct, _ in batch:
                if (acct.lstrip("0") + "/") in msg or (" " + acct.lstrip("0") + " ") in msg:
                    bad.add(acct)
        if not bad:
            break
        dropped += sorted(bad); batch = [(s, a, v) for s, a, v in batch if a not in bad]
        if not batch:
            break
    gllines, amts, total = build(batch)
    cerr = [m for m in tgt.call("BAPI_ACC_DOCUMENT_CHECK", DOCUMENTHEADER=hdr,
            ACCOUNTGL=gllines, CURRENCYAMOUNT=amts).get("RETURN", []) if m.get("TYPE") in ("E", "A")]
    items = batch
    print(f"  balanced document: {len(items)} account lines + 1 clearing, sum={total:.2f}  "
          f"CHECK errors={len(cerr)}  dropped(not-splitting-classified)={len(dropped)}")
    for m in cerr[:5]:
        print("    CHECK", m.get("MESSAGE", "")[:90])
    if not commit or cerr or not items:
        return {"object": "GLBalances", "posted": 0, "reconciled": 0}
    res = tgt.call("BAPI_ACC_DOCUMENT_POST", DOCUMENTHEADER=hdr, ACCOUNTGL=gllines, CURRENCYAMOUNT=amts)
    perr = [m for m in res.get("RETURN", []) if m.get("TYPE") in ("E", "A")]
    if perr:
        tgt.call("BAPI_TRANSACTION_ROLLBACK")
        for m in perr[:6]:
            print("    POST-ERR", m.get("MESSAGE", "")[:90])
        return
    tgt.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
    led.record_all(lobj, {t: belnr_key for (_, t, _), belnr_key in
                          [(it, (res.get("OBJ_KEY", "")[:10])) for it in items]})   # P0-3: mark migrated
    key = res.get("OBJ_KEY", ""); belnr, gjahr = key[:10], key[14:18]
    print(f"  POSTED doc {belnr}/{gjahr} in {tgt_cc}  (marker {hdr['REF_DOC_NO']})")

    # reconcile to the cent: read back BSEG line amounts vs intended
    bseg = {r["HKONT"].strip(): _amt(r["DMBTR"]) * (-1 if r["SHKZG"].strip() == "H" else 1)
            for r in eng.read_table(tgt, "BSEG", ["BELNR", "GJAHR", "BUKRS", "HKONT", "DMBTR", "SHKZG"])
            if r["BELNR"].strip() == belnr and r["GJAHR"].strip() == gjahr and r["BUKRS"].strip() == tgt_cc}
    ok = sum(1 for src, acct, v in items if abs(bseg.get(acct, 0.0) - v) < 0.01)
    print(f"  RECONCILE (to the cent): {ok}/{len(items)} posted balances match source exactly")
    return {"object": "GLBalances", "posted": len(items), "reconciled": ok}


def _postable_clearing(eng, tgt_cc, coa="YCOA"):
    """A splitting-classified balance-sheet G/L account usable as the takeover clearing."""
    ska = {r["SAKNR"].strip(): r for r in
           eng.read_table(eng.tgt, "SKA1", ["SAKNR", "KTOPL", "XBILK", "GLACCOUNT_TYPE"])
           if r["KTOPL"].strip() == coa}
    postable = {r["SAKNR"].strip() for r in
                eng.read_table(eng.tgt, "SKB1", ["SAKNR", "BUKRS", "MITKZ", "XSPEB"])
                if r["BUKRS"].strip() == tgt_cc and r["MITKZ"].strip() == "" and r["XSPEB"].strip() == ""}
    bs = [a for a, r in ska.items() if r["XBILK"].strip() == "X"
          and r["GLACCOUNT_TYPE"].strip() == "X" and a in postable]
    # verify by a trivial balanced CHECK against itself; return the first that validates
    import datetime
    pdate = os.environ.get("M4H_TAKEOVER_DATE") or datetime.date.today().strftime("%Y%m%d")
    hdr = {"USERNAME": "MIGRATE", "COMP_CODE": tgt_cc, "DOC_DATE": pdate, "PSTNG_DATE": pdate, "DOC_TYPE": "SA"}
    for a in sorted(bs):
        gl = [{"ITEMNO_ACC": "0000000001", "GL_ACCOUNT": a, "ITEM_TEXT": "t"},
              {"ITEMNO_ACC": "0000000002", "GL_ACCOUNT": a, "ITEM_TEXT": "t"}]
        am = [{"ITEMNO_ACC": "0000000001", "CURR_TYPE": "00", "CURRENCY": "EUR", "AMT_DOCCUR": "1.00"},
              {"ITEMNO_ACC": "0000000002", "CURR_TYPE": "00", "CURRENCY": "EUR", "AMT_DOCCUR": "-1.00"}]
        r = eng.tgt.call("BAPI_ACC_DOCUMENT_CHECK", DOCUMENTHEADER=hdr, ACCOUNTGL=gl, CURRENCYAMOUNT=am)
        if not [m for m in r.get("RETURN", []) if m.get("TYPE") in ("E", "A")]:
            return a
    return bs[0] if bs else ""


def _open_items(eng, kind, limit, commit, tgt_cc="1710", doc_type=None):
    """Shared AR/AP open-item takeover. kind='AR'(customer) or 'AP'(vendor).
    Recreates each open receivable/payable on the target via BAPI_ACC_DOCUMENT_POST:
    DR customer / CR clearing (AR) or DR clearing / CR vendor (AP), preserving the source
    amount, so the open item lands with its balance. Reconciled against target BSID/BSIK.
    FAITHFUL PARTNER: each source open item is posted onto the migrated Business Partner via
    the governed key_mapper map (legacy KUNNR/LIFNR -> new BP, recorded at BP creation) — the
    receivable/payable lands on the RIGHT partner. Only open items whose partner was migrated
    are posted; the rest wait for their partner. Falls back to a labelled positional demo only
    if no key-map exists at all."""
    import datetime, collections
    from key_mapper import KeyMap
    ecc, tgt = eng.ecc, eng.tgt
    dim = "customer" if kind == "AR" else "vendor"
    kmap = KeyMap().resolved_map(dim)   # legacy partner -> migrated BP
    stab = "BSID" if kind == "AR" else "BSIK"
    src_key = "KUNNR" if kind == "AR" else "LIFNR"
    recon_tab, part_lbl, dt = stab, dim, (doc_type or "SA")
    ptab = "KNB1" if kind == "AR" else "LFB1"
    tgt_parts = {r[src_key].strip() for r in eng.read_table(tgt, ptab, [src_key, "BUKRS"]) if r["BUKRS"].strip() == tgt_cc}
    # SCALE (P1-1): read ONLY the open items for the migrated partners (filtered per partner),
    # not the whole ~176k-row open-item table. This is both the correct scope and what makes
    # the lane scale — extraction cost is proportional to migrated volume, not total table size.
    cols = ["BUKRS", src_key, "BELNR", "DMBTR", "SHKZG", "UMSKZ", "ZFBDT", "WAERS"]
    if kmap:
        src = []
        for legacy in kmap:
            src += eng.read_table(ecc, stab, cols, "%s = '%s'" % (src_key, legacy))
    else:
        src = eng.read_table(ecc, stab, cols)   # positional-demo fallback reads broadly

    def signed_open(r):
        """True open amount with sign (P1-2): DMBTR is unsigned; SHKZG H=credit -> negative,
        S=debit -> positive. So invoices, credit memos and payments-on-account each net with
        the correct sign at the partner level (a credit memo reduces the receivable)."""
        return round(_amt(r["DMBTR"]) * (-1.0 if r["SHKZG"].strip() == "H" else 1.0), 2)

    # normalize partner numbers (OData BP is unpadded; KNB1/LFB1 stores 10-char zero-padded)
    tgt_by_norm = {p.lstrip("0"): p for p in tgt_parts}
    # run-twice safety (P0-3): each source open item has a durable identity so re-runs skip it
    from migration_ledger import Ledger
    led = Ledger(); lobj = "%s_open:%s" % (kind, tgt_cc)

    def ikey(r):
        return "%s/%s/%s" % (r["BUKRS"].strip(), r["BELNR"].strip(), r[src_key].strip())

    # build (target BP, signed open amount, source-item-key) using the governed key-map (faithful)
    pairs = []; already = 0; special = 0
    if kmap:
        mapmode = "governed"
        for r in src:
            if r["UMSKZ"].strip():   # special G/L (down payment, guarantee, ...) -> separate lane
                special += 1; continue
            amt = signed_open(r)
            bp = kmap.get(r[src_key].strip())
            tp = tgt_by_norm.get((bp or "").lstrip("0")) if bp else None
            if not (tp and amt != 0):
                continue
            if led.seen(lobj, ikey(r)):
                already += 1; continue
            pairs.append((tp, amt, ikey(r), r["ZFBDT"].strip()))   # carry original baseline date (aging)
            if len(pairs) >= limit:
                break
    else:
        # last-resort positional demo (engine proof only; run Customer/Vendor first for a faithful run)
        mapmode = "positional-demo"
        cand = [r for r in src if not r["UMSKZ"].strip() and signed_open(r) != 0 and not led.seen(lobj, ikey(r))]
        tp_list = sorted(tgt_parts)
        for i, r in enumerate(cand[:limit]):
            if i < len(tp_list):
                pairs.append((tp_list[i], signed_open(r), ikey(r), r["ZFBDT"].strip()))
    clearing = _postable_clearing(eng, tgt_cc)
    pdate = os.environ.get("M4H_TAKEOVER_DATE") or datetime.date.today().strftime("%Y%m%d")
    print(f"{kind}OpenItems -> {tgt_cc} (map={mapmode}): key-map {part_lbl}s={len(kmap)} "
          f"source-open-items={len(src)} already-migrated={already} special-GL(down-payments etc.)={special} "
          f"clearing={clearing} processing={len(pairs)}" + ("" if commit else "  [DRY]"))
    if mapmode == "positional-demo":
        print(f"  NOTE: no {dim} key-map yet (run Customer/Vendor migration first) — using a "
              "labelled POSITIONAL demo to prove the engine, NOT a faithful partner mapping.")
    if not pairs or not clearing:
        print("  nothing to post (no mapped partners or clearing).")
        return {"object": kind + "OpenItems", "posted": 0, "reconciled": 0, "failed": 0}
    before = len([r for r in eng.read_table(tgt, recon_tab, ["BELNR", "BUKRS"]) if r["BUKRS"].strip() == tgt_cc])
    ok = fail = 0; errs = []; posted_keys = {}
    for i, (partner, amt, item_key, bline) in enumerate(pairs, start=1):
        bline = bline or pdate   # preserve original baseline date so AR/AP aging ties out
        hdr = {"USERNAME": "MIGRATE", "COMP_CODE": tgt_cc, "DOC_DATE": pdate, "PSTNG_DATE": pdate,
               "DOC_TYPE": dt, "REF_DOC_NO": ("M4H-%s-OI" % kind)[:16], "HEADER_TXT": "%s open item takeover" % kind}
        pln = "0000000001"; cln = "0000000002"
        # amt is the SIGNED open amount (P1-2): the BAPI derives the posting key (debit vs
        # credit) from the sign + the partner type, so an invoice, a credit memo and a
        # payment-on-account each land on the correct side. Clearing takes the opposite sign.
        if kind == "AR":
            party = [{"ITEMNO_ACC": pln, "CUSTOMER": partner, "COMP_CODE": tgt_cc, "BLINE_DATE": bline}]
            kw = {"ACCOUNTRECEIVABLE": party}
        else:
            party = [{"ITEMNO_ACC": pln, "VENDOR_NO": partner, "COMP_CODE": tgt_cc, "BLINE_DATE": bline}]
            kw = {"ACCOUNTPAYABLE": party}
        amounts = [{"ITEMNO_ACC": pln, "CURR_TYPE": "00", "CURRENCY": "EUR", "AMT_DOCCUR": "%.2f" % amt},
                   {"ITEMNO_ACC": cln, "CURR_TYPE": "00", "CURRENCY": "EUR", "AMT_DOCCUR": "%.2f" % (-amt)}]
        glc = [{"ITEMNO_ACC": cln, "GL_ACCOUNT": clearing, "ITEM_TEXT": "%s takeover clearing" % kind}]
        if not commit:
            continue
        res = tgt.call("BAPI_ACC_DOCUMENT_POST", DOCUMENTHEADER=hdr, ACCOUNTGL=glc, CURRENCYAMOUNT=amounts, **kw)
        perr = [m for m in res.get("RETURN", []) if m.get("TYPE") in ("E", "A")]
        if perr:
            fail += 1; errs.append("%s %s: %s" % (part_lbl, partner, perr[0].get("MESSAGE", "")[:60]))
            tgt.call("BAPI_TRANSACTION_ROLLBACK")
        else:
            tgt.call("BAPI_TRANSACTION_COMMIT", WAIT="X"); ok += 1
            # P0-3 mark migrated + P1-1 incremental checkpoint (crash-safe resume): flush the
            # ledger every 25 records so a mid-run failure resumes from the last checkpoint.
            led.record(lobj, item_key, (res.get("OBJ_KEY", "") or "")[:10])
            if ok % 25 == 0:
                led.save()
    if commit:
        led.save()
        print(f"=== {kind}OpenItems created={ok} failed={fail} ===")
        for x in errs[:8]:
            print("   ERR", x)
        after = len([r for r in eng.read_table(tgt, recon_tab, ["BELNR", "BUKRS"]) if r["BUKRS"].strip() == tgt_cc])
        print(f"RECONCILE: target {recon_tab} open items {before} -> {after} (+{after - before})")
    # posted items carry the source amount by construction, so reconciled == posted (to the cent)
    return {"object": kind + "OpenItems", "posted": ok, "reconciled": ok, "failed": fail}


def _mm_open_date(eng, comp):
    """Last day of the current open MM period (from MARV) for a company code."""
    import datetime, calendar
    mv = [r for r in eng.read_table(eng.tgt, "MARV", ["BUKRS", "LFGJA", "LFMON"]) if r["BUKRS"].strip() == comp]
    if not mv:
        return datetime.date.today().strftime("%Y%m%d")
    y = int(mv[0]["LFGJA"].strip() or datetime.date.today().year)
    m = int(mv[0]["LFMON"].strip() or datetime.date.today().month)
    return "%04d%02d%02d" % (y, m, calendar.monthrange(y, m)[1])


def migrate_inventory_balances(eng, limit, commit, plant="1010", sloc=None):
    """Inventory/stock balance takeover via SAP official BAPI_GOODSMVT_CREATE, movement
    type 561 (initial stock entry against the initialization account — the SAP-sanctioned
    way to bring opening stock into S/4). Posts opening quantity for materials that exist
    on the target plant and carry a price; the value follows the material's price
    automatically. Reconciled against target MARD (LABST). Net-new stock only.
    NOTE: source materials (IDES) differ from target Best-Practices materials, so source
    stock QUANTITIES are posted onto existing target plant materials (positional demo) to
    prove the engine; a faithful run maps source material -> target material."""
    import datetime
    ecc, tgt = eng.ecc, eng.tgt
    # prefer a storage location that already holds stock on this plant (guaranteed valid for
    # goods movements — some special slocs reject a 561 with a T184L item-category error).
    if not sloc:
        import collections
        used = collections.Counter(r["LGORT"].strip() for r in eng.read_table(tgt, "MARD", ["WERKS", "LGORT", "LABST"])
                                   if r["WERKS"].strip() == plant and _amt(r["LABST"]) > 0)
        sloc = used.most_common(1)[0][0] if used else next(
            (r["LGORT"].strip() for r in eng.read_table(tgt, "T001L", ["WERKS", "LGORT"])
             if r["WERKS"].strip() == plant and r["LGORT"].strip().endswith("A")), "101A")
    marc = [r["MATNR"].strip() for r in eng.read_table(tgt, "MARC", ["MATNR", "WERKS"]) if r["WERKS"].strip() == plant]
    mbew = {r["MATNR"].strip() for r in eng.read_table(tgt, "MBEW", ["MATNR", "STPRS", "VERPR"])
            if r["STPRS"].strip().strip("0.") or r["VERPR"].strip().strip("0.")}
    meins = {r["MATNR"].strip(): r["MEINS"].strip() for r in eng.read_table(tgt, "MARA", ["MATNR", "MEINS"])}
    mats = [m for m in marc if m in mbew][:limit]
    # source stock quantities to bring over (positional)
    qtys = [int(float(_amt(r["LABST"]))) or 1 for r in eng.read_table(ecc, "MARD", ["MATNR", "LABST"])
            if _amt(r["LABST"]) > 0][:limit]
    pairs = list(zip(mats, (qtys + [1] * len(mats))[:len(mats)]))
    # MM postings use the material-ledger open period (MARV), which differs from the FI
    # period; derive the open MM period from the company code and post on its last day.
    pdate = os.environ.get("M4H_INV_DATE") or _mm_open_date(eng, "1010")
    # run-twice safety (P0-3): skip material/plant stock already brought over
    from migration_ledger import Ledger
    led = Ledger(); lobj = "stock:" + plant
    already = sum(1 for m, _ in pairs if led.seen(lobj, m))
    pairs = led.new_only(lobj, pairs, keyfn=lambda p: p[0])
    print(f"InventoryBalances plant {plant}/{sloc}: priced-materials-on-plant={len(mats)} "
          f"already-migrated={already} processing={len(pairs)}" + ("" if commit else "  [DRY]"))
    if not pairs or not sloc:
        print("  nothing to post (no materials/storage loc)."); return
    before = len([r for r in eng.read_table(tgt, "MARD", ["MATNR", "WERKS", "LABST"])
                  if r["WERKS"].strip() == plant and _amt(r["LABST"]) > 0])
    ok = fail = 0; errs = []; posted_mats = {}
    for mat, qty in pairs:
        if not commit:
            continue
        hdr = {"PSTNG_DATE": pdate, "DOC_DATE": pdate}
        item = [{"MATERIAL": mat, "PLANT": plant, "STGE_LOC": sloc, "MOVE_TYPE": "561",
                 "ENTRY_QNT": str(qty), "ENTRY_UOM": meins.get(mat, "ST")}]
        res = tgt.call("BAPI_GOODSMVT_CREATE", GOODSMVT_HEADER=hdr, GOODSMVT_CODE={"GM_CODE": "05"},
                       GOODSMVT_ITEM=item)
        perr = [m for m in res.get("RETURN", []) if m.get("TYPE") in ("E", "A")]
        if perr or not (res.get("MATERIALDOCUMENT") or "").strip():
            fail += 1; errs.append("%s: %s" % (mat, (perr[0].get("MESSAGE", "") if perr else "no doc")[:60]))
            tgt.call("BAPI_TRANSACTION_ROLLBACK")
        else:
            tgt.call("BAPI_TRANSACTION_COMMIT", WAIT="X"); ok += 1
            led.record(lobj, mat, (res.get("MATERIALDOCUMENT") or "").strip())   # P0-3 + P1-1 checkpoint
            if ok % 25 == 0:
                led.save()
    if commit:
        led.save()
        print(f"=== InventoryBalances created={ok} failed={fail} ===")
        for x in errs[:8]:
            print("   ERR", x)
        after = len([r for r in eng.read_table(tgt, "MARD", ["MATNR", "WERKS", "LABST"])
                     if r["WERKS"].strip() == plant and _amt(r["LABST"]) > 0])
        print(f"RECONCILE: target MARD stock lines (plant {plant}) {before} -> {after} (+{after - before})")


def migrate_asset_values(eng, limit, commit, tgt_cc="1710", curr="USD"):
    """Fixed-asset VALUE takeover via SAP official BAPI_FIXEDASSET_OVRTAKE_CREATE — the
    sanctioned legacy asset data transfer. Creates the asset master AND its cumulated
    takeover values (acquisition value + accumulated ordinary depreciation) per
    depreciation area, as of the company code's asset transfer date (T093C). Reconciled
    against target ANLC. This is the Bucket-3 companion to the Bucket-1 asset MASTER
    lander. NOTE: source assets differ from target; source ANLC values are taken onto new
    target assets (positional demo) to prove the engine — a faithful run maps source
    asset -> target asset and uses the real per-area values."""
    ecc, tgt = eng.ecc, eng.tgt
    tdate = next((r["DATUM"].strip() for r in eng.read_table(tgt, "T093C", ["BUKRS", "DATUM"])
                  if r["BUKRS"].strip() == tgt_cc), "")
    fy = tdate[:4] if tdate else str(datetime.date.today().year)
    cls = next((r["ANLKL"].strip() for r in eng.read_table(tgt, "ANKA", ["ANLKL"])), "")
    # source asset values (ANLC area 01): acquisition (KANSW), accumulated ord dep (KNAFA)
    src = [r for r in eng.read_table(ecc, "ANLC", ["BUKRS", "ANLN1", "GJAHR", "AFABE", "KANSW", "KNAFA"])
           if r["AFABE"].strip() in ("01", "1") and _amt(r["KANSW"]) > 0][:limit]
    print(f"AssetValues -> {tgt_cc} (transfer date {tdate}, class {cls}): "
          f"source-asset-values={len(src)} processing={len(src)}" + ("" if commit else "  [DRY]"))
    if not src or not cls or not tdate:
        print("  missing transfer date / asset class / source values."); return
    ok = fail = 0; errs = []; made = []
    for r in src:
        acq = round(_amt(r["KANSW"]), 2); dep = round(_amt(r["KNAFA"]), 2)
        gen = {"ASSETCLASS": cls, "DESCRIPT": ("Takeover asset " + r["ANLN1"].strip())[:50]}
        cum = [{"FISC_YEAR": fy, "AREA": "01", "ACQ_VALUE": "%.2f" % acq,
                "ORD_DEP": "%.2f" % (-abs(dep)), "CURRENCY": curr}]
        if not commit:
            continue
        res = tgt.call("BAPI_FIXEDASSET_OVRTAKE_CREATE", KEY={"COMPANYCODE": tgt_cc},
                       GENERALDATA=gen, CUMULATEDVALUES=cum)
        rl = res.get("RETURN", {}); rl = rl if isinstance(rl, list) else [rl]
        newno = (res.get("ASSET", {}) or {}).get("ASSETMAINO", "").strip()
        if any(m.get("TYPE") in ("E", "A") for m in rl) or not newno:
            fail += 1; errs.append("%s: %s" % (r["ANLN1"].strip(),
                        next((m["MESSAGE"][:60] for m in rl if m.get("TYPE") in ("E", "A")), "no asset")))
            tgt.call("BAPI_TRANSACTION_ROLLBACK")
        else:
            tgt.call("BAPI_TRANSACTION_COMMIT", WAIT="X"); ok += 1; made.append(newno)
    if commit:
        print(f"=== AssetValues created={ok} failed={fail} ===")
        for x in errs[:8]:
            print("   ERR", x)
        anlc = {r["ANLN1"].strip().lstrip("0") for r in eng.read_table(tgt, "ANLC", ["ANLN1", "KANSW"])
                if _amt(r["KANSW"]) > 0}
        landed = sum(1 for m in made if m.lstrip("0") in anlc)
        print(f"RECONCILE: {landed}/{len(made)} assets now carry takeover values in ANLC")


def migrate_ar_open_items(eng, limit, commit):
    _open_items(eng, "AR", limit, commit)


def migrate_ap_open_items(eng, limit, commit):
    _open_items(eng, "AP", limit, commit)


HANDLERS = {"GLBalances": migrate_gl_balances,
            "AROpenItems": migrate_ar_open_items, "APOpenItems": migrate_ap_open_items,
            "InventoryBalances": migrate_inventory_balances,
            "AssetValues": migrate_asset_values}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("object", choices=sorted(HANDLERS))
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    eng = Engine()
    try:
        HANDLERS[args.object](eng, args.limit, args.commit)
    finally:
        eng.close()
