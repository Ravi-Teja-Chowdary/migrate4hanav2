"""
bapi_loader — BAPI-based write adapter (the cleanest mechanism for most master
data when a super-admin RFC user is available). Sits alongside idoc_loader;
both are fed by meta_recipe.MetaRecipeResolver.

BAPIs are SAP-shipped, business-logic-honoring APIs — fully support-preserving
(they are NOT raw table writes). For Business Partner / Customer / Vendor this
path sidesteps the DEBMAS/MDG IDoc bottleneck entirely.
"""
from __future__ import annotations
import datetime
import re

try:
    from sap_number import parse_sap_number
except Exception:  # pragma: no cover
    def parse_sap_number(v, default=0.0):
        try:
            s = str(v).strip()
            return -float(s[:-1]) if s.endswith("-") else float(s)
        except Exception:
            return default


class BapiLoader:
    def __init__(self, conn):
        self.c = conn

    def _ret(self, res):
        r = res.get("RETURN", [])
        return r if isinstance(r, list) else [r]

    def _commit(self):
        self.c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")

    def _rollback(self):
        try:
            self.c.call("BAPI_TRANSACTION_ROLLBACK")
        except Exception:
            pass

    # ── Business Partner (Customer/Vendor consolidate to BP in S/4) ─────────
    def create_business_partner(self, name: str, category: str = "2",
                                grouping: str = "", commit: bool = True,
                                verify: bool = True) -> dict:
        """Create an organization ('2') or person ('1') BP.
        Returns {status, partner, messages, verified}."""
        kwargs = {"PARTNERCATEGORY": category}
        if category == "1":
            kwargs["CENTRALDATAPERSON"] = {"LASTNAME": name[:40]}
        else:
            kwargs["CENTRALDATAORGANIZATION"] = {"NAME1": name[:40]}
        if grouping:
            kwargs["PARTNERGROUP"] = grouping

        res = self.c.call("BAPI_BUPA_CREATE_FROM_DATA", **kwargs)
        ret = self._ret(res)
        bp = (res.get("BUSINESSPARTNER") or "").strip()
        errs = [m for m in ret if m.get("TYPE") in ("E", "A")]
        if errs or not bp:
            self._rollback()
            return {"status": "failed", "partner": bp,
                    "messages": [f"{m.get('TYPE')} {m.get('MESSAGE')}" for m in ret]}
        if commit:
            self._commit()
        verified = self._verify_but000(bp) if (commit and verify) else None
        name_field = "NAME_LAST" if category == "1" else "NAME_ORG1"
        return {"status": "created", "partner": bp, "verified": verified,
                "verify_key": {"table": "BUT000", "key": {"PARTNER": bp},
                               "values": {"TYPE": category, name_field: name[:40]}},
                "messages": [m.get("MESSAGE") for m in ret if m.get("TYPE") == "W"]}

    def _verify_but000(self, partner: str) -> bool:
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="BUT000", DELIMITER="|",
                            OPTIONS=[{"TEXT": f"PARTNER = '{partner}'"}],
                            FIELDS=[{"FIELDNAME": "PARTNER"}], ROWCOUNT=1)
            return bool(r.get("DATA"))
        except Exception:
            return False

    # ── Material (BAPI is cleaner than the MATMAS IDoc) ─────────────────────
    def _material_identity(self, matnr: str):
        """(MTART, MBRSH) if the material exists in the target, else None."""
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="MARA", DELIMITER="|",
                            OPTIONS=[{"TEXT": f"MATNR = '{matnr}'"}],
                            FIELDS=[{"FIELDNAME": "MTART"}, {"FIELDNAME": "MBRSH"}], ROWCOUNT=1)
            if r.get("DATA"):
                v = [x.strip() for x in r["DATA"][0]["WA"].split("|")]
                return (v[0], v[1])
        except Exception:
            pass
        return None

    @staticmethod
    def _remap_matnr(matnr: str) -> str:
        """Deterministic, reversible collision-free target number for a source MATNR."""
        return ("M4H" + (matnr.lstrip("0") or "0"))[:40]

    def _save_material(self, matnr, mtype, ind, uom, desc, commit):
        res = self.c.call("BAPI_MATERIAL_SAVEDATA",
                          HEADDATA={"MATERIAL": matnr, "IND_SECTOR": ind,
                                    "MATL_TYPE": mtype, "BASIC_VIEW": "X"},
                          CLIENTDATA={"BASE_UOM": uom}, CLIENTDATAX={"BASE_UOM": "X"},
                          MATERIALDESCRIPTION=[{"LANGU": "EN", "MATL_DESC": desc}])
        ret = self._ret(res)
        if [m for m in ret if m.get("TYPE") in ("E", "A")]:
            self._rollback()
            return None, [f"{m.get('TYPE')} {m.get('MESSAGE')}" for m in ret]
        if commit:
            self._commit()
        return matnr, [m.get("MESSAGE") for m in ret]

    def create_material(self, matnr: str, mtype="HALB", ind="M", uom="EA",
                        desc="Migrate4HANA material", commit: bool = True,
                        on_collision: str = "remap") -> dict:
        """Collision-aware material load with a source->target key strategy. A source
        MATNR may already name a DIFFERENT material in the target (common between IDES
        clones). We never silently extend the wrong material:
          - absent in target           -> create with the retained number ("created")
          - present, same identity      -> idempotent ("matched_existing")
          - present, different identity -> COLLISION: remap to a collision-free number
            preserving the source's identity ("remapped"), or skip if on_collision=skip.
        Always returns a key_mapping (source->target+disposition) for traceability and
        for dependent objects to follow."""
        matnr = (matnr or "").strip()

        def ok(status, target, msgs):
            return {"status": status, "material": target,
                    "verify_key": {"table": "MARA", "key": {"MATNR": target},
                                   "values": {"MTART": mtype}},
                    "key_mapping": {"source": matnr, "target": target, "disposition": status},
                    "messages": msgs}

        ident = self._material_identity(matnr) if matnr else None
        if matnr and ident is None:                              # net-new -> retain number
            tgt, msgs = self._save_material(matnr, mtype, ind, uom, desc, commit)
            return ok("created", tgt, msgs) if tgt else {
                "status": "failed", "material": matnr,
                "key_mapping": {"source": matnr, "target": matnr, "disposition": "create_failed"},
                "messages": msgs}
        if ident and ident == (mtype, ind):                      # already there, same identity
            return ok("matched_existing", matnr,
                      [f"material {matnr} already present with type {mtype}"])
        # COLLISION — a different material occupies this number
        if on_collision == "skip" or not matnr:
            return {"status": "collision", "material": matnr,
                    "key_mapping": {"source": matnr, "target": None,
                                    "disposition": "collision_skipped",
                                    "existing": ident, "desired": [mtype, ind]},
                    "messages": [f"MATNR {matnr} collides (target {ident} vs source "
                                 f"{(mtype, ind)}); skipped to avoid corrupting it"]}
        remapped = self._remap_matnr(matnr)
        rident = self._material_identity(remapped)
        tag = f"{desc} [migrated from {matnr}]"
        if rident is None:
            tgt, msgs = self._save_material(remapped, mtype, ind, uom, tag, commit)
            return ok("remapped", tgt, msgs) if tgt else {
                "status": "failed", "material": remapped,
                "key_mapping": {"source": matnr, "target": remapped, "disposition": "remap_failed"},
                "messages": msgs}
        if rident == (mtype, ind):
            return ok("remapped_matched", remapped,
                      [f"remapped material {remapped} already present with type {mtype}"])
        return {"status": "collision", "material": matnr,
                "key_mapping": {"source": matnr, "target": remapped,
                                "disposition": "remap_collision"},
                "messages": [f"both {matnr} and remap {remapped} occupied by other materials"]}

    # ── Purchase order (BAPI_PO_CREATE1) — first TRANSACTIONAL object ────────
    def _ready_suppliers(self, ekorg: str) -> list:
        """Cached list of purchasing-ready suppliers (LFM1) for a purchasing org."""
        cache = getattr(self, "_sup_cache", {})
        if ekorg not in cache:
            try:
                r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="LFM1", DELIMITER="|",
                                OPTIONS=[{"TEXT": f"EKORG = '{ekorg}'"}],
                                FIELDS=[{"FIELDNAME": "LIFNR"}], ROWCOUNT=200)
                cache[ekorg] = [d["WA"].strip() for d in r.get("DATA", [])]
            except Exception:
                cache[ekorg] = []
            self._sup_cache = cache
        return cache[ekorg]

    def create_purchase_order(self, header: dict, items: list, org: dict,
                              key_map=None, commit: bool = True) -> dict:
        """Create a PO via BAPI_PO_CREATE1 — the first transactional object, and the
        first that CONSUMES the key registry. Vendor resolution: registry first; if the
        source vendor wasn't migrated to a purchasing-ready supplier, harmonize it to an
        existing ready target supplier (a real migration pattern) and record that back in
        the registry. Org units are remapped to the target model (org param). Items are
        account-assigned (KNTTP=K) with short text — no material-master dependency,
        matching the source POs."""
        src_po = (header.get("EBELN") or "").strip()
        src_vendor = (header.get("LIFNR") or "").strip()
        ekorg = org["PURCH_ORG"]
        ready = set(self._ready_suppliers(ekorg))
        tgt_vendor = key_map.resolve("Vendor", src_vendor) if key_map else None
        vdisp = "registry"
        if not (tgt_vendor and tgt_vendor in ready):
            if not ready:
                return {"status": "no_target_supplier",
                        "messages": [f"no purchasing-ready supplier for org {ekorg}"]}
            pool = sorted(ready)
            digits = "".join(ch for ch in src_vendor if ch.isdigit())
            tgt_vendor = pool[(int(digits) if digits else 0) % len(pool)]
            vdisp = "harmonized"
            if key_map:
                key_map.add("Vendor", src_vendor, tgt_vendor, "harmonized")

        poitem, poitemx, acct, acctx = [], [], [], []
        for i, it in enumerate(items or [], start=1):
            n = "%05d" % (i * 10)
            qty = str(int(parse_sap_number(it.get("MENGE"), 1)) or 1)
            txt = ("Material " + it["MATNR"]) if it.get("MATNR") else f"Migrated item PO {src_po}"
            poitem.append({"PO_ITEM": n, "SHORT_TEXT": txt[:40], "PLANT": org["PLANT"],
                           "QUANTITY": qty, "PO_UNIT": org["PO_UNIT"],
                           "NET_PRICE": it.get("NETPR") or "0", "ACCTASSCAT": "K",
                           "MATL_GROUP": org["MATL_GROUP"]})
            poitemx.append({"PO_ITEM": n, "SHORT_TEXT": "X", "PLANT": "X", "QUANTITY": "X",
                            "PO_UNIT": "X", "NET_PRICE": "X", "ACCTASSCAT": "X", "MATL_GROUP": "X"})
            acct.append({"PO_ITEM": n, "SERIAL_NO": "01", "GL_ACCOUNT": org["GL_ACCOUNT"],
                         "COSTCENTER": org["COSTCENTER"], "QUANTITY": qty})
            acctx.append({"PO_ITEM": n, "SERIAL_NO": "01", "GL_ACCOUNT": "X",
                          "COSTCENTER": "X", "QUANTITY": "X"})
        if not poitem:
            return {"status": "skipped", "messages": ["PO has no items"]}

        doc_date = org.get("DOC_DATE") or datetime.date.today().strftime("%Y%m%d")
        # Pass currency explicitly (the source PO's WAERS) rather than relying on the
        # vendor's default — robust across vendors/landscapes.
        curr = (header.get("WAERS") or org.get("CURRENCY") or "USD").strip()
        hdr = {"COMP_CODE": org["COMP_CODE"], "DOC_TYPE": org["DOC_TYPE"], "VENDOR": tgt_vendor,
               "PURCH_ORG": ekorg, "PUR_GROUP": org["PUR_GROUP"], "DOC_DATE": doc_date,
               "CURRENCY": curr}
        # Source-number preservation: on modern S/4 the external PO number
        # is exposed via POHEADER-PO_NUMBER (NESTED), not the classic top-
        # level PURCHASEORDER param (which BAPI_PO_CREATE1's signature no
        # longer has on 1809+; earlier code hit RFC_INVALID_PARAMETER on
        # 'PURCHASEORDER' against 816). Setting POHEADER-PO_NUMBER +
        # POHEADERX-PO_NUMBER = 'X' is honored when T161.NUMKE = 'A1' on
        # the target BSART. Silent-fallback if internal range.
        import os as _os
        _preserve = _os.environ.get("M4H_PRESERVE_SRC_NUMBERS", "0").strip() == "1"
        if _preserve and src_po:
            hdr["PO_NUMBER"] = src_po.zfill(10)
        _hdrx = {k: "X" for k in hdr}
        _bapi_kwargs = {"POHEADER": hdr, "POHEADERX": _hdrx,
                          "POITEM": poitem, "POITEMX": poitemx,
                          "POACCOUNT": acct, "POACCOUNTX": acctx}
        res = self.c.call("BAPI_PO_CREATE1", **_bapi_kwargs)
        ret = self._ret(res)
        po = (res.get("EXPPURCHASEORDER") or "").strip()
        vendor_ref = {"source": src_vendor, "target": tgt_vendor, "disposition": vdisp}
        if [m for m in ret if m.get("TYPE") in ("E", "A")] or not po:
            self._rollback()
            return {"status": "failed", "vendor": vendor_ref,
                    "messages": [f"{m.get('TYPE')} {m.get('MESSAGE')}" for m in ret][:4]}
        if commit:
            self._commit()
        return {"status": "created", "po": po, "vendor": vendor_ref,
                "verify_key": {"table": "EKKO", "key": {"EBELN": po}},
                "key_mapping": {"source": src_po, "target": po, "disposition": "created"},
                "messages": [m.get("MESSAGE") for m in ret if m.get("TYPE") in ("S", "W")][:2]}

    # ── Purchase requisition (BAPI_REQUISITION_CREATE) — open MM doc ───────────
    def create_purchase_requisition(self, row: dict, org: dict, commit: bool = True) -> dict:
        """Create a purchase requisition (ME51N) via BAPI_REQUISITION_CREATE. Account-assigned
        item (ACCTASSCAT='K', GL + cost center) with short text -- no material-master dependency,
        mirroring the PO loader and reusing the discovered po_org. Internal numbering -> the BAPI
        assigns the PR number; source BANFN -> target recorded (idempotency via the ledger). A
        valuation price (C_AMT_BAPI) is mandatory for account-assigned items."""
        src_pr = (row.get("BANFN") or "").strip()
        qty = str(int(parse_sap_number(row.get("MENGE"), 1)) or 1)
        price = parse_sap_number(row.get("PREIS"), 0)
        c_amt = ("%.2f" % price) if price else "100.00"
        txt = ((row.get("TXZ01") or ("Migrated PR " + (src_pr or "item"))).strip())[:40]
        deliv = (datetime.date.today() + datetime.timedelta(days=30)).strftime("%Y%m%d")
        item = [{"PREQ_ITEM": "00010", "DOC_TYPE": org.get("DOC_TYPE", "NB"),
                 "PUR_GROUP": org["PUR_GROUP"], "SHORT_TEXT": txt, "PLANT": org["PLANT"],
                 "QUANTITY": qty, "UNIT": org["PO_UNIT"], "DELIV_DATE": deliv,
                 "MAT_GRP": org["MATL_GROUP"], "ACCTASSCAT": "K",
                 "C_AMT_BAPI": c_amt, "PRICE_UNIT": "1"}]
        acc = [{"PREQ_ITEM": "00010", "SERIAL_NO": "01",
                "G_L_ACCT": org["GL_ACCOUNT"], "COST_CTR": org["COSTCENTER"]}]
        res = self.c.call("BAPI_REQUISITION_CREATE",
                          REQUISITION_ITEMS=item, REQUISITION_ACCOUNT_ASSIGNMENT=acc)
        ret = self._ret(res)
        num = (res.get("NUMBER") or "").strip()
        if [m for m in ret if m.get("TYPE") in ("E", "A")] or not num:
            self._rollback()
            return {"status": "failed",
                    "messages": [f"{m.get('TYPE')} {m.get('MESSAGE')}" for m in ret][:4]}
        if commit:
            self._commit()
        return {"status": "created", "pr": num,
                "verify_key": {"table": "EBAN", "key": {"BANFN": num}},
                "key_mapping": {"source": src_pr or num, "target": num, "disposition": "created"},
                "messages": [m.get("MESSAGE") for m in ret if m.get("TYPE") in ("S", "I", "W")][:1]}

    # ── Purchase contract / outline agreement (BAPI_CONTRACT_CREATE) ───────────
    def _comp_currency(self, bukrs: str) -> str:
        """Local currency of a target company code (T001.WAERS), cached. Used to normalize obsolete
        source currencies (e.g. IDES 'DEM') that have no rate in the target and would hard-fail."""
        cache = getattr(self, "_comp_curr_cache", None)
        if cache is None:
            cache = self._comp_curr_cache = {}
        if bukrs in cache:
            return cache[bukrs]
        curr = ""
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="T001", DELIMITER="|",
                            FIELDS=[{"FIELDNAME": "WAERS"}],
                            OPTIONS=[{"TEXT": f"BUKRS = '{bukrs}'"}], ROWCOUNT=1)
            curr = r["DATA"][0]["WA"].strip() if r.get("DATA") else ""
        except Exception:
            pass
        cache[bukrs] = curr
        return curr

    def _contract_payload(self, org, dtype, vendor, src_doc):
        """Build (HEADER, HEADERX, ITEM, ITEMX) for a contract create. Currency normalized to the
        target company code's local currency (obsolete source currencies like IDES 'DEM' hard-fail);
        account-assignment 'U' so no material dependency; nominal qty/price placeholders."""
        today = datetime.date.today()
        end = today.replace(year=today.year + 1)
        curr = (self._comp_currency(org["COMP_CODE"]) or org.get("CURRENCY") or "EUR").strip()
        hdr = {"COMP_CODE": org["COMP_CODE"], "DOC_TYPE": dtype, "VENDOR": vendor.zfill(10),
               "PURCH_ORG": org["PURCH_ORG"], "PUR_GROUP": org["PUR_GROUP"], "CURRENCY": curr,
               "VPER_START": today.strftime("%Y%m%d"), "VPER_END": end.strftime("%Y%m%d"),
               "DOC_DATE": today.strftime("%Y%m%d")}
        item = [{"ITEM_NO": "00010", "SHORT_TEXT": (f"Migrated contract {src_doc}")[:40],
                 "PLANT": org["PLANT"], "MATL_GROUP": org["MATL_GROUP"], "TARGET_QTY": "100",
                 "PO_UNIT": org["PO_UNIT"], "NET_PRICE": "10", "PRICE_UNIT": "1", "ACCTASSCAT": "U"}]
        itemx = [{"ITEM_NO": "00010", "SHORT_TEXT": "X", "PLANT": "X", "MATL_GROUP": "X",
                  "TARGET_QTY": "X", "PO_UNIT": "X", "NET_PRICE": "X", "PRICE_UNIT": "X", "ACCTASSCAT": "X"}]
        return hdr, {k: "X" for k in hdr}, item, itemx

    def _contract_vendor_ok(self, org, dtype, vendor, src_doc) -> bool:
        """TESTRUN-validate that a vendor is contract-capable (complete purchasing data, not blocked).
        _ready_suppliers is broader than contracts require -- some vendors fail on 'faulty items'."""
        hdr, hdrx, item, itemx = self._contract_payload(org, dtype, vendor, src_doc)
        try:
            res = self.c.call("BAPI_CONTRACT_CREATE", HEADER=hdr, HEADERX=hdrx,
                              ITEM=item, ITEMX=itemx, TESTRUN="X")
            ok = not [m for m in self._ret(res) if m.get("TYPE") in ("E", "A")]
        except Exception:
            ok = False
        finally:
            self._rollback()
        return ok

    def create_purchase_contract(self, header: dict, org: dict, key_map=None, commit: bool = True) -> dict:
        """Create a purchasing contract / outline agreement (ME31K) via BAPI_CONTRACT_CREATE. Vendor
        resolution mirrors the PO loader, but the chosen vendor is TESTRUN-validated as contract-capable
        and, if not, a capable one is found from the ready pool and cached per purchasing org (the proven
        TESTRUN-validate-and-fallback pattern). Item uses account-assignment 'U' (no material dependency).
        Doc type from source BSART (MK quantity / WK value), default MK. Source EBELN -> target recorded."""
        src_doc = (header.get("EBELN") or "").strip()
        src_vendor = (header.get("LIFNR") or "").strip()
        ekorg = org["PURCH_ORG"]
        ready = sorted(set(self._ready_suppliers(ekorg)))
        if not ready:
            return {"status": "no_target_supplier", "messages": [f"no purchasing-ready supplier for org {ekorg}"]}
        dtype = (header.get("BSART") or "").strip()
        if dtype not in ("MK", "WK"):
            dtype = "MK"
        # Choose a contract-capable vendor: prefer the migrated/registry one if it validates, else a
        # cached known-good one for this org, else scan the ready pool (TESTRUN) and cache the winner.
        preferred = key_map.resolve("Vendor", src_vendor) if key_map else None
        cache = getattr(self, "_contract_vendor_cache", None)
        if cache is None:
            cache = self._contract_vendor_cache = {}
        tgt_vendor, vdisp = None, "harmonized"
        if preferred and preferred in set(ready) and self._contract_vendor_ok(org, dtype, preferred, src_doc):
            tgt_vendor, vdisp = preferred, "registry"
        elif ekorg in cache:
            tgt_vendor = cache[ekorg]
        else:
            for v in ready[:15]:
                if self._contract_vendor_ok(org, dtype, v, src_doc):
                    tgt_vendor = cache[ekorg] = v
                    break
        if not tgt_vendor:
            return {"status": "failed", "messages": [f"no contract-capable supplier found in org {ekorg}"]}
        if vdisp == "harmonized" and key_map and src_vendor:
            key_map.add("Vendor", src_vendor, tgt_vendor, "harmonized")
        vendor_ref = {"source": src_vendor, "target": tgt_vendor, "disposition": vdisp}
        hdr, hdrx, item, itemx = self._contract_payload(org, dtype, tgt_vendor, src_doc)
        try:
            res = self.c.call("BAPI_CONTRACT_CREATE", HEADER=hdr, HEADERX=hdrx, ITEM=item, ITEMX=itemx)
        except Exception as ex:
            self._rollback()
            return {"status": "failed", "vendor": vendor_ref,
                    "messages": [f"contract create exception: {str(ex).splitlines()[0]}"]}
        ret = self._ret(res)
        doc = (res.get("PURCHASINGDOCUMENT") or "").strip()
        if [m for m in ret if m.get("TYPE") in ("E", "A")] or not doc:
            self._rollback()
            return {"status": "failed", "vendor": vendor_ref,
                    "messages": [f"{m.get('TYPE')} {m.get('MESSAGE')}" for m in ret][:4]}
        if commit:
            self._commit()
        return {"status": "created", "contract": doc, "vendor": vendor_ref,
                "verify_key": {"table": "EKKO", "key": {"EBELN": doc}},
                "key_mapping": {"source": src_doc or doc, "target": doc, "disposition": "created"},
                "messages": [m.get("MESSAGE") for m in ret if m.get("TYPE") in ("S", "W")][:1]}

    # ── Inventory balance (BAPI_GOODSMVT_CREATE, mvt 561 initial stock) ────────
    def _stock_target(self):
        """Discover a target (material, plant, storage location) that exists in stock master (MARD),
        cached. Source materials rarely carry the target's plant/sloc views, so initial stock is
        posted against a discovered target-ready material+plant+sloc (harmonized, recorded)."""
        cache = getattr(self, "_stock_tgt_cache", None)
        if cache is not None:
            return cache
        mat = plant = sloc = ""
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="MARD", DELIMITER="|",
                            FIELDS=[{"FIELDNAME": "MATNR"}, {"FIELDNAME": "WERKS"},
                                    {"FIELDNAME": "LGORT"}], ROWCOUNT=1)
            if r.get("DATA"):
                mat, plant, sloc = (c.strip() for c in (r["DATA"][0]["WA"].split("|") + ["", "", ""])[:3])
        except Exception:
            pass
        self._stock_tgt_cache = (mat, plant, sloc)
        return mat, plant, sloc

    def _mm_posting_date(self) -> str:
        """An MM posting date in an OPEN period. The appliance's MM current period often lags real
        time; cached. Defaults to today and is corrected (parsed from the BAPI's 'periods YYYY/MM'
        message) on the first failure."""
        return getattr(self, "_mm_pdate", None) or datetime.date.today().strftime("%Y%m%d")

    def create_inventory_balance(self, row: dict, commit: bool = True) -> dict:
        """Post an initial stock balance (movement type 561) via BAPI_GOODSMVT_CREATE. Material is
        harmonized to a discovered target-ready (material, plant, sloc); quantity from source MARD.LABST.
        Self-heals the posting date if the target's MM period is closed (parses the open period from the
        BAPI message and retries, cached). verify_key on the resulting material document (MKPF)."""
        import re
        src_mat = (row.get("MATNR") or "").strip()
        qty = parse_sap_number(row.get("LABST"), 0)
        if qty <= 0:
            return {"status": "skipped", "messages": ["zero/again non-positive stock quantity"]}
        tgt_mat, plant, sloc = self._stock_target()
        if not tgt_mat or not plant or not sloc:
            return {"status": "skipped", "messages": ["no target material/plant/storage-location discovered"]}
        uom = (row.get("MEINS") or "EA").strip() or "EA"

        def _post(pdate):
            hdr = {"PSTNG_DATE": pdate, "DOC_DATE": pdate, "HEADER_TXT": f"M4H init stock {src_mat}"[:25]}
            item = [{"MATERIAL": tgt_mat, "PLANT": plant, "STGE_LOC": sloc,
                     "MOVE_TYPE": "561", "ENTRY_QNT": ("%.3f" % qty), "ENTRY_UOM": uom}]
            return self.c.call("BAPI_GOODSMVT_CREATE", GOODSMVT_HEADER=hdr,
                               GOODSMVT_CODE={"GM_CODE": "05"}, GOODSMVT_ITEM=item)

        res = _post(self._mm_posting_date())
        ret = self._ret(res)
        # MM period closed -> parse the open period (YYYY/MM) and retry once on the 15th of it.
        period_err = [m for m in ret if "period" in (m.get("MESSAGE") or "").lower()]
        if period_err and not (res.get("MATERIALDOCUMENT") or "").strip():
            self._rollback()
            mt = re.search(r"(\d{4})/(\d{2})", period_err[0].get("MESSAGE") or "")
            if mt:
                self._mm_pdate = f"{mt.group(1)}{mt.group(2)}15"
                res = _post(self._mm_pdate)
                ret = self._ret(res)
        doc = (res.get("MATERIALDOCUMENT") or "").strip()
        year = (res.get("MATDOCUMENTYEAR") or "").strip()
        if [m for m in ret if m.get("TYPE") in ("E", "A")] or not doc:
            self._rollback()
            return {"status": "failed", "messages": [f"{m.get('TYPE')} {m.get('MESSAGE')}" for m in ret][:3]}
        if commit:
            self._commit()
        msgs = []
        if tgt_mat != src_mat:
            msgs.append(f"material {src_mat} harmonized to target {tgt_mat}/{plant}/{sloc}")
        return {"status": "created", "matdoc": doc,
                "verify_key": {"table": "MKPF", "key": {"MBLNR": doc, "MJAHR": year}},
                "key_mapping": {"source": src_mat, "target": f"{tgt_mat}@{doc}", "disposition": "harmonized"},
                "messages": msgs}

    # ── Batch (BAPI_BATCH_CREATE) — batch master under a material+plant ────────
    def _batch_target_mat(self):
        """Discover a (material, plant) on the target that is batch-managed (MARC.XCHPF='X'), cached.
        Batches need a batch-managed material+plant; source materials rarely carry the target's plant
        view, so (like SO/material harmonization) batches are created under a target-ready material."""
        cache = getattr(self, "_batch_mat_cache", None)
        if cache is not None:
            return cache
        mat = plant = ""
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="MARC", DELIMITER="|",
                            FIELDS=[{"FIELDNAME": "MATNR"}, {"FIELDNAME": "WERKS"}],
                            OPTIONS=[{"TEXT": "XCHPF = 'X'"}], ROWCOUNT=1)
            if r.get("DATA"):
                mat, plant = (c.strip() for c in (r["DATA"][0]["WA"].split("|") + ["", ""])[:2])
        except Exception:
            pass
        self._batch_mat_cache = (mat, plant)
        return mat, plant

    def _batch_exists(self, mat: str, batch: str) -> bool:
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="MCH1", DELIMITER="|",
                            FIELDS=[{"FIELDNAME": "CHARG"}],
                            OPTIONS=[{"TEXT": f"MATNR = '{mat}' AND CHARG = '{batch}'"}], ROWCOUNT=1)
            return bool(r.get("DATA"))
        except Exception:
            return False

    def create_batch(self, row: dict, commit: bool = True) -> dict:
        """Create a batch master via BAPI_BATCH_CREATE. The batch is created under a target-ready
        (material, plant) -- source materials rarely carry the target's plant view, so we harmonize
        to a discovered batch-managed target material (recorded). The source batch number (CHARG) is
        preserved 1:1 under the target material when free, else a collision-safe suffix is appended."""
        src_mat = (row.get("MATNR") or "").strip()
        src_batch = (row.get("CHARG") or "").strip()
        if not src_batch:
            return {"status": "skipped", "messages": ["missing batch number"]}
        tgt_mat, plant = self._batch_target_mat()
        if not tgt_mat or not plant:
            return {"status": "skipped", "messages": ["no target batch-managed material/plant discovered"]}
        tgt_batch, n = src_batch, 0
        while self._batch_exists(tgt_mat, tgt_batch):
            n += 1
            tgt_batch = f"{src_batch}_{n}"[-10:]  # CHARG max 10 chars
            if n > 999:
                return {"status": "failed", "messages": [f"could not find a free batch number for {src_mat}/{src_batch}"]}
        res = self.c.call("BAPI_BATCH_CREATE", MATERIAL=tgt_mat, PLANT=plant, BATCH=tgt_batch)
        ret = self._ret(res)
        target = (res.get("BATCH") or tgt_batch).strip()
        if [m for m in ret if m.get("TYPE") in ("E", "A")]:
            self._rollback()
            return {"status": "failed", "messages": [f"{m.get('TYPE')} {m.get('MESSAGE')}" for m in ret][:3]}
        if commit:
            self._commit()
        msgs = []
        if tgt_mat != src_mat:
            msgs.append(f"material {src_mat} harmonized to target batch-managed {tgt_mat}/plant {plant}")
        if target != src_batch:
            msgs.append(f"batch {src_batch} collided -> {target}")
        return {"status": "created", "batch": target,
                "verify_key": {"table": "MCH1", "key": {"MATNR": tgt_mat, "CHARG": target}},
                "key_mapping": {"source": f"{src_mat}/{src_batch}", "target": f"{tgt_mat}/{target}",
                                "disposition": "harmonized" if tgt_mat != src_mat else ("created" if target == src_batch else "remapped")},
                "messages": msgs}

    # ── Sales order (BAPI_SALESORDER_CREATEFROMDAT2) — open SD doc ─────────────
    def _so_config(self):
        """Discover a coherent target sales setup: a sales area (VKORG/VTWEG/SPART) that has BOTH a
        sales-ready sold-to (KNVV) and a saleable material (MVKE), plus the dominant order type
        (VBAK.AUART). Sales orders need all three to align -- source customers/materials rarely carry
        target sales views, so (like PO vendor harmonization) we harmonize to ready target masters."""
        cache = getattr(self, "_so_cfg_cache", None)
        if cache is not None:
            return cache
        from collections import Counter
        cfg = None
        try:
            kn = self.c.call("RFC_READ_TABLE", QUERY_TABLE="KNVV", DELIMITER="|",
                             FIELDS=[{"FIELDNAME": "KUNNR"}, {"FIELDNAME": "VKORG"},
                                     {"FIELDNAME": "VTWEG"}, {"FIELDNAME": "SPART"}], ROWCOUNT=2000)
            mv = self.c.call("RFC_READ_TABLE", QUERY_TABLE="MVKE", DELIMITER="|",
                             FIELDS=[{"FIELDNAME": "MATNR"}, {"FIELDNAME": "VKORG"},
                                     {"FIELDNAME": "VTWEG"}], ROWCOUNT=3000)
            custs, mats = {}, {}
            for x in kn.get("DATA", []):
                ku, vk, vt, sp = (c.strip() for c in (x["WA"].split("|") + ["", "", "", ""])[:4])
                custs.setdefault((vk, vt, sp), []).append(ku)
            for x in mv.get("DATA", []):
                ma, vk, vt = (c.strip() for c in (x["WA"].split("|") + ["", "", ""])[:3])
                mats.setdefault((vk, vt), []).append(ma)
            otypes = Counter()
            try:
                vb = self.c.call("RFC_READ_TABLE", QUERY_TABLE="VBAK", DELIMITER="|",
                                 FIELDS=[{"FIELDNAME": "AUART"}], ROWCOUNT=500)
                otypes = Counter(x["WA"].strip() for x in vb.get("DATA", []) if x["WA"].strip())
            except Exception:
                pass
            otype = otypes.most_common(1)[0][0] if otypes else "TA"
            for (vk, vt, sp), cl in custs.items():
                if (vk, vt) in mats and cl and mats[(vk, vt)]:
                    cfg = {"sorg": vk, "chan": vt, "div": sp, "otype": otype,
                           "customers": set(cl), "sample_customer": cl[0],
                           "sample_material": mats[(vk, vt)][0]}
                    break
        except Exception as e:
            # A discovery EXCEPTION (typically a dead RFC connection late in a
            # long run) must NOT be cached as "no sales area" — that verdict
            # poisoned all 10,000 OpenSO rows in AUTO/AUTO2 within 0.1s. Leave
            # the cache unset so the next record retries, and surface why.
            self._so_cfg_reason = f"discovery failed: {type(e).__name__}: {str(e)[:120]}"
            return None
        if cfg is None:
            self._so_cfg_reason = ("no (VKORG,VTWEG) present in BOTH KNVV and "
                                   "MVKE on target — extend a customer + "
                                   "material into the sales area (prep step)")
        self._so_cfg_cache = cfg
        return cfg

    def create_sales_order(self, header: dict, key_map=None, commit: bool = True) -> dict:
        """Create a sales order (VA01) via BAPI_SALESORDER_CREATEFROMDAT2. Sold-to is resolved from
        the migration registry; if the source customer didn't migrate to a sales-ready target customer
        in the discovered sales area, it is harmonized to a ready one (recorded). The item uses a
        saleable target material (harmonized) -- source materials rarely carry the target's sales view.
        Internal numbering -> the BAPI assigns the document; source VBELN -> target recorded."""
        cfg = self._so_config()
        if not cfg:
            reason = getattr(self, "_so_cfg_reason", "") or "unknown"
            return {"status": "skipped",
                    "messages": ["no coherent target sales area (customer+material) "
                                 f"discovered [{reason}]"]}
        src_so = (header.get("VBELN") or "").strip()
        src_cust = (header.get("KUNNR") or "").strip()
        tgt_cust = key_map.resolve("Customer", src_cust) if key_map else None
        cdisp = "registry"
        if not (tgt_cust and tgt_cust in cfg["customers"]):
            tgt_cust = cfg["sample_customer"]
            cdisp = "harmonized"
            if key_map and src_cust:
                key_map.add("Customer", src_cust, tgt_cust, "harmonized")
        hdr = {"DOC_TYPE": cfg["otype"], "SALES_ORG": cfg["sorg"],
               "DISTR_CHAN": cfg["chan"], "DIVISION": cfg["div"]}
        parts = [{"PARTN_ROLE": "AG", "PARTN_NUMB": tgt_cust.zfill(10)}]
        items = [{"ITM_NUMBER": "000010", "MATERIAL": cfg["sample_material"],
                  "TARGET_QTY": "1", "TARGET_QU": "EA"}]
        sched = [{"ITM_NUMBER": "000010", "REQ_QTY": "1"}]
        # Source-number preservation (M4H_PRESERVE_SRC_NUMBERS=1): pass
        # SALESDOCUMENTIN so the target SO gets the ECC VBELN when the
        # TVAK.NUMKE external-range flag is set (Basis Kit does this via
        # Z_M4H_TABLE_UPDATE). Silent-fallback: if TVAK is still internal
        # range, S/4 ignores the input and assigns its own number.
        import os as _os
        _preserve = _os.environ.get("M4H_PRESERVE_SRC_NUMBERS", "0").strip() == "1"
        _bapi_kwargs = {"ORDER_HEADER_IN": hdr, "ORDER_PARTNERS": parts,
                          "ORDER_ITEMS_IN": items, "ORDER_SCHEDULES_IN": sched}
        if _preserve and src_so:
            _bapi_kwargs["SALESDOCUMENTIN"] = src_so.zfill(10)
        res = self.c.call("BAPI_SALESORDER_CREATEFROMDAT2", **_bapi_kwargs)
        ret = self._ret(res)
        doc = (res.get("SALESDOCUMENT") or "").strip()
        cust_ref = {"source": src_cust, "target": tgt_cust, "disposition": cdisp}
        # After the initial call, if source-number preservation is on AND
        # the first attempt renumbered the SO, retry with SALESDOCUMENTIN=src_so.
        # This is intentionally the second attempt so that if the target's
        # TVAK.NUMKE flag ISN'T flipped we fail cleanly on the first call
        # rather than silently rejecting the external number.
        # (Moved to a pre-call injection in the follow-up patch below.)
        if [m for m in ret if m.get("TYPE") in ("E", "A")] or not doc:
            self._rollback()
            return {"status": "failed", "customer": cust_ref,
                    "messages": [f"{m.get('TYPE')} {m.get('MESSAGE')}" for m in ret][:4]}
        if commit:
            self._commit()
        return {"status": "created", "so": doc, "customer": cust_ref,
                "verify_key": {"table": "VBAK", "key": {"VBELN": doc}},
                "key_mapping": {"source": src_so or doc, "target": doc, "disposition": "created"},
                "messages": [m.get("MESSAGE") for m in ret if m.get("TYPE") in ("S", "W")][:1]}

    # ── Open AR / AP financial items (BAPI_ACC_DOCUMENT_POST) ───────────────
    def _recon_partners(self, table: str, key_field: str, bukrs: str) -> list:
        """Cached partners with company-code data (recon account) — KNB1 customers /
        LFB1 suppliers. Only these can carry an open item in that company code."""
        cache = getattr(self, "_recon_cache", {})
        ck = (table, bukrs)
        if ck not in cache:
            try:
                r = self.c.call("RFC_READ_TABLE", QUERY_TABLE=table, DELIMITER="|",
                                OPTIONS=[{"TEXT": f"BUKRS = '{bukrs}'"}],
                                FIELDS=[{"FIELDNAME": key_field}], ROWCOUNT=300)
                cache[ck] = [d["WA"].strip() for d in r.get("DATA", [])]
            except Exception:
                cache[ck] = []
            self._recon_cache = cache
        return cache[ck]

    def create_fi_open_item(self, item: dict, kind: str, org: dict,
                            key_map=None, commit: bool = True) -> dict:
        """Post one open AR/AP item as a balanced FI document via BAPI_ACC_DOCUMENT_POST
        — the most business-critical transactional data. Consumes the key registry to
        resolve the customer/vendor; if the migrated partner isn't recon-account-ready,
        harmonizes to an existing ready partner (and records it). The offset is a
        balance-sheet 'data takeover' clearing account (no P&L impact), with a profit
        center so S/4 document splitting is satisfied. Org units remapped to target."""
        is_ar = (kind == "AR")
        bukrs = org["COMP_CODE"]
        src_partner = ((item.get("KUNNR") if is_ar else item.get("LIFNR")) or "").strip()
        src_doc = (item.get("BELNR") or "").strip()
        amount = parse_sap_number(item.get("DMBTR"))
        shkzg = (item.get("SHKZG") or ("S" if is_ar else "H")).strip()
        curr = (item.get("WAERS") or "USD").strip()
        reg_obj, table, kf = ("Customer", "KNB1", "KUNNR") if is_ar else ("Vendor", "LFB1", "LIFNR")
        pool = self._recon_partners(table, kf, bukrs)
        tgt = key_map.resolve(reg_obj, src_partner) if key_map else None
        pdisp = "registry"
        if not (tgt and tgt in set(pool)):
            if not pool:
                return {"status": "no_target_partner",
                        "messages": [f"no recon-ready {reg_obj} in company {bukrs}"]}
            digits = "".join(ch for ch in src_partner if ch.isdigit())
            tgt = pool[(int(digits) if digits else 0) % len(pool)]
            pdisp = "harmonized"
            if key_map:
                key_map.add(reg_obj, src_partner, tgt, "harmonized")

        if amount <= 0:
            return {"status": "skipped", "messages": ["zero/negative open amount"]}
        # partner debit when SHKZG='S' (receivable), credit when 'H' (payable); GL offsets
        pamt = amount if shkzg == "S" else -amount
        doc_date = org.get("DOC_DATE") or datetime.date.today().strftime("%Y%m%d")
        hdr = {"USERNAME": org.get("USERNAME", "MIGRATE_ADMI"), "COMP_CODE": bukrs,
               "DOC_DATE": doc_date, "PSTNG_DATE": doc_date,
               "DOC_TYPE": "DR" if is_ar else "KR", "BUS_ACT": "RFBU",
               "REF_DOC_NO": ("M4H-" + src_doc)[:16]}
        gl = [{"ITEMNO_ACC": "0000000002", "GL_ACCOUNT": org["CLEARING_GL"],
               "ITEM_TEXT": f"M4H open {kind} {src_doc}"[:50], "PROFIT_CTR": org["PROFIT_CTR"]}]
        cur = [{"ITEMNO_ACC": "0000000001", "CURRENCY": curr, "AMT_DOCCUR": "%.2f" % pamt},
               {"ITEMNO_ACC": "0000000002", "CURRENCY": curr, "AMT_DOCCUR": "%.2f" % (-pamt)}]
        kwargs = {"DOCUMENTHEADER": hdr, "ACCOUNTGL": gl, "CURRENCYAMOUNT": cur}
        if is_ar:
            kwargs["ACCOUNTRECEIVABLE"] = [{"ITEMNO_ACC": "0000000001", "CUSTOMER": tgt}]
        else:
            kwargs["ACCOUNTPAYABLE"] = [{"ITEMNO_ACC": "0000000001", "VENDOR_NO": tgt}]
        res = self.c.call("BAPI_ACC_DOCUMENT_POST", **kwargs)
        ret = self._ret(res)
        objkey = (res.get("OBJ_KEY") or "").strip()
        partner_ref = {"source": src_partner, "target": tgt, "disposition": pdisp}
        if [m for m in ret if m.get("TYPE") in ("E", "A")] or not objkey or objkey == "$":
            self._rollback()
            return {"status": "failed", "partner": partner_ref,
                    "messages": [f"{m.get('TYPE')} {m.get('MESSAGE')}" for m in ret][:4]}
        if commit:
            self._commit()
        belnr, bk, gj = objkey[:10], objkey[10:14], objkey[14:18]
        # Verify against the OPEN-ITEM table (BSID/BSIK): proves the item exists AND
        # carries the right amount (WRBTR, doc currency) — the financial tie-out that
        # matters for receivables/payables. Stronger than a BKPF header existence check.
        return {"status": "created", "doc": belnr, "partner": partner_ref,
                "verify_key": {"table": "BSID" if is_ar else "BSIK",
                               "key": {"BUKRS": bk or bukrs, "BELNR": belnr, "GJAHR": gj},
                               "values": {"WRBTR": round(amount, 2)}},
                "key_mapping": {"source": src_doc, "target": belnr, "disposition": "created"},
                "messages": [m.get("MESSAGE") for m in ret if m.get("TYPE") in ("S", "W")][:2]}

    # ── Cost center (CO master, BAPI_COSTCENTER_CREATEMULTIPLE) ─────────────
    def _cost_center_exists(self, kostl: str, kokrs: str) -> bool:
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="CSKS", DELIMITER="|",
                            OPTIONS=[{"TEXT": "KOKRS = '%s' AND KOSTL = '%s'" % (kokrs, kostl)}],
                            FIELDS=[{"FIELDNAME": "KOSTL"}], ROWCOUNT=1)
            return bool(r.get("DATA"))
        except Exception:
            return False

    def create_cost_center(self, row: dict, org: dict, commit: bool = True) -> dict:
        """Create a cost center (CO master). Idempotent: if it already exists in the target
        controlling area, reuse it. org supplies the discovered CO area / hierarchy node /
        category / company / currency / profit center."""
        kostl = (row.get("KOSTL") or "").strip()
        if not kostl:
            return {"status": "skipped", "messages": ["no cost center number"]}
        kokrs = org["CO_AREA"]
        verify = {"table": "CSKS", "key": {"KOKRS": kokrs, "KOSTL": kostl}}
        if self._cost_center_exists(kostl, kokrs):
            return {"status": "matched_existing", "cost_center": kostl, "verify_key": verify,
                    "key_mapping": {"source": kostl, "target": kostl, "disposition": "matched_existing"},
                    "messages": [f"cost center {kostl} already exists in {kokrs}"]}
        name = ((row.get("KTEXT") or ("CC " + kostl)).strip() or kostl)[:20]
        cc = {"COSTCENTER": kostl, "VALID_FROM": org.get("VALID_FROM", "20240101"),
              "VALID_TO": "99991231", "PERSON_IN_CHARGE": "M4H",
              "COSTCENTER_TYPE": org["CC_CATEGORY"], "COSTCTR_HIER_GRP": org["CC_HIER"],
              "COMP_CODE": org["COMP_CODE"], "CURRENCY": org["CURRENCY"],
              "PROFIT_CTR": org.get("PROFIT_CTR", ""), "NAME": name, "DESCRIPT": name}
        res = self.c.call("BAPI_COSTCENTER_CREATEMULTIPLE", CONTROLLINGAREA=kokrs, COSTCENTERLIST=[cc])
        ret = self._ret(res)
        if [m for m in ret if m.get("TYPE") in ("E", "A")]:
            self._rollback()
            return {"status": "failed", "messages": [f"{m.get('TYPE')} {m.get('MESSAGE')}" for m in ret][:3]}
        if commit:
            self._commit()
        return {"status": "created", "cost_center": kostl, "verify_key": verify,
                "key_mapping": {"source": kostl, "target": kostl, "disposition": "created"},
                "messages": [m.get("MESSAGE") for m in ret if m.get("TYPE") in ("S", "W")][:2]}

    # ── Profit center (CO master, BAPI_PROFITCENTER_CREATE) ────────────────
    def _profit_center_exists(self, prctr: str, kokrs: str) -> bool:
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="CEPC", DELIMITER="|",
                            OPTIONS=[{"TEXT": "KOKRS = '%s' AND PRCTR = '%s'" % (kokrs, prctr)}],
                            FIELDS=[{"FIELDNAME": "PRCTR"}], ROWCOUNT=1)
            return bool(r.get("DATA"))
        except Exception:
            return False

    def _discover_pc_hier(self, kokrs: str) -> str:
        """Profit-center standard-hierarchy node for a controlling area (most-common CEPC.KHINR),
        looked up from the target and cached. Self-heals when the discovered config predates
        PC_HIER (a stale cache) so PRCTR_HIER_GRP is never empty — empty => BAPI 'fill required fields'."""
        cache = getattr(self, "_pchier_cache", None)
        if cache is None:
            cache = self._pchier_cache = {}
        if kokrs in cache:
            return cache[kokrs]
        val = ""
        try:
            from collections import Counter
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="CEPC", DELIMITER="|",
                            FIELDS=[{"FIELDNAME": "KHINR"}],
                            OPTIONS=[{"TEXT": "KOKRS = '%s'" % kokrs}], ROWCOUNT=300)
            kh = Counter(x["WA"].strip() for x in r.get("DATA", []) if x["WA"].strip())
            val = kh.most_common(1)[0][0] if kh else ""
        except Exception:
            val = ""
        cache[kokrs] = val
        return val

    def create_profit_center(self, row: dict, org: dict, commit: bool = True) -> dict:
        """Create a profit center (CO master). Idempotent: reuse if it already exists in the
        target controlling area. org supplies CO area / PC standard-hierarchy node."""
        prctr = (row.get("PRCTR") or "").strip()
        if not prctr:
            return {"status": "skipped", "messages": ["no profit center number"]}
        kokrs = org["CO_AREA"]
        verify = {"table": "CEPC", "key": {"KOKRS": kokrs, "PRCTR": prctr}}
        if self._profit_center_exists(prctr, kokrs):
            return {"status": "matched_existing", "profit_center": prctr, "verify_key": verify,
                    "key_mapping": {"source": prctr, "target": prctr, "disposition": "matched_existing"},
                    "messages": [f"profit center {prctr} already exists in {kokrs}"]}
        name = ((row.get("KTEXT") or ("PC " + prctr)).strip() or prctr)[:20]
        # PRCTR_HIER_GRP is required; if the discovered config lacks PC_HIER (e.g. a stale cache),
        # self-heal by looking up the CO area's standard-hierarchy node from the target.
        hier = (org.get("PC_HIER") or "").strip() or self._discover_pc_hier(kokrs)
        res = self.c.call("BAPI_PROFITCENTER_CREATE",
                          PROFITCENTERID={"CO_AREA": kokrs, "PROFIT_CTR": prctr},
                          VALIDFROM=org.get("VALID_FROM", "20240101"), VALIDTO="99991231",
                          BASICDATA={"PRCTR_NAME": name, "LONG_TEXT": name, "IN_CHARGE": "M4H",
                                     "PRCTR_HIER_GRP": hier},
                          LANGUAGE={"LANGU": "E"})
        ret = self._ret(res)
        if [m for m in ret if m.get("TYPE") in ("E", "A")]:
            self._rollback()
            return {"status": "failed", "messages": [f"{m.get('TYPE')} {m.get('MESSAGE')}" for m in ret][:3]}
        if commit:
            self._commit()
        return {"status": "created", "profit_center": prctr, "verify_key": verify,
                "key_mapping": {"source": prctr, "target": prctr, "disposition": "created"},
                "messages": [m.get("MESSAGE") for m in ret if m.get("TYPE") in ("S", "W")][:2]}

    # ── Fixed asset master (BAPI_FIXEDASSET_CREATE1) ───────────────────────
    def _fixed_asset_exists(self, anln1: str, bukrs: str) -> bool:
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="ANLA", DELIMITER="|",
                            OPTIONS=[{"TEXT": "BUKRS = '%s' AND ANLN1 = '%s' AND ANLN2 = '0000'"
                                      % (bukrs, anln1)}],
                            FIELDS=[{"FIELDNAME": "ANLN1"}], ROWCOUNT=1)
            return bool(r.get("DATA"))
        except Exception:
            return False

    def _asset_class_valid(self, bukrs: str, anlkl: str, cap_date: str) -> bool:
        """Is this asset class usable in this company code's chart of depreciation?
        Validated once per (company,class) via a TESTRUN create and cached, so a mass
        load probes each distinct class only once, not once per asset."""
        cache = getattr(self, "_acls_cache", None)
        if cache is None:
            cache = self._acls_cache = {}
        k = (bukrs, anlkl)
        if k in cache:
            return cache[k]
        try:
            res = self.c.call("BAPI_FIXEDASSET_CREATE1", KEY={"COMPANYCODE": bukrs},
                              GENERALDATA={"ASSETCLASS": anlkl, "DESCRIPT": "validate"},
                              GENERALDATAX={"ASSETCLASS": "X", "DESCRIPT": "X"},
                              POSTINGINFORMATION={"CAP_DATE": cap_date},
                              POSTINGINFORMATIONX={"CAP_DATE": "X"}, TESTRUN="X")
            ok = not [m for m in self._ret(res) if m.get("TYPE") in ("E", "A")]
        except Exception:
            ok = False
        cache[k] = ok
        return ok

    def create_fixed_asset(self, row: dict, org: dict, commit: bool = True,
                           testrun: bool = False) -> dict:
        """Create a fixed-asset master via BAPI_FIXEDASSET_CREATE1 (probe-validated shape).

        Company code -> KEY.COMPANYCODE; asset class -> GENERALDATA.ASSETCLASS; an external
        asset number (when the class uses external numbering) -> KEY.ASSET. The X-structures
        flag which fields we supply. Depreciation areas/keys/useful-life DEFAULT from the
        asset-class customizing (table ANKB) — we only pass DEPRECIATIONAREAS as a fallback
        when org supplies ASSET_DEP_AREAS. Numbering: external preserves the source ANLN1;
        otherwise the BAPI assigns an internal number and we record source->target (cross-run
        idempotency then carried by the unified loader's ledger, like Material/BP).

        Source assets often live in a different company code/asset class than the target
        (e.g. ECC 1000/3000 -> S/4 1710): the handler maps row.BUKRS/row.ANLKL via the
        discovered asset config before calling, so here we trust row.ANLKL + org company code.

        org keys: ASSET_COMP_CODE (or COMP_CODE), ASSET_CLASS (fallback class),
        ASSET_EXTERNAL_NUM (bool), CAP_DATE (yyyymmdd), ASSET_DEP_AREAS (optional)."""
        anln1 = (row.get("ANLN1") or "").strip()
        bukrs = org.get("ASSET_COMP_CODE") or org.get("COMP_CODE")
        anlkl = (row.get("ANLKL") or org.get("ASSET_CLASS") or "").strip()
        if not anlkl or not bukrs:
            return {"status": "skipped", "messages": ["missing asset class or company code"]}
        external = bool(org.get("ASSET_EXTERNAL_NUM")) and bool(anln1)
        # idempotent only when we preserve the source number (external numbering)
        if external and self._fixed_asset_exists(anln1, bukrs):
            verify = {"table": "ANLA", "key": {"BUKRS": bukrs, "ANLN1": anln1, "ANLN2": "0000"}}
            return {"status": "matched_existing", "asset": anln1, "verify_key": verify,
                    "key_mapping": {"source": anln1, "target": anln1, "disposition": "matched_existing"},
                    "messages": [f"asset {anln1} already exists in {bukrs}"]}
        desc = ((row.get("TXT50") or ("Asset " + (anln1 or anlkl))).strip())[:50]
        cap_date = org.get("CAP_DATE") or org.get("VALID_FROM", "20240101")
        # Source class may not exist in the target chart of depreciation (e.g. ECC class
        # 00004001 -> S/4 chart 1710). Validate once; if unusable, fall back to the
        # discovered default class and record the remap transparently.
        src_class, class_remapped = anlkl, False
        fallback = (org.get("ASSET_CLASS") or "").strip()
        if not testrun and fallback and anlkl != fallback and not self._asset_class_valid(bukrs, anlkl, cap_date):
            anlkl, class_remapped = fallback, True
        key = {"COMPANYCODE": bukrs}
        if external:
            key["ASSET"] = anln1
        kwargs = dict(KEY=key,
                      GENERALDATA={"ASSETCLASS": anlkl, "DESCRIPT": desc},
                      GENERALDATAX={"ASSETCLASS": "X", "DESCRIPT": "X"},
                      POSTINGINFORMATION={"CAP_DATE": cap_date},
                      POSTINGINFORMATIONX={"CAP_DATE": "X"})
        if testrun:
            kwargs["TESTRUN"] = "X"
        deps = org.get("ASSET_DEP_AREAS")  # optional fallback: [{AREA,DEP_KEY,ULIFE_YRS}, ...]
        if deps:
            kwargs["DEPRECIATIONAREAS"] = [{"AREA": d["AREA"], **({"DEP_KEY": d["DEP_KEY"]} if d.get("DEP_KEY") else {}),
                                            **({"ULIFE_YRS": d["ULIFE_YRS"]} if d.get("ULIFE_YRS") else {})}
                                           for d in deps]
            kwargs["DEPRECIATIONAREASX"] = [{"AREA": d["AREA"], "DEP_KEY": "X" if d.get("DEP_KEY") else "",
                                             "ULIFE_YRS": "X" if d.get("ULIFE_YRS") else ""} for d in deps]
        res = self.c.call("BAPI_FIXEDASSET_CREATE1", **kwargs)
        ret = self._ret(res)
        if [m for m in ret if m.get("TYPE") in ("E", "A")]:
            self._rollback()
            return {"status": "failed", "messages": [f"{m.get('TYPE')} {m.get('MESSAGE')}" for m in ret][:3]}
        target = (res.get("ASSET") or anln1 or "").strip()
        if testrun:
            return {"status": "tested", "asset": target,
                    "messages": [m.get("MESSAGE") for m in ret if m.get("TYPE") in ("S", "W")][:2]}
        if commit:
            self._commit()
        verify = {"table": "ANLA", "key": {"BUKRS": bukrs, "ANLN1": target, "ANLN2": "0000"}}
        msgs = [m.get("MESSAGE") for m in ret if m.get("TYPE") in ("S", "W")][:2]
        if class_remapped:
            msgs.append(f"asset class {src_class} not valid in {bukrs}; loaded under {anlkl}")
        return {"status": "created", "asset": target, "asset_class": anlkl, "verify_key": verify,
                "key_mapping": {"source": anln1 or target, "target": target,
                                "disposition": "created" if target == anln1 else "remapped"},
                "messages": msgs}

    # ── Bank master (BAPI_BANK_CREATE) ─────────────────────────────────────
    def _bank_exists(self, ctry: str, key: str) -> bool:
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="BNKA", DELIMITER="|",
                            OPTIONS=[{"TEXT": "BANKS = '%s' AND BANKL = '%s'" % (ctry, key)}],
                            FIELDS=[{"FIELDNAME": "BANKL"}], ROWCOUNT=1)
            return bool(r.get("DATA"))
        except Exception:
            return False

    def create_bank(self, row: dict, commit: bool = True) -> dict:
        """Create a bank master (global, no org config). Idempotent on (BANKS, BANKL).
        Source ECC BNKA: BANKS=country, BANKL=bank key, BANKA=name, SWIFT, BRNCH, ORT01=city."""
        ctry = (row.get("BANKS") or "").strip()
        key = (row.get("BANKL") or "").strip()
        if not ctry or not key:
            return {"status": "skipped", "messages": ["missing bank country/key"]}
        verify = {"table": "BNKA", "key": {"BANKS": ctry, "BANKL": key}}
        if self._bank_exists(ctry, key):
            return {"status": "matched_existing", "bank": key, "verify_key": verify,
                    "key_mapping": {"source": key, "target": key, "disposition": "matched_existing"},
                    "messages": [f"bank {ctry}/{key} already exists"]}
        addr = {"BANK_NAME": ((row.get("BANKA") or ("Bank " + key)).strip())[:60]}
        if (row.get("SWIFT") or "").strip():
            addr["SWIFT_CODE"] = row["SWIFT"].strip()
        if (row.get("BRNCH") or "").strip():
            addr["BANK_BRANCH"] = row["BRNCH"].strip()[:40]
        if (row.get("ORT01") or "").strip():
            addr["CITY"] = row["ORT01"].strip()[:35]
        res = self.c.call("BAPI_BANK_CREATE", BANK_CTRY=ctry, BANK_KEY=key, BANK_ADDRESS=addr)
        ret = self._ret(res)
        if [m for m in ret if m.get("TYPE") in ("E", "A")]:
            self._rollback()
            return {"status": "failed", "messages": [f"{m.get('TYPE')} {m.get('MESSAGE')}" for m in ret][:3]}
        if commit:
            self._commit()
        return {"status": "created", "bank": key, "verify_key": verify,
                "key_mapping": {"source": key, "target": key, "disposition": "created"},
                "messages": [m.get("MESSAGE") for m in ret if m.get("TYPE") in ("S", "W")][:2]}

    # ── Internal order (CO master, BAPI_INTERNALORDER_CREATE) ──────────────
    def _discover_profit_ctr(self, kokrs: str) -> str:
        """Most-common real profit center in a controlling area (cached) — PROFIT_CTR is required
        on S/4 (profit-center accounting active)."""
        cache = getattr(self, "_prctr_cache", None)
        if cache is None:
            cache = self._prctr_cache = {}
        if kokrs in cache:
            return cache[kokrs]
        val = ""
        try:
            from collections import Counter
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="CEPC", DELIMITER="|",
                            FIELDS=[{"FIELDNAME": "PRCTR"}],
                            OPTIONS=[{"TEXT": "KOKRS = '%s'" % kokrs}], ROWCOUNT=300)
            pc = Counter(x["WA"].strip() for x in r.get("DATA", []) if x["WA"].strip())
            val = pc.most_common(1)[0][0] if pc else ""
        except Exception:
            val = ""
        cache[kokrs] = val
        return val

    def _order_type_valid(self, kokrs: str, otype: str, comp: str, curr: str, prctr: str) -> bool:
        cache = getattr(self, "_iotype_cache", None)
        if cache is None:
            cache = self._iotype_cache = {}
        k = (kokrs, otype)
        if k in cache:
            return cache[k]
        try:
            res = self.c.call("BAPI_INTERNALORDER_CREATE", TESTRUN="X",
                              I_MASTER_DATA={"ORDER_TYPE": otype, "CO_AREA": kokrs,
                                             "ORDER_NAME": "validate", "COMP_CODE": comp,
                                             "CURRENCY": curr, "PROFIT_CTR": prctr})
            ok = not [m for m in self._ret(res) if m.get("TYPE") in ("E", "A")]
        except Exception:
            ok = False
        cache[k] = ok
        return ok

    def create_internal_order(self, row: dict, org: dict, commit: bool = True) -> dict:
        """Create an internal order (CO master). Internal numbering -> BAPI assigns ORDERID; source
        AUFNR -> target order recorded (idempotency via the loader ledger). Source order types often
        differ from the target (ECC 0100 vs S/4 Y600/...): validate once via TESTRUN (cached) and fall
        back to the discovered default order type with a transparent remap. org = the discovered CO
        config (CO_AREA, COMP_CODE, CURRENCY, PROFIT_CTR, ORDER_TYPE)."""
        aufnr = (row.get("AUFNR") or "").strip()
        kokrs = org.get("CO_AREA")
        otype = (row.get("AUART") or org.get("ORDER_TYPE") or "").strip()
        if not kokrs or not otype:
            return {"status": "skipped", "messages": ["missing CO area / order type"]}
        comp = org.get("COMP_CODE", "")
        curr = org.get("CURRENCY", "")
        prctr = (org.get("PROFIT_CTR") or "").strip() or self._discover_profit_ctr(kokrs)
        fallback = (org.get("ORDER_TYPE") or "").strip()
        src_ot, ot_remapped = otype, False
        if fallback and otype != fallback and not self._order_type_valid(kokrs, otype, comp, curr, prctr):
            otype, ot_remapped = fallback, True
        name = ((row.get("KTEXT") or ("IO " + (aufnr or otype))).strip())[:40]
        res = self.c.call("BAPI_INTERNALORDER_CREATE",
                          I_MASTER_DATA={"ORDER_TYPE": otype, "CO_AREA": kokrs, "ORDER_NAME": name,
                                         "COMP_CODE": comp, "CURRENCY": curr, "PROFIT_CTR": prctr})
        ret = self._ret(res)
        if [m for m in ret if m.get("TYPE") in ("E", "A")]:
            self._rollback()
            return {"status": "failed", "messages": [f"{m.get('TYPE')} {m.get('MESSAGE')}" for m in ret][:3]}
        target = (res.get("ORDERID") or (res.get("E_MASTER_DATA") or {}).get("ORDER") or "").strip()
        if commit:
            self._commit()
        verify = {"table": "AUFK", "key": {"AUFNR": target}}
        msgs = [m.get("MESSAGE") for m in ret if m.get("TYPE") in ("S", "W")][:2]
        if ot_remapped:
            msgs.append(f"order type {src_ot} not valid in {kokrs}; used {otype}")
        return {"status": "created", "internal_order": target, "verify_key": verify,
                "key_mapping": {"source": aufnr or target, "target": target,
                                "disposition": "created" if target == aufnr else "remapped"},
                "messages": msgs}

    # ── Equipment master (BAPI_EQUI_CREATE) ────────────────────────────────
    def _equip_cats(self):
        """(valid_categories_set, default_category) from the target's in-use EQUI.EQTYP, cached."""
        cache = getattr(self, "_eqcat_cache", None)
        if cache is not None:
            return cache
        from collections import Counter
        cats = Counter()
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="EQUI", DELIMITER="|",
                            FIELDS=[{"FIELDNAME": "EQTYP"}], ROWCOUNT=500)
            cats = Counter(x["WA"].strip() for x in r.get("DATA", []) if x["WA"].strip())
        except Exception:
            pass
        self._eqcat_cache = (set(cats), cats.most_common(1)[0][0] if cats else "M")
        return self._eqcat_cache

    def create_equipment(self, row: dict, commit: bool = True) -> dict:
        """Create an equipment master (PM). Internal numbering -> BAPI assigns EQUIPMENT; source
        EQUNR -> target recorded (idempotency via the ledger). Equipment category (EQTYP) is
        validated against the target's in-use set; falls back to the default with a transparent remap.
        Self-contained (no org config). Source ECC EQUI: EQUNR, EQTYP; description EQKT-EQKTX."""
        equnr = (row.get("EQUNR") or "").strip()
        cat = (row.get("EQTYP") or "").strip()
        valid, default = self._equip_cats()
        src_cat, remapped = cat, False
        if cat not in valid:
            cat, remapped = (default, True)
        name = ((row.get("EQKTX") or row.get("SHTXT") or ("Equipment " + (equnr or cat))).strip())[:40]
        res = self.c.call("BAPI_EQUI_CREATE",
                          DATA_GENERAL={"DESCRIPT": name},
                          DATA_SPECIFIC={"EQUICATGRY": cat},
                          VALID_DATE=datetime.date.today().strftime("%Y%m%d"))
        ret = self._ret(res)
        if [m for m in ret if m.get("TYPE") in ("E", "A")]:
            self._rollback()
            return {"status": "failed", "messages": [f"{m.get('TYPE')} {m.get('MESSAGE')}" for m in ret][:3]}
        target = (res.get("EQUIPMENT") or "").strip()
        if commit:
            self._commit()
        verify = {"table": "EQUI", "key": {"EQUNR": target}}
        msgs = [m.get("MESSAGE") for m in ret if m.get("TYPE") in ("S", "W")][:2]
        if remapped:
            msgs.append(f"equipment category {src_cat} not valid; used {cat}")
        return {"status": "created", "equipment": target, "verify_key": verify,
                "key_mapping": {"source": equnr or target, "target": target,
                                "disposition": "created" if target == equnr else "remapped"},
                "messages": msgs}

    # ── Functional location (BAPI_FUNCLOC_CREATE) ─────────────────────────────
    def _floc_config(self):
        """Discover the target's in-use functional-location structure: the most-common
        structure indicator (IFLOT.TPLKZ), category (FLTYP), the label delimiter and the
        per-level segment widths (the editing mask), plus the set of existing labels.
        Funcloc labels are *structure-bound*: they must conform to the target structure
        indicator's mask. ECC source labels usually do NOT conform (different masks), so we
        reformat source labels to the target mask (collision-safe), like a MATNR remap."""
        cache = getattr(self, "_floc_cfg_cache", None)
        if cache is not None:
            return cache
        from collections import Counter
        strinds, cats, widths, existing = Counter(), Counter(), {}, set()
        delim = "-"
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="IFLOT", DELIMITER="|",
                            FIELDS=[{"FIELDNAME": "TPLNR"}, {"FIELDNAME": "TPLKZ"},
                                    {"FIELDNAME": "FLTYP"}], ROWCOUNT=1000)
            for x in r.get("DATA", []):
                tplnr, tplkz, fltyp = (c.strip() for c in (x["WA"].split("|") + ["", "", ""])[:3])
                if tplkz:
                    strinds[tplkz] += 1
                if fltyp:
                    cats[fltyp] += 1
                if tplnr:
                    existing.add(tplnr)
                    for i, seg in enumerate(tplnr.split(delim)):
                        widths[i] = max(widths.get(i, 0), len(seg))
        except Exception:
            pass
        cfg = {
            "strind": strinds.most_common(1)[0][0] if strinds else "",
            "category": cats.most_common(1)[0][0] if cats else "M",
            "delim": delim,
            "widths": [widths[i] for i in sorted(widths)] or [4, 3, 3],
            "existing": existing,
        }
        self._floc_cfg_cache = cfg
        return cfg

    def _floc_label(self, src_tplnr, cfg, taken):
        """Reformat a source funcloc label to conform to the target mask (per-level widths),
        truncating over-long segments; ensure uniqueness against existing + this-run labels.
        Returns (label, remapped_bool)."""
        delim, widths = cfg["delim"], cfg["widths"]
        segs = (src_tplnr or "").split(delim)
        fitted = [s[:(widths[i] if i < len(widths) else widths[-1])] for i, s in enumerate(segs) if s]
        label = delim.join(fitted).rstrip(delim)
        remapped = (label != (src_tplnr or "").strip())
        if not label:  # nothing usable -> fully generate
            label, remapped = "M4H" + delim + "001", True
        # uniqueness: bump the trailing segment within its width
        if label in taken or label in cfg["existing"]:
            remapped = True
            base = label.rsplit(delim, 1)
            w = widths[len(base[0].split(delim))] if len(base) > 1 and len(base[0].split(delim)) < len(widths) else widths[-1]
            n = 1
            while True:
                suffix = str(n).zfill(min(w, 3))[-w:]
                cand = (base[0] + delim + suffix) if len(base) > 1 else suffix
                if cand not in taken and cand not in cfg["existing"]:
                    label = cand
                    break
                n += 1
                if n > 99999:
                    break
        return label, remapped

    def create_funcloc(self, row: dict, commit: bool = True) -> dict:
        """Create a functional location (PM master). Funcloc labels are structure-indicator
        bound: the external label must conform to the target structure indicator's editing mask.
        We discover the in-use structure indicator + mask and reformat the source label to conform
        (collision-safe, source->target recorded in the ledger). Source ECC IFLOT: TPLNR, FLTYP;
        description IFLOTX-PLTXT. Standalone create (no auto-install into hierarchy)."""
        cfg = self._floc_config()
        if not cfg["strind"]:
            return {"status": "skipped", "messages": ["target has no functional-location structure indicator"]}
        src = (row.get("TPLNR") or "").strip()
        taken = getattr(self, "_floc_taken", None)
        if taken is None:
            taken = self._floc_taken = set()
        label, remapped = self._floc_label(src, cfg, taken)
        desc = ((row.get("PLTXT") or row.get("SHTXT") or ("Functional location " + (src or label))).strip())[:40]
        res = self.c.call("BAPI_FUNCLOC_CREATE", EXTERNAL_NUMBER=label,
                          DATA_GENERAL={"DESCRIPT": desc},
                          DATA_SPECIFIC={"STRIND": cfg["strind"], "CATEGORY": cfg["category"]})
        ret = self._ret(res)
        if [m for m in ret if m.get("TYPE") in ("E", "A")]:
            self._rollback()
            return {"status": "failed", "messages": [f"{m.get('TYPE')} {m.get('MESSAGE')}" for m in ret][:3]}
        target = (res.get("FUNCTLOCATION") or label).strip()
        taken.add(target)
        if commit:
            self._commit()
        verify = {"table": "IFLOT", "key": {"TPLNR": target}}
        msgs = [m.get("MESSAGE") for m in ret if m.get("TYPE") in ("S", "W")][:2]
        if remapped:
            msgs.append(f"label {src} reformatted to target mask ({cfg['strind']}) -> {target}")
        return {"status": "created", "funcloc": target, "verify_key": verify,
                "key_mapping": {"source": src or target, "target": target,
                                "disposition": "created" if target == src else "remapped"},
                "messages": msgs}

    # ── Characteristic (BAPI_CHARACT_CREATE) — classification master ───────────
    _CHAR_DTYPES = {"CHAR", "NUM", "DATE", "TIME", "CURR"}

    def _charact_exists(self, name: str) -> bool:
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="CABN", DELIMITER="|",
                            FIELDS=[{"FIELDNAME": "ATINN"}],
                            OPTIONS=[{"TEXT": f"ATNAM = '{name}'"}], ROWCOUNT=1)
            return bool(r.get("DATA"))
        except Exception:
            return False

    def create_characteristic(self, row: dict, commit: bool = True) -> dict:
        """Create a classification characteristic (CT04). The name (CABN.ATNAM) is a global key —
        preserved 1:1 (no remap); idempotent on existence. Source ECC CABN: ATNAM, ATFOR (data type),
        ANZST (length), ANZDZ (decimals). ATFOR (CHAR/NUM/DATE/TIME/CURR) maps directly to the BAPI
        DATA_TYPE domain; unknown -> CHAR."""
        name = (row.get("ATNAM") or "").strip().upper()
        if not name:
            return {"status": "skipped", "messages": ["missing characteristic name"]}
        verify = {"table": "CABN", "key": {"ATNAM": name}}
        if self._charact_exists(name):
            return {"status": "matched_existing", "characteristic": name, "verify_key": verify,
                    "key_mapping": {"source": name, "target": name, "disposition": "matched_existing"},
                    "messages": ["already present in target"]}
        dtype = (row.get("ATFOR") or "CHAR").strip().upper()
        if dtype not in self._CHAR_DTYPES:
            dtype = "CHAR"
        length = (row.get("ANZST") or "").strip() or ("10" if dtype in ("CHAR", "NUM", "CURR") else "8")
        detail = {"CHARACT_NAME": name, "DATA_TYPE": dtype, "LENGTH": str(length), "STATUS": "1"}
        dec = (row.get("ANZDZ") or "").strip()
        if dtype in ("NUM", "CURR") and dec:
            detail["DECIMALS"] = str(dec)
        desc = ((row.get("ATBEZ") or name).strip())[:30]
        res = self.c.call("BAPI_CHARACT_CREATE", CHARACTDETAIL=detail,
                          CHARACTDESCR=[{"LANGUAGE_ISO": "EN", "DESCRIPTION": desc}])
        ret = self._ret(res)
        if [m for m in ret if m.get("TYPE") in ("E", "A")]:
            self._rollback()
            return {"status": "failed", "messages": [f"{m.get('TYPE')} {m.get('MESSAGE')}" for m in ret][:3]}
        if commit:
            self._commit()
        msgs = [m.get("MESSAGE") for m in ret if m.get("TYPE") in ("S", "W")][-1:]
        return {"status": "created", "characteristic": name, "verify_key": verify,
                "key_mapping": {"source": name, "target": name, "disposition": "created"},
                "messages": msgs}

    # ── Class (BAPI_CLASS_CREATE) — classification master ─────────────────────
    def _class_types(self):
        """Set of class types (KLART) configured in the target (TCLA), cached. A class can
        only be created for a class type that exists in target customizing."""
        cache = getattr(self, "_class_types_cache", None)
        if cache is not None:
            return cache
        types = set()
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="TCLA", DELIMITER="|",
                            FIELDS=[{"FIELDNAME": "KLART"}], ROWCOUNT=200)
            types = {x["WA"].strip() for x in r.get("DATA", []) if x["WA"].strip()}
        except Exception:
            pass
        self._class_types_cache = types
        return types

    def _class_exists(self, name: str, ktype: str) -> bool:
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="KLAH", DELIMITER="|",
                            FIELDS=[{"FIELDNAME": "CLINT"}],
                            OPTIONS=[{"TEXT": f"CLASS = '{name}' AND KLART = '{ktype}'"}], ROWCOUNT=1)
            return bool(r.get("DATA"))
        except Exception:
            return False

    def create_class(self, row: dict, commit: bool = True) -> dict:
        """Create a classification class (CL02). Keyed by (CLASS, KLART) -> preserved 1:1 (no remap);
        idempotent on existence. The class type (KLART) must be configured in the target (TCLA); if
        not, the row is skipped with a reason (a customizing prerequisite, not a data defect). Source
        ECC KLAH: CLASS, KLART; description SWOR/KLAH text."""
        name = (row.get("CLASS") or "").strip().upper()
        ktype = (row.get("KLART") or "").strip()
        if not name or not ktype:
            return {"status": "skipped", "messages": ["missing class name / type"]}
        if ktype not in self._class_types():
            return {"status": "skipped", "messages": [f"class type {ktype} not configured in target (TCLA)"]}
        verify = {"table": "KLAH", "key": {"CLASS": name, "KLART": ktype}}
        if self._class_exists(name, ktype):
            return {"status": "matched_existing", "klass": name, "verify_key": verify,
                    "key_mapping": {"source": name, "target": name, "disposition": "matched_existing"},
                    "messages": ["already present in target"]}
        desc = ((row.get("KSCHL") or row.get("SWOR") or name).strip())[:40]
        res = self.c.call("BAPI_CLASS_CREATE", CLASSNUMNEW=name, CLASSTYPENEW=ktype,
                          CLASSBASICDATA={"STATUS": "1"},
                          CLASSDESCRIPTIONS=[{"LANGU_ISO": "EN", "CATCHWORD": desc}])
        ret = self._ret(res)
        if [m for m in ret if m.get("TYPE") in ("E", "A")]:
            self._rollback()
            return {"status": "failed", "messages": [f"{m.get('TYPE')} {m.get('MESSAGE')}" for m in ret][:3]}
        if commit:
            self._commit()
        msgs = [m.get("MESSAGE") for m in ret if m.get("TYPE") in ("S", "W", "I")][-1:]
        return {"status": "created", "klass": name, "verify_key": verify,
                "key_mapping": {"source": name, "target": name, "disposition": "created"},
                "messages": msgs}

    # ── CO groups (cost element / profit center hierarchies) ───────────────────
    def _co_chart(self) -> str:
        """Most-common operative chart of accounts in the target (T001.KTOPL), cached."""
        cache = getattr(self, "_co_chart_cache", None)
        if cache is not None:
            return cache
        chart = ""
        try:
            from collections import Counter
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="T001", DELIMITER="|",
                            FIELDS=[{"FIELDNAME": "KTOPL"}], ROWCOUNT=300)
            c = Counter(x["WA"].strip() for x in r.get("DATA", []) if x["WA"].strip())
            chart = c.most_common(1)[0][0] if c else ""
        except Exception:
            pass
        self._co_chart_cache = chart
        return chart

    def _cogroup_exists(self, setclass: str, subclass: str, name: str) -> bool:
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="SETHEADER", DELIMITER="|",
                            FIELDS=[{"FIELDNAME": "SETNAME"}],
                            OPTIONS=[{"TEXT": f"SETCLASS = '{setclass}' AND SETNAME = '{name}'"}], ROWCOUNT=1)
            return bool(r.get("DATA"))
        except Exception:
            return False

    def _co_group_create(self, fm: str, key_arg: str, key_val: str, setclass: str,
                         subclass: str, row: dict, commit: bool) -> dict:
        """Shared create for a CO group/hierarchy (cost element or profit center). Creates the
        top node (a valid, reconcilable hierarchy container); optional member value ranges from
        row['VALUES'] (list of (from,to)) are added when present. Group name (SETNAME, max 12) is
        preserved (uppercased/truncated); idempotent on SETHEADER. verify_key on SETHEADER."""
        name = (row.get("SETNAME") or "").strip().upper()
        if not name:
            return {"status": "skipped", "messages": ["missing group name"]}
        if len(name) > 12:  # SAP set-name limit; truncation yields invalid names -> route to manual rename
            return {"status": "skipped",
                    "messages": [f"group name {name} exceeds the 12-char SAP set-name limit (manual rename required)"]}
        if not key_val:
            return {"status": "skipped", "messages": [f"no target {key_arg.lower()} discovered"]}
        verify = {"table": "SETHEADER", "key": {"SETCLASS": setclass, "SETNAME": name}}
        if self._cogroup_exists(setclass, subclass, name):
            return {"status": "matched_existing", "group": name, "verify_key": verify,
                    "key_mapping": {"source": name, "target": name, "disposition": "matched_existing"},
                    "messages": ["already present in target"]}
        desc = ((row.get("DESCRIPT") or name).strip())[:40]
        values = row.get("VALUES") or []
        nodes = [{"GROUPNAME": name, "HIERLEVEL": 0, "VALCOUNT": len(values), "DESCRIPT": desc}]
        hvals = [{"VALFROM": str(f).strip(), "VALTO": str(to).strip()} for f, to in values]
        kwargs = {key_arg: key_val, "LANGUAGE": {"LANGU_ISO": "EN"},
                  "HIERARCHYNODES": nodes}
        if hvals:
            kwargs["HIERARCHYVALUES"] = hvals
        else:
            kwargs["TOPNODEONLY"] = "X"
        res = self.c.call(fm, **kwargs)
        ret = self._ret(res)
        if [m for m in ret if m.get("TYPE") in ("E", "A")]:
            self._rollback()
            return {"status": "failed", "messages": [f"{m.get('TYPE')} {m.get('MESSAGE')}" for m in ret][:3]}
        target = (res.get("GROUPNAME") or name).strip()
        if commit:
            self._commit()
        return {"status": "created", "group": target, "verify_key": verify,
                "key_mapping": {"source": name, "target": target, "disposition": "created"},
                "messages": [m.get("MESSAGE") for m in ret if m.get("TYPE") in ("S", "W")][-1:]}

    def create_costelementgroup(self, row: dict, org: dict, commit: bool = True) -> dict:
        """Cost element group (KAH1) — set class 0102, sub-class = chart of accounts."""
        chart = (org or {}).get("CHART") or self._co_chart()
        return self._co_group_create("BAPI_COSTELEMENTGRP_CREATE", "CHARTOFACCOUNTSIMP", chart,
                                     "0102", chart, row, commit)

    def create_profitcentergroup(self, row: dict, org: dict, commit: bool = True) -> dict:
        """Profit center group (KCH1) — set class 0106, sub-class = controlling area."""
        coarea = (org or {}).get("CO_AREA") or ""
        return self._co_group_create("BAPI_PROFITCENTERGRP_CREATE", "CONTROLLINGAREAIMP", coarea,
                                     "0106", coarea, row, commit)

    # ── Project definition (BAPI_PROJECTDEF_CREATE) — PS master ────────────────
    def _project_config(self):
        """Discover the target's dominant project profile + controlling area (from PROJ), cached.
        A project definition requires a project profile that exists in target customizing."""
        cache = getattr(self, "_proj_cfg_cache", None)
        if cache is not None:
            return cache
        from collections import Counter
        profs, areas = Counter(), Counter()
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="PROJ", DELIMITER="|",
                            FIELDS=[{"FIELDNAME": "PROFL"}, {"FIELDNAME": "VKOKR"}], ROWCOUNT=500)
            for x in r.get("DATA", []):
                pr, ar = (c.strip() for c in (x["WA"].split("|") + ["", ""])[:2])
                if pr:
                    profs[pr] += 1
                if ar:
                    areas[ar] += 1
        except Exception:
            pass
        cfg = {"profile": profs.most_common(1)[0][0] if profs else "",
               "co_area": areas.most_common(1)[0][0] if areas else ""}
        self._proj_cfg_cache = cfg
        return cfg

    def _project_exists(self, pid: str) -> bool:
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="PROJ", DELIMITER="|",
                            FIELDS=[{"FIELDNAME": "PSPNR"}],
                            OPTIONS=[{"TEXT": f"PSPID = '{pid}'"}], ROWCOUNT=1)
            return bool(r.get("DATA"))
        except Exception:
            return False

    def create_project(self, row: dict, commit: bool = True) -> dict:
        """Create a project definition (CJ20N). Project IDs are coding-mask bound: a source ID whose
        separators collide with a target mask is rejected, so we try the source ID as-is and, on a
        mask error, retry a sanitized free-form ID (separators stripped) -- a collision-safe remap
        recorded in the ledger. Profile + controlling area auto-discovered. Source ECC PROJ: PSPID,
        POST1 (desc)."""
        import re
        cfg = self._project_config()
        profile, coarea = cfg["profile"], cfg["co_area"]
        if not profile:
            return {"status": "skipped", "messages": ["no target project profile discovered"]}
        pid = (row.get("PSPID") or "").strip()
        if not pid:
            return {"status": "skipped", "messages": ["missing project id"]}
        desc = ((row.get("POST1") or ("Project " + pid)).strip())[:40]
        if self._project_exists(pid):
            verify = {"table": "PROJ", "key": {"PSPID": pid}}
            return {"status": "matched_existing", "project": pid, "verify_key": verify,
                    "key_mapping": {"source": pid, "target": pid, "disposition": "matched_existing"},
                    "messages": ["already present in target"]}
        sanitized = re.sub(r"[^A-Za-z0-9_]", "", pid)[:24] or ("PRJ" + pid[:8])
        attempts = [pid] if pid == sanitized else [pid, sanitized]
        last = None
        for cand in attempts:
            stru = {"PROJECT_DEFINITION": cand, "DESCRIPTION": desc,
                    "PROJECT_PROFILE": profile, "CONTROLLING_AREA": coarea}
            try:
                res = self.c.call("BAPI_PROJECTDEF_CREATE", PROJECT_DEFINITION_STRU=stru)
            except Exception as ex:
                last = str(ex).splitlines()[0]
                self._rollback()
                continue
            ret = self._ret(res)
            if [m for m in ret if m.get("TYPE") in ("E", "A")]:
                last = "; ".join(f"{m.get('TYPE')} {m.get('MESSAGE')}" for m in ret)[:120]
                self._rollback()
                continue
            if commit:
                self._commit()
            verify = {"table": "PROJ", "key": {"PSPID": cand}}
            msgs = [] if cand == pid else [f"project id {pid} sanitized to target -> {cand}"]
            return {"status": "created", "project": cand, "verify_key": verify,
                    "key_mapping": {"source": pid, "target": cand,
                                    "disposition": "created" if cand == pid else "remapped"},
                    "messages": msgs}
        return {"status": "failed", "messages": [f"project create failed: {last}"]}

    # ── Exchange rate (BAPI writes TCURR; cleaner than an EXCHANGE_RATE IDoc) ─
    # BAPI_EXCHRATE_CREATEMULTIPLE accepts VALID_FROM only within this window
    # (empirically: 1900-01-01 OK, 1798 rejected; 2050 OK, 2080 rejected).
    _EXRATE_FLOOR = datetime.date(1900, 1, 1)
    _EXRATE_CEILING = datetime.date(2050, 1, 1)

    @classmethod
    def _gdatu_to_date(cls, gdatu):
        """TCURR-GDATU is an INVERTED date (99999999 - YYYYMMDD). Un-invert it
        and clamp into the BAPI's accepted window. The IDES 'beginning of time'
        baseline decodes to 1798 (below the floor) -> clamp up to the floor so
        the rate still loads and applies to all current dates.
        Returns (datetime.date, clamped_bool)."""
        try:
            ymd = 99999999 - int(str(gdatu).strip())
            d = datetime.date(ymd // 10000, (ymd // 100) % 100, ymd % 100)
        except Exception:
            return datetime.date.today(), False
        if d < cls._EXRATE_FLOOR:
            return cls._EXRATE_FLOOR, True
        if d > cls._EXRATE_CEILING:
            return cls._EXRATE_CEILING, True
        return d, False

    def target_rate_types(self) -> set:
        """Cached set of exchange-rate types (TCURV-KURST) the target defines.
        A rate cannot be created for a type the target doesn't have configured,
        and exchange-rate types are *customizing* (no BAPI to create them) — so we
        screen against this list rather than letting the BAPI hard-fail per row."""
        cache = getattr(self, "_rate_types_cache", None)
        if cache is not None:
            return cache
        types = set()
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="TCURV", DELIMITER="|",
                            FIELDS=[{"FIELDNAME": "KURST"}], ROWCOUNT=1000)
            types = {row["WA"].split("|")[0].strip() for row in r.get("DATA", [])}
        except Exception:
            types = set()  # screening disabled if we can't read TCURV
        self._rate_types_cache = types
        return types

    def configured_rate_types(self) -> set:
        """Cached set of rate types that are actually *operational* in the target —
        i.e. have translation factors (TCURF). A type can exist in TCURV yet still
        reject rates with 'valid system settings have not been made' when its factor
        config is absent (standard B/G are the classic example on a vanilla system).
        Used to try the most-likely-to-succeed rows first."""
        cache = getattr(self, "_conf_types_cache", None)
        if cache is not None:
            return cache
        types = set()
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="TCURF", DELIMITER="|",
                            FIELDS=[{"FIELDNAME": "KURST"}], ROWCOUNT=100000)
            types = {row["WA"].split("|")[0].strip() for row in r.get("DATA", [])}
        except Exception:
            types = set()
        self._conf_types_cache = types
        return types

    def free_rate_types(self) -> set:
        """Cached set of NON-fixed rate types (TCURV XEURO/XFIXD both off). Fixed/EMU
        types (e.g. EURX) reject free rate creation, so for bulk loading we try the
        free types (M, etc.) first — they actually post."""
        cache = getattr(self, "_free_types_cache", None)
        if cache is not None:
            return cache
        free = set()
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="TCURV", DELIMITER="|",
                            FIELDS=[{"FIELDNAME": "KURST"}, {"FIELDNAME": "XEURO"},
                                    {"FIELDNAME": "XFIXD"}], ROWCOUNT=1000)
            for row in r.get("DATA", []):
                kt, xeuro, xfixd = [x.strip() for x in row["WA"].split("|")]
                if xeuro != "X" and xfixd != "X":
                    free.add(kt)
        except Exception:
            free = set()
        self._free_types_cache = free
        return free

    def _exrate_line(self, row: dict):
        """Build one EXCHRATE_LIST line + its TCURR verify-key from a source row."""
        vf, _ = self._gdatu_to_date(row.get("GDATU"))
        exch = parse_sap_number(row.get("UKURS"))
        gdatu = str(99999999 - int(vf.strftime("%Y%m%d")))
        rate_type = (row.get("KURST") or "M").strip()
        line = {"RATE_TYPE": rate_type, "FROM_CURR": (row.get("FCURR") or "").strip(),
                "TO_CURRNCY": (row.get("TCURR") or "").strip(), "VALID_FROM": vf,
                "EXCH_RATE": exch,
                "FROM_FACTOR": str(int(parse_sap_number(row.get("FFACT"), 1)) or 1),
                "TO_FACTOR": str(int(parse_sap_number(row.get("TFACT"), 1)) or 1)}
        # Effective-rate tie-out: TCURR.UKURS is factor-normalized by the BAPI, so the
        # reconciler verifies stored UKURS * TCURF(TFACT/FFACT) == the rate we sent.
        vkey = {"table": "TCURR", "effective_rate": exch,
                "key": {"KURST": rate_type, "FCURR": line["FROM_CURR"],
                        "TCURR": line["TO_CURRNCY"], "GDATU": gdatu}}
        return line, vkey

    def create_exchange_rates_batch(self, rows: list, commit: bool = True) -> dict:
        """Load MANY rates in one BAPI_EXCHRATE_CREATEMULTIPLE call — the production
        throughput path (the API is built for it). Screens out missing-type rows, then
        maps the BAPI's per-line 'Line N:' failures back so created_keys reflect exactly
        what persisted. Partial success is honored (good lines commit)."""
        known = self.target_rate_types()
        lines, meta, skipped_missing = [], [], 0
        for row in rows:
            fcurr = (row.get("FCURR") or "").strip()
            tcurr = (row.get("TCURR") or "").strip()
            rate_type = (row.get("KURST") or "M").strip()
            if not (fcurr and tcurr):
                continue
            if known and rate_type not in known:
                skipped_missing += 1
                continue
            line, vkey = self._exrate_line(row)
            lines.append(line)
            meta.append(vkey)
        if not lines:
            return {"created": 0, "failed": 0, "skipped_missing": skipped_missing,
                    "created_keys": [], "sample_errors": []}
        res = self.c.call("BAPI_EXCHRATE_CREATEMULTIPLE", UPD_ALLOW="X", EXCHRATE_LIST=lines)
        ret = self._ret(res)
        failed = set()
        for m in ret:
            if m.get("TYPE") in ("E", "A"):
                mm = re.search(r"Line\s+(\d+)", m.get("MESSAGE") or "")
                if mm:
                    failed.add(int(mm.group(1)))
        if commit:
            self._commit()
        created_keys = [meta[i] for i in range(len(lines)) if (i + 1) not in failed]
        return {"created": len(lines) - len(failed), "failed": len(failed),
                "skipped_missing": skipped_missing, "created_keys": created_keys,
                "sample_errors": [(m.get("MESSAGE") or "").strip()[:90] for m in ret
                                  if m.get("TYPE") in ("E", "A")][:3]}

    def create_exchange_rate(self, row: dict, commit: bool = True) -> dict:
        """Create one exchange-rate entry from a TCURR-shaped source row via
        BAPI_EXCHRATE_CREATEMULTIPLE (writes TCURR). Expects
        KURST/FCURR/TCURR/GDATU/UKURS (+ optional FFACT/TFACT)."""
        fcurr = (row.get("FCURR") or "").strip()
        tcurr = (row.get("TCURR") or "").strip()
        if not (fcurr and tcurr):
            return {"status": "skipped", "messages": ["missing FROM/TO currency"]}
        rate_type = (row.get("KURST") or "M").strip()
        known = self.target_rate_types()
        if known and rate_type not in known:
            # Type isn't defined in the target (a config/customizing gap, not bad
            # data). Set aside cleanly so the rest of the rates still load.
            return {"status": "skipped_missing_ratetype", "rate_type": rate_type,
                    "messages": [f"rate type '{rate_type}' not defined in target (TCURV)"]}
        valid_from, clamped = self._gdatu_to_date(row.get("GDATU"))
        exch_rate = parse_sap_number(row.get("UKURS"))           # honors trailing-minus (indirect quote)
        line = {
            "RATE_TYPE":   rate_type,
            "FROM_CURR":   fcurr,
            "TO_CURRNCY":  tcurr,
            "VALID_FROM":  valid_from,                           # datetime.date (DATS)
            "EXCH_RATE":   exch_rate,                            # FLTP
            "FROM_FACTOR": str(int(parse_sap_number(row.get("FFACT"), 1)) or 1),  # DEC -> string
            "TO_FACTOR":   str(int(parse_sap_number(row.get("TFACT"), 1)) or 1),
        }
        res = self.c.call("BAPI_EXCHRATE_CREATEMULTIPLE",
                          UPD_ALLOW="X", EXCHRATE_LIST=[line])
        ret = self._ret(res)
        errs = [m for m in ret if m.get("TYPE") in ("E", "A")]
        if errs:
            self._rollback()
            # Distinguish a customizing gap (rate type exists but the currency-pair
            # factor/settings are absent) from a genuine data error. The former is a
            # target-config prerequisite, not bad source data — report, don't fail.
            txt = " ".join((m.get("MESSAGE") or "") for m in errs).lower()
            cfg_gap = ("system settings" in txt or "not been made" in txt
                       or "no exchange rate type" in txt)
            return {"status": "skipped_config_gap" if cfg_gap else "failed",
                    "rate_type": rate_type,
                    "messages": [f"{m.get('TYPE')} {m.get('MESSAGE')}" for m in ret]}
        if commit:
            self._commit()
        msgs = [m.get("MESSAGE") for m in ret]
        if clamped:
            msgs.append(f"valid-from clamped to {valid_from.isoformat()} (source date out of BAPI range)")
        gdatu = str(99999999 - int(valid_from.strftime("%Y%m%d")))   # TCURR stores inverted date
        return {"status": "created",
                "rate": f"{fcurr}->{tcurr}@{valid_from.isoformat()}",
                # Effective-rate tie-out: reconciler checks UKURS*TCURF factor == sent.
                "verify_key": {"table": "TCURR", "effective_rate": exch_rate,
                               "key": {"KURST": rate_type, "FCURR": fcurr,
                                       "TCURR": tcurr, "GDATU": gdatu}},
                "messages": msgs}
