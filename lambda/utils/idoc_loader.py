"""
idoc_loader — recipe-driven IDoc loader for posting master data into S/4HANA
through SAP's own inbound IDoc channel (support-preserving write path).

Design goals (maximum automation):
  * Per-object RECIPES: which IDoc type, segments, field mapping, defaults.
  * Auto-discover each segment's field layout from DD03L (offsets are correct
    on any release, no hardcoded positions).
  * Post via IDOC_INBOUND_ASYNCHRONOUS, then read EDIDC/EDIDS status.
  * Self-diagnose status 51: parse the application log for "field X required"
    messages and report them precisely (so adding a new object type is a
    quick, guided iteration instead of blind debugging).

Proven against live S/4 2023/2025: Material (MATMAS05) posts to status 53.

Usage:
    from idoc_loader import IDocLoader
    ldr = IDocLoader(conn, own_logical_system="S4HCLNT100", sender="M4HSENDER")
    result = ldr.post("Material", {"MATNR": "M4H100", "MAKTX": "Test"})
    # result = {"docnum":..., "status":"53", "created":True, "missing_fields":[...], "messages":[...]}
"""
from __future__ import annotations
import time
from datetime import datetime


# ── Per-object recipes ───────────────────────────────────────────────────────
# Each recipe: idoc_type, message_type, verify (table+key), and segments.
# A segment maps row data -> SAP field names; `defaults` fill required fields
# the source row may not carry. `dynamic` keys are resolved at runtime (e.g. a
# valid material group looked up from the target system).
RECIPES = {
    "Material": {
        "idoc_type": "MATMAS05", "message_type": "MATMAS",
        "verify_table": "MARA", "verify_key": "MATNR",
        "segments": [
            {"name": "E1MARAM", "hlevel": "01", "segnum": "000001", "psgnum": "000000",
             "app_table": "MARA",
             "map": {"MATNR": "MATNR", "MTART": "MTART", "MBRSH": "MBRSH", "MEINS": "MEINS"},
             "defaults": {"MSGFN": "005", "MTART": "HALB", "MBRSH": "M", "MEINS": "EA",
                          "PSTAT": "K", "GEWEI": "KG"},
             "dynamic": {"MATKL": "material_group"}},
            {"name": "E1MAKTM", "hlevel": "02", "segnum": "000002", "psgnum": "000001",
             "app_table": "MAKT",
             "map": {"MAKTX": "MAKTX"},
             "defaults": {"MSGFN": "005", "SPRAS": "E", "SPRAS_ISO": "EN",
                          "MAKTX": "Migrated by Migrate4HANA"}},
        ],
    },
    # Business Partner / Customer via DEBMAS — recipe scaffold (fields to be
    # confirmed on first live run via the self-diagnosis output).
    "Customer": {
        "idoc_type": "DEBMAS07", "message_type": "DEBMAS",
        "verify_table": "KNA1", "verify_key": "KUNNR",
        "segments": [
            {"name": "E1KNA1M", "hlevel": "01", "segnum": "000001", "psgnum": "000000",
             "map": {"KUNNR": "KUNNR", "NAME1": "NAME1", "LAND1": "LAND1", "ORT01": "ORT01"},
             "defaults": {"MSGFN": "005", "LAND1": "DE", "SPRAS": "E", "KTOKD": "0001"}},
        ],
    },
}


class IDocLoader:
    def __init__(self, conn, own_logical_system: str, sender: str = "M4HSENDER",
                 client: str = "100", target_sid: str = "S4H"):
        self.c = conn
        self.own_ls = own_logical_system
        self.sender = sender
        self.client = client
        self.sid = target_sid
        self._layout_cache: dict = {}
        self._dynamic_cache: dict = {}

    # ── segment layout (DD03L) ──────────────────────────────────────────────
    def _layout(self, segname: str):
        if segname in self._layout_cache:
            return self._layout_cache[segname]
        r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="DD03L", DELIMITER="|",
                        OPTIONS=[{"TEXT": f"TABNAME = '{segname}'"}],
                        FIELDS=[{"FIELDNAME": "FIELDNAME"}, {"FIELDNAME": "POSITION"},
                                {"FIELDNAME": "LENG"}], ROWCOUNT=999)
        rows = []
        for d in r.get("DATA", []):
            fn, pos, leng = [p.strip() for p in d["WA"].split("|")]
            if fn and not fn.startswith("."):
                rows.append((int(pos), fn, int(leng)))
        rows.sort()
        self._layout_cache[segname] = rows
        return rows

    def _build_sdata(self, segname: str, values: dict) -> str:
        out = []
        for _pos, fn, leng in self._layout(segname):
            out.append(str(values.get(fn, "")).ljust(leng)[:leng])
        return "".join(out).ljust(1000)

    # ── dynamic value resolvers (valid codes from the target) ───────────────
    def _resolve_dynamic(self, kind: str) -> str:
        if kind in self._dynamic_cache:
            return self._dynamic_cache[kind]
        val = ""
        try:
            if kind == "material_group":
                r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="T023", DELIMITER="|",
                                FIELDS=[{"FIELDNAME": "MATKL"}], ROWCOUNT=1)
                val = (r.get("DATA") or [{"WA": ""}])[0]["WA"].split("|")[0].strip()
        except Exception:
            val = ""
        self._dynamic_cache[kind] = val
        return val

    def _seg_values(self, seg: dict, row: dict) -> dict:
        vals = dict(seg.get("defaults", {}))
        for sap_field, src_field in seg.get("map", {}).items():
            if row.get(src_field):
                vals[sap_field] = row[src_field]
        for sap_field, kind in seg.get("dynamic", {}).items():
            resolved = self._resolve_dynamic(kind)
            if resolved:
                vals[sap_field] = resolved
        return vals

    # ── post one object ─────────────────────────────────────────────────────
    def post(self, object_name: str, row: dict) -> dict:
        recipe = RECIPES.get(object_name)
        if not recipe:
            return {"object": object_name, "status": "no_recipe",
                    "error": f"no IDoc recipe for {object_name}"}
        now = datetime.now()
        control = [{
            "TABNAM": "EDI_DC40", "MANDT": self.client, "DIRECT": "2",
            "IDOCTYP": recipe["idoc_type"], "MESTYP": recipe["message_type"],
            "SNDPOR": "SAPM4H", "SNDPRT": "LS", "SNDPRN": self.sender,
            "RCVPOR": f"SAP{self.sid}", "RCVPRT": "LS", "RCVPRN": self.own_ls,
            "CREDAT": now.strftime("%Y%m%d"), "CRETIM": now.strftime("%H%M%S"),
        }]
        data = []
        for seg in recipe["segments"]:
            vals = self._seg_values(seg, row)
            data.append({"SEGNAM": seg["name"], "MANDT": self.client,
                         "SEGNUM": seg["segnum"], "PSGNUM": seg["psgnum"],
                         "HLEVEL": seg["hlevel"], "SDATA": self._build_sdata(seg["name"], vals)})

        self.c.call("IDOC_INBOUND_ASYNCHRONOUS",
                    IDOC_CONTROL_REC_40=control, IDOC_DATA_REC_40=data)
        try:
            self.c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception:
            pass
        time.sleep(2)
        return self._status(recipe, row)

    # ── META post: resolve every field via the resolver ────────────────────
    def post_resolved(self, object_name: str, source_row: dict, resolver) -> dict:
        """Like post(), but each field value is derived by the MetaRecipeResolver
        (source-if-valid -> default -> check-table), with the recipe's declared
        default as a final fallback. This is the meta-recipe path: adding a new
        object type needs only its segment skeleton, not hand-picked values."""
        recipe = RECIPES.get(object_name)
        if not recipe:
            return {"object": object_name, "status": "no_recipe"}
        now = datetime.now()
        control = [{
            "TABNAM": "EDI_DC40", "MANDT": self.client, "DIRECT": "2",
            "IDOCTYP": recipe["idoc_type"], "MESTYP": recipe["message_type"],
            "SNDPOR": "SAPM4H", "SNDPRT": "LS", "SNDPRN": self.sender,
            "RCVPOR": f"SAP{self.sid}", "RCVPRT": "LS", "RCVPRN": self.own_ls,
            "CREDAT": now.strftime("%Y%m%d"), "CRETIM": now.strftime("%H%M%S"),
        }]
        data, resolution = [], {}
        for seg in recipe["segments"]:
            app = seg.get("app_table", "")
            needed = list(dict.fromkeys(
                list(seg.get("defaults", {}).keys())
                + list(seg.get("map", {}).keys())
                + list(seg.get("dynamic", {}).keys())))
            vals = {}
            for f in needed:
                r = resolver.resolve(app, f, source_row) if app else {"value": None, "via": "no_table"}
                v = r.get("value")
                if v is None:                       # fall back to recipe's hardcoded default
                    v = seg.get("defaults", {}).get(f)
                    r = {"value": v, "via": "recipe_default"}
                if v is not None:
                    vals[f] = v
                resolution[f"{seg['name']}.{f}"] = r.get("via")
            data.append({"SEGNAM": seg["name"], "MANDT": self.client,
                         "SEGNUM": seg["segnum"], "PSGNUM": seg["psgnum"],
                         "HLEVEL": seg["hlevel"], "SDATA": self._build_sdata(seg["name"], vals)})

        self.c.call("IDOC_INBOUND_ASYNCHRONOUS",
                    IDOC_CONTROL_REC_40=control, IDOC_DATA_REC_40=data)
        try:
            self.c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception:
            pass
        time.sleep(2)
        out = self._status(recipe, source_row)
        out["resolution"] = resolution
        return out

    # ── read status + self-diagnose ─────────────────────────────────────────
    def _status(self, recipe: dict, row: dict) -> dict:
        r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="EDIDC", DELIMITER="|",
                        OPTIONS=[{"TEXT": f"DIRECT = '2' AND MESTYP = '{recipe['message_type']}'"}],
                        FIELDS=[{"FIELDNAME": "DOCNUM"}, {"FIELDNAME": "STATUS"},
                                {"FIELDNAME": "CREDAT"}, {"FIELDNAME": "CRETIM"}],
                        ROWCOUNT=200)
        rows = sorted([[p.strip() for p in d["WA"].split("|")] for d in r.get("DATA", [])],
                      key=lambda x: (x[2], x[3]))
        if not rows:
            return {"status": "no_idoc"}
        docnum, status = rows[-1][0], rows[-1][1]
        missing, messages = [], []
        if status != "53":
            messages, missing = self._diagnose(docnum)
        created = self._verify(recipe, row) if status == "53" else False
        return {"docnum": docnum, "status": status, "created": created,
                "missing_fields": missing, "messages": messages}

    def _diagnose(self, docnum: str):
        """Read EDIDS status records + resolve the underlying app messages."""
        messages, missing = [], []
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="EDIDS", DELIMITER="|",
                            OPTIONS=[{"TEXT": f"DOCNUM = '{docnum}'"}],
                            FIELDS=[{"FIELDNAME": "STATUS"}, {"FIELDNAME": "STAMID"},
                                    {"FIELDNAME": "STAMNO"}, {"FIELDNAME": "STAPA1"},
                                    {"FIELDNAME": "STAPA2"}], ROWCOUNT=50)
            for d in r.get("DATA", []):
                v = [p.strip() for p in d["WA"].split("|")]
                st, mid, mno = v[0], v[1], v[2]
                vars_ = [x for x in v[3:5] if x]
                txt = self._msg_text(mid, mno, vars_)
                if txt:
                    messages.append(f"{st} {mid}{mno}: {txt}")
                    low = txt.lower()
                    if "required field" in low or "is required" in low or "mandatory" in low:
                        for vv in vars_:
                            if "-" in vv:
                                missing.append(vv.strip())
        except Exception as e:
            messages.append(f"diagnose error: {e}")
        return messages, missing

    def _msg_text(self, mid: str, mno: str, vars_: list) -> str:
        if not (mid and mno):
            return ""
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="T100", DELIMITER="|",
                            OPTIONS=[{"TEXT": f"SPRSL = 'E' AND ARBGB = '{mid}' AND MSGNR = '{mno}'"}],
                            FIELDS=[{"FIELDNAME": "TEXT"}], ROWCOUNT=1)
            if r.get("DATA"):
                txt = r["DATA"][0]["WA"].split("|")[0].strip()
                for i, val in enumerate(vars_, 1):
                    txt = txt.replace(f"&{i}", val).replace("&", val, 1)
                return txt
        except Exception:
            pass
        return ""

    def _verify(self, recipe: dict, row: dict) -> bool:
        key_field = recipe["verify_key"]
        key_val = row.get(key_field, "")
        if not key_val:
            return True
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE=recipe["verify_table"], DELIMITER="|",
                            OPTIONS=[{"TEXT": f"{key_field} LIKE '%{key_val}%'"}],
                            FIELDS=[{"FIELDNAME": key_field}], ROWCOUNT=1)
            return bool(r.get("DATA"))
        except Exception:
            return False
