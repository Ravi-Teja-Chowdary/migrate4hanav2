"""
superuser_commands - Clickable CLI catalog for the root-user console.

PURPOSE
-------
The new UI gives the root user a Command Board: every CLI-equivalent
operation a basis-team-grade operator might reach for, exposed as a
clickable button with rich metadata: what it does, when to reach for it,
what happens if you click it, and any danger labels.

Each command:
  - id           short slug, used in the click URL
  - label        button text
  - what         one-line plain English
  - when         when an operator would actually use it
  - danger       "safe" | "caution" | "danger"
  - reversible   bool — does it persist data that can't be reverted?
  - params       list of {name, type, required, description} for inputs
  - runs         what backend this dispatches to (lambda invoke / shell)
  - run_target   the target id (Lambda function name, shell path, etc.)

UI contract:
  - GET /api/admin/commands               -> the catalog
  - POST /api/admin/commands/{id}/execute -> runs it (root-only)

The catalog is curated, not auto-discovered, so dangerous shell commands
don't accidentally show up in the UI.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Catalog
# ─────────────────────────────────────────────────────────────────────────────
_COMMANDS: List[dict] = [
    # ── Diagnostics (safe, read-only) ──────────────────────────────────────
    {
        "id": "health-check",
        "label": "Health check",
        "category": "Diagnostics",
        "what": "Probes every Lambda + Fargate service + DDB table for liveness "
                 "and returns a one-line green/yellow/red roll-up per component.",
        "when": "Always safe. Run first when something feels off; the result "
                 "tells you which subsystem to look at.",
        "danger": "safe",
        "reversible": True,
        "params": [],
        "runs": "lambda",
        "run_target": "migrate4hana-readiness-check",
    },
    {
        "id": "chain-verify",
        "label": "Verify hash chain",
        "category": "Diagnostics",
        "what": "Walks the HashChainLedger for the latest run and confirms every "
                 "block's prev_hash links to the previous block. Returns "
                 "broken_at + reason if a break is found.",
        "when": "Run before signing off a cutover, or when an auditor asks "
                 "'prove the ledger is intact'.",
        "danger": "safe",
        "reversible": True,
        "params": [
            {"name": "run_id", "type": "string", "required": False,
             "description": "Run to verify (default: latest)"}],
        "runs": "lambda",
        "run_target": "migrate4hana-reconciliation-engine",
    },
    {
        "id": "list-pending-gates",
        "label": "List pending gates",
        "category": "Diagnostics",
        "what": "Shows every HMAC-signed governance gate that is still in "
                 "'pending' status, sorted by created_at.",
        "when": "When a run feels stuck. A pending gate is the most common "
                 "reason the pipeline is waiting on a human.",
        "danger": "safe",
        "reversible": True,
        "params": [],
        "runs": "lambda",
        "run_target": "migrate4hana-data-migrator",
    },
    {
        "id": "spool-capture",
        "label": "Capture FAGLB03 + MB5B",
        "category": "Diagnostics",
        "what": "Triggers FAGLB03 and MB5B on the target as SAP background "
                 "jobs and seals the spool binaries into the audit chain.",
        "when": "Pre-cutover, when the post_validate gate alert says "
                 "'missing required close spools'. Required for auditor "
                 "sign-off.",
        "danger": "safe",
        "reversible": True,
        "params": [
            {"name": "bukrs", "type": "string", "required": True,
             "description": "Company code (FAGLB03)"},
            {"name": "saknr", "type": "string", "required": True,
             "description": "G/L account"},
            {"name": "matnr", "type": "string", "required": True,
             "description": "Material number (MB5B)"},
            {"name": "werks", "type": "string", "required": True,
             "description": "Plant (MB5B)"}],
        "runs": "lambda",
        "run_target": "migrate4hana-reconciliation-engine",
    },

    # ── Run control ────────────────────────────────────────────────────────
    {
        "id": "discover-anchors",
        "label": "Discover target anchors",
        "category": "Run Control",
        "what": "Pre-flight: probes the target's customizing tables "
                 "(T001/T001W/T024E/T007A/etc.) and writes the discovered "
                 "anchor values to S3. Spines lift to Tier-1 on this landscape.",
        "when": "Once per new target landscape, before the first migration. "
                 "Re-run after a basis transport touches customizing tables.",
        "danger": "safe",
        "reversible": True,
        "params": [],
        "runs": "lambda",
        "run_target": "migrate4hana-data-migrator",
        "payload": {"mode": "discover_anchors"},
    },
    {
        "id": "list-spines",
        "label": "List registered spines",
        "category": "Run Control",
        "what": "Returns every BAPI/MC spine the loader knows about. Useful "
                 "for confirming a new spine deployment shipped.",
        "when": "After deploying a new object spine; before triggering a "
                 "selective migration to make sure the object you picked "
                 "is wired.",
        "danger": "safe",
        "reversible": True,
        "params": [],
        "runs": "lambda",
        "run_target": "migrate4hana-data-migrator",
        "payload": {"mode": "list_spines"},
    },
    {
        "id": "rerun-object",
        "label": "Re-run one object",
        "category": "Run Control",
        "what": "Re-runs the extract+load lifecycle for one object, scoped "
                 "to whatever rows are in the dead-letter table. Idempotency "
                 "via the cross-run key-map prevents duplicate creates on "
                 "rows that already landed.",
        "when": "When a dead-letter spike showed up for a known root cause "
                 "(e.g. a missing customizing row that has now been applied).",
        "danger": "caution",
        "reversible": False,
        "params": [
            {"name": "object_type", "type": "string", "required": True,
             "description": "Spine object name (Customer / Vendor / Material / ...)"},
            {"name": "run_id", "type": "string", "required": True,
             "description": "Original run id"}],
        "runs": "lambda",
        "run_target": "migrate4hana-data-migrator",
    },

    # ── Customising auto-apply ─────────────────────────────────────────────
    {
        "id": "apply-customizing",
        "label": "Apply packaged customizing",
        "category": "Customising",
        "what": "Takes the reconciler-packaged customizing manifest and "
                 "applies it to the target via the 3-strategy chain "
                 "(BAPI -> CTS transport -> SE16N). Refuses without a valid "
                 "post_data_prep gate token.",
        "when": "When the post_data_prep gate alert lists missing "
                 "customising and the basis team has authorised auto-apply.",
        "danger": "caution",
        "reversible": False,
        "params": [
            {"name": "gate_token", "type": "string", "required": True,
             "description": "HMAC-signed post_data_prep gate token"},
            {"name": "manifest_s3_uri", "type": "string", "required": True,
             "description": "S3 URI of the packaged customizing manifest"}],
        "runs": "lambda",
        "run_target": "migrate4hana-data-migrator",
        "payload": {"mode": "apply_customizing"},
    },

    # ── Key-map DR ─────────────────────────────────────────────────────────
    {
        "id": "backup-key-map",
        "label": "Backup key-map (on-demand)",
        "category": "Disaster Recovery",
        "what": "Creates an on-demand DynamoDB backup of the live key-map "
                 "table and tags it with a human-readable label + run-id.",
        "when": "Before any operation that could affect cross-run idempotency "
                 "(per docs/DR.md §2.2: 'snapshot at cutover boundaries').",
        "danger": "safe",
        "reversible": True,
        "params": [
            {"name": "label", "type": "string", "required": False,
             "description": "Backup label (default: pre-cutover-<timestamp>)"}],
        "runs": "shell",
        "run_target": "scripts/backup-key-map.ps1",
    },
    {
        "id": "restore-key-map",
        "label": "Restore key-map from backup",
        "category": "Disaster Recovery",
        "what": "Restores the key-map table from PITR (timestamp) or an "
                 "on-demand backup ARN. Creates a NEW table; does NOT swap.",
        "when": "When key-map data is suspected corrupt. Restore creates a "
                 "side table; only swap-key-map.ps1 makes it production.",
        "danger": "caution",
        "reversible": True,
        "params": [
            {"name": "source", "type": "string", "required": True,
             "description": "Source table or backup ARN"},
            {"name": "to_timestamp", "type": "string", "required": False,
             "description": "PITR target timestamp (ISO 8601 UTC)"}],
        "runs": "shell",
        "run_target": "scripts/restore-key-map.ps1",
    },
    {
        "id": "swap-key-map",
        "label": "Atomic key-map swap (PRODUCTION CUTOVER)",
        "category": "Disaster Recovery",
        "what": "Performs the atomic swap that promotes a restored table "
                 "to production by updating every Lambda env-var that "
                 "names the table. Requires -ConfirmYes inside the script.",
        "when": "After a restore-key-map run has been verified and the "
                 "operator is ready to make the new content production.",
        "danger": "danger",
        "reversible": False,
        "params": [
            {"name": "current_table", "type": "string", "required": True,
             "description": "Live prod table name"},
            {"name": "restored_table", "type": "string", "required": True,
             "description": "Verified restored table name"},
            {"name": "confirm", "type": "string", "required": True,
             "description": "Must be exactly 'I-UNDERSTAND' to proceed"}],
        "runs": "shell",
        "run_target": "scripts/swap-key-map.ps1",
    },

    # ── User & client management ───────────────────────────────────────────
    {
        "id": "rotate-root-password",
        "label": "Rotate root password",
        "category": "Auth",
        "what": "Generates a new random root password, updates the "
                 "migrate4hana/<env>/root-user secret, and writes the new "
                 "hash to the users table. Existing root JWT remains valid "
                 "until expiry.",
        "when": "Immediately after the first login (the bootstrapped "
                 "password should be rotated), or on any suspected leak.",
        "danger": "caution",
        "reversible": False,
        "params": [],
        "runs": "api",
        "run_target": "/api/admin/rotate-root-password",
    },
    {
        "id": "list-users",
        "label": "List all users",
        "category": "Auth",
        "what": "Returns every user in the users table with their role, "
                 "client scopes, allowed operations, and disabled status.",
        "when": "Periodic auth audit. Confirm a fired employee is "
                 "disabled. Confirm a new IAM user got the scopes you "
                 "expected.",
        "danger": "safe",
        "reversible": True,
        "params": [],
        "runs": "api",
        "run_target": "/api/users",
    },

    # ── Tenant / wizard hygiene ────────────────────────────────────────────
    {
        "id": "purge-stale-wizards",
        "label": "Purge stale wizard sessions",
        "category": "Hygiene",
        "what": "Deletes wizard-state DDB items older than 30 days. The TTL "
                 "attribute is 7 days; this cleans up rows that escaped the "
                 "TTL (corrupted expires_at, manually-extended sessions).",
        "when": "Monthly hygiene, or after a bug shipped that wrote bad "
                 "expires_at values.",
        "danger": "caution",
        "reversible": False,
        "params": [
            {"name": "older_than_days", "type": "integer", "required": False,
             "description": "Default 30"}],
        "runs": "api",
        "run_target": "/api/admin/purge-wizards",
    },
]


_BY_ID: Dict[str, dict] = {c["id"]: c for c in _COMMANDS}


def list_commands(category: Optional[str] = None) -> List[dict]:
    """Return the full catalog, optionally filtered by category."""
    if category:
        return [c for c in _COMMANDS if c["category"] == category]
    return list(_COMMANDS)


def get_command(command_id: str) -> Optional[dict]:
    return _BY_ID.get(command_id)


def categories() -> List[str]:
    seen: List[str] = []
    for c in _COMMANDS:
        if c["category"] not in seen:
            seen.append(c["category"])
    return seen


def validate_params(command_id: str, supplied: Dict[str, Any]) -> Dict[str, Any]:
    """Validate user-supplied params against the command's schema. Returns
    {"ok": bool, "missing": [...], "unknown": [...], "type_errors": [...]}."""
    cmd = _BY_ID.get(command_id)
    if not cmd:
        return {"ok": False, "error": "unknown command_id"}
    schema = {p["name"]: p for p in cmd.get("params") or []}
    required = [n for n, p in schema.items() if p.get("required")]
    missing = [n for n in required if n not in supplied or supplied[n] in ("", None)]
    unknown = [n for n in supplied if n not in schema]
    type_errors: List[str] = []
    for name, p in schema.items():
        if name not in supplied:
            continue
        expected = p.get("type", "string")
        val = supplied[name]
        if expected == "integer" and not isinstance(val, int):
            try:
                supplied[name] = int(val)
            except (TypeError, ValueError):
                type_errors.append(f"{name}: expected integer")
        elif expected == "string" and not isinstance(val, str):
            type_errors.append(f"{name}: expected string")
    # Special case: the danger=danger commands require an "I-UNDERSTAND"
    # confirm param when present in the schema.
    if "confirm" in schema and supplied.get("confirm") != "I-UNDERSTAND":
        type_errors.append("confirm: must be exactly 'I-UNDERSTAND' for danger=danger")
    return {
        "ok": not (missing or type_errors),
        "missing": missing, "unknown": unknown, "type_errors": type_errors,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Self-test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("superuser_commands  self-test")
    print("=" * 70)

    cmds = list_commands()
    print(f"\n[1] catalog size: {len(cmds)} commands")
    cats = categories()
    print(f"[2] categories ({len(cats)}): {cats}")
    assert len(cmds) >= 12

    # Danger-distribution sanity
    by_danger = {"safe": 0, "caution": 0, "danger": 0}
    for c in cmds:
        by_danger[c["danger"]] += 1
    print(f"[3] danger distribution: {by_danger}")
    assert by_danger["danger"] >= 1  # at least one truly dangerous command

    # Every command has the required keys
    REQUIRED = {"id", "label", "what", "when", "danger", "reversible",
                "params", "runs", "run_target", "category"}
    for c in cmds:
        missing = REQUIRED - set(c)
        assert not missing, f"{c['id']} missing keys: {missing}"
    print(f"[4] every command has all required metadata keys")

    swap = get_command("swap-key-map")
    print(f"[5] swap-key-map: danger={swap['danger']} reversible={swap['reversible']}")
    assert swap["danger"] == "danger" and not swap["reversible"]

    # validate_params: missing required
    res = validate_params("rerun-object", {"object_type": "Customer"})
    print(f"[6] rerun-object missing run_id: ok={res['ok']} missing={res['missing']}")
    assert not res["ok"] and "run_id" in res["missing"]

    # validate_params: danger command needs I-UNDERSTAND
    res = validate_params("swap-key-map", {
        "current_table": "x", "restored_table": "y", "confirm": "yes"})
    print(f"[7] swap-key-map wrong confirm: type_errors={res['type_errors']}")
    assert not res["ok"]
    assert any("I-UNDERSTAND" in e for e in res["type_errors"])

    # validate_params: happy path
    res = validate_params("swap-key-map", {
        "current_table": "x", "restored_table": "y", "confirm": "I-UNDERSTAND"})
    print(f"[8] swap-key-map valid: ok={res['ok']}")
    assert res["ok"]

    # Filtering by category
    dr = list_commands(category="Disaster Recovery")
    print(f"[9] DR category: {[c['id'] for c in dr]}")
    assert len(dr) >= 3

    print("\nOK  superuser_commands catalog, schema validation, "
          "danger labelling, and I-UNDERSTAND confirm gate all work.")
