"""
consent_ledger — tamper-evident signed-consent audit ledger for governed runs
(road-to-production P2-3 / UNIFIED_PLAN H1.4).

WHY
    Every write to a customer's SAP system must be traceable to an explicit human sign-off:
    who approved, what scope (which objects / company codes), when, and against which
    preflight. This is a hash-chained (append-only, tamper-evident) ledger of those consents.
    A governed run records a consent before it writes and can refuse to proceed without one.

    Each entry links to the previous by hash (SHA-256 over prev_hash + the entry body), so any
    later edit/deletion breaks the chain and `verify()` detects it — the same discipline the
    project's reconciler evidence pack uses.

API / CLI
    py -3.7 consent_ledger.py grant --signer "Jane (CFO)" --scope "GL balances cc 1010" --run RUN-1
    py -3.7 consent_ledger.py verify
    py -3.7 consent_ledger.py show
    # in code:  require_consent(scope) -> latest matching consent dict or None
"""
import os, sys, json, time, hashlib, argparse

LEDGER = os.environ.get("M4H_CONSENT_LEDGER", "consent_ledger.jsonl")
GENESIS = "0" * 64


def _hash(prev, body):
    return hashlib.sha256((prev + json.dumps(body, sort_keys=True)).encode()).hexdigest()


def _entries():
    if not os.path.exists(LEDGER):
        return []
    return [json.loads(l) for l in open(LEDGER, encoding="utf-8") if l.strip()]


def grant(signer, scope, run_id="", decision="APPROVED", preflight_ref=""):
    """Append a signed consent, chained to the previous entry."""
    ents = _entries()
    prev = ents[-1]["hash"] if ents else GENESIS
    body = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "signer": signer, "scope": scope,
            "run_id": run_id, "decision": decision, "preflight_ref": preflight_ref, "prev": prev}
    entry = dict(body, hash=_hash(prev, body))
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def verify():
    """Return (ok, message). Detects any tamper/reordering by recomputing the chain."""
    prev = GENESIS
    for i, e in enumerate(_entries()):
        body = {k: e[k] for k in ("ts", "signer", "scope", "run_id", "decision", "preflight_ref", "prev")}
        if e.get("prev") != prev or _hash(prev, body) != e.get("hash"):
            return False, f"chain broken at entry {i} (signer={e.get('signer')}, scope={e.get('scope')})"
        prev = e["hash"]
    return True, f"chain intact ({len(_entries())} consent(s))"


def require_consent(scope, decision="APPROVED"):
    """Latest consent whose scope contains `scope` (or vice-versa) with the given decision, else None.
    A governed loader calls this and refuses to write when it returns None."""
    match = None
    for e in _entries():
        if e.get("decision") != decision:
            continue
        s = e.get("scope", "")
        if scope in s or s in scope or s == "ALL":
            match = e
    return match


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("grant"); g.add_argument("--signer", required=True); g.add_argument("--scope", required=True)
    g.add_argument("--run", default=""); g.add_argument("--decision", default="APPROVED"); g.add_argument("--preflight", default="")
    sub.add_parser("verify"); sub.add_parser("show")
    a = ap.parse_args()
    if a.cmd == "grant":
        e = grant(a.signer, a.scope, a.run, a.decision, a.preflight)
        print("recorded consent: %s | %s | %s | hash=%s" % (e["ts"], e["signer"], e["scope"], e["hash"][:12]))
    elif a.cmd == "verify":
        ok, msg = verify(); print(("OK: " if ok else "TAMPER: ") + msg)
    else:
        for e in _entries():
            print("%s | %s | scope=%s | %s | %s" % (e["ts"], e["signer"], e["scope"], e["decision"], e["hash"][:12]))


if __name__ == "__main__":
    main()
