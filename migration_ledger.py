"""
migration_ledger — durable "already migrated" ledger for run-twice safety (road-to-production P0-3).

THE PROBLEM IT SOLVES
    Master-data creates are net-new-guarded (skip what already exists). Balances, open items,
    inventory and notifications are NOT — re-running would POST THEM AGAIN and double the money
    (the whole-company gate P0-2 caught exactly this on repeated demo runs). Real migrations are
    run many times (test -> dry-run -> real), so every posting must be idempotent.

    This is a small, durable, JSON-backed ledger keyed by (object, source-key) -> target ref.
    A handler checks the ledger before it posts and skips anything already migrated, then records
    what it posts. Run it twice -> the second run posts nothing.

API
    led = Ledger()
    led.seen(obj, key) -> bool
    led.new_only(obj, items, keyfn) -> [items not yet migrated]   (order-preserving)
    led.record(obj, key, target="")      # then led.save() once at the end
    led.record_all(obj, {key: target})   # bulk + save

    (For production scale this same contract is what the DynamoDB key-map already implements;
    the JSON store keeps a single-box run self-contained and equally correct.)
"""
import os, json, time

LEDGER = os.environ.get("M4H_LEDGER_FILE", "migration_ledger.json")


class Ledger:
    def __init__(self, path=LEDGER):
        self.path = path
        try:
            self.data = json.load(open(path)) if os.path.exists(path) else {}
        except Exception:
            self.data = {}

    def seen(self, obj, key):
        return str(key) in self.data.get(obj, {})

    def new_only(self, obj, items, keyfn):
        """Return only items whose keyfn(item) is not yet in the ledger (order preserved)."""
        done = self.data.get(obj, {})
        return [it for it in items if str(keyfn(it)) not in done]

    def record(self, obj, key, target=""):
        self.data.setdefault(obj, {})[str(key)] = {"target": str(target), "ts": int(time.time())}

    def record_all(self, obj, mapping):
        d = self.data.setdefault(obj, {})
        for k, t in mapping.items():
            d[str(k)] = {"target": str(t), "ts": int(time.time())}
        self.save()

    def count(self, obj):
        return len(self.data.get(obj, {}))

    def save(self):
        tmp = self.path + ".tmp"
        json.dump(self.data, open(tmp, "w"), indent=0)
        os.replace(tmp, self.path)
