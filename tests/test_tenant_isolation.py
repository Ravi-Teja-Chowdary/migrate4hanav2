"""
Tenant isolation tests (F7).

Validates the Fortune 500 / multi-tenancy claim that there is NO POSSIBLE WAY
for tenant A's data to leak to tenant B at the namespace level.

Three classes of test:

  1. TenantContext format + reserved-name enforcement
  2. Resource-naming derivations (DDB / S3 / secrets / logs)
  3. End-to-end isolation in PersistentKeyMap with a shared mock DDB:
     tenant A writes a key; tenant B's resolve() for the same source value
     MUST NOT return tenant A's target. Period.

These are the tests an enterprise security auditor will run on the demo
deployment. If they pass, the "multi-tenant safe" claim is defensible.

Run:  python tests\test_tenant_isolation.py
"""
from __future__ import annotations
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lambda" / "utils"))

from tenant_context import (   # noqa
    TenantContext, default_context,
    TenantIdError, validate_tenant_id,
    DEFAULT_TENANT_ID,
)
from key_map import PersistentKeyMap   # noqa


# ─────────────────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────────────────
class _SharedFakeDdb:
    """A shared mock DDB table that BOTH tenants write to. The whole point of
    the test is to prove that even with the same backing table, tenant
    partition-key prefixing keeps writes isolated."""
    def __init__(self):
        self.items: dict = {}    # (object, source_key) -> Item dict
        self.put_calls = 0
        self.get_calls = 0
        self._lock = threading.Lock()

    def put_item(self, *, TableName, Item, ConditionExpression=None):
        with self._lock:
            self.put_calls += 1
            k = (Item["object"]["S"], Item["source_key"]["S"])
            if ConditionExpression and "attribute_not_exists" in ConditionExpression and k in self.items:
                raise Exception("ConditionalCheckFailedException")
            self.items[k] = Item
            return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def get_item(self, *, TableName, Key, ConsistentRead=False):
        with self._lock:
            self.get_calls += 1
            k = (Key["object"]["S"], Key["source_key"]["S"])
            return {"Item": self.items[k]} if k in self.items else {}

    def batch_get_item(self, *, RequestItems):
        with self._lock:
            return {"Responses": {}, "UnprocessedKeys": {}}

    def query(self, *, TableName, KeyConditionExpression,
              ExpressionAttributeNames, ExpressionAttributeValues, ExclusiveStartKey=None):
        with self._lock:
            obj = ExpressionAttributeValues[":o"]["S"]
            return {"Items": [v for (o, _), v in self.items.items() if o == obj]}


# ─────────────────────────────────────────────────────────────────────────────
# Format + reserved-id rules
# ─────────────────────────────────────────────────────────────────────────────
def test_tenant_id_format_accepts_valid_ids():
    for ok in ("acme-corp", "tenant001", "abc-def-ghi", "x1y2z3", "global-bank"):
        validate_tenant_id(ok)  # must NOT raise
    print("  [OK] valid tenant IDs pass the format gate")


def test_tenant_id_format_rejects_invalid():
    bad_cases = [
        "ABC",        # uppercase
        "ab",         # too short
        "a_b",        # underscore
        "",           # empty
        "tenant-",    # trailing dash
        "-tenant",    # leading dash
        "a" * 33,     # too long
        "foo bar",    # whitespace
    ]
    failed = 0
    for bad in bad_cases:
        try:
            validate_tenant_id(bad)
            failed += 1
        except TenantIdError:
            pass
    assert failed == 0, f"expected all {len(bad_cases)} cases to fail; {failed} unexpectedly passed"
    print(f"  [OK] {len(bad_cases)} malformed tenant IDs rejected")


def test_tenant_id_format_rejects_reserved():
    for reserved in ("admin", "system", "internal", "migrate4hana", "root", "anonymous"):
        try:
            validate_tenant_id(reserved)
        except TenantIdError:
            continue
        assert False, f"reserved id {reserved!r} should have been rejected"
    print("  [OK] reserved tenant IDs (admin/system/root/...) are blocked")


def test_default_tenant_short_circuits_validation():
    """The 'default' tenant exists for backward-compat with single-tenant deployments."""
    validate_tenant_id(DEFAULT_TENANT_ID)
    ctx = default_context()
    assert ctx.is_default
    print("  [OK] DEFAULT_TENANT_ID is allowed (single-tenant backward-compat)")


# ─────────────────────────────────────────────────────────────────────────────
# Resource naming
# ─────────────────────────────────────────────────────────────────────────────
def test_default_tenant_preserves_legacy_resource_names():
    """Single-tenant deployments must continue to work unchanged."""
    ctx = default_context()
    assert ctx.ddb_object_key("Customer") == "Customer"            # bare, no prefix
    assert ctx.s3_prefix("runs") == "runs"                          # bare, no prefix
    assert ctx.secret_name("sap-credentials") == "migrate4hana/prod/sap-credentials"
    assert ctx.log_group("data-migrator") == "/aws/lambda/migrate4hana-data-migrator-prod"
    assert ctx.connections_path() == ""
    print("  [OK] default tenant gives the same names existing prod deployments use")


def test_named_tenant_namespaces_all_resources():
    ctx = TenantContext(tenant_id="acme-corp", environment="prod")
    assert ctx.ddb_object_key("Customer") == "acme-corp#Customer"
    assert ctx.s3_prefix("runs")        == "tenants/acme-corp/runs"
    assert ctx.s3_prefix("audit")       == "tenants/acme-corp/audit"
    assert ctx.s3_prefix("mappings")    == "tenants/acme-corp/mappings"
    assert ctx.secret_name("sap-credentials") == "migrate4hana/prod/tenants/acme-corp/sap-credentials"
    assert ctx.log_group("data-migrator") == "/migrate4hana/prod/tenants/acme-corp/data-migrator"
    assert ctx.connections_path() == "tenants/acme-corp"
    print("  [OK] named tenant gets fully namespaced DDB / S3 / Secrets / CW names")


def test_two_tenants_dont_share_any_resource_name():
    """The most important property: ANY two distinct tenants get DISJOINT
    namespaces for EVERY resource type. Fortune 500 procurement asks for this."""
    a = TenantContext(tenant_id="acme-corp", environment="prod")
    b = TenantContext(tenant_id="global-bank", environment="prod")
    obj = "Customer"
    for resource in [
        a.ddb_object_key(obj)              != b.ddb_object_key(obj),
        a.s3_prefix("runs")                 != b.s3_prefix("runs"),
        a.s3_prefix("audit")                != b.s3_prefix("audit"),
        a.s3_prefix("mappings")             != b.s3_prefix("mappings"),
        a.secret_name("sap-credentials")    != b.secret_name("sap-credentials"),
        a.log_group("data-migrator")        != b.log_group("data-migrator"),
        a.staging_key("r1", "data-migrator") != b.staging_key("r1", "data-migrator"),
    ]:
        assert resource is True
    print("  [OK] two named tenants get DISJOINT namespaces for every resource type")


def test_env_var_overlay_round_trips():
    ctx = TenantContext(tenant_id="some-tenant", environment="prod")
    overlay = ctx.lambda_env_overlay()
    rebuilt = TenantContext.from_env(overlay)
    assert rebuilt.tenant_id == ctx.tenant_id
    assert rebuilt.tenant_slug == ctx.tenant_slug
    assert rebuilt.environment == ctx.environment
    print("  [OK] env-var overlay round-trips through Lambda-to-Lambda invocation")


def test_from_env_with_no_overlay_returns_default_tenant():
    rebuilt = TenantContext.from_env({})
    assert rebuilt.is_default
    print("  [OK] from_env({}) defaults to single-tenant (matches today's prod behavior)")


# ─────────────────────────────────────────────────────────────────────────────
# End-to-end isolation through PersistentKeyMap with a shared mock DDB
# ─────────────────────────────────────────────────────────────────────────────
def test_two_tenants_writing_same_source_key_DO_NOT_COLLIDE():
    """Critical test: tenant A and tenant B both register KUNNR=0001000123,
    each gets their OWN target. Without partition-key prefixing, the second
    write would either clobber or be rejected. WITH prefixing, both succeed
    and resolves stay disjoint."""
    ddb = _SharedFakeDdb()
    a = TenantContext(tenant_id="acme-corp")
    b = TenantContext(tenant_id="global-bank")

    km_a = PersistentKeyMap(table_name="shared", dynamodb_client=ddb,
                             run_id="run-a", tenant_context=a)
    km_b = PersistentKeyMap(table_name="shared", dynamodb_client=ddb,
                             run_id="run-b", tenant_context=b)

    # Both write SAME source KUNNR with DIFFERENT target BPs
    km_a.add("Customer", "0001000123", "BP_ACME_500", "created")
    km_b.add("Customer", "0001000123", "BP_BANK_777", "created")

    # Both writes succeed - no ConditionalCheckFailed
    assert ddb.put_calls == 2
    assert len(ddb.items) == 2

    # Now do FRESH resolves on cold caches - each tenant must see THEIR target
    km_a_cold = PersistentKeyMap(table_name="shared", dynamodb_client=ddb, tenant_context=a)
    km_b_cold = PersistentKeyMap(table_name="shared", dynamodb_client=ddb, tenant_context=b)
    assert km_a_cold.resolve("Customer", "0001000123") == "BP_ACME_500"
    assert km_b_cold.resolve("Customer", "0001000123") == "BP_BANK_777"
    print("  [OK] same source KUNNR -> DIFFERENT targets per tenant; no leak")


def test_tenant_A_cannot_resolve_tenant_Bs_keys():
    """Even when both share the DDB backing table, tenant A's resolve must
    return None for a key only tenant B has registered."""
    ddb = _SharedFakeDdb()
    a = TenantContext(tenant_id="acme-corp")
    b = TenantContext(tenant_id="global-bank")

    km_b = PersistentKeyMap(table_name="shared", dynamodb_client=ddb, tenant_context=b)
    km_b.add("Customer", "BANK_ONLY_KUNNR", "BP_BANK_999", "created")

    km_a = PersistentKeyMap(table_name="shared", dynamodb_client=ddb, tenant_context=a)
    assert km_a.resolve("Customer", "BANK_ONLY_KUNNR") is None
    print("  [OK] tenant A's resolve for tenant B's key returns None (no cross-tenant read)")


def test_default_tenant_cannot_see_namespaced_tenant_data():
    """The default (legacy) tenant uses bare object names; a named tenant
    uses prefixed object names. They MUST NOT conflict."""
    ddb = _SharedFakeDdb()
    default_km = PersistentKeyMap(table_name="shared", dynamodb_client=ddb,
                                   tenant_context=default_context())
    acme_km = PersistentKeyMap(table_name="shared", dynamodb_client=ddb,
                                tenant_context=TenantContext(tenant_id="acme-corp"))

    default_km.add("Customer", "K1", "BP_LEGACY", "created")
    acme_km.add("Customer", "K1", "BP_ACME", "created")

    # Cold-cache resolves: each side sees ONLY its own data
    df = PersistentKeyMap(table_name="shared", dynamodb_client=ddb,
                          tenant_context=default_context())
    ak = PersistentKeyMap(table_name="shared", dynamodb_client=ddb,
                          tenant_context=TenantContext(tenant_id="acme-corp"))
    assert df.resolve("Customer", "K1") == "BP_LEGACY"
    assert ak.resolve("Customer", "K1") == "BP_ACME"
    print("  [OK] default tenant + named tenant on the same DDB stay disjoint")


def test_tenant_id_appears_on_DDB_item_for_named_tenants_only():
    """Audit-trail check: items written by a named tenant carry tenant_id
    in the row. Items written by the default tenant DON'T (legacy compat)."""
    ddb = _SharedFakeDdb()
    default_km = PersistentKeyMap(table_name="shared", dynamodb_client=ddb,
                                   tenant_context=default_context())
    acme_km = PersistentKeyMap(table_name="shared", dynamodb_client=ddb,
                                tenant_context=TenantContext(tenant_id="acme-corp"))
    default_km.add("Customer", "K1", "BP1", "created")
    acme_km.add("Customer", "K2", "BP2", "created")

    legacy_item = ddb.items[("Customer", "K1")]
    acme_item   = ddb.items[("acme-corp#Customer", "K2")]
    assert "tenant_id" not in legacy_item        # legacy compat
    assert acme_item["tenant_id"]["S"] == "acme-corp"
    print("  [OK] named-tenant rows carry tenant_id audit column; default rows omit it")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("F7 - tenant isolation tests")
    print("=" * 70)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll F7 tenant isolation tests passed.")
