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
from concurrent.futures import ThreadPoolExecutor

# Parallel workers for mass loading (pyrfc releases the GIL during RFC calls, so worker
# threads with their OWN connection post concurrently). 1 = single-threaded (default).
LOAD_WORKERS = int(os.environ.get("M4H_LOAD_WORKERS", "1"))
# Per-document BAPI objects safe to parallelize across a worker pool.
PARALLEL_MECHS = {("bapi", "bp"), ("bapi", "material"), ("bapi", "po"),
                  ("bapi", "fi_ar"), ("bapi", "fi_ap")}

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

# object -> the SOURCE key field used for cross-run idempotency (the migration ledger).
# If a source record's key is already in the ledger, we reuse its target, never re-create.
OBJECT_SOURCE_KEY = {
    "Customer": "KUNNR", "Vendor": "LIFNR", "BusinessPartner": "PARTNER",
    "Material": "MATNR", "OpenPO": "EBELN", "OpenAR": "BELNR", "OpenAP": "BELNR",
    "CostCenter": "KOSTL",
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
    "CostCenter":      ("bapi", "costcenter"),
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
        self._init_kwargs = dict(own_logical_system=own_logical_system, sender=sender,
                                 client=client, target_sid=target_sid)
        self.bapi = BapiLoader(tconn)
        self.idoc = IDocLoader(tconn, own_logical_system, sender, client, target_sid)
        self.resolver = MetaRecipeResolver(tconn)
        self.key_map = None        # live source->target registry (set by the handler)
        self.source_conn = None    # ECC conn, for reading dependent rows (PO items)
        self.odata = None          # OData client for transaction-ready partner creation
        # Factories for the parallel worker pool (fresh per-worker connections):
        self.target_conn_factory = None
        self.source_conn_factory = None
        self.odata_factory = None
        self.po_org = dict(PO_TARGET_ORG)
        self.fi_org = dict(FI_TARGET_ORG)
        self.bp_org = dict(BP_TARGET_ORG)
        self.cc_org = {}           # CO master config (set from discovery by the handler)

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
        # Mass load: parallelize per-document BAPI objects across a connection pool
        # (proven ~Nx throughput) when there's enough work to justify the worker setup.
        if (mech in PARALLEL_MECHS and LOAD_WORKERS > 1 and self.target_conn_factory
                and max_rows >= LOAD_WORKERS):
            return self._load_parallel(obj, mech, rows, max_rows, LOAD_WORKERS)
        # Scan for max_rows successes (collisions/skips don't consume the budget),
        # capped so a fully-blocked object can't loop forever. Records already migrated
        # in a prior run (in the cross-run ledger) are REUSED, never re-created.
        out, src_keys, ok_count, scanned = [], [], 0, 0
        scan_cap = max(max_rows * 20, 60)
        t0 = time.time()
        for row in rows:
            if ok_count >= max_rows or scanned >= scan_cap:
                break
            scanned += 1
            reuse = self._ledger_hit(obj, row)
            if reuse:
                res = {"ok": True, "status": "already_migrated", "id": reuse, "reused": True}
            else:
                try:
                    res = self._load_one(obj, mech, row)
                except Exception as e:
                    res = {"ok": False, "status": "exception",
                           "msg": f"{type(e).__name__}: {str(e)[:140]}"}
            out.append(res)
            src_keys.append(self._source_key(obj, row))
            if res.get("ok"):
                ok_count += 1
        elapsed = round(time.time() - t0, 1)
        created = sum(1 for r in out if r.get("ok") and not r.get("reused"))
        reused = sum(1 for r in out if r.get("reused"))
        result = {"object": obj, "mechanism": f"{mech[0]}/{mech[1] or ''}".rstrip("/"),
                  "attempted": len(out), "created_in_s4": created,
                  "status_breakdown": dict(Counter(r.get("status") for r in out)),
                  "created_keys": self._created_keys(out),
                  "samples": [r for r in out if r.get("ok")][:3] or out[:3],
                  "elapsed_sec": elapsed,
                  "throughput_per_sec": round(created / elapsed, 2) if elapsed and created else None}
        if reused:
            result["reused_from_ledger"] = reused
        dl = self._dead_letter(out, src_keys)
        if dl:
            result["failed_count"] = len(dl)
            result["dead_letter"] = dl[:50]
        kmaps = self._key_mappings(out)
        if kmaps:
            result["key_mappings"] = kmaps
        # Populate the live registry as objects load (in DAG order), so later
        # dependent objects (e.g. OpenPO -> Vendor) can resolve their references.
        if self.key_map is not None:
            self.key_map.add_many(obj, kmaps)
        return result

    @staticmethod
    def _source_key(obj: str, row: dict) -> str:
        field = OBJECT_SOURCE_KEY.get(obj)
        return (row.get(field) or "").strip() if field else ""

    def _ledger_hit(self, obj: str, row: dict):
        """If this source record was already migrated (present in the cross-run ledger),
        return its target key so we reuse it instead of creating a duplicate."""
        if self.key_map is None:
            return None
        sk = self._source_key(obj, row)
        return self.key_map.resolve(obj, sk) if sk else None

    @staticmethod
    def _dead_letter(out: list, source_keys: list) -> list:
        """Genuinely failed records (status failed/exception) with source key + reason —
        a dead-letter for targeted reprocessing (the idempotent re-run picks these up;
        records already loaded are skipped). Intentional skips are NOT dead-lettered."""
        dl = []
        for r, sk in zip(out, source_keys):
            if r.get("status") in ("failed", "exception"):
                msg = r.get("msg") or r.get("messages")
                if isinstance(msg, list):
                    msg = "; ".join(str(m) for m in msg[:2])
                dl.append({"source": sk, "status": r.get("status"), "reason": str(msg)[:160]})
        return dl

    def _make_worker(self, mech):
        """A parallel worker = a full loader on a FRESH target connection, sharing the
        thread-safe ledger + org configs. Only opens the extra connections the mechanism
        needs: a source (ECC) conn for PO item reads; an OData client for bp creation."""
        w = UnifiedLoader(self.target_conn_factory(), **self._init_kwargs)
        w.key_map = self.key_map
        w.po_org, w.fi_org, w.bp_org, w.cc_org = self.po_org, self.fi_org, self.bp_org, self.cc_org
        if mech == ("bapi", "po") and self.source_conn_factory:
            w.source_conn = self.source_conn_factory()
        if mech == ("bapi", "bp") and self.odata_factory:
            w.odata = self.odata_factory()
            w._odata_ok = getattr(self, "_odata_ok", None)
        return w

    def _load_parallel(self, obj: str, mech: tuple, rows: list, max_rows: int,
                       workers: int) -> dict:
        """Mass-load a per-document BAPI object across a pool of `workers`, each a loader
        on its own connections. pyrfc frees the GIL per RFC call, so the posts overlap
        (~Nx). The ledger is shared + thread-safe; per-record outcomes match the serial
        path. Used for bp / material / po / fi (each via the worker's _load_one)."""
        work = rows[:max_rows]
        pool = [self._make_worker(mech) for _ in range(workers)]
        chunks = [work[i::workers] for i in range(workers)]
        out = [[] for _ in range(workers)]
        keys = [[] for _ in range(workers)]

        def run(wi):
            w = pool[wi]
            for row in chunks[wi]:
                sk = self._source_key(obj, row)
                keys[wi].append(sk)
                reuse = self.key_map.resolve(obj, sk) if (self.key_map and sk) else None
                if reuse:
                    out[wi].append({"ok": True, "status": "already_migrated", "id": reuse, "reused": True})
                    continue
                try:
                    out[wi].append(w._load_one(obj, mech, row))
                except Exception as e:
                    out[wi].append({"ok": False, "status": "exception",
                                    "msg": f"{type(e).__name__}: {str(e)[:120]}"})

        t0 = time.time()
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(run, range(workers)))
        elapsed = round(time.time() - t0, 1)
        for w in pool:
            for c in (w.c, w.source_conn):
                try:
                    c and c.close()
                except Exception:
                    pass

        flat = [x for sub in out for x in sub]
        flat_keys = [k for sub in keys for k in sub]
        created = sum(1 for r in flat if r.get("ok") and not r.get("reused"))
        reused = sum(1 for r in flat if r.get("reused"))
        kmaps = self._key_mappings(flat)
        if self.key_map is not None:
            self.key_map.add_many(obj, kmaps)
        result = {"object": obj, "mechanism": f"{mech[0]}/{mech[1] or ''}".rstrip("/"),
                  "attempted": len(flat), "created_in_s4": created,
                  "status_breakdown": dict(Counter(r.get("status") for r in flat)),
                  "created_keys": self._created_keys(flat),
                  "samples": [r for r in flat if r.get("ok")][:3] or flat[:3],
                  "elapsed_sec": elapsed, "workers": workers,
                  "throughput_per_sec": round(created / elapsed, 2) if elapsed and created else None}
        if reused:
            result["reused_from_ledger"] = reused
        if kmaps:
            result["key_mappings"] = kmaps
        dl = self._dead_letter(flat, flat_keys)
        if dl:
            result["failed_count"] = len(dl)
            result["dead_letter"] = dl[:50]
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
        if kind == "bapi" and sub == "costcenter":
            r = self.bapi.create_cost_center(row, self.cc_org, commit=True)
            return {"ok": r["status"] in ("created", "matched_existing"), "status": r["status"],
                    "id": r.get("cost_center"), "verify_key": r.get("verify_key"),
                    "key_mapping": r.get("key_mapping"), "msg": r.get("messages")}
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
