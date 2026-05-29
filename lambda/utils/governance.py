"""
governance.py — Pillar 3: human-in-the-loop cutover gates
===========================================================
Production migrations must not run cutover-affecting phases unattended. This module
provides the *secure, code-testable* core of the governance fence that sits after
Phase 0 (ASSESS), Phase 4 (DATA-PREP), and Phase 6 (VALIDATE):

* **GateController** — creates a pending gate carrying a cryptographically **HMAC-
  signed** approval token, persists it (file-backed so a separate API process can
  resolve it), and exposes ``approve`` / ``reject`` that verify the signature in
  constant time before unfreezing the pipeline. The signature is the fence: only a
  caller holding the run's gate secret can pass it.

* **build_gate_alert / publish_alert** — a schema-validated notification payload
  (rows extracted, data-quality metrics, quarantined counts, infra telemetry +
  the signed approve URL) and an SNS publisher (boto3, infra-gated).

The actual *wait-state* is an AWS Step Functions ``TaskToken`` task (Terraform); the
runtime resume arrives at the FastAPI ``/api/spine/approve`` webhook, which calls
``GateController.approve``. Step Functions/SNS need a live AWS account to certify;
the signing, persistence, verification, and payload schema are all unit-tested here.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

GATE_POINTS = ("post_assess", "post_data_prep", "post_validate")
_DEFAULT_STORE = os.path.join(
    os.environ.get("M4H_STAGING_ROOT", "local-staging"), "spine-gates", "gates.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class GateController:
    """Create / resolve HMAC-signed human-approval gates, persisted to a JSON store."""

    def __init__(self, secret: Optional[str] = None, store_path: Optional[str] = None):
        # The gate secret is the fence. In production set M4H_GATE_SECRET (e.g. from
        # Secrets Manager); we never invent a weak default silently for a real run.
        self.secret = (secret or os.environ.get("M4H_GATE_SECRET") or
                       secrets.token_hex(32)).encode("utf-8")
        self.store_path = Path(store_path or os.environ.get("M4H_GATE_STORE") or _DEFAULT_STORE)
        self._lock = threading.Lock()
        self._gates: dict = {}
        self._load()

    # ── persistence ───────────────────────────────────────────────────────────
    def _load(self) -> None:
        try:
            if self.store_path.exists():
                self._gates = json.loads(self.store_path.read_text(encoding="utf-8")) or {}
        except (OSError, json.JSONDecodeError):
            self._gates = {}

    def _flush(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.store_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._gates, indent=2, default=str), encoding="utf-8")
        tmp.replace(self.store_path)   # atomic-ish swap so a crash can't tear the store

    # ── signing ─────────────────────────────────────────────────────────────
    def sign(self, gate_id: str) -> str:
        return hmac.new(self.secret, gate_id.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify(self, gate_id: str, signature: str) -> bool:
        if not signature:
            return False
        return hmac.compare_digest(self.sign(gate_id), str(signature))

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def create_gate(self, run_id: str, gate: str, payload: Optional[dict] = None,
                    task_token: Optional[str] = None) -> dict:
        """Open a pending gate. Returns the record incl. its signature (the token a
        stakeholder must present to ``/api/spine/approve``). ``task_token`` is the
        Step Functions wait-state token to resume (stored, used by the SF resumer)."""
        gate_id = f"{run_id}__{gate}"
        with self._lock:
            rec = {
                "gate_id": gate_id, "run_id": run_id, "gate": gate,
                "status": "pending", "created_at": _now_iso(),
                "payload": payload or {}, "task_token": task_token,
                "signature": self.sign(gate_id),
            }
            self._gates[gate_id] = rec
            self._flush()
        return rec

    def get(self, gate_id: str) -> Optional[dict]:
        with self._lock:
            return self._gates.get(gate_id)

    def list_pending(self) -> list:
        with self._lock:
            return [r for r in self._gates.values() if r.get("status") == "pending"]

    def _decide(self, gate_id: str, signature: str, status: str, decided_by: str) -> dict:
        with self._lock:
            rec = self._gates.get(gate_id)
            if rec is None:
                return {"ok": False, "error": "gate not found", "gate_id": gate_id}
            if rec["status"] != "pending":
                return {"ok": False, "error": f"gate already {rec['status']}", "gate_id": gate_id}
            if not self.verify(gate_id, signature):
                return {"ok": False, "error": "invalid signature", "gate_id": gate_id}
            rec["status"] = status
            rec["decided_by"] = decided_by or "anonymous"
            rec["decided_at"] = _now_iso()
            self._flush()
            return {"ok": True, "gate_id": gate_id, "status": status,
                    "decided_by": rec["decided_by"], "task_token": rec.get("task_token"),
                    "resume": status == "approved"}

    def approve(self, gate_id: str, signature: str, decided_by: str = "") -> dict:
        """Verify the signature and pass the fence. ``resume=True`` ⇒ the orchestrator
        (or the Step Functions resumer) may proceed past this gate."""
        return self._decide(gate_id, signature, "approved", decided_by)

    def reject(self, gate_id: str, signature: str, decided_by: str = "") -> dict:
        return self._decide(gate_id, signature, "rejected", decided_by)


# ── notification payload (schema-validated) + SNS publish (infra-gated) ──────
_REQUIRED_METRIC_KEYS = ("rows_extracted", "quarantined", "data_quality", "telemetry")


def build_gate_alert(run_id: str, gate: str, signature: str, metrics: dict,
                     approve_base_url: str = "") -> dict:
    """Build a schema-validated gate alert. Raises ValueError if a required metric
    block is missing — a gate alert with no decision context is unacceptable."""
    missing = [k for k in _REQUIRED_METRIC_KEYS if k not in (metrics or {})]
    if missing:
        raise ValueError(f"gate alert missing required metrics: {missing}")
    gate_id = f"{run_id}__{gate}"
    approve_url = (f"{approve_base_url.rstrip('/')}/api/spine/approve"
                   if approve_base_url else "/api/spine/approve")
    return {
        "schema": "m4h.gate_alert.v1",
        "gate_id": gate_id,
        "run_id": run_id,
        "gate": gate,
        "status": "pending",
        "created_at": _now_iso(),
        "metrics": {
            "rows_extracted": int(metrics["rows_extracted"]),
            "quarantined": int(metrics["quarantined"]),
            "data_quality": metrics["data_quality"],
            "telemetry": metrics["telemetry"],
        },
        "action": {
            "approve_url": approve_url,
            "body": {"gate_id": gate_id, "signature": signature, "decided_by": "<approver>"},
        },
    }


def publish_alert(alert: dict, topic_arn: Optional[str] = None,
                  region: Optional[str] = None) -> dict:
    """Publish a gate alert to SNS. Infra-gated; returns the publish result or a
    recorded error (never raises) so a notification hiccup can't crash the pipeline."""
    topic_arn = topic_arn or os.environ.get("M4H_GATE_SNS_TOPIC")
    if not topic_arn:
        return {"published": False, "reason": "no SNS topic configured"}
    try:
        import boto3
        sns = boto3.client("sns", region_name=region or os.environ.get("AWS_REGION", "us-east-1"))
        resp = sns.publish(
            TopicArn=topic_arn,
            Subject=f"[Migrate4HANA] Gate {alert['gate']} awaiting approval ({alert['run_id']})",
            Message=json.dumps(alert, indent=2, default=str),
            MessageAttributes={"gate": {"DataType": "String", "StringValue": alert["gate"]}})
        return {"published": True, "message_id": resp.get("MessageId")}
    except Exception as e:  # noqa: BLE001
        return {"published": False, "error": str(e)[:160]}


# ════════════════════════════════════════════════════════════════════════════
#  Self-test (no AWS) — gate create / sign / verify / approve + alert schema
# ════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import tempfile

    print("=" * 72)
    print("governance — self-test (HMAC-signed gates + alert schema)")
    print("=" * 72)

    store = Path(tempfile.mkdtemp(prefix="m4h_gates_")) / "gates.json"
    gc = GateController(secret="unit-test-secret", store_path=store)

    rec = gc.create_gate("RUN-9", "post_data_prep",
                         payload={"rows_extracted": 1_250_000, "quarantined": 318})
    sig = rec["signature"]
    print(f"\n[gate] created {rec['gate_id']} status={rec['status']} sig={sig[:16]}…")
    assert rec["status"] == "pending" and len(gc.list_pending()) == 1

    # wrong signature is refused; the gate stays pending (the fence holds)
    bad = gc.approve(rec["gate_id"], "deadbeef", "mallory")
    print(f"[gate] forged signature -> {bad}")
    assert not bad["ok"] and gc.get(rec["gate_id"])["status"] == "pending"

    # a *separate* controller process (the API webhook) resolves it with the real sig
    gc2 = GateController(secret="unit-test-secret", store_path=store)
    ok = gc2.approve(rec["gate_id"], sig, "cfo@corp")
    print(f"[gate] valid signature -> {ok}")
    assert ok["ok"] and ok["resume"] is True and ok["status"] == "approved"

    # re-approving an already-decided gate is refused (no double-pass)
    again = gc2.approve(rec["gate_id"], sig, "cfo@corp")
    assert not again["ok"]
    print(f"[gate] re-approve refused -> {again['error']}")

    # alert payload schema: required metric blocks enforced
    alert = build_gate_alert("RUN-9", "post_data_prep", sig, {
        "rows_extracted": 1_250_000, "quarantined": 318,
        "data_quality": {"rejected": 318, "rate": "0.025%"},
        "telemetry": {"throughput_per_sec": 9.4, "workers": 6}},
        approve_base_url="https://migrate4hana.local")
    print(f"\n[alert] schema={alert['schema']} approve_url={alert['action']['approve_url']}")
    assert alert["metrics"]["rows_extracted"] == 1_250_000
    try:
        build_gate_alert("RUN-9", "post_validate", sig, {"rows_extracted": 1})
        raise AssertionError("should have rejected incomplete metrics")
    except ValueError as e:
        print(f"[alert] incomplete metrics rejected -> {e}")

    print(f"\n[sns] publish (no topic configured) -> {publish_alert(alert)}")
    print("\nOK — gates are HMAC-fenced (forge refused, valid passes, no double-pass), "
          "cross-process via the file store, and alert payloads are schema-validated.")
