"""
auth_users - Root + IAM user store with client scoping (AWS-style login).

PURPOSE
-------
The new UI distinguishes between two principal types, mirroring AWS:

  * **root**: account-level superuser. Has all permissions; can create / delete
    IAM users; can grant cross-client access; sees the superuser command board.
    One root per deployment is the norm (more is possible but not encouraged).

  * **iam**: regular user, always scoped to one or more clients. Cannot create
    other users or change permissions. Sees only the projects belonging to the
    clients they are scoped to.

A login MUST resolve to (user_id, role, client_scopes, allowed_operations).
The JWT carries this so each request is self-describing; the server re-checks
against the live store on protected operations.

STORAGE
-------
DynamoDB tables:
  - m4h-users   PK=email             -> {id, email, role, password_hash, salt,
                                          client_scopes, allowed_operations,
                                          created_by, created_at, mfa_secret?,
                                          disabled?}
  - m4h-clients PK=client_id         -> {client_id, display_name, created_by,
                                          created_at, members: [email,...]}

In dev (no DDB) the store falls back to a JSON file at
`local-staging/auth/users.json` and `clients.json` so the UX is identical for
local runs.

PASSWORD HASH
-------------
PBKDF2-HMAC-SHA256, 600,000 iterations (OWASP 2026 recommendation), random
16-byte salt per user. Verified with hmac.compare_digest (constant-time).

OPERATIONS CATALOG
------------------
The `allowed_operations` field is a list of operation slugs. Root has the
wildcard `*`. IAM users get a subset chosen by root at creation time. The
catalog is the source of truth for what an IAM user can do:

  - run.start              start a migration run
  - run.stop               cancel a running run
  - run.view               view runs + logs (read-only)
  - gate.approve           approve / reject a governance gate
  - connection.write       create / edit ECC and S/4 connections
  - connection.test        test connections (read-only)
  - report.download        download PDF reports
  - command.execute        superuser command board (root-only by default)
  - user.manage            create / disable users (root-only by default)
  - client.manage          create / delete clients (root-only by default)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("auth_users")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

# ─────────────────────────────────────────────────────────────────────────────
# Operations catalog (the source of truth)
# ─────────────────────────────────────────────────────────────────────────────
OPERATIONS: Dict[str, str] = {
    "run.start":          "Start a migration run",
    "run.stop":           "Cancel a running migration",
    "run.view":           "View run status, logs, and reports",
    "gate.approve":       "Approve or reject HMAC-signed governance gates",
    "connection.write":   "Create or edit ECC and S/4 system connections",
    "connection.test":    "Test ECC and S/4 connectivity",
    "report.download":    "Download PDF reports for runs",
    "command.execute":    "Execute superuser command-board operations",
    "user.manage":        "Create, disable, or modify IAM users",
    "client.manage":      "Create, delete, or modify clients",
    "audit.view":         "View hash-chained audit ledger entries",
}

# Default operations for newly-created IAM users (root chooses at creation).
DEFAULT_IAM_OPERATIONS = [
    "run.start", "run.view", "gate.approve",
    "connection.test", "report.download", "audit.view",
]

ROLE_ROOT = "root"
ROLE_IAM = "iam"

# PBKDF2 parameters
_PBKDF2_ITER = 600_000
_PBKDF2_DKLEN = 32
_SALT_BYTES = 16


# ─────────────────────────────────────────────────────────────────────────────
# Password hashing
# ─────────────────────────────────────────────────────────────────────────────
def hash_password(password: str, salt: Optional[bytes] = None) -> Tuple[str, str]:
    """Hash password with PBKDF2-HMAC-SHA256. Returns (hex_hash, hex_salt)."""
    if not password or len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    salt = salt or secrets.token_bytes(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                              _PBKDF2_ITER, _PBKDF2_DKLEN)
    return dk.hex(), salt.hex()


def verify_password(password: str, hex_hash: str, hex_salt: str) -> bool:
    """Constant-time password verification."""
    if not password or not hex_hash or not hex_salt:
        return False
    try:
        salt = bytes.fromhex(hex_salt)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                                  _PBKDF2_ITER, _PBKDF2_DKLEN)
        return hmac.compare_digest(dk.hex(), hex_hash)
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class User:
    email:               str
    role:                str                            # "root" | "iam"
    password_hash:       str
    password_salt:       str
    client_scopes:       List[str] = field(default_factory=list)
    allowed_operations:  List[str] = field(default_factory=list)
    created_by:          str = ""
    created_at:          str = ""
    disabled:            bool = False
    last_login_at:       str = ""

    def public_dict(self) -> dict:
        """Safe-to-return shape (no hash material)."""
        d = asdict(self)
        d.pop("password_hash", None)
        d.pop("password_salt", None)
        return d


@dataclass
class Client:
    client_id:    str
    display_name: str
    created_by:   str = ""
    created_at:   str = ""
    members:      List[str] = field(default_factory=list)  # list of emails


# ─────────────────────────────────────────────────────────────────────────────
# Storage backend (DDB in prod, JSON file in dev)
# ─────────────────────────────────────────────────────────────────────────────
class UserStore:
    """Thin abstraction over DDB / local JSON."""

    def __init__(self, ddb_table: Optional[str] = None,
                 client_table: Optional[str] = None,
                 local_path: Optional[Path] = None):
        self.ddb_table = ddb_table or os.environ.get("M4H_USERS_TABLE")
        self.client_table = client_table or os.environ.get("M4H_CLIENTS_TABLE")
        self.local_root = local_path or Path(
            os.environ.get("M4H_STAGING_ROOT", "local-staging")) / "auth"
        self._ddb = None

    # ── DDB lazy init ─────────────────────────────────────────────────────
    def _ddb_client(self):
        if self._ddb is None and self.ddb_table:
            try:
                import boto3
                self._ddb = boto3.client("dynamodb")
            except Exception as e:
                logger.warning("DDB unavailable, falling back to local file: %s", e)
                self._ddb = None
        return self._ddb

    # ── User CRUD ────────────────────────────────────────────────────────
    def get_user(self, email: str) -> Optional[User]:
        email = (email or "").strip().lower()
        if not email:
            return None
        ddb = self._ddb_client()
        if ddb and self.ddb_table:
            try:
                resp = ddb.get_item(TableName=self.ddb_table,
                                      Key={"email": {"S": email}})
                item = resp.get("Item")
                if not item:
                    return None
                return User(
                    email=item["email"]["S"],
                    role=item["role"]["S"],
                    password_hash=item["password_hash"]["S"],
                    password_salt=item["password_salt"]["S"],
                    client_scopes=[s["S"] for s in item.get("client_scopes", {}).get("L", [])],
                    allowed_operations=[s["S"] for s in item.get("allowed_operations", {}).get("L", [])],
                    created_by=item.get("created_by", {}).get("S", ""),
                    created_at=item.get("created_at", {}).get("S", ""),
                    disabled=item.get("disabled", {}).get("BOOL", False),
                    last_login_at=item.get("last_login_at", {}).get("S", ""),
                )
            except Exception as e:
                logger.warning("DDB get_user failed: %s; falling back to local", e)
        # Local fallback
        path = self.local_root / "users.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
        rec = data.get(email)
        return User(**rec) if rec else None

    def put_user(self, user: User) -> None:
        user.email = user.email.strip().lower()
        ddb = self._ddb_client()
        if ddb and self.ddb_table:
            try:
                ddb.put_item(TableName=self.ddb_table, Item={
                    "email":              {"S": user.email},
                    "role":               {"S": user.role},
                    "password_hash":      {"S": user.password_hash},
                    "password_salt":      {"S": user.password_salt},
                    "client_scopes":      {"L": [{"S": s} for s in user.client_scopes]},
                    "allowed_operations": {"L": [{"S": s} for s in user.allowed_operations]},
                    "created_by":         {"S": user.created_by or ""},
                    "created_at":         {"S": user.created_at or ""},
                    "disabled":           {"BOOL": bool(user.disabled)},
                    "last_login_at":      {"S": user.last_login_at or ""},
                })
                return
            except Exception as e:
                logger.warning("DDB put_user failed: %s; falling back to local", e)
        # Local fallback
        self.local_root.mkdir(parents=True, exist_ok=True)
        path = self.local_root / "users.json"
        data = json.loads(path.read_text(encoding="utf-8") or "{}") if path.exists() else {}
        data[user.email] = asdict(user)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def list_users(self) -> List[User]:
        ddb = self._ddb_client()
        if ddb and self.ddb_table:
            try:
                resp = ddb.scan(TableName=self.ddb_table)
                out = []
                for item in resp.get("Items", []):
                    out.append(User(
                        email=item["email"]["S"],
                        role=item["role"]["S"],
                        password_hash=item.get("password_hash", {}).get("S", ""),
                        password_salt=item.get("password_salt", {}).get("S", ""),
                        client_scopes=[s["S"] for s in item.get("client_scopes", {}).get("L", [])],
                        allowed_operations=[s["S"] for s in item.get("allowed_operations", {}).get("L", [])],
                        disabled=item.get("disabled", {}).get("BOOL", False),
                        created_at=item.get("created_at", {}).get("S", ""),
                    ))
                return out
            except Exception as e:
                logger.warning("DDB scan failed: %s; local fallback", e)
        path = self.local_root / "users.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
        return [User(**rec) for rec in data.values()]

    def delete_user(self, email: str) -> bool:
        email = (email or "").strip().lower()
        if not email:
            return False
        ddb = self._ddb_client()
        if ddb and self.ddb_table:
            try:
                ddb.delete_item(TableName=self.ddb_table,
                                  Key={"email": {"S": email}})
                return True
            except Exception:
                pass
        path = self.local_root / "users.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
            if email in data:
                del data[email]
                path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                return True
        return False

    # ── Client CRUD ──────────────────────────────────────────────────────
    def get_client(self, client_id: str) -> Optional[Client]:
        client_id = (client_id or "").strip().lower()
        if not client_id:
            return None
        ddb = self._ddb_client()
        if ddb and self.client_table:
            try:
                resp = ddb.get_item(TableName=self.client_table,
                                     Key={"client_id": {"S": client_id}})
                item = resp.get("Item")
                if not item:
                    return None
                return Client(
                    client_id=item["client_id"]["S"],
                    display_name=item.get("display_name", {}).get("S", ""),
                    created_by=item.get("created_by", {}).get("S", ""),
                    created_at=item.get("created_at", {}).get("S", ""),
                    members=[s["S"] for s in item.get("members", {}).get("L", [])],
                )
            except Exception:
                pass
        path = self.local_root / "clients.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
        rec = data.get(client_id)
        return Client(**rec) if rec else None

    def put_client(self, client: Client) -> None:
        client.client_id = client.client_id.strip().lower()
        ddb = self._ddb_client()
        if ddb and self.client_table:
            try:
                ddb.put_item(TableName=self.client_table, Item={
                    "client_id":    {"S": client.client_id},
                    "display_name": {"S": client.display_name or ""},
                    "created_by":   {"S": client.created_by or ""},
                    "created_at":   {"S": client.created_at or ""},
                    "members":      {"L": [{"S": e} for e in client.members]},
                })
                return
            except Exception:
                pass
        self.local_root.mkdir(parents=True, exist_ok=True)
        path = self.local_root / "clients.json"
        data = json.loads(path.read_text(encoding="utf-8") or "{}") if path.exists() else {}
        data[client.client_id] = asdict(client)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def list_clients(self) -> List[Client]:
        ddb = self._ddb_client()
        if ddb and self.client_table:
            try:
                resp = ddb.scan(TableName=self.client_table)
                return [Client(
                    client_id=item["client_id"]["S"],
                    display_name=item.get("display_name", {}).get("S", ""),
                    created_at=item.get("created_at", {}).get("S", ""),
                    members=[s["S"] for s in item.get("members", {}).get("L", [])],
                ) for item in resp.get("Items", [])]
            except Exception:
                pass
        path = self.local_root / "clients.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
        return [Client(**rec) for rec in data.values()]


# ─────────────────────────────────────────────────────────────────────────────
# Bootstrap: first-run root creation
# ─────────────────────────────────────────────────────────────────────────────
def ensure_root_user(store: UserStore,
                      root_email: Optional[str] = None,
                      root_password: Optional[str] = None) -> Optional[User]:
    """First-run bootstrap. If no root user exists, create one from env vars
    M4H_ROOT_EMAIL + M4H_ROOT_PASSWORD (or args). Idempotent: returns the
    existing root if one is already present.

    The root user has role='root', wildcard operations, and no client scope.
    """
    # Are there ANY root users already?
    existing = [u for u in store.list_users() if u.role == ROLE_ROOT]
    if existing:
        return existing[0]
    email = (root_email or os.environ.get("M4H_ROOT_EMAIL", "")).strip().lower()
    password = root_password or os.environ.get("M4H_ROOT_PASSWORD", "")
    if not email or not password:
        logger.warning("ensure_root_user: no root credentials configured "
                       "(set M4H_ROOT_EMAIL + M4H_ROOT_PASSWORD)")
        return None
    h, s = hash_password(password)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    user = User(
        email=email, role=ROLE_ROOT,
        password_hash=h, password_salt=s,
        client_scopes=[], allowed_operations=["*"],
        created_by="bootstrap", created_at=now,
    )
    store.put_user(user)
    logger.info("bootstrapped root user: %s", email)
    return user


# ─────────────────────────────────────────────────────────────────────────────
# Authorisation helpers
# ─────────────────────────────────────────────────────────────────────────────
def can(user: User, operation: str, client_id: Optional[str] = None) -> bool:
    """True if user can perform operation. Root passes everything. IAM users
    must have operation in allowed_operations AND, when client_id is given,
    must be scoped to that client."""
    if user is None or user.disabled:
        return False
    if user.role == ROLE_ROOT:
        return True
    if "*" not in user.allowed_operations and operation not in user.allowed_operations:
        return False
    if client_id is not None:
        cid = client_id.strip().lower()
        if cid and cid not in [c.lower() for c in user.client_scopes]:
            return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Self-test (no DDB)
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import tempfile
    print("=" * 72)
    print("auth_users  self-test")
    print("=" * 72)

    tmp = Path(tempfile.mkdtemp(prefix="m4h_auth_"))
    store = UserStore(local_path=tmp)

    # ── 1) Bootstrap root
    root = ensure_root_user(store, "root@acme.com", "S3cur3-root-pw")
    assert root is not None and root.role == "root"
    print(f"\n[1] root bootstrapped: {root.email} role={root.role} ops={root.allowed_operations}")

    # ── 2) Re-bootstrap is idempotent
    again = ensure_root_user(store, "another@acme.com", "different-pw")
    assert again.email == root.email   # first root wins
    print(f"[2] re-bootstrap idempotent (still {again.email})")

    # ── 3) Verify password
    fetched = store.get_user("root@acme.com")
    assert verify_password("S3cur3-root-pw", fetched.password_hash, fetched.password_salt)
    assert not verify_password("wrong-pw", fetched.password_hash, fetched.password_salt)
    print(f"[3] password verify: correct=True, wrong=False")

    # ── 4) Create IAM user scoped to client 'acme'
    h, s = hash_password("iam-user-pw")
    iam = User(
        email="alice@acme.com", role="iam",
        password_hash=h, password_salt=s,
        client_scopes=["acme"],
        allowed_operations=DEFAULT_IAM_OPERATIONS,
        created_by=root.email,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    store.put_user(iam)
    fetched = store.get_user("alice@acme.com")
    assert fetched.role == "iam" and fetched.client_scopes == ["acme"]
    print(f"[4] IAM user: {fetched.email} scoped to {fetched.client_scopes}")

    # ── 5) Authorisation matrix
    assert can(root, "user.manage")                           # root: yes
    assert can(root, "run.start", client_id="acme")           # root: any client
    assert can(root, "run.start", client_id="other")          # root: any client
    assert can(iam, "run.start", client_id="acme")            # IAM in-scope
    assert not can(iam, "run.start", client_id="other")       # IAM cross-client = no
    assert not can(iam, "user.manage")                        # IAM no admin
    assert not can(iam, "command.execute")                    # IAM no superuser
    print(f"[5] auth matrix:")
    print(f"    root.user.manage           -> True")
    print(f"    root.run.start@other       -> True (any client)")
    print(f"    iam.run.start@acme         -> True (in-scope)")
    print(f"    iam.run.start@other        -> False (out of scope)")
    print(f"    iam.user.manage            -> False (no permission)")
    print(f"    iam.command.execute        -> False (root-only)")

    # ── 6) Client CRUD + member list
    cli = Client(client_id="acme", display_name="ACME Corp",
                  created_by=root.email,
                  created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  members=["alice@acme.com"])
    store.put_client(cli)
    fetched_cli = store.get_client("acme")
    assert fetched_cli.display_name == "ACME Corp" and "alice@acme.com" in fetched_cli.members
    print(f"[6] client: {fetched_cli.client_id} '{fetched_cli.display_name}' members={fetched_cli.members}")

    # ── 7) Public dict has no hash material
    pub = root.public_dict()
    assert "password_hash" not in pub and "password_salt" not in pub
    print(f"[7] public_dict() strips hash material: keys={sorted(pub)[:6]}...")

    # ── 8) Disabled user fails authorisation
    iam.disabled = True
    store.put_user(iam)
    assert not can(iam, "run.start", client_id="acme")
    print(f"[8] disabled IAM user denied: can(...) = False")

    # ── 9) Delete user
    assert store.delete_user("alice@acme.com") and store.get_user("alice@acme.com") is None
    print(f"[9] delete_user: alice removed")

    print(f"\nOK  auth_users full lifecycle works: bootstrap, hash/verify, "
          f"IAM-with-scope, can() matrix, client CRUD, soft-disable, delete.")
    print(f"   artifacts in {tmp}")
