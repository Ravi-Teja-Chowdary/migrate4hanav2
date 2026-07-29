"""
org_mapper — legacy(ECC) -> target(S/4) organizational-unit mapping layer.

THE PROBLEM IT SOLVES
    ECC and the S/4 best-practice target have different org structures. ECC uses
    ~90 sales orgs / dozens of plants across every country; the target ships only
    DE (0001, 1010) and US (0003, 1710, FOBP, FORP) sales orgs and a handful of
    plants (1010/1710/...). Nothing org-keyed — material sales views (MVKE),
    plant/MRP/valuation views, pricing, open orders — can land 1:1 without a
    decision: which legacy org unit becomes which target org unit. This is THE
    gap for an "every damn thing" migrator, and it is a business decision, not a
    guess. This module makes the decision *governed and cheap*:

        detect  -> read what org units the SOURCE data actually uses, per
                   dimension, and what the TARGET actually offers, with the
                   country linkage (VKORG->BUKRS->LAND1, plant->LAND1).
        propose -> for each used source unit, propose a target unit by COUNTRY
                   (the safe, explainable heuristic) and mark a confidence:
                     * auto     - exactly one sensible target for that country
                     * review   - several targets for that country; we pick the
                                  S/4 best-practice one and ask you to confirm
                     * decision - no target unit for that country; you must
                                  create one, consolidate, or skip
        confirm -> the mapping lives in org_mapper.json; you edit/approve. Only
                   'confirmed' (or auto) entries are used by loaders.
        resolve -> resolve(dim, source) -> target, for any loader to translate.

    We only ever propose from the data + country; we never silently invent an
    org mapping. Everything unresolved surfaces in ORG_MAPPING.md as a decision.

DIMENSIONS
    sales_org (VKORG), distribution_channel (VTWEG), division (SPART), plant
    (WERKS). Company code (BUKRS) already maps 1:1 across the SCCL copy, so it is
    read only as the country bridge, not remapped.

CLI
    py -3.7 org_mapper.py            # detect + propose + (re)write org_mapper.json + ORG_MAPPING.md
    py -3.7 org_mapper.py --status   # summarise current mapping (no SAP calls)
"""
import os, sys, json, time
from collections import Counter, defaultdict, OrderedDict

MAPFILE = "org_mapper.json"
REPORT = "ORG_MAPPING.md"

# S/4 best-practice preferred target unit per country, when several exist.
PREFERRED_SALES_ORG = {"DE": "1010", "US": "1710"}
PREFERRED_PLANT = {"DE": "1010", "US": "1710"}
# distribution channels / divisions collapse onto the target's canonical value.
CANONICAL_DISTR = "10"     # target ships 01 + 10; 10 = "Final customer sales"
CANONICAL_DIV = "00"       # cross-division


# ─────────────────────────────────────────────────────────────────────────────
# detect
# ─────────────────────────────────────────────────────────────────────────────
def _rt(c, t, f, w="", n=0):
    r = c.call("RFC_READ_TABLE", QUERY_TABLE=t, DELIMITER="~",
               OPTIONS=([{"TEXT": w}] if w else []),
               FIELDS=[{"FIELDNAME": x} for x in f], ROWCOUNT=n)
    return [dict(zip(f, x["WA"].split("~"))) for x in r.get("DATA", [])]


def detect(ec, sc):
    """Return the org landscape: what the source uses + what the target offers,
    each with country linkage and source usage counts."""
    def country_maps(c):
        bukrs = {r["BUKRS"].strip(): r["LAND1"].strip() for r in _rt(c, "T001", ["BUKRS", "LAND1"])}
        vkorg = {r["VKORG"].strip(): r["BUKRS"].strip() for r in _rt(c, "TVKO", ["VKORG", "BUKRS"])}
        vk_country = {v: bukrs.get(b, "") for v, b in vkorg.items()}
        plant_country = {r["WERKS"].strip(): r["LAND1"].strip() for r in _rt(c, "T001W", ["WERKS", "LAND1"])}
        return vk_country, plant_country

    src_vk_country, src_plant_country = country_maps(ec)
    tgt_vk_country, tgt_plant_country = country_maps(sc)

    # what the SOURCE data actually uses (usage counts drive priority)
    used_sales = Counter(r["VKORG"].strip() for r in _rt(ec, "MVKE", ["VKORG"]))
    used_distr = Counter(r["VTWEG"].strip() for r in _rt(ec, "MVKE", ["VTWEG"]))
    used_div = Counter(r["SPART"].strip() for r in _rt(ec, "MARA", ["SPART"]))  # division is on MARA
    used_plant = Counter(r["WERKS"].strip() for r in _rt(ec, "MARC", ["WERKS"]))

    # what the TARGET offers
    tgt_sales = set(tgt_vk_country)
    tgt_distr = {r["VTWEG"].strip() for r in _rt(sc, "TVTW", ["VTWEG"])}
    tgt_div = {r["SPART"].strip() for r in _rt(sc, "TSPA", ["SPART"])}
    tgt_plant = set(tgt_plant_country)

    # invert target by country for proposal lookups
    tgt_sales_by_country = defaultdict(list)
    for v, ctry in tgt_vk_country.items():
        tgt_sales_by_country[ctry].append(v)
    tgt_plant_by_country = defaultdict(list)
    for p, ctry in tgt_plant_country.items():
        tgt_plant_by_country[ctry].append(p)

    return {
        "src_vk_country": src_vk_country, "src_plant_country": src_plant_country,
        "used_sales": used_sales, "used_distr": used_distr,
        "used_div": used_div, "used_plant": used_plant,
        "tgt_sales": tgt_sales, "tgt_distr": tgt_distr, "tgt_div": tgt_div,
        "tgt_plant": tgt_plant,
        "tgt_sales_by_country": dict(tgt_sales_by_country),
        "tgt_plant_by_country": dict(tgt_plant_by_country),
    }


# ─────────────────────────────────────────────────────────────────────────────
# propose
# ─────────────────────────────────────────────────────────────────────────────
def _entry(target, country, confidence, rationale, count, alternatives=None):
    return OrderedDict([
        ("target", target), ("country", country), ("confidence", confidence),
        ("rationale", rationale), ("source_count", count),
        ("alternatives", alternatives or []), ("confirmed", confidence == "auto"),
    ])


def _propose_by_country(used, src_country, tgt_by_country, preferred):
    out = OrderedDict()
    for val, cnt in used.most_common():
        if not val:
            continue
        ctry = src_country.get(val, "")
        cands = tgt_by_country.get(ctry, [])
        if not cands:
            out[val] = _entry("", ctry, "decision",
                              f"no target org for country {ctry or '(unknown)'} — create one, "
                              f"consolidate onto an existing target org, or skip these records",
                              cnt)
        elif len(cands) == 1:
            out[val] = _entry(cands[0], ctry, "auto",
                              f"only target org for country {ctry}", cnt)
        else:
            pick = preferred.get(ctry) if preferred.get(ctry) in cands else sorted(cands)[0]
            out[val] = _entry(pick, ctry, "review",
                              f"{len(cands)} target orgs for {ctry}; picked S/4 best-practice",
                              cnt, alternatives=sorted(cands))
    return out


def propose(land):
    dims = OrderedDict()
    dims["sales_org"] = _propose_by_country(
        land["used_sales"], land["src_vk_country"], land["tgt_sales_by_country"], PREFERRED_SALES_ORG)
    dims["plant"] = _propose_by_country(
        land["used_plant"], land["src_plant_country"], land["tgt_plant_by_country"], PREFERRED_PLANT)

    # distribution channel + division: collapse to the target's canonical value
    # if the exact value is missing (they are refinements, not country-keyed).
    dc = OrderedDict()
    for val, cnt in land["used_distr"].most_common():
        if not val:
            continue
        if val in land["tgt_distr"]:
            dc[val] = _entry(val, "", "auto", "same value exists on target", cnt)
        else:
            tgt = CANONICAL_DISTR if CANONICAL_DISTR in land["tgt_distr"] else sorted(land["tgt_distr"])[0]
            dc[val] = _entry(tgt, "", "review",
                             f"not on target; collapse to canonical channel {tgt}",
                             cnt, alternatives=sorted(land["tgt_distr"]))
    dims["distribution_channel"] = dc

    dv = OrderedDict()
    for val, cnt in land["used_div"].most_common():
        if not val:
            continue
        if val in land["tgt_div"]:
            dv[val] = _entry(val, "", "auto", "same value exists on target", cnt)
        else:
            tgt = CANONICAL_DIV if CANONICAL_DIV in land["tgt_div"] else sorted(land["tgt_div"])[0]
            dv[val] = _entry(tgt, "", "review",
                             f"not on target; collapse to canonical division {tgt}",
                             cnt, alternatives=sorted(land["tgt_div"]))
    dims["division"] = dv
    return dims


# ─────────────────────────────────────────────────────────────────────────────
# persist + merge (never clobber a human's confirmed choice)
# ─────────────────────────────────────────────────────────────────────────────
def load():
    if os.path.exists(MAPFILE):
        return json.load(open(MAPFILE))
    return {"dimensions": {}}


def merge(existing, fresh):
    """Keep any human-confirmed target/confirmed flags; refresh counts/rationale."""
    out = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "dimensions": OrderedDict()}
    prev = existing.get("dimensions", {})
    for dim, entries in fresh.items():
        pdim = prev.get(dim, {})
        merged = OrderedDict()
        for val, ent in entries.items():
            old = pdim.get(val)
            if old and (old.get("confirmed") or old.get("target") != ent["target"]):
                # preserve the human's decision, but refresh usage count
                keep = OrderedDict(old)
                keep["source_count"] = ent["source_count"]
                merged[val] = keep
            else:
                merged[val] = ent
        out["dimensions"][dim] = merged
    return out


def save(mapping):
    json.dump(mapping, open(MAPFILE, "w"), indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# resolve API (used by loaders)
# ─────────────────────────────────────────────────────────────────────────────
class OrgMap:
    """Thin resolver over org_mapper.json for loaders."""
    def __init__(self, path=MAPFILE):
        self.dims = (json.load(open(path)) if os.path.exists(path) else {"dimensions": {}}).get("dimensions", {})

    def resolve(self, dim, source, require_confirmed=True):
        ent = self.dims.get(dim, {}).get((source or "").strip())
        if not ent or not ent.get("target"):
            return None
        if require_confirmed and ent.get("confidence") != "auto" and not ent.get("confirmed"):
            return None
        return ent["target"]

    def unresolved(self, dim):
        return {k: v for k, v in self.dims.get(dim, {}).items()
                if not v.get("target") or (v.get("confidence") == "decision")}


# ─────────────────────────────────────────────────────────────────────────────
# human report
# ─────────────────────────────────────────────────────────────────────────────
def write_report(mapping):
    dims = mapping["dimensions"]
    lines = ["# Organizational-unit mapping — ECC → S/4 (client 200)", "",
             f"_Generated {mapping.get('generated','')}. Edit `org_mapper.json` to confirm/adjust; "
             "loaders only use `auto` or `confirmed` rows._", ""]
    label = {"auto": "✅ auto", "review": "🟡 review", "decision": "🔴 decision"}
    order = {"decision": 0, "review": 1, "auto": 2}
    titles = {"sales_org": "Sales organization (VKORG)", "plant": "Plant (WERKS)",
              "distribution_channel": "Distribution channel (VTWEG)", "division": "Division (SPART)"}
    # summary
    tot = Counter()
    for dim, entries in dims.items():
        for e in entries.values():
            tot[e["confidence"] if not e.get("confirmed") else "auto"] += 1
    lines += [f"**Summary:** {tot['decision']} decisions · {tot['review']} to review · {tot['auto']} auto-mapped", ""]
    for dim, entries in dims.items():
        if not entries:
            continue
        lines += [f"## {titles.get(dim, dim)}", "",
                  "| source | → target | conf. | country | records | rationale | alternatives |",
                  "|---|---|---|---|---:|---|---|"]
        for val, e in sorted(entries.items(),
                             key=lambda kv: (order.get(kv[1]["confidence"], 3), -kv[1]["source_count"])):
            conf = "auto" if e.get("confirmed") else e["confidence"]
            alts = ",".join(e.get("alternatives", []))
            lines.append(f"| `{val}` | `{e['target'] or '—'}` | {label.get(conf, conf)} | "
                         f"{e.get('country','')} | {e['source_count']} | {e['rationale']} | {alts} |")
        lines.append("")
    open(REPORT, "w", encoding="utf-8").write("\n".join(lines))


# ─────────────────────────────────────────────────────────────────────────────
def _status():
    m = load()
    if not m.get("dimensions"):
        print("no org_mapper.json yet — run without --status to generate it"); return
    for dim, entries in m["dimensions"].items():
        c = Counter("auto" if e.get("confirmed") else e["confidence"] for e in entries.values())
        print(f"{dim:22} {dict(c)}")


def main():
    if "--status" in sys.argv:
        _status(); return
    os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    from pyrfc import Connection
    cfg = json.load(open("connections.json"))
    e, s = cfg["ecc"], cfg["lift_and_shift_target"]
    ec = Connection(ashost=e["ashost"], sysnr=e["sysnr"], client=e["client"],
                    user=e["user"], passwd=os.environ["M4H_ECC_PASSWD"], lang="EN")
    sc = Connection(ashost=s["target_ashost"], sysnr="00", client="200",
                    user=s["target_user"], passwd=os.environ["M4H_TARGET_PASSWD"], lang="EN")
    print("detecting org landscape…", flush=True)
    land = detect(ec, sc)
    ec.close(); sc.close()
    fresh = propose(land)
    mapping = merge(load(), fresh)
    save(mapping)
    write_report(mapping)
    tot = Counter()
    for entries in mapping["dimensions"].values():
        for e in entries.values():
            tot["auto" if e.get("confirmed") else e["confidence"]] += 1
    print(f"wrote {MAPFILE} + {REPORT}", flush=True)
    print(f"  {tot['auto']} auto · {tot['review']} review · {tot['decision']} decision", flush=True)


if __name__ == "__main__":
    main()
