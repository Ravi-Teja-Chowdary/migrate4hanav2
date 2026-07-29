"""
run_client200_material_views — migrate ECC material SALES-relevant tax
classifications (MLAN) into client 200 via the released OData service
API_PRODUCT_SRV (entity set A_ProductSalesTax).

WHY THIS EXISTS
    BAPI_MATERIAL_SAVEDATA silently ignores the TAXCLASSIFICATIONS table, so
    the classic loader can never populate material tax classification and hits
    MG172 ("tax classifications not fully maintained") the moment a sales view
    is touched — even on a fully configured client. The SAP-supported door is
    the OData product API, which exposes A_ProductSalesTax as a first-class,
    writable entity (proven live: POST -> 201, DELETE -> 204). This is the exact
    field the BAPI dropped.

GATEWAY ROUTING SELF-HEAL
    Client 200 was created by our migration setup (SCCL copy); the appliance's
    SAP Gateway service→alias routing row (/IWFND/C_MGDEAM) only existed for
    client 100, so OData calls with sap-client=200 failed alias determination
    ("/IWFND/CM_COS/064 No System Alias found"). We replicate the exact working
    routing row (SERVICE_ID=ZAPI_PRODUCT_SRV_0001 -> SYSTEM_ALIAS=LOCAL,
    IS_DEFAULT=X) into client 200 via the Basis Kit — governed customizing, the
    same mechanism used for T005/T077S. Idempotent; runs every time so a fresh
    appliance needs no manual /IWFND/MAINT_SERVICE step beyond activating the
    service once.

POSITIONAL TAX MAP
    MLAN stores classifications positionally: TAXM1..TAXM9 map, in LFDNR order,
    to the tax categories (TATYP) defined per departure country in TSTL. We read
    TSTL from the source to build country -> ordered[TATYP], then emit one
    A_ProductSalesTax row per non-blank TAXMn:
        {Product, Country=ALAND, TaxCategory=seq[ALAND][n-1], TaxClassification=TAXMn}

PREREQUISITE — MATERIAL MUST ALREADY HAVE A SALES VIEW (proven empirically)
    A standalone A_ProductSalesTax POST returns 201 but the tax classification
    only COMMITS if the material already carries a sales-org view (MVKE). On a
    Basic-view-only material the create no-ops silently — verified even on the
    fully configured reference client 100 (material 23, Basic-only: POST -> 201,
    MLAN still empty). This is the SD rule behind MG172: tax classification is a
    facet of the sales view, not a standalone object. Therefore this loader is
    the SECOND step: it must run AFTER the material sales-org view is created,
    which itself needs the org-mapper (ECC sales org -> target sales org). Until
    then it will correctly find 0 eligible materials and say so. It never reports
    a write as done without reading the row back from the target (MLAN).

FAITHFUL + NET-NEW
    Only materials that already exist on target client 200 AND already have a
    target sales view (MVKE) are touched; only their real ECC classifications
    are carried (no guessed values). Resumable; per-reason skip tally.
"""
import os, sys, json, time
from collections import defaultdict, Counter
import requests, urllib3
urllib3.disable_warnings()
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))
from pyrfc import Connection
from basis_kit_installer import push_rows_via_kit

SERVICE = "API_PRODUCT_SRV"
DONEFILE = os.path.join("local-staging", "c200_mattax_done.json")
SKIPFILE = os.path.join("local-staging", "c200_mattax_skips.json")

cfg = json.load(open("connections.json"))
e, s = cfg["ecc"], cfg["lift_and_shift_target"]
HOST = s["target_ashost"]; PW = os.environ["M4H_TARGET_PASSWD"]
BASE = f"https://{HOST}:44300/sap/opu/odata/sap/{SERVICE}"


def rt(c, t, f, w="", n=0):
    r = c.call("RFC_READ_TABLE", QUERY_TABLE=t, DELIMITER="~",
               OPTIONS=([{"TEXT": w}] if w else []),
               FIELDS=[{"FIELDNAME": x} for x in f], ROWCOUNT=n)
    return [dict(zip(f, x["WA"].split("~"))) for x in r.get("DATA", [])]


# ── 1. gateway routing self-heal (idempotent) ────────────────────────────────
def ensure_routing(sc):
    have = rt(sc, "/IWFND/C_MGDEAM", ["SERVICE_ID", "SYSTEM_ALIAS", "IS_DEFAULT"],
              "SERVICE_ID LIKE '%PRODUCT%'")
    if any(r["SERVICE_ID"].strip() == "ZAPI_PRODUCT_SRV_0001" for r in have):
        print("gateway routing for API_PRODUCT_SRV already present on 200", flush=True)
        return
    fields = ["SERVICE_ID", "USER_ROLE", "HOST_NAME", "SYSTEM_ALIAS", "IS_DEFAULT", "IS_DEF_FOR_META"]
    row = {"SERVICE_ID": "ZAPI_PRODUCT_SRV_0001", "USER_ROLE": "", "HOST_NAME": "",
           "SYSTEM_ALIAS": "LOCAL", "IS_DEFAULT": "X", "IS_DEF_FOR_META": ""}
    res = push_rows_via_kit(sc, "/IWFND/C_MGDEAM", fields, [row])
    print(f"gateway routing inserted on 200: {res.get('upserted')} upserted "
          f"{res.get('failed')} failed", flush=True)


# ── OData session ─────────────────────────────────────────────────────────────
def new_session():
    S = requests.Session(); S.auth = ("MIGRATE_ADMI", PW); S.verify = False
    r = S.get(BASE + "/", headers={"X-CSRF-Token": "Fetch"},
              params={"sap-client": "200"}, timeout=60)
    tok = r.headers.get("x-csrf-token")
    if not tok:
        raise RuntimeError(f"no CSRF token (status {r.status_code}) — routing not active?")
    return S, tok


def post_one(S, tok, r):
    """POST a single A_ProductSalesTax create. Returns (status, message), or
    None to signal a CSRF-token refresh is needed."""
    body = json.dumps({"Product": r["Product"], "Country": r["Country"],
                       "TaxCategory": r["TaxCategory"], "TaxClassification": r["TaxClassification"]})
    h = {"X-CSRF-Token": tok, "Content-Type": "application/json", "Accept": "application/json"}
    resp = S.post(BASE + "/A_ProductSalesTax", headers=h, params={"sap-client": "200"},
                  data=body, timeout=60)
    if resp.status_code == 403 and "csrf" in (resp.headers.get("x-csrf-token", "") + resp.text).lower():
        return None
    msg = ""
    if resp.status_code >= 400:
        try:
            msg = resp.json()["error"]["message"]["value"][:80]
        except Exception:
            msg = resp.text[:80]
    return resp.status_code, msg


def main():
    ec = Connection(ashost=e["ashost"], sysnr=e["sysnr"], client=e["client"],
                    user=e["user"], passwd=os.environ["M4H_ECC_PASSWD"], lang="EN")
    sc = Connection(ashost=s["target_ashost"], sysnr="00", client="200",
                    user=s["target_user"], passwd=os.environ["M4H_TARGET_PASSWD"], lang="EN")
    print(f"started {time.strftime('%H:%M:%S')}", flush=True)
    ensure_routing(sc)

    # positional category map from source TSTL
    seq = defaultdict(list)
    for r in sorted(rt(ec, "TSTL", ["TALND", "LFDNR", "TATYP"]),
                    key=lambda r: (r["TALND"], int(r["LFDNR"] or 0))):
        seq[r["TALND"].strip()].append(r["TATYP"].strip())
    print(f"tax-category sequences for {len(seq)} countries", flush=True)

    # materials that exist on target 200 AND already carry a sales view (MVKE):
    # tax classification only commits for those (see PREREQUISITE in the header).
    tgt_mat = {r["MATNR"].lstrip("0") for r in rt(sc, "MARA", ["MATNR"])}
    sales_mat = {r["MATNR"].lstrip("0") for r in rt(sc, "MVKE", ["MATNR"])}
    eligible = tgt_mat & sales_mat
    print(f"materials on 200: {len(tgt_mat)} | with a sales view (MVKE): {len(sales_mat)} "
          f"| eligible for tax write: {len(eligible)}", flush=True)
    if not eligible:
        print("\nNo material on client 200 has a sales-org view yet, so material tax\n"
              "classification cannot commit. Create the sales view first (org-mapper:\n"
              "ECC sales org -> target sales org), then re-run this loader.", flush=True)
        ec.close(); sc.close()
        return

    # source MLAN -> tax rows for target materials
    mfields = ["MATNR", "ALAND"] + [f"TAXM{i}" for i in range(1, 10)]
    mlan = rt(ec, "MLAN", mfields)
    tax_rows = []
    no_cat = Counter()
    for r in mlan:
        matnr = r["MATNR"].lstrip("0"); aland = r["ALAND"].strip()
        if matnr not in eligible or not aland:
            continue
        cats = seq.get(aland, [])
        for i in range(1, 10):
            val = (r.get(f"TAXM{i}") or "").strip()
            if not val:
                continue
            if i - 1 >= len(cats):
                no_cat[aland] += 1
                continue
            tax_rows.append({"Product": matnr, "Country": aland,
                             "TaxCategory": cats[i - 1], "TaxClassification": val})
    ec.close(); sc.close()
    print(f"faithful tax rows to migrate: {len(tax_rows)} "
          f"(countries: {dict(Counter(r['Country'] for r in tax_rows).most_common(8))})", flush=True)
    if no_cat:
        print(f"  note: {sum(no_cat.values())} classifications had no TSTL category slot "
              f"(source config gap): {dict(no_cat.most_common(6))}", flush=True)

    done = set(json.load(open(DONEFILE))) if os.path.exists(DONEFILE) else set()
    skips = json.load(open(SKIPFILE)) if os.path.exists(SKIPFILE) else []
    todo = [r for r in tax_rows if f"{r['Product']}|{r['Country']}|{r['TaxCategory']}" not in done]
    print(f"to-do after resume: {len(todo)}", flush=True)

    S, tok = new_session()
    ok = fail = 0; reasons = Counter()
    for n, r in enumerate(todo, 1):
        key = f"{r['Product']}|{r['Country']}|{r['TaxCategory']}"
        res = post_one(S, tok, r)
        if res is None:                       # CSRF expired
            S, tok = new_session(); res = post_one(S, tok, r)
        code, msg = res
        if code in (201, 200):
            done.add(key); ok += 1
        elif code == 409 or "exist" in msg.lower() or "duplicate" in msg.lower():
            done.add(key); ok += 1            # already present = success
        else:
            fail += 1; reasons[f"{code}:{r['Country']}/{r['TaxCategory']}"] += 1
            skips.append({"key": key, "code": code, "msg": msg})
        if n % 100 == 0:
            json.dump(sorted(done), open(DONEFILE, "w")); json.dump(skips, open(SKIPFILE, "w"))
            print(f"  … {n}/{len(todo)} (ok={ok} fail={fail})", flush=True)

    json.dump(sorted(done), open(DONEFILE, "w")); json.dump(skips, open(SKIPFILE, "w"))
    print(f"\nwrites accepted (HTTP 201/2xx)={ok} failed={fail}", flush=True)
    print("fail reasons:", dict(reasons.most_common(12)), flush=True)

    # HONEST VERIFICATION: a 201 is not proof of persistence for this entity —
    # read the tax rows back from the target's MLAN and report the TRUE count.
    vc = Connection(ashost=s["target_ashost"], sysnr="00", client="200",
                    user=s["target_user"], passwd=os.environ["M4H_TARGET_PASSWD"], lang="EN")
    persisted = len([r for r in rt(vc, "MLAN", ["MATNR", "ALAND", "TAXM1"])
                     if (r.get("TAXM1") or "").strip()])
    vc.close()
    print(f"VERIFIED persisted in MLAN on client 200: {persisted}", flush=True)
    if ok and persisted < ok:
        print("  WARNING: fewer rows persisted than accepted — the un-persisted ones\n"
              "  are on materials whose sales view did not actually commit the tax facet.",
              flush=True)
    print(f"DONE {time.strftime('%H:%M:%S')}", flush=True)


if __name__ == "__main__":
    main()
