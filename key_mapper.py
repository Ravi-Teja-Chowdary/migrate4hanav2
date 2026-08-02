"""
key_mapper — governed legacy(ECC) -> target(S/4) MASTER-DATA KEY mapping.

THE PROBLEM IT SOLVES (road-to-production gap P0-1, the #1 correctness gap)
    The old and new systems use different *codes* for the same thing:
      * a G/L account is `113100` in the source chart (INT) and `0022544100` in the
        target operating chart (YCOA);
      * a customer/vendor keeps a legacy number in ECC but gets a NEW Business
        Partner number in S/4 (external CVI numbering);
      * a material can be renumbered.
    Balances and open items are POINTERS into these codes — post them against the
    wrong code and the books are wrong. Until now `bucket3_migrate` used a
    *positional demo* map (proves the engine, not a faithful migration). This module
    replaces that guesswork with a **governed, explainable key map** — the same
    detect -> propose -> confirm -> resolve discipline as `org_mapper.py`, but for
    keys instead of org units.

        detect  -> read the source keys (+ description / group / balance-sheet flag)
                   and the target keys the same way.
        propose -> per source key, choose a target key by, in order:
                     * identity  - the same key exists in the target set (auto).
                                   (This is the whole story for a same-chart / same-
                                    numbering migration — fully automatic.)
                     * description - exactly one target key has the identical
                                   (normalised) description (review).
                     * semantic  - narrow by account group + balance-sheet/P&L and
                                   pick the best (review, with alternatives).
                     * decision  - nothing credible; you must map it by hand.
        confirm -> the map lives in key_mapper.json; you edit/approve. Loaders use
                   ONLY 'auto' or 'confirmed' rows — never a guess.
        resolve -> KeyMap().resolve(dim, source) -> target, for any loader.

    We never silently invent a key mapping; everything unresolved surfaces in
    KEY_MAPPING.md as a decision, exactly like the org report.

DIMENSIONS (extensible; add one entry to DIMS)
    gl_account (built + wired into bucket3 GL-balance takeover). customer / vendor /
    material are scaffolded the same way and are the next to wire.

CLI
    M4H_TARGET_CLIENT=100 py -3.7 key_mapper.py gl_account            # detect+propose+write
    M4H_TARGET_CLIENT=100 py -3.7 key_mapper.py gl_account --src-chart INT --tgt-chart YCOA
    py -3.7 key_mapper.py --status
"""
import os, sys, json, time, argparse, re
from collections import Counter, OrderedDict, defaultdict

os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, os.getcwd()); sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))

MAPFILE = "key_mapper.json"
REPORT = "KEY_MAPPING.md"


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _entry(target, confidence, rationale, count=0, alternatives=None):
    return OrderedDict([
        ("target", target), ("confidence", confidence), ("rationale", rationale),
        ("source_count", count), ("alternatives", alternatives or []),
        ("confirmed", confidence == "auto"),
    ])


# ── generic propose: identity → description → semantic(group+bs) → decision ──────
def _propose_keys(src, tgt):
    """src/tgt: {key: {"desc":..., "group":..., "bs":...}}. Returns OrderedDict key->entry."""
    tgt_nums = set(tgt)
    by_desc = defaultdict(list)
    for k, r in tgt.items():
        if r.get("desc"):
            by_desc[_norm(r["desc"])].append(k)
    by_semantic = defaultdict(list)
    for k, r in tgt.items():
        by_semantic[(r.get("group", ""), r.get("bs", ""))].append(k)

    out = OrderedDict()
    for k in sorted(src):
        r = src[k]
        if k in tgt_nums:
            out[k] = _entry(k, "auto", "identity — same key exists in target set")
            continue
        dm = by_desc.get(_norm(r.get("desc", "")), [])
        if len(dm) == 1:
            out[k] = _entry(dm[0], "review", "matched by identical description", alternatives=dm)
        elif len(dm) > 1:
            out[k] = _entry(sorted(dm)[0], "review",
                            "%d target keys share this description" % len(dm), alternatives=sorted(dm))
        else:
            sem = [c for c in by_semantic.get((r.get("group", ""), r.get("bs", "")), []) if c != k]
            if sem:
                out[k] = _entry("", "decision",
                                "no key/description match; %d candidates share account group '%s'/%s "
                                "— pick one or map by hand" % (len(sem), r.get("group", ""), r.get("bs", "")),
                                alternatives=sorted(sem)[:12])
            else:
                out[k] = _entry("", "decision", "no target key by number, description, or group — map by hand")
    return out


# ── dimension detectors (read source + target key sets) ─────────────────────────
def detect_gl_account(eng, src_chart, tgt_chart):
    ecc, tgt = eng.ecc, eng.tgt

    def read(conn, chart):
        acc = {r["SAKNR"].strip(): {"group": r["KTOKS"].strip(), "bs": r["XBILK"].strip(), "desc": ""}
               for r in eng.read_table(conn, "SKA1", ["SAKNR", "KTOPL", "KTOKS", "XBILK"], "KTOPL = '%s'" % chart)}
        for lang in ("E", "D"):   # prefer English text, fall back to German
            for r in eng.read_table(conn, "SKAT", ["SAKNR", "KTOPL", "SPRAS", "TXT50"],
                                    "KTOPL = '%s' AND SPRAS = '%s'" % (chart, lang)):
                a = r["SAKNR"].strip()
                if a in acc and not acc[a]["desc"]:
                    acc[a]["desc"] = r["TXT50"].strip()
        return acc

    return read(ecc, src_chart), read(tgt, tgt_chart)


def detect_material(eng, **_):
    """Material key map: source MATNR -> target MATNR. Identity where the number exists on
    the target (the common case — materials usually keep their number), else by description."""
    ecc, tgt = eng.ecc, eng.tgt

    def read(conn):
        m = {r["MATNR"].strip(): {"group": r["MTART"].strip(), "bs": "", "desc": ""}
             for r in eng.read_table(conn, "MARA", ["MATNR", "MTART"])}
        for r in eng.read_table(conn, "MAKT", ["MATNR", "MAKTX", "SPRAS"], "SPRAS = 'E'"):
            a = r["MATNR"].strip()
            if a in m and not m[a]["desc"]:
                m[a]["desc"] = r["MAKTX"].strip()
        return m

    return read(ecc), read(tgt)


DIMS = {
    "gl_account": {
        "title": "G/L account (chart of accounts conversion)",
        "detect": detect_gl_account,
        "params": {"src_chart": "INT", "tgt_chart": "YCOA"},
    },
    "material": {
        "title": "Material (MATNR)",
        "detect": detect_material,
        "params": {},
    },
    # customer / vendor are LOADER-POPULATED dims (recorded at BP creation via record_bulk),
    # not detect-based, because S/4 assigns a NEW Business Partner number per created partner.
}


# ── persist / merge (never clobber a confirmed human choice) ─────────────────────
def load():
    return json.load(open(MAPFILE)) if os.path.exists(MAPFILE) else {"dimensions": {}}


def merge(existing, dim, fresh):
    out = existing if existing.get("dimensions") else {"dimensions": {}}
    out["generated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    prev = out["dimensions"].get(dim, {})
    merged = OrderedDict()
    for k, ent in fresh.items():
        old = prev.get(k)
        if old and (old.get("confirmed") or (old.get("target") and old.get("target") != ent["target"])):
            keep = OrderedDict(old); keep["source_count"] = ent["source_count"]; merged[k] = keep
        else:
            merged[k] = ent
    out["dimensions"][dim] = merged
    return out


def save(m):
    json.dump(m, open(MAPFILE, "w"), indent=1)


def record_bulk(dim, pairs):
    """Loaders call this to persist source->target mappings they CREATED (e.g. the
    customer/vendor spine records legacy KUNNR/LIFNR -> the new S/4 Business Partner as
    it creates each one). These are authoritative (confirmed), because the loader knows
    the exact target it just made — no proposal/guess involved. Idempotent upsert."""
    if not pairs:
        return
    m = load()
    d = m.setdefault("dimensions", {}).setdefault(dim, {})
    for s, t in pairs.items():
        s = str(s).strip(); t = str(t).strip()
        if not s or not t:
            continue
        d[s] = _entry(t, "auto", "recorded at migration (created by loader)", count=1)
    m["generated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    save(m)


# ── resolver (loaders use this) ─────────────────────────────────────────────────
class KeyMap:
    def __init__(self, path=MAPFILE):
        self.dims = (json.load(open(path)) if os.path.exists(path) else {"dimensions": {}}).get("dimensions", {})

    def resolve(self, dim, source, require_confirmed=True):
        ent = self.dims.get(dim, {}).get((source or "").strip())
        if not ent or not ent.get("target"):
            return None
        if require_confirmed and ent.get("confidence") != "auto" and not ent.get("confirmed"):
            return None
        return ent["target"]

    def resolved_map(self, dim, require_confirmed=True):
        """All source->target pairs usable by a loader (auto + confirmed)."""
        out = {}
        for s, ent in self.dims.get(dim, {}).items():
            t = self.resolve(dim, s, require_confirmed)
            if t:
                out[s] = t
        return out


# ── human report ────────────────────────────────────────────────────────────────
def write_report(m):
    label = {"auto": "✅ auto", "review": "🟡 review", "decision": "🔴 decision"}
    order = {"decision": 0, "review": 1, "auto": 2}
    lines = ["# Master-data key mapping — ECC → S/4", "",
             f"_Generated {m.get('generated','')}. Edit `key_mapper.json` to confirm/adjust; loaders use "
             "only `auto` or `confirmed` rows. Nothing here is a silent guess._", ""]
    for dim, entries in m["dimensions"].items():
        if not entries:
            continue
        c = Counter("auto" if e.get("confirmed") else e["confidence"] for e in entries.values())
        title = DIMS.get(dim, {}).get("title", dim)
        lines += [f"## {title}", "",
                  f"**{c.get('decision',0)} decisions · {c.get('review',0)} to review · {c.get('auto',0)} auto** "
                  f"(of {len(entries)} source keys)", "",
                  "| source | → target | conf. | rationale | alternatives |", "|---|---|---|---|---|"]
        shown = sorted(entries.items(), key=lambda kv: (order.get(kv[1]["confidence"], 3), kv[0]))
        for k, e in shown[:400]:
            conf = "auto" if e.get("confirmed") else e["confidence"]
            alts = ",".join(e.get("alternatives", [])[:8])
            lines.append(f"| `{k}` | `{e['target'] or '—'}` | {label.get(conf, conf)} | {e['rationale']} | {alts} |")
        if len(shown) > 400:
            lines.append(f"| … | | | _{len(shown)-400} more in key_mapper.json_ | |")
        lines.append("")
    open(REPORT, "w", encoding="utf-8").write("\n".join(lines))


def _status():
    m = load()
    if not m.get("dimensions"):
        print("no key_mapper.json yet — run e.g. `key_mapper.py gl_account`"); return
    for dim, entries in m["dimensions"].items():
        c = Counter("auto" if e.get("confirmed") else e["confidence"] for e in entries.values())
        print(f"{dim:14} {dict(c)}  ({len(entries)} keys)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dimension", nargs="?", choices=sorted(DIMS))
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--confirm-reviews", action="store_true",
                    help="approve all 'review' proposals that have a target (the human sign-off "
                         "after eyeballing KEY_MAPPING.md) -> they become usable by loaders")
    ap.add_argument("--src-chart"); ap.add_argument("--tgt-chart")
    args = ap.parse_args()
    if args.status or not args.dimension:
        _status(); return
    if args.confirm_reviews:
        m = load(); n = 0
        for k, e in m.get("dimensions", {}).get(args.dimension, {}).items():
            if e.get("confidence") == "review" and e.get("target") and not e.get("confirmed"):
                e["confirmed"] = True; n += 1
        save(m); write_report(m)
        print(f"confirmed {n} review proposal(s) for {args.dimension} — now usable by loaders"); return
    from migration_engine import Engine
    spec = DIMS[args.dimension]
    params = dict(spec["params"])
    if args.src_chart:
        params["src_chart"] = args.src_chart
    if args.tgt_chart:
        params["tgt_chart"] = args.tgt_chart
    eng = Engine()
    try:
        print(f"detecting {args.dimension} keys ({params})…", flush=True)
        src, tgt = spec["detect"](eng, **params)
    finally:
        eng.close()
    fresh = _propose_keys(src, tgt)
    for k in fresh:   # carry a usage-ish count = 1 (real counts come from the loader's data)
        fresh[k]["source_count"] = 1
    m = merge(load(), args.dimension, fresh)
    save(m); write_report(m)
    c = Counter("auto" if e.get("confirmed") else e["confidence"] for e in m["dimensions"][args.dimension].values())
    print(f"wrote {MAPFILE} + {REPORT}", flush=True)
    print(f"  {args.dimension}: {c.get('auto',0)} auto · {c.get('review',0)} review · {c.get('decision',0)} decision "
          f"(src={len(src)} tgt={len(tgt)})", flush=True)


if __name__ == "__main__":
    main()
