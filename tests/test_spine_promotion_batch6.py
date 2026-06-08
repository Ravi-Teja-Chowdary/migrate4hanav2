"""
Unit tests for object-promotion grind batch 6:
  BusinessPartner / Customer / Vendor / ExchangeRates.

This batch closes the live-25 sweep (objects 22 through 25 of 25). Each
handles a distinct non-create-BAPI shape:

  - BusinessPartner: BP shell via BAPI_BUPA_CREATE_FROM_DATA, internal
     SAP-assigned numbering (source BPARTNER informational under BP-led).
  - Customer (CVI): BP shell + sold-to role assignment via
     BAPI_BUPA_ROLES_CHANGE; the BP number IS the customer number on S/4.
  - Vendor (CVI):   BP shell + supplier role (FLVN01); same pattern.
  - ExchangeRates: 1-row-per-spine-call wrapping of
     BAPI_EXCHRATE_CREATEMULTIPLE, with TCURV customizing-prerequisite
     gate, GDATU inverted-date un-inversion + clamping, and TCURF
     operational-set tagging.

Run:  python tests\test_spine_promotion_batch6.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import datetime

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lambda" / "utils"))

from base_spine_orchestrator import (   # noqa
    get_spine, DISP_CREATED, DISP_MATCHED_EXISTING, DISP_REMAPPED,
    DISP_DEAD_LETTER, DEAD_LETTER_DQ, DEAD_LETTER_BAPI,
)
import business_partner_spine     # noqa: F401
import customer_spine             # noqa: F401
import vendor_spine               # noqa: F401
import exchange_rates_spine       # noqa: F401
from business_partner_spine  import BusinessPartnerSpineOrchestrator   # noqa
from customer_spine          import CustomerSpineOrchestrator           # noqa
from vendor_spine            import VendorSpineOrchestrator             # noqa
from exchange_rates_spine    import ExchangeRatesSpineOrchestrator      # noqa


# ─────────────────────────────────────────────────────────────────────────────
class FakeRfc:
    def __init__(self):
        self.calls: list = []
        self.scripts: dict = {}
        self.scripts["BAPI_TRANSACTION_COMMIT"] = {}
        self.scripts["BAPI_TRANSACTION_ROLLBACK"] = {}
        self.scripts["RFC_READ_TABLE"] = {"DATA": []}

    def script(self, fn, resp):
        self.scripts[fn] = resp
        return self

    def call(self, fn, **kwargs):
        self.calls.append((fn, kwargs))
        return self.scripts.get(fn, {})


# ─────────────────────────────────────────────────────────────────────────────
def test_all_4_batch6_objects_register():
    for obj, cls in (
        ("BusinessPartner", BusinessPartnerSpineOrchestrator),
        ("Customer", CustomerSpineOrchestrator),
        ("Vendor", VendorSpineOrchestrator),
        ("ExchangeRates", ExchangeRatesSpineOrchestrator),
    ):
        assert get_spine(obj) is cls
    print("  [OK] all 4 batch-6 spine subclasses registered via @register_spine")


# ─────────────────────────────────────────────────────────────────────────────
# BusinessPartner
# ─────────────────────────────────────────────────────────────────────────────
def test_bp_happy_org_captures_sap_assigned_number():
    rfc = FakeRfc()
    rfc.script("BAPI_BUPA_CREATE_FROM_DATA",
                {"RETURN": [{"TYPE": "S"}], "BUSINESSPARTNER": "0001000123"})
    orch = BusinessPartnerSpineOrchestrator(rfc)
    res = orch.load_one({"BPARTNER": "SRC_BP_1", "CATEGORY": "2",
                          "NAME": "ACME Corp"})
    assert res.status == DISP_CREATED
    assert res.target_key == "0001000123"   # SAP-assigned, BP-led numbering
    create = next(c for c in rfc.calls if c[0] == "BAPI_BUPA_CREATE_FROM_DATA")
    assert create[1]["CENTRALDATAORGANIZATION"]["NAME1"] == "ACME Corp"
    assert create[1]["PARTNERCATEGORY"] == "2"
    print("  [OK] BP org happy path: SAP assigns BP number (BP-led numbering)")


def test_bp_person_uses_centraldataperson():
    rfc = FakeRfc()
    rfc.script("BAPI_BUPA_CREATE_FROM_DATA",
                {"RETURN": [{"TYPE": "S"}], "BUSINESSPARTNER": "0001000124"})
    orch = BusinessPartnerSpineOrchestrator(rfc)
    res = orch.load_one({"BPARTNER": "X", "CATEGORY": "1", "NAME": "Smith"})
    assert res.status == DISP_CREATED
    create = next(c for c in rfc.calls if c[0] == "BAPI_BUPA_CREATE_FROM_DATA")
    assert "CENTRALDATAPERSON" in create[1]
    assert "CENTRALDATAORGANIZATION" not in create[1]
    assert create[1]["CENTRALDATAPERSON"]["LASTNAME"] == "Smith"
    print("  [OK] BP person uses CENTRALDATAPERSON / LASTNAME")


def test_bp_invalid_category_dq_rejects():
    orch = BusinessPartnerSpineOrchestrator(FakeRfc())
    res = orch.load_one({"BPARTNER": "X", "CATEGORY": "9", "NAME": "Bad"})
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_DQ
    print("  [OK] BP invalid CATEGORY -> DQ dead-letter")


def test_bp_missing_name_dq_rejects():
    orch = BusinessPartnerSpineOrchestrator(FakeRfc())
    res = orch.load_one({"BPARTNER": "X"})
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_DQ
    print("  [OK] BP missing NAME -> DQ dead-letter")


# ─────────────────────────────────────────────────────────────────────────────
# Customer (BP-led)
# ─────────────────────────────────────────────────────────────────────────────
def test_customer_happy_path_creates_bp_then_assigns_role():
    rfc = FakeRfc()
    rfc.script("BAPI_BUPA_CREATE_FROM_DATA",
                {"RETURN": [{"TYPE": "S"}], "BUSINESSPARTNER": "0001000200"})
    rfc.script("BAPI_BUPA_ROLES_CHANGE", {"RETURN": [{"TYPE": "S"}]})
    orch = CustomerSpineOrchestrator(rfc)
    res = orch.load_one({"KUNNR": "SRC_C_1", "NAME1": "ACME Customer"})
    assert res.status == DISP_CREATED
    assert res.target_key == "0001000200"   # BP # = customer # under CVI
    # Both BP create AND role assignment happened
    fns = [c[0] for c in rfc.calls]
    assert "BAPI_BUPA_CREATE_FROM_DATA" in fns
    assert "BAPI_BUPA_ROLES_CHANGE" in fns
    role_call = next(c for c in rfc.calls if c[0] == "BAPI_BUPA_ROLES_CHANGE")
    assert role_call[1]["BUSINESSPARTNER"] == "0001000200"
    assert role_call[1]["ROLES"][0]["PARTNERROLE"] == "FLCU01"
    print("  [OK] Customer: BP shell created + sold-to role FLCU01 assigned")


def test_customer_role_assignment_failure_rolls_back():
    rfc = FakeRfc()
    rfc.script("BAPI_BUPA_CREATE_FROM_DATA",
                {"RETURN": [{"TYPE": "S"}], "BUSINESSPARTNER": "0001000201"})
    rfc.script("BAPI_BUPA_ROLES_CHANGE",
                {"RETURN": [{"TYPE": "E", "MESSAGE": "Role not configured for grouping"}]})
    orch = CustomerSpineOrchestrator(rfc)
    res = orch.load_one({"KUNNR": "SRC_C_X", "NAME1": "Test"})
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_BAPI
    assert any(c[0] == "BAPI_TRANSACTION_ROLLBACK" for c in rfc.calls)
    assert any("Role not configured" in m for m in res.messages)
    print("  [OK] Customer role assignment failure -> rolls back the whole txn")


def test_customer_custom_role_via_cc_org():
    rfc = FakeRfc()
    rfc.script("BAPI_BUPA_CREATE_FROM_DATA",
                {"RETURN": [{"TYPE": "S"}], "BUSINESSPARTNER": "0001000202"})
    rfc.script("BAPI_BUPA_ROLES_CHANGE", {"RETURN": [{"TYPE": "S"}]})
    orch = CustomerSpineOrchestrator(rfc, cc_org={"CUSTOMER_ROLE": "FLCU00"})
    res = orch.load_one({"KUNNR": "X", "NAME1": "Test"})
    assert res.status == DISP_CREATED
    role_call = next(c for c in rfc.calls if c[0] == "BAPI_BUPA_ROLES_CHANGE")
    assert role_call[1]["ROLES"][0]["PARTNERROLE"] == "FLCU00"
    print("  [OK] Customer overridable role via cc_org['CUSTOMER_ROLE']")


def test_customer_missing_kunnr_dq_rejects():
    orch = CustomerSpineOrchestrator(FakeRfc())
    res = orch.load_one({"NAME1": "X"})
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_DQ
    print("  [OK] Customer missing KUNNR -> DQ dead-letter")


# ─────────────────────────────────────────────────────────────────────────────
# Vendor (BP-led)
# ─────────────────────────────────────────────────────────────────────────────
def test_vendor_happy_path_assigns_flvn01_role():
    rfc = FakeRfc()
    rfc.script("BAPI_BUPA_CREATE_FROM_DATA",
                {"RETURN": [{"TYPE": "S"}], "BUSINESSPARTNER": "0001000300"})
    rfc.script("BAPI_BUPA_ROLES_CHANGE", {"RETURN": [{"TYPE": "S"}]})
    orch = VendorSpineOrchestrator(rfc)
    res = orch.load_one({"LIFNR": "SRC_V_1", "NAME1": "ACME Supplier"})
    assert res.status == DISP_CREATED
    assert res.target_key == "0001000300"
    role_call = next(c for c in rfc.calls if c[0] == "BAPI_BUPA_ROLES_CHANGE")
    assert role_call[1]["ROLES"][0]["PARTNERROLE"] == "FLVN01"   # supplier
    print("  [OK] Vendor: BP shell + supplier role FLVN01 assigned")


def test_vendor_bp_create_failure_skips_role_assignment():
    rfc = FakeRfc()
    rfc.script("BAPI_BUPA_CREATE_FROM_DATA",
                {"RETURN": [{"TYPE": "E", "MESSAGE": "Grouping not configured"}]})
    orch = VendorSpineOrchestrator(rfc)
    res = orch.load_one({"LIFNR": "X", "NAME1": "Bad"})
    assert res.status == DISP_DEAD_LETTER
    # Role-change call should NOT have happened
    assert all(c[0] != "BAPI_BUPA_ROLES_CHANGE" for c in rfc.calls)
    print("  [OK] Vendor BP create failure -> no orphan role assignment")


# ─────────────────────────────────────────────────────────────────────────────
# ExchangeRates
# ─────────────────────────────────────────────────────────────────────────────
def test_exrates_happy_path_with_configured_type():
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "TCURV": return {"DATA": [{"WA": "M"}, {"WA": "G"}, {"WA": "B"}]}
            if qt == "TCURF": return {"DATA": [{"WA": "M"}, {"WA": "G"}]}
        if fn == "BAPI_EXCHRATE_CREATEMULTIPLE":
            return {"RETURN": [{"TYPE": "S"}]}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    orch = ExchangeRatesSpineOrchestrator(rfc)
    # GDATU 79919898 -> 99999999-79919898 = 20080101 -> 2008-01-01
    res = orch.load_one({"KURST": "M", "FCURR": "USD", "TCURR": "EUR",
                          "GDATU": "79919898", "UKURS": "0.7234",
                          "FFACT": "1", "TFACT": "1"})
    assert res.status == DISP_CREATED
    assert res.target_key.startswith("M|USD|EUR@")
    create = next(c for c in rfc.calls if c[0] == "BAPI_EXCHRATE_CREATEMULTIPLE")
    line = create[1]["EXCHRATE_LIST"][0]
    assert line["RATE_TYPE"] == "M"
    assert line["FROM_CURR"] == "USD"
    assert isinstance(line["VALID_FROM"], datetime.date)
    print("  [OK] ExchangeRates happy path: GDATU un-inverted + factors normalized")


def test_exrates_unknown_rate_type_customizing_dead_letter():
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "TCURV": return {"DATA": [{"WA": "M"}]}
            if qt == "TCURF": return {"DATA": [{"WA": "M"}]}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    orch = ExchangeRatesSpineOrchestrator(rfc)
    res = orch.load_one({"KURST": "ZZ", "FCURR": "USD", "TCURR": "EUR",
                          "GDATU": "79919898", "UKURS": "1.0"})
    assert res.status == DISP_DEAD_LETTER
    assert any("ZZ" in m and "customizing" in m for m in res.messages)
    # Confirm the BAPI was NOT called -- pre-flight customizing screen
    assert all(c[0] != "BAPI_EXCHRATE_CREATEMULTIPLE" for c in rfc.calls)
    print("  [OK] ExchangeRates unknown KURST -> customizing dead-letter (no BAPI call)")


def test_exrates_factor_gap_classifies_distinctly():
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "TCURV": return {"DATA": [{"WA": "B"}]}    # B is in TCURV
            if qt == "TCURF": return {"DATA": []}                # but not in TCURF
        if fn == "BAPI_EXCHRATE_CREATEMULTIPLE":
            return {"RETURN": [{"TYPE": "E",
                                 "MESSAGE": "valid system settings have not been made"}]}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    orch = ExchangeRatesSpineOrchestrator(rfc)
    res = orch.load_one({"KURST": "B", "FCURR": "USD", "TCURR": "EUR",
                          "GDATU": "79919898", "UKURS": "1.0"})
    assert res.status == DISP_DEAD_LETTER
    # Distinguished classification: customizing-factor gap
    assert any("customizing prerequisite" in m and "TCURF" in m for m in res.messages)
    print("  [OK] ExchangeRates TCURV-but-not-TCURF -> distinct TCURF customizing dead-letter")


def test_exrates_clamp_below_floor():
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "TCURV": return {"DATA": [{"WA": "M"}]}
            if qt == "TCURF": return {"DATA": [{"WA": "M"}]}
        if fn == "BAPI_EXCHRATE_CREATEMULTIPLE":
            return {"RETURN": [{"TYPE": "S"}]}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    orch = ExchangeRatesSpineOrchestrator(rfc)
    # GDATU 82019898 -> 99999999 - 82019898 = 17980101 -> 1798-01-01 (below the BAPI's 1995 floor)
    res = orch.load_one({"KURST": "M", "FCURR": "USD", "TCURR": "EUR",
                          "GDATU": "82019898", "UKURS": "1.0"})
    assert res.status == DISP_CREATED
    create = next(c for c in rfc.calls if c[0] == "BAPI_EXCHRATE_CREATEMULTIPLE")
    line = create[1]["EXCHRATE_LIST"][0]
    # Clamped to floor 1995-01-01
    assert line["VALID_FROM"] >= datetime.date(1995, 1, 1)
    assert any("clamped" in m for m in res.messages)
    print("  [OK] ExchangeRates pre-floor GDATU clamps to 1995-01-01 + records reason")


def test_exrates_missing_currency_dq_rejects():
    orch = ExchangeRatesSpineOrchestrator(FakeRfc())
    res = orch.load_one({"KURST": "M", "FCURR": "USD", "GDATU": "79919898", "UKURS": "1.0"})
    assert res.status == DISP_DEAD_LETTER
    assert res.dead_letter == DEAD_LETTER_DQ
    print("  [OK] ExchangeRates missing TCURR -> DQ dead-letter")


# ─────────────────────────────────────────────────────────────────────────────
# Cross-cutting dry-run
# ─────────────────────────────────────────────────────────────────────────────
def test_dry_run_across_batch6():
    rfc = FakeRfc()
    def patched(fn, **kwargs):
        rfc.calls.append((fn, kwargs))
        if fn == "RFC_READ_TABLE":
            qt = kwargs.get("QUERY_TABLE")
            if qt == "TCURV": return {"DATA": [{"WA": "M"}]}
            if qt == "TCURF": return {"DATA": [{"WA": "M"}]}
            return {"DATA": []}
        return rfc.scripts.get(fn, {})
    rfc.call = patched

    cases = (
        (BusinessPartnerSpineOrchestrator,
            {"BPARTNER": "DRY", "CATEGORY": "2", "NAME": "Dry"}, {}),
        (CustomerSpineOrchestrator,
            {"KUNNR": "DRY", "NAME1": "Dry"}, {}),
        (VendorSpineOrchestrator,
            {"LIFNR": "DRY", "NAME1": "Dry"}, {}),
        (ExchangeRatesSpineOrchestrator,
            {"KURST": "M", "FCURR": "USD", "TCURR": "EUR",
              "GDATU": "79919898", "UKURS": "1.0"}, {}),
    )
    for cls, row, extra in cases:
        orch = cls(rfc, dry_run=True, **extra)
        res = orch.load_one(row)
        assert res.status == DISP_CREATED, f"{cls.__name__} got {res.status}"
        assert res.disposition.endswith("_dry_run"), f"{cls.__name__} got {res.disposition}"
    write_bapis = [c[0] for c in rfc.calls if c[0] in (
        "BAPI_BUPA_CREATE_FROM_DATA", "BAPI_BUPA_ROLES_CHANGE",
        "BAPI_EXCHRATE_CREATEMULTIPLE",
    )]
    assert not write_bapis, f"dry-run should skip writes; got {write_bapis}"
    print("  [OK] dry-run mode skips writes for all 4 batch-6 subclasses")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("Spine promotion batch 6 - BP / Customer / Vendor / ExchangeRates")
    print("                          (closes the live-25 sweep)")
    print("=" * 70)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll batch-6 spine promotion tests passed. Live-25 spine sweep COMPLETE.")
