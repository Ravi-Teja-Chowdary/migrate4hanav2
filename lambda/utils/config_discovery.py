"""
config_discovery — auto-discover target org units & accounts so the tool adapts to ANY
S/4 landscape, not just the appliance it was built on.

Loaders need a coherent set of target config (company code, purchasing org, plant, sales
area, reconciliation accounts, clearing/expense GLs, cost/profit center). Hard-coding them
ties the tool to one system. This reads VALID values from the target at runtime — picking
the most operational company (most customers), then deriving everything for THAT company so
the set is internally consistent. Precedence per field: env override > discovered > fallback.
Read-only; every lookup degrades gracefully so discovery never breaks a run.
"""
from __future__ import annotations
import os
import time
from collections import Counter

# Last-resort fallbacks (the appliance we were built on) if a lookup returns nothing.
_FB = {"COMP_CODE": "1710", "CONTROLLING_AREA": "A000", "PURCH_ORG": "1710", "PLANT": "1710",
       "PUR_GROUP": "001", "DOC_TYPE": "NB", "PO_UNIT": "EA", "MATL_GROUP": "L001",
       "GL_ACCOUNT": "0052513000", "COSTCENTER": "0017101601", "CLEARING_GL": "0023007000",
       "PROFIT_CTR": "YB600", "CUST_RECON": "0012100100", "VEND_RECON": "0021102200",
       "SALES_ORG": "1710", "DISTR_CHAN": "10", "DIVISION": "00"}


def _rows(conn, table, fields, where="", n=100000):
    try:
        r = conn.call("RFC_READ_TABLE", QUERY_TABLE=table, DELIMITER="|",
                      OPTIONS=[{"TEXT": where}] if where else [],
                      FIELDS=[{"FIELDNAME": f} for f in fields], ROWCOUNT=n)
        cols = [f["FIELDNAME"] for f in r.get("FIELDS", [])]
        return [dict(zip(cols, [x.strip() for x in d["WA"].split("|")])) for d in r.get("DATA", [])]
    except Exception:
        return []


def _first(conn, table, field, where="", n=50):
    rs = _rows(conn, table, [field], where, n)
    return rs[0][field] if rs else None


def _pick_gl(conn, ktopl, comp, primary):
    """A GL valid for DIRECT posting in `comp`: a primary-cost (type P) expense account for
    PO items, or a balance-sheet account for the FI clearing offset."""
    postable = {r["SAKNR"] for r in _rows(conn, "SKB1", ["SAKNR", "MITKZ", "XSPEB"],
                                          "BUKRS = '%s'" % comp)
                if r.get("MITKZ", "") == "" and r.get("XSPEB", "") == ""}
    if primary:
        cand = [r["SAKNR"] for r in _rows(conn, "SKA1", ["SAKNR", "GLACCOUNT_TYPE"],
                                          "KTOPL = '%s' AND GLACCOUNT_TYPE = 'P'" % ktopl)]
    else:
        cand = [r["SAKNR"] for r in _rows(conn, "SKA1", ["SAKNR", "XBILK"],
                                          "KTOPL = '%s' AND XBILK = 'X'" % ktopl)]
    for s in cand:
        if s in postable:
            return s
    return None


def _probe_po(conn, comp, dtype, vend, porg, pgrp, plant, mgrp, gl, cc, day) -> bool:
    """Test-post a 1-line account-assigned PO with this expense GL, then ROLL BACK.
    Returns True only if it would actually post — the real test of PO-usability."""
    try:
        hdr = {"COMP_CODE": comp, "DOC_TYPE": dtype, "VENDOR": vend, "PURCH_ORG": porg,
               "PUR_GROUP": pgrp, "DOC_DATE": day, "CURRENCY": "USD"}
        item = [{"PO_ITEM": "00010", "SHORT_TEXT": "M4H probe", "PLANT": plant, "QUANTITY": "1",
                 "PO_UNIT": "EA", "NET_PRICE": "1", "ACCTASSCAT": "K", "MATL_GROUP": mgrp}]
        itemx = [{"PO_ITEM": "00010", "SHORT_TEXT": "X", "PLANT": "X", "QUANTITY": "X",
                  "PO_UNIT": "X", "NET_PRICE": "X", "ACCTASSCAT": "X", "MATL_GROUP": "X"}]
        acct = [{"PO_ITEM": "00010", "SERIAL_NO": "01", "GL_ACCOUNT": gl, "COSTCENTER": cc, "QUANTITY": "1"}]
        acctx = [{"PO_ITEM": "00010", "SERIAL_NO": "01", "GL_ACCOUNT": "X", "COSTCENTER": "X", "QUANTITY": "X"}]
        res = conn.call("BAPI_PO_CREATE1", POHEADER=hdr, POHEADERX={k: "X" for k in hdr},
                        POITEM=item, POITEMX=itemx, POACCOUNT=acct, POACCOUNTX=acctx)
        ret = res.get("RETURN", [])
        ret = ret if isinstance(ret, list) else [ret]
        ok = bool((res.get("EXPPURCHASEORDER") or "").strip()) and not [m for m in ret if m.get("TYPE") in ("E", "A")]
    except Exception:
        ok = False
    try:
        conn.call("BAPI_TRANSACTION_ROLLBACK")
    except Exception:
        pass
    return ok


def _discover_po_gl(conn, comp, kokrs, porg, plant, pgrp, dtype, mgrp, cc):
    """A primary cost element valid in `comp` that ACTUALLY posts in a PO (validated by a
    rolled-back probe — config flags don't guarantee it; default-range cost elements fail)."""
    day = time.strftime("%Y%m%d")
    postable = {r["SAKNR"] for r in _rows(conn, "SKB1", ["SAKNR", "MITKZ", "XSPEB"], "BUKRS = '%s'" % comp)
                if r.get("MITKZ", "") == "" and r.get("XSPEB", "") == ""}
    cands = [r["KSTAR"] for r in _rows(conn, "CSKB", ["KSTAR", "KATYP", "DATBI", "DATAB"],
                                       "KOKRS = '%s' AND KATYP = '01'" % kokrs)
             if r.get("DATAB", "00000000") <= day <= r.get("DATBI", "99991231") and r["KSTAR"] in postable]
    cands.sort(key=lambda s: (s.startswith("00699"), s))   # real expense accts before default-range
    vend = _first(conn, "LFM1", "LIFNR", "EKORG = '%s'" % porg)
    if not (cands and vend):
        return cands[0] if cands else None
    for gl in cands[:12]:
        if _probe_po(conn, comp, dtype, vend, porg, pgrp, plant, mgrp, gl, cc, day):
            return gl
    return cands[0]


def discover(conn) -> dict:
    """Discover a coherent target config. Returns {po, fi, bp, summary}."""
    env = os.environ.get

    comp = env("M4H_COMP_CODE")
    if not comp:                                   # most operational company = most customers
        knb1 = _rows(conn, "KNB1", ["BUKRS"], "", 5000)
        comp = Counter(r["BUKRS"] for r in knb1).most_common(1)[0][0] if knb1 else None
    comp = comp or _FB["COMP_CODE"]

    ktopl = _first(conn, "T001", "KTOPL", "BUKRS = '%s'" % comp) or "YCOA"
    kokrs = _first(conn, "TKA02", "KOKRS", "BUKRS = '%s'" % comp) or _FB["CONTROLLING_AREA"]

    # reconciliation accounts — from existing masters in this company (guaranteed valid/typed)
    cust_recon = env("M4H_BP_CUST_RECON") or _first(conn, "KNB1", "AKONT", "BUKRS = '%s'" % comp) or _FB["CUST_RECON"]
    vend_recon = env("M4H_BP_VEND_RECON") or _first(conn, "LFB1", "AKONT", "BUKRS = '%s'" % comp) or _FB["VEND_RECON"]

    # sales area — a sales org for this company, then a real (channel, division) from KNVV
    sorg = env("M4H_BP_SALES_ORG") or _first(conn, "TVKO", "VKORG", "BUKRS = '%s'" % comp)
    dch, div = env("M4H_BP_DISTR_CHAN"), env("M4H_BP_DIVISION")
    if sorg and not (dch and div):
        sa = _rows(conn, "KNVV", ["VTWEG", "SPART"], "VKORG = '%s'" % sorg, 1)
        if sa:
            dch, div = dch or sa[0]["VTWEG"], div or sa[0]["SPART"]
    sorg, dch, div = sorg or _FB["SALES_ORG"], dch or _FB["DISTR_CHAN"], div or _FB["DIVISION"]

    # purchasing + logistics
    porg = env("M4H_PO_PURCH_ORG") or _first(conn, "T024E", "EKORG", "BUKRS = '%s'" % comp) or _FB["PURCH_ORG"]
    plant = env("M4H_PO_PLANT") or _first(conn, "T001K", "BWKEY", "BUKRS = '%s'" % comp) or _FB["PLANT"]
    pgrp = env("M4H_PO_PUR_GROUP") or _first(conn, "T024", "EKGRP") or _FB["PUR_GROUP"]
    mgrp = env("M4H_PO_MATL_GROUP") or _first(conn, "T023", "MATKL") or _FB["MATL_GROUP"]
    dts = [r["BSART"] for r in _rows(conn, "T161", ["BSART", "BSTYP"], "BSTYP = 'F'", 50)]
    dtype = env("M4H_PO_DOC_TYPE") or ("NB" if "NB" in dts else (dts[0] if dts else _FB["DOC_TYPE"]))

    # cost & profit center first (the PO expense account is validated against the cost center)
    cc = env("M4H_PO_COSTCENTER") or _first(conn, "CSKS", "KOSTL",
             "KOKRS = '%s' AND BUKRS = '%s'" % (kokrs, comp)) or _FB["COSTCENTER"]
    pc = env("M4H_FI_PROFIT_CTR") or _first(conn, "CEPC", "PRCTR", "KOKRS = '%s'" % kokrs) or _FB["PROFIT_CTR"]
    # FI clearing offset = a postable balance-sheet account
    gl_clr = env("M4H_FI_CLEARING_GL") or _pick_gl(conn, ktopl, comp, primary=False) or _FB["CLEARING_GL"]
    # PO expense account = a primary cost element that actually posts (probe-validated)
    gl_po = (env("M4H_PO_GL_ACCOUNT")
             or _discover_po_gl(conn, comp, kokrs, porg, plant, pgrp, dtype, mgrp, cc)
             or _FB["GL_ACCOUNT"])

    # CO master (cost center) config: standard hierarchy node + a valid category
    cc_hier = _first(conn, "TKA01", "KHINR", "KOKRS = '%s'" % kokrs) or "0001"
    cats = Counter(r["KOSAR"] for r in _rows(conn, "CSKS", ["KOSAR"], "KOKRS = '%s'" % kokrs, 500)
                   if r.get("KOSAR"))
    cc_cat = env("M4H_CC_CATEGORY") or (cats.most_common(1)[0][0] if cats else "1")
    comp_curr = _first(conn, "T001", "WAERS", "BUKRS = '%s'" % comp) or "USD"
    pc_hiers = Counter(r["KHINR"] for r in _rows(conn, "CEPC", ["KHINR"], "KOKRS = '%s'" % kokrs, 500)
                       if r.get("KHINR"))
    pc_hier = pc_hiers.most_common(1)[0][0] if pc_hiers else cc_hier
    co = {"CO_AREA": kokrs, "CC_HIER": cc_hier, "CC_CATEGORY": cc_cat, "PC_HIER": pc_hier,
          "COMP_CODE": comp, "CURRENCY": comp_curr, "PROFIT_CTR": pc,
          "VALID_FROM": env("M4H_CC_VALID_FROM") or "20240101"}

    # Fixed-asset config: pick a company code that ACTUALLY has assets and a
    # demonstrably-valid asset class (most-common ANLKL among real assets) so the
    # class customizing (account determination, default depreciation) is guaranteed
    # usable. Default to internal numbering (BAPI assigns; source->target mapped),
    # which is the support-safe choice and needs no number-range discovery.
    a_rows = _rows(conn, "ANLA", ["BUKRS", "ANLKL"], "ANLN2 = '0000'", 1000)
    a_bukrs_ct = Counter(r["BUKRS"] for r in a_rows if r.get("BUKRS"))
    a_bukrs = env("M4H_ASSET_COMP_CODE") or (a_bukrs_ct.most_common(1)[0][0] if a_bukrs_ct else comp)
    a_cls_ct = Counter(r["ANLKL"] for r in a_rows if r.get("BUKRS") == a_bukrs and r.get("ANLKL"))
    a_class = env("M4H_ASSET_CLASS") or (a_cls_ct.most_common(1)[0][0] if a_cls_ct else "")
    asset = {"ASSET_COMP_CODE": a_bukrs, "ASSET_CLASS": a_class, "COMP_CODE": comp,
             "ASSET_EXTERNAL_NUM": bool(env("M4H_ASSET_EXTERNAL_NUM")),
             "CAP_DATE": env("M4H_ASSET_CAP_DATE") or env("M4H_CC_VALID_FROM") or "20240101",
             "VALID_FROM": env("M4H_CC_VALID_FROM") or "20240101"}

    po = {"COMP_CODE": comp, "PURCH_ORG": porg, "PLANT": plant, "PUR_GROUP": pgrp,
          "DOC_TYPE": dtype, "PO_UNIT": env("M4H_PO_UNIT") or _FB["PO_UNIT"],
          "MATL_GROUP": mgrp, "GL_ACCOUNT": gl_po, "COSTCENTER": cc}
    fi = {"COMP_CODE": comp, "CLEARING_GL": gl_clr, "PROFIT_CTR": pc}
    bp = {"COMP_CODE": comp, "CUST_RECON": cust_recon, "VEND_RECON": vend_recon,
          "SALES_ORG": sorg, "DISTR_CHAN": dch, "DIVISION": div, "PURCH_ORG": porg}
    summary = {"company": comp, "chart_of_accounts": ktopl, "controlling_area": kokrs,
               "sales_area": f"{sorg}/{dch}/{div}", "plant": plant, "purch_org": porg,
               "cust_recon": cust_recon, "vend_recon": vend_recon,
               "po_gl": gl_po, "clearing_gl": gl_clr, "cost_center": cc, "profit_center": pc,
               "cc_hierarchy": cc_hier, "cc_category": cc_cat,
               "asset_comp_code": a_bukrs, "asset_class": a_class}
    return {"po": po, "fi": fi, "bp": bp, "co": co, "asset": asset, "summary": summary}
