"""
bapi_loader — BAPI-based write adapter (the cleanest mechanism for most master
data when a super-admin RFC user is available). Sits alongside idoc_loader;
both are fed by meta_recipe.MetaRecipeResolver.

BAPIs are SAP-shipped, business-logic-honoring APIs — fully support-preserving
(they are NOT raw table writes). For Business Partner / Customer / Vendor this
path sidesteps the DEBMAS/MDG IDoc bottleneck entirely.
"""
from __future__ import annotations


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
        return {"status": "created", "partner": bp, "verified": verified,
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
    def create_material(self, matnr: str, mtype="HALB", ind="M", uom="EA",
                        desc="Migrate4HANA material", commit: bool = True) -> dict:
        res = self.c.call("BAPI_MATERIAL_SAVEDATA",
                          HEADDATA={"MATERIAL": matnr, "IND_SECTOR": ind,
                                    "MATL_TYPE": mtype, "BASIC_VIEW": "X"},
                          CLIENTDATA={"BASE_UOM": uom}, CLIENTDATAX={"BASE_UOM": "X"},
                          MATERIALDESCRIPTION=[{"LANGU": "EN", "MATL_DESC": desc}])
        ret = self._ret(res)
        errs = [m for m in ret if m.get("TYPE") in ("E", "A")]
        if errs:
            self._rollback()
            return {"status": "failed", "material": matnr,
                    "messages": [f"{m.get('TYPE')} {m.get('MESSAGE')}" for m in ret]}
        if commit:
            self._commit()
        return {"status": "created", "material": matnr,
                "messages": [m.get("MESSAGE") for m in ret]}
