"""
unified_loader — mechanism-agnostic load dispatcher.

Picks the BEST write mechanism per object type and feeds it values from the
MetaRecipeResolver. One entry point (load_object) so the pipeline doesn't care
whether an object goes via BAPI, IDoc, or (later) Migration Cockpit.

    Customer / Vendor / BusinessPartner -> BAPI (BUPA)  [sidesteps MDG/IDoc wall]
    Material                            -> BAPI (cleanest; resolver-validated)
    ExchangeRates                       -> BAPI (BAPI_EXCHRATE_CREATEMULTIPLE)
    BankStatements                      -> IDoc
"""
from __future__ import annotations
from collections import Counter

try:
    from bapi_loader import BapiLoader
    from idoc_loader import IDocLoader, RECIPES as IDOC_RECIPES
    from meta_recipe import MetaRecipeResolver
except Exception:  # pragma: no cover
    BapiLoader = IDocLoader = MetaRecipeResolver = None
    IDOC_RECIPES = {}

# object -> (mechanism, sub-kind)
OBJECT_MECHANISM = {
    "Customer":        ("bapi", "bp"),
    "Vendor":          ("bapi", "bp"),
    "BusinessPartner": ("bapi", "bp"),
    "Material":        ("bapi", "material"),
    "ExchangeRates":   ("bapi", "exrate"),
    "BankStatements":  ("idoc", None),
}


class UnifiedLoader:
    def __init__(self, tconn, own_logical_system="S4HCLNT100", sender="M4HSENDER",
                 client="100", target_sid="S4H"):
        self.c = tconn
        self.bapi = BapiLoader(tconn)
        self.idoc = IDocLoader(tconn, own_logical_system, sender, client, target_sid)
        self.resolver = MetaRecipeResolver(tconn)

    def supported(self, obj: str) -> bool:
        return obj in OBJECT_MECHANISM

    def load_object(self, obj: str, rows: list, max_rows: int = 5) -> dict:
        mech = OBJECT_MECHANISM.get(obj)
        if not mech:
            return {"object": obj, "loaded": False, "reason": "no mechanism registered"}
        # Exchange rates need special handling: loadability depends on target
        # customizing (rate type in TCURV + currency-pair factors in TCURF), which
        # no static screen fully predicts. So attempt-and-classify — see _load_exrate.
        if mech == ("bapi", "exrate"):
            return self._load_exrate(obj, mech, rows, max_rows)
        out = []
        for row in rows[:max_rows]:
            try:
                out.append(self._load_one(obj, mech, row))
            except Exception as e:
                out.append({"ok": False, "status": "exception",
                            "msg": f"{type(e).__name__}: {str(e)[:140]}"})
        created = sum(1 for r in out if r.get("ok"))
        return {"object": obj, "mechanism": f"{mech[0]}/{mech[1] or ''}".rstrip("/"),
                "attempted": len(out), "created_in_s4": created,
                "status_breakdown": dict(Counter(r.get("status") for r in out)),
                "created_keys": self._created_keys(out),
                "samples": out[:3]}

    def _load_exrate(self, obj: str, mech: tuple, rows: list, max_rows: int,
                     scan_cap: int = 120) -> dict:
        """Load up to max_rows *successful* exchange rates. Rows are tried with
        operational (factor-configured) rate types first so we spend the budget on
        the rates that will actually post; rows whose type is missing entirely are
        set aside without an attempt. Each outcome is classified so the summary
        cleanly separates real loads, target-config gaps, and genuine failures."""
        known = self.bapi.target_rate_types()           # exists in TCURV
        configured = self.bapi.configured_rate_types()  # has TCURF factors
        missing = Counter()
        candidates = []
        for r in rows:
            kt = (r.get("KURST") or "M").strip()
            if known and kt not in known:
                missing[kt] += 1                        # type not defined in target
            else:
                candidates.append(r)
        # operational types first → find the loadable rates fast
        candidates.sort(key=lambda r: 0 if (r.get("KURST") or "M").strip() in configured else 1)

        out, created, scanned = [], 0, 0
        for row in candidates:
            if created >= max_rows or scanned >= scan_cap:
                break
            scanned += 1
            try:
                res = self._load_one(obj, mech, row)
            except Exception as e:
                res = {"ok": False, "status": "exception",
                       "msg": f"{type(e).__name__}: {str(e)[:140]}"}
            out.append(res)
            if res.get("ok"):
                created += 1

        result = {"object": obj, "mechanism": "bapi/exrate",
                  "attempted": len(out), "created_in_s4": created,
                  "status_breakdown": dict(Counter(r.get("status") for r in out)),
                  "created_keys": self._created_keys(out),
                  "samples": [r for r in out if r.get("ok")][:3] or out[:3],
                  "total_rows": len(rows), "loadable_candidates": len(candidates)}
        if missing:
            result["missing_ratetype_rows"] = sum(missing.values())
            result["missing_rate_types"] = dict(sorted(missing.items(), key=lambda x: -x[1]))
        return result

    def _load_one(self, obj: str, mech: tuple, row: dict) -> dict:
        kind, sub = mech
        if kind == "bapi" and sub == "bp":
            name = (row.get("NAME1") or row.get("MCOD1")
                    or ("BP " + (row.get("KUNNR") or row.get("LIFNR") or "")).strip())
            r = self.bapi.create_business_partner(name.strip() or "Migrated BP",
                                                  category="2", commit=True)
            return {"ok": r["status"] == "created", "status": r["status"],
                    "id": r.get("partner"), "verify_key": r.get("verify_key"),
                    "msg": r.get("messages")}
        if kind == "bapi" and sub == "material":
            matnr = (row.get("MATNR") or "").strip()
            mtart = self.resolver.resolve("MARA", "MTART", row)["value"] or "HALB"
            meins = self.resolver.resolve("MARA", "MEINS", row)["value"] or "EA"
            r = self.bapi.create_material(matnr or None, mtype=mtart, uom=meins, commit=True)
            return {"ok": r["status"] == "created", "status": r["status"],
                    "id": r.get("material"), "verify_key": r.get("verify_key"),
                    "msg": r.get("messages")}
        if kind == "bapi" and sub == "exrate":
            r = self.bapi.create_exchange_rate(row, commit=True)
            return {"ok": r["status"] == "created", "status": r["status"],
                    "id": r.get("rate"), "verify_key": r.get("verify_key"),
                    "msg": r.get("messages")}
        if kind == "idoc":
            r = self.idoc.post_resolved(obj, row, self.resolver)
            return {"ok": bool(r.get("created")), "status": r.get("status"), "id": r.get("docnum")}
        return {"ok": False, "status": "unknown_mechanism"}

    @staticmethod
    def _created_keys(out: list) -> list:
        """Verification keys for the records that loaded — fed to the Reconciler to
        prove each one persisted in the target system of record."""
        return [r["verify_key"] for r in out if r.get("ok") and r.get("verify_key")]
