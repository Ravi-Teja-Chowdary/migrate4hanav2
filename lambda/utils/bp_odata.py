"""
bp_odata — create TRANSACTION-READY customers/suppliers via API_BUSINESS_PARTNER (OData).

This is the answer to the RFC dead-end (see partner-readiness-cvi memory): the released
API_BUSINESS_PARTNER OData service creates a BP-led customer/supplier WITH the company-code
and sales/purchasing facets in one deep-insert — honoring CVI external numbering, fully
SAP-supported. So a migrated vendor/customer becomes directly usable on POs / AR / AP / SO
(no harmonization fallback), under its own new BP number.

Prereq (one-time, setup not run-time): activate API_BUSINESS_PARTNER in the gateway
(/IWFND/MAINT_SERVICE or the "Activate and Maintain Services" Fiori app). Until then
is_service_active() returns False and the loaders fall back to harmonization.

Deep-insert shapes follow the standard API_BUSINESS_PARTNER schema:
  A_BusinessPartner -> to_BusinessPartnerRole (FLCU01/FLVN01)
                    -> to_Customer -> to_CustomerCompany / to_CustomerSalesArea
                    -> to_Supplier -> to_SupplierCompany / to_SupplierPurchasingOrg
"""
from __future__ import annotations

SERVICE = "API_BUSINESS_PARTNER"


def is_service_active(oc) -> bool:
    """True if API_BUSINESS_PARTNER is published on the gateway (else activation pending)."""
    try:
        r = oc.get(SERVICE, "A_BusinessPartner", {"$top": "1"})
        return r.status_code == 200
    except Exception:
        return False


def _bp_name_fields(name: str, category: str) -> dict:
    name = (name or "Migrated BP").strip()
    if category == "1":   # person
        return {"FirstName": name[:40], "LastName": (name[:40] or "BP")}
    return {"OrganizationBPName1": name[:40]}            # organization


def create_customer(oc, name: str, company_code: str, recon_account: str,
                    grouping: str = "", sales_org: str = None, distr_chan: str = None,
                    division: str = None, country: str = "US", category: str = "2") -> dict:
    """Create a customer (BP + FLCU01 role + company-code [+ sales area]) in one deep-insert.
    Returns {status, partner, customer, messages}."""
    customer = {"to_CustomerCompany": {"results": [
        {"CompanyCode": company_code, "ReconciliationAccount": recon_account}]}}
    if sales_org:
        customer["to_CustomerSalesArea"] = {"results": [
            {"SalesOrganization": sales_org, "DistributionChannel": distr_chan or "10",
             "Division": division or "00"}]}
    payload = {
        "BusinessPartnerCategory": category,
        "BusinessPartnerGrouping": grouping,            # blank -> standard internal grouping
        "to_BusinessPartnerRole": {"results": [{"BusinessPartnerRole": "FLCU01"}]},
        "to_Customer": customer,
    }
    payload.update(_bp_name_fields(name, category))
    return _post_bp(oc, payload, kind="customer")


def create_supplier(oc, name: str, company_code: str, recon_account: str,
                    grouping: str = "", purch_org: str = None, country: str = "US",
                    category: str = "2") -> dict:
    """Create a supplier (BP + FLVN01 role + company-code [+ purchasing org]) in one deep-insert."""
    supplier = {"to_SupplierCompany": {"results": [
        {"CompanyCode": company_code, "ReconciliationAccount": recon_account}]}}
    if purch_org:
        supplier["to_SupplierPurchasingOrg"] = {"results": [{"PurchasingOrganization": purch_org}]}
    payload = {
        "BusinessPartnerCategory": category,
        "BusinessPartnerGrouping": grouping,
        "to_BusinessPartnerRole": {"results": [{"BusinessPartnerRole": "FLVN01"}]},
        "to_Supplier": supplier,
    }
    payload.update(_bp_name_fields(name, category))
    return _post_bp(oc, payload, kind="supplier")


def _post_bp(oc, payload: dict, kind: str) -> dict:
    r = oc.post(SERVICE, "A_BusinessPartner", payload)
    if r.status_code in (200, 201):
        d = r.json().get("d", {})
        partner = (d.get("BusinessPartner") or "").strip()
        sub = ((d.get("to_Customer") or {}).get("Customer")
               or (d.get("to_Supplier") or {}).get("Supplier") or partner)
        return {"status": "created", "partner": partner, kind: (sub or "").strip(),
                "messages": []}
    return {"status": "failed", "partner": None,
            "messages": oc.error_messages(r), "http_status": r.status_code}
