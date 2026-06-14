"""
spine_discovery — find every ``*_spine.py`` module in the Lambda root.

The unified_loader used to maintain a hand-curated tuple of spine module names
("material_spine", "bank_spine", ...). Every new object meant editing that
tuple — a tax the scaffolder (design/SCAFFOLDER_SPEC.md) was supposed to
eliminate. This module replaces the tuple with a directory scan so a generated
spine becomes live the moment it's bundled into the Lambda zip.

Discovery is stable + deterministic:

  - We scan the directory containing this file (the Lambda zip root at runtime;
    lambda/utils/ in development).
  - We look for files matching ``*_spine.py`` (lowercase, ends in _spine.py).
  - We exclude ``base_spine_orchestrator.py`` (the abstract base — never has
    @register_spine on a class).
  - We exclude test files (``test_*_spine.py``) so pytest leftovers don't
    register orchestrators that would crash on import.
  - We return module names sorted so the import order is reproducible across
    runs (matters for any spine that uses ``@register_spine`` side-effects
    that depend on what's already in the registry).

A priority list is supported so dependency-sensitive spines (e.g., Material,
which must be in the registry before Batch / InventoryBalance load) get
imported first. Priority-listed modules are skipped during the discovery
sweep to avoid duplicate-import work.
"""
from __future__ import annotations

import os
from typing import Iterable, List


# Hand-tuned priority order. Modules listed here are imported FIRST and in
# this order; anything not on this list is imported afterwards in alphabetical
# order. Existence is NOT required — a missing priority module is silently
# skipped (the actual import attempt is the source of truth).
PRIORITY_SPINE_MODULES: tuple = (
    # Material is the root FK for many downstream objects (Batch, InventoryBalance,
    # MARC-based loads). Import it first so dependent spines can resolve via key_map.
    "material_spine",
    # CVI / BP shells: needed before Customer/Vendor wrappers can register.
    "business_partner_spine",
    # Master data trunk
    "bank_spine", "cost_center_spine", "profit_center_spine", "equipment_spine",
    "internal_order_spine", "funcloc_spine", "fixed_asset_spine", "project_spine",
    "characteristic_spine", "class_spine",
    "cost_element_group_spine", "profit_center_group_spine",
    # Transactional documents
    "purchase_requisition_spine", "purchase_order_spine",
    "purchase_contract_spine", "sales_order_spine",
    # Postings + balances
    "open_ar_spine", "open_ap_spine", "batch_spine", "inventory_balance_spine",
    # CVI customer + vendor + currency tables
    "customer_spine", "vendor_spine", "exchange_rates_spine",
    # PP + MM + SD extension
    "work_center_spine", "info_record_spine", "quotation_spine",
    "outbound_delivery_spine",
    "inquiry_spine", "billing_document_spine", "planned_order_spine",
    "production_bom_spine",
    # MC file lane orchestrator
    "mc_file_exporter",
)


def _discovery_root() -> str:
    """Return the directory the spine modules live in.

    In a Lambda zip the root is flat — handler.py + every utils/ module at
    the top level. In development we're imported from lambda/utils/, so the
    discovery root is __file__'s dirname. Both cases work because the same
    rule applies: scan the directory this module lives in.
    """
    return os.path.dirname(os.path.abspath(__file__))


def discovered_spine_modules() -> List[str]:
    """Return every importable spine module name in the discovery root.

    Result is sorted alphabetically (deterministic). Priority modules are NOT
    included — they're meant to be loaded separately before discovery.
    """
    root = _discovery_root()
    if not os.path.isdir(root):
        return []
    out: list = []
    seen = set(PRIORITY_SPINE_MODULES)
    for fname in os.listdir(root):
        if not fname.endswith("_spine.py"):
            continue
        if fname.startswith("test_"):
            continue                       # test files masquerading as spines
        if fname == "base_spine_orchestrator.py":
            continue                       # not a spine — the abstract base
        mod = fname[:-3]                   # strip .py
        if mod in seen:
            continue
        seen.add(mod)
        out.append(mod)
    out.sort()
    return out


def load_all_spines(*, verbose: bool = False) -> dict:
    """Import every spine module so @register_spine side-effects populate the
    central registry.

    Returns a summary dict with three lists::

        {"loaded":   [...module names imported successfully...],
         "skipped":  [...priority entries that don't exist on disk...],
         "failures": [(module, error_msg), ...]}

    Each import is independently try/excepted so a single broken module
    cannot poison the entire registry. Failures are reported but never raised
    — the lane falls back to the legacy BapiLoader path for any object whose
    spine didn't register.
    """
    loaded: List[str] = []
    skipped: List[str] = []
    failures: List[tuple] = []

    def _try_import(mod: str):
        try:
            __import__(mod)
            loaded.append(mod)
            if verbose:
                print(f"  + {mod}")
        except ModuleNotFoundError:
            skipped.append(mod)
            if verbose:
                print(f"  - {mod} (not on disk)")
        except Exception as e:               # any other import-time error
            failures.append((mod, f"{type(e).__name__}: {str(e)[:200]}"))
            if verbose:
                print(f"  ! {mod}: {type(e).__name__}: {e}")

    # 1) Priority list, in author-controlled order
    for mod in PRIORITY_SPINE_MODULES:
        _try_import(mod)

    # 2) Filesystem sweep — picks up everything the scaffolder generates
    for mod in discovered_spine_modules():
        _try_import(mod)

    return {"loaded": loaded, "skipped": skipped, "failures": failures}


def registry_snapshot() -> dict:
    """Return a JSON-serialisable view of the current spine registry.

    Used by data-migrator's ``mode: list_spines`` to surface what's actually
    registered to a caller without having to invoke a real load.
    """
    try:
        from base_spine_orchestrator import registered_spines  # type: ignore
    except Exception as e:
        return {"error": f"base_spine_orchestrator unavailable: {e}"}
    types = registered_spines()
    return {
        "registered_count": len(types),
        "object_types": types,
        "priority_modules": list(PRIORITY_SPINE_MODULES),
        "discovered_modules": discovered_spine_modules(),
    }
