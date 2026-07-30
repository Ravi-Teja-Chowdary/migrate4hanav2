"""
object_catalog — read the Migration Cockpit's authoritative object registry.

The MC staging-tables approach records every mass-transfer → object → structure →
staging-table binding in HANA table `/1LT/DS_MAPPING` (cols SYS_ID, MT_ID,
COBJ_IDENT, STRUCT_IDENT, STAGING_TAB). This is the catalog we long reverse-
engineered by column signature: it tells us, per migration project (MT_ID), the
exact staging table for every object's every structure — no signature guessing.

Read over RFC (as the ABAP user) because the external HANA SYSTEM user has no
SELECT grant on the SAPHANADB-owned `/1LT/` tables (privilege 258); RFC_READ_TABLE
goes through the ABAP layer where the schema-owner privilege applies.

    from object_catalog import Catalog
    cat = Catalog(engine)              # engine = migration_engine.Engine()
    cat.mass_transfers()               # -> {'M02': 230, 'M01': 7, ...}
    objs = cat.objects("M02")          # -> {obj_ident: [(struct_ident, staging_tab), ...]}
    tab  = cat.primary_table("M02", "Z_BANK_2_M02")   # -> '/1LT/DSS4H000120'
"""
from collections import defaultdict

MAPPING_TABLE = "/1LT/DS_MAPPING"


class Catalog:
    def __init__(self, engine):
        self.eng = engine
        self._rows = None

    def _load(self):
        if self._rows is None:
            self._rows = self.eng.read_table(
                self.eng.tgt, MAPPING_TABLE,
                ["MT_ID", "COBJ_IDENT", "STRUCT_IDENT", "STAGING_TAB"])
        return self._rows

    def mass_transfers(self):
        counts = defaultdict(set)
        for r in self._load():
            counts[r["MT_ID"].strip()].add(r["COBJ_IDENT"].strip())
        return {mt: len(objs) for mt, objs in sorted(counts.items())}

    def objects(self, mt_id):
        """{object_ident: [(struct_ident, staging_table), ...]} in staging-table order."""
        by_obj = defaultdict(list)
        for r in self._load():
            if r["MT_ID"].strip() != mt_id:
                continue
            by_obj[r["COBJ_IDENT"].strip()].append(
                (r["STRUCT_IDENT"].strip(), r["STAGING_TAB"].strip()))
        for obj in by_obj:
            by_obj[obj].sort(key=lambda t: t[1])  # by staging-table number
        return dict(by_obj)

    def structures(self, mt_id, obj_ident):
        return self.objects(mt_id).get(obj_ident, [])

    def primary(self, mt_id, obj_ident):
        """(struct_ident, staging_table) of the object's first/header structure."""
        sts = self.structures(mt_id, obj_ident)
        return sts[0] if sts else (None, None)

    def primary_table(self, mt_id, obj_ident):
        return self.primary(mt_id, obj_ident)[1]


if __name__ == "__main__":
    import sys, json, os
    sys.path.insert(0, os.getcwd())
    sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))
    from migration_engine import Engine
    eng = Engine()
    try:
        cat = Catalog(eng)
        print("mass transfers:", json.dumps(cat.mass_transfers(), indent=2))
        mt = sys.argv[1] if len(sys.argv) > 1 else "M02"
        objs = cat.objects(mt)
        print(f"\n{mt}: {len(objs)} objects")
        for obj in sorted(objs):
            ps, pt = cat.primary(mt, obj)
            print(f"  {obj:<26} {ps:<24} {pt}  (+{len(objs[obj]) - 1} more structs)")
    finally:
        eng.close()
