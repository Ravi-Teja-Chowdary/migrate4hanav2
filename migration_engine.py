"""
migration_engine — universal SAP Migration Cockpit object loader, driven by recipes.

PHASE A of DATA_MIGRATION_ROADMAP.md. This generalizes the hand-built material
staging lane (`run_client200_material_sales.py`) into ONE engine that can run any
Migration Cockpit object from a declarative recipe — so adding a new object becomes
"write a recipe (config)", not "write code". It is the multiplier for Phases B/C/D.

WHAT IT DOES, per object recipe
    For each MC *structure* in the object (e.g. Product = basic + sales + tax):
      1. discover  — find the object's `/1LT/DS*` HANA staging table by the columns
                     it must contain (a signature), so we never hardcode table names.
      2. read      — pull source rows over RFC (ECC or the target), with an optional
                     WHERE and an optional "only keys that exist on the target" scope.
      3. build     — map source fields → staging columns via declarative transforms
                     (copy / lstrip0 / const / org-resolve via org_mapper) OR a named
                     custom builder for genuinely complex structures (material tax's
                     positional TATYPn/TAXMn from the target's TSTL).
      4. stage     — clear + bulk-load the staging table via the kit FMs
                     (Z_M4H_STAGING_CLEAR / Z_M4H_STAGING_LOAD, class-L only).
      5. verify    — read the staging rows back and report the true count.
    The MC Prepare/Simulate/Migrate run itself is app-gated on S/4 2025 (see the
    roadmap) — the engine stages everything and reports; a human clicks the 2 gates.

RECIPE (JSON) — see recipes/product.json for the worked example.
    { "object": "...", "structures": [ { "id","staging_signature","builder",
      "source": {"conn","table","fields","where","scope"}, "map":[{col,src,fn,...}] } ] }

Reuses: hana_staging (discover/load), basis_kit_installer (kit FM names),
org_mapper (OrgMap.resolve). No new SAP-side objects — pure orchestration.
"""
import os, sys, json
from collections import defaultdict
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))
from pyrfc import Connection
from hana_staging import from_connections
from org_mapper import OrgMap


# ─────────────────────────────────────────────────────────────────────────────
# field transforms (declarative). Each takes (value, spec, ctx) -> str
# ─────────────────────────────────────────────────────────────────────────────
def _t_copy(v, spec, ctx):
    return (v or "").strip()


def _t_lstrip0(v, spec, ctx):
    return (v or "").strip().lstrip("0")


def _t_const(v, spec, ctx):
    return spec.get("val", "")


def _t_org(v, spec, ctx):
    """Resolve an org unit via org_mapper. Returns None to signal 'skip this row'
    when a required org can't be mapped (and no allow_blank/default given)."""
    tgt = ctx["org"].resolve(spec["dim"], (v or "").strip(),
                             require_confirmed=not ctx.get("allow_proposed"))
    if tgt:
        return tgt
    if spec.get("allow_blank"):
        return ""
    if "default" in spec:
        return spec["default"]
    return None  # required + unmappable → caller skips the row


TRANSFORMS = {"copy": _t_copy, "lstrip0": _t_lstrip0, "const": _t_const, "org": _t_org}


class SkipRow(Exception):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────────────────
class Engine:
    def __init__(self, connections_path="connections.json", allow_proposed=False):
        self.cfg = json.load(open(connections_path))
        self.allow_proposed = allow_proposed
        self._ecc = self._tgt = self._hs = None
        self.org = OrgMap()

    # ── lazy connections ───────────────────────────────────────────────────────
    @property
    def ecc(self):
        if self._ecc is None:
            e = self.cfg["ecc"]
            self._ecc = Connection(ashost=e["ashost"], sysnr=e["sysnr"], client=e["client"],
                                   user=e["user"], passwd=os.environ["M4H_ECC_PASSWD"], lang="EN")
        return self._ecc

    @property
    def tgt(self):
        if self._tgt is None:
            s = self.cfg["lift_and_shift_target"]
            self._tgt = Connection(ashost=s["target_ashost"], sysnr="00", client="200",
                                   user=s["target_user"], passwd=os.environ["M4H_TARGET_PASSWD"], lang="EN")
        return self._tgt

    @property
    def hs(self):
        if self._hs is None:
            self._hs = from_connections(self.cfg); self._hs.connect()
        return self._hs

    def conn(self, name):
        return self.ecc if name == "ecc" else self.tgt

    # ── primitives ─────────────────────────────────────────────────────────────
    def read_table(self, conn, table, fields, where="", rowcount=0):
        r = conn.call("RFC_READ_TABLE", QUERY_TABLE=table, DELIMITER="~",
                      OPTIONS=([{"TEXT": where}] if where else []),
                      FIELDS=[{"FIELDNAME": f} for f in fields], ROWCOUNT=rowcount)
        return [dict(zip(fields, x["WA"].split("~"))) for x in r.get("DATA", [])]

    def discover_staging(self, signature, override=None):
        """Find the /1LT/ MC staging table that contains ALL columns in `signature`.
        `override` (env or recipe) short-circuits discovery."""
        if override:
            return override
        cur = self.hs.connect().cursor()
        conds = " AND ".join("SUM(CASE WHEN COLUMN_NAME=? THEN 1 ELSE 0 END)>0" for _ in signature)
        cur.execute(
            "SELECT TABLE_NAME FROM TABLE_COLUMNS WHERE SCHEMA_NAME=? AND TABLE_NAME LIKE '/1LT/%' "
            "GROUP BY TABLE_NAME HAVING " + conds + " ORDER BY TABLE_NAME LIMIT 2",
            tuple([self.hs.schema] + list(signature)))
        hits = [r[0] for r in cur.fetchall()]; cur.close()
        if len(hits) != 1:
            raise RuntimeError(f"staging signature {signature} matched {hits or 'nothing'} "
                               f"(need exactly one) — refine the signature or set an override")
        return hits[0]

    def target_key_set(self, table, key_field):
        """Keys present on the target, stripped of leading zeros. Single read — a
        one-field key column for even ~25k rows fits RFC_READ_TABLE's DATA buffer."""
        rows = self.tgt.call("RFC_READ_TABLE", QUERY_TABLE=table, DELIMITER="~",
                             FIELDS=[{"FIELDNAME": key_field}])
        return {x["WA"].strip().lstrip("0") for x in rows.get("DATA", [])}

    # ── driving key set: the records this object migrates (shared by all structs) ─
    def compute_key_scope(self, recipe):
        ks = recipe.get("key_scope")
        if not ks:
            return None
        d = ks["driver"]
        rows = self.read_table(self.conn(d.get("conn", "ecc")), d["table"], d["fields"], d.get("where", ""))
        on_target = None
        if ks.get("require_on_target"):
            rt = ks["require_on_target"]
            on_target = self.target_key_set(rt["table"], rt["key_field"])
        rom = ks.get("require_org_mapped")
        keys, seen = [], set()
        for r in rows:
            k = r[d["key"]].strip().lstrip("0")
            if not k or k in seen:
                continue
            if rom and not self.org.resolve(rom["dim"], r[rom["field"]].strip(),
                                            require_confirmed=not self.allow_proposed):
                continue
            if on_target is not None and k not in on_target:
                continue
            seen.add(k); keys.append(k)
            if ks.get("limit") and len(keys) >= ks["limit"]:
                break
        return set(keys)

    # ── declarative row builder ────────────────────────────────────────────────
    def build_declarative(self, struct):
        src = struct["source"]
        conn = self.conn(src.get("conn", "ecc"))
        rows = self.read_table(conn, src["table"], src["fields"], src.get("where", ""),
                               rowcount=src.get("limit", 0))
        mats = struct.get("_materials")
        if mats is not None and struct.get("key_src"):
            rows = [r for r in rows if r.get(struct["key_src"], "").strip().lstrip("0") in mats]
        # optional text join (e.g. MAKT description) keyed on a shared field
        tj = struct.get("text_join")
        if tj:
            tmap = {}
            for r in self.read_table(conn, tj["table"], [tj["on"], tj["field"]],
                                     tj.get("where", "")):
                tmap.setdefault(r[tj["on"]].strip(), r[tj["field"]].strip())
        # optional scope: only source keys that exist on the target
        scope = struct.get("scope")
        keyset = None
        if scope and scope.get("target_exists_in"):
            keyset = self.target_key_set(scope["target_exists_in"], scope["key_field"])
        ctx = {"org": self.org, "allow_proposed": self.allow_proposed}
        out, skipped = [], defaultdict(int)
        for r in rows:
            if keyset is not None:
                k = r.get(scope["src_key"], "").strip().lstrip("0")
                if k not in keyset:
                    skipped["not-on-target"] += 1; continue
            rec = {}
            try:
                for m in struct["map"]:
                    fn = TRANSFORMS[m.get("fn", "copy")]
                    val = fn(r.get(m.get("src", ""), ""), m, ctx)
                    if val is None:
                        skipped[f"unmapped-{m.get('fn')}-{m.get('dim','')}"] += 1
                        raise SkipRow
                    if not val and "default" in m:
                        val = m["default"]
                    if tj and m.get("src") == tj["on"]:
                        pass  # key col already handled
                    rec[m["col"]] = val
                # attach text-join value if a map entry references it by col name
                if tj:
                    key = r.get(tj["on"], "").strip()
                    for m in struct["map"]:
                        if m.get("from_text_join"):
                            rec[m["col"]] = tmap.get(key, m.get("default", ""))
                out.append(rec)
            except SkipRow:
                continue
        return out, dict(skipped)

    # ── stage one structure ────────────────────────────────────────────────────
    def stage_structure(self, struct, truncate=True, verify=True):
        table = self.discover_staging(struct["staging_signature"],
                                      os.environ.get("M4H_STG_" + struct["id"].upper()))
        builder = struct.get("builder", "declarative")
        if builder == "declarative":
            rows, skipped = self.build_declarative(struct)
            fields = [m["col"] for m in struct["map"]]
        else:
            fn = CUSTOM_BUILDERS[builder]
            rows, fields, skipped = fn(self, struct)
        if truncate:
            self.tgt.call("Z_M4H_STAGING_CLEAR", IV_TABLE=table)
        # bulk load via kit (pipe-joined lines, kit forces MANDT)
        lines = [{"LINE": "|".join(str(r.get(f, "")) for f in fields)} for r in rows]
        res = self.tgt.call("Z_M4H_STAGING_LOAD", IV_TABLE=table,
                            IV_FIELDS=",".join(fields), IT_ROWS=lines)
        info = {"structure": struct["id"], "table": table, "built": len(rows),
                "status": (res.get("EV_STATUS") or "").strip(), "skipped": skipped}
        if verify:
            back = self.read_table(self.tgt, table, ["MANDT"] + fields[:1])
            info["verified_rows"] = len(back)
        return info

    # ── run a whole object recipe ───────────────────────────────────────────────
    def run(self, recipe):
        if isinstance(recipe, str):
            recipe = json.load(open(recipe))
        print(f"=== object: {recipe['object']} — {recipe.get('description','')} ===", flush=True)
        keys = self.compute_key_scope(recipe)
        if keys is not None:
            print(f"  driving key set: {len(keys)} records", flush=True)
        results = []
        for struct in recipe["structures"]:
            if keys is not None:
                struct["_materials"] = keys
            info = self.stage_structure(struct, truncate=struct.get("truncate", True))
            results.append(info)
            print(f"  [{info['structure']:>10}] {info['table']}: built={info['built']} "
                  f"verified={info.get('verified_rows','?')} | {info['status']}"
                  + (f" | skipped={info['skipped']}" if info['skipped'] else ""), flush=True)
        return results

    def close(self):
        for c in (self._ecc, self._tgt):
            try:
                c and c.close()
            except Exception:
                pass
        try:
            self._hs and self._hs.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# custom builders — for structures too complex for the declarative map.
# signature: fn(engine, struct) -> (rows, fields, skipped_dict)
# ─────────────────────────────────────────────────────────────────────────────
def _b_product_basic_from_target(eng, struct):
    """Material basic (S_MARA): read the material's CURRENT values from the TARGET
    (faithful echo — never blanks existing basic data) + EN description from MAKT."""
    fields = ["PRODUCT", "MTART", "MBRSH", "MEINS", "MATKL", "MAKTX", "SPRAS"]
    scope = struct.get("scope", {})
    mats = struct.get("_materials")  # optional explicit list
    where = scope.get("where", "")
    mara = eng.read_table(eng.tgt, "MARA", ["MATNR", "MTART", "MBRSH", "MEINS", "MATKL"], where,
                          rowcount=scope.get("limit", 0))
    rows = []
    for a in mara:
        m = a["MATNR"].strip().lstrip("0")
        if mats and m not in mats:
            continue
        makt = eng.read_table(eng.tgt, "MAKT", ["MAKTX"],
                              "MATNR = '%s' AND SPRAS = 'E'" % a["MATNR"].strip())
        rows.append({"PRODUCT": m, "MTART": a["MTART"].strip(), "MBRSH": a["MBRSH"].strip(),
                     "MEINS": a["MEINS"].strip(), "MATKL": a["MATKL"].strip(),
                     "MAKTX": (makt[0]["MAKTX"].strip() if makt else "Material " + m), "SPRAS": "E"})
    return rows, fields, {}


def _b_product_tax_positional(eng, struct):
    """Material tax (S_MLAN): ECC MLAN TAXMn carried onto the TARGET's tax categories
    (target TSTL, positionally), not ECC's — so DE→TTX1, US→UTXJ, CA→CTX1/2/3."""
    tcat = defaultdict(list)
    for r in sorted(eng.read_table(eng.tgt, "TSTL", ["TALND", "LFDNR", "TATYP"]),
                    key=lambda r: (r["TALND"], int(r["LFDNR"] or 0))):
        tcat[r["TALND"].strip()].append(r["TATYP"].strip())
    mats = struct.get("_materials")
    where = struct.get("source", {}).get("where", "")
    fields = ["PRODUCT", "ALAND"] + sum([["TATYP%d" % i, "TAXM%d" % i] for i in range(1, 10)], [])
    rows, skipped = [], defaultdict(int)
    mlan = eng.read_table(eng.ecc, "MLAN", ["MATNR", "ALAND"] + ["TAXM%d" % i for i in range(1, 10)], where)
    for r in mlan:
        m = r["MATNR"].strip().lstrip("0"); aland = r["ALAND"].strip()
        if (mats and m not in mats) or not aland:
            continue
        cats = tcat.get(aland, [])
        if not cats:
            skipped["no-target-tax-cat-" + aland] += 1; continue
        rec, anyv = {"PRODUCT": m, "ALAND": aland}, False
        for i in range(1, len(cats) + 1):
            v = (r.get("TAXM%d" % i) or "").strip()
            rec["TATYP%d" % i] = cats[i - 1]; rec["TAXM%d" % i] = v
            anyv = anyv or bool(v)
        if anyv:
            rows.append(rec)
    return rows, fields, dict(skipped)


CUSTOM_BUILDERS = {
    "product_basic_from_target": _b_product_basic_from_target,
    "product_tax_positional": _b_product_tax_positional,
}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("recipe", help="path to a recipe JSON")
    ap.add_argument("--allow-proposed", action="store_true")
    args = ap.parse_args()
    eng = Engine(allow_proposed=args.allow_proposed)
    try:
        eng.run(args.recipe)
    finally:
        eng.close()
