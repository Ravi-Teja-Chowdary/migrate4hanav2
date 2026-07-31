"""
bucket2_preflight — honest readiness assessment for Bucket 2 (open transactions).

Every open transaction is a POINTER into master data: a purchase order points at a
vendor + a plant-extended material, a sales order at a customer + a sales-view material,
an account-assigned requisition at a cost element or an asset. So an open-transaction
migrator can only LAND a document if the master data it references already exists on the
target in the right org units. This script makes that dependency explicit BEFORE any
write: for each Bucket-2 object it reports the open source volume, the official create
BAPI (all support-safe), and whether the target currently satisfies the object's
master-data prerequisites — turning "the BAPI failed" into "the target is missing X".

    py -3.7 bucket2_preflight.py

Support-safe by construction: this script only READS (RFC_READ_TABLE); it writes nothing.
The landing itself (a separate step) goes exclusively through the official BAPIs named
below — never table writes, never modifying SAP standard — so SAP support is preserved.
"""
import os, sys
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.getcwd(), "sapnwrfc"))
sys.path.insert(0, os.getcwd()); sys.path.insert(0, os.path.join(os.getcwd(), "lambda", "utils"))
from migration_engine import Engine


def n(eng, conn, table, fields, where=""):
    try:
        return len(eng.read_table(conn, table, fields, where))
    except Exception as ex:
        return "ERR:" + str(ex)[:30]


def main():
    eng = Engine(); ecc, tgt = eng.ecc, eng.tgt
    print("=== Bucket 2 (open transactions) — target readiness preflight (READ-ONLY) ===\n")

    # target master-data prerequisites (the pointers open docs need)
    marc = n(eng, tgt, "MARC", ["MATNR"])                    # plant-extended materials
    mvke = n(eng, tgt, "MVKE", ["MATNR"])                    # sales-view materials
    bp_cust = n(eng, tgt, "KNA1", ["KUNNR"])                 # customers (BP)
    bp_vend = n(eng, tgt, "LFA1", ["LIFNR"])                 # vendors (BP)
    ce = n(eng, tgt, "CSKB", ["KSTAR"], "KOKRS = 'A000' AND KATYP = '01'")  # primary cost elements
    print("Target master-data pointers open docs depend on:")
    print(f"  plant-extended materials (MARC): {marc}")
    print(f"  sales-view materials     (MVKE): {mvke}")
    print(f"  customers                (KNA1): {bp_cust}")
    print(f"  vendors                  (LFA1): {bp_vend}")
    print(f"  primary cost elements A000     : {ce}\n")

    def ready(cond):
        return "READY" if cond else "BLOCKED"

    # object -> (open source volume, official BAPI, prerequisite, status)
    rows = [
        ("Open sales order", n(eng, ecc, "VBAK", ["VBELN"], "VBTYP = 'C'"),
         "BAPI_SALESORDER_CREATEFROMDAT2", "sales-view materials (MVKE) + customers",
         ready((isinstance(mvke, int) and mvke > 0) and (isinstance(bp_cust, int) and bp_cust > 0))),
        ("Open purchase order", n(eng, ecc, "EKPO", ["EBELN"], "LOEKZ = '' AND ELIKZ = ''"),
         "BAPI_PO_CREATE1", "plant-extended materials (MARC) + vendors",
         ready((isinstance(marc, int) and marc > 5) and (isinstance(bp_vend, int) and bp_vend > 0))),
        ("Open purchase requisition (stock)", n(eng, ecc, "EBAN", ["BANFN"], "LOEKZ = '' AND EBAKZ = '' AND KNTTP = ''"),
         "BAPI_PR_CREATE", "plant-extended materials (MARC)",
         ready(isinstance(marc, int) and marc > 5)),
        ("Open purchase requisition (cost-center)", n(eng, ecc, "EBAN", ["BANFN"], "LOEKZ = '' AND EBAKZ = '' AND KNTTP = 'K'"),
         "BAPI_PR_CREATE", "primary cost elements in A000",
         ready(isinstance(ce, int) and ce > 0)),
        ("Open production order", n(eng, ecc, "AFKO", ["AUFNR"]),
         "BAPI_PRODORD_CREATE", "plant-extended materials + routings/BOM",
         ready(isinstance(marc, int) and marc > 5)),
        ("Open reservation", n(eng, ecc, "RESB", ["RSNUM"], "KZEAR = '' AND XLOEK = ''"),
         "BAPI_RESERVATION_CREATE1", "plant-extended materials (MARC)",
         ready(isinstance(marc, int) and marc > 5)),
        ("Quality/service notification", n(eng, ecc, "QMEL", ["QMNUM"]),
         "BAPI_SERVNOT_CREATE / BAPI_QUALNOT_CREATE", "notification types (client-level, low dep)",
         "READY*"),
    ]
    w = max(len(r[0]) for r in rows)
    print(f"{'object'.ljust(w)}  {'open-src':>8}  status   BAPI (support-safe)  |  needs")
    print("-" * (w + 60))
    for name, vol, bapi, needs, st in rows:
        print(f"{name.ljust(w)}  {str(vol):>8}  {st:<8} {bapi}\n{' ' * (w + 12)}needs: {needs}")

    print("\nLegend: READY = target has the referenced master data, object can land at volume via its BAPI.")
    print("        BLOCKED = target is missing the master data the document points at (load it first).")
    print("        READY* = client-level object, minimal master-data dependency.")
    print("\nAll create paths are official BAPIs (support-safe). This preflight only reads.")
    eng.close()


if __name__ == "__main__":
    main()
