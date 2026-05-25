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
import os
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
    "OpenPO":          ("bapi", "po"),
    "BankStatements":  ("idoc", None),
}

# Target org model that source POs are remapped into. In production this is a
# business-provided org-mapping table; here it's a config default (S/4 BP 1710 model).
PO_TARGET_ORG = {
    "COMP_CODE": os.environ.get("M4H_PO_COMP_CODE", "1710"),
    "PURCH_ORG": os.environ.get("M4H_PO_PURCH_ORG", "1710"),
    "PLANT":     os.environ.get("M4H_PO_PLANT", "1710"),
    "PUR_GROUP": os.environ.get("M4H_PO_PUR_GROUP", "001"),
    "DOC_TYPE":  os.environ.get("M4H_PO_DOC_TYPE", "NB"),
    "PO_UNIT":   os.environ.get("M4H_PO_UNIT", "EA"),
    "MATL_GROUP": os.environ.get("M4H_PO_MATL_GROUP", "L001"),
    "GL_ACCOUNT": os.environ.get("M4H_PO_GL_ACCOUNT", "0052513000"),
    "COSTCENTER": os.environ.get("M4H_PO_COSTCENTER", "0017101601"),
}


class UnifiedLoader:
    def __init__(self, tconn, own_logical_system="S4HCLNT100", sender="M4HSENDER",
                 client="100", target_sid="S4H"):
        self.c = tconn
        self.bapi = BapiLoader(tconn)
        self.idoc = IDocLoader(tconn, own_logical_system, sender, client, target_sid)
        self.resolver = MetaRecipeResolver(tconn)
        self.key_map = None        # live source->target registry (set by the handler)
        self.source_conn = None    # ECC conn, for reading dependent rows (PO items)
        self.po_org = dict(PO_TARGET_ORG)

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
        # Scan for max_rows successes (collisions/skips don't consume the budget),
        # capped so a fully-blocked object can't loop forever.
        out, created, scanned = [], 0, 0
        scan_cap = max(max_rows * 20, 60)
        for row in rows:
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
        result = {"object": obj, "mechanism": f"{mech[0]}/{mech[1] or ''}".rstrip("/"),
                  "attempted": len(out), "created_in_s4": created,
                  "status_breakdown": dict(Counter(r.get("status") for r in out)),
                  "created_keys": self._created_keys(out),
                  "samples": [r for r in out if r.get("ok")][:3] or out[:3]}
        kmaps = self._key_mappings(out)
        if kmaps:
            result["key_mappings"] = kmaps
        # Populate the live registry as objects load (in DAG order), so later
        # dependent objects (e.g. OpenPO -> Vendor) can resolve their references.
        if self.key_map is not None:
            self.key_map.add_many(obj, kmaps)
        return result

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
            src_key = (row.get("KUNNR") or row.get("LIFNR") or row.get("PARTNER") or "").strip()
            name = (row.get("NAME1") or row.get("MCOD1")
                    or ("BP " + src_key).strip())
            r = self.bapi.create_business_partner(name.strip() or "Migrated BP",
                                                  category="2", commit=True)
            created = r["status"] == "created"
            # source customer/vendor/BP -> new target partner number (transactional
            # data must follow this); recorded in the run's key registry.
            kmap = ({"source": src_key, "target": r.get("partner"), "disposition": "created"}
                    if created and src_key else None)
            return {"ok": created, "status": r["status"],
                    "id": r.get("partner"), "verify_key": r.get("verify_key"),
                    "key_mapping": kmap, "msg": r.get("messages")}
        if kind == "bapi" and sub == "material":
            matnr = (row.get("MATNR") or "").strip()
            mtart = self.resolver.resolve("MARA", "MTART", row)["value"] or "HALB"
            meins = self.resolver.resolve("MARA", "MEINS", row)["value"] or "EA"
            r = self.bapi.create_material(matnr or None, mtype=mtart, uom=meins, commit=True)
            ok_states = {"created", "matched_existing", "remapped", "remapped_matched"}
            return {"ok": r["status"] in ok_states, "status": r["status"],
                    "id": r.get("material"), "verify_key": r.get("verify_key"),
                    "key_mapping": r.get("key_mapping"), "msg": r.get("messages")}
        if kind == "bapi" and sub == "exrate":
            r = self.bapi.create_exchange_rate(row, commit=True)
            return {"ok": r["status"] == "created", "status": r["status"],
                    "id": r.get("rate"), "verify_key": r.get("verify_key"),
                    "msg": r.get("messages")}
        if kind == "bapi" and sub == "po":
            items = self._po_items(row.get("EBELN"))
            r = self.bapi.create_purchase_order(row, items, self.po_org,
                                                key_map=self.key_map, commit=True)
            return {"ok": r["status"] == "created", "status": r["status"],
                    "id": r.get("po"), "verify_key": r.get("verify_key"),
                    "key_mapping": r.get("key_mapping"), "refs": r.get("vendor"),
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

    @staticmethod
    def _key_mappings(out: list) -> list:
        """source->target key dispositions (created/matched/remapped/collision) — the
        traceability record dependent objects follow, and proof we never corrupt."""
        return [r["key_mapping"] for r in out if r.get("key_mapping")]

    _EKPO_FIELDS = ("EBELP", "MATNR", "WERKS", "MENGE", "MEINS", "NETPR", "KNTTP")

    def _po_items(self, ebeln) -> list:
        """Read a PO's items (EKPO) from the SOURCE system, on demand for the POs we
        actually load (avoids enriching every extracted header)."""
        ebeln = (ebeln or "").strip()
        if not (self.source_conn and ebeln):
            return []
        try:
            r = self.source_conn.call("RFC_READ_TABLE", QUERY_TABLE="EKPO", DELIMITER="|",
                                      OPTIONS=[{"TEXT": f"EBELN = '{ebeln}'"}],
                                      FIELDS=[{"FIELDNAME": f} for f in self._EKPO_FIELDS],
                                      ROWCOUNT=100)
            return [dict(zip(self._EKPO_FIELDS, [x.strip() for x in d["WA"].split("|")]))
                    for d in r.get("DATA", [])]
        except Exception:
            return []
