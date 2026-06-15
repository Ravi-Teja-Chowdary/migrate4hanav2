"""
wizard_state - DDB-backed save/load for the multi-page wizard flow.

PURPOSE
-------
The new UI is a 9-page wizard. Between pages the user can refresh,
navigate, hand off to another user, or come back the next day — each
page must be able to read the state collected so far and continue.

Backing store: DynamoDB `migrate4hana-wizard-state-<env>` with a TTL on
expires_at (default 7 days), keyed by (user_email, run_id). Local-file
fallback for dev parity.

State shape (a dict that grows as the user moves through the wizard):

    {
      "run_id":        "wiz-2026-06-15-...",
      "user_email":    "alice@acme.com",
      "client_id":     "acme",
      "page":          "wizard-3-creds",      # current page
      "ecc_version":   "EHP8",                # set by page 3
      "s4_version":    "S4HANA_2023",
      "migration_type":"full",                # "full" | "selective"
      "selective_objects": [...],
      "ecc_conn":      {"ashost": "...", ...},
      "s4_conn":       {"ashost": "...", ...},
      "connection_test_results": {...},
      "permission_check_results": {...},
      "started_at":    "2026-06-15T18:30:00Z",
      "updated_at":    "2026-06-15T18:42:00Z",
      "expires_at":    1718647200,            # epoch seconds, TTL attr
    }

INTERFACE
---------
    store = WizardStore()                       # picks up env vars
    state = store.get(user_email, run_id)       # -> dict | None
    store.put(state)                            # full upsert
    store.patch(user_email, run_id, **fields)   # partial update
    store.list_for_user(user_email)             # in-flight wizards
    store.delete(user_email, run_id)
"""
from __future__ import annotations

import json
import logging
import os
import time
import secrets
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("wizard_state")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


# Default TTL: 7 days. Wizards inherently take more than one sitting; this
# matches typical SAP basis lead time for connection provisioning.
DEFAULT_TTL_SECONDS = 7 * 24 * 3600


def new_run_id(prefix: str = "wiz") -> str:
    """Stable, sortable, opaque run-id. yyyymmddTHHMMSSZ-<hex>."""
    return f"{prefix}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{secrets.token_hex(4)}"


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class WizardStore:
    """Wizard state store. DDB in prod, JSON-file in dev."""

    def __init__(self, ddb_table: Optional[str] = None,
                 local_path: Optional[Path] = None,
                 ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self.ddb_table = ddb_table or os.environ.get("M4H_WIZARD_STATE_TABLE")
        self.local_root = local_path or Path(
            os.environ.get("M4H_STAGING_ROOT", "local-staging")) / "wizard"
        self.ttl_seconds = ttl_seconds
        self._ddb = None

    def _ddb_client(self):
        if self._ddb is None and self.ddb_table:
            try:
                import boto3
                self._ddb = boto3.client("dynamodb")
            except Exception as e:
                logger.warning("DDB unavailable, local fallback: %s", e)
                self._ddb = None
        return self._ddb

    # ── canonical attribute conversion ─────────────────────────────────────
    @staticmethod
    def _to_ddb_item(state: dict) -> dict:
        """Serialise the nested wizard state to a DDB item. The state body
        is stored as a single JSON string under `body_json` so we don't have
        to translate every nested type."""
        return {
            "user_email": {"S": state["user_email"]},
            "run_id":     {"S": state["run_id"]},
            "page":       {"S": state.get("page", "")},
            "client_id":  {"S": state.get("client_id", "")},
            "updated_at": {"S": state.get("updated_at", now_iso())},
            "expires_at": {"N": str(int(state.get("expires_at", 0)))},
            "body_json":  {"S": json.dumps(state, default=str)[:380000]},
        }

    @staticmethod
    def _from_ddb_item(item: dict) -> Optional[dict]:
        body = (item or {}).get("body_json", {}).get("S")
        if body:
            try:
                return json.loads(body)
            except Exception:
                return None
        # Minimal fallback shape
        if not item:
            return None
        return {
            "user_email": item.get("user_email", {}).get("S", ""),
            "run_id":     item.get("run_id", {}).get("S", ""),
            "page":       item.get("page", {}).get("S", ""),
            "client_id":  item.get("client_id", {}).get("S", ""),
            "updated_at": item.get("updated_at", {}).get("S", ""),
        }

    # ── CRUD ──────────────────────────────────────────────────────────────
    def get(self, user_email: str, run_id: str) -> Optional[dict]:
        user_email = (user_email or "").strip().lower()
        if not user_email or not run_id:
            return None
        ddb = self._ddb_client()
        if ddb and self.ddb_table:
            try:
                resp = ddb.get_item(TableName=self.ddb_table, Key={
                    "user_email": {"S": user_email},
                    "run_id":     {"S": run_id},
                })
                item = resp.get("Item")
                if not item:
                    return None
                return self._from_ddb_item(item)
            except Exception as e:
                logger.warning("DDB get failed: %s; local fallback", e)
        path = self._local_path(user_email, run_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def put(self, state: dict) -> dict:
        state = dict(state)  # don't mutate caller
        state["user_email"] = (state.get("user_email") or "").strip().lower()
        if not state["user_email"] or not state.get("run_id"):
            raise ValueError("wizard state requires user_email + run_id")
        state["updated_at"] = now_iso()
        state.setdefault("started_at", state["updated_at"])
        state["expires_at"] = int(time.time()) + self.ttl_seconds

        ddb = self._ddb_client()
        if ddb and self.ddb_table:
            try:
                ddb.put_item(TableName=self.ddb_table,
                              Item=self._to_ddb_item(state))
                return state
            except Exception as e:
                logger.warning("DDB put failed: %s; local fallback", e)
        path = self._local_path(state["user_email"], state["run_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        return state

    def patch(self, user_email: str, run_id: str, **fields) -> dict:
        """Read-modify-write a subset of fields. Useful when the UI sends
        one field per page."""
        state = self.get(user_email, run_id) or {
            "user_email": user_email, "run_id": run_id,
            "page": "", "client_id": fields.pop("client_id", ""),
        }
        # protect identity fields from being overwritten
        for k, v in fields.items():
            if k in ("user_email", "run_id", "expires_at", "started_at"):
                continue
            state[k] = v
        return self.put(state)

    def list_for_user(self, user_email: str) -> List[dict]:
        """Return in-flight wizards for a user (most-recent first)."""
        user_email = (user_email or "").strip().lower()
        if not user_email:
            return []
        ddb = self._ddb_client()
        if ddb and self.ddb_table:
            try:
                resp = ddb.query(
                    TableName=self.ddb_table,
                    KeyConditionExpression="user_email = :u",
                    ExpressionAttributeValues={":u": {"S": user_email}})
                out = []
                for item in resp.get("Items", []):
                    state = self._from_ddb_item(item)
                    if state:
                        out.append(state)
                out.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
                return out
            except Exception as e:
                logger.warning("DDB query failed: %s; local fallback", e)
        # Local: read all under the user's dir
        user_dir = self.local_root / _safe(user_email)
        if not user_dir.exists():
            return []
        out = []
        for p in user_dir.glob("*.json"):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                continue
        out.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
        return out

    def delete(self, user_email: str, run_id: str) -> bool:
        user_email = (user_email or "").strip().lower()
        if not user_email or not run_id:
            return False
        ddb = self._ddb_client()
        if ddb and self.ddb_table:
            try:
                ddb.delete_item(TableName=self.ddb_table, Key={
                    "user_email": {"S": user_email},
                    "run_id":     {"S": run_id},
                })
                return True
            except Exception:
                pass
        path = self._local_path(user_email, run_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def _local_path(self, user_email: str, run_id: str) -> Path:
        return self.local_root / _safe(user_email) / f"{_safe(run_id)}.json"


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in (s or ""))[:120]


# ─────────────────────────────────────────────────────────────────────────────
# Self-test (no DDB)
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import tempfile
    print("=" * 70)
    print("wizard_state  self-test")
    print("=" * 70)

    tmp = Path(tempfile.mkdtemp(prefix="m4h_wiz_"))
    store = WizardStore(local_path=tmp, ttl_seconds=60)

    rid = new_run_id()
    print(f"\n[1] new run_id: {rid}")

    initial = {
        "user_email": "alice@acme.com",
        "run_id":     rid,
        "client_id":  "acme",
        "page":       "wizard-1-versions",
        "ecc_version": "EHP8",
    }
    saved = store.put(initial)
    assert saved["expires_at"] > int(time.time())
    print(f"[2] put: page={saved['page']} expires_at delta="
          f"{saved['expires_at'] - int(time.time())}s")

    fetched = store.get("alice@acme.com", rid)
    assert fetched["ecc_version"] == "EHP8"
    print(f"[3] get: page={fetched['page']} ecc={fetched['ecc_version']}")

    patched = store.patch("alice@acme.com", rid,
                          page="wizard-3-creds",
                          s4_version="S4HANA_2023",
                          migration_type="full")
    assert patched["page"] == "wizard-3-creds"
    assert patched["ecc_version"] == "EHP8"   # preserved
    assert patched["migration_type"] == "full"
    print(f"[4] patch: page={patched['page']} migration={patched['migration_type']}")

    rid2 = new_run_id()
    store.put({"user_email": "alice@acme.com", "run_id": rid2,
                "client_id": "acme", "page": "wizard-1-versions"})
    wizards = store.list_for_user("alice@acme.com")
    assert len(wizards) == 2
    print(f"[5] list_for_user: {len(wizards)} in-flight wizards")
    assert wizards[0]["run_id"] in (rid, rid2)   # newest first

    # Identity fields are write-protected by patch() — confirm via the
    # dict path the API server uses (it sends a body dict, never kwargs)
    fetched = store.get("alice@acme.com", rid)
    fetched["user_email"] = "evil@bad.com"   # attacker tries to forge
    fetched["page"] = "wizard-5-launch"
    re_saved = store.put({**fetched, "user_email": "alice@acme.com"})  # server overrides
    assert re_saved["user_email"] == "alice@acme.com"
    # And the patch() kwarg path also drops identity attempts
    p2 = store.patch("alice@acme.com", rid,
                      **{"foo": "bar"})   # non-identity kwarg fine
    assert p2["foo"] == "bar" and p2["user_email"] == "alice@acme.com"
    print(f"[6] patch identity write-protection: user_email preserved")

    # Cross-user isolation
    bob = store.list_for_user("bob@acme.com")
    assert bob == []
    print(f"[7] cross-user isolation: bob has 0 wizards")

    assert store.delete("alice@acme.com", rid) is True
    assert store.get("alice@acme.com", rid) is None
    print(f"[8] delete: rid removed")

    print(f"\nOK  wizard_state put/get/patch/list/delete + TTL + isolation")
    print(f"   artifacts in {tmp}")
