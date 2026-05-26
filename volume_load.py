#!/usr/bin/env python3
"""
volume_load.py — PARALLEL mass loader to prove the spine holds at production volume.

Single-threaded FI posting is ~1 doc/sec (round-trip bound to a cloud S/4). Real volume
needs parallelism: pyrfc releases the GIL during each RFC call, so N worker threads each
with their OWN S/4 connection post concurrently -> ~N x throughput. This loads a large
batch of OpenAR financial documents in parallel, then RECONCILES every one (existence +
amount in BSID) so the scale claim is proven, not asserted.

Usage:  M4H_VOL_N=1000 M4H_VOL_WORKERS=6 python volume_load.py
Creds from env (M4H_ECC_PASSWD / M4H_TARGET_PASSWD). Read-only on the source.
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "lambda" / "utils"))
os.environ.setdefault("SAPNWRFC_HOME", str(ROOT / "sapnwrfc"))
from pyrfc import Connection            # noqa: E402
from bapi_loader import BapiLoader      # noqa: E402
from reconciler import Reconciler       # noqa: E402

N = int(os.environ.get("M4H_VOL_N", "1000"))
W = int(os.environ.get("M4H_VOL_WORKERS", "6"))
FI_ORG = {"COMP_CODE": "1710", "CLEARING_GL": "0023007000", "PROFIT_CTR": "YB600"}
CONF = json.loads((ROOT / "connections.json").read_text())
E, T = CONF["ecc"], CONF["lift_and_shift_target"]


def _conn(cfg, pw_env):
    return Connection(ashost=cfg.get("ashost") or cfg.get("target_ashost"),
                      sysnr=cfg.get("sysnr") or cfg.get("target_sysnr"),
                      client=cfg.get("client") or cfg.get("target_client"),
                      user=cfg.get("user") or cfg.get("target_user"),
                      passwd=os.environ[pw_env], lang="EN")


def main():
    print(f"VOLUME RUN: OpenAR, N={N} docs, {W} parallel workers")
    # 1) Extract N open-AR rows from the source (read-only).
    ecc = _conn(E, "M4H_ECC_PASSWD")
    f = ["BUKRS", "KUNNR", "BELNR", "DMBTR", "SHKZG", "WAERS"]
    r = ecc.call("RFC_READ_TABLE", QUERY_TABLE="BSID", DELIMITER="|",
                 FIELDS=[{"FIELDNAME": x} for x in f], ROWCOUNT=N)
    rows = [dict(zip(f, [v.strip() for v in d["WA"].split("|")])) for d in r["DATA"]]
    ecc.close()
    print(f"  extracted {len(rows)} source AR items")

    # 2) One S/4 connection + loader per worker; round-robin partition the rows.
    conns = [_conn(T, "M4H_TARGET_PASSWD") for _ in range(W)]
    loaders = [BapiLoader(c) for c in conns]
    chunks = [rows[i::W] for i in range(W)]
    out = [[] for _ in range(W)]

    def worker(wi):
        bl = loaders[wi]
        for row in chunks[wi]:
            try:
                out[wi].append(bl.create_fi_open_item(row, "AR", FI_ORG, key_map=None, commit=True))
            except Exception as e:
                out[wi].append({"status": "exception", "messages": [str(e)[:120]]})

    # 3) Post in parallel.
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=W) as ex:
        list(ex.map(worker, range(W)))
    elapsed = time.time() - t0

    allr = [x for sub in out for x in sub]
    created = [x for x in allr if x.get("status") == "created"]
    rate = round(len(created) / elapsed, 1) if elapsed else 0
    print(f"\n  POSTED {len(created)}/{len(allr)} docs in {elapsed:.1f}s "
          f"-> {rate} docs/sec ({W} workers)  | per-worker {round(rate / W, 2)}/s")
    print(f"  extrapolated: 100k docs ~ {round(100000 / rate / 60, 1)} min, "
          f"1M ~ {round(1000000 / rate / 3600, 1)} h at this parallelism")

    # 4) Reconcile EVERY created doc (existence + amount) against the target.
    rec = Reconciler(conns[0])
    load_result = {"created_in_s4": len(created),
                   "created_keys": [x["verify_key"] for x in created if x.get("verify_key")]}
    t1 = time.time()
    report = rec.reconcile("OpenAR", load_result)
    print(f"\n  RECONCILED {report['verified_in_target']}/{report['created']} "
          f"(value {report['value_matched']}/{report['value_checked']}) in {time.time()-t1:.1f}s "
          f"-> {report['status']}")
    for c in conns:
        c.close()
    print("\nVERDICT:", "VOLUME PROVEN" if report["status"] == "RECONCILED"
          and len(created) >= N * 0.9 else "REVIEW")


if __name__ == "__main__":
    main()
