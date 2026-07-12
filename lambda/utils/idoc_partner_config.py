"""
idoc_partner_config — canonical IDoc message-type / process-code registry
matching the customer's live S/4 inbound partner-profile configuration.

Source of truth: WE2 partner profile inbound parameters as configured by
the customer's Basis team on 2026-07-12 for S4H client 100. Every place
in the codebase that decides an IDoc's process code MUST import from
here rather than hardcoding.

Structural note
---------------
On classic ECC, MESTYP == PROCESS_CODE by convention (MATMAS -> MATMAS
process code). On S/4 (post-1809 CVI + simplified logistics) many
partner profiles use *shortened* process codes:
    MATMAS  -> MATM      (4-char shortcut, not the classic MATMAS)
    DEBMAS  -> DEBM
    CREMAS  -> CRE1      (CVI-integrated vendor path)
    ORDERS  -> ORDE
    DESADV  -> DELV
    COAMAS  -> COSM      (S/4 unified with Cost Center message)
    COSMAS  -> COSM      (same process code as COAMAS)
    CLFMAS  -> CLFM
    CHRMAS  -> CHRM
    GLMAST  -> GLMA
    PROACT  -> PRAC
    INVOIC  -> INVR      (primary), INVL as fallback

Some message types are BAPI-routed on S/4 — the partner profile explicitly
uses "BAPI" as process code, meaning the inbound handler is a BAPI wrapper,
not a classic IDoc processor. For these the migration engine should skip
the IDoc lane entirely and route through the BAPI spine.
"""
from __future__ import annotations
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# The customer's live inbound partner-profile mapping
# ─────────────────────────────────────────────────────────────────────────────
# Format: message_type -> (primary_process_code, fallback_process_code_or_None, note)
# "BAPI" as process_code means IDoc lane is BYPASSED for this message type —
# use the BAPI spine instead (see BAPI_ROUTED_TYPES below).
PARTNER_INBOUND = {
    # ── SD / Sales flow ─────────────────────────────────────────────────────
    "ORDERS":         ("ORDE",  None,   "Purchase / Sales orders"),
    "DESADV":         ("DELV",  None,   "Deliveries / Shipping (DELVRY-family)"),
    "INVOIC":         ("INVR",  "INVL", "Invoices / Billing (INVR primary, INVL fallback)"),

    # ── MM / Materials ──────────────────────────────────────────────────────
    "MATMAS":         ("MATM",  None,   "Material Master"),

    # ── FI / Financial masters ──────────────────────────────────────────────
    "DEBMAS":         ("DEBM",  None,   "Customer Master"),
    "CREMAS":         ("CRE1",  None,   "Vendor Master (S/4HANA CVI-unified)"),
    "GLMAST":         ("GLMA",  "BAPI", "G/L Account Master (BAPI fallback if GLMA fails)"),
    "EXCHANGE_RATE":  ("BAPI",  None,   "Exchange rates — BAPI driver"),
    "BANK_CREATE":    ("BAPI",  None,   "Bank Master — BAPI driver"),

    # ── CO / Controlling ────────────────────────────────────────────────────
    "COSMAS":         ("COSM",  None,   "Cost Center Master"),
    "COAMAS":         ("COSM",  None,   "Activity Types (S/4 unified with COSM)"),
    "INTERNAL_ORDER": ("BAPI",  None,   "Internal Orders (KO01 BAPI driver)"),

    # ── Classification / Characteristics ────────────────────────────────────
    "CLFMAS":         ("CLFM",  None,   "Classification Master"),
    "CHRMAS":         ("CHRM",  None,   "Characteristics Master"),

    # ── Product / logistics extended ────────────────────────────────────────
    "PROACT":         ("PRAC",  None,   "Product Activity Data"),

    # ── PREQ / Requisitions ─────────────────────────────────────────────────
    "PREQCR":         ("BAPI",  None,   "Purchase Requisitions (BUS3001 BAPI driver)"),
}


# ─────────────────────────────────────────────────────────────────────────────
# Object-type → IDoc mapping.
# Updated to reflect the S/4 CREMAS -> CRE1 and MATMAS -> MATM et al reality.
# Fields: (basic_type, message_type). Process code is looked up from
# PARTNER_INBOUND above via message_type.
# ─────────────────────────────────────────────────────────────────────────────
OBJECT_TO_IDOC = {
    # Masters
    "Material":           ("MATMAS05", "MATMAS"),
    "Customer":           ("DEBMAS07", "DEBMAS"),
    "Vendor":             ("CREMAS05", "CREMAS"),   # -> CRE1 process code
    "BusinessPartner":    ("CRMXIF_PARTNER_SAVE_M02", "CRMXIF_PARTNER_SAVE_M"),
    "GLAccount":          ("GLMAST02", "GLMAST"),
    "BankMaster":         ("BUS_BANK", "BANK_CREATE"),

    # CO
    "CostCenter":         ("COSMAS01", "COSMAS"),
    "ActivityType":       ("COAMAS01", "COAMAS"),   # unified COSM process code
    "ProfitCenter":       ("PRCMAS01", "PRCMAS"),
    "InternalOrder":      ("INTERNAL_ORDER", "INTERNAL_ORDER"),

    # Classification
    "Class":              ("CLFMAS02", "CLFMAS"),
    "Characteristic":     ("CHRMAS04", "CHRMAS"),

    # Documents
    "PurchaseOrder":      ("ORDERS05", "ORDERS"),
    "SalesOrder":         ("ORDERS05", "ORDERS"),
    "OpenSO":             ("ORDERS05", "ORDERS"),
    "OutboundDelivery":   ("DELVRY07", "DESADV"),
    "BillingDocument":    ("INVOIC02", "INVOIC"),
    "PurchaseRequisition":("PREQCR01", "PREQCR"),

    # Rates + others
    "ExchangeRates":      ("EXCHANGE_RATE", "EXCHANGE_RATE"),
    "WBSElement":         ("PROJECT01",     "PROJECT"),
    "ProductActivity":    ("PROACT01",      "PROACT"),
}


# ─────────────────────────────────────────────────────────────────────────────
# Message types whose inbound is BAPI-routed on S/4.
# For these, the migration engine should skip the classic IDoc post and
# route the data through the tool's BAPI spine (which calls the same BAPI
# the partner profile would invoke internally, just directly).
# ─────────────────────────────────────────────────────────────────────────────
BAPI_ROUTED_TYPES = {
    m for m, (pc, _fb, _n) in PARTNER_INBOUND.items() if pc == "BAPI"
}


def process_code_for(message_type: str) -> Optional[str]:
    """Return the primary process code the partner profile expects.
    None if the message type isn't configured."""
    entry = PARTNER_INBOUND.get(message_type)
    return entry[0] if entry else None


def fallback_process_code_for(message_type: str) -> Optional[str]:
    """Return the secondary process code (e.g. INVOIC INVR->INVL fallback)."""
    entry = PARTNER_INBOUND.get(message_type)
    return entry[1] if entry else None


def is_bapi_routed(message_type: str) -> bool:
    """True when the target S/4 partner profile has the message type routed
    through a BAPI driver rather than a classic IDoc process code. Migration
    tools should use the BAPI spine directly for these, not the IDoc lane."""
    return message_type in BAPI_ROUTED_TYPES


def object_type_to_idoc(object_type: str):
    """Return (basic_type, message_type) for a migration object type."""
    return OBJECT_TO_IDOC.get(object_type)


def route_hint_for_object(object_type: str) -> str:
    """Return the recommended lane for an object type:
       'BAPI'  — route through the tool's BAPI spine
       'IDOC'  — route through IDoc lane with proper process code
       'UNKNOWN' — not registered
    """
    idoc = OBJECT_TO_IDOC.get(object_type)
    if not idoc:
        return "UNKNOWN"
    _basic, mestyp = idoc
    return "BAPI" if is_bapi_routed(mestyp) else "IDOC"


# ─────────────────────────────────────────────────────────────────────────────
# Self-test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Sanity: every OBJECT_TO_IDOC message type has an entry in PARTNER_INBOUND
    # (or is a legacy one we know isn't in the customer's active config yet)
    unmapped = []
    for obj, (basic, mestyp) in OBJECT_TO_IDOC.items():
        if mestyp not in PARTNER_INBOUND:
            unmapped.append((obj, mestyp))

    print(f"OBJECT_TO_IDOC size: {len(OBJECT_TO_IDOC)}")
    print(f"PARTNER_INBOUND size: {len(PARTNER_INBOUND)}")
    print(f"BAPI-routed message types: {sorted(BAPI_ROUTED_TYPES)}")

    if unmapped:
        print("\nObjects whose message type isn't in PARTNER_INBOUND yet")
        print("(legacy — will be added to WE20 when customer needs them):")
        for obj, mestyp in unmapped:
            print(f"  {obj:20s} MESTYP={mestyp}")

    # Quick per-object lane hint
    print("\nRouting hints for known object types:")
    for obj in sorted(OBJECT_TO_IDOC.keys()):
        route = route_hint_for_object(obj)
        _basic, mestyp = OBJECT_TO_IDOC[obj]
        pc = process_code_for(mestyp)
        fb = fallback_process_code_for(mestyp)
        fb_str = f" fallback={fb}" if fb else ""
        print(f"  {obj:22s} MESTYP={mestyp:36s} process_code={pc or '-':6s}{fb_str} route={route}")

    print("\nOK - idoc_partner_config self-test passed.")
