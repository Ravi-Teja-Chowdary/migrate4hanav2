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
        hdr = {"COMP_CODE": org["COMP_CODE"], "DOC_TYPE": org["DOC_TYPE"], "VENDOR": tgt_vendor,
               "PURCH_ORG": ekorg, "PUR_GROUP": org["PUR_GROUP"], "DOC_DATE": doc_date}
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
        return {"status": "created", "doc": belnr, "partner": partner_ref,
                "verify_key": {"table": "BKPF", "key": {"BUKRS": bk or bukrs,
                                                        "BELNR": belnr, "GJAHR": gj}},
                "key_mapping": {"source": src_doc, "target": belnr, "disposition": "created"},
                "messages": [m.get("MESSAGE") for m in ret if m.get("TYPE") in ("S", "W")][:2]}

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
