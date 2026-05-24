"""
meta_recipe — the intelligence layer for the data loader.

Given a target field that a recipe must populate, derive a VALID value
automatically, in this order:
  1. The extracted source row (if it carries the field with a value).
  2. The field's CHECK TABLE in the target's data dictionary — read one valid
     key value from it (e.g. MARA-MATKL -> check table T023 -> a real material
     group; MARA-GEWEI -> T006 -> a real weight unit). This is the "smart" bit:
     it learns valid codes from the *target system's own configuration*, so a
     new object type doesn't need hand-picked constants.
  3. A small set of known safe defaults.
  4. None (caller reports it as needing a mapping).

Plus persistence: discovered/seeded recipes are saved so future runs skip
re-discovery and the platform accumulates its mapping knowledge.
"""
from __future__ import annotations
import json
from pathlib import Path

KNOWN_DEFAULTS = {
    "MSGFN": "005", "SPRAS": "E", "SPRAS_ISO": "EN", "PSTAT": "K",
    "GEWEI": "KG", "MEINS": "EA",   # dimension-specific units (blind 1st-row is wrong)
}

# learned recipes live here (one json per object)
LEARNED_DIR = Path(__file__).resolve().parents[2] / "local-staging" / "m4h-local" / "recipes_learned"


class MetaRecipeResolver:
    def __init__(self, conn):
        self.c = conn
        self._fieldinfo: dict = {}   # (table,field) -> {checktable,leng,datatype}
        self._keyfield: dict = {}    # checktable -> meaningful key field
        self._ckvalue: dict = {}     # checktable -> first valid value

    # ── DDIC helpers ────────────────────────────────────────────────────────
    def _field_info(self, table: str, field: str) -> dict:
        key = (table.upper(), field.upper())
        if key in self._fieldinfo:
            return self._fieldinfo[key]
        info = {"checktable": "", "leng": 0, "datatype": ""}
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="DD03L", DELIMITER="|",
                            OPTIONS=[{"TEXT": f"TABNAME = '{table.upper()}' AND FIELDNAME = '{field.upper()}'"}],
                            FIELDS=[{"FIELDNAME": "CHECKTABLE"}, {"FIELDNAME": "LENG"},
                                    {"FIELDNAME": "DATATYPE"}], ROWCOUNT=1)
            if r.get("DATA"):
                v = [p.strip() for p in r["DATA"][0]["WA"].split("|")]
                ct = v[0]
                info = {"checktable": ct if ct and ct != "*" else "",
                        "leng": int(v[1] or 0), "datatype": v[2]}
        except Exception:
            pass
        self._fieldinfo[key] = info
        return info

    def _checktable_keyfield(self, checktable: str) -> str:
        if checktable in self._keyfield:
            return self._keyfield[checktable]
        kf = ""
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE="DD03L", DELIMITER="|",
                            OPTIONS=[{"TEXT": f"TABNAME = '{checktable}' AND KEYFLAG = 'X'"}],
                            FIELDS=[{"FIELDNAME": "FIELDNAME"}, {"FIELDNAME": "POSITION"}], ROWCOUNT=20)
            keys = sorted(([p.strip() for p in d["WA"].split("|")] for d in r.get("DATA", [])),
                          key=lambda x: int(x[1] or 0))
            # last non-MANDT/non-language key = the meaningful code
            names = [k[0] for k in keys if k[0] not in ("MANDT", "SPRAS", "LANGU")]
            kf = names[-1] if names else (keys[-1][0] if keys else "")
        except Exception:
            pass
        self._keyfield[checktable] = kf
        return kf

    def _value_exists(self, checktable: str, value: str) -> bool:
        """Is `value` a valid key in the check table?"""
        kf = self._checktable_keyfield(checktable)
        if not kf:
            return False
        try:
            r = self.c.call("RFC_READ_TABLE", QUERY_TABLE=checktable, DELIMITER="|",
                            OPTIONS=[{"TEXT": f"{kf} = '{value}'"}],
                            FIELDS=[{"FIELDNAME": kf}], ROWCOUNT=1)
            return bool(r.get("DATA"))
        except Exception:
            return False

    def _checktable_value(self, checktable: str) -> str:
        if checktable in self._ckvalue:
            return self._ckvalue[checktable]
        val = ""
        kf = self._checktable_keyfield(checktable)
        if kf:
            try:
                r = self.c.call("RFC_READ_TABLE", QUERY_TABLE=checktable, DELIMITER="|",
                                FIELDS=[{"FIELDNAME": kf}], ROWCOUNT=1)
                if r.get("DATA"):
                    val = r["DATA"][0]["WA"].split("|")[0].strip()
            except Exception:
                pass
        self._ckvalue[checktable] = val
        return val

    # ── public: resolve one field ───────────────────────────────────────────
    def resolve(self, app_table: str, field: str, source_row: dict = None) -> dict:
        source_row = source_row or {}
        info = self._field_info(app_table, field)
        ct = info.get("checktable")
        src = source_row.get(field)

        # 1. source value — faithful — IF valid (validate against check table)
        if src:
            if not ct or self._value_exists(ct, src):
                return {"field": field, "value": src, "via": "source_row"}
            # source value not valid on target -> fall through to a valid substitute

        # 2. known default — if valid against the check table
        d = KNOWN_DEFAULTS.get(field.upper())
        if d and (not ct or self._value_exists(ct, d)):
            return {"field": field, "value": d, "via": "default"}

        # 3. a valid value from the target's own config
        if ct:
            v = self._checktable_value(ct)
            if v:
                via = "checktable_substitute" if src else f"checktable:{ct}"
                return {"field": field, "value": v, "via": via}
        return {"field": field, "value": None, "via": "unresolved"}


# ── learned-recipe persistence ───────────────────────────────────────────────
def load_learned(object_name: str) -> dict:
    p = LEARNED_DIR / f"{object_name}.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return {}
    return {}


def save_learned(object_name: str, recipe: dict) -> None:
    LEARNED_DIR.mkdir(parents=True, exist_ok=True)
    (LEARNED_DIR / f"{object_name}.json").write_text(json.dumps(recipe, indent=2))
