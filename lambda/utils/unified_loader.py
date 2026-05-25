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
import time
from collections import Counter

try:
    from bapi_loader import BapiLoader
    from idoc_loader import IDocLoader, RECIPES as IDOC_RECIPES
    from meta_recipe import MetaRecipeResolver
except Exception:  # pragma: no cover
    BapiLoader = IDocLoader = MetaRecipeResolver = None
    IDOC_RECIPES = {}

try:
    import bp_odata   # OData path: create TRANSACTION-READY customers/suppliers (BP-led)
except Exception:  # pragma: no cover
    bp_odata = None

# Target org/config for OData partner creation (env-overridable). Recon accounts are the
# customer/vendor reconciliation GLs in the target company (verified live: 0012100100 / 0021102200).
BP_TARGET_ORG = {
    "COMP_CODE":  os.environ.get("M4H_BP_COMP_CODE", "1710"),
    "CUST_RECON": os.environ.get("M4H_BP_CUST_RECON", "0012100100"),
    "VEND_RECON": os.environ.get("M4H_BP_VEND_RECON", "0021102200"),
    "SALES_ORG":  os.environ.get("M4H_BP_SALES_ORG", "1710"),
    "DISTR_CHAN": os.environ.get("M4H_BP_DISTR_CHAN", "10"),
    "DIVISION":   os.environ.get("M4H_BP_DIVISION", "00"),
    "PURCH_ORG":  os.environ.get("M4H_BP_PURCH_ORG", "1710"),
}

# object -> (mechanism, sub-kind)
OBJECT_MECHANISM = {
    "Customer":        ("bapi", "bp"),
    "Vendor":          ("bapi", "bp"),
    "BusinessPartner": ("bapi", "bp"),
    "Material":        ("bapi", "material"),
    "ExchangeRates":   ("bapi", "exrate"),
    "OpenPO":          ("bapi", "po"),
    "OpenAR":          ("bapi", "fi_ar"),
    "OpenAP":          ("bapi", "fi_ap"),
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

# Target org/config for FI open-item (AR/AP) postings. The offset is a balance-sheet
# 'data takeover' clearing account; profit center satisfies S/4 document splitting.
FI_TARGET_ORG = {
    "COMP_CODE":   os.environ.get("M4H_FI_COMP_CODE", "1710"),
    "CLEARING_GL": os.environ.get("M4H_FI_CLEARING_GL", "0023007000"),
    "PROFIT_CTR":  os.environ.get("M4H_FI_PROFIT_CTR", "YB600"),
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
        self.odata = None          # OData client for transaction-ready partner creation
        self.po_org = dict(PO_TARGET_ORG)
        self.fi_org = dict(FI_TARGET_ORG)
        self.bp_org = dict(BP_TARGET_ORG)

    def odata_ready(self) -> bool:
        """True if the OData BP service is available — gates transaction-ready partner
        creation; falls back to bare-BP RFC otherwise. Cached per run."""
        if self.odata is None or bp_odata is None:
            return False
        cache = getattr(self, "_odata_ok", None)
        if cache is None:
            cache = bp_odata.is_service_active(self.odata)
            self._odata_ok = cache
        return cache

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
        cleanly separates real loads, target-config gaps, and genuine failures.
        At volume (max_rows > 50) we switch to the batched path below."""
        if max_rows > 50:
            return self._load_exrate_batched(obj, rows, max_rows)
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

    def _load_exrate_batched(self, obj: str, rows: list, max_rows: int,
                             batch_size: int = 200, scan_cap: int = 20000) -> dict:
        """Volume path: load rates in batches via BAPI_EXCHRATE_CREATEMULTIPLE. Tries
        FREE rate types first (M, …) — fixed/EMU types like EURX reject free creation —
        and stops once max_rows have posted. Reports throughput; created_keys feed the
        reconciler so the scale claim is proven, not asserted."""
        known = self.bapi.target_rate_types()
        free = self.bapi.free_rate_types()
        missing = Counter()
        candidates = []
        for r in rows:
            kt = (r.get("KURST") or "M").strip()
            if known and kt not in known:
                missing[kt] += 1
            else:
                candidates.append(r)
        # free (postable) types first; 'M' the workhorse ahead of the rest
        candidates.sort(key=lambda r: (0 if (r.get("KURST") or "M").strip() == "M"
                                       else 1 if (r.get("KURST") or "M").strip() in free else 2))
        created = failed = processed = 0
        created_keys, errsample = [], []
        t0 = time.time()
        for i in range(0, min(len(candidates), scan_cap), batch_size):
            if created >= max_rows:
                break
            rb = self.bapi.create_exchange_rates_batch(candidates[i:i + batch_size], commit=True)
            created += rb["created"]
            failed += rb["failed"]
            processed += rb["created"] + rb["failed"]
            created_keys.extend(rb["created_keys"])
            if rb.get("sample_errors") and not errsample:
                errsample = rb["sample_errors"]
        elapsed = round(time.time() - t0, 2)
        result = {"object": obj, "mechanism": "bapi/exrate", "mode": "batched",
                  "attempted": processed, "created_in_s4": created,
                  "config_or_data_gaps": failed,
                  "status_breakdown": {"created": created, "config_or_data_gap": failed},
                  "created_keys": created_keys,
                  "batch_size": batch_size, "elapsed_sec": elapsed,
                  "throughput_per_sec": round(created / elapsed, 1) if elapsed else None,
                  "total_rows": len(rows), "loadable_candidates": len(candidates),
                  "sample_gap_messages": errsample}
        if missing:
            result["missing_ratetype_rows"] = sum(missing.values())
        return result

    def _load_one(self, obj: str, mech: tuple, row: dict) -> dict:
        kind, sub = mech
        if kind == "bapi" and sub == "bp":
            src_key = (row.get("KUNNR") or row.get("LIFNR") or row.get("PARTNER") or "").strip()
            name = (row.get("NAME1") or row.get("MCOD1")
                    or ("BP " + src_key).strip()) or "Migrated BP"
            # Preferred: create a TRANSACTION-READY customer/supplier via OData (BP-led,
            # with company-code + sales/purchasing facets) so dependent docs reference a
            # truly-migrated partner. Falls back to bare-BP RFC if the service is absent.
            o = self.bp_org
            if obj in ("Customer", "Vendor") and self.odata_ready():
                if obj == "Customer":
                    r = bp_odata.create_customer(self.odata, name, o["COMP_CODE"], o["CUST_RECON"],
                                                 sales_org=o["SALES_ORG"], distr_chan=o["DISTR_CHAN"],
                                                 division=o["DIVISION"])
                    tbl, kf, recon = "KNB1", "KUNNR", o["CUST_RECON"]
                else:
                    r = bp_odata.create_supplier(self.odata, name, o["COMP_CODE"], o["VEND_RECON"],
                                                 purch_org=o["PURCH_ORG"])
                    tbl, kf, recon = "LFB1", "LIFNR", o["VEND_RECON"]
                ok = r["status"] == "created"
                num = (r.get("partner") or "")
                pk = num.zfill(10) if num.isdigit() else num
                vkey = ({"table": tbl, "key": {kf: pk, "BUKRS": o["COMP_CODE"]},
                         "values": {"AKONT": recon}} if ok else None)
                kmap = ({"source": src_key, "target": pk, "disposition": "created_ready"}
                        if ok and src_key else None)
                return {"ok": ok, "status": "created_ready" if ok else "failed",
                        "id": pk, "verify_key": vkey, "key_mapping": kmap,
                        "msg": r.get("messages")}
            # fallback: bare BP via RFC (no company-code/sales facets)
            r = self.bapi.create_business_partner(name, category="2", commit=True)
            created = r["status"] == "created"
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
        if kind == "bapi" and sub in ("fi_ar", "fi_ap"):
            arap = "AR" if sub == "fi_ar" else "AP"
            r = self.bapi.create_fi_open_item(row, arap, self.fi_org,
                                              key_map=self.key_map, commit=True)
            return {"ok": r["status"] == "created", "status": r["status"],
                    "id": r.get("doc"), "verify_key": r.get("verify_key"),
                    "key_mapping": r.get("key_mapping"), "refs": r.get("partner"),
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
