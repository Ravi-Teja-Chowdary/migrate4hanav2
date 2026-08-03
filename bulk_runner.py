"""
bulk_runner — high-volume parallel execution engine (road-to-production #4).

THE PROBLEM IT SOLVES
    The direct-API lane posts one record at a time through SAP's official APIs (that's what keeps
    it support-safe). Correct, but for tens/hundreds of thousands of records a single serial
    stream is far too slow. This engine keeps every write on the SAME official API but runs many
    of them CONCURRENTLY: a pool of independent SAP connections (one per worker thread), each
    pulling from a shared work queue, committing, and recording progress to the durable ledger.

    Why threads work with pyrfc: the SAP RFC call releases Python's GIL while it runs, so N worker
    threads each holding their OWN Connection genuinely execute N BAPI calls in parallel on the
    application server (bounded by the server's dialog work processes — SAP's own guidance is
    ~8 concurrent migration jobs, so the default pool is 8). Every worker checkpoints to the
    ledger, so a crash resumes; the run is idempotent (skip-already-migrated) as before.

    This is the CAPABILITY (parallelism + checkpoint + resume). The true throughput SLO
    (e.g. "100k open items in N hours") is measured on a data-rich system.

    py -3.7 bulk_runner.py bench --workers 8 --n 40      # measure serial vs parallel speedup
"""
import os, sys, time, threading, queue, argparse, datetime, json
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
sys.path.insert(0, os.getcwd()); sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))


def target_conn():
    """A fresh, independent target connection (each worker gets its own — pyrfc conns aren't shared)."""
    from pyrfc import Connection
    cfg = json.load(open("connections.json"))["lift_and_shift_target"]
    client = os.environ.get("M4H_TARGET_CLIENT") or cfg.get("target_client") or "200"
    return Connection(ashost=cfg["target_ashost"], sysnr=cfg.get("target_sysnr", "00"),
                      client=client, user=cfg["target_user"], passwd=os.environ["M4H_TARGET_PASSWD"], lang="EN")


class BulkPoster:
    """Parallel poster: N worker threads, each with its own SAP connection, drain a work queue.
    post_fn(conn, item) -> truthy target-ref on success / falsy on skip / raises on error.
    record_fn(item, ref) persists progress (called under a lock; keep it fast)."""
    def __init__(self, connect_fn=target_conn, workers=8):
        self.connect_fn = connect_fn
        self.workers = max(1, workers)
        self.q = queue.Queue()
        self.lock = threading.Lock()
        self.ok = 0; self.fail = 0; self.errors = []

    def _worker(self, post_fn, record_fn):
        try:
            conn = self.connect_fn()
        except Exception as e:
            with self.lock:
                self.errors.append("connect: " + str(e)[:70])
            # drain the queue so run() doesn't hang
            while True:
                if self.q.get() is None:
                    self.q.task_done(); break
                self.q.task_done()
            return
        while True:
            item = self.q.get()
            if item is None:
                self.q.task_done(); break
            try:
                ref = post_fn(conn, item)
                with self.lock:
                    if ref:
                        self.ok += 1; record_fn(item, ref)
                    else:
                        self.fail += 1
            except Exception as e:
                with self.lock:
                    self.fail += 1
                    if len(self.errors) < 20:
                        self.errors.append(str(e)[:80])
            finally:
                self.q.task_done()
        try:
            conn.close()
        except Exception:
            pass

    def run(self, items, post_fn, record_fn=lambda i, r: None):
        threads = [threading.Thread(target=self._worker, args=(post_fn, record_fn), daemon=True)
                   for _ in range(self.workers)]
        for t in threads:
            t.start()
        for it in items:
            self.q.put(it)
        for _ in threads:
            self.q.put(None)
        for t in threads:
            t.join()
        return {"ok": self.ok, "fail": self.fail, "errors": self.errors}


# ── benchmark: post throwaway balanced G/L docs to measure serial vs parallel throughput ──
def _bench_items(n, cc, acct, clearing):
    return [{"cc": cc, "acct": acct, "clearing": clearing, "amt": 1.00, "i": i} for i in range(n)]


def _post_gl_pair(conn, item):
    """A tiny balanced 2-line G/L doc (acct <-> clearing, €1) — a uniform unit of write work."""
    pd = os.environ.get("M4H_TAKEOVER_DATE") or datetime.date.today().strftime("%Y%m%d")
    hdr = {"USERNAME": "MIGRATE", "COMP_CODE": item["cc"], "DOC_DATE": pd, "PSTNG_DATE": pd,
           "DOC_TYPE": "SA", "REF_DOC_NO": "M4H-BENCH", "HEADER_TXT": "bulk bench"}
    gl = [{"ITEMNO_ACC": "0000000001", "GL_ACCOUNT": item["acct"], "ITEM_TEXT": "b"},
          {"ITEMNO_ACC": "0000000002", "GL_ACCOUNT": item["clearing"], "ITEM_TEXT": "b"}]
    am = [{"ITEMNO_ACC": "0000000001", "CURR_TYPE": "00", "CURRENCY": "EUR", "AMT_DOCCUR": "1.00"},
          {"ITEMNO_ACC": "0000000002", "CURR_TYPE": "00", "CURRENCY": "EUR", "AMT_DOCCUR": "-1.00"}]
    res = conn.call("BAPI_ACC_DOCUMENT_POST", DOCUMENTHEADER=hdr, ACCOUNTGL=gl, CURRENCYAMOUNT=am)
    if [m for m in res.get("RETURN", []) if m.get("TYPE") in ("E", "A")]:
        conn.call("BAPI_TRANSACTION_ROLLBACK"); return None
    conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
    return (res.get("OBJ_KEY", "") or "")[:10]


def bench(workers, n, cc="1010"):
    from migration_engine import Engine
    eng = Engine()
    # two splitting-classified balance-sheet accounts to bounce €1 between (uses the reconciler helper)
    import bucket3_migrate as b3
    clearing = b3._postable_clearing(eng, cc)
    ska = {r["SAKNR"].strip(): r for r in eng.read_table(eng.tgt, "SKA1", ["SAKNR", "KTOPL", "XBILK", "GLACCOUNT_TYPE"]) if r["KTOPL"].strip() == "YCOA"}
    postable = {r["SAKNR"].strip() for r in eng.read_table(eng.tgt, "SKB1", ["SAKNR", "BUKRS", "MITKZ", "XSPEB"]) if r["BUKRS"].strip() == cc and r["MITKZ"].strip() == "" and r["XSPEB"].strip() == ""}
    acct = next((a for a, r in ska.items() if r["XBILK"].strip() == "X" and r["GLACCOUNT_TYPE"].strip() == "X" and a in postable and a != clearing), "")
    eng.close()
    if not acct or not clearing:
        print("bench: no postable account pair found"); return
    print(f"bench: cc={cc} acct={acct} clearing={clearing}  posting {n} tiny docs...")
    for w in (1, workers):
        items = _bench_items(n, cc, acct, clearing)
        bp = BulkPoster(workers=w)
        t0 = time.time()
        r = bp.run(items, _post_gl_pair)
        dt = time.time() - t0
        rate = r["ok"] / dt if dt else 0
        print(f"  workers={w:<2}  posted={r['ok']}/{n}  failed={r['fail']}  wall={dt:.1f}s  rate={rate:.2f} docs/s"
              + (f"  ERR:{r['errors'][0]}" if r["errors"] else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["bench"])
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--cc", default="1010")
    a = ap.parse_args()
    if a.cmd == "bench":
        bench(a.workers, a.n, a.cc)


if __name__ == "__main__":
    main()
