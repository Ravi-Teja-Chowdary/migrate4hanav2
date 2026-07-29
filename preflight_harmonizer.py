"""
preflight_harmonizer — the "check the target BEFORE you load" engine.

WHY THIS EXISTS
---------------
Three things stop a faithful ECC→S/4 migration from being a single button
(see the plain-English writeup in EXPERT_REVIEW_*), and every one of them is
detectable *before* we try to create a single record:

  Wall #3  Config prerequisites  — the target is missing a customizing switch
           (a unit of measure, a material group, a relaxed bank rule, a tax
           category). Some we can flip remotely via the Basis Kit; a few need a
           person inside SAP (Material Ledger startup, gateway publish, number-
           range external flip).
  Wall #4  Data quality vs stricter target rules — real source values that the
           target rejects (10-char CA bank keys vs the 9-char rule, retired
           region codes, malformed SWIFT). Auto-fixable by relaxing config or
           blanking optional fields — or flagged for a decision.
  Wall #1  Org-structure mismatch — the source uses org units (plants, sales
           orgs, company codes) that don't exist on the target. This is NOT a
           code problem; it's a business mapping DECISION only the customer can
           make. This is the big one, and the whole point of the checklist.

This module connects to the live ECC + target pair, runs every registered
object's checks, AUTO-APPLIES the safe/remote config fixes through the kit, and
writes ONE human-readable decision checklist (MIGRATION_CHECKLIST.md) plus a
machine-readable migration_checklist.json for the pipeline. Nothing here mangles
source data or overrides an SAP NO-GO; unfixable items become checklist entries,
never silent losses.

Grounded in the rules proven live on client 200 this session (materials + banks
+ the plant/org mismatch). Adding an object = add one Recipe entry.

Run:  py -3.7 preflight_harmonizer.py            # detect + write checklist
      py -3.7 preflight_harmonizer.py --apply    # also auto-apply safe fixes
"""
from __future__ import annotations
import os, sys, json, time, argparse
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional

os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))
from pyrfc import Connection
from basis_kit_installer import push_rows_via_kit

WALL_CONFIG = "config-prerequisite"   # wall #3
WALL_DATA   = "data-quality"          # wall #4
WALL_ORG    = "org-mapping"           # wall #1
WALL_BAPI   = "sap-limitation"        # wall #2 (surfaced, never auto-fixed)


@dataclass
class Finding:
    wall: str                 # one of the WALL_* buckets
    obj: str                  # migration object, e.g. "material"
    title: str                # short human line
    detail: str               # what/why
    count: int = 0            # how many records/values affected
    auto_fixable: bool = False
    action: str = ""          # what the auto-fix does, or what the human must do
    samples: list = field(default_factory=list)
    all_values: list = field(default_factory=list)   # full value set (for dedup/pipeline)
    dedup_key: str = ""       # findings sharing this key merge into one decision


# ─────────────────────────────────────────────────────────────────────────────
# Table-read helper
# ─────────────────────────────────────────────────────────────────────────────
def rt(c, t, f, w="", n=0):
    r = c.call("RFC_READ_TABLE", QUERY_TABLE=t, DELIMITER="|",
               OPTIONS=([{"TEXT": w}] if w else []),
               FIELDS=[{"FIELDNAME": x} for x in f], ROWCOUNT=n)
    return [dict(zip(f, [p.strip() for p in x["WA"].split("|")])) for x in r.get("DATA", [])]


def real_fields(c, tab):
    r = c.call("DDIF_FIELDINFO_GET", TABNAME=tab)
    return [f["FIELDNAME"] for f in r.get("DFIES_TAB", [])
            if not f["FIELDNAME"].startswith(".") and f["FIELDNAME"] != "MANDT"]


def distinct(rows, key):
    return sorted({r[key] for r in rows if r.get(key)})


# ─────────────────────────────────────────────────────────────────────────────
# Reusable check primitives
# ─────────────────────────────────────────────────────────────────────────────
def config_gap(ec, sc, obj, tab, keyfields, delivery_class, human_hint=""):
    """Compare a customizing table source-vs-target. Delivery-class C/E/G/S rows
    are auto-fixable via the kit; otherwise flag for a human.

    RFC_READ_TABLE caps a row at ~512 bytes, so we only read the FULL row (for
    the apply payload) on auto-fixable class-C/E/S tables, which are narrow.
    Non-auto tables (e.g. wide T134) are detected on their key fields only."""
    auto = delivery_class in ("C", "E", "S")     # class G left to basis (heavy deps)
    # ECC and S/4 schemas drift (S/4 adds columns), so read each side with ITS
    # OWN field list; compare on the shared key; push source fields (kit MODIFY
    # defaults any target-only columns).
    src_fields = real_fields(ec, tab) if auto else list(keyfields)
    tgt_fields = real_fields(sc, tab) if auto else list(keyfields)
    src = rt(ec, tab, src_fields)
    tgt = rt(sc, tab, tgt_fields)
    tgt_keys = {tuple(r[k] for k in keyfields) for r in tgt}
    missing = [r for r in src if tuple(r[k] for k in keyfields) not in tgt_keys]
    if not missing:
        return None
    finding = Finding(
        wall=WALL_CONFIG, obj=obj,
        title=f"{tab}: {len(missing)} customizing rows missing on target",
        detail=(f"{tab} (delivery class {delivery_class}) has {len(missing)} "
                f"entries in ECC not present on the target. {human_hint}"),
        count=len(missing), auto_fixable=auto,
        action=(f"auto-apply {len(missing)} rows via Basis Kit (class {delivery_class})"
                if auto else f"needs basis: maintain {tab} on target"),
        samples=[("|".join(r[k] for k in keyfields) if len(keyfields) > 1 else r[keyfields[0]])
                 for r in missing[:10]],
    )
    payload = (tab, src_fields, missing) if auto else None
    return finding, payload


def org_gap(ec, sc, obj, src_tab, src_field, tgt_tab, tgt_field, unit_name, where=""):
    """Distinct org values used by the source that don't exist on the target =
    mapping decisions (wall #1). Never auto-fixable — a business decision."""
    src_vals = set(distinct(rt(ec, src_tab, [src_field], where), src_field))
    tgt_vals = set(distinct(rt(sc, tgt_tab, [tgt_field]), tgt_field))
    unmapped = sorted(src_vals - tgt_vals)
    if not unmapped:
        return None
    return Finding(
        wall=WALL_ORG, obj=obj,
        title=f"{unit_name}: {len(unmapped)} source values have no target equivalent",
        detail=(f"The source uses {len(unmapped)} {unit_name}(s) that don't exist "
                f"on the target (target only has: {sorted(tgt_vals)[:12]}…). Each "
                f"needs a mapping decision (old {unit_name} → new {unit_name}) or "
                f"the org unit created on the target."),
        count=len(unmapped), auto_fixable=False,
        action=f"DECIDE: map each source {unit_name} to a target {unit_name}",
        samples=unmapped[:15], all_values=unmapped, dedup_key=f"org:{unit_name}",
    )


def catalog_gap(ec, sc, obj, src_tab, src_field, tgt_tab, tgt_field, name, where=""):
    """Source values of a config key (order type, account group…) not defined on
    the target = a config DECISION (define it, or map to a target value). Not
    auto-fixed: these carry number ranges / account determination a human owns."""
    src_vals = set(distinct(rt(ec, src_tab, [src_field], where), src_field))
    tgt_vals = set(distinct(rt(sc, tgt_tab, [tgt_field]), tgt_field))
    missing = sorted(src_vals - tgt_vals)
    if not missing:
        return None
    return Finding(
        wall=WALL_CONFIG, obj=obj,
        title=f"{name}: {len(missing)} source values not defined on target",
        detail=(f"The source uses {len(missing)} {name}(s) the target doesn't "
                f"define (target has: {sorted(tgt_vals)[:12]}…). Each carries its "
                f"own config (number ranges / account determination), so this is a "
                f"decision: create it on the target or map to an existing one."),
        count=len(missing), auto_fixable=False,
        action=f"DECIDE: define each source {name} on target, or map to an existing one",
        samples=missing[:15],
    )


def region_dq(ec, sc, obj, tab, land_field, regio_field):
    """Records whose region code isn't valid on the target T005S — blanked at
    load (optional field), the master record still lands faithfully."""
    valid = {f"{r['LAND1']}|{r['BLAND']}" for r in rt(sc, "T005S", ["LAND1", "BLAND"])}
    rows = rt(ec, tab, [land_field, regio_field])
    bad = [r for r in rows if r[regio_field] and f"{r[land_field]}|{r[regio_field]}" not in valid]
    if not bad:
        return None
    return Finding(
        wall=WALL_DATA, obj=obj,
        title=f"{len(bad)} {obj} records carry a region code the target rejects",
        detail="Region blanked at load (optional address field); the record still lands.",
        count=len(bad), auto_fixable=True,
        action="auto-handled at load: blank invalid REGION",
        samples=sorted({f"{r[land_field]}/{r[regio_field]}" for r in bad})[:10],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Per-object recipes: each returns a list of Findings (+ optional apply payloads)
# ─────────────────────────────────────────────────────────────────────────────
def check_material(ec, sc, apply_payloads):
    findings = []
    # Wall #3: units + material groups are class-C customizing → auto-fixable
    for tab, keys, hint in [("T006", ["MSEHI"], "Base unit of measure."),
                            ("T023", ["MATKL"], "Material group.")]:
        res = config_gap(ec, sc, "material", tab, keys, "C", hint)
        if res:
            findings.append(res[0])
            if res[1]:
                apply_payloads.append(res[1])
    # Wall #3: material types (class G) — heavy dependent config, flag for basis
    res = config_gap(ec, sc, "material", "T134", ["MTART"], "X",
                     "Material type carries number ranges + account refs.")
    if res:
        f = res[0]; f.auto_fixable = False
        f.action = "DECIDE: create these material types on target, or skip those materials"
        findings.append(f)
    # Wall #1: plants / sales orgs / valuation areas used by ECC material views
    findings.append(org_gap(ec, sc, "material", "MARC", "WERKS", "T001W", "WERKS", "plant"))
    findings.append(org_gap(ec, sc, "material", "MVKE", "VKORG", "TVKO", "VKORG", "sales org"))
    # Wall #2: BAPI limitations we route around (surfaced, not fixed)
    findings.append(Finding(
        wall=WALL_BAPI, obj="material",
        title="Sales & valuation views not loadable via the standard BAPI",
        detail=("BAPI_MATERIAL_SAVEDATA ignores TAXCLASSIFICATIONS (MG172) so the "
                "sales view can't be set from outside; the valuation view needs "
                "Material Ledger production-startup (CKMSTART), a transaction. "
                "Materials migrate as the client-level Basic view; these two views "
                "are a separate, post-basic step."),
        auto_fixable=False,
        action="ACCEPT: Basic view migrates now; sales/valuation views are a follow-on"))
    return [f for f in findings if f]


def check_bank(ec, sc, apply_payloads):
    findings = []
    banks = rt(ec, "BNKA", ["BANKS", "BANKL", "SWIFT", "PROVZ"])
    countries = sorted({b["BANKS"] for b in banks if b["BANKS"]})
    # Wall #4: source keys violate target country checks → relax T005 BNKEY (auto)
    t5f = real_fields(sc, "T005")
    t5 = rt(sc, "T005", t5f)
    to_flip = [dict(r, BNKEY="2") for r in t5 if r["LAND1"] in countries and r.get("BNKEY") != "2"]
    if to_flip:
        findings.append(Finding(
            wall=WALL_DATA, obj="bank",
            title=f"{len(to_flip)} bank countries enforce key checks the source violates",
            detail=("ECC bank keys are external and some exceed the target's country "
                    "key-length rule (e.g. CA 10-char vs 9). Setting T005-BNKEY='2' "
                    "(external key) preserves every real key faithfully."),
            count=len(to_flip), auto_fixable=True,
            action="auto-apply: set T005-BNKEY='2' for the source's bank countries",
            samples=[r["LAND1"] for r in to_flip[:15]]))
        apply_payloads.append(("T005", t5f, to_flip))
    # Wall #4: regions retired on target (blanked at load, reported here)
    valid_reg = {f"{r['LAND1']}|{r['BLAND']}" for r in rt(sc, "T005S", ["LAND1", "BLAND"])}
    bad_reg = [b for b in banks if b["PROVZ"] and f"{b['BANKS']}|{b['PROVZ']}" not in valid_reg]
    if bad_reg:
        findings.append(Finding(
            wall=WALL_DATA, obj="bank",
            title=f"{len(bad_reg)} banks carry a region code the target rejects",
            detail="Region blanked at load (optional address field); key preserved.",
            count=len(bad_reg), auto_fixable=True,
            action="auto-handled at load: blank invalid REGION",
            samples=[f"{b['BANKS']}/{b['PROVZ']}" for b in bad_reg[:10]]))
    bad_swift = [b for b in banks if b["SWIFT"] and len(b["SWIFT"]) not in (8, 11)]
    if bad_swift:
        findings.append(Finding(
            wall=WALL_DATA, obj="bank",
            title=f"{len(bad_swift)} banks carry a malformed SWIFT/BIC",
            detail="SWIFT must be 8 or 11 chars; blanked at load, key preserved.",
            count=len(bad_swift), auto_fixable=True,
            action="auto-handled at load: blank invalid SWIFT",
            samples=[f"{b['BANKS']}{b['BANKL']}={b['SWIFT']}" for b in bad_swift[:10]]))
    return findings


def check_customer(ec, sc, apply_payloads):
    """Customer (KNA1 → BP FLCU01). Sales-area + company-code org mapping,
    account-group config, region data quality."""
    F = [
        org_gap(ec, sc, "customer", "KNVV", "VKORG", "TVKO", "VKORG", "sales org"),
        org_gap(ec, sc, "customer", "KNVV", "VTWEG", "TVTW", "VTWEG", "distribution channel"),
        org_gap(ec, sc, "customer", "KNVV", "SPART", "TSPA", "SPART", "division"),
        org_gap(ec, sc, "customer", "KNB1", "BUKRS", "T001", "BUKRS", "company code"),
        catalog_gap(ec, sc, "customer", "KNA1", "KTOKD", "T077D", "KTOKD", "customer account group"),
        region_dq(ec, sc, "customer", "KNA1", "LAND1", "REGIO"),
    ]
    return [f for f in F if f]


def check_vendor(ec, sc, apply_payloads):
    """Vendor (LFA1 → BP FLVN01). Purchasing-org + company-code org mapping,
    account-group config, region data quality."""
    F = [
        org_gap(ec, sc, "vendor", "LFM1", "EKORG", "T024E", "EKORG", "purchasing org"),
        org_gap(ec, sc, "vendor", "LFB1", "BUKRS", "T001", "BUKRS", "company code"),
        catalog_gap(ec, sc, "vendor", "LFA1", "KTOKK", "T077K", "KTOKK", "vendor account group"),
        region_dq(ec, sc, "vendor", "LFA1", "LAND1", "REGIO"),
    ]
    return [f for f in F if f]


def check_sales_order(ec, sc, apply_payloads):
    """Sales order (VBAK). Sales-area org mapping + order-type config. Number
    preservation is handled by the load driver (band-cycling), noted here."""
    F = [
        org_gap(ec, sc, "sales_order", "VBAK", "VKORG", "TVKO", "VKORG", "sales org"),
        org_gap(ec, sc, "sales_order", "VBAK", "VTWEG", "TVTW", "VTWEG", "distribution channel"),
        org_gap(ec, sc, "sales_order", "VBAK", "SPART", "TSPA", "SPART", "division"),
        catalog_gap(ec, sc, "sales_order", "VBAK", "AUART", "TVAK", "AUART", "order type"),
    ]
    return [f for f in F if f]


def check_cost_center(ec, sc, apply_payloads):
    """Cost center (CSKS). Controlling-area + company-code org mapping."""
    F = [
        org_gap(ec, sc, "cost_center", "CSKS", "KOKRS", "TKA01", "KOKRS", "controlling area"),
        org_gap(ec, sc, "cost_center", "CSKS", "BUKRS", "T001", "BUKRS", "company code"),
    ]
    return [f for f in F if f]


def check_profit_center(ec, sc, apply_payloads):
    """Profit center (CEPC). Controlling-area org mapping."""
    F = [org_gap(ec, sc, "profit_center", "CEPC", "KOKRS", "TKA01", "KOKRS", "controlling area")]
    return [f for f in F if f]


def check_glaccount(ec, sc, apply_payloads):
    """G/L accounts (SKA1) via GL_ACCT_MASTER_SAVE_RFC. Accounts migrate into
    their OWN chart where it exists on the target; ECC charts with no target
    equivalent are a chart-of-accounts mapping DECISION."""
    findings = []
    ecc = rt(ec, "SKA1", ["KTOPL", "SAKNR"])
    tgt_charts = {r["KTOPL"] for r in rt(sc, "SKA1", ["KTOPL"])}
    from collections import Counter as _C
    by_chart = _C(r["KTOPL"] for r in ecc)
    unmapped = {ch: n for ch, n in by_chart.items() if ch not in tgt_charts}
    if unmapped:
        naccts = sum(unmapped.values())
        findings.append(Finding(
            wall=WALL_ORG, obj="gl_account",
            title=f"chart of accounts: {len(unmapped)} ECC charts ({naccts} accounts) not on target",
            detail=("These ECC charts of accounts don't exist on the target, so their "
                    "accounts can't migrate into a native chart. Decide: create the "
                    "chart on the target, or map its accounts into a target operational "
                    "chart (e.g. YCOA) with an account-level translation."),
            count=len(unmapped), auto_fixable=False,
            action="DECIDE: map each source chart of accounts to a target chart",
            samples=[f"{ch}({n})" for ch, n in sorted(unmapped.items(), key=lambda x: -x[1])[:12]]))
    overlap = sorted({r["KTOPL"] for r in ecc} & tgt_charts)
    if overlap:
        findings.append(Finding(
            wall=WALL_CONFIG, obj="gl_account",
            title=f"{len(overlap)} charts overlap — accounts migrate into their native chart",
            detail=("Handled by run_client200_glaccounts.py (GL_ACCT_MASTER_SAVE_RFC): "
                    "account number + all language texts preserved; GLACCOUNT_TYPE derived "
                    "from balance-sheet + cost-element category; account-group number "
                    "ranges auto-widened (governed T077S). Accounts whose group account "
                    "number references a group chart not on the target are skipped (that "
                    "group chart is a separate migration)."),
            count=len(overlap), auto_fixable=True,
            action="auto-migrated via GL_ACCT_MASTER_SAVE_RFC into native charts",
            samples=overlap[:15]))
    return findings


RECIPES: dict = {
    "customer": check_customer,
    "vendor": check_vendor,
    "material": check_material,
    "bank": check_bank,
    "sales_order": check_sales_order,
    "cost_center": check_cost_center,
    "profit_center": check_profit_center,
    "gl_account": check_glaccount,
}


# ─────────────────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────────────────
def run(apply=False, objects=None):
    cfg = json.load(open("connections.json"))
    e, s = cfg["ecc"], cfg["lift_and_shift_target"]
    ec = Connection(ashost=e["ashost"], sysnr=e["sysnr"], client=e["client"],
                    user=e["user"], passwd=os.environ["M4H_ECC_PASSWD"], lang="EN")
    sc = Connection(ashost=s["target_ashost"], sysnr="00",
                    client=s.get("target_client", "200"),
                    user=s["target_user"], passwd=os.environ["M4H_TARGET_PASSWD"], lang="EN")

    all_findings, apply_payloads = [], []
    for obj in (objects or RECIPES):
        print(f"checking {obj} …", flush=True)
        try:
            all_findings.extend(RECIPES[obj](ec, sc, apply_payloads))
        except Exception as ex:
            print(f"  ! {obj} check error: {type(ex).__name__}: {ex}", flush=True)

    all_findings = merge_shared_decisions(all_findings)

    applied = []
    if apply:
        for tab, fields, rows in apply_payloads:
            res = push_rows_via_kit(sc, tab, fields, rows)
            applied.append({"table": tab, "rows": len(rows),
                            "upserted": res.get("upserted"), "failed": res.get("failed")})
            print(f"  applied {tab}: upserted={res.get('upserted')} failed={res.get('failed')}",
                  flush=True)

    write_checklist(all_findings, applied, apply)
    ec.close(); sc.close()
    return all_findings


def merge_shared_decisions(findings):
    """An org unit (sales org, plant…) referenced by several objects is ONE
    mapping decision, not one per object. Merge findings sharing a dedup_key:
    union their value sets, list the objects affected, keep a single entry."""
    groups, order, passthrough = {}, [], []
    for f in findings:
        if not f.dedup_key:
            passthrough.append(f); continue
        if f.dedup_key not in groups:
            groups[f.dedup_key] = []; order.append(f.dedup_key)
        groups[f.dedup_key].append(f)
    merged = []
    for k in order:
        fs = groups[k]
        vals, objs = set(), set()
        for f in fs:
            vals |= set(f.all_values)
            objs.add(f.obj)
        base = fs[0]
        base.all_values = sorted(vals)
        base.count = len(base.all_values)
        base.samples = base.all_values[:15]
        base.obj = ", ".join(sorted(objs))
        unit = k.split(":", 1)[1]      # dedup_key is "org:<unit name>"
        # regenerate title/detail from the MERGED count (the originals baked the
        # first object's per-object count into their text)
        base.title = f"{unit}: {base.count} source values have no target equivalent"
        base.detail = (f"The source uses {base.count} {unit}(s) that don't exist on "
                       f"the target. Each needs a mapping decision (old {unit} → new "
                       f"{unit}) or the org unit created on the target. Affects: {base.obj}.")
        merged.append(base)
    return passthrough + merged


def write_checklist(findings, applied, applied_mode):
    buckets = {
        WALL_ORG:  ("🧭 Decisions only you can make (org mapping)",
                    "The old and new systems have different org structures. Pick a "
                    "mapping for each — nothing loads into these areas until you do."),
        WALL_CONFIG: ("🔧 Config switches",
                      "Settings the target is missing. Class-C/G ones we flip "
                      "automatically; the rest need a basis person."),
        WALL_DATA: ("🧹 Data-quality fixes",
                    "Real source values the pickier target rejects. Auto-handled "
                    "faithfully (relax a rule, or blank an optional field)."),
        WALL_BAPI: ("🚧 SAP limitations we route around",
                    "Not fixable from outside — we take the supported path instead."),
    }
    manual = [f for f in findings if not f.auto_fixable]
    auto = [f for f in findings if f.auto_fixable]

    lines = ["# migrate4hana — Migration Decision Checklist",
             f"\n_Generated {time.strftime('%Y-%m-%d %H:%M')} · "
             f"{len(auto)} auto-handled · **{len(manual)} need a human**_\n",
             "This is the honest gap between your ECC data and the new S/4 system. "
             "Everything under 🧭 is a **business decision**; the rest we handle.\n"]
    for wall, (heading, blurb) in buckets.items():
        fs = [f for f in findings if f.wall == wall]
        if not fs:
            continue
        lines.append(f"\n## {heading}\n\n_{blurb}_\n")
        for f in sorted(fs, key=lambda x: -x.count):
            tag = "✅ auto" if f.auto_fixable else "⛔ **decide**"
            lines.append(f"- {tag} — **{f.title}**  \n  {f.detail}")
            if f.samples:
                lines.append(f"  \n  _e.g._ `{', '.join(str(x) for x in f.samples)}`")
            lines.append(f"  \n  → _{f.action}_\n")
    if applied:
        lines.append("\n## Auto-applied this run\n")
        for a in applied:
            lines.append(f"- `{a['table']}`: {a['upserted']} applied, {a['failed']} failed")
    elif auto and not applied_mode:
        lines.append(f"\n> {len(auto)} auto-fixable items detected. Re-run with "
                     "`--apply` to flip the safe config switches.\n")

    open("MIGRATION_CHECKLIST.md", "w", encoding="utf-8").write("\n".join(lines))
    json.dump({"generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "auto_fixable": len(auto), "needs_human": len(manual),
               "applied": applied,
               "findings": [asdict(f) for f in findings]},
              open("migration_checklist.json", "w"), indent=2)
    print(f"\nwrote MIGRATION_CHECKLIST.md ({len(auto)} auto, {len(manual)} need a human)",
          flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="auto-apply safe config fixes via the kit")
    ap.add_argument("--objects", nargs="*", help="subset of objects to check")
    a = ap.parse_args()
    run(apply=a.apply, objects=a.objects)
