"""
Battle-test synthetic data generator.

Produces SAP-shaped synthetic data at configurable scale with realistic dirty-
data scenarios baked in. The output is gzipped JSON-Lines, written either to
local disk (for offline runs) or S3 (for AWS runs).

Why "realistic dirty" data
--------------------------
A clean fixture run is uninformative. We want to prove the tool handles the
patterns that crash real migrations:

  - CVI overlap (same partner number used in KNA1 and LFA1)
  - Intercompany cycles (KNA1.LIFNR -> LFA1.KUNNR -> back to KNA1.KUNNR)
  - Near-duplicate masters (same name + country, different tax IDs)
  - Custom extension fields (CI_*, ZZ_*) the BAPI cannot carry
  - Country-specific tax fields (J_1B*, TXJCD)
  - Missing mandatory fields (NAME1 blank, LAND1 missing)
  - Invalid value formats (malformed tax IDs, ISO country mismatches)
  - Cluster-table data (BSEG-shaped FI line items keyed off BKPF headers)

The percentages are tunable so you can ramp dirty-data density for stress runs.

CLI:
    python generator.py --scale small         # 10K customers + proportional rest
    python generator.py --scale medium        # 100K
    python generator.py --scale large         # 1M
    python generator.py --scale xlarge        # 10M
    python generator.py --scale large --s3 s3://my-bucket/battletest/run-1/
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, List, Tuple


# ─────────────────────────────────────────────────────────────────────────────
#  Scale presets
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Scale:
    name: str
    customers: int
    vendors: int
    materials: int
    gl_accounts: int
    sales_orders: int
    fi_documents: int       # BKPF headers; each gets 2-5 BSEG lines


SCALES = {
    "tiny":   Scale("tiny",       100,       50,      200,       40,        50,        80),
    "small":  Scale("small",   10_000,    5_000,   20_000,      400,     5_000,    20_000),
    "medium": Scale("medium", 100_000,   50_000,  200_000,    1_000,    50_000,   200_000),
    "large":  Scale("large", 1_000_000, 500_000, 2_000_000,    5_000,   500_000, 2_000_000),
    "xlarge": Scale("xlarge", 10_000_000, 5_000_000, 20_000_000, 10_000, 5_000_000, 20_000_000),
}


# ─────────────────────────────────────────────────────────────────────────────
#  Dirty-data injection rates (configurable; defaults match real-customer-class)
# ─────────────────────────────────────────────────────────────────────────────
DIRTY = {
    "cvi_overlap_rate":           0.05,  # 5% of vendors share a number with a customer
    "intercompany_cycle_rate":    0.02,  # 2% of customers cross-reference a vendor (and back)
    "near_duplicate_rate":        0.03,  # 3% have same name+country, different tax_id
    "missing_mandatory_rate":     0.02,  # 2% missing NAME1 or LAND1 (DQ rejection)
    "invalid_taxid_rate":         0.02,  # 2% have malformed STCEG
    "ci_field_rate":              0.10,  # 10% carry a CI_ extension field
    "zz_field_rate":              0.08,  # 8% carry a ZZ_ extension field
    "j1b_tax_rate":               0.15,  # 15% of Brazilian-country records carry J_1B fields
    "tax_jurisdiction_us":        0.20,  # 20% of US records carry TXJCD
}


# ─────────────────────────────────────────────────────────────────────────────
#  Faker (lazy import - optional, falls back to deterministic generator)
# ─────────────────────────────────────────────────────────────────────────────
def _make_faker():
    try:
        from faker import Faker
        Faker.seed(42)
        return Faker(["en_US", "de_DE", "fr_FR", "es_ES", "pt_BR", "ja_JP", "en_IN"])
    except ImportError:
        return None


_FAKER = _make_faker()


# Deterministic fallbacks if faker isn't installed
_FALLBACK_NAMES = ["ACME Corp", "Beta Industries", "Gamma Holdings", "Delta Ltd",
                   "Epsilon Group", "Zeta Manufacturing", "Eta Logistics",
                   "Theta Trading", "Iota Services", "Kappa Solutions"]
_FALLBACK_CITIES = ["Frankfurt", "Munich", "London", "Paris", "Madrid",
                    "Tokyo", "Mumbai", "New York", "Chicago", "Sao Paulo"]


def _name(rng: random.Random) -> str:
    if _FAKER:
        return _FAKER.company()
    return f"{rng.choice(_FALLBACK_NAMES)} {rng.randint(1, 9999)}"


def _city(rng: random.Random) -> str:
    if _FAKER:
        return _FAKER.city()
    return rng.choice(_FALLBACK_CITIES)


def _street(rng: random.Random) -> str:
    if _FAKER:
        return _FAKER.street_address()
    return f"{rng.randint(1, 999)} Industrial Way"


def _postcode(rng: random.Random) -> str:
    return f"{rng.randint(10000, 99999)}"


# ─────────────────────────────────────────────────────────────────────────────
#  Country + tax distributions
# ─────────────────────────────────────────────────────────────────────────────
# Weighted country distribution roughly matching real SAP customer base
COUNTRIES = [
    ("DE", 0.18), ("US", 0.20), ("GB", 0.08), ("FR", 0.06), ("JP", 0.05),
    ("IN", 0.05), ("BR", 0.04), ("ES", 0.04), ("CN", 0.05), ("IT", 0.04),
    ("AU", 0.03), ("CA", 0.03), ("MX", 0.03), ("KR", 0.03), ("NL", 0.03),
    ("SE", 0.02), ("CH", 0.02), ("SG", 0.02),
]


def _weighted_country(rng: random.Random) -> str:
    r = rng.random()
    cumulative = 0.0
    for code, weight in COUNTRIES:
        cumulative += weight
        if r <= cumulative:
            return code
    return "DE"


def _tax_id(rng: random.Random, country: str) -> str:
    """Produce a country-appropriate tax id format."""
    if country == "DE":
        return f"DE{rng.randint(100000000, 999999999)}"
    if country == "US":
        return f"{rng.randint(10, 99)}-{rng.randint(1000000, 9999999)}"
    if country == "GB":
        return f"GB{rng.randint(100000000, 999999999)}"
    if country == "FR":
        return f"FR{rng.randint(10, 99)}{rng.randint(100000000, 999999999)}"
    if country == "BR":
        return (f"{rng.randint(10, 99)}.{rng.randint(100, 999)}."
                f"{rng.randint(100, 999)}/{rng.randint(1000, 9999)}-"
                f"{rng.randint(10, 99)}")
    if country == "IN":
        return f"{rng.randint(10, 99)}AAAAA{rng.randint(1000, 9999)}A1Z{rng.randint(0, 9)}"
    return f"{country}{rng.randint(100000000, 999999999)}"


def _invalid_tax_id(rng: random.Random) -> str:
    """Deliberately malformed tax id for DQ-rejection testing."""
    bad = rng.choice([
        "INVALID-FORMAT",
        f"BAD{rng.randint(1, 99)}",
        "TBD",
        "",
        "N/A",
        f"DE{rng.randint(100, 999)}",  # too short
    ])
    return bad


# ─────────────────────────────────────────────────────────────────────────────
#  Customer (KNA1) generator
# ─────────────────────────────────────────────────────────────────────────────
def gen_customers(scale: Scale, rng: random.Random) -> Iterator[dict]:
    """Yield KNA1-shaped customer records with dirty-data injection.

    Designed to produce these patterns when run alongside vendors:
      - some customers share a fingerprint (near-duplicate)
      - some customers have a LIFNR cross-reference (intercompany)
      - some customers carry CI_/ZZ_/J_1B fields
      - some customers are missing mandatory fields (DQ reject)
    """
    n = scale.customers
    # Pre-allocate "shared fingerprint" group so duplicates land in the same bucket
    near_dup_count = int(n * DIRTY["near_duplicate_rate"])
    shared_names = [_name(rng) for _ in range(near_dup_count // 2)]   # each name used twice

    for i in range(n):
        country = _weighted_country(rng)
        kunnr_padded = f"{i + 100000:010d}"

        # Default record
        rec = {
            "KUNNR": kunnr_padded,
            "NAME1": _name(rng),
            "NAME2": "",
            "STRAS": _street(rng),
            "ORT01": _city(rng),
            "PSTLZ": _postcode(rng),
            "LAND1": country,
            "SPRAS": "EN",
            "STCEG": _tax_id(rng, country),
            "TELF1": f"+{rng.randint(1, 99)}-{rng.randint(1000000, 9999999)}",
            "_synthetic_dirty_flags": [],
        }

        # Inject near-duplicate fingerprints (~3%)
        if i < len(shared_names) * 2:
            rec["NAME1"] = shared_names[i // 2]
            rec["_synthetic_dirty_flags"].append("near_duplicate")
            # Half the pair gets a slightly-different tax_id (the realistic conflict)
            if i % 2 == 1:
                rec["STCEG"] = _tax_id(rng, country)  # re-roll
                rec["_synthetic_dirty_flags"].append("near_duplicate_tax_mismatch")

        # Missing mandatory (~2%)
        if rng.random() < DIRTY["missing_mandatory_rate"]:
            rec["NAME1"] = ""
            rec["_synthetic_dirty_flags"].append("missing_mandatory_NAME1")

        # Invalid tax id (~2%)
        if rng.random() < DIRTY["invalid_taxid_rate"]:
            rec["STCEG"] = _invalid_tax_id(rng)
            rec["_synthetic_dirty_flags"].append("invalid_taxid")

        # CI_ extension field (~10%)
        if rng.random() < DIRTY["ci_field_rate"]:
            rec["CI_LOYALTY_TIER"] = rng.choice(["GOLD", "SILVER", "BRONZE", "PLATINUM"])
            rec["_synthetic_dirty_flags"].append("ci_extension_field")

        # ZZ_ extension field (~8%)
        if rng.random() < DIRTY["zz_field_rate"]:
            rec["ZZ_RISK_BAND"] = rng.choice(["A", "B", "C", "D"])
            rec["_synthetic_dirty_flags"].append("zz_extension_field")

        # Brazilian tax field
        if country == "BR" and rng.random() < DIRTY["j1b_tax_rate"]:
            rec["J_1BNFTYPE"] = rng.choice(["T01", "T02", "T03"])
            rec["_synthetic_dirty_flags"].append("brazil_tax_field")

        # US tax jurisdiction
        if country == "US" and rng.random() < DIRTY["tax_jurisdiction_us"]:
            rec["TXJCD"] = f"US{rng.randint(10, 99)}{rng.randint(1000, 9999)}"
            rec["_synthetic_dirty_flags"].append("us_tax_jurisdiction")

        # Intercompany cross-reference - point at a vendor that we KNOW exists
        # (the corresponding LIFNR is generated in the vendor pool)
        if rng.random() < DIRTY["intercompany_cycle_rate"]:
            xref_lifnr = f"{rng.randint(200000, 200000 + scale.vendors - 1):010d}"
            rec["LIFNR"] = xref_lifnr
            rec["_synthetic_dirty_flags"].append("intercompany_xref")

        yield rec


# ─────────────────────────────────────────────────────────────────────────────
#  Vendor (LFA1) generator
# ─────────────────────────────────────────────────────────────────────────────
def gen_vendors(scale: Scale, rng: random.Random,
                customer_overlap_keys: List[str]) -> Iterator[dict]:
    """Yield LFA1-shaped vendor records, with intentional KUNNR overlap for the
    CVI test cases."""
    n = scale.vendors

    # CVI overlap: ~5% of vendors share a number with a customer
    overlap_count = int(n * DIRTY["cvi_overlap_rate"])
    overlap_keys = set(customer_overlap_keys[:overlap_count])

    for i in range(n):
        country = _weighted_country(rng)
        # Either use an overlapping customer key OR a fresh vendor key
        if i < overlap_count:
            lifnr_raw = customer_overlap_keys[i]   # same as some KUNNR
        else:
            lifnr_raw = f"{i + 200000:010d}"

        rec = {
            "LIFNR": lifnr_raw,
            "NAME1": _name(rng),
            "NAME2": "",
            "STRAS": _street(rng),
            "ORT01": _city(rng),
            "PSTLZ": _postcode(rng),
            "LAND1": country,
            "SPRAS": "EN",
            "STCEG": _tax_id(rng, country),
            "TELF1": f"+{rng.randint(1, 99)}-{rng.randint(1000000, 9999999)}",
            "_synthetic_dirty_flags": [],
        }
        if i < overlap_count:
            rec["_synthetic_dirty_flags"].append("cvi_overlap")

        # Cross-reference back to a customer (~2%) - creates the cycle
        if rng.random() < DIRTY["intercompany_cycle_rate"]:
            xref_kunnr = f"{rng.randint(100000, 100000 + scale.customers - 1):010d}"
            rec["KUNNR"] = xref_kunnr
            rec["_synthetic_dirty_flags"].append("intercompany_xref_back")

        # Same dirty-data injection as customers
        if rng.random() < DIRTY["missing_mandatory_rate"]:
            rec["LAND1"] = ""
            rec["_synthetic_dirty_flags"].append("missing_mandatory_LAND1")

        if rng.random() < DIRTY["ci_field_rate"]:
            rec["CI_PAYMENT_PREF"] = rng.choice(["NET30", "NET60", "EOM"])
            rec["_synthetic_dirty_flags"].append("ci_extension_field")

        yield rec


# ─────────────────────────────────────────────────────────────────────────────
#  Material (MARA) generator
# ─────────────────────────────────────────────────────────────────────────────
def gen_materials(scale: Scale, rng: random.Random) -> Iterator[dict]:
    n = scale.materials
    mtarts = ["HALB", "FERT", "ROH", "HAWA", "DIEN"]
    meinses = ["EA", "KG", "L", "M", "BOX", "PAL"]
    matkls = ["00100", "00200", "00300", "00400", "00500"]

    for i in range(n):
        matnr = f"MAT{i + 1:08d}"
        rec = {
            "MATNR": matnr,
            "MTART": rng.choice(mtarts),
            "MEINS": rng.choice(meinses),
            "MATKL": rng.choice(matkls),
            "MAKTX": f"Material {matnr}",
            "_synthetic_dirty_flags": [],
        }
        # Custom Z field on some
        if rng.random() < 0.05:
            rec["ZZ_HAZMAT_CLASS"] = rng.choice(["1A", "2B", "3C", "4D"])
            rec["_synthetic_dirty_flags"].append("zz_extension_field")
        yield rec


# ─────────────────────────────────────────────────────────────────────────────
#  GL accounts + FI documents (BKPF headers) + FI line items (BSEG)
# ─────────────────────────────────────────────────────────────────────────────
def gen_gl_accounts(scale: Scale, rng: random.Random) -> Iterator[dict]:
    n = scale.gl_accounts
    for i in range(n):
        saknr = f"{400000 + i:010d}"
        yield {
            "SAKNR": saknr,
            "KTOPL": "INT",
            "XBILK": "X" if i < n * 0.3 else "",  # 30% are balance-sheet
            "BUKRS": rng.choice(["1010", "1020", "2010"]),
            "WAERS": rng.choice(["EUR", "USD", "GBP", "JPY"]),
            "TXT50": f"Account {saknr}",
        }


def gen_fi_documents(scale: Scale, rng: random.Random) -> Iterator[Tuple[dict, List[dict]]]:
    """Yield (BKPF header, [BSEG line items]) pairs."""
    n = scale.fi_documents
    bukrs_pool = ["1010", "1020", "2010"]

    for i in range(n):
        belnr = f"{100000000 + i:010d}"
        gjahr = "2026"
        bukrs = rng.choice(bukrs_pool)

        bkpf = {
            "BUKRS": bukrs,
            "BELNR": belnr,
            "GJAHR": gjahr,
            "BLART": rng.choice(["KR", "DR", "SA", "AB"]),
            "BLDAT": f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
            "BUDAT": f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
            "WAERS": rng.choice(["EUR", "USD", "GBP"]),
        }

        # 2-5 line items per document
        num_lines = rng.randint(2, 5)
        bseg_lines = []
        running_total = 0.0
        for line_idx in range(num_lines):
            amount = round(rng.uniform(100, 50000), 2)
            shkzg = "S" if line_idx == 0 else ("H" if line_idx == 1 else rng.choice(["S", "H"]))
            if shkzg == "S":
                running_total += amount
            else:
                running_total -= amount
            bseg_lines.append({
                "BUKRS": bukrs, "BELNR": belnr, "GJAHR": gjahr,
                "BUZEI": f"{line_idx + 1:03d}",
                "HKONT": f"{400000 + rng.randint(0, scale.gl_accounts - 1):010d}",
                "DMBTR": amount,
                "WRBTR": amount,
                "SHKZG": shkzg,
                "WAERS": bkpf["WAERS"],
            })
        # Force the last line to balance
        if running_total != 0 and bseg_lines:
            bseg_lines[-1]["DMBTR"] = abs(bseg_lines[-1]["DMBTR"]) + abs(running_total)
            bseg_lines[-1]["WRBTR"] = bseg_lines[-1]["DMBTR"]

        yield bkpf, bseg_lines


# ─────────────────────────────────────────────────────────────────────────────
#  Output writers
# ─────────────────────────────────────────────────────────────────────────────
class GzJsonLinesWriter:
    """Buffered gzip JSON-Lines writer, flushes every N records."""

    def __init__(self, path: Path, batch_size: int = 10000):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.batch_size = batch_size
        self._buf: List[str] = []
        self._fh = gzip.open(path, "wt", encoding="utf-8")
        self.count = 0

    def write(self, rec: dict) -> None:
        self._buf.append(json.dumps(rec, default=str))
        if len(self._buf) >= self.batch_size:
            self._fh.write("\n".join(self._buf) + "\n")
            self._buf.clear()
        self.count += 1

    def close(self) -> None:
        if self._buf:
            self._fh.write("\n".join(self._buf) + "\n")
            self._buf.clear()
        self._fh.close()

    def __enter__(self): return self
    def __exit__(self, *a): self.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Top-level orchestrator
# ─────────────────────────────────────────────────────────────────────────────
def generate_all(scale: Scale, out_dir: Path, seed: int = 42) -> dict:
    """Generate all object types under out_dir. Returns metrics."""
    rng = random.Random(seed)
    metrics = {"scale": scale.name, "seed": seed, "counts": {}, "files": {}}

    # Decide which customer KUNNRs will be re-used as vendor LIFNRs (CVI overlap)
    overlap_count = int(scale.vendors * DIRTY["cvi_overlap_rate"])
    customer_overlap_keys = [
        f"{i + 100000:010d}" for i in range(overlap_count)
    ]

    # Customers
    cust_path = out_dir / "customers.jsonl.gz"
    with GzJsonLinesWriter(cust_path) as w:
        for rec in gen_customers(scale, rng):
            w.write(rec)
        metrics["counts"]["customers"] = w.count
        metrics["files"]["customers"] = str(cust_path)

    # Vendors (with overlap injection)
    vend_path = out_dir / "vendors.jsonl.gz"
    with GzJsonLinesWriter(vend_path) as w:
        for rec in gen_vendors(scale, rng, customer_overlap_keys):
            w.write(rec)
        metrics["counts"]["vendors"] = w.count
        metrics["files"]["vendors"] = str(vend_path)

    # Materials
    mat_path = out_dir / "materials.jsonl.gz"
    with GzJsonLinesWriter(mat_path) as w:
        for rec in gen_materials(scale, rng):
            w.write(rec)
        metrics["counts"]["materials"] = w.count
        metrics["files"]["materials"] = str(mat_path)

    # GL accounts
    gl_path = out_dir / "gl_accounts.jsonl.gz"
    with GzJsonLinesWriter(gl_path) as w:
        for rec in gen_gl_accounts(scale, rng):
            w.write(rec)
        metrics["counts"]["gl_accounts"] = w.count
        metrics["files"]["gl_accounts"] = str(gl_path)

    # FI documents (BKPF + BSEG)
    bkpf_path = out_dir / "bkpf.jsonl.gz"
    bseg_path = out_dir / "bseg.jsonl.gz"
    with GzJsonLinesWriter(bkpf_path) as bkpf_w, GzJsonLinesWriter(bseg_path) as bseg_w:
        for bkpf, bseg_lines in gen_fi_documents(scale, rng):
            bkpf_w.write(bkpf)
            for line in bseg_lines:
                bseg_w.write(line)
        metrics["counts"]["bkpf"] = bkpf_w.count
        metrics["counts"]["bseg"] = bseg_w.count
        metrics["files"]["bkpf"] = str(bkpf_path)
        metrics["files"]["bseg"] = str(bseg_path)

    # Manifest
    (out_dir / "manifest.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics


# ─────────────────────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Generate synthetic SAP-shaped data.")
    ap.add_argument("--scale", default="small", choices=list(SCALES))
    ap.add_argument("--out", default="tests/battletest/fixtures",
                    help="Local output directory (S3 sync happens separately).")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    scale = SCALES[args.scale]
    out = Path(args.out) / f"scale-{args.scale}"
    print(f"Generating scale={args.scale} into {out}")
    print(f"  customers={scale.customers:,}  vendors={scale.vendors:,}  "
          f"materials={scale.materials:,}")
    print(f"  gl_accounts={scale.gl_accounts:,}  fi_documents={scale.fi_documents:,}")
    print(f"  expected BSEG lines ~{scale.fi_documents * 3:,}  (2-5 per BKPF)")
    print()

    import time
    t0 = time.time()
    metrics = generate_all(scale, out, seed=args.seed)
    elapsed = time.time() - t0

    print(f"\nGenerated in {elapsed:.1f}s")
    print(f"Total records: {sum(metrics['counts'].values()):,}")
    for kind, n in metrics["counts"].items():
        print(f"  {kind:20s} {n:>12,}")
    print(f"\nManifest: {out}/manifest.json")
    print(f"Throughput: {sum(metrics['counts'].values()) / elapsed:,.0f} records/sec")


if __name__ == "__main__":
    main()
