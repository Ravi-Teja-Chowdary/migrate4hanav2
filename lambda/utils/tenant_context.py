"""
tenant_context - Multi-tenancy core (F7 / Fortune 500 readiness).

Every Migrate4HANA resource that holds CUSTOMER data must be addressable through
a tenant scope so that:

  1. A bug in tenant A's loader can NEVER reach tenant B's data
  2. A Fortune 500 customer can deploy Migrate4HANA into our account or theirs
     and trust that data isolation is enforced at the namespace level, not just
     at IAM
  3. Tenant onboarding/offboarding is a single source-key change, not a 20-file
     refactor

Design:

  TenantContext is a tiny value object (no I/O) that carries one tenant ID +
  derives all per-tenant resource names from it. The defaults preserve
  current single-tenant behavior (tenant_id="default") so existing tests +
  the live ECC tunnel proof from 2026-06-02 keep working unchanged.

  When a customer-specific TenantContext is constructed, EVERY resource the
  pipeline touches is prefixed:

    DDB key_map row:    PK = "<tenant>#<object>",  SK = "<source_key>"
    S3 staging path:     s3://<bucket>/tenants/<slug>/runs/<run_id>/...
    S3 audit path:       s3://<bucket>/tenants/<slug>/audit/...
    S3 value-maps path:  s3://<bucket>/tenants/<slug>/mappings/matrix.json
    Secret name:         migrate4hana/<env>/tenants/<slug>/<role>
    CloudWatch log gp:   /migrate4hana/<env>/tenants/<slug>/<lambda>
    SAP connection key:  connections.json[tenants][<slug>]

  Single-tenant deployments (where tenant_id == "default") use the LEGACY
  paths so we don't break existing customers - default-tenant DDB rows use the
  bare object name as PK, not "default#<object>". This is intentional: it
  keeps backwards compatibility with all 16 unit + 5 integration tests in
  test_persistent_key_map.py / integration_test_persistent_key_map.py.

Standard-library only. Thread-safe (immutable after construction).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_TENANT_ID   = "default"
DEFAULT_TENANT_SLUG = "default"

# Tenant ID format. Must be safe in DDB partition keys, S3 paths, IAM resource
# ARNs, CloudWatch log group names, and SAP secret names - the intersection is
# lowercase alphanumeric + dash, length 3-32.
_TENANT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,30}[a-z0-9]$")
_RESERVED_IDS = {"admin", "system", "internal", "migrate4hana", "root", "anonymous"}


class TenantIdError(ValueError):
    """Raised when a tenant ID violates the format / reserved-name rules."""


# ─────────────────────────────────────────────────────────────────────────────
# TenantContext
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class TenantContext:
    """Identifies a tenant + derives all per-tenant resource names from it.

    Immutable after construction. Carry it through the request lifecycle the
    same way you'd carry a ``run_id`` - one ``TenantContext`` per Lambda
    invocation, never mutated, never shared between concurrent tenants.

    :param tenant_id: stable canonical identifier (e.g. "acme-corp"). The
                       Fortune 500 onboarding flow generates this from the
                       legal entity name.
    :param tenant_slug: short URL/path-safe slug. Defaults to ``tenant_id``;
                       override only for legacy renames where the slug must
                       differ from the canonical id.
    :param display_name: human-readable name for dashboards + audit logs.
                       Never used in resource naming.
    :param environment: prod / staging / dev. Affects the secret name and the
                       CloudWatch log group prefix.
    """

    tenant_id:    str = DEFAULT_TENANT_ID
    tenant_slug:  str = ""
    display_name: str = ""
    environment:  str = "prod"

    def __post_init__(self):
        validate_tenant_id(self.tenant_id)
        if not self.tenant_slug:
            # frozen dataclass: bypass setattr via __dict__
            object.__setattr__(self, "tenant_slug", self.tenant_id)
        validate_tenant_id(self.tenant_slug)
        if not self.display_name:
            object.__setattr__(self, "display_name", self.tenant_id)

    # ── shortcuts ────────────────────────────────────────────────────────────
    @property
    def is_default(self) -> bool:
        """True iff this is the single-tenant default context (backward-compat mode)."""
        return self.tenant_id == DEFAULT_TENANT_ID

    # ── DDB partition-key shaping for the cross-run key_map ──────────────────
    def ddb_object_key(self, object_type: str) -> str:
        """Compose the DDB partition key for an ``object`` field row.

        Default tenant returns the bare object name (backward-compat with the
        existing F1 PersistentKeyMap tests). Real tenants get prefixed.
        """
        if self.is_default:
            return object_type
        return f"{self.tenant_slug}#{object_type}"

    # ── S3 paths ────────────────────────────────────────────────────────────
    def s3_prefix(self, category: str = "") -> str:
        """Tenant-scoped S3 key prefix. ``category`` is the bucket sub-folder
        (e.g. "runs", "audit", "mappings"). Default tenant returns the legacy
        un-prefixed path for compatibility."""
        if self.is_default:
            return category.strip("/")
        base = f"tenants/{self.tenant_slug}"
        if category:
            return f"{base}/{category.strip('/')}"
        return base

    def staging_key(self, run_id: str, *parts: str) -> str:
        """Build the staging-bucket key for a run artifact."""
        base = self.s3_prefix("runs")
        path = "/".join([p.strip("/") for p in (run_id, *parts) if p])
        return f"{base}/{path}" if base else path

    def audit_key(self, *parts: str) -> str:
        """Build the audit-logs key for an audit-ledger artifact."""
        base = self.s3_prefix("audit")
        path = "/".join([p.strip("/") for p in parts if p])
        return f"{base}/{path}" if base else path

    def value_maps_key(self, filename: str = "matrix.json") -> str:
        """Build the value-mapping bucket key for this tenant's matrix.json."""
        base = self.s3_prefix("mappings")
        return f"{base}/{filename.strip('/')}" if base else f"mappings/{filename}"

    # ── Secret + log-group + connections.json key naming ───────────────────
    def secret_name(self, role: str) -> str:
        """Compose the Secrets Manager secret name for a role (e.g. "sap-credentials").

        Default tenant uses the legacy single-tenant naming so existing prod
        deployments aren't broken; per-tenant deployments are explicitly
        namespaced.
        """
        if self.is_default:
            return f"migrate4hana/{self.environment}/{role}"
        return f"migrate4hana/{self.environment}/tenants/{self.tenant_slug}/{role}"

    def log_group(self, lambda_short_name: str) -> str:
        """CloudWatch log-group name for a Lambda invocation made under this tenant."""
        if self.is_default:
            return f"/aws/lambda/migrate4hana-{lambda_short_name}-{self.environment}"
        return (f"/migrate4hana/{self.environment}/tenants/{self.tenant_slug}"
                f"/{lambda_short_name}")

    def connections_path(self) -> str:
        """Key into connections.json. Default tenant uses the top-level legacy
        keys (`ecc`, `s4hana`, `versions`). Real tenants get a tenants[<slug>]
        sub-tree."""
        if self.is_default:
            return ""    # caller reads top-level keys
        return f"tenants/{self.tenant_slug}"

    # ── Lambda env overlay for cross-Lambda invocations ─────────────────────
    def lambda_env_overlay(self) -> dict:
        """Return a dict of env-var overrides for Lambda-to-Lambda invocation.

        When a Lambda invokes another Lambda for this tenant (via the Step
        Functions state machine or direct invoke), it passes these env vars
        so the called Lambda's TenantContext.from_env() reconstructs cleanly.
        """
        return {
            "M4H_TENANT_ID":    self.tenant_id,
            "M4H_TENANT_SLUG":  self.tenant_slug,
            "M4H_ENVIRONMENT":  self.environment,
        }

    # ── (de)serialization ───────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "tenant_id":    self.tenant_id,
            "tenant_slug":  self.tenant_slug,
            "display_name": self.display_name,
            "environment":  self.environment,
        }

    @classmethod
    def from_env(cls, env: Optional[dict] = None) -> "TenantContext":
        """Construct from env vars set by ``lambda_env_overlay()`` on the
        invoking Lambda. Returns the DEFAULT tenant when no env var is set
        (single-tenant mode, current behavior)."""
        env = env if env is not None else os.environ
        tid = env.get("M4H_TENANT_ID") or DEFAULT_TENANT_ID
        slug = env.get("M4H_TENANT_SLUG") or tid
        environment = env.get("M4H_ENVIRONMENT") or env.get("ENVIRONMENT") or "prod"
        return cls(tenant_id=tid, tenant_slug=slug, environment=environment)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def validate_tenant_id(tenant_id: str) -> None:
    """Enforce the tenant-id format + reserved-name rules. Raises TenantIdError."""
    if tenant_id is None or not isinstance(tenant_id, str):
        raise TenantIdError("tenant_id must be a non-empty string")
    if tenant_id == DEFAULT_TENANT_ID:
        return     # allowed; matches the regex pattern anyway
    if not _TENANT_ID_RE.match(tenant_id):
        raise TenantIdError(
            f"tenant_id {tenant_id!r} fails the format rule "
            f"(lowercase alphanumeric + dash, 4-32 chars, must start and end "
            f"with alphanumeric)"
        )
    if tenant_id in _RESERVED_IDS:
        raise TenantIdError(f"tenant_id {tenant_id!r} is reserved")


def default_context(environment: str = "prod") -> TenantContext:
    """Convenience for the single-tenant fallback used by every legacy code path
    that hasn't been wired through F7 yet."""
    return TenantContext(tenant_id=DEFAULT_TENANT_ID, environment=environment)


# ─────────────────────────────────────────────────────────────────────────────
# Self-test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("tenant_context - self-test")
    print("=" * 70)

    default = default_context()
    assert default.is_default
    assert default.ddb_object_key("Customer") == "Customer"
    assert default.s3_prefix("runs") == "runs"
    assert default.secret_name("sap-credentials") == "migrate4hana/prod/sap-credentials"
    print("  [OK] default tenant preserves legacy backward-compat naming")

    acme = TenantContext(tenant_id="acme-corp",
                          display_name="ACME Corporation",
                          environment="prod")
    assert not acme.is_default
    assert acme.ddb_object_key("Customer") == "acme-corp#Customer"
    assert acme.s3_prefix("runs") == "tenants/acme-corp/runs"
    assert acme.secret_name("sap-credentials") == "migrate4hana/prod/tenants/acme-corp/sap-credentials"
    assert acme.log_group("data-migrator") == "/migrate4hana/prod/tenants/acme-corp/data-migrator"
    assert acme.staging_key("run-001", "data-migrator", "Customer.csv") == \
        "tenants/acme-corp/runs/run-001/data-migrator/Customer.csv"
    print("  [OK] acme-corp tenant gets fully-namespaced resource paths")

    overlay = acme.lambda_env_overlay()
    assert overlay["M4H_TENANT_ID"] == "acme-corp"
    reconstructed = TenantContext.from_env(overlay)
    assert reconstructed.tenant_id == "acme-corp"
    print("  [OK] env-var overlay round-trips through from_env()")

    # Format rules
    for bad in ("AB", "1", "x_y", "FOO", "", "system", "migrate4hana", "a"):
        try:
            validate_tenant_id(bad)
        except TenantIdError:
            continue
        raise AssertionError(f"expected TenantIdError for {bad!r}")
    print("  [OK] tenant ID format rules reject invalid + reserved IDs")

    print("\nOK - TenantContext namespaces all per-tenant resources correctly.")
