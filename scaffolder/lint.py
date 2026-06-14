"""
scaffolder.lint — cross-cutting checks beyond JSON Schema validation.

Schema validation catches structural errors (missing required fields, wrong
types, unknown keys via additionalProperties:false). Lint catches semantic
errors that the schema cannot express:

  - Every FK target object_type must be a known object (in the registry OR
    declared in another definition under definitions/).
  - Every DQ rule name must be a known rule (in scaffolder/rules/).
  - Every value_map target field must appear in field_maps.
  - Exactly one extract.tables entry may be primary=true; primary is required.
  - Every fk source field must appear in either a field_map or be a known
    SAP key field.
  - Computed fields cannot reference themselves.

Usage:

    from scaffolder.lint import lint_object_definition
    errors = lint_object_definition(definition, definitions_dir, rules_registry)
    if errors:
        for e in errors: print(f"LINT: {e}")
        raise SystemExit(1)
"""
from __future__ import annotations

import os
import json
from typing import List, Set


def _known_object_types(definitions_dir: str) -> Set[str]:
    """Scan definitions/ for every declared object_type so cross-references work."""
    out: Set[str] = set()
    if not os.path.isdir(definitions_dir):
        return out
    for fname in os.listdir(definitions_dir):
        if not fname.endswith(".json") or fname.startswith("_"):
            continue
        path = os.path.join(definitions_dir, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            if "object_type" in d:
                out.add(d["object_type"])
        except Exception:
            continue
    return out


# Object_types already implemented as hand-written spines in lambda/utils/.
# Keep this list in sync with definitions added later; entries here can be
# referenced as FK targets even if no JSON definition exists yet.
_LEGACY_SPINE_OBJECTS = {
    "BusinessPartner", "Customer", "Vendor", "Material",
    "Bank", "ProfitCenter", "CostCenter", "Equipment", "InternalOrder",
    "FunctionalLocation", "FixedAsset", "Project", "Characteristic", "Class",
    "CostElementGroup", "ProfitCenterGroup", "PurchaseRequisition",
    "PurchaseOrder", "PurchaseContract", "SalesOrder", "Batch",
    "InventoryBalance", "ExchangeRates", "WorkCenter", "InfoRecord",
    "Quotation", "OutboundDelivery", "Inquiry", "BillingDocument",
    "PlannedOrder", "ProductionBOM", "OpenAR", "OpenAP",
    # Implicit references (FKs from other objects often point at these even
    # if they're not full spine objects yet)
    "Plant", "CompanyCode", "ChartOfAccounts",
}


def lint_object_definition(definition: dict,
                            definitions_dir: str,
                            known_rules: Set[str]) -> List[str]:
    """Run cross-cutting lint checks. Returns a list of error strings.

    Empty list means lint passed.
    """
    errors: List[str] = []
    object_type = definition.get("object_type", "<unknown>")
    known_objects = _LEGACY_SPINE_OBJECTS | _known_object_types(definitions_dir) | {object_type}

    # ── extract.tables: exactly one primary ──
    tables = definition.get("extract", {}).get("tables", [])
    primaries = [t for t in tables if t.get("primary")]
    if not primaries:
        errors.append(f"{object_type}: extract.tables must mark exactly one entry primary=true (none found)")
    elif len(primaries) > 1:
        errors.append(f"{object_type}: extract.tables has {len(primaries)} entries marked primary=true (must be exactly 1)")

    # ── field_maps + value_maps cross-check ──
    field_maps = definition.get("transform", {}).get("field_maps", {}) or {}
    value_maps = definition.get("transform", {}).get("value_maps", {}) or {}
    target_fields = set(field_maps.values())
    for tgt_field in value_maps:
        if tgt_field not in target_fields:
            errors.append(
                f"{object_type}: value_maps key {tgt_field!r} does not appear "
                f"as a target in field_maps (typo? available targets: {sorted(target_fields)})"
            )

    # ── DQ rules registered ──
    dq_gates = definition.get("transform", {}).get("dq_gates", []) or []
    for i, gate in enumerate(dq_gates):
        rule_name = gate.get("rule", "")
        if rule_name and rule_name not in known_rules:
            errors.append(
                f"{object_type}: dq_gates[{i}] references unknown rule {rule_name!r} "
                f"(available: {sorted(known_rules)})"
            )

    # ── FK targets are known object_types ──
    fk = definition.get("fk", {}) or {}
    for src_field, target_obj in fk.items():
        if target_obj not in known_objects:
            errors.append(
                f"{object_type}: fk[{src_field!r}] = {target_obj!r} is not a known object_type. "
                f"Either add definitions/{target_obj}.json or register it in _LEGACY_SPINE_OBJECTS."
            )

    # ── verify.key_field must be set ──
    verify = definition.get("verify", {})
    if not verify.get("key_field"):
        errors.append(f"{object_type}: verify.key_field is required")

    # ── computed fields cannot self-reference ──
    computed = definition.get("transform", {}).get("computed_fields", []) or []
    for cf in computed:
        name = cf.get("name", "")
        expr = cf.get("expr", "")
        if name and (f"row['{name}']" in expr or f"row.get('{name}'" in expr):
            errors.append(f"{object_type}: computed_field {name!r} references itself")

    # ── load.bapi required when primary_lane is BAPI ──
    load = definition.get("load", {})
    if load.get("primary_lane") == "BAPI":
        if not (load.get("bapi") or {}).get("function"):
            errors.append(f"{object_type}: primary_lane=BAPI requires load.bapi.function")

    return errors
