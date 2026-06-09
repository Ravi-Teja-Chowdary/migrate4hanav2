"""
load-gemini-to-ecc.py -- push the gemini-data-gen.py output CSVs into
local ECC via direct pyrfc.

Mirrors what the AWS path does (extract -> light cleanse -> BAPI ->
commit -> classify) but with no AWS detour so this workstation can
drive the load.

Two object types:

  * KNA1 customers via BAPI_CUSTOMER_CREATEFROMDATA1 (classic ECC,
    pre-CVI). Internal numbering -- we capture the assigned KUNNR.
  * MARA materials via BAPI_MATERIAL_SAVEDATA. External MATNR (the
    LEG keys from the generator are passed through verbatim).

Per-record output:
  - source_key (the LEG id from the CSV)
  - sap_target_key (KUNNR / MATNR returned by the BAPI, or "")
  - disposition (created / matched_existing / dead_letter)
  - dead_letter_code (DQ_REJECTION / BAPI_FAILURE / EXISTS / "")
  - sap_message (concatenated MTYPE/MESSAGE from RETURN)

Writes the per-row dispositions to scripts/load-gemini-disposition.csv
so you can grep / count / pivot in Excel.

This is the "push the dirty data, see what SAP catches" run -- light
cleanse only (NULL-safe trimming and key uppercasing). The DQ engine
+ value-mapping matrix that F4 exposes is INTENTIONALLY bypassed
because the point of this run is to characterize raw-SAP rejection
behavior on the dirty corpus, so you can see what the F4 layer
prevents when it's later turned on.

Usage:
    python scripts/load-gemini-to-ecc.py
    python scripts/load-gemini-to-ecc.py --limit 50         # sample run
    python scripts/load-gemini-to-ecc.py --only customers
    python scripts/load-gemini-to-ecc.py --only materials
    python scripts/load-gemini-to-ecc.py --commit-every 25  # default

ENV vars consumed:
    M4H_ECC_HOST    default 192.168.100.154
    M4H_ECC_SYSNR   default 41
    M4H_ECC_CLIENT  default 800
    M4H_ECC_USER    default sapuser
    M4H_ECC_PASSWD  default India123 (this is the dev/IDES password)
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path

from pyrfc import Connection, ABAPApplicationError, ABAPRuntimeError, CommunicationError


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS   = REPO_ROOT / "scripts"

KNA1_CSV  = SCRIPTS / "dirty_kna1.csv"
MARA_CSV  = SCRIPTS / "dirty_mara.csv"
DISP_CSV  = SCRIPTS / "load-gemini-disposition.csv"

# Discovered at startup -- which BAPI flavor (if any) attaches the customer
# role under CVI on this system. None of them on this ECC EHP7. Cache so the
# per-row loader doesn't repeatedly burn RFC roundtrips on FU_NOT_FOUND.
_ROLE_BAPI_NAME: str | None = None
_ROLE_BAPI_PROBED: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _open_conn() -> Connection:
    return Connection(
        ashost = os.environ.get("M4H_ECC_HOST",  "192.168.100.154"),
        sysnr  = os.environ.get("M4H_ECC_SYSNR", "41"),
        client = os.environ.get("M4H_ECC_CLIENT", "800"),
        user   = os.environ.get("M4H_ECC_USER",  "sapuser"),
        passwd = os.environ.get("M4H_ECC_PASSWD", "India123"),
    )


def _trim(v) -> str:
    """Trim + collapse repeated whitespace; never returns None."""
    if v is None:
        return ""
    return " ".join(str(v).strip().split())


def _msgs_to_disposition(ret_rows: list) -> tuple[str, str, str]:
    """Walk a SAP BAPI RETURN list and classify.

    Returns (disposition, dead_letter_code, combined_message_text).
    """
    if not ret_rows:
        return "created", "", ""
    txts = []
    severities = set()
    msg_ids = set()
    for r in ret_rows:
        mtype = (r.get("TYPE") or "").upper()
        msgid = (r.get("ID") or "").strip()
        msgno = (r.get("NUMBER") or "").strip()
        text  = (r.get("MESSAGE") or "").strip()
        severities.add(mtype)
        msg_ids.add(f"{msgid}{msgno}")
        txts.append(f"{mtype}:{msgid}/{msgno} {text}")
    combined = " || ".join(txts)[:1200]

    # E or A in any row = hard failure
    if "E" in severities or "A" in severities:
        # Distinguish "already exists" vs "BAPI failure". Must NOT match
        # "does not exist" -- only positive existence hints.
        low = combined.lower()
        if ("already exist" in low
                or "already created" in low
                or "is already" in low):
            return "matched_existing", "EXISTS", combined
        return "dead_letter", "BAPI_FAILURE", combined
    return "created", "", combined


# ─────────────────────────────────────────────────────────────────────────────
# KNA1 loader
# ─────────────────────────────────────────────────────────────────────────────
def _load_customer(conn: Connection, row: dict) -> tuple[str, str, str, str]:
    """Push one KNA1 row via the BP-led path.

    The classic BAPI_CUSTOMER_CREATEFROMDATA1 is blocked on this system
    (CVI active -- customer numbering is BP-led). The pattern matches
    lambda/utils/customer_spine.py:

       1. BAPI_BUPA_CREATE_FROM_DATA (PARTNERCATEGORY=2, organization name)
       2. BAPI_BUPA_ROLES_CHANGE / _ADD_2 to attach FLCU01 (sold-to)
       3. The BP number IS the customer number under CVI; KNA1 mirrors

    Returns (sap_target_key, disposition, dead_letter_code, sap_message).
    """
    name1 = _trim(row.get("NAME1"))
    if not name1:
        return "", "dead_letter", "DQ_REJECTION", "NAME1 is blank (DQ)"

    try:
        resp = conn.call(
            "BAPI_BUPA_CREATE_FROM_DATA",
            PARTNERCATEGORY         = "2",
            CENTRALDATAORGANIZATION = {"NAME1": name1[:40]},
        )
    except (ABAPApplicationError, ABAPRuntimeError, CommunicationError) as e:
        return "", "dead_letter", "BAPI_FAILURE", f"{type(e).__name__}: {str(e)[:400]}"

    ret_rows = resp.get("RETURN") or []
    if isinstance(ret_rows, dict):
        ret_rows = [ret_rows] if ret_rows.get("TYPE") else []
    disp, dl, msg = _msgs_to_disposition(ret_rows)
    bp = (resp.get("BUSINESSPARTNER") or "").strip()

    if disp != "created" or not bp:
        try:
            conn.call("BAPI_TRANSACTION_ROLLBACK")
        except Exception:
            pass
        if not bp and disp == "created":
            return "", "dead_letter", "BAPI_NO_KEY", msg
        return "", disp, dl, msg

    # Attach the customer (FLCU01) role IFF this system has a working
    # role-assignment BAPI. The probe happens once at startup; per-row we
    # only invoke a BAPI we already know exists.
    role_note = ""
    if _ROLE_BAPI_NAME:
        try:
            rresp = conn.call(_ROLE_BAPI_NAME,
                               BUSINESSPARTNER = bp,
                               ROLES = [{"PARTNERROLE": "FLCU01"}])
            rret = rresp.get("RETURN") or []
            if isinstance(rret, dict):
                rret = [rret] if rret.get("TYPE") else []
            r_hard = [r for r in rret if (r.get("TYPE") or "").upper() in ("E", "A")]
            if r_hard:
                role_note = f"role: {(r_hard[0].get('MESSAGE') or '')[:80]}"
        except Exception as e:
            role_note = f"role: {str(e).splitlines()[0][:80]}"
    else:
        role_note = "role: BAPI unavailable on this system (BP=customer under CVI)"

    try:
        conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
    except Exception as e:
        return bp, "dead_letter", "COMMIT_FAILURE", f"commit raised: {e}"

    msg = (msg + " || " + role_note) if msg else role_note
    return bp, "created", "", msg[:1200]


# ─────────────────────────────────────────────────────────────────────────────
# MARA loader
# ─────────────────────────────────────────────────────────────────────────────
def _load_material(conn: Connection, row: dict) -> tuple[str, str, str, str]:
    """Push one MARA row via BAPI_MATERIAL_SAVEDATA.

    Returns (sap_target_key, disposition, dead_letter_code, sap_message).
    """
    matnr = _trim(row.get("MATNR")).upper()
    mtart = _trim(row.get("MTART")).upper()
    meins = _trim(row.get("MEINS")).upper()
    mbrsh = _trim(row.get("MBRSH")).upper() or "M"
    maktx = _trim(row.get("MAKTX"))
    if not matnr or not mtart:
        return "", "dead_letter", "DQ_REJECTION", "MATNR or MTART blank"
    if not meins:
        return "", "dead_letter", "DQ_REJECTION", "MEINS blank after trim (was whitespace)"

    headdata = {
        "MATERIAL":     matnr,
        "IND_SECTOR":   mbrsh,
        "MATL_TYPE":    mtart,
        "BASIC_VIEW":   "X",
    }
    try:
        brgew = float(row.get("BRGEW") or 0.0)
    except ValueError:
        brgew = 0.0
    gewei = _trim(row.get("GEWEI")).upper() or "KG"

    clientdata  = {
        "BASE_UOM":   meins,
        "NET_WEIGHT": brgew,
        "UNIT_OF_WT": gewei,
    }
    clientdatax = {
        "BASE_UOM":   "X",
        "NET_WEIGHT": "X",
        "UNIT_OF_WT": "X",
    }

    descs = [{"LANGU": "E", "MATL_DESC": maktx[:40]}] if maktx else []

    try:
        result = conn.call(
            "BAPI_MATERIAL_SAVEDATA",
            HEADDATA            = headdata,
            CLIENTDATA          = clientdata,
            CLIENTDATAX         = clientdatax,
            MATERIALDESCRIPTION = descs,
        )
    except (ABAPApplicationError, ABAPRuntimeError, CommunicationError) as e:
        return "", "dead_letter", "BAPI_FAILURE", f"{type(e).__name__}: {str(e)[:400]}"

    ret  = result.get("RETURN") or {}
    if isinstance(ret, dict):
        ret_rows = [ret]
    else:
        ret_rows = list(ret)
    disp, dl, msg = _msgs_to_disposition(ret_rows)
    sap_key = (result.get("MATERIALNUMBER") or matnr).strip()

    if disp == "created":
        try:
            conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception as e:
            return sap_key, "dead_letter", "COMMIT_FAILURE", f"commit raised: {e}"
    else:
        try:
            conn.call("BAPI_TRANSACTION_ROLLBACK")
        except Exception:
            pass

    return sap_key, disp, dl, msg


# ─────────────────────────────────────────────────────────────────────────────
# Main driver
# ─────────────────────────────────────────────────────────────────────────────
def _stream_csv(path: Path, limit: int | None):
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if limit is not None and i >= limit:
                return
            yield row


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None,
                    help="cap rows per CSV (sample run)")
    p.add_argument("--only", choices=["customers", "materials"], default=None,
                    help="restrict to one object type")
    args = p.parse_args()

    if not KNA1_CSV.exists() or not MARA_CSV.exists():
        print(f"[FATAL] missing input CSVs.\n"
              f"  expected: {KNA1_CSV}\n"
              f"  expected: {MARA_CSV}\n"
              f"  run scripts/gemini-data-gen.py first.")
        sys.exit(2)

    print(f"[INFO] Opening ECC connection (host={os.environ.get('M4H_ECC_HOST', '192.168.100.154')} "
            f"sysnr={os.environ.get('M4H_ECC_SYSNR', '41')} "
            f"client={os.environ.get('M4H_ECC_CLIENT', '800')})")
    t0 = time.time()
    conn = _open_conn()
    print(f"[INFO] Connected in {time.time()-t0:.2f}s")

    # ── Probe which role-assignment BAPI exists. Saves N*2 RFC roundtrips
    #    on FU_NOT_FOUND per customer create. None on this ECC EHP7.
    global _ROLE_BAPI_NAME, _ROLE_BAPI_PROBED
    if args.only != "materials":
        for fm in ("BAPI_BUPA_ROLES_CHANGE", "BAPI_BUPA_ROLES_ADD_2"):
            try:
                conn.call("RFC_GET_FUNCTION_INTERFACE", FUNCNAME=fm)
                _ROLE_BAPI_NAME = fm
                break
            except Exception:
                continue
        _ROLE_BAPI_PROBED = True
        print(f"[INFO] Role-BAPI probe: "
              + (f"using {_ROLE_BAPI_NAME}" if _ROLE_BAPI_NAME else "NONE available -- BP=customer under CVI"))

    disp_f = DISP_CSV.open("w", encoding="utf-8", newline="")
    disp_w = csv.writer(disp_f)
    disp_w.writerow(["object", "source_key", "sap_target_key",
                      "disposition", "dead_letter_code", "sap_message"])

    summary = {
        "customers": {"attempted": 0, "created": 0, "matched_existing": 0,
                       "dead_letter": 0, "elapsed_sec": 0.0},
        "materials": {"attempted": 0, "created": 0, "matched_existing": 0,
                       "dead_letter": 0, "elapsed_sec": 0.0},
    }

    try:
        # ── Customers ────────────────────────────────────────────────────────
        if args.only != "materials":
            print(f"\n[CUSTOMERS] streaming {KNA1_CSV.name}"
                  + (f" (limit={args.limit})" if args.limit else ""))
            t0 = time.time()
            for i, row in enumerate(_stream_csv(KNA1_CSV, args.limit), start=1):
                summary["customers"]["attempted"] += 1
                src = (row.get("KUNNR") or "").strip()
                sap_key, disp, dl, msg = _load_customer(conn, row)
                summary["customers"][disp] += 1
                disp_w.writerow(["Customer", src, sap_key, disp, dl, msg])
                if i % 100 == 0:
                    rps = i / max(time.time() - t0, 0.001)
                    s = summary["customers"]
                    print(f"  [{i}] rps={rps:6.2f}/s  "
                          f"created={s['created']}  "
                          f"matched={s['matched_existing']}  "
                          f"dead_letter={s['dead_letter']}")
            summary["customers"]["elapsed_sec"] = time.time() - t0

        # ── Materials ────────────────────────────────────────────────────────
        if args.only != "customers":
            print(f"\n[MATERIALS] streaming {MARA_CSV.name}"
                  + (f" (limit={args.limit})" if args.limit else ""))
            t0 = time.time()
            for i, row in enumerate(_stream_csv(MARA_CSV, args.limit), start=1):
                summary["materials"]["attempted"] += 1
                src = (row.get("MATNR") or "").strip()
                sap_key, disp, dl, msg = _load_material(conn, row)
                summary["materials"][disp] += 1
                disp_w.writerow(["Material", src, sap_key, disp, dl, msg])
                if i % 100 == 0:
                    rps = i / max(time.time() - t0, 0.001)
                    s = summary["materials"]
                    print(f"  [{i}] rps={rps:6.2f}/s  "
                          f"created={s['created']}  "
                          f"matched={s['matched_existing']}  "
                          f"dead_letter={s['dead_letter']}")
            summary["materials"]["elapsed_sec"] = time.time() - t0
    finally:
        disp_f.close()
        try:
            conn.close()
        except Exception:
            pass

    print("\n" + "=" * 72)
    print(f"SUMMARY  (disposition CSV: {DISP_CSV.relative_to(REPO_ROOT)})")
    print("=" * 72)
    for obj in ("customers", "materials"):
        if args.only and args.only != obj:
            continue
        s = summary[obj]
        if s["attempted"] == 0:
            continue
        succ_pct = 100.0 * s["created"] / s["attempted"]
        print(f"  {obj.upper():9s}  attempted={s['attempted']}  "
              f"created={s['created']} ({succ_pct:.1f}%)  "
              f"matched={s['matched_existing']}  "
              f"dead_letter={s['dead_letter']}  "
              f"elapsed={s['elapsed_sec']:.1f}s  "
              f"rps={s['attempted']/max(s['elapsed_sec'], 0.001):.2f}/s")
    print("=" * 72)


if __name__ == "__main__":
    main()
