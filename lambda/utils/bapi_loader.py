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
        res = self.c.call("BAPI_PO_CREATE1", POHEADER=hdr, POHEADERX={k: "X" for k in hdr},
                          POITEM=poitem, POITEMX=poitemx, POACCOUNT=acct, POACCOUNTX=acctx)
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
