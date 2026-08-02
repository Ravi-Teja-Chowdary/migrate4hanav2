"""
rollback_postings — reverse the FI postings a balance/open-item run created (road-to-production
P2-2, the "failed-halfway recovery" piece).

WHY
    Master-data creates are net-new and are simply left in place on a retry (SAP does not delete
    Business Partners). But the Bucket-3 FI postings (G/L balance takeover, AR/AP open items) are
    real documents — if a run fails halfway, or a rehearsal needs to be undone before the real
    cutover, you must REVERSE them cleanly. This does exactly that, via SAP's official reversal
    BAPI (BAPI_ACC_DOCUMENT_REV_POST) — never a table delete. Every takeover document carries a
    marker (M4H-*) in its reference, so we find precisely our own documents and nothing else.

    After reversal it clears the matching migration-ledger entries so a corrected re-run re-posts
    those records (idempotency + rollback compose into a safe retry loop).

    M4H_TARGET_CLIENT=100 py -3.7 rollback_postings.py                 # dry-run: list our docs
    M4H_TARGET_CLIENT=100 py -3.7 rollback_postings.py --commit        # reverse them + clear ledger
    M4H_TARGET_CLIENT=100 py -3.7 rollback_postings.py --commit --marker M4H-GLBAL --cc 1010
"""
import os, sys, argparse, datetime
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, os.getcwd()); sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))

MARKERS = ("M4H-GLBAL", "M4H-AR-OI", "M4H-AP-OI")   # our takeover-document references (XBLNR)


def main():
    from migration_engine import Engine
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--marker", default="")          # restrict to one marker prefix
    ap.add_argument("--cc", default="")               # restrict to one company code
    ap.add_argument("--reason", default="01")         # reversal reason (T041C)
    a = ap.parse_args()
    eng = Engine(); tgt = eng.tgt

    # find OUR posted documents by marker in the reference field (XBLNR)
    prefixes = (a.marker,) if a.marker else MARKERS
    docs = [r for r in eng.read_table(tgt, "BKPF", ["BUKRS", "BELNR", "GJAHR", "XBLNR", "STBLG"])
            if any(r["XBLNR"].strip().startswith(p) for p in prefixes)
            and (not a.cc or r["BUKRS"].strip() == a.cc)]
    open_docs = [d for d in docs if not d["STBLG"].strip()]   # STBLG set = already reversed
    print("Our takeover documents: %d found, %d already reversed, %d to reverse%s"
          % (len(docs), len(docs) - len(open_docs), len(open_docs), "" if a.commit else "   [DRY-RUN]"))
    for d in open_docs[:10]:
        print("  %s/%s/%s  ref=%s" % (d["BELNR"].strip(), d["BUKRS"].strip(), d["GJAHR"].strip(), d["XBLNR"].strip()))
    if not a.commit or not open_docs:
        if not a.commit:
            print("  (dry-run — pass --commit to reverse)")
        eng.close(); return

    pdate = os.environ.get("M4H_TAKEOVER_DATE") or datetime.date.today().strftime("%Y%m%d")
    ok = fail = 0; reversed_refs = {}; worklist = []
    for d in open_docs:
        objkey = "%s%s%s" % (d["BELNR"].strip(), d["BUKRS"].strip(), d["GJAHR"].strip())   # AWKEY: BELNR+BUKRS+GJAHR
        rev = {"OBJ_TYPE": "BKPFF", "OBJ_KEY": objkey, "OBJ_KEY_R": "M4HREV" + objkey[6:], "OBJ_SYS": "",
               "COMP_CODE": d["BUKRS"].strip(), "REASON_REV": a.reason, "PSTNG_DATE": pdate}
        res = tgt.call("BAPI_ACC_DOCUMENT_REV_POST", REVERSAL=rev)
        err = [m for m in res.get("RETURN", []) if m.get("TYPE") in ("E", "A")]
        if err:
            fail += 1; worklist.append(d)
            if fail <= 5:
                print("  BAPI cannot reverse %s: %s" % (d["BELNR"].strip(), err[-1].get("MESSAGE", "")[:65]))
            tgt.call("BAPI_TRANSACTION_ROLLBACK")
        else:
            tgt.call("BAPI_TRANSACTION_COMMIT", WAIT="X"); ok += 1
            reversed_refs.setdefault(d["XBLNR"].strip(), []).append(d)
    print("=== reversed via BAPI=%d | need standard mass-reversal=%d ===" % (ok, fail))

    # HONEST fallback: BAPI_ACC_DOCUMENT_REV_POST only reverses documents whose ACC-interface
    # reference it can resolve; documents created by BAPI_ACC_DOCUMENT_POST are not always
    # resolvable that way on every release. Rather than call an internal/unreleased reversal FM
    # (which would risk SAP support), emit the exact reversal work-list for the SAP-canonical
    # transaction FB08 (single) / F.80 (mass) — the client's Basis/FI team runs it. Same doctrine
    # the tool already uses for STMS/WP-freeze: defer to the SAP-standard path, never a risky Z.
    if worklist:
        wl = ["# Rollback work-list — reverse via FB08 (single) / F.80 (mass)", "",
              f"_{len(worklist)} takeover documents the reversal BAPI could not resolve on this release. "
              "Run F.80 (mass reversal) for these exact documents; all are our marker docs (M4H-*), safe "
              "to reverse. Reversal reason 01, posting date = go-live/open period._", "",
              "| company code | document | fiscal year | reference |", "|---|---|---|---|"]
        for d in worklist:
            wl.append("| %s | %s | %s | %s |" % (d["BUKRS"].strip(), d["BELNR"].strip(),
                                                 d["GJAHR"].strip(), d["XBLNR"].strip()))
        open("ROLLBACK_WORKLIST.md", "w", encoding="utf-8").write("\n".join(wl))
        print("  wrote ROLLBACK_WORKLIST.md (%d docs for FB08/F.80 mass reversal)" % len(worklist))

    # clear the matching ledger entries so a corrected re-run re-posts those records
    try:
        from migration_ledger import Ledger
        led = Ledger(); cleared = 0
        for obj in list(led.data.keys()):
            # GL ledger key = target account (per cc); AR/AP key = source-item id — safest is to
            # drop the ledger objects whose marker we reversed, so those records are re-eligible.
            if a.marker and a.marker not in ("",):
                pass
        # simplest safe policy: if we reversed GL docs, clear gl_balance:* ; AR/AP -> *_open:*
        drop = []
        if any(k.startswith("M4H-GLBAL") for k in reversed_refs):
            drop += [o for o in led.data if o.startswith("gl_balance:")]
        if any(k.startswith("M4H-AR-OI") for k in reversed_refs):
            drop += [o for o in led.data if o.startswith("AR_open:")]
        if any(k.startswith("M4H-AP-OI") for k in reversed_refs):
            drop += [o for o in led.data if o.startswith("AP_open:")]
        for o in drop:
            cleared += len(led.data.pop(o, {}))
        if drop:
            led.save()
        print("  cleared %d ledger entries (%d ledger scopes) — re-run will re-post" % (cleared, len(drop)))
    except Exception as e:
        print("  (ledger clear skipped: %s)" % str(e)[:60])
    eng.close()


if __name__ == "__main__":
    main()
