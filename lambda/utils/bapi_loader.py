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
                "verify_key": {"table": "TCURR",
                               "key": {"KURST": rate_type, "FCURR": fcurr,
                                       "TCURR": tcurr, "GDATU": gdatu},
                               "values": {"UKURS": exch_rate}},   # financial value tie-out
                "messages": msgs}
