"""
run_client200_materials — migrate the ECC material master (MARA) into client 200
as client-level **Basic view** records via BAPI_MATERIAL_SAVEDATA.

Why Basic-only: ECC and the fresh S/4 target have different org structures
(ECC plants 1000/3000/1200… vs S/4 1710/1010…; only 0001 overlaps), so plant/
MRP/valuation/sales views need org-mapping decisions and are handled separately.
The Basic view (identity, description, base UoM, material group, weights/volume)
is org-independent and migrates faithfully now. MATNR is preserved (external).

Depends on prep_client200_mat_customizing.py having replicated T006/T023 so the
real base units and material groups resolve. Harmonisation:
  * MTART not on target T134  -> skip + report (custom types with heavy config)
  * MEINS not on target T006  -> skip + report (should be rare post-prep)
  * MATKL not on target T023  -> blanked (material group is optional)
  * MBRSH not on target T137  -> defaulted to a valid sector
Resumable; per-reason skip tally written to a report file.
"""
import os, sys, json, time
from collections import Counter
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
from pyrfc import Connection

DONEFILE = os.path.join("local-staging", "c200_matmap.json")
SKIPFILE = os.path.join("local-staging", "c200_mat_skips.json")
cfg = json.load(open("connections.json"))
e, s = cfg["ecc"], cfg["lift_and_shift_target"]
ec = Connection(ashost=e["ashost"], sysnr=e["sysnr"], client=e["client"],
                user=e["user"], passwd=os.environ["M4H_ECC_PASSWD"], lang="EN")
sc = Connection(ashost=s["target_ashost"], sysnr="00", client="200",
                user=s["target_user"], passwd=os.environ["M4H_TARGET_PASSWD"], lang="EN")


def rt(c, t, f, w="", n=0):
    r = c.call("RFC_READ_TABLE", QUERY_TABLE=t, DELIMITER="|",
               OPTIONS=([{"TEXT": w}] if w else []),
               FIELDS=[{"FIELDNAME": x} for x in f], ROWCOUNT=n)
    return [dict(zip(f, [p.strip() for p in x["WA"].split("|")])) for x in r.get("DATA", [])]


print(f"started {time.strftime('%H:%M:%S')}", flush=True)
mfields = ["MATNR", "MTART", "MBRSH", "MATKL", "MEINS", "BRGEW", "NTGEW",
           "GEWEI", "VOLUM", "VOLEH", "GROES"]
mara = rt(ec, "MARA", mfields)
print(f"ECC MARA: {len(mara)}", flush=True)

# descriptions (EN)
makt = {r["MATNR"]: r["MAKTX"] for r in rt(ec, "MAKT", ["MATNR", "MAKTX"], "SPRAS = 'E'")}
print(f"ECC MAKT(EN): {len(makt)}", flush=True)

# target customizing coverage
tgt_mtart = {r["MTART"] for r in rt(sc, "T134", ["MTART"])}
tgt_meins = {r["MSEHI"] for r in rt(sc, "T006", ["MSEHI"])}
tgt_matkl = {r["MATKL"] for r in rt(sc, "T023", ["MATKL"])}
tgt_mbrsh = {r["MBRSH"] for r in rt(sc, "T137", ["MBRSH"])}
def_mbrsh = "M" if "M" in tgt_mbrsh else (sorted(tgt_mbrsh)[0] if tgt_mbrsh else "M")
print(f"target: MTART={len(tgt_mtart)} MEINS={len(tgt_meins)} MATKL={len(tgt_matkl)} "
      f"MBRSH={len(tgt_mbrsh)} default MBRSH={def_mbrsh}", flush=True)

done = set(json.load(open(DONEFILE))) if os.path.exists(DONEFILE) else set()
existing = {r["MATNR"] for r in rt(sc, "MARA", ["MATNR"], "", 0)}
done |= existing
todo = [m for m in mara if m["MATNR"] not in done]
print(f"to create: {len(todo)} (already on 200/mapped: {len(done)})", flush=True)


ok = fail = matkl_blanked = mbrsh_defaulted = 0
skips, reasons = [], Counter()
for i, m in enumerate(todo, 1):
    matnr = m["MATNR"]
    if m["MTART"] not in tgt_mtart:
        reasons["MTART:" + m["MTART"]] += 1
        skips.append({"matnr": matnr, "reason": "MTART " + m["MTART"]}); continue
    if m["MEINS"] not in tgt_meins:
        reasons["MEINS:" + m["MEINS"]] += 1
        skips.append({"matnr": matnr, "reason": "MEINS " + m["MEINS"]}); continue
    matkl = m["MATKL"] if m["MATKL"] in tgt_matkl else ""
    if not matkl and m["MATKL"]:
        matkl_blanked += 1
    mbrsh = m["MBRSH"] if m["MBRSH"] in tgt_mbrsh else def_mbrsh
    if mbrsh != m["MBRSH"]:
        mbrsh_defaulted += 1
    hd = {"MATERIAL": matnr, "MATL_TYPE": m["MTART"], "IND_SECTOR": mbrsh, "BASIC_VIEW": "X"}
    cd = {"BASE_UOM": m["MEINS"]}
    cdx = {"BASE_UOM": "X"}
    if matkl:
        cd["MATL_GROUP"] = matkl; cdx["MATL_GROUP"] = "X"
    # BAPI_MARA exposes NET_WEIGHT (QUAN, pass raw decimal string) + UNIT_OF_WT
    # + SIZE_DIM. It has NO GROSS_WT / VOLUME fields, so those are not carried in
    # the Basis view (they belong to the logistics/plant views, deferred).
    weu = m["GEWEI"] if m["GEWEI"] in tgt_meins else ""
    if weu and m["NTGEW"] and m["NTGEW"] not in ("", "0.000"):
        cd["UNIT_OF_WT"] = weu; cdx["UNIT_OF_WT"] = "X"
        cd["NET_WEIGHT"] = m["NTGEW"]; cdx["NET_WEIGHT"] = "X"
    if m["GROES"]:
        cd["SIZE_DIM"] = m["GROES"][:32]; cdx["SIZE_DIM"] = "X"
    desc = makt.get(matnr, matnr)[:40]
    try:
        r = sc.call("BAPI_MATERIAL_SAVEDATA", HEADDATA=hd, CLIENTDATA=cd, CLIENTDATAX=cdx,
                    MATERIALDESCRIPTION=[{"LANGU": "EN", "MATL_DESC": desc}])
    except Exception as ex:
        fail += 1; reasons["RFC:" + type(ex).__name__] += 1
        skips.append({"matnr": matnr, "reason": type(ex).__name__}); continue
    ret = r.get("RETURN"); rl = [ret] if isinstance(ret, dict) else (ret or [])
    errs = [x for x in rl if x.get("TYPE") in ("E", "A")]
    if errs:
        sc.call("BAPI_TRANSACTION_ROLLBACK"); fail += 1
        rc = f"{errs[0].get('ID')}/{errs[0].get('NUMBER')}"; reasons[rc] += 1
        skips.append({"matnr": matnr, "reason": rc, "msg": errs[0].get("MESSAGE", "")[:80]})
    else:
        sc.call("BAPI_TRANSACTION_COMMIT", WAIT="X"); done.add(matnr); ok += 1
    if i % 1000 == 0:
        json.dump(sorted(done), open(DONEFILE, "w"))
        json.dump(skips, open(SKIPFILE, "w"))
        print(f"  … {i}/{len(todo)} (ok={ok} fail={fail} matkl-blanked={matkl_blanked})", flush=True)

json.dump(sorted(done), open(DONEFILE, "w"))
json.dump(skips, open(SKIPFILE, "w"))
total = len(rt(sc, "MARA", ["MATNR"], "", 0))
print(f"\nDONE {time.strftime('%H:%M:%S')} | created={ok} failed={fail} "
      f"matkl-blanked={matkl_blanked} mbrsh-defaulted={mbrsh_defaulted} | MARA on 200: {total}", flush=True)
print("skip/fail reasons:", dict(reasons.most_common(15)), flush=True)
ec.close(); sc.close()
