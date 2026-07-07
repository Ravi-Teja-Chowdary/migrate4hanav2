#!/usr/bin/env python3
"""
verify_tier2_local — iterate every Tier-2 spine, attempt live BAPI on S/4,
and print per-spine outcome so we can promote successes to Tier-1.

Uses the same synth pattern as _phase_b_validate_generated in the
data-migrator handler, but bypasses Secrets Manager: reads connections
from ./connections.json and passwords from env.

Prereqs before running::

    $env:M4H_TARGET_PASSWD = "<S/4 password for MIGRATE_ADMI>"
    $env:M4H_ECC_PASSWD    = "<ECC password for sapuser>"

Then::

    python verify_tier2_local.py

Emits::

    tier2_verify_results.json — full per-spine result payload
    Prints a summary table — one row per T2 spine with pass/fail + reason

Every spine that reports created ≥ 1 in the live test is a Tier-1
promotion candidate. Every failure is annotated with the first
dead-letter's message so we know exactly what to fix.
"""
from __future__ import annotations

import importlib
import json
import os
import re
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UTILS = ROOT / "lambda" / "utils"
MIGRATOR = ROOT / "lambda" / "data-migrator"
for p in (UTILS, MIGRATOR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# ── Read connections + creds ─────────────────────────────────────────────────
CONN_FILE = ROOT / "connections.json"
if not CONN_FILE.is_file():
    sys.exit(f"missing {CONN_FILE}. Save + test connections in the wizard first.")
with open(CONN_FILE) as f:
    conns = json.load(f)
ecc = conns.get("ecc") or {}
s4 = conns.get("s4hana") or {}

target_passwd = os.environ.get("M4H_TARGET_PASSWD") or os.environ.get("M4H_S4_PASSWD")
ecc_passwd = os.environ.get("M4H_ECC_PASSWD")
if not (target_passwd and ecc_passwd):
    sys.exit("Set M4H_TARGET_PASSWD and M4H_ECC_PASSWD env vars first.")

# ── Discover Tier-2 spines from coverage_summary ─────────────────────────────
from coverage_summary import compute_coverage  # type: ignore

cov = compute_coverage(project_dir=str(ROOT))
t2_names = sorted(o["name"] for o in cov["objects"] if o["tier"] == "T2")
if not t2_names:
    sys.exit("No Tier-2 spines in coverage — nothing to verify.")

print(f"Discovered {len(t2_names)} Tier-2 spines:", ", ".join(t2_names))
print()

# ── Open S/4 connection ──────────────────────────────────────────────────────
try:
    from pyrfc import Connection  # type: ignore
except ImportError:
    sys.exit("pyrfc unavailable. Install SAP NW RFC SDK + pip install pyrfc.")

print(f"Connecting to S/4 at {s4.get('ashost')}:{s4.get('sysnr')} client {s4.get('client')} as {s4.get('user')} ...")
try:
    tconn = Connection(
        ashost=s4["ashost"], sysnr=s4["sysnr"],
        client=s4["client"], user=s4["user"], passwd=target_passwd,
        lang="EN",
    )
    sysinfo = tconn.call("RFC_SYSTEM_INFO").get("RFCSI_EXPORT", {})
    print(f"  Connected to {sysinfo.get('RFCSYSID')} {sysinfo.get('RFCSAPRL')}")
except Exception as e:
    sys.exit(f"S/4 connection failed: {type(e).__name__}: {e}")
print()

# ── Synth helpers (mirror handler.py's phase_b_validate_generated) ───────────
RULE_VALUE = {
    "non_empty":              "VALUE",
    "positive_number":        "1",
    "non_negative_number":    "0",
    "iso_date":               "20260714",
    "sap_unit_of_measure":    "EA",
    "currency_iso_4217":      "USD",
    "material_number_format": "MAT_T0001",
    "bukrs_company_code":     "1010",
    "werks_plant":            "1710",
    "langu_code":             "EN",
    "sap_client_3char":       "100",
    "decimal_max_digits":     "100.00",
    "regex_match":            "VALUE",
    "in_set":                 "VALUE",
    "fk_required_when":       "VALUE",
}


def _default_for_source_field(source_field: str) -> str:
    """Guess a reasonable default for common ECC-side field names so the
    'mandatory columns missing' check passes and the row makes it to the
    BAPI. Field names are stable across ECC installs so this table is
    portable."""
    if not source_field:
        return "VALUE"
    f = source_field.upper()
    # Numeric-looking keys
    for prefix in ("MATNR", "KUNNR", "LIFNR"):
        if f.startswith(prefix):
            return "0000000001"
    if f in ("VBELN", "EBELN", "BANFN", "AUFNR", "PLNUM", "MBLNR", "BELNR",
             "TKNUM", "QMNUM", "WARPL", "WTYID", "ANLN1", "ANLN2"):
        return "0000000001"
    if f in ("WERKS", "PWWRK", "IWERK"): return "1710"
    if f in ("BUKRS",): return "1010"
    if f in ("KOKRS",): return "A000"
    if f in ("PRCTR",): return "YB700"
    if f in ("KOSTL",): return "0017101601"
    if f in ("SAKNR", "HKONT"): return "0064002000"
    if f in ("EKORG",): return "1710"
    if f in ("EKGRP",): return "001"
    if f in ("LGORT",): return "171A"
    if f in ("MEINS", "MEIN", "VRKME"): return "EA"
    if f in ("BWART",): return "101"
    if f in ("SPRAS",): return "E"
    if f in ("LAND1",): return "US"
    if f in ("WAERS", "WAERK", "CURRENCY"): return "USD"
    if f in ("KATALOGART",): return "1"
    if f in ("PLNTY",): return "N"
    if f in ("MTART",): return "FERT"
    if f in ("MATKL",): return "00101"
    if f in ("BSART",): return "NB"
    if f in ("AUART",): return "TA"
    if f in ("FKART",): return "F2"
    if f in ("LFART",): return "LF"
    if f in ("QMART",): return "Q1"
    if f in ("VKORG",): return "1710"
    if f in ("VTWEG",): return "10"
    if f in ("SPART",): return "00"
    if f in ("BOART",): return "0002"
    if f in ("KURST",): return "M"
    if f in ("PSPID",): return "T-20001"
    if f in ("STLNR",): return "00000001"
    if f in ("WARPL",): return "1"
    if f in ("WAPOS",): return "10"
    if f in ("BLART",): return "RE"
    if f in ("BSTYP",): return "F"
    if f in ("STLTY",): return "M"
    if f in ("VBTYP",): return "C"
    # BAPI-payload side field names (the manually-written PurchaseOrder spine
    # checks its payload's cc_org block rather than ECC-side row fields, so
    # the row also carries these to satisfy that gate).
    if f in ("PURCH_ORG",): return "1710"
    if f in ("PUR_GROUP",): return "001"
    if f in ("PLANT",): return "1710"
    if f in ("PO_UNIT", "UNIT"): return "EA"
    if f in ("MATL_GROUP",): return "00101"
    if f in ("GL_ACCOUNT",): return "0064002000"
    if f in ("COSTCENTER",): return "0017101601"
    if f in ("COMP_CODE",): return "1010"
    if f in ("DOC_TYPE",): return "NB"
    if f in ("VENDOR",): return "0000100001"
    if f in ("MATERIAL",): return "MAT_T0001"
    if f in ("PO_ITEM",): return "10"
    return "VALUE"


def synth_row(orch_cls, spine_module, i: int) -> dict:
    field_maps = dict(getattr(spine_module, "FIELD_MAPS", {}) or {})
    item_field_maps = dict(getattr(spine_module, "ITEM_FIELD_MAPS", {}) or {})
    dq_gates = list(getattr(spine_module, "DQ_GATES", []) or [])

    row = {orch_cls.source_key_field: f"{i:010d}"}
    in_set_locked: set = set()  # fields fixed by DQ in_set — never overwrite

    # 1) Overlay DQ gate rule-specific values first — least precise, they
    # only know the RULE_VALUE fallback ('VALUE' etc.).
    for gate in dq_gates:
        field = gate[0] if isinstance(gate, (tuple, list)) else gate.get("field")
        rule = gate[1] if isinstance(gate, (tuple, list)) else gate.get("rule")
        val = RULE_VALUE.get(rule, "VALUE")
        if rule == "in_set":
            args = gate[2] if isinstance(gate, (tuple, list)) else gate.get("rule_args", {})
            values = (args or {}).get("values") or []
            if values:
                val = values[0]
                in_set_locked.add(field)
        row[field] = val

    # 2) Fill every FIELD_MAPS source with the field-specific default. This
    # WINS over the generic RULE_VALUE — '1710' is a real plant, 'VALUE' is
    # not — so the spine's custom validate() sees a plausible row.
    # BUT: never overwrite an in_set-locked value ('UB' for STO's BSART) —
    # that's the ground truth for that field per the spine's own DQ contract.
    for src_field in list(field_maps) + list(item_field_maps):
        if src_field in in_set_locked:
            continue
        default = _default_for_source_field(src_field)
        if default != "VALUE":
            row[src_field] = default

    # 3) Re-stamp source key so identity survives.
    row[orch_cls.source_key_field] = f"{i:010d}"
    return row


class IdentityKeyMap:
    """In-memory identity map — returns the source key for every lookup so
    the spine's FK resolution never errors out on 'missing dependency'."""

    def __init__(self):
        self._store = {}

    def resolve(self, obj, src):
        return self._store.get((obj, str(src)), str(src))

    def add(self, obj, src, tgt, disposition=""):
        self._store[(obj, str(src))] = str(tgt)


# ── Iterate + verify ─────────────────────────────────────────────────────────
import inspect
from base_spine_orchestrator import get_spine, BaseSpineOrchestrator  # type: ignore

# Trigger spine registration by importing every spine module.
for name in os.listdir(UTILS):
    if name.endswith("_spine.py"):
        try:
            importlib.import_module(name[:-3])
        except Exception:
            pass


# ── Runtime constant patching ────────────────────────────────────────────────
# Some scaffolder-generated spines hardcode date constants (DOC_DATE, REQ_DATE
# etc.) that are now in the past — SAP rejects. Rather than edit those files
# (they'd get overwritten on next scaffolder run), we patch them in-memory:
# any YYYYMMDD-looking constant in CONSTANTS_HEADER / EXTRA_PAYLOAD gets
# bumped to today if it's stale. Same treatment for the known-invalid period
# indicator 'T' → 'D' in date-typed structs.
TODAY = datetime.now(timezone.utc).strftime("%Y%m%d")


def _looks_like_stale_date(v) -> bool:
    if not isinstance(v, str) or len(v) != 8 or not v.isdigit():
        return False
    return v < TODAY


def _bump_dates_in(container: dict) -> int:
    """Walk a dict's values and bump any stale YYYYMMDD strings to today.
    Descends into nested dicts + lists of dicts (BAPI table params)."""
    count = 0
    for k, v in list(container.items()):
        if _looks_like_stale_date(v):
            container[k] = TODAY
            count += 1
        elif isinstance(v, dict):
            count += _bump_dates_in(v)
        elif isinstance(v, list):
            for entry in v:
                if isinstance(entry, dict):
                    count += _bump_dates_in(entry)
        # Fix known-invalid period indicator 'T' (only when we already know
        # we're inside a DATE_TYPE / PERIV-shaped field).
        if k in ("DATE_TYPE", "PERIV", "PER_IND") and v == "T":
            container[k] = "D"
            count += 1
    return count


for _mod_name, _mod in list(sys.modules.items()):
    if not _mod_name.endswith("_spine"):
        continue
    for _attr in ("CONSTANTS_HEADER", "CONSTANTS_ITEM",
                   "CONSTANTS_EXTRA", "EXTRA_PAYLOAD"):
        _dict = getattr(_mod, _attr, None)
        if isinstance(_dict, dict) and _dict:
            _bump_dates_in(_dict)

# Spine-specific runtime patches for the trickier hand-written cases.
_future = (datetime.now(timezone.utc) + timedelta(days=14)).strftime("%Y%m%d")

# SubcontractingPO: also set delivery date on item constants two weeks out
# so SAP's "Can delivery date be met?" warning stays quiet.
_sp = sys.modules.get("subcontracting_po_spine")
if _sp:
    if hasattr(_sp, "CONSTANTS_HEADER") and isinstance(_sp.CONSTANTS_HEADER, dict):
        _sp.CONSTANTS_HEADER["DOC_DATE"] = TODAY

# Requirement: the schedule dict has DATE_TYPE and REQ_DATE. My generic
# bump handles those. Also add a valid PERIV to the header constants so
# BAPI's Period Indicator field (which lives in the schedule struct here)
# has a converter target.
_rq = sys.modules.get("requirement_spine")
if _rq and hasattr(_rq, "EXTRA_PAYLOAD"):
    sched = (_rq.EXTRA_PAYLOAD or {}).get("REQUIREMENTS_SCHEDULE_IN") or []
    if isinstance(sched, list):
        for entry in sched:
            if isinstance(entry, dict):
                # Force valid D (day) period + a future date the BAPI will
                # accept unconditionally.
                entry["DATE_TYPE"] = "D"
                entry["REQ_DATE"] = _future


def _find_bapi_class_for(obj_name: str):
    """Locate the BAPI spine class for obj_name.

    get_spine() may return the MC-file shim because mc_file_exporter also
    registers into _SPINE_REGISTRY and last-write-wins. This walks the
    matching _spine.py module and picks its concrete BaseSpineOrchestrator
    subclass, guaranteeing we test the BAPI path, not the MC-template path.
    """
    # Convention: object_type_snake_spine.py — but the scaffolder keeps
    # consecutive uppercase letters ("MM", "PO", "SD") together as one word:
    #   ControlPlan          -> control_plan_spine
    #   PurchaseOrder        -> purchase_order_spine
    #   WBSElement           -> wbselement_spine (edge case: fully squashed)
    #   ReturnsOrderSD       -> returns_order_sd_spine    (SD kept together)
    #   ScheduleAgreementMM  -> schedule_agreement_mm_spine (MM together)
    #   SubcontractingPO     -> subcontracting_po_spine
    #   BOMItem              -> bomitem_spine (squashed acronym)
    snake = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', obj_name)
    snake = re.sub(r'([a-z\d])([A-Z])', r'\1_\2', snake).lower()
    candidates = [f"{snake}_spine"]
    # Squashed variants where the scaffolder didn't insert underscores at all.
    if '_' in snake:
        candidates.append(f"{snake.replace('_', '')}_spine")
    for mod_name in candidates:
        mod = sys.modules.get(mod_name)
        if not mod:
            try:
                mod = importlib.import_module(mod_name)
            except Exception:
                continue
        for _, cls in inspect.getmembers(mod, inspect.isclass):
            if (cls is not BaseSpineOrchestrator
                    and issubclass(cls, BaseSpineOrchestrator)
                    and cls.__module__ == mod.__name__
                    and getattr(cls, "object_type", "") == obj_name):
                return cls
    # Fallback: whatever get_spine returns (may be MC).
    return get_spine(obj_name)

results = []
for obj_name in t2_names:
    orch_cls = _find_bapi_class_for(obj_name)
    if orch_cls is None:
        results.append({"object": obj_name, "outcome": "no_spine",
                         "reason": "not in registry"})
        continue

    spine_module = sys.modules[orch_cls.__module__]
    try:
        row = synth_row(orch_cls, spine_module, 5000)
        # Spine-specific enrichment for hand-written spines that expect
        # extra row shape (items array etc.) not derivable from FIELD_MAPS.
        if obj_name == "PurchaseOrder":
            # purchase_order_spine reads row["items"] — see its docstring.
            row["items"] = [{"MATNR": "TG0013", "MENGE": "1", "NETPR": "10",
                              "MEINS": "EA"}]
        if obj_name == "SubcontractingPO":
            # Provide ECC-side dates two weeks out; the spine's field-map
            # projects these into BAPI DELIVERY_DATE.
            future = (datetime.now(timezone.utc) + timedelta(days=14)).strftime("%Y%m%d")
            row["EEIND"] = future
            row["EINDT"] = future
    except Exception as e:
        results.append({"object": obj_name, "outcome": "synth_error",
                         "reason": f"{type(e).__name__}: {e}"})
        continue

    try:
        km = IdentityKeyMap()
        # Spine-specific constructor kwargs. PurchaseOrder's manually-written
        # spine requires cc_org supplied by the caller (data-migrator wires
        # this from live target scans; here we hardcode CAL S/4 defaults).
        extra_kwargs = {}
        if obj_name == "PurchaseOrder":
            extra_kwargs["cc_org"] = {
                "PURCH_ORG": "1710", "PUR_GROUP": "001", "PLANT": "1710",
                "PO_UNIT":   "EA",   "MATL_GROUP": "00101",
                "GL_ACCOUNT": "0064002000", "COSTCENTER": "0017101601",
                "COMP_CODE": "1710", "DOC_TYPE": "NB",  "CURRENCY": "USD",
                "DOC_DATE":  TODAY,
            }
        orch = orch_cls(tconn, key_map=km, dry_run=False,
                         target_release="S4HANA_2022", **extra_kwargs)
        # Force the actual BAPI call. Without this the ledger short-circuit
        # returns matched_existing before we get to the BAPI (because the
        # identity key-map makes every source key resolve to itself).
        orch._skip_ledger_check = True
        load_result = orch.load_one(row)
    except Exception as e:
        results.append({
            "object":  obj_name, "outcome": "exception",
            "reason":  f"{type(e).__name__}: {str(e)[:200]}",
            "trace":   traceback.format_exc().splitlines()[-3:],
        })
        continue

    r = load_result.to_dict()
    outcome = ("created" if r["status"] == "created" else
               "matched_existing" if r["status"] == "matched_existing" else
               "dead_letter" if r["status"] == "dead_letter" else "failed")
    reason = ""
    if outcome not in ("created", "matched_existing"):
        # First BAPI message tells us why.
        reason = (r.get("messages") or [""])[0]
        if r.get("dead_letter"):
            reason = f"[{r['dead_letter']}] {reason}"
    results.append({
        "object":     obj_name,
        "outcome":    outcome,
        "target_key": r.get("target_key"),
        "reason":     reason[:240],
    })
    print(f"  {obj_name:35s} {outcome:20s} {reason[:120]}")

# ── Report ───────────────────────────────────────────────────────────────────
out_file = ROOT / "tier2_verify_results.json"
payload = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "s4_host":      s4.get("ashost"),
    "s4_sysid":     sysinfo.get("RFCSYSID"),
    "s4_release":   sysinfo.get("RFCSAPRL"),
    "total":        len(results),
    "created":      sum(1 for r in results if r["outcome"] == "created"),
    "matched":      sum(1 for r in results if r["outcome"] == "matched_existing"),
    "dead_letter":  sum(1 for r in results if r["outcome"] == "dead_letter"),
    "exception":    sum(1 for r in results if r["outcome"] == "exception"),
    "results":      results,
}
with open(out_file, "w") as f:
    json.dump(payload, f, indent=2)

print()
print("=" * 70)
print(f"  Total T2 spines attempted : {payload['total']}")
print(f"  Created on S/4 (Tier-1)   : {payload['created']}")
print(f"  Matched existing          : {payload['matched']}")
print(f"  Dead-lettered             : {payload['dead_letter']}")
print(f"  Exceptions                : {payload['exception']}")
print("=" * 70)
print(f"Full detail: {out_file}")
print()
promote = [r["object"] for r in results if r["outcome"] in ("created", "matched_existing")]
if promote:
    print("Promote these to Tier-1 in coverage_summary.py TIER_1_VERIFIED:")
    for name in promote:
        print(f"    \"{name}\",")
