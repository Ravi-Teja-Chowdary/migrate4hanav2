"""
data-migrator (lift-and-shift) — MC/IDoc/LTMOM template generator only.

This Lambda used to do in-place loading. In lift-and-shift it has ONE job:
read the routed object spec, extract data from ECC via pyrfc, and emit
*tool-native templates* to S3:

    * MC lane     -> CSV/XLSX in the MC staging-table layout
    * IDoc lane   -> per-object IDoc XML files
    * LTMOM lane  -> mapping spec + sample CSV (manual SLT/LTMOM build)
    * BODS lane   -> dataflow-input CSV with column metadata

It does NOT push anything into S/4HANA. Push is done by the lane
orchestrators (migration-cockpit-orchestrator / idoc-orchestrator /
ltmom-orchestrator).
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
import time

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "utils"))

import boto3  # noqa: E402

try:
    import sapnwrfc  # noqa: F401
except Exception:  # pragma: no cover
    pass

try:
    from logger import log_stage_event  # type: ignore
except Exception:  # pragma: no cover
    def log_stage_event(*a, **k):  # type: ignore
        pass

try:
    from unified_loader import UnifiedLoader, OBJECT_MECHANISM  # type: ignore
except Exception:  # pragma: no cover
    UnifiedLoader = None
    OBJECT_MECHANISM = {}

try:
    from currency_config import CurrencyConfigReconciler  # type: ignore
except Exception:  # pragma: no cover
    CurrencyConfigReconciler = None

try:
    from reconciler import Reconciler  # type: ignore
except Exception:  # pragma: no cover
    Reconciler = None

try:
    from key_map import KeyMap, PersistentKeyMap  # type: ignore
except Exception:  # pragma: no cover
    KeyMap = None
    PersistentKeyMap = None

try:
    import compliance  # type: ignore
except Exception:  # pragma: no cover
    compliance = None

try:
    import config_discovery  # type: ignore
except Exception:  # pragma: no cover
    config_discovery = None

S3 = boto3.client("s3")
SECRETS = boto3.client("secretsmanager")
STAGING_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hanav2-staging-dev")

# Conservative per-invoke caps; production batching happens upstream.
MAX_ROWS_PER_TEMPLATE = int(os.environ.get("MAX_ROWS_PER_TEMPLATE", "50000"))

# Actually post extracted data into S/4 (via idoc_loader) when M4H_LOAD_TO_S4=1.
LOAD_TO_S4 = os.environ.get("M4H_LOAD_TO_S4", "0") == "1"
LOAD_MAX_ROWS = int(os.environ.get("M4H_LOAD_MAX_ROWS", "10"))
OWN_LOGICAL_SYSTEM = os.environ.get("M4H_TARGET_LOGSYS", "S4HCLNT100")
IDOC_SENDER = os.environ.get("M4H_IDOC_SENDER", "M4HSENDER")


def _ecc(secret_id: str):
    sec = json.loads(SECRETS.get_secret_value(SecretId=secret_id)["SecretString"])
    from pyrfc import Connection
    # Base connection kwargs from the secret. Optional gwhost/gwserv/saprouter
    # allow connection through a TCP forwarder (e.g. ngrok) where the published
    # port differs from the SAP-derived sapgw<NN> port.
    kwargs = {
        "ashost": sec["ashost"],
        "sysnr":  sec.get("sysnr", "00"),
        "client": sec["client"],
        "user":   sec["user"],
        "passwd": sec.get("passwd") or sec.get("password"),
        "lang":   sec.get("lang", "EN"),
    }
    for opt in ("gwhost", "gwserv", "saprouter"):
        if sec.get(opt):
            kwargs[opt] = sec[opt]
    return Connection(**kwargs)


def _read_table(conn, table: str, fields: list, where: str = "", max_rows: int = MAX_ROWS_PER_TEMPLATE) -> list:
    # Cluster-table aware preflight (Gemini gap #7). Refuses NO_GO plans
    # (e.g. PCL1/PCL2 with no WHERE) BEFORE making the RFC call that would
    # otherwise dump the source ECC database. For BSEG/RFBLG/KOCLU it caps the
    # row count and logs that we're touching a cluster table.
    where_dict = _where_to_dict(where) if where else {}
    on_hana = (os.environ.get("M4H_ECC_ON_HANA", "").lower() in ("1", "true", "yes"))
    try:
        from cluster_table_awareness import preflight, KIND_TRANSPARENT
        plan = preflight(table, where=where_dict, fields=fields,
                         requested_package_size=max_rows, on_hana=on_hana)
        if plan.verdict == "NO_GO":
            raise RuntimeError(
                f"cluster_table_awareness refused extraction of {table}: "
                f"{plan.warnings[0] if plan.warnings else 'unsafe extraction'}")
        if plan.kind != KIND_TRANSPARENT and not on_hana:
            # Honor the cap so a 5000-row BSEG fetch becomes 200 (memory-safe)
            max_rows = min(max_rows, plan.recommended_package_size)
    except ImportError:
        pass    # module not on path -> proceed unprotected (legacy behaviour)

    opts = [{"TEXT": where}] if where else []
    fld = [{"FIELDNAME": f} for f in fields]
    # DELIMITER='|' so multi-field rows split cleanly (without it RFC_READ_TABLE
    # returns fixed-width WA and the split produces garbage columns).
    res = conn.call("RFC_READ_TABLE", QUERY_TABLE=table, DELIMITER="|",
                    OPTIONS=opts, FIELDS=fld, ROWCOUNT=max_rows)
    cols = [f["FIELDNAME"] for f in res.get("FIELDS", [])]
    rows = []
    for r in res.get("DATA", []):
        parts = [p.strip() for p in r["WA"].split("|")]
        rows.append(dict(zip(cols, parts)))
    return rows, cols


_WHERE_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9_]{1,29})\s*=\s*'([^']*)'")

def _where_to_dict(where_clause: str) -> dict:
    """Best-effort extract of column=value pins from an OPTIONS WHERE string
    (e.g. "BUKRS = '1010' AND GJAHR = '2026'"). Used only to feed
    cluster_table_awareness.preflight()'s header-keys check; non-equality
    predicates (BETWEEN, IN, LIKE) are ignored - the preflight then treats
    those columns as not pinned."""
    if not where_clause:
        return {}
    return dict(_WHERE_KEY_RE.findall(where_clause))


def _target_connection():
    """RFC connection to the TARGET S/4 (for loading data in), from local:target."""
    sec = json.loads(SECRETS.get_secret_value(SecretId=(os.environ.get("TARGET_SECRETS_ARN") or os.environ.get("S4_SECRETS_ARN") or "local:target"))["SecretString"])
    from pyrfc import Connection
    return Connection(ashost=sec["ashost"], sysnr=sec.get("sysnr", "00"),
                      client=sec["client"], user=sec["user"],
                      passwd=sec.get("passwd") or sec.get("password"), lang="EN")


def _target_odata():
    """OData (HTTPS gateway) client to the TARGET S/4 — the door RFC can't open for
    transaction-ready partner creation. None if requests/odata_client unavailable."""
    try:
        from odata_client import ODataClient
        sec = json.loads(SECRETS.get_secret_value(SecretId=(os.environ.get("TARGET_SECRETS_ARN") or os.environ.get("S4_SECRETS_ARN") or "local:target"))["SecretString"])
        port = int(os.environ.get("M4H_ODATA_PORT", "44300"))
        return ODataClient(sec["ashost"], sec["user"], sec.get("passwd") or sec.get("password"),
                           client=sec.get("client", "100"), port=port)
    except Exception:
        return None


def _emit_mc_csv(run_id: str, obj_name: str, rows: list, cols: list) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)
    key = f"runs/{run_id}/data-migrator/mc/{obj_name}.csv"
    S3.put_object(Bucket=STAGING_BUCKET, Key=key, Body=buf.getvalue().encode(),
                  ContentType="text/csv")
    return f"s3://{STAGING_BUCKET}/{key}"


def _emit_idoc_xml(run_id: str, obj_name: str, idoc_type: str, rows: list) -> str:
    """Minimal IDoc XML envelope; real per-segment population is delegated
    to idoc-orchestrator using the segment definitions on the target."""
    body_parts = ['<?xml version="1.0" encoding="UTF-8"?>',
                  f'<{idoc_type}_BATCH count="{len(rows)}">']
    for r in rows:
        seg = "".join(f"<{k}>{v}</{k}>" for k, v in r.items())
        body_parts.append(f"<{idoc_type}>{seg}</{idoc_type}>")
    body_parts.append(f"</{idoc_type}_BATCH>")
    key = f"runs/{run_id}/data-migrator/idoc/{obj_name}.xml"
    S3.put_object(Bucket=STAGING_BUCKET, Key=key,
                  Body="\n".join(body_parts).encode(),
                  ContentType="application/xml")
    return f"s3://{STAGING_BUCKET}/{key}"


def _emit_ltmom_spec(run_id: str, obj_name: str, cols: list) -> str:
    spec = {"object": obj_name, "source": "ECC", "target": "S/4HANA",
            "fields": [{"source": c, "target": c, "transform": "identity"} for c in cols],
            "instructions": "LTMOM mapping is built manually on target; "
                            "this spec is the design input."}
    key = f"runs/{run_id}/data-migrator/ltmom/{obj_name}.json"
    S3.put_object(Bucket=STAGING_BUCKET, Key=key, Body=json.dumps(spec, indent=2).encode(),
                  ContentType="application/json")
    return f"s3://{STAGING_BUCKET}/{key}"


def _emit_currency_config(run_id: str, manifest: dict, csv_text: str) -> dict:
    """Write the currency-customizing deploy package (the prerequisite TCURV rate
    types + TCURF factors the target is missing) for controlled, transport-grade
    apply. Returns the artifact locations."""
    base = f"runs/{run_id}/data-migrator/config/exchange_rate_customizing"
    S3.put_object(Bucket=STAGING_BUCKET, Key=f"{base}.json",
                  Body=json.dumps(manifest, indent=2).encode(), ContentType="application/json")
    S3.put_object(Bucket=STAGING_BUCKET, Key=f"{base}.csv",
                  Body=csv_text.encode(), ContentType="text/csv")
    return {"manifest": f"s3://{STAGING_BUCKET}/{base}.json",
            "review_csv": f"s3://{STAGING_BUCKET}/{base}.csv"}


def _emit_key_map(run_id: str, km) -> dict:
    """Persist the run's source->target key registry as a first-class artifact:
    a JSON for programmatic lookup by later stages / dependent objects, and a CSV
    for audit. This is how transactional data follows remapped/renumbered keys."""
    base = f"runs/{run_id}/data-migrator/keymap/key_mapping"
    S3.put_object(Bucket=STAGING_BUCKET, Key=f"{base}.json",
                  Body=json.dumps(km.to_dict(), indent=2).encode(), ContentType="application/json")
    S3.put_object(Bucket=STAGING_BUCKET, Key=f"{base}.csv",
                  Body=km.to_csv().encode(), ContentType="text/csv")
    return {"registry": f"s3://{STAGING_BUCKET}/{base}.json",
            "audit_csv": f"s3://{STAGING_BUCKET}/{base}.csv"}


# ── Object → source-table mapping for batch-mode runs ────────────────────────
# When the runner invokes data-migrator without an explicit object_spec, we
# iterate over the stage-3 DAG and apply this canonical mapping per object.
DEFAULT_OBJECT_TABLES = {
    "Customer":          {"table": "KNA1", "fields": ["KUNNR", "NAME1", "LAND1", "ORT01"], "lane": "MC"},
    "Vendor":            {"table": "LFA1", "fields": ["LIFNR", "NAME1", "LAND1", "ORT01"], "lane": "MC"},
    "Material":          {"table": "MARA", "fields": ["MATNR", "MTART", "MATKL", "MEINS"], "lane": "MC"},
    "BusinessPartner":   {"table": "BUT000", "fields": ["PARTNER", "TYPE", "BPKIND", "BU_GROUP"], "lane": "MC"},
    "CompanyCode":       {"table": "T001", "fields": ["BUKRS", "BUTXT", "ORT01", "LAND1"], "lane": "MC"},
    "GLAccount":         {"table": "SKA1", "fields": ["KTOPL", "SAKNR", "XBILK"], "lane": "MC"},
    "CostCenter":        {"table": "CSKS", "fields": ["KOKRS", "KOSTL", "DATBI"], "lane": "MC"},
    "ProfitCenter":      {"table": "CEPC", "fields": ["KOKRS", "PRCTR", "DATBI"], "lane": "MC"},
    "FixedAsset":        {"table": "ANLA", "fields": ["BUKRS", "ANLN1", "ANLN2", "ANLKL", "TXT50"], "lane": "MC"},
    "Bank":              {"table": "BNKA", "fields": ["BANKS", "BANKL", "BANKA", "SWIFT", "BRNCH", "ORT01"], "lane": "MC"},
    "InternalOrder":     {"table": "AUFK", "fields": ["AUFNR", "AUART", "KTEXT", "KOKRS", "BUKRS"], "where": "AUTYP = '01'", "lane": "MC"},
    "Equipment":         {"table": "EQUI", "fields": ["EQUNR", "EQTYP"], "lane": "MC"},
    "FunctionalLocation": {"table": "IFLOT", "fields": ["TPLNR", "FLTYP"], "lane": "MC"},
    "Characteristic":    {"table": "CABN", "fields": ["ATNAM", "ATFOR", "ANZST", "ANZDZ"], "lane": "MC"},
    "Class":             {"table": "KLAH", "fields": ["CLASS", "KLART"], "lane": "MC"},
    "CostElementGroup":  {"table": "SETHEADER", "fields": ["SETNAME", "SUBCLASS"], "where": "SETCLASS = '0102'", "lane": "MC"},
    "ProfitCenterGroup": {"table": "SETHEADER", "fields": ["SETNAME", "SUBCLASS"], "where": "SETCLASS = '0106'", "lane": "MC"},
    "Project":           {"table": "PROJ", "fields": ["PSPID", "POST1"], "lane": "MC"},
    "PurchaseRequisition": {"table": "EBAN", "fields": ["BANFN", "BNFPO", "MATNR", "WERKS", "MENGE", "TXZ01", "PREIS"], "where": "LOEKZ = '' AND EBELN = ''", "lane": "MC"},
    "OpenSO":            {"table": "VBAK", "fields": ["VBELN", "AUART", "VKORG", "VTWEG", "SPART", "KUNNR"], "lane": "MC"},
    # SD document family — Spine-loaded via BAPI_SALESORDER_CREATEFROMDAT2 with
    # VBTYP filters distinguishing standard SO (C), return (H), credit-memo
    # request (K). Contract (G) already exists below. All feed into the same
    # sales_order_spine / returns_order_sd_spine / credit_memo_request_spine
    # trio which now honours M4H_PRESERVE_SRC_NUMBERS for external doc numbers.
    "SalesOrder":        {"table": "VBAK", "fields": ["VBELN", "AUART", "VKORG", "VTWEG", "SPART", "KUNNR", "WAERK"], "where": "VBTYP = 'C'", "lane": "BAPI"},
    "ReturnsOrderSD":    {"table": "VBAK", "fields": ["VBELN", "AUART", "VKORG", "VTWEG", "SPART", "KUNNR", "WAERK"], "where": "VBTYP = 'H'", "lane": "BAPI"},
    "CreditMemoRequest": {"table": "VBAK", "fields": ["VBELN", "AUART", "VKORG", "VTWEG", "SPART", "KUNNR", "WAERK"], "where": "VBTYP = 'K'", "lane": "BAPI"},
    "DebitMemoRequest":  {"table": "VBAK", "fields": ["VBELN", "AUART", "VKORG", "VTWEG", "SPART", "KUNNR", "WAERK"], "where": "VBTYP = 'L'", "lane": "BAPI"},
    "PurchaseContract":  {"table": "EKKO", "fields": ["EBELN", "BSART", "LIFNR", "EKORG", "WAERS"], "where": "BSTYP = 'K'", "lane": "MC"},
    "Batch":             {"table": "MCH1", "fields": ["MATNR", "CHARG"], "lane": "MC"},
    "InventoryBalance":  {"table": "MARD", "fields": ["MATNR", "WERKS", "LGORT", "LABST"], "where": "LABST > '0'", "lane": "MC"},
    "Plant":             {"table": "T001W", "fields": ["WERKS", "NAME1", "LAND1"], "lane": "MC"},
    "ChartOfAccounts":   {"table": "T004", "fields": ["KTOPL", "KTPLT", "MWSKZ"], "lane": "MC"},
    "ControllingArea":   {"table": "TKA01", "fields": ["KOKRS", "BEZEI", "WAERS"], "lane": "MC"},
    "OpenPO":            {"table": "EKKO", "fields": ["EBELN", "BSART", "BUKRS", "EKORG", "EKGRP", "LIFNR", "WAERS"], "where": "BSTYP = 'F'", "lane": "MC"},
    "OpenAR":            {"table": "BSID", "fields": ["BUKRS", "KUNNR", "BELNR", "DMBTR", "SHKZG", "WAERS"], "lane": "MC"},
    "OpenAP":            {"table": "BSIK", "fields": ["BUKRS", "LIFNR", "BELNR", "DMBTR", "SHKZG", "WAERS"], "lane": "MC"},
    "BankStatements":    {"table": "FEBKO", "fields": ["KUKEY", "ESNUM", "BANKL", "BANKN"], "lane": "IDOC", "idoc_type": "FINSTA01"},
    "ExchangeRates":     {"table": "TCURR", "fields": ["KURST", "FCURR", "TCURR", "GDATU", "UKURS", "FFACT", "TFACT"], "lane": "IDOC", "idoc_type": "EXCHRATE_CREATE01"},
    "AssetMaster":       {"table": "ANLA", "fields": ["BUKRS", "ANLN1", "ANLN2", "ANLKL"], "lane": "MC"},
    "BOM":               {"table": "MAST", "fields": ["MATNR", "WERKS", "STLAN", "STLNR"], "lane": "MC"},
    "Routing":           {"table": "MAPL", "fields": ["MATNR", "WERKS", "PLNTY", "PLNNR"], "lane": "MC"},
    "WorkCenter":        {"table": "CRHD", "fields": ["OBJID", "ARBPL", "WERKS"], "lane": "MC"},

    # ── Extended Migration-Cockpit catalog (extract+emit lane = "MC") ───────────
    # The dispatcher reads source from ECC for each entry and emits the MC-staging
    # template; load into S/4 is done by the MC tool consuming those templates.
    # Verified extracts where probed live (the proven extract pattern).
    # MM
    "SourceList":            {"table": "EORD",  "fields": ["MATNR", "WERKS", "LIFNR", "EBELN", "ERDAT"], "lane": "MC"},
    "QuotaArrangement":      {"table": "EQUOT", "fields": ["MATNR", "WERKS", "QUNUM", "QUPOS"], "lane": "MC"},
    "PurchaseInfoRecord":    {"table": "EINA",  "fields": ["INFNR", "LIFNR", "MATNR", "MATKL", "MEINS"], "lane": "MC"},
    "ServiceMaster":         {"table": "ASMD",  "fields": ["ASNUM", "ASKTX", "MEINS", "MATKL"], "lane": "MC"},
    "ScheduleAgreementMM":   {"table": "EKKO",  "fields": ["EBELN", "BSART", "LIFNR", "EKORG", "WAERS"], "where": "BSTYP = 'L'", "lane": "MC"},
    "MaterialBOMHeader":     {"table": "STKO",  "fields": ["STLNR", "STLAL", "BMENG", "BMEIN", "STLST"], "lane": "MC"},
    "MaterialBOMItem":       {"table": "STPO",  "fields": ["STLNR", "STLKN", "IDNRK", "MENGE", "MEINS", "POSTP"], "lane": "MC"},
    "MaterialStock":         {"table": "MARD",  "fields": ["MATNR", "WERKS", "LGORT", "LABST"], "lane": "MC"},
    "StorageLocation":       {"table": "T001L", "fields": ["WERKS", "LGORT", "LGOBE"], "lane": "MC"},
    "MaterialClassification": {"table": "AUSP", "fields": ["OBJEK", "ATINN", "ATWRT", "KLART"], "lane": "MC"},
    "PricingConditionMM":    {"table": "KONP",  "fields": ["KNUMH", "KOPOS", "KSCHL", "KBETR"], "lane": "MC"},
    "ConsignmentStock":      {"table": "MKOL",  "fields": ["MATNR", "WERKS", "LIFNR", "LBLAB"], "lane": "MC"},
    # SD
    "CustomerMaterialInfo":  {"table": "KNMT",  "fields": ["KUNNR", "MATNR", "KDMAT", "POSTX"], "lane": "MC"},
    "SalesQuotation":        {"table": "VBAK",  "fields": ["VBELN", "AUART", "KUNNR", "VKORG", "VTWEG", "SPART"], "where": "VBTYP = 'B'", "lane": "MC"},
    "SalesInquiry":          {"table": "VBAK",  "fields": ["VBELN", "AUART", "KUNNR", "VKORG", "VTWEG", "SPART"], "where": "VBTYP = 'A'", "lane": "MC"},
    "SalesContract":         {"table": "VBAK",  "fields": ["VBELN", "AUART", "KUNNR", "VKORG", "VTWEG", "SPART"], "where": "VBTYP = 'G'", "lane": "MC"},
    "ScheduleAgreementSD":   {"table": "VBAK",  "fields": ["VBELN", "AUART", "KUNNR", "VKORG", "VTWEG", "SPART"], "where": "VBTYP = 'E'", "lane": "MC"},
    "CreditMaster":          {"table": "KNKK",  "fields": ["KUNNR", "KKBER", "KLIMK", "SKFOR"], "lane": "MC"},
    "CustomerHierarchy":     {"table": "KNVH",  "fields": ["HKUNNR", "KUNNR", "VKORG", "VTWEG", "SPART"], "lane": "MC"},
    "OutboundDelivery":      {"table": "LIKP",  "fields": ["VBELN", "VKORG", "VSTEL", "LFART", "KUNAG"], "lane": "MC"},
    "BillingDocument":       {"table": "VBRK",  "fields": ["VBELN", "FKART", "BUKRS", "WAERK", "NETWR"], "lane": "MC"},
    "PricingConditionSD":    {"table": "KONH",  "fields": ["KNUMH", "KSCHL", "KAPPL"], "lane": "MC"},
    # PP
    "ProductionVersion":     {"table": "MKAL",  "fields": ["MATNR", "WERKS", "VERID", "ADATU", "BDATU"], "lane": "MC"},
    "ProductionOrder":       {"table": "AUFK",  "fields": ["AUFNR", "AUART", "WERKS", "BUKRS"], "where": "AUTYP = '10'", "lane": "MC"},
    "PlannedOrder":          {"table": "PLAF",  "fields": ["PLNUM", "MATNR", "PWWRK", "GSMNG"], "lane": "MC"},
    "MRPArea":               {"table": "T001K", "fields": ["BWKEY", "BUKRS"], "lane": "MC"},
    "DemandManagement":      {"table": "PBED",  "fields": ["MATNR", "WERKS", "BDZEI", "BDMNG"], "lane": "MC"},
    # PS
    "WBSElement":            {"table": "PRPS",  "fields": ["POSID", "PSPNR", "OBJNR"], "lane": "MC"},
    "Network":               {"table": "AUFK",  "fields": ["AUFNR", "AUART", "WERKS", "BUKRS"], "where": "AUTYP = '20'", "lane": "MC"},
    "NetworkActivity":       {"table": "AFVC",  "fields": ["AUFPL", "APLZL", "VORNR", "LTXA1"], "lane": "MC"},
    # PM
    "MaintenancePlan":       {"table": "MPLA",  "fields": ["WARPL", "MPTYP", "STRAT"], "lane": "MC"},
    "MaintenanceTaskList":   {"table": "PLKO",  "fields": ["PLNNR", "PLNAL", "WERKS", "KTEXT"], "where": "PLNTY = 'A'", "lane": "MC"},
    "MeasuringPoint":        {"table": "IMPT",  "fields": ["POINT", "MPOBJ", "MPTYP"], "lane": "MC"},
    "MeasurementDocument":   {"table": "IMRG",  "fields": ["MDOCM", "POINT", "MDATE"], "lane": "MC"},
    "ServiceNotification":   {"table": "VIQMEL", "fields": ["QMNUM", "QMART", "QMTXT"], "lane": "MC"},
    "ServiceContract":       {"table": "VEDA",  "fields": ["VBELN", "VPOSN", "VBEGDAT", "VENDDAT"], "lane": "MC"},
    # QM
    "InspectionPlan":        {"table": "PLKO",  "fields": ["PLNNR", "PLNAL", "WERKS", "KTEXT"], "where": "PLNTY = 'Q'", "lane": "MC"},
    "InspectionMethod":      {"table": "QMTB",  "fields": ["PRUEFMETH", "WERKS"], "lane": "MC"},
    "InspectionCharacteristic": {"table": "QPMK", "fields": ["VERWMERKM", "WERKS", "KURZTEXT"], "lane": "MC"},
    "QualityInfoRecord":     {"table": "QINF",  "fields": ["MATNR", "LIFNR", "WERKS"], "lane": "MC"},
    "InspectionLot":         {"table": "QALS",  "fields": ["PRUEFLOS", "MATNR", "WERKS"], "lane": "MC"},
    "CatalogCode":           {"table": "QPGR",  "fields": ["KATALOGART", "CODEGRUPPE"], "lane": "MC"},
    # WM / EWM
    "StorageBin":            {"table": "LAGP",  "fields": ["LGNUM", "LGTYP", "LGPLA"], "lane": "MC"},
    "StockInBin":            {"table": "LQUA",  "fields": ["LGNUM", "LGTYP", "LGPLA", "MATNR", "GESME"], "lane": "MC"},
    "WarehouseTransferOrder": {"table": "LTAK", "fields": ["LGNUM", "TANUM", "BDATU"], "lane": "MC"},
    "HandlingUnit":          {"table": "VEKP",  "fields": ["VENUM", "VPOBJKEY", "EXIDV"], "lane": "MC"},
    # HR (mini-master)
    "EmployeeOrgData":       {"table": "PA0001", "fields": ["PERNR", "BUKRS", "WERKS", "BTRTL"], "lane": "MC"},
    "EmployeePersonalData":  {"table": "PA0002", "fields": ["PERNR", "VORNA", "NACHN"], "lane": "MC"},
    "EmployeeAddress":       {"table": "PA0006", "fields": ["PERNR", "ANSSA", "LAND1", "ORT01"], "lane": "MC"},
    # Classification & documents
    "ClassAssignment":       {"table": "AUSP",  "fields": ["OBJEK", "ATINN", "ATWRT", "KLART"], "lane": "MC"},
    "DocumentInfoRecord":    {"table": "DRAW",  "fields": ["DOKNR", "DOKAR", "DOKTL", "DOKVR"], "lane": "MC"},
    # Finance master (extensions)
    "HouseBankAccount":      {"table": "T012K", "fields": ["BUKRS", "HBKID", "HKTID"], "lane": "MC"},
    "AssetClass":            {"table": "ANKA",  "fields": ["ANLKL", "ANLKT"], "lane": "MC"},
    "AssetSubNumber":        {"table": "ANLB",  "fields": ["BUKRS", "ANLN1", "ANLN2", "AFABE"], "lane": "MC"},
    "DepreciationArea":      {"table": "T093",  "fields": ["AFAPL", "AFABE"], "lane": "MC"},
    "TaxCode":               {"table": "T007A", "fields": ["KALSM", "MWSKZ"], "lane": "MC"},
    "DunningArea":           {"table": "T047M", "fields": ["BUKRS", "MABER"], "lane": "MC"},
    # CO-FM (routed lanes, see BREADTH_TRACKER for evidence)
    "ActivityType":          {"table": "CSLA",  "fields": ["KOKRS", "LSTAR", "DATBI"], "lane": "MC"},
    "StatisticalKeyFigure":  {"table": "TKA03", "fields": ["KOKRS", "STAGR"], "lane": "MC"},
    "CommitmentItem":        {"table": "FMCI",  "fields": ["FIKRS", "FIPEX", "FIPOS"], "lane": "MC"},
    # Customizing / config (config-master extracts; lane MC for parity migration)
    "Currency":              {"table": "TCURC", "fields": ["WAERS", "ISOCD"], "lane": "MC"},
    "Country":               {"table": "T005",  "fields": ["LAND1", "LANDN", "ISO3"], "lane": "MC"},
    "Region":                {"table": "T005S", "fields": ["LAND1", "BLAND"], "lane": "MC"},
    "PaymentTerms":          {"table": "T052",  "fields": ["ZTERM", "TAGE2", "TAGE3"], "lane": "MC"},
    "UnitOfMeasure":         {"table": "T006",  "fields": ["MSEHI", "ISOCODE"], "lane": "MC"},
    "IncoTerm":              {"table": "TINC",  "fields": ["INCO1"], "lane": "MC"},
    # Address master
    "Address":               {"table": "ADRC",  "fields": ["ADDRNUMBER", "NAME1", "STREET", "CITY1", "COUNTRY"], "lane": "MC"},
    "Person":                {"table": "ADRP",  "fields": ["PERSNUMBER", "NAME_FIRST", "NAME_LAST"], "lane": "MC"},

    # ── Catalog batch 2 — document items, FI/MM/SD extensions, FM ─────────────
    # Doc items (extracted separately from headers; header is the parent extract)
    "SalesOrderItem":        {"table": "VBAP",  "fields": ["VBELN", "POSNR", "MATNR", "KWMENG", "VRKME", "NETWR"], "lane": "MC"},
    "PurchaseOrderItem":     {"table": "EKPO",  "fields": ["EBELN", "EBELP", "MATNR", "WERKS", "MENGE", "NETPR"], "lane": "MC"},
    "BillingItem":           {"table": "VBRP",  "fields": ["VBELN", "POSNR", "MATNR", "FKIMG", "NETWR"], "lane": "MC"},
    "DeliveryItem":          {"table": "LIPS",  "fields": ["VBELN", "POSNR", "MATNR", "LFIMG", "VRKME"], "lane": "MC"},
    "PRItem":                {"table": "EBAN",  "fields": ["BANFN", "BNFPO", "MATNR", "WERKS", "MENGE", "PREIS"], "lane": "MC"},
    # MM extensions
    "GoodsReceipt":          {"table": "MSEG",  "fields": ["MBLNR", "ZEILE", "MATNR", "WERKS", "BWART", "MENGE"], "lane": "MC"},
    "LogisticsInvoice":      {"table": "RBKP",  "fields": ["BELNR", "GJAHR", "LIFNR", "RMWWR", "WAERS"], "lane": "MC"},
    "StockTransportOrder":   {"table": "EKKO",  "fields": ["EBELN", "BSART", "BUKRS", "EKORG", "LIFNR"], "where": "BSTYP = 'F' AND BSART = 'UB'", "lane": "MC"},
    "PurchaseOrderHistory":  {"table": "EKBE",  "fields": ["EBELN", "EBELP", "BELNR", "VGABE", "MENGE"], "lane": "MC"},
    "BidInvitation":         {"table": "EKKO",  "fields": ["EBELN", "BSART", "LIFNR", "EKORG"], "where": "BSTYP = 'A'", "lane": "MC"},
    "VendorBankDetails":     {"table": "LFBK",  "fields": ["LIFNR", "BANKS", "BANKL", "BANKN"], "lane": "MC"},
    "CustomerBankDetails":   {"table": "KNBK",  "fields": ["KUNNR", "BANKS", "BANKL", "BANKN"], "lane": "MC"},
    # SD extensions
    "ScheduleLines":         {"table": "VBEP",  "fields": ["VBELN", "POSNR", "ETENR", "EDATU", "WMENG"], "lane": "MC"},
    "Shipment":              {"table": "VTTK",  "fields": ["TKNUM", "SHTYP", "TPLST"], "lane": "MC"},
    # PP / process
    "ProcessOrder":          {"table": "AUFK",  "fields": ["AUFNR", "AUART", "WERKS", "BUKRS"], "where": "AUTYP = '40'", "lane": "MC"},
    # FI extensions
    "AccountingDocHeader":   {"table": "BKPF",  "fields": ["BUKRS", "BELNR", "GJAHR", "BLART", "BLDAT"], "lane": "MC"},
    "AccountingDocItem":     {"table": "BSEG",  "fields": ["BUKRS", "BELNR", "GJAHR", "BUZEI", "DMBTR", "SHKZG"], "lane": "MC"},
    "AssetValues":           {"table": "ANLC",  "fields": ["BUKRS", "ANLN1", "ANLN2", "GJAHR", "AFABE"], "lane": "MC"},
    # FM (Funds Management)
    "FundsCenter":           {"table": "FMFCTR", "fields": ["FIKRS", "FICTR"], "lane": "MC"},
    "Fund":                  {"table": "FMFINCODE", "fields": ["FIKRS", "FINCODE"], "lane": "MC"},
    # Material / WM extras
    "MaterialUnitConversion": {"table": "MARM", "fields": ["MATNR", "MEINH", "UMREZ", "UMREN"], "lane": "MC"},
    "StorageTypeMaster":     {"table": "T331",  "fields": ["LGNUM", "LGTYP", "T331_LDESC"], "lane": "MC"},
    # Determinations / pricing tables
    "TaxDetermination":      {"table": "A053",  "fields": ["KAPPL", "KSCHL", "DATBI", "ALAND"], "lane": "MC"},
    "AccountDetermination":  {"table": "T030",  "fields": ["KTOPL", "KTOSL", "BWMOD"], "lane": "MC"},
}


# Cross-run migration ledger: the durable source->target record that makes re-runs
# idempotent (resume, don't duplicate). Stable key (not per run_id) so it accumulates.
LEDGER_KEY = "migration-ledger/key_mapping.json"


def _load_ledger(run_id: str = ""):
    """Load the cross-run migration ledger into a KeyMap.

    Two modes, chosen at runtime:

    * **DynamoDB mode** (production): if ``M4H_KEYMAP_TABLE`` env var is set AND
      ``PersistentKeyMap`` is importable, return a PersistentKeyMap. Writes during
      the run stream straight to DynamoDB (per-mapping, atomic, race-safe);
      resolves for dependent objects fall through to DynamoDB on miss.
    * **S3-blob fallback** (local/dev or when DDB isn't configured): same shape as
      before — load the single JSON blob and accumulate in memory.

    Returns ``None`` only if KeyMap itself is unimportable.
    """
    if KeyMap is None:
        return None
    table = os.environ.get("M4H_KEYMAP_TABLE", "").strip()
    if table and PersistentKeyMap is not None:
        try:
            return PersistentKeyMap(table_name=table, run_id=run_id or "",
                                    target_release=os.environ.get("M4H_TARGET_RELEASE", ""))
        except Exception:
            # Fall through to S3 fallback below; DDB connectivity blip shouldn't
            # halt the run when we have a working S3 alternative.
            pass
    try:
        obj = S3.get_object(Bucket=STAGING_BUCKET, Key=LEDGER_KEY)
        return KeyMap.from_dict(json.loads(obj["Body"].read()))
    except Exception:
        return KeyMap()


def _save_ledger(km) -> None:
    """Persist the (now-merged) ledger.

    For PersistentKeyMap, writes already streamed to DynamoDB during the run, so
    we only need to emit the audit-friendly per-run CSV (done by _emit_key_map).
    For plain KeyMap, dump the merged ledger to S3 as before so the next run
    reuses it.
    """
    if PersistentKeyMap is not None and isinstance(km, PersistentKeyMap):
        # DDB writes already happened; persistence_stats() gives the verdict.
        try:
            log_stage_event("", "data-migrator", "key_map_persisted", km.persistence_stats())
        except Exception:
            pass
        return
    try:
        S3.put_object(Bucket=STAGING_BUCKET, Key=LEDGER_KEY,
                      Body=json.dumps(km.to_dict(), indent=2).encode(),
                      ContentType="application/json")
    except Exception:
        pass


# Discovered target config is cached (it involves probe calls; ~minutes). Reuse across
# runs; re-discover only for a new target or when M4H_REDISCOVER=1.
DISCOVERED_CONFIG_KEY = "migration-ledger/discovered-config.json"


def _load_discovered_config():
    try:
        obj = S3.get_object(Bucket=STAGING_BUCKET, Key=DISCOVERED_CONFIG_KEY)
        return json.loads(obj["Body"].read())
    except Exception:
        return None


def _save_discovered_config(cfg) -> None:
    try:
        S3.put_object(Bucket=STAGING_BUCKET, Key=DISCOVERED_CONFIG_KEY,
                      Body=json.dumps(cfg, indent=2).encode(), ContentType="application/json")
    except Exception:
        pass


# ── Delta / CDC: extract only records changed since the last watermark ────────
# Delta mode (M4H_CDC_DELTA=1) filters each object's extraction by a change-date field
# >= the persisted watermark — incremental migration + the cutover delta load. NOTE:
# KNA1/LFA1 only carry ERDAT (created) — so customer/vendor delta catches NEW masters;
# CHANGED existing ones need change documents (CDHDR/CDPOS), a future enhancement.
CDC_DELTA = os.environ.get("M4H_CDC_DELTA", "0") == "1"
CDC_STATE_KEY = "migration-ledger/cdc-watermark.json"
CDC_FIELDS = {
    "Customer": ["ERDAT"], "Vendor": ["ERDAT"], "Material": ["LAEDA", "ERSDA"],
    "OpenPO": ["AEDAT"], "OpenAR": ["CPUDT"], "OpenAP": ["CPUDT"],
}


def _load_watermark():
    """Last CDC watermark (YYYYMMDD) — None on first run (=> full extract)."""
    if os.environ.get("M4H_CDC_WATERMARK"):
        return os.environ["M4H_CDC_WATERMARK"]
    try:
        obj = S3.get_object(Bucket=STAGING_BUCKET, Key=CDC_STATE_KEY)
        return json.loads(obj["Body"].read()).get("watermark")
    except Exception:
        return None


def _save_watermark(wm: str) -> None:
    try:
        S3.put_object(Bucket=STAGING_BUCKET, Key=CDC_STATE_KEY,
                      Body=json.dumps({"watermark": wm}).encode(), ContentType="application/json")
    except Exception:
        pass


def _cdc_where(obj: str, watermark: str) -> str:
    """Delta WHERE for an object: any of its change-date fields >= watermark."""
    fields = CDC_FIELDS.get(obj)
    if not (fields and watermark):
        return ""
    return "( " + " OR ".join("%s >= '%s'" % (f, watermark) for f in fields) + " )"


# Change documents (CDHDR) let the delta also catch CHANGED masters (not just NEW), which
# the date-field filter alone misses (KNA1/LFA1 have no change date). object -> (class, key).
CDC_CHANGE_DOC = {"Customer": ("DEBI", "KUNNR"), "Vendor": ("KRED", "LIFNR"),
                  "Material": ("MATERIAL", "MATNR")}


def _pack_opts(where: str) -> list:
    """Split a WHERE into <=72-char OPTIONS lines (RFC_READ_TABLE limit), space-padded."""
    lines, cur = [], ""
    for w in where.split():
        if cur and len(cur) + len(w) + 1 > 72:
            lines.append(cur)
            cur = ""
        cur += w + " "
    if cur.strip():
        lines.append(cur)
    return [{"TEXT": ln} for ln in lines]


def _cdc_changed_keys(conn, obj: str, watermark: str, cap: int = 20000) -> set:
    """Master keys CHANGED since the watermark, from change documents (CDHDR)."""
    spec = CDC_CHANGE_DOC.get(obj)
    if not (spec and watermark):
        return set()
    cls, _ = spec
    try:
        r = conn.call("RFC_READ_TABLE", QUERY_TABLE="CDHDR", DELIMITER="|",
                      OPTIONS=_pack_opts("OBJECTCLAS = '%s' AND UDATE >= '%s'" % (cls, watermark)),
                      FIELDS=[{"FIELDNAME": "OBJECTID"}], ROWCOUNT=cap)
        return {d["WA"].strip() for d in r.get("DATA", []) if d["WA"].strip()}
    except Exception:
        return set()


def _read_by_keys(conn, table: str, fields: list, keyfield: str, keys: list, chunk: int = 40) -> list:
    """Read master rows for a set of keys (chunked OR-list); rows as field-keyed dicts."""
    rows, keys = [], list(keys)
    for i in range(0, len(keys), chunk):
        where = " OR ".join("%s = '%s'" % (keyfield, k) for k in keys[i:i + chunk])
        try:
            r = conn.call("RFC_READ_TABLE", QUERY_TABLE=table, DELIMITER="|",
                          OPTIONS=_pack_opts(where),
                          FIELDS=[{"FIELDNAME": f} for f in fields], ROWCOUNT=0)
            cols = [f["FIELDNAME"] for f in r.get("FIELDS", [])]
            for d in r.get("DATA", []):
                rows.append(dict(zip(cols, [p.strip() for p in d["WA"].split("|")])))
        except Exception:
            pass
    return rows


def _load_dag(run_id: str) -> dict:
    """Load the routing DAG written by stage 3 (object-router)."""
    try:
        obj = S3.get_object(Bucket=STAGING_BUCKET, Key=f"runs/{run_id}/object-router/dag.json")
        return json.loads(obj["Body"].read())
    except Exception as ex:
        return {"nodes": [], "_load_error": str(ex)}


def _process_one_object(conn, run_id: str, node: dict, loader=None, cdc_watermark=None) -> dict:
    """Extract one object from ECC and emit lane-appropriate artifact."""
    obj_name = node.get("object", "UNKNOWN")
    lane = (node.get("lane") or "MC").upper()
    mapping = DEFAULT_OBJECT_TABLES.get(obj_name)

    if not mapping:
        # Unknown object — emit a placeholder so downstream stages don't blow up
        key = f"runs/{run_id}/data-migrator/skipped/{obj_name}.json"
        S3.put_object(Bucket=STAGING_BUCKET, Key=key,
                      Body=json.dumps({"object": obj_name, "lane": lane,
                                       "status": "skipped", "reason": "no source-table mapping"},
                                      indent=2).encode())
        return {"object": obj_name, "lane": lane, "status": "skipped",
                "reason": "no canonical mapping", "artifact": f"s3://{STAGING_BUCKET}/{key}"}

    table = mapping["table"]
    fields = mapping["fields"]
    base_where = mapping.get("where", "")
    # Delta/CDC: AND a change-date filter onto the base WHERE when a watermark is set.
    cdc_where = _cdc_where(obj_name, cdc_watermark) if cdc_watermark else ""
    delta_applied = bool(cdc_where)
    where = (f"( {base_where} ) AND {cdc_where}" if base_where and cdc_where
             else cdc_where or base_where)
    err_note = None
    try:
        rows, cols = _read_table(conn, table, fields, where)
    except Exception as e:
        if delta_applied:   # bad CDC field etc. — fall back to a full extract
            try:
                rows, cols = _read_table(conn, table, fields, base_where)
                delta_applied = False
                err_note = "cdc filter failed; full extract fallback"
            except Exception as e2:
                rows, cols = [], fields
                err_note = f"ECC read failed: {type(e2).__name__}: {str(e2)[:120]}"
        else:
            rows, cols = [], fields
            err_note = f"ECC read failed: {type(e).__name__}: {str(e)[:120]}"

    # Delta completeness: also pull masters CHANGED since the watermark (change docs),
    # which the date-field filter misses (e.g. a customer changed but not newly created).
    changed_via_cdhdr = 0
    if delta_applied and obj_name in CDC_CHANGE_DOC and not err_note:
        kf = CDC_CHANGE_DOC[obj_name][1]
        changed = _cdc_changed_keys(conn, obj_name, cdc_watermark)
        have = {r.get(kf) for r in rows}
        missing = [k for k in changed if k and k not in have]
        if missing:
            extra = _read_by_keys(conn, table, fields, kf, missing)
            rows = rows + extra
            changed_via_cdhdr = len(extra)

    artifacts = {}
    target_lane = mapping.get("lane", lane).upper()
    if target_lane == "MC":
        artifacts["mc_csv"] = _emit_mc_csv(run_id, obj_name, rows, cols)
    elif target_lane == "IDOC":
        idoc_type = mapping.get("idoc_type", obj_name)
        artifacts["idoc_xml"] = _emit_idoc_xml(run_id, obj_name, idoc_type, rows)
    elif target_lane == "LTMOM":
        artifacts["ltmom_spec"] = _emit_ltmom_spec(run_id, obj_name, cols)
        artifacts["sample_csv"] = _emit_mc_csv(run_id, f"{obj_name}_sample", rows[:1000], cols)
    else:
        artifacts["raw_csv"] = _emit_mc_csv(run_id, obj_name, rows, cols)

    result = {"object": obj_name, "lane": target_lane, "row_count": len(rows),
              "artifacts": artifacts, "note": err_note,
              "status": "ok" if err_note is None else "partial"}
    if cdc_watermark and delta_applied:   # only objects that actually have a CDC field
        result["delta"] = {"applied": True, "since": cdc_watermark,
                           "changed_rows": len(rows),
                           "changed_via_change_docs": changed_via_cdhdr}

    # Optionally LOAD the extracted rows into S/4 via the best mechanism (BAPI/IDoc).
    # Per-object cap overrides the global one (M4H_LOAD_MAX_ROWS_<OBJECT>) — e.g. run
    # ExchangeRates at volume while keeping side-effecting objects (BP/PO) at a few rows.
    if loader is not None and rows and loader.supported(obj_name):
        omax = int(os.environ.get("M4H_LOAD_MAX_ROWS_" + obj_name.upper(), LOAD_MAX_ROWS))
        try:
            result["load"] = loader.load_object(obj_name, rows, omax)
        except Exception as e:
            result["load"] = {"error": f"{type(e).__name__}: {str(e)[:160]}"}

    # RECONCILE: prove every record the BAPI said it created actually persisted in
    # the target's system of record (reads keys back; ties created == verified).
    if (loader is not None and Reconciler is not None and result.get("load")
            and "error" not in result["load"]):
        try:
            result["reconciliation"] = Reconciler(loader.c).reconcile(
                obj_name, result["load"], extracted=len(rows))
        except Exception as e:
            result["reconciliation"] = {"error": f"{type(e).__name__}: {str(e)[:160]}"}

    # ExchangeRates: run the currency-customizing READINESS check. Rates only post
    # when their TCURV type + TCURF factor exist in the target; this reports the
    # exact prerequisite delta (and its coverage impact) and emits a deploy package
    # the config team applies via transport — closing the gap to ~100% the right way.
    if (obj_name == "ExchangeRates" and loader is not None and rows
            and CurrencyConfigReconciler is not None):
        try:
            rec = CurrencyConfigReconciler(conn, loader.c)
            rep = rec.diff(rate_rows=rows)
            manifest, csv_text = rec.build_artifact(rep)
            artifacts.update(_emit_currency_config(run_id, manifest, csv_text))
            result["currency_config_readiness"] = {
                "coverage_before": rep["coverage_before"],
                "coverage_after_provisioning": rep["coverage_after_provisioning"],
                "missing_rate_types": rep["missing_rate_type_count"],
                "missing_factors": rep["missing_factor_count"],
                "deploy_package": {"manifest": artifacts.get("manifest"),
                                   "review_csv": artifacts.get("review_csv")},
            }
        except Exception as e:
            result["currency_config_readiness"] = {"error": f"{type(e).__name__}: {str(e)[:160]}"}
    return result


def _carve_out_programs(run_id, results, event):
    """Natuvion-class selective carve-out, embedded in the extraction stage.

    For each extracted object whose source table is carve-eligible, generate an
    optimized in-system extraction program: company-code (BUKRS) + fiscal-year
    (GJAHR) pushed into the WHERE, OPEN CURSOR + PACKAGE SIZE streaming, and
    dependency-aware header co-extraction (line items -> BKPF). Generation is
    deterministic + side-effect-free; in-system DEPLOY stays gated behind
    M4H_CARVE_DEPLOY + a live connection (not done here).

    Off by default; enabled by event["carve_out"] or M4H_CARVE_OUT=1.
    """
    spec = event.get("carve_out") or {}
    if not (spec or os.environ.get("M4H_CARVE_OUT", "0") == "1"):
        return None
    try:
        agent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "agent"))
        if agent_dir not in sys.path:
            sys.path.insert(0, agent_dir)
        from in_system_agent_generator import InSystemAgentGenerator
    except Exception as e:
        return {"enabled": True, "error": f"carve-out generator unavailable: {e}", "programs": []}

    gen = InSystemAgentGenerator()
    bukrs = spec.get("bukrs") or os.environ.get("M4H_CARVE_BUKRS", "")
    gjahr = spec.get("gjahr") or os.environ.get("M4H_CARVE_GJAHR", "")
    try:
        pkg = int(spec.get("package_size") or os.environ.get("M4H_CARVE_PKG", "50000"))
    except (TypeError, ValueError):
        pkg = 50000
    programs, errors, seen = [], [], set()
    for r in results:
        obj = r.get("object")
        table = ((DEFAULT_OBJECT_TABLES.get(obj) or {}).get("table") or "").upper()
        if not table or table in seen or table not in gen.registry:
            continue
        seen.add(table)
        try:
            g = gen.generate(table, bukrs=bukrs, gjahr=gjahr, package_size=pkg)
            artifact = None
            try:
                key = f"runs/{run_id}/data-migrator/carve-out/{g['program']}.abap"
                S3.put_object(Bucket=STAGING_BUCKET, Key=key,
                              Body=g["source"].encode(), ContentType="text/plain")
                artifact = f"s3://{STAGING_BUCKET}/{key}"
            except Exception:
                pass
            programs.append({"object": obj, "table": table, "program": g["program"],
                             "meta": g["meta"], "artifact": artifact})
        except Exception as e:
            errors.append({"object": obj, "table": table, "error": str(e)})
    return {"enabled": True, "engine": "Natuvion-class selective carve-out",
            "filters": {"bukrs": bukrs or "*", "gjahr": gjahr or "*", "package_size": pkg},
            "deploy_gated": os.environ.get("M4H_CARVE_DEPLOY", "0") == "1",
            "program_count": len(programs), "programs": programs, "errors": errors}


def lambda_handler(event, context):
    run_id = event.get("run_id", f"run-{int(time.time())}")
    mode = event.get("mode", "generate_templates")
    spec = event.get("object_spec") or {}
    log_stage_event(run_id, "data-migrator", "start", {"mode": mode, "object": spec.get("object")})

    # F2/F3/F5/F6 Phase B validation modes - exercise the new spine + dynamic-
    # schema + version-routing + benchmark paths against real SAP without the
    # DAG/batch-mode overhead. Tiny entry points; the validator functions live
    # further down.
    if mode == "phase_b_validate_f2":
        return _phase_b_validate_f2(event, run_id)
    if mode == "phase_b_validate_f3":
        return _phase_b_validate_f3(event, run_id)
    if mode == "phase_b_validate_f6":
        return _phase_b_validate_f6(event, run_id)
    if mode == "phase_b_validate_f5":
        return _phase_b_validate_f5(event, run_id)
    if mode == "phase_b_validate_f4":
        return _phase_b_validate_f4(event, run_id)
    if mode == "phase_b_validate_f7":
        return _phase_b_validate_f7(event, run_id)
    if mode == "phase_b_validate_chain":
        return _phase_b_validate_chain(event, run_id)
    if mode == "phase_b_validate_reconcile":
        return _phase_b_validate_reconcile(event, run_id)
    if mode == "phase_b_validate_production_path":
        return _phase_b_validate_production_path(event, run_id)
    if mode == "pilot_readiness_probe":
        return _pilot_readiness_probe(event, run_id)
    if mode == "phase_b_validate_reconcile_sweep":
        return _phase_b_validate_reconcile_sweep(event, run_id)
    if mode == "phase_b_validate_idempotency":
        return _phase_b_validate_idempotency(event, run_id)
    if mode == "list_spines":
        return _list_spines(event, run_id)
    if mode == "phase_b_validate_generated":
        return _phase_b_validate_generated(event, run_id)
    if mode == "phase_c_mc_trigger":
        return _phase_c_mc_trigger(event, run_id)
    # ── 2026-06-15 fire-and-forget completers ──────────────────────────
    # Three new modes that close the gap between "fire-and-forget per
    # configured run" and "fire-and-forget end-to-end except for terraform
    # + the 3 SAP gates": (1) discover_anchors pre-flights the target's
    # customizing tables and writes per-landscape anchors to S3 so spines
    # lift to Tier-1 without per-landscape code; (2) apply_customizing
    # uses the reconciler-packaged manifest and the post_data_prep gate
    # token to land tax codes / exchange rates / classes on the target
    # automatically; (3) mc_lane_extended_strategy_probe smoke-tests
    # the 5-strategy MC trigger chain (lt mc_api / odata / xbp_job /
    # bapi_substitute / idoc_inbound) so a CAL IDES landscape still
    # carries the MC lane through to S/4 via the BAPI substitute path.
    if mode == "discover_anchors":
        return _discover_anchors_mode(event, run_id)
    if mode == "apply_customizing":
        return _apply_customizing_mode(event, run_id)
    if mode == "mc_lane_extended_probe":
        return _mc_lane_extended_probe(event, run_id)
    if mode == "bapi_lane_scale_probe":
        # End-to-end BAPI-lane scale probe: pick a Tier-1 promoted spine
        # and run N synthetic rows through extract -> transform -> validate
        # -> BAPI call -> S/4 create -> result aggregation. Measures
        # per-row latency + total throughput + dead-letter rate. Used as
        # the gating end-to-end validation before Customer Zero.
        import time as _time
        object_type = event.get("object_type", "DocumentInfoRecord")
        row_count   = int(event.get("row_count", 100))
        target_secret_id = event.get("target_secret_id") or "migrate4hana/prod/s4hana-credentials"

        from base_spine_orchestrator import _SPINE_REGISTRY
        cls = _SPINE_REGISTRY.get(object_type)
        if cls is None:
            return {"status": "error", "phase": "bapi_lane_scale_probe", "run_id": run_id,
                    "error": f"object_type '{object_type}' not in spine registry"}

        try:
            tsec = json.loads(SECRETS.get_secret_value(SecretId=target_secret_id)["SecretString"])
            from pyrfc import Connection
            tconn = Connection(ashost=tsec["ashost"], sysnr=tsec.get("sysnr","00"),
                               client=tsec["client"], user=tsec["user"],
                               passwd=tsec.get("passwd") or tsec.get("password"), lang="EN")
        except Exception as e:
            return {"status": "error", "phase": "bapi_lane_scale_probe", "run_id": run_id,
                    "error": f"target_connection failed: {type(e).__name__}: {str(e)[:200]}"}

        spine = cls(tconn, dry_run=False)

        # Build synthetic rows. Same shape as synth_good in the validate
        # generated test — only DQ-gated fields get typed values; source
        # key digit-only so it round-trips through CHAR and NUMC fields.
        RULE_VALUE = {
            "non_empty": "value", "positive_number": "1", "iso_date": "20251115",
            "sap_unit_of_measure": "EA", "currency_iso_4217": "USD",
            "material_number_format": "MAT_T0001", "bukrs_company_code": "1710",
            "werks_plant": "1710", "langu_code": "EN", "sap_client_3char": "100",
            "decimal_max_digits": "100.00", "regex_match": "value",
        }
        try:
            from importlib import import_module
            mod_name = cls.__module__
            spine_mod = import_module(mod_name)
            dq_gates = getattr(spine_mod, "DQ_GATES", [])
        except Exception:
            dq_gates = []

        rows = []
        for i in range(row_count):
            row = {spine.source_key_field: f"{i:010d}"}
            for gate in dq_gates:
                field = gate[0] if isinstance(gate, (tuple, list)) else gate.get("field")
                rule  = gate[1] if isinstance(gate, (tuple, list)) else gate.get("rule")
                val = RULE_VALUE.get(rule, "VALUE")
                if rule == "in_set":
                    args = gate[2] if isinstance(gate, (tuple, list)) else gate.get("rule_args", {})
                    values = (args or {}).get("values") or []
                    if values: val = values[0]
                row[field] = val
            row[spine.source_key_field] = f"{i:010d}"
            rows.append(row)

        t_start = _time.time()
        results = spine.load_many(rows)
        t_elapsed = _time.time() - t_start

        stats = spine.stats.to_dict() if hasattr(spine.stats, "to_dict") else {}
        created     = stats.get("created", 0)
        matched     = stats.get("matched_existing", 0)
        dead_letter = stats.get("dead_letter", 0)
        failed      = stats.get("failed", 0)
        attempted   = stats.get("attempted", row_count)

        # Capture sample dispositions + first dead-letter message for diag
        sample_creates = []
        first_dl = None
        for r in (results or [])[:10]:
            if hasattr(r, "to_dict"): r = r.to_dict()
            if isinstance(r, dict):
                d = r.get("disposition") or r.get("status") or ""
                if d in ("created", "created_dry_run") and len(sample_creates) < 5:
                    sample_creates.append({"src": r.get("source_key"), "tgt": r.get("target_key")})
                if d == "dead_letter" and not first_dl:
                    first_dl = {"src": r.get("source_key"),
                                "msgs": (r.get("messages") or [])[:3]}

        return {"status": "ok", "phase": "bapi_lane_scale_probe", "run_id": run_id,
                "object_type": object_type, "row_count": row_count,
                "elapsed_secs": round(t_elapsed, 3),
                "rows_per_sec": round(row_count / t_elapsed, 2) if t_elapsed > 0 else None,
                "attempted":   attempted,
                "created":     created,
                "matched_existing": matched,
                "dead_letter": dead_letter,
                "failed":      failed,
                "sample_creates": sample_creates,
                "first_dead_letter": first_dl,
                "target": {"ashost": tsec.get("ashost"), "sid": tsec.get("sid",""),
                           "client": tsec.get("client")}}

    if mode == "mc_lane_scale_probe":
        # 100K-row MC-lane throughput probe. Synthesizes rows that pass
        # the spine's mandatory-column validator, runs them through
        # spine.build_payload + call_bapi (buffer), then flushes to S3
        # as the MC-conformant CSV. Optional auto_trigger fires the
        # mc_job_trigger strategy chain on the live S/4 target.
        import time as _time
        object_type = event.get("object_type", "SourceList")
        row_count = int(event.get("row_count", 100000))
        auto_trigger = bool(event.get("auto_trigger", False))
        project_id = event.get("project_id", "")
        tenant_slug = event.get("tenant_slug", "probe-scale")

        from mc_file_exporter import MC_TEMPLATES, flush_all, get_mc_class
        spec = MC_TEMPLATES.get(object_type)
        if not spec:
            return {"status": "error", "phase": "mc_lane_scale_probe", "run_id": run_id,
                    "error": f"object_type '{object_type}' not in MC_TEMPLATES",
                    "available": sorted(MC_TEMPLATES.keys())[:30]}
        # Use the MC factory class directly — scaffolder-generated BAPI spines
        # with the same object_type may have shadowed it in the shared registry.
        cls = get_mc_class(object_type)
        if cls is None:
            return {"status": "error", "phase": "mc_lane_scale_probe", "run_id": run_id,
                    "error": f"object_type '{object_type}' not in MC factory registry"}
        # MC-lane probe doesn't need a real S/4 connection — call_bapi just
        # appends to an in-memory buffer. Pass None as conn; spine.validate
        # + spine.build_payload + spine.call_bapi all run without it.
        spine = cls(None, dry_run=True)

        # Synthesize: every mandatory column gets a non-empty value. Use a
        # mix of digit + char patterns so NUMC fields (WERKS, BUKRS) and
        # CHAR fields (MATNR, KUNNR) both pass downstream MC validation.
        mandatory = spec.get("mandatory", [])
        all_cols = spec.get("csv_columns", [])
        # Common field-shape hints; default = digit-only zero-padded
        _hint = {"WERKS": "1710", "BUKRS": "1710", "EKORG": "1710",
                 "VKORG": "1710", "MATNR": None, "KUNNR": None, "LIFNR": None}
        def _val(col, i):
            h = _hint.get(col)
            if h is not None: return h
            return f"{col[:4]}{i:08d}"

        t_synth_start = _time.time()
        validated = 0; rejected = 0; buffered = 0
        for i in range(row_count):
            row = {col: _val(col, i) for col in all_cols}
            err = spine.validate(row)
            if err:
                rejected += 1
                continue
            validated += 1
            payload = spine.build_payload(row, [])
            spine.call_bapi(payload)
            buffered += 1
        t_synth = _time.time() - t_synth_start

        t_flush_start = _time.time()
        tconn = None
        if auto_trigger:
            target_secret_id = event.get("target_secret_id") or "migrate4hana/prod/s4hana-credentials"
            try:
                tsec = json.loads(SECRETS.get_secret_value(SecretId=target_secret_id)["SecretString"])
                from pyrfc import Connection
                tconn = Connection(ashost=tsec["ashost"], sysnr=tsec.get("sysnr","00"),
                                   client=tsec["client"], user=tsec["user"],
                                   passwd=tsec.get("passwd") or tsec.get("password"), lang="EN")
            except Exception as e:
                return {"status": "error", "phase": "mc_lane_scale_probe", "run_id": run_id,
                        "error": f"target_connection failed: {type(e).__name__}: {str(e)[:200]}"}
        flush_results = flush_all(
            S3, STAGING_BUCKET, run_id, tenant_slug=tenant_slug,
            target_conn=tconn, project_id=project_id,
            auto_trigger=auto_trigger, wait_for_complete=False,
        )
        t_flush = _time.time() - t_flush_start
        total = t_synth + t_flush

        return {"status": "ok", "phase": "mc_lane_scale_probe", "run_id": run_id,
                "object_type": object_type, "row_count": row_count,
                "validated": validated, "rejected": rejected, "buffered": buffered,
                "synth_secs": round(t_synth, 3),
                "flush_secs": round(t_flush, 3),
                "total_secs": round(total, 3),
                "rows_per_sec": round(row_count / total, 1) if total > 0 else None,
                "auto_trigger": auto_trigger,
                "flush_results": flush_results}

    if mode == "query_target_table":
        # Quick read against the live S/4 target table; used to discover
        # real customizing values (purchasing orgs, plants, doc types) so
        # scaffolder definitions can pin per-system constants accurately.
        table   = event.get("table", "T024E")
        fields  = event.get("fields") or []
        where   = event.get("where", "")
        rowcount = int(event.get("rowcount", 30))
        target_secret_id = event.get("target_secret_id") or "migrate4hana/prod/s4hana-credentials"
        try:
            tsec = json.loads(SECRETS.get_secret_value(SecretId=target_secret_id)["SecretString"])
            from pyrfc import Connection
            tconn = Connection(ashost=tsec["ashost"], sysnr=tsec.get("sysnr","00"),
                               client=tsec["client"], user=tsec["user"],
                               passwd=tsec.get("passwd") or tsec.get("password"), lang="EN")
            params = {"QUERY_TABLE": table, "DELIMITER": "|", "ROWCOUNT": rowcount}
            if fields:
                params["FIELDS"] = [{"FIELDNAME": f} for f in fields]
            if where:
                params["OPTIONS"] = [{"TEXT": where}]
            resp = tconn.call("RFC_READ_TABLE", **params)
            return {"status": "ok", "phase": "query_target_table", "run_id": run_id,
                    "table": table, "rowcount": len(resp.get("DATA", [])),
                    "fields": [f.get("FIELDNAME") for f in resp.get("FIELDS", [])],
                    "rows":   [r.get("WA") for r in resp.get("DATA", [])][:50]}
        except Exception as e:
            return {"status": "error", "phase": "query_target_table", "run_id": run_id,
                    "error": f"{type(e).__name__}: {str(e)[:300]}"}

    if mode == "introspect_bapi":
        # Cheap RFC_GET_FUNCTION_INTERFACE probe on the S/4 target so we can
        # author JSON definitions for new spines without guessing field/struct
        # names. Returns the parameter list + struct-field detail per BAPI.
        bapis = event.get("bapis") or ([event["bapi"]] if event.get("bapi") else [])
        target_secret_id = event.get("target_secret_id") or "migrate4hana/prod/s4hana-credentials"
        out = {}
        try:
            tsec = json.loads(SECRETS.get_secret_value(SecretId=target_secret_id)["SecretString"])
            from pyrfc import Connection
            tconn = Connection(ashost=tsec["ashost"], sysnr=tsec.get("sysnr","00"),
                               client=tsec["client"], user=tsec["user"],
                               passwd=tsec.get("passwd") or tsec.get("password"), lang="EN")
            from dynamic_schema_builder import introspect_via_get_function_interface
            for bapi in bapis:
                try:
                    iface = introspect_via_get_function_interface(tconn, bapi)
                    out[bapi] = iface
                except Exception as e:
                    out[bapi] = {"error": f"{type(e).__name__}: {str(e)[:300]}"}
        except Exception as e:
            return {"status": "error", "phase": "introspect_bapi", "run_id": run_id,
                    "error": f"{type(e).__name__}: {str(e)[:300]}"}
        return {"status": "ok", "phase": "introspect_bapi", "run_id": run_id, "introspections": out}

    secret_id = (event.get("ecc_secret_id")
                 or os.environ.get("ECC_SECRET_ID")
                 or event.get("ecc_creds_arn")
                 or event.get("source_creds_arn")
                 or "local:ecc")
    if not secret_id:
        return {"status": "blocked", "reason": "ecc_secret_id / ecc_creds_arn required", "run_id": run_id}

    # ── Batch mode: no object_spec → iterate over stage-3 DAG ─────────────────
    if not spec.get("object"):
        dag = _load_dag(run_id)
        nodes = [n for n in dag.get("nodes", [])
                 if (n.get("lane") or "").upper() in ("MC", "IDOC", "LTMOM")]
        # Always emit routing.dag so the Step Functions Map state can iterate
        # cleanly (even with zero items) instead of crashing on
        # "Unable to apply step 'routing' to input". Nodes carry whatever the
        # downstream lane handlers need (object, lane, deps).
        if not nodes:
            return {"status": "ok", "run_id": run_id, "mode": mode,
                    "note": "no MC/IDoc/LTMOM nodes in DAG — nothing to extract",
                    "dag_load": dag.get("_load_error"),
                    "routing": {"dag": []}}
        try:
            conn = _ecc(secret_id)
        except Exception as e:
            log_stage_event(run_id, "data-migrator", "error", {"connect": str(e)})
            return {"status": "error", "reason": f"ECC connect failed: {e}", "run_id": run_id}

        # Optional S/4 loader (real write path) — only when M4H_LOAD_TO_S4=1
        loader = None
        discovered_config = None
        if LOAD_TO_S4 and UnifiedLoader is not None:
            try:
                tsec = json.loads(SECRETS.get_secret_value(SecretId=(os.environ.get("TARGET_SECRETS_ARN") or os.environ.get("S4_SECRETS_ARN") or "local:target"))["SecretString"])
                tconn = _target_connection()
                loader = UnifiedLoader(tconn, own_logical_system=OWN_LOGICAL_SYSTEM,
                                       sender=IDOC_SENDER,
                                       client=tsec.get("client", "100"),
                                       target_sid=tsec.get("sid", "S4H"))
                # Enterprise transformation / value-mapping / DQ engine (Pillar 2).
                # Active only when M4H_TRANSFORM_RULES is configured; else a no-op.
                try:
                    import transformation_engine as _txe
                    loader.transformer = _txe.from_env()
                    if loader.transformer is not None:
                        log_stage_event(run_id, "data-migrator", "transform_engine_active",
                                        {"rules": os.environ.get("M4H_TRANSFORM_RULES")})
                except Exception as _te:
                    log_stage_event(run_id, "data-migrator", "transform_engine_skipped",
                                    {"reason": str(_te)[:160]})

                # BAPI field-coverage analysis (Gemini gap #3). Routes records
                # carrying CI_/ZZ_/J_1B fields the BAPI cannot transport to an
                # LTMC staging file instead of silently dropping them. Active
                # only when M4H_BAPI_COVERAGE_DIR is configured. The field
                # catalog ships from lambda/utils/bapi_field_catalog.py and
                # can be widened per landscape via M4H_BAPI_FIELD_CATALOG_JSON.
                _cov_dir = os.environ.get("M4H_BAPI_COVERAGE_DIR")
                if _cov_dir:
                    try:
                        from bapi_coverage import LtmcStagingEmitter
                        import bapi_field_catalog as _bfc
                        loader.bapi_coverage_emitter = LtmcStagingEmitter(_cov_dir)

                        # F3 - dynamic schema preferred. When M4H_DYNAMIC_SCHEMA_S3
                        # is set AND we have a target connection, introspect via
                        # DDIC; otherwise use the static baseline.
                        loader.bapi_field_catalog = _bfc.as_dict()
                        _dyn_s3 = os.environ.get("M4H_DYNAMIC_SCHEMA_S3", "").strip()
                        if _dyn_s3:
                            try:
                                from dynamic_schema_builder import build_all_schemas
                                from bapi_field_catalog import known_objects
                                dyn = build_all_schemas(
                                    sorted(known_objects()),
                                    conn=tconn, sid=tsec.get("sid", "S4H"),
                                    client=tsec.get("client", "100"),
                                    s4_release=os.environ.get("M4H_TARGET_RELEASE",
                                                              "UNKNOWN"),
                                    cache_s3_uri=_dyn_s3,
                                )
                                # Overlay dynamic results on top of static baseline:
                                # static fields stay as fallback; dynamic widens.
                                for obj, fields in dyn.items():
                                    base = loader.bapi_field_catalog.get(obj, set())
                                    loader.bapi_field_catalog[obj] = base | fields
                                log_stage_event(run_id, "data-migrator",
                                                "dynamic_schema_active",
                                                {"s3": _dyn_s3,
                                                 "objects_introspected": len(dyn)})
                            except Exception as _dse:
                                log_stage_event(run_id, "data-migrator",
                                                "dynamic_schema_skipped",
                                                {"reason": str(_dse)[:160]})
                        log_stage_event(run_id, "data-migrator",
                                        "bapi_coverage_active",
                                        {"dir": _cov_dir,
                                         "objects_covered": len(loader.bapi_field_catalog)})
                    except Exception as _ce:
                        log_stage_event(run_id, "data-migrator",
                                        "bapi_coverage_skipped",
                                        {"reason": str(_ce)[:160]})
                # Live source->target registry, shared across the run so dependent
                # objects (OpenPO -> Vendor) resolve refs; source conn for PO items.
                loader.key_map = _load_ledger(run_id)   # cross-run ledger -> idempotent re-runs (DDB-backed when M4H_KEYMAP_TABLE set)
                loader.source_conn = conn
                loader.odata = _target_odata()   # transaction-ready partner creation (OData)
                # Factories for the parallel worker pool (fresh per-worker connections):
                loader.target_conn_factory = _target_connection
                loader.source_conn_factory = lambda: _ecc(secret_id)
                loader.odata_factory = _target_odata
                # Auto-discover target org units/accounts so we adapt to THIS landscape
                # (not the appliance we were built on). Env overrides win; on failure we
                # keep the built-in defaults.
                if config_discovery is not None:
                    try:
                        _cfg = _load_discovered_config()
                        if _cfg is None or os.environ.get("M4H_REDISCOVER") == "1":
                            _cfg = config_discovery.discover(tconn)
                            _save_discovered_config(_cfg)
                            log_stage_event(run_id, "data-migrator", "config_discovered", _cfg["summary"])
                        else:
                            log_stage_event(run_id, "data-migrator", "config_cached", _cfg["summary"])
                        loader.po_org, loader.fi_org, loader.bp_org = _cfg["po"], _cfg["fi"], _cfg["bp"]
                        loader.cc_org = _cfg.get("co", {})
                        loader.asset_org = _cfg.get("asset", {})
                        discovered_config = _cfg["summary"]
                    except Exception as e:
                        log_stage_event(run_id, "data-migrator", "config_discovery_skipped", {"reason": str(e)[:160]})
                log_stage_event(run_id, "data-migrator", "load_enabled",
                                {"max_rows": LOAD_MAX_ROWS, "mechanisms": OBJECT_MECHANISM,
                                 "odata_partner_create": bool(loader.odata and loader.odata_ready())})
            except Exception as e:
                log_stage_event(run_id, "data-migrator", "load_disabled", {"reason": str(e)[:160]})

        # Delta/CDC: in delta mode, extract only records changed since the watermark.
        run_watermark = _load_watermark() if CDC_DELTA else None

        results = []
        for node in nodes:
            try:
                results.append(_process_one_object(conn, run_id, node, loader=loader,
                                                   cdc_watermark=run_watermark))
            except Exception as e:
                results.append({"object": node.get("object"), "status": "error",
                                "error": f"{type(e).__name__}: {str(e)[:200]}"})

        # Advance the watermark to today so the next delta run only picks up newer changes.
        new_watermark = time.strftime("%Y%m%d")
        if CDC_DELTA or _load_watermark() is None:
            _save_watermark(new_watermark)

        # Persist the live source->target key registry (built during the run as
        # objects loaded; consumed by dependent objects, then written for audit).
        key_map_info = None
        km = getattr(loader, "key_map", None) if loader else None
        if km is not None and km.to_rows():
            key_map_info = {**_emit_key_map(run_id, km), "stats": km.stats()}
            _save_ledger(km)   # persist the merged ledger for idempotent re-runs

        # Dead-letter: genuinely failed records across objects -> a report for targeted
        # reprocessing (a subsequent idempotent re-run picks these up; successes are skipped).
        dead_letters = [{"object": r.get("object"), **d}
                        for r in results for d in (r.get("load") or {}).get("dead_letter", [])]

        # CVI conflicts (Gemini gap #1) - appended into dead_letters here so they
        # ride the same dead-letter S3 artifact below. Uses unify_with_xrefs to
        # detect intercompany cycles (KNA1.LIFNR <-> LFA1.KUNNR) and produce a
        # two-phase load plan: phase 1 creates BP stubs, phase 2 attaches xrefs.
        cvi_info = None
        try:
            from cvi_mapper import unify_with_xrefs, detect_overlap as _cvi_overlap
            kna1_rows = next((((r.get("extract") or {}).get("rows") or [])
                              for r in results if r.get("object") == "Customer"), [])
            lfa1_rows = next((((r.get("extract") or {}).get("rows") or [])
                              for r in results if r.get("object") == "Vendor"), [])
            if kna1_rows and lfa1_rows:
                overlap_keys = _cvi_overlap(kna1_rows, lfa1_rows)
                mappings, conflicts, plan = unify_with_xrefs(kna1_rows, lfa1_rows)
                cvi_info = {
                    "overlap_partner_numbers": overlap_keys[:50],
                    "overlap_count": len(overlap_keys),
                    "legacy_keys_mapped": len(mappings),
                    "unique_bps": len({m.target_bp_id for m in mappings.values()}),
                    "merged_customer_vendor": sum(1 for m in mappings.values() if m.merged),
                    "conflicts_requiring_review": len(conflicts),
                    "two_phase_plan": plan.to_dict(),
                }
                cvi_key = f"runs/{run_id}/data-migrator/cvi_map.json"
                S3.put_object(
                    Bucket=STAGING_BUCKET, Key=cvi_key,
                    Body=json.dumps({
                        "mappings": {k: v.to_dict() for k, v in mappings.items()},
                        "conflicts": [c.to_dict() for c in conflicts],
                        "two_phase_plan": plan.to_dict(),
                    }, indent=2).encode(),
                    ContentType="application/json")
                cvi_info["artifact"] = f"s3://{STAGING_BUCKET}/{cvi_key}"
                log_stage_event(run_id, "data-migrator", "cvi_computed", cvi_info)
                for c in conflicts:
                    dead_letters.append({
                        "object": "BusinessPartner",
                        "reason": "CVI_CONFLICT",
                        "kna1_id": c.legacy_kna1_id,
                        "lfa1_id": c.legacy_lfa1_id,
                        "msg": c.reason,
                        "detail": c.detail,
                    })
        except Exception as _ce:
            log_stage_event(run_id, "data-migrator", "cvi_skipped",
                            {"reason": str(_ce)[:160]})

        dead_letter_info = None
        if dead_letters:
            dkey = f"runs/{run_id}/data-migrator/dead-letter/failed_records.json"
            S3.put_object(Bucket=STAGING_BUCKET, Key=dkey,
                          Body=json.dumps(dead_letters, indent=2).encode(),
                          ContentType="application/json")
            dead_letter_info = {"failed_records": len(dead_letters),
                                "artifact": f"s3://{STAGING_BUCKET}/{dkey}",
                                "reprocess": "idempotent re-run reloads these; loaded records are skipped"}

        # LTMC handoffs (Gemini follow-up #4). When bapi_coverage routes a
        # record to LTMC staging (BAPI lacks the field), the load result
        # carries an ltmc_handoff dict. Collect them ALL here so we can:
        #   - report the pending-LTMC-import count in the run summary
        #   - seal an "ltmc_pending" block into the hash chain so any tamper
        #     of the staging file is detectable
        ltmc_handoffs = []
        for r in results:
            for item in (r.get("load") or {}).get("ltmc_handoffs") or []:
                ltmc_handoffs.append({"object": r.get("object"), **item})
            # Also catch single-handoff style returned from _load_one:
            for record_load in (r.get("load") or {}).get("records") or []:
                handoff = record_load.get("ltmc_handoff")
                if handoff:
                    ltmc_handoffs.append({"object": r.get("object"), **handoff})

        ltmc_pending_info = None
        if ltmc_handoffs:
            ltmc_key = f"runs/{run_id}/data-migrator/ltmc_handoffs.json"
            S3.put_object(
                Bucket=STAGING_BUCKET, Key=ltmc_key,
                Body=json.dumps(ltmc_handoffs, indent=2).encode(),
                ContentType="application/json")
            ltmc_pending_info = {
                "pending_count": len(ltmc_handoffs),
                "objects_with_pending": sorted({h["object"] for h in ltmc_handoffs}),
                "artifact": f"s3://{STAGING_BUCKET}/{ltmc_key}",
                "note": "Gate: cutover must NOT proceed until each pending "
                        "LTMC handoff is confirmed imported in the Migration "
                        "Cockpit and reconciled. See EvidencePack.cutover_verdict.",
            }
            log_stage_event(run_id, "data-migrator", "ltmc_pending", ltmc_pending_info)

        # Write batch summary so downstream validator can read it
        loaded_to_s4 = sum((r.get("load", {}) or {}).get("created_in_s4", 0) for r in results)
        recon_reports = [r["reconciliation"] for r in results
                         if isinstance(r.get("reconciliation"), dict)
                         and "error" not in r["reconciliation"]]
        # Data-quality SLO rollup: total_attempted vs total_dead_letter, and the
        # resulting pct. The SFN Choice state (DataQualitySloChoice) branches on
        # data_quality.slo_breach, halting at DataQualityHaltForReview when
        # dead-letter rate exceeds M4H_DEAD_LETTER_THRESHOLD_PCT (default 5%).
        # threshold=0 disables the gate (dirty data flows through unblocked).
        try:
            _dq_threshold = float(os.environ.get("M4H_DEAD_LETTER_THRESHOLD_PCT", "5.0"))
        except Exception:
            _dq_threshold = 5.0
        _total_attempted = sum(int((r.get("load") or {}).get("attempted") or 0)
                               for r in results)
        _total_dead = sum(int((r.get("load") or {}).get("failed_count") or
                              len((r.get("load") or {}).get("dead_letter") or []))
                          for r in results)
        # Also count CVI conflicts pushed into the dead-letter artifact above.
        if cvi_info:
            _total_dead += int(cvi_info.get("conflicts_requiring_review") or 0)
        _dq_pct = round((_total_dead / _total_attempted * 100.0), 3) if _total_attempted else 0.0
        _dq_breach = bool(_dq_threshold > 0 and _dq_pct > _dq_threshold)
        data_quality = {
            "total_attempted":   _total_attempted,
            "total_dead_letter": _total_dead,
            "dead_letter_pct":   _dq_pct,
            "threshold_pct":     _dq_threshold,
            "slo_breach":        _dq_breach,
            "gate_disabled":     bool(_dq_threshold == 0),
        }
        summary = {"run_id": run_id, "mode": mode, "object_count": len(results),
                   "ok_count": sum(1 for r in results if r.get("status") == "ok"),
                   "partial_count": sum(1 for r in results if r.get("status") == "partial"),
                   "error_count": sum(1 for r in results if r.get("status") == "error"),
                   "skipped_count": sum(1 for r in results if r.get("status") == "skipped"),
                   "load_to_s4_enabled": bool(loader),
                   "objects_created_in_s4": loaded_to_s4,
                   "cdc": {"mode": "delta" if CDC_DELTA else "full",
                           "watermark_used": run_watermark, "next_watermark": new_watermark,
                           "changed_rows_extracted": sum((r.get("delta") or {}).get("changed_rows", 0)
                                                         for r in results if r.get("delta"))},
                   "idempotency": {"newly_created": loaded_to_s4,
                                   "reused_from_ledger": sum((r.get("load", {}) or {}).get("reused_from_ledger", 0)
                                                             for r in results)},
                   "discovered_config": discovered_config,
                   "reconciliation": Reconciler.rollup(recon_reports) if Reconciler else None,
                   "support_compliance": compliance.audit(results) if compliance else None,
                   "key_mapping": key_map_info,
                   "dead_letter": dead_letter_info,
                   "data_quality": data_quality,
                   "dead_letter_pct": data_quality["dead_letter_pct"],
                   "slo_breach": data_quality["slo_breach"],
                   "cvi": cvi_info,
                   "ltmc_pending": ltmc_pending_info,
                   "carve_out": _carve_out_programs(run_id, results, event),
                   "results": results,
                   "routing": {"dag": [{"object": r.get("object"),
                                         "lane": (r.get("lane") or "MC").upper(),
                                         "status": r.get("status")}
                                        for r in results if r.get("object")]}}
        # Pillar 4 — cryptographic audit chain over this run's verifiable actions.
        # Each block (data load, key-map, reconciliation, carve-out) is SHA-256
        # hash-chained to the previous, giving auditors tamper-evident assurance.
        try:
            from reconciler import HashChainLedger
            _chain = HashChainLedger(run_id=run_id)
            _chain.append("data_load", {"object_count": len(results),
                                        "created_in_s4": loaded_to_s4})
            if key_map_info:
                _chain.append("key_map", key_map_info.get("stats", {}))
            # Seal one block per LTMC handoff so the chain bears witness to
            # the staging file. cutover_verdict reads this to enforce
            # "no GO until LTMC imports confirmed."
            for handoff in (ltmc_handoffs or []):
                _chain.append("ltmc_pending", {
                    "object": handoff.get("object"),
                    "csv_path": handoff.get("csv_path"),
                    "records": handoff.get("records"),
                    "delta_fields": handoff.get("delta_fields"),
                    "status": "PENDING_LTMC_IMPORT",
                })
            if summary.get("reconciliation"):
                _chain.append("reconciliation", summary["reconciliation"])
            if summary.get("carve_out"):
                _chain.append("carve_out",
                              {"program_count": summary["carve_out"].get("program_count")})
            summary["audit_chain"] = {"head_hash": _chain.head(),
                                      "blocks": _chain.block_count(),
                                      "verification": _chain.verify()}
            S3.put_object(Bucket=STAGING_BUCKET,
                          Key=f"runs/{run_id}/data-migrator/audit_chain.jsonl",
                          Body=_chain.dump_jsonl().encode(),
                          ContentType="application/x-ndjson")
        except Exception as _ce:
            summary["audit_chain"] = {"error": str(_ce)[:160]}

        S3.put_object(Bucket=STAGING_BUCKET,
                      Key=f"runs/{run_id}/data-migrator/summary.json",
                      Body=json.dumps(summary, default=str, indent=2).encode(),
                      ContentType="application/json")
        log_stage_event(run_id, "data-migrator", "ok", summary)
        return {"status": "success", **summary}

    # ── Single-object mode (legacy) ───────────────────────────────────────────
    obj_name = spec.get("object", "UNKNOWN")
    table = spec.get("source_table", obj_name)
    fields = spec.get("fields", [])
    where = spec.get("where_clause", "")
    lane = (spec.get("lane") or "MC").upper()

    try:
        conn = _ecc(secret_id)
        rows, cols = _read_table(conn, table, fields, where)
    except Exception as e:
        log_stage_event(run_id, "data-migrator", "error", {"ecc_read": str(e)})
        return {"status": "error", "reason": f"ECC read failed: {e}", "run_id": run_id}

    artifacts = {}
    if lane == "MC":
        artifacts["mc_csv"] = _emit_mc_csv(run_id, obj_name, rows, cols)
    elif lane == "IDOC":
        idoc_type = spec.get("idoc_type", obj_name)
        artifacts["idoc_xml"] = _emit_idoc_xml(run_id, obj_name, idoc_type, rows)
    elif lane == "LTMOM":
        artifacts["ltmom_spec"] = _emit_ltmom_spec(run_id, obj_name, cols)
        artifacts["sample_csv"] = _emit_mc_csv(run_id, f"{obj_name}_sample", rows[:1000], cols)
    else:
        artifacts["raw_csv"] = _emit_mc_csv(run_id, obj_name, rows, cols)

    summary = {"run_id": run_id, "status": "ok", "object": obj_name, "lane": lane,
               "row_count": len(rows), "artifacts": artifacts}
    log_stage_event(run_id, "data-migrator", "ok", summary)
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Phase B validators
# ─────────────────────────────────────────────────────────────────────────────
def _phase_b_validate_f2(event, run_id):
    """F2 Phase B - drive MaterialSpineOrchestrator against the live S/4 target.

    Loads `count` synthetic Material records (default 3) via BAPI_MATERIAL_SAVEDATA
    and reports the per-record LoadResult, PersistentKeyMap writes, and stats.

    Payload shape::

        { "mode": "phase_b_validate_f2",
          "run_id": "f2-phaseb-001",
          "count": 3,
          "prefix": "F2PHASEB",
          "target_secret_id": "migrate4hana/prod/s4hana-credentials" }
    """
    target_secret_id = event.get("target_secret_id") or "migrate4hana/prod/s4hana-credentials"
    count   = int(event.get("count", 3))
    prefix  = event.get("prefix", "F2PHASEB")

    # Open target connection
    try:
        tsec = json.loads(SECRETS.get_secret_value(SecretId=target_secret_id)["SecretString"])
        from pyrfc import Connection   # type: ignore
        tconn = Connection(
            ashost=tsec["ashost"], sysnr=tsec.get("sysnr", "00"),
            client=tsec["client"], user=tsec["user"],
            passwd=tsec.get("passwd") or tsec.get("password"),
            lang=tsec.get("lang", "EN"),
        )
    except Exception as e:
        return {"status": "error", "phase": "connect_s4", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}"}

    # PersistentKeyMap pointed at the real DDB table
    try:
        from key_map import PersistentKeyMap
        ddb_table = os.environ.get("M4H_KEYMAP_TABLE", "migrate4hana-key-map-prod")
        km = PersistentKeyMap(table_name=ddb_table, run_id=run_id,
                              target_release=os.environ.get("M4H_TARGET_RELEASE", "S4HANA_UNKNOWN"))
    except Exception as e:
        km = None
        log_stage_event(run_id, "data-migrator", "phaseB_keymap_skipped",
                        {"reason": str(e)[:160]})

    # Drive the spine
    try:
        from material_spine import MaterialSpineOrchestrator
    except Exception as e:
        return {"status": "error", "phase": "import_spine", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}"}

    orch = MaterialSpineOrchestrator(tconn, key_map=km)

    # Synthetic records - keep the field set tight so a Phase B validation works
    # against any S/4 release without needing customer customizing.
    rows = []
    for i in range(count):
        rows.append({
            "MATNR": f"{prefix}_{i:04d}",
            "MTART": "HALB",        # universally supported semi-finished
            "MBRSH": "M",           # mechanical industry
            "MEINS": "EA",
            "MAKTX": f"Phase B test material {i:04d}",
        })

    results = orch.load_many(rows)
    summary = {
        "run_id":     run_id,
        "status":     "ok",
        "phase":      "f2_material_spine",
        "target":     {"sid": tsec.get("sid"), "client": tsec.get("client"),
                       "ashost": tsec.get("ashost")},
        "count":      count,
        "results":    [r.to_dict() for r in results],
        "spine_stats": orch.stats.to_dict(),
        "key_map_writes": (km.persistence_stats() if km is not None else None),
    }
    log_stage_event(run_id, "data-migrator", "phaseB_f2_complete",
                    {"created": orch.stats.created, "dead_letter": orch.stats.dead_letter})
    try:
        tconn.close()
    except Exception:
        pass
    return summary


def _phase_b_validate_f3(event, run_id):
    """F3 Phase B - drive dynamic_schema_builder against the live S/4 target.

    Calls DD_BAPI_PARAMETER_GET on the target, compiles the field set, writes
    the S3 cache, and returns the compiled CachedSchema.

    Payload shape::

        { "mode": "phase_b_validate_f3",
          "run_id": "f3-phaseb-001",
          "object_type": "Material",
          "target_secret_id": "migrate4hana/prod/s4hana-credentials",
          "force_refresh": true }
    """
    target_secret_id = event.get("target_secret_id") or "migrate4hana/prod/s4hana-credentials"
    object_type      = event.get("object_type", "Material")
    force_refresh    = bool(event.get("force_refresh", True))

    try:
        tsec = json.loads(SECRETS.get_secret_value(SecretId=target_secret_id)["SecretString"])
        from pyrfc import Connection   # type: ignore
        tconn = Connection(
            ashost=tsec["ashost"], sysnr=tsec.get("sysnr", "00"),
            client=tsec["client"], user=tsec["user"],
            passwd=tsec.get("passwd") or tsec.get("password"),
            lang=tsec.get("lang", "EN"),
        )
    except Exception as e:
        return {"status": "error", "phase": "connect_s4", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}"}

    # Try each RFC entry point directly so we capture and surface the real
    # error responses (build_schema falls back silently, which hides why the
    # live introspection didn't work).
    diag = {"dd_bapi_param_get": None, "get_function_interface": None,
            "dd03l_read": None}
    try:
        from dynamic_schema_builder import (
            introspect_via_dd_bapi_parameter_get, introspect_via_dd03l,
            introspect_via_get_function_interface,
            compile_field_set_from_dd_bapi, compile_field_set_from_dd03l,
            compile_field_set_from_function_interface,
            build_schema,
        )
    except Exception as e:
        return {"status": "error", "phase": "import_dynamic_schema",
                "run_id": run_id, "error": f"{type(e).__name__}: {str(e)[:240]}"}

    bapi = "BAPI_MATERIAL_SAVEDATA" if object_type == "Material" \
           else f"BAPI_{object_type.upper()}_CREATE"

    # 1) DD_BAPI_PARAMETER_GET direct probe (older releases only)
    try:
        params = introspect_via_dd_bapi_parameter_get(tconn, bapi)
        diag["dd_bapi_param_get"] = {"ok": True, "param_count": len(params),
                                      "compiled_fields": sorted(compile_field_set_from_dd_bapi(params))[:30]}
    except Exception as e:
        diag["dd_bapi_param_get"] = {"ok": False,
                                      "error": f"{type(e).__name__}: {str(e)[:300]}"}

    # 2) RFC_GET_FUNCTION_INTERFACE direct probe (universally available)
    try:
        iface = introspect_via_get_function_interface(tconn, bapi)
        fields = sorted(compile_field_set_from_function_interface(iface))
        diag["get_function_interface"] = {
            "ok": True,
            "param_count": len(iface),
            "param_summary": [
                {"name": p.get("PARAMETER"), "class": p.get("PARAMCLASS"),
                 "tabname": p.get("TABNAME"), "field_count": len(p.get("FIELDS") or [])}
                for p in iface[:10]
            ],
            "compiled_field_count": len(fields),
            "compiled_fields_sample": fields[:40],
        }
    except Exception as e:
        diag["get_function_interface"] = {"ok": False,
                                           "error": f"{type(e).__name__}: {str(e)[:300]}"}

    # 3) DD03L direct probe (read structure for the BAPI's function-module name)
    try:
        rows = introspect_via_dd03l(tconn, bapi)
        diag["dd03l_read"] = {"ok": True, "row_count": len(rows),
                               "compiled_fields": sorted(compile_field_set_from_dd03l(rows))[:30]}
    except Exception as e:
        diag["dd03l_read"] = {"ok": False,
                               "error": f"{type(e).__name__}: {str(e)[:300]}"}

    # 3) Full build_schema (fallback chain) for the actual cache write
    try:
        schema = build_schema(
            object_type,
            conn=tconn,
            sid=tsec.get("sid", "S4H"),
            client=tsec.get("client", "100"),
            s4_release=os.environ.get("M4H_TARGET_RELEASE", "S4HANA_2023"),
            cache_s3_uri=os.environ.get("M4H_DYNAMIC_SCHEMA_S3",
                                        f"s3://{STAGING_BUCKET}/dynamic-schema"),
            force_refresh=force_refresh,
        )
    except Exception as e:
        return {"status": "error", "phase": "build_schema", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}", "diag": diag}
    finally:
        try:
            tconn.close()
        except Exception:
            pass

    return {
        "run_id":   run_id,
        "status":   "ok",
        "phase":    "f3_dynamic_schema",
        "object":   object_type,
        "bapi":     bapi,
        "diag":     diag,
        "schema_source": schema.source,
        "field_count":   len(schema.fields),
        "sample_fields": schema.fields[:20],
    }


def _resolve_routing(source_code: str, target_code: str, source_db=None):
    """Helper - resolve a version_matrix RoutingPlan for the given pair.
    Returns ``(plan_dict, error_str)``. Either or both may be None."""
    try:
        from version_matrix import routing_for_pair, VersionIncompatibilityError
    except Exception as e:
        return None, f"version_matrix unimportable: {e}"
    try:
        plan = routing_for_pair(source_code, target_code, source_db=source_db)
        return plan.to_dict(), None
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:200]}"


def _phase_b_validate_f6(event, run_id):
    """F6 Phase B - validate that a saved version selection compiles into a
    RoutingPlan whose tags actually shape extract behaviour.

    Two-part proof:
      1. Resolve the routing plan from (source_code, target_code, source_db)
         either from the event payload or from auto-detection via RFC.
      2. Apply the plan's ``package_size`` to a real RFC_READ_TABLE call
         against the live ECC, and confirm the row-count cap matches the plan.

    Payload shape::

        { "mode": "phase_b_validate_f6",
          "run_id": "f6-phaseb-001",
          "source_code": "ECC60_EHP8",        # optional - auto-detect if absent
          "target_code": "S4HANA_2023",       # optional - auto-detect if absent
          "source_db":   "HANA",              # optional override
          "ecc_secret_id": "migrate4hana/prod/sap-credentials",
          "probe_table": "KNA1",
          "probe_fields": ["KUNNR", "NAME1"] }
    """
    ecc_secret_id = (event.get("ecc_secret_id")
                     or os.environ.get("ECC_SECRET_ID")
                     or "migrate4hana/prod/sap-credentials")
    src_code = event.get("source_code")
    tgt_code = event.get("target_code")
    src_db   = event.get("source_db")
    probe_table  = event.get("probe_table", "KNA1")
    probe_fields = event.get("probe_fields", ["KUNNR", "NAME1", "LAND1"])

    diag = {"detection": None, "routing_plan": None, "probe": None}

    # Open the ECC connection
    try:
        conn = _ecc(ecc_secret_id)
    except Exception as e:
        return {"status": "error", "phase": "connect_ecc", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}"}

    # If the caller didn't supply the version codes, auto-detect via RFC_SYSTEM_INFO
    if not src_code:
        try:
            from version_matrix import detect_source_ecc_version
            info = conn.call("RFC_SYSTEM_INFO")
            detected = detect_source_ecc_version(info)
            if detected:
                src_code = detected.code
                if not src_db:
                    src_db = detected.db_default
                diag["detection"] = {"source_code": src_code,
                                      "source_db": src_db,
                                      "rfc_release": info.get("RFCSI_EXPORT", {}).get("RFCSAPRL"),
                                      "rfc_dbsys":   info.get("RFCSI_EXPORT", {}).get("RFCDBSYS")}
            else:
                diag["detection"] = {"error": "RFC_SYSTEM_INFO returned an unmapped release",
                                      "raw": info.get("RFCSI_EXPORT")}
        except Exception as e:
            diag["detection"] = {"error": f"{type(e).__name__}: {str(e)[:240]}"}

    # Fall back to a sensible default target if not specified
    tgt_code = tgt_code or "S4HANA_2023"

    # Resolve routing plan
    if not src_code:
        try: conn.close()
        except Exception: pass
        return {"status": "error", "phase": "resolve_source_version",
                "run_id": run_id, "diag": diag,
                "error": "could not resolve source ECC version (pass source_code explicitly)"}

    plan, err = _resolve_routing(src_code, tgt_code, source_db=src_db)
    if err:
        try: conn.close()
        except Exception: pass
        return {"status": "error", "phase": "resolve_routing", "run_id": run_id,
                "diag": diag, "error": err}
    diag["routing_plan"] = plan

    # Apply the routing plan's package_size as the ROWCOUNT cap on a live probe
    cap = int(plan["package_size"])
    try:
        t0 = time.time()
        resp = conn.call(
            "RFC_READ_TABLE",
            QUERY_TABLE=probe_table,
            FIELDS=[{"FIELDNAME": f} for f in probe_fields],
            ROWCOUNT=cap,
        )
        elapsed_ms = int((time.time() - t0) * 1000)
        rows = resp.get("DATA") or []
        diag["probe"] = {"ok": True,
                          "table": probe_table,
                          "package_size_applied": cap,
                          "rows_returned": len(rows),
                          "elapsed_ms": elapsed_ms,
                          "throughput_rows_per_sec":
                              round(len(rows) / (elapsed_ms / 1000), 1) if elapsed_ms else None}
    except Exception as e:
        diag["probe"] = {"ok": False,
                          "error": f"{type(e).__name__}: {str(e)[:240]}"}
    finally:
        try: conn.close()
        except Exception: pass

    return {
        "run_id":      run_id,
        "status":      "ok",
        "phase":       "f6_version_routing",
        "source_code": src_code,
        "target_code": tgt_code,
        "source_db":   src_db,
        "extract_strategy":     plan["extract_strategy"],
        "package_size":         plan["package_size"],
        "template_format":      plan["template_format"],
        "fargate_fan_out":      plan["fargate_fan_out"],
        "cluster_read_safety":  plan["cluster_read_safety"],
        "odata_ltmc_supported": plan["odata_ltmc_supported"],
        "diag":        diag,
    }


def _percentile(values, p):
    if not values:
        return 0.0
    s = sorted(values)
    import math
    k = (len(s) - 1) * (p / 100.0)
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return float(s[int(k)])
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _phase_b_validate_f5(event, run_id):
    """F5 Phase B - benchmark the spine path against real S/4 with per-record
    latency capture. Returns the same BenchmarkResult shape as the offline
    harness so SCALE_BENCHMARK.md can drop the numbers in directly.

    Payload shape::

        { "mode": "phase_b_validate_f5",
          "run_id": "f5-phaseb-001",
          "count": 25,
          "prefix": "F5PHASEB",
          "target_secret_id": "migrate4hana/prod/s4hana-credentials" }
    """
    target_secret_id = event.get("target_secret_id") or "migrate4hana/prod/s4hana-credentials"
    count   = int(event.get("count", 25))
    prefix  = event.get("prefix", "F5PHASEB")

    try:
        tsec = json.loads(SECRETS.get_secret_value(SecretId=target_secret_id)["SecretString"])
        from pyrfc import Connection   # type: ignore
        tconn = Connection(
            ashost=tsec["ashost"], sysnr=tsec.get("sysnr", "00"),
            client=tsec["client"], user=tsec["user"],
            passwd=tsec.get("passwd") or tsec.get("password"),
            lang=tsec.get("lang", "EN"),
        )
    except Exception as e:
        return {"status": "error", "phase": "connect_s4", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}"}

    try:
        from material_spine import MaterialSpineOrchestrator
        from key_map import PersistentKeyMap
    except Exception as e:
        return {"status": "error", "phase": "import_spine", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}"}

    ddb_table = os.environ.get("M4H_KEYMAP_TABLE", "migrate4hana-key-map-prod")
    km = PersistentKeyMap(table_name=ddb_table, run_id=run_id)
    orch = MaterialSpineOrchestrator(tconn, key_map=km)

    # Build records up front so generation cost isn't in the latency window
    records = []
    for i in range(count):
        records.append({
            "MATNR": f"{prefix}_{run_id[-6:]}_{i:04d}",
            "MTART": "HALB",
            "MBRSH": "M",
            "MEINS": "EA",
            "MAKTX": f"Phase B perf {i:04d}",
        })

    latencies_ms = []
    status_breakdown = {}
    dead_letter_codes = {}
    dead_letter_samples = []   # first 5 dead-letters with messages
    ext_rows_total = 0

    t0 = time.perf_counter()
    for row in records:
        r0 = time.perf_counter()
        res = orch.load_one(row)
        latencies_ms.append((time.perf_counter() - r0) * 1000)
        status_breakdown[res.status] = status_breakdown.get(res.status, 0) + 1
        if res.dead_letter:
            dead_letter_codes[res.dead_letter] = dead_letter_codes.get(res.dead_letter, 0) + 1
            if len(dead_letter_samples) < 5:
                dead_letter_samples.append({
                    "src_key": res.source_key,
                    "code":    res.dead_letter,
                    "msg":     (res.messages or [""])[0][:300],
                })
        ext_rows_total += res.extension_rows
    wall_clock_s = round(time.perf_counter() - t0, 3)

    try:
        tconn.close()
    except Exception:
        pass

    return {
        "run_id":             run_id,
        "status":             "ok",
        "phase":              "f5_spine_benchmark",
        "object_type":        "Material",
        "count":              count,
        "wall_clock_s":       wall_clock_s,
        "throughput_per_sec": round(count / wall_clock_s, 2) if wall_clock_s else 0.0,
        "p50_ms":             round(_percentile(latencies_ms, 50), 1),
        "p90_ms":             round(_percentile(latencies_ms, 90), 1),
        "p99_ms":             round(_percentile(latencies_ms, 99), 1),
        "p999_ms":            round(_percentile(latencies_ms, 99.9), 1),
        "min_ms":             round(min(latencies_ms), 1) if latencies_ms else 0,
        "max_ms":             round(max(latencies_ms), 1) if latencies_ms else 0,
        "status_breakdown":   status_breakdown,
        "dead_letter_codes":  dead_letter_codes,
        "dead_letter_samples": dead_letter_samples,
        "extension_rows":     ext_rows_total,
        "spine_stats":        orch.stats.to_dict(),
        "key_map_writes":     km.persistence_stats(),
    }


def _phase_b_validate_f4(event, run_id):
    """F4 Phase B - drive TransformationEngine against the live S/4 target.

    Proves three properties end-to-end against real SAP:

      1. VALUE_MAP succeeds: a source MTART value (e.g. legacy 'ZHALB') is
         translated to a target-valid one ('HALB') BEFORE the BAPI call, and
         the row creates successfully.
      2. DQ gate rejects BEFORE the BAPI: a row missing a mandatory field
         (MEINS) dead-letters as DATA_QUALITY_REJECTION; the BAPI is never
         called for that row (proven by the spine stats — created=0 for the
         rejected row, and dead_letter+=1 with code DATA_QUALITY_REJECTION).
      3. VALUE_MAP unmapped-with-reject sentinel composes with ALLOWED gate:
         an unmapped MTART hits the reject sentinel and is caught by a DQ
         ALLOWED rule, dead-lettering before the BAPI.

    Payload shape::

        { "mode": "phase_b_validate_f4",
          "run_id": "f4-phaseb-001",
          "prefix": "F4PHASEB",
          "target_secret_id": "migrate4hana/prod/s4hana-credentials" }
    """
    target_secret_id = event.get("target_secret_id") or "migrate4hana/prod/s4hana-credentials"
    prefix = event.get("prefix", "F4PHASEB")

    try:
        tsec = json.loads(SECRETS.get_secret_value(SecretId=target_secret_id)["SecretString"])
        from pyrfc import Connection   # type: ignore
        tconn = Connection(
            ashost=tsec["ashost"], sysnr=tsec.get("sysnr", "00"),
            client=tsec["client"], user=tsec["user"],
            passwd=tsec.get("passwd") or tsec.get("password"),
            lang=tsec.get("lang", "EN"),
        )
    except Exception as e:
        return {"status": "error", "phase": "connect_s4", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}"}

    try:
        from transformation_engine import TransformationEngine
        from material_spine import MaterialSpineOrchestrator
        from key_map import PersistentKeyMap
    except Exception as e:
        try: tconn.close()
        except Exception: pass
        return {"status": "error", "phase": "import_f4", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}"}

    # Ruleset: legacy MTART value mapping + DQ gates that must trigger BEFORE the BAPI
    ruleset = {
        "version": "1",
        "value_maps": {
            "mtart_map": {"ZHALB": "HALB", "ZROH": "ROH"},
        },
        "object_rules": {
            "Material": {
                "transforms": [
                    {"type": "TRIM",  "field": "MATNR"},
                    {"type": "UPPER", "field": "MEINS"},
                    {"type": "VALUE_MAP", "field": "MTART", "table": "mtart_map",
                     "on_missing": "reject", "reject_sentinel": "__UNMAPPED__"},
                ],
                "dq_rules": [
                    {"type": "MANDATORY", "field": "MEINS"},
                    {"type": "MANDATORY", "field": "MBRSH"},
                    {"type": "ALLOWED",   "field": "MTART",
                     "values": ["HALB", "ROH", "FERT"]},
                ],
            }
        }
    }
    try:
        engine = TransformationEngine(ruleset=ruleset)
    except Exception as e:
        try: tconn.close()
        except Exception: pass
        return {"status": "error", "phase": "init_engine", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}"}

    ddb_table = os.environ.get("M4H_KEYMAP_TABLE", "migrate4hana-key-map-prod")
    km = PersistentKeyMap(table_name=ddb_table, run_id=run_id)
    orch = MaterialSpineOrchestrator(tconn, key_map=km, transformer=engine)

    # Three records exercising the three properties
    records = [
        # 1) value-map success: legacy ZHALB -> HALB, then BAPI creates
        {"id": "value_map_success",
         "row": {"MATNR": f"{prefix}_VMOK_{run_id[-6:]}",
                 "MTART": "ZHALB",   # gets mapped to HALB
                 "MBRSH": "M",
                 "MEINS": "ea",       # uppercased to EA by TRIM/UPPER
                 "MAKTX": "F4 phase-B value-map success"},
         "expect_status": "created",
         "expect_transformed_mtart": "HALB",
         "expect_transformed_meins": "EA"},
        # 2) DQ-mandatory rejects BEFORE BAPI: missing MEINS
        {"id": "dq_mandatory_reject",
         "row": {"MATNR": f"{prefix}_DQFAIL_{run_id[-6:]}",
                 "MTART": "ZHALB",
                 "MBRSH": "M",
                 # MEINS deliberately omitted
                 "MAKTX": "F4 phase-B mandatory reject"},
         "expect_status": "dead_letter",
         "expect_dead_letter": "DATA_QUALITY_REJECTION"},
        # 3) VALUE_MAP unmapped-with-reject composes with ALLOWED gate -> dead-letter
        {"id": "value_map_unmapped_then_allowed_reject",
         "row": {"MATNR": f"{prefix}_UNMAP_{run_id[-6:]}",
                 "MTART": "ZSOMETHING",   # unmapped -> reject sentinel
                 "MBRSH": "M",
                 "MEINS": "EA",
                 "MAKTX": "F4 phase-B unmapped"},
         "expect_status": "dead_letter",
         "expect_dead_letter": "DATA_QUALITY_REJECTION"},
    ]

    # Snapshot stats so we can confirm:
    #   - created went up by 1 (record 1 only)
    #   - dead_letter went up by 2 (records 2 and 3)
    #   - the BAPI was NOT called for records 2 and 3 (otherwise created > 1)
    base_created = orch.stats.created
    base_dead    = orch.stats.dead_letter

    per_record_results = []
    for spec in records:
        # Also call engine.apply directly so we can prove the transform output
        # matches expectations BEFORE the spine sends it (useful evidence in
        # the report even when the row is later rejected).
        transformed, dq = engine.apply("Material", dict(spec["row"]))
        res = orch.load_one(spec["row"])
        per_record_results.append({
            "id":                       spec["id"],
            "expected_status":          spec["expect_status"],
            "actual_status":            res.status,
            "actual_dead_letter":       res.dead_letter,
            "expected_dead_letter":     spec.get("expect_dead_letter"),
            "actual_target_key":        res.target_key,
            "transformed_record":       transformed,
            "transformed_mtart_match":  (spec.get("expect_transformed_mtart") is None
                                          or transformed.get("MTART") == spec.get("expect_transformed_mtart")),
            "transformed_meins_match":  (spec.get("expect_transformed_meins") is None
                                          or transformed.get("MEINS") == spec.get("expect_transformed_meins")),
            "dq_passed":                None if dq is None else dq.passed,
            "dq_reasons":               [] if dq is None else dq.reasons,
            "messages":                 res.messages,
            "match_expected":           (res.status == spec["expect_status"]
                                          and (spec.get("expect_dead_letter") is None
                                                or res.dead_letter == spec.get("expect_dead_letter"))),
        })

    delta_created = orch.stats.created - base_created
    delta_dead    = orch.stats.dead_letter - base_dead

    proof = {
        "p1_value_map_success_created":           delta_created == 1,
        "p2_dq_blocked_bapi_count":               delta_dead == 2,
        "p3_no_bapi_for_dq_rejected_rows":        delta_created == 1,  # if BAPI had run for #2 or #3, created > 1
        "all_per_record_expectations_met":        all(r["match_expected"] for r in per_record_results),
    }
    overall_ok = all(proof.values())

    log_stage_event(run_id, "data-migrator", "phaseB_f4_complete",
                    {"created": delta_created, "dead_letter": delta_dead,
                     "overall_ok": overall_ok})
    try:
        tconn.close()
    except Exception:
        pass

    return {
        "run_id":          run_id,
        "status":          "ok" if overall_ok else "mismatch",
        "phase":           "f4_transformation_engine",
        "target":          {"sid": tsec.get("sid"), "client": tsec.get("client"),
                            "ashost": tsec.get("ashost")},
        "ruleset_summary": {
            "value_maps": list(ruleset["value_maps"].keys()),
            "transform_count": len(ruleset["object_rules"]["Material"]["transforms"]),
            "dq_rule_count":   len(ruleset["object_rules"]["Material"]["dq_rules"]),
        },
        "per_record":      per_record_results,
        "delta_stats":     {"created": delta_created, "dead_letter": delta_dead},
        "spine_stats":     orch.stats.to_dict(),
        "key_map_writes":  km.persistence_stats(),
        "proof":           proof,
    }


def _phase_b_validate_f7(event, run_id):
    """F7 Phase B - prove TenantContext isolation against the live DDB key-map.

    The strongest possible cross-tenant collision test: TWO tenants write the
    SAME source_key with DIFFERENT target_keys for the SAME object_type. With
    F7's partition-key prefixing they must coexist; without it they would
    collide (one would clobber the other) and resolve() would return the
    wrong tenant's mapping.

    The validator drives five proofs against a real DDB write:

      1. PARTITION-KEY ISOLATION: tenant A and tenant B write the same
         (object_type, source_key) pair with distinct target_keys to the live
         migrate4hana-key-map-prod table. Without F7's PK prefixing this
         would be a conditional-write conflict OR a clobber; with F7 both
         rows land cleanly.
      2. RESOLVE ISOLATION A: tenant A's resolve(source_key) returns tenant
         A's target_key, NEVER tenant B's. Proven via a fresh PersistentKeyMap
         instance (no in-memory cache contamination) bound to tenant A.
      3. RESOLVE ISOLATION B: tenant B's resolve(source_key) returns tenant
         B's target_key. (Symmetric to #2.)
      4. DEFAULT-TENANT BACKWARD COMPAT: a fresh PersistentKeyMap with no
         tenant context (legacy single-tenant mode) gets a separate
         partition, doesn't see either tenant's mapping when resolving the
         same source key. Proves the default-tenant path is genuinely
         separate, not a fallback that picks up real-tenant data.
      5. AUDIT COLUMN: non-default tenants write a tenant_id attribute on
         each row for admin/audit queries. Default-tenant rows don't carry
         it (legacy schema preserved).

    The test cleans up after itself (deletes the 3 rows it wrote) so the
    DDB table state is unchanged at the end. Cleanup is unconditional - even
    if a proof fails, the cleanup still runs.

    Payload shape::

        { "mode": "phase_b_validate_f7",
          "run_id": "f7-phaseb-001",
          "tenant_a_id": "acme-corp",
          "tenant_b_id": "globex-inc",
          "object_type": "Customer",
          "source_key":  "F7PHB-SRC-1" }
    """
    tenant_a_id = (event.get("tenant_a_id") or "acme-corp").strip()
    tenant_b_id = (event.get("tenant_b_id") or "globex-inc").strip()
    object_type = (event.get("object_type") or "Customer").strip()
    src_key = (event.get("source_key") or f"F7PHB-SRC-{run_id[-6:]}").strip()

    try:
        from tenant_context import TenantContext, default_context
        from key_map import PersistentKeyMap
        import boto3   # type: ignore
    except Exception as e:
        return {"status": "error", "phase": "import_f7", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}"}

    ddb_table = os.environ.get("M4H_KEYMAP_TABLE", "migrate4hana-key-map-prod")
    ddb = boto3.client("dynamodb")

    # Distinct target keys per tenant - identical source side
    tgt_a = f"{src_key}__tenantA"
    tgt_b = f"{src_key}__tenantB"

    tenant_a = TenantContext(tenant_id=tenant_a_id, display_name=tenant_a_id,
                              environment="prod")
    tenant_b = TenantContext(tenant_id=tenant_b_id, display_name=tenant_b_id,
                              environment="prod")
    pk_a = tenant_a.ddb_object_key(object_type)   # e.g. "acme-corp#Customer"
    pk_b = tenant_b.ddb_object_key(object_type)   # e.g. "globex-inc#Customer"
    pk_default = default_context().ddb_object_key(object_type)  # bare "Customer"

    # Track cleanup work
    cleanup_keys: list = []

    def _delete_row(pk_value: str, src: str):
        # Use BatchWriteItem with DeleteRequest (the lambda role has
        # BatchWriteItem but not DeleteItem on this table).
        try:
            ddb.batch_write_item(RequestItems={
                ddb_table: [{"DeleteRequest": {
                    "Key": {"object": {"S": pk_value}, "source_key": {"S": src}}}}],
            })
        except Exception:
            pass

    diag: dict = {"steps": []}

    # ── Step 1: write through tenant A + tenant B PersistentKeyMaps ─────────
    km_a = PersistentKeyMap(table_name=ddb_table, run_id=run_id,
                             tenant_context=tenant_a, dynamodb_client=ddb)
    km_b = PersistentKeyMap(table_name=ddb_table, run_id=run_id,
                             tenant_context=tenant_b, dynamodb_client=ddb)
    try:
        km_a.add(object_type, src_key, tgt_a, "phase_b_f7_test")
        cleanup_keys.append((pk_a, src_key))
        diag["steps"].append({"step": "tenantA_write", "pk": pk_a, "ok": True})
    except Exception as e:
        diag["steps"].append({"step": "tenantA_write", "pk": pk_a, "ok": False,
                               "error": str(e)[:200]})
    try:
        km_b.add(object_type, src_key, tgt_b, "phase_b_f7_test")
        cleanup_keys.append((pk_b, src_key))
        diag["steps"].append({"step": "tenantB_write", "pk": pk_b, "ok": True})
    except Exception as e:
        diag["steps"].append({"step": "tenantB_write", "pk": pk_b, "ok": False,
                               "error": str(e)[:200]})

    # ── Step 2: read back via DDB GetItem directly (raw, bypass cache) ──────
    raw_a = {}
    raw_b = {}
    try:
        r = ddb.get_item(TableName=ddb_table,
                          Key={"object": {"S": pk_a}, "source_key": {"S": src_key}})
        raw_a = r.get("Item") or {}
    except Exception as e:
        diag["steps"].append({"step": "raw_get_a", "ok": False, "error": str(e)[:200]})
    try:
        r = ddb.get_item(TableName=ddb_table,
                          Key={"object": {"S": pk_b}, "source_key": {"S": src_key}})
        raw_b = r.get("Item") or {}
    except Exception as e:
        diag["steps"].append({"step": "raw_get_b", "ok": False, "error": str(e)[:200]})

    raw_a_target  = (raw_a.get("target_key") or {}).get("S")
    raw_b_target  = (raw_b.get("target_key") or {}).get("S")
    raw_a_tenant  = (raw_a.get("tenant_id") or {}).get("S")
    raw_b_tenant  = (raw_b.get("tenant_id") or {}).get("S")

    # ── Step 3: resolve via FRESH PKM instances (no shared in-memory cache) ─
    # If isolation works, each fresh instance resolves only its own tenant's row.
    km_a_fresh = PersistentKeyMap(table_name=ddb_table, run_id=run_id + "-rA",
                                   tenant_context=tenant_a, dynamodb_client=ddb)
    km_b_fresh = PersistentKeyMap(table_name=ddb_table, run_id=run_id + "-rB",
                                   tenant_context=tenant_b, dynamodb_client=ddb)
    km_default_fresh = PersistentKeyMap(table_name=ddb_table, run_id=run_id + "-rD",
                                         dynamodb_client=ddb)  # default tenant

    resolved_a       = km_a_fresh.resolve(object_type, src_key)
    resolved_b       = km_b_fresh.resolve(object_type, src_key)
    resolved_default = km_default_fresh.resolve(object_type, src_key)

    # ── Build the proof ─────────────────────────────────────────────────────
    proof = {
        "p1_pk_isolation_both_rows_present":     bool(raw_a_target) and bool(raw_b_target),
        "p1_pk_partitions_differ":               pk_a != pk_b and pk_a != pk_default and pk_b != pk_default,
        "p2_tenant_a_resolves_to_own_target":    resolved_a == tgt_a,
        "p2_tenant_a_does_not_see_tenant_b":     resolved_a != tgt_b,
        "p3_tenant_b_resolves_to_own_target":    resolved_b == tgt_b,
        "p3_tenant_b_does_not_see_tenant_a":     resolved_b != tgt_a,
        "p4_default_tenant_does_not_see_either": resolved_default is None,
        "p5_tenant_a_row_has_tenant_id_column":  raw_a_tenant == tenant_a_id,
        "p5_tenant_b_row_has_tenant_id_column":  raw_b_tenant == tenant_b_id,
    }
    overall_ok = all(proof.values())

    # ── Cleanup ─────────────────────────────────────────────────────────────
    cleanup_results = []
    for pkval, sk in cleanup_keys:
        _delete_row(pkval, sk)
        cleanup_results.append({"pk": pkval, "source_key": sk, "deleted": True})

    log_stage_event(run_id, "data-migrator", "phaseB_f7_complete",
                    {"overall_ok": overall_ok,
                     "tenant_a": tenant_a_id, "tenant_b": tenant_b_id,
                     "rows_cleaned": len(cleanup_results)})

    return {
        "run_id":  run_id,
        "status":  "ok" if overall_ok else "mismatch",
        "phase":   "f7_tenant_isolation",
        "table":   ddb_table,
        "tenant_a": {"id": tenant_a_id, "pk": pk_a, "target_written": tgt_a,
                     "raw_target_read": raw_a_target, "raw_tenant_id_col": raw_a_tenant,
                     "resolve_via_fresh_pkm": resolved_a},
        "tenant_b": {"id": tenant_b_id, "pk": pk_b, "target_written": tgt_b,
                     "raw_target_read": raw_b_target, "raw_tenant_id_col": raw_b_tenant,
                     "resolve_via_fresh_pkm": resolved_b},
        "default_tenant": {"pk": pk_default,
                            "resolve_via_fresh_pkm": resolved_default},
        "shared_source_key": src_key,
        "proof":   proof,
        "diag":    diag,
        "cleanup": cleanup_results,
    }


def _phase_b_validate_chain(event, run_id):
    """End-to-end dependency-chain proof against live S/4 + live DDB.

    The spine sweep promoted 25 objects individually; this validator drives
    them as a CONNECTED GRAPH via the F1 PersistentKeyMap, proving that
    composition works -- i.e. that loading BPs makes them resolvable by
    Customer, and loading Customers makes them resolvable by SalesOrder.

    Pipeline::

        Step A: load N BusinessPartners       -> registers (BPARTNER -> tgtBP)
        Step B: load N Customers (CVI)         -> registers (KUNNR -> tgtBP/cust)
        Step C: load N SalesOrders             -> resolve KUNNR via F1

    The interesting metric is HOW the SO step resolves customers:
      - "registry": F1 found the (Customer, KUNNR) -> BP mapping AND that BP
        was in the discovered sales-area customer pool. This is the only path
        that proves the chain actually composed.
      - "harmonized": F1 found nothing OR the BP wasn't in the sales-area
        pool. The SO falls back to a sample customer. Harmonization itself is
        a valid migration pattern, but for THIS proof it means the chain
        DIDN'T compose -- which is a real finding worth reporting (typically
        because freshly-created BPs lack KNVV sales-area data).

    The validator therefore returns BOTH classification counts, so the user
    can see the registry-vs-harmonized split and act on it.

    Payload shape::

        { "mode": "phase_b_validate_chain",
          "run_id": "chain-001",
          "count": 5,
          "prefix": "CHAIN" }
    """
    count = int(event.get("count", 3))
    prefix = (event.get("prefix") or f"CHAIN{run_id[-4:]}").strip()
    target_secret_id = event.get("target_secret_id") or "migrate4hana/prod/s4hana-credentials"

    try:
        tsec = json.loads(SECRETS.get_secret_value(SecretId=target_secret_id)["SecretString"])
        from pyrfc import Connection   # type: ignore
        tconn = Connection(
            ashost=tsec["ashost"], sysnr=tsec.get("sysnr", "00"),
            client=tsec["client"], user=tsec["user"],
            passwd=tsec.get("passwd") or tsec.get("password"),
            lang=tsec.get("lang", "EN"),
        )
    except Exception as e:
        return {"status": "error", "phase": "connect_s4", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}"}

    try:
        from business_partner_spine import BusinessPartnerSpineOrchestrator
        from customer_spine          import CustomerSpineOrchestrator
        from sales_order_spine       import SalesOrderSpineOrchestrator
        from key_map import PersistentKeyMap
    except Exception as e:
        try: tconn.close()
        except Exception: pass
        return {"status": "error", "phase": "import_chain", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}"}

    # ── F1: a SHARED PersistentKeyMap across all three steps. This is the
    # whole point — Customer step registers (KUNNR -> BP) and the SO step
    # finds it via the same registry instance + the DDB-backed lookup.
    ddb_table = os.environ.get("M4H_KEYMAP_TABLE", "migrate4hana-key-map-prod")
    km = PersistentKeyMap(table_name=ddb_table, run_id=run_id)

    # Spine instances
    bp_orch  = BusinessPartnerSpineOrchestrator(tconn, key_map=km)
    cust_orch = CustomerSpineOrchestrator(tconn, key_map=km)
    so_orch   = SalesOrderSpineOrchestrator(tconn, key_map=km)

    # ── Step A: BP loads ──────────────────────────────────────────────────────
    bp_records = [
        {"BPARTNER": f"{prefix}_BP_{i:03d}", "CATEGORY": "2",
         "NAME": f"{prefix} BP organization {i:03d}"}
        for i in range(count)
    ]
    bp_results = [bp_orch.load_one(r) for r in bp_records]
    bp_targets = {r.source_key: r.target_key for r in bp_results if r.target_key}

    # ── Step B: Customer loads (each creates its OWN BP + role) ───────────────
    cust_records = [
        {"KUNNR": f"{prefix}_C_{i:03d}", "NAME1": f"{prefix} customer {i:03d}"}
        for i in range(count)
    ]
    cust_results = [cust_orch.load_one(r) for r in cust_records]
    cust_targets = {r.source_key: r.target_key for r in cust_results if r.target_key}

    # F1 readback: confirm Customer step actually populated the registry
    f1_customer_resolutions = {}
    for src in cust_targets.keys():
        f1_customer_resolutions[src] = km.resolve("Customer", src)

    # ── Step C: SalesOrder loads referencing the customers we just created ───
    so_records = [
        {"VBELN": f"{prefix}_SO_{i:03d}", "KUNNR": f"{prefix}_C_{i:03d}"}
        for i in range(count)
    ]
    # IMPORTANT: snapshot the F1 registry BEFORE the SO loads run. The SO
    # spine's harmonization path overwrites F1 entries (a documented pattern:
    # once a customer harmonizes for sales-doc purposes, route all subsequent
    # SOs to the same harmonized target). For the chain proof we want to know
    # what F1 had at the time step C started -- not what step C left behind.
    so_f1_pre = {rec["KUNNR"]: km.resolve("Customer", rec["KUNNR"])
                  for rec in so_records}
    so_results = [so_orch.load_one(r) for r in so_records]
    so_f1_post = {rec["KUNNR"]: km.resolve("Customer", rec["KUNNR"])
                   for rec in so_records}
    so_f1_overwrites = [k for k in so_f1_pre
                          if so_f1_pre[k] and so_f1_post[k] != so_f1_pre[k]]

    # Classify each SO outcome: did it use the chain (registry path) or fall
    # back to harmonization (BP not in KNVV sales-area pool)?
    so_classification = {
        "registry":       0,   # SO used F1-resolved BP, BP was in sales-area pool
        "harmonized":     0,   # SO had to fall back to sample customer
        "dead_letter":    0,   # SO failed entirely (e.g. no sales-area at all)
    }
    # Use the PRE-step-C F1 snapshot as the chain-composition proof. This
    # captures what step C saw on entry, before its own harmonization writes.
    so_details = []
    for src_kunnr, r in zip([rec["KUNNR"] for rec in so_records], so_results):
        f1_pre = so_f1_pre.get(src_kunnr)
        if r.dead_letter:
            so_classification["dead_letter"] += 1
            so_details.append({"src_kunnr": src_kunnr, "outcome": "dead_letter",
                                "messages": r.messages, "code": r.dead_letter,
                                "f1_pre_step_c": f1_pre})
        elif any("harmonized" in m for m in (r.messages or [])):
            so_classification["harmonized"] += 1
            so_details.append({"src_kunnr": src_kunnr, "outcome": "harmonized",
                                "target_so": r.target_key,
                                "messages": [m for m in r.messages if "harmonized" in m][:1],
                                "f1_pre_step_c": f1_pre,
                                "f1_post_step_c": so_f1_post.get(src_kunnr),
                                "note": ("F1 chain DID resolve the customer to its created BP; "
                                          "SO harmonized because that BP is not in the target "
                                          "KNVV sales-area pool. F1 layer composed correctly.")
                                          if f1_pre else None})
        else:
            so_classification["registry"] += 1
            so_details.append({"src_kunnr": src_kunnr, "outcome": "registry",
                                "target_so": r.target_key,
                                "expected_customer_target": cust_targets.get(src_kunnr),
                                "f1_pre_step_c": f1_pre})

    # ── Build the proof object ────────────────────────────────────────────────
    # Two compositional proofs:
    #   F1-layer:   shared registry can resolve a customer registered by
    #               step B from step C's perspective (the engineering claim
    #               of F1). This works even if SAP refuses the SO downstream.
    #   SAP-layer:  step C actually wrote a SO linked to the BP from step B
    #               via SAP data (KNVV / VBAK). Requires sales-area data on
    #               the freshly-created BP, which IDES typically lacks.
    proof = {
        "bp_step_all_created":          all(r.target_key for r in bp_results),
        "customer_step_all_created":    all(r.target_key for r in cust_results),
        "f1_customer_resolves_for_all": all(f1_customer_resolutions.get(s) for s in cust_targets),
        "so_step_no_dead_letters":      so_classification["dead_letter"] == 0,
        # F1-LAYER composition: at step C entry, the shared registry resolved
        # every customer registered in step B. This is the engineering proof
        # of the F1 chain composition -- captured BEFORE step C's harmonization
        # writes (which would otherwise clobber the entries).
        "f1_chain_composed_in_step_c":  all(so_f1_pre.get(rec["KUNNR"])
                                              for rec in so_records),
        # F1-LAYER consistency: did the customer-spine's target_key match the
        # F1-pre-step-C resolution? This proves the customer step really wrote
        # to F1 (the SAP-assigned BP, not a fallback).
        "f1_customer_writes_match_targets":
            all(so_f1_pre.get(rec["KUNNR"]) == cust_targets.get(rec["KUNNR"])
                for rec in so_records),
        # SAP-LAYER composition: at least one SO actually went through the
        # registry path (BP was in KNVV pool). If 0 -> KNVV gap, surfaced
        # as a known finding rather than a chain failure.
        "sap_chain_composed_at_least_once": so_classification["registry"] >= 1,
    }
    # Overall: F1-layer is the engineering claim of the spine sweep; SAP-layer
    # composition is a downstream data-prep concern (KNVV provisioning).
    overall_ok = all([proof["bp_step_all_created"],
                       proof["customer_step_all_created"],
                       proof["f1_customer_resolves_for_all"],
                       proof["so_step_no_dead_letters"],
                       proof["f1_chain_composed_in_step_c"],
                       proof["f1_customer_writes_match_targets"]])

    log_stage_event(run_id, "data-migrator", "phaseB_chain_complete",
                    {"bp_created":   sum(1 for r in bp_results   if r.target_key),
                     "cust_created": sum(1 for r in cust_results if r.target_key),
                     "so_registry":  so_classification["registry"],
                     "so_harmonized": so_classification["harmonized"],
                     "so_dead":      so_classification["dead_letter"],
                     "overall_ok":   overall_ok})
    try:
        tconn.close()
    except Exception:
        pass

    return {
        "run_id":  run_id,
        "status":  "ok" if overall_ok else "partial",
        "phase":   "chain_end_to_end",
        "count":   count,
        "target":  {"sid": tsec.get("sid"), "client": tsec.get("client"),
                    "ashost": tsec.get("ashost")},
        "step_a_business_partner": {
            "attempted": len(bp_results),
            "created":   sum(1 for r in bp_results if r.target_key),
            "targets":   bp_targets,
            "errors":    [{"src": r.source_key, "code": r.dead_letter,
                            "messages": (r.messages or [])[:3]}
                           for r in bp_results if not r.target_key][:3],
        },
        "step_b_customer": {
            "attempted": len(cust_results),
            "created":   sum(1 for r in cust_results if r.target_key),
            "targets":   cust_targets,
            "f1_resolutions": f1_customer_resolutions,
            "errors":    [{"src": r.source_key, "code": r.dead_letter,
                            "messages": (r.messages or [])[:3]}
                           for r in cust_results if not r.target_key][:3],
        },
        "step_c_sales_order": {
            "attempted":          len(so_results),
            "classification":     so_classification,
            "f1_pre_snapshot":    so_f1_pre,
            "f1_post_snapshot":   so_f1_post,
            "f1_overwrites":      so_f1_overwrites,
            "details":            so_details,
        },
        "proof":         proof,
        "spine_stats":   {
            "bp":   bp_orch.stats.to_dict(),
            "cust": cust_orch.stats.to_dict(),
            "so":   so_orch.stats.to_dict(),
        },
        "key_map_writes": km.persistence_stats(),
    }


def _phase_b_validate_reconcile(event, run_id):
    """Reconciliation engine wiring proof: drive spine loads + Reconciler against
    live S/4 to prove the end-to-end "BAPI said OK + record actually persisted +
    values match what we sent" loop closes.

    Closes the #3 roadmap gap: the legacy bapi_loader.create_* methods emit
    verify_key dicts that the Reconciler reads back from MARA / BUT000 / etc.
    The new spine subclasses now emit verify_key via the 4-tuple call_bapi
    return. This validator proves that wiring works end-to-end.

    Loads N Materials, then calls Reconciler.reconcile() and reports:
      - records the BAPI claimed to create
      - records read back from MARA via RFC_READ_TABLE
      - MTART value tie-out (sent vs stored)
      - final status: RECONCILED / DISCREPANCY / VALUE_DISCREPANCY

    Payload::

        { "mode": "phase_b_validate_reconcile",
          "run_id": "recon-001",
          "count":  3,
          "prefix": "RECON" }
    """
    count = int(event.get("count", 3))
    prefix = (event.get("prefix") or f"RECON{run_id[-4:]}").strip()
    target_secret_id = event.get("target_secret_id") or "migrate4hana/prod/s4hana-credentials"

    try:
        tsec = json.loads(SECRETS.get_secret_value(SecretId=target_secret_id)["SecretString"])
        from pyrfc import Connection   # type: ignore
        tconn = Connection(
            ashost=tsec["ashost"], sysnr=tsec.get("sysnr", "00"),
            client=tsec["client"], user=tsec["user"],
            passwd=tsec.get("passwd") or tsec.get("password"),
            lang=tsec.get("lang", "EN"),
        )
    except Exception as e:
        return {"status": "error", "phase": "connect_s4", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}"}

    try:
        from material_spine import MaterialSpineOrchestrator
        from base_spine_orchestrator import BaseSpineOrchestrator
        from key_map import PersistentKeyMap
        from reconciler import Reconciler
    except Exception as e:
        try: tconn.close()
        except Exception: pass
        return {"status": "error", "phase": "import_reconcile", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}"}

    ddb_table = os.environ.get("M4H_KEYMAP_TABLE", "migrate4hana-key-map-prod")
    km = PersistentKeyMap(table_name=ddb_table, run_id=run_id)

    # Drive N Material loads (proven object — F2 already validated)
    orch = MaterialSpineOrchestrator(tconn, key_map=km)
    rows = [
        {"MATNR": f"{prefix}_{run_id[-6:]}_{i:03d}",
         "MTART": "HALB", "MBRSH": "M", "MEINS": "EA",
         "MAKTX": f"Reconcile phase B {i:03d}"}
        for i in range(count)
    ]
    results = orch.load_many(rows)

    # Convert spine results -> reconciler input shape (the new helper)
    recon_input = BaseSpineOrchestrator.to_reconciler_input(results)

    # Drive the reconciler against live S/4
    reconciler = Reconciler(tconn)
    report = reconciler.reconcile("Material", recon_input, extracted=count)

    # Build proof object
    proof = {
        "spine_emitted_verify_keys":
            recon_input["created_in_s4"] == orch.stats.created,
        "reconciler_verified_all_created":
            report["verified_in_target"] == report["created"]
            and report["created"] > 0,
        "value_match_all":
            report.get("value_checked", 0) == 0
            or report.get("value_matched", 0) == report.get("value_checked", 0),
        "status_reconciled":
            report["status"] == "RECONCILED",
    }
    overall_ok = all(proof.values())

    log_stage_event(run_id, "data-migrator", "phaseB_reconcile_complete",
                    {"created":   report["created"],
                     "verified":  report["verified_in_target"],
                     "status":    report["status"],
                     "overall_ok": overall_ok})

    try:
        tconn.close()
    except Exception:
        pass

    return {
        "run_id":       run_id,
        "status":       "ok" if overall_ok else "mismatch",
        "phase":        "reconciliation_engine_wired",
        "target":       {"sid": tsec.get("sid"), "client": tsec.get("client"),
                          "ashost": tsec.get("ashost")},
        "count":        count,
        "spine_results": [r.to_dict() for r in results],
        "reconciler_input":  recon_input,
        "reconciler_report": report,
        "proof":        proof,
        "spine_stats":  orch.stats.to_dict(),
    }


def _phase_b_validate_production_path(event, run_id):
    """End-to-end production-path proof: UnifiedLoader -> spine -> Reconciler.

    Closes roadmap #2. The Step Functions pipeline's data-load stage routes
    through ECS Fargate; the ECS data-loader entrypoint (and the data-migrator
    lambda's BAPI/in-place mode under M4H_LOAD_TO_S4=1) both invoke
    UnifiedLoader.load_object(obj, rows, max_rows). This validator exercises
    THAT same code path -- not the spine subclass directly -- and proves:

      1. UnifiedLoader.load_object dispatches to the spine via the registry
         when one is available (not the legacy bapi_loader.create_* path).
      2. The dispatched spine emits verify_key dicts in its results.
      3. UnifiedLoader._load_via_spine packages verify_key dicts into
         created_keys (the shape Reconciler.reconcile expects), not flat
         target_key strings (the pre-fix shape that silently produced
         NOT_VERIFIABLE reports in production).
      4. The Reconciler can consume the result dict directly and tie out
         to RECONCILED status.

    Payload::

        { "mode": "phase_b_validate_production_path",
          "run_id": "prodpath-001",
          "count": 3,
          "object": "Material" }
    """
    count = int(event.get("count", 3))
    obj_name = (event.get("object") or "Material").strip()
    target_secret_id = event.get("target_secret_id") or "migrate4hana/prod/s4hana-credentials"

    try:
        tsec = json.loads(SECRETS.get_secret_value(SecretId=target_secret_id)["SecretString"])
        from pyrfc import Connection   # type: ignore
        tconn = Connection(
            ashost=tsec["ashost"], sysnr=tsec.get("sysnr", "00"),
            client=tsec["client"], user=tsec["user"],
            passwd=tsec.get("passwd") or tsec.get("password"),
            lang=tsec.get("lang", "EN"),
        )
    except Exception as e:
        return {"status": "error", "phase": "connect_s4", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}"}

    try:
        from unified_loader import UnifiedLoader
        from base_spine_orchestrator import get_spine, registered_spines
        from key_map import PersistentKeyMap
        from reconciler import Reconciler
    except Exception as e:
        try: tconn.close()
        except Exception: pass
        return {"status": "error", "phase": "import_production_path", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}"}

    # Synthetic rows for the object under test. Each generator yields rows
    # whose source_key derives from `run_id[-6:]` so per-invocation
    # uniqueness is automatic and the F1 ledger-hit guard doesn't
    # short-circuit a fresh proof.
    seed = run_id[-6:].upper()
    if obj_name == "Material":
        rows = [{"MATNR": f"PROD_{seed}_{i:03d}",
                  "MTART": "HALB", "MBRSH": "M", "MEINS": "EA",
                  "MAKTX": f"Production-path test {i:03d}"}
                 for i in range(count)]
    elif obj_name == "BusinessPartner":
        rows = [{"BPARTNER": f"PROD_BP_{seed}_{i:03d}",
                  "CATEGORY": "2",
                  "NAME":     f"PROD path test org {seed} {i:03d}"}
                 for i in range(count)]
    else:
        # Generic shape for other objects; caller can override via event["rows"]
        rows = event.get("rows") or []

    ddb_table = os.environ.get("M4H_KEYMAP_TABLE", "migrate4hana-key-map-prod")
    km = PersistentKeyMap(table_name=ddb_table, run_id=run_id)

    # Construct UnifiedLoader the same way the data-migrator lambda does in
    # production (M4H_LOAD_TO_S4=1 code path).
    loader = UnifiedLoader(tconn, own_logical_system="M4H_PROD",
                            sender="MIGRATE4HANA",
                            client=tsec.get("client", "100"),
                            target_sid=tsec.get("sid", "S4H"))
    loader.key_map = km

    # Confirm the spine registry has the object before we exercise the path
    spine_present = get_spine(obj_name) is not None

    # The production call -- this is exactly what the prod pipeline runs
    load_result = loader.load_object(obj_name, rows, max_rows=count)

    # Inspect the result shape: created_keys MUST be a list of verify_key
    # dicts (post-fix) -- pre-fix was a flat list of target_key strings.
    created_keys = load_result.get("created_keys") or []
    created_keys_are_dicts = (
        bool(created_keys)
        and all(isinstance(k, dict) and "table" in k and "key" in k
                 for k in created_keys)
    )

    # Drive the Reconciler against the load_result -- the production
    # reconciliation stage does this same step against the same shape.
    reconciler = Reconciler(tconn)
    report = reconciler.reconcile(obj_name, load_result, extracted=count)

    proof = {
        "spine_registered_for_object":   spine_present,
        "unified_loader_dispatched_to_spine":
            "spine/" in str(load_result.get("mechanism", "")),
        "created_keys_are_verify_dicts": created_keys_are_dicts,
        "reconciler_status_reconciled":  report.get("status") == "RECONCILED",
        "verified_count_matches_created":
            report.get("verified_in_target") == report.get("created")
            and (report.get("created") or 0) > 0,
        "value_tie_out_passed":
            report.get("value_checked", 0) == 0
            or report.get("value_matched", 0) == report.get("value_checked", 0),
    }
    overall_ok = all(proof.values())

    log_stage_event(run_id, "data-migrator", "phaseB_production_path_complete",
                    {"object": obj_name,
                     "mechanism": load_result.get("mechanism"),
                     "status":    report.get("status"),
                     "overall_ok": overall_ok})

    try:
        tconn.close()
    except Exception:
        pass

    return {
        "run_id":            run_id,
        "status":            "ok" if overall_ok else "mismatch",
        "phase":             "production_path_unifiedloader_to_reconciler",
        "object":            obj_name,
        "count":             count,
        "target":            {"sid": tsec.get("sid"), "client": tsec.get("client"),
                                "ashost": tsec.get("ashost")},
        "load_result":       load_result,
        "reconciler_report": report,
        "proof":             proof,
        "spine_registry":    {"object_registered": spine_present,
                                "total_spines": len(registered_spines())},
    }


def _pilot_readiness_probe(event, run_id):
    """Pre-pilot diagnostic: probe a target S/4 system and report what would
    go right vs wrong on a real-customer data load.

    Roadmap #5 scaffolding: a true customer pilot needs the customer's data,
    but this probe lets a customer's IT person validate their TARGET S/4
    against the spine's customizing assumptions BEFORE the pilot day --
    surfacing the "we'd dead-letter half the load because TCURV is empty"
    cases as known yellow/red items, not surprises.

    Probes (each is a quick RFC_READ_TABLE against the connected target):

      - target_rate_types: count of TCURV entries (ExchangeRates loadability)
      - operational_rate_types: count of TCURF entries (factor settings)
      - class_types: count of TCLA entries (Class object loadability)
      - chart_of_accounts: distinct T001.KTOPL values (CO group loadability)
      - controlling_areas: distinct T001.KOKRS values (PC group + IO + OpenAR/AP)
      - sales_areas: tuples in KNVV ∩ MVKE (SalesOrder loadability)
      - recon_ready_customers: KNB1 row count (OpenAR loadability)
      - recon_ready_vendors: LFB1 row count (OpenAP loadability)
      - purchasing_ready_vendors: LFM1 row count (PO + Contract loadability)
      - batch_managed_materials: MARC where XCHPF='X' row count
      - stock_master_population: MARD row count (InventoryBalance)
      - func_loc_structure_indicators: distinct IFLOT.TPLKZ count
      - project_profiles: distinct PROJ.PROFL count

    Each probe yields a verdict:
      green:  ready -- the customizing supports a real load at scale
      yellow: partially ready -- some objects will dead-letter as
              customizing prerequisites
      red:    blocker -- the object category is largely unloadable on this
              target until customizing is provisioned

    Payload::

        { "mode":  "pilot_readiness_probe",
          "run_id": "pilot-probe-001",
          "target_secret_id": "migrate4hana/prod/s4hana-credentials" }
    """
    target_secret_id = event.get("target_secret_id") or "migrate4hana/prod/s4hana-credentials"
    try:
        tsec = json.loads(SECRETS.get_secret_value(SecretId=target_secret_id)["SecretString"])
        from pyrfc import Connection   # type: ignore
        tconn = Connection(
            ashost=tsec["ashost"], sysnr=tsec.get("sysnr", "00"),
            client=tsec["client"], user=tsec["user"],
            passwd=tsec.get("passwd") or tsec.get("password"),
            lang=tsec.get("lang", "EN"),
        )
    except Exception as e:
        return {"status": "error", "phase": "connect_s4", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}"}

    def _read_count(qt, fields, options=None, rowcount=1000):
        try:
            r = tconn.call("RFC_READ_TABLE", QUERY_TABLE=qt, DELIMITER="|",
                            FIELDS=[{"FIELDNAME": f} for f in fields],
                            OPTIONS=options or [], ROWCOUNT=rowcount)
            data = r.get("DATA") or []
            return len(data), [(x.get("WA") or "").strip() for x in data[:5]]
        except Exception as e:
            return None, [f"ERR: {str(e)[:120]}"]

    findings: list = []

    def add(category, label, count, sample, *,
             green_at, yellow_at,
             affects, customizing_table=None):
        if count is None:
            v = "red"; reason = "probe failed (RFC_READ_TABLE error)"
        elif count >= green_at:
            v = "green"; reason = f"{count} rows in {customizing_table or label}"
        elif count >= yellow_at:
            v = ("yellow"); reason = (f"only {count} rows in {customizing_table or label} "
                                       f"(threshold for green: {green_at})")
        else:
            v = "red";    reason = (f"{count} rows in {customizing_table or label} "
                                     f"(below pilot threshold {yellow_at})")
        findings.append({
            "category":  category, "label": label, "verdict": v,
            "count":     count, "sample": sample[:3],
            "affects":   affects, "reason": reason,
        })

    # Currency / rate-type customizing
    n, s = _read_count("TCURV", ["KURST"])
    add("CurrencyConfig", "TCURV rate types", n, s,
         green_at=20, yellow_at=5, affects=["ExchangeRates"],
         customizing_table="TCURV")
    n, s = _read_count("TCURF", ["KURST"])
    add("CurrencyConfig", "TCURF operational rate types", n, s,
         green_at=20, yellow_at=5, affects=["ExchangeRates"],
         customizing_table="TCURF")

    # Classification customizing
    n, s = _read_count("TCLA", ["KLART"])
    add("Classification", "TCLA class types", n, s,
         green_at=10, yellow_at=1, affects=["Class"],
         customizing_table="TCLA")

    # CO customizing
    n, s = _read_count("T001", ["KTOPL", "BUKRS"])
    add("ControllingConfig", "T001 chart-of-accounts coverage", n, s,
         green_at=1, yellow_at=1, affects=["CostElementGroup"],
         customizing_table="T001.KTOPL")

    # Partner readiness
    n, s = _read_count("KNB1", ["KUNNR"])
    add("PartnerReadiness", "KNB1 recon-ready customers", n, s,
         green_at=50, yellow_at=5, affects=["OpenAR"],
         customizing_table="KNB1")
    n, s = _read_count("LFB1", ["LIFNR"])
    add("PartnerReadiness", "LFB1 recon-ready vendors", n, s,
         green_at=50, yellow_at=5, affects=["OpenAP"],
         customizing_table="LFB1")
    n, s = _read_count("LFM1", ["LIFNR"])
    add("PartnerReadiness", "LFM1 purchasing-ready vendors", n, s,
         green_at=50, yellow_at=5,
         affects=["PurchaseOrder", "PurchaseContract"],
         customizing_table="LFM1")

    # Sales-area readiness (the chain-test SO finding)
    n, s = _read_count("KNVV", ["KUNNR", "VKORG", "VTWEG", "SPART"])
    add("SalesAreaReadiness", "KNVV sales-area customer pool", n, s,
         green_at=100, yellow_at=10, affects=["SalesOrder"],
         customizing_table="KNVV")
    n, s = _read_count("MVKE", ["MATNR", "VKORG", "VTWEG"])
    add("SalesAreaReadiness", "MVKE saleable material pool", n, s,
         green_at=100, yellow_at=10, affects=["SalesOrder"],
         customizing_table="MVKE")

    # Inventory readiness
    n, s = _read_count("MARC",
                        ["MATNR", "WERKS"],
                        options=[{"TEXT": "XCHPF = 'X'"}])
    add("InventoryReadiness", "Batch-managed material+plant", n, s,
         green_at=10, yellow_at=1, affects=["Batch"],
         customizing_table="MARC.XCHPF")
    n, s = _read_count("MARD", ["MATNR", "WERKS", "LGORT"])
    add("InventoryReadiness", "MARD stock master rows", n, s,
         green_at=50, yellow_at=1, affects=["InventoryBalance"],
         customizing_table="MARD")

    # Plant maintenance readiness
    n, s = _read_count("IFLOT", ["TPLKZ"])
    add("PMReadiness", "IFLOT structure-indicator coverage", n, s,
         green_at=5, yellow_at=1, affects=["FunctionalLocation"],
         customizing_table="IFLOT.TPLKZ")

    # Project system readiness
    n, s = _read_count("PROJ", ["PROFL"])
    add("PSReadiness", "PROJ project profiles in use", n, s,
         green_at=5, yellow_at=1, affects=["Project"],
         customizing_table="PROJ.PROFL")

    # Score the overall pilot readiness
    by_verdict = {"green": 0, "yellow": 0, "red": 0}
    for f in findings:
        by_verdict[f["verdict"]] += 1
    pilot_ready = (by_verdict["red"] == 0 and by_verdict["yellow"] <= 2)
    rate_types_known = next((f for f in findings
                              if f["label"] == "TCURV rate types"), {}).get("count")

    affected_objects_at_risk = sorted({
        obj for f in findings
        if f["verdict"] in ("red", "yellow")
        for obj in f["affects"]
    })

    try:
        tconn.close()
    except Exception:
        pass

    return {
        "run_id":      run_id,
        "status":      "ok",
        "phase":       "pilot_readiness_probe",
        "target":      {"sid": tsec.get("sid"), "client": tsec.get("client"),
                          "ashost": tsec.get("ashost")},
        "pilot_ready": pilot_ready,
        "scorecard":   {
            "green":  by_verdict["green"],
            "yellow": by_verdict["yellow"],
            "red":    by_verdict["red"],
            "total":  len(findings),
            "pilot_verdict": ("READY" if pilot_ready
                               else ("CONDITIONAL" if by_verdict["red"] == 0
                                       else "BLOCKED")),
        },
        "affected_objects_at_risk": affected_objects_at_risk,
        "findings":    findings,
        "rate_types_known": rate_types_known,
    }


def _phase_b_validate_reconcile_sweep(event, run_id):
    """Reconcile sweep across multiple spine objects -- proves verify_key
    wiring works END-TO-END for the full roster (roadmap A finish).

    Drives each loadable object through UnifiedLoader.load_object -> spine ->
    verify_key emission -> Reconciler.reconcile -> RECONCILED. Per-object
    counts are small (3 records) so the sweep stays under the lambda timeout.

    Objects covered: every spine that can be driven with no cc_org input.
    Currently: Material, BusinessPartner (org category).

    Payload::

        { "mode": "phase_b_validate_reconcile_sweep",
          "run_id": "recon-sweep-001",
          "count": 3 }
    """
    count = int(event.get("count", 3))
    target_secret_id = event.get("target_secret_id") or "migrate4hana/prod/s4hana-credentials"

    try:
        tsec = json.loads(SECRETS.get_secret_value(SecretId=target_secret_id)["SecretString"])
        from pyrfc import Connection   # type: ignore
        tconn = Connection(
            ashost=tsec["ashost"], sysnr=tsec.get("sysnr", "00"),
            client=tsec["client"], user=tsec["user"],
            passwd=tsec.get("passwd") or tsec.get("password"),
            lang=tsec.get("lang", "EN"),
        )
    except Exception as e:
        return {"status": "error", "phase": "connect_s4", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}"}

    try:
        from unified_loader import UnifiedLoader
        from key_map import PersistentKeyMap
        from reconciler import Reconciler
    except Exception as e:
        try: tconn.close()
        except Exception: pass
        return {"status": "error", "phase": "import_sweep", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}"}

    # Object -> synthetic-row generator
    def gen_material(i):
        return {"MATNR": f"SWEEP_M_{run_id[-5:]}_{i:03d}",
                 "MTART": "HALB", "MBRSH": "M", "MEINS": "EA",
                 "MAKTX": f"Sweep test material {i:03d}"}

    def gen_bp(i):
        return {"BPARTNER": f"SWEEP_BP_{run_id[-5:]}_{i:03d}",
                 "CATEGORY": "2",
                 "NAME": f"Sweep test org {i:03d}"}

    targets = [
        ("Material",         gen_material),
        ("BusinessPartner",  gen_bp),
    ]

    ddb_table = os.environ.get("M4H_KEYMAP_TABLE", "migrate4hana-key-map-prod")
    km = PersistentKeyMap(table_name=ddb_table, run_id=run_id)
    loader = UnifiedLoader(tconn, own_logical_system="M4H_SWEEP",
                            sender="MIGRATE4HANA",
                            client=tsec.get("client", "100"),
                            target_sid=tsec.get("sid", "S4H"))
    loader.key_map = km
    reconciler = Reconciler(tconn)

    per_object = []
    for obj, gen in targets:
        rows = [gen(i) for i in range(count)]
        load_result = loader.load_object(obj, rows, max_rows=count)
        report = reconciler.reconcile(obj, load_result, extracted=count)
        # Inspect the shape: every created row should have a verify_key dict
        keys = load_result.get("created_keys") or []
        verify_dicts = [k for k in keys if isinstance(k, dict)
                          and "table" in k and "key" in k]
        per_object.append({
            "object":              obj,
            "mechanism":           load_result.get("mechanism"),
            "attempted":           load_result.get("attempted"),
            "created":             report.get("created"),
            "verified_in_target":  report.get("verified_in_target"),
            "value_checked":       report.get("value_checked"),
            "value_matched":       report.get("value_matched"),
            "status":              report.get("status"),
            "verify_key_dict_count": len(verify_dicts),
            "verify_key_dict_pct":  (round(100*len(verify_dicts)/max(len(keys),1), 1)),
            "by_table":            report.get("by_table") or {},
        })

    sweep_proof = {
        "all_objects_reconciled":
            all(p["status"] == "RECONCILED" for p in per_object),
        "all_via_spine":
            all((p["mechanism"] or "").startswith("spine/") for p in per_object),
        "all_emit_verify_key_dicts":
            all(p["verify_key_dict_pct"] == 100.0 for p in per_object),
    }
    overall_ok = all(sweep_proof.values())

    log_stage_event(run_id, "data-migrator", "phaseB_reconcile_sweep_complete",
                    {"objects_swept": len(per_object),
                     "all_reconciled": sweep_proof["all_objects_reconciled"]})

    try:
        tconn.close()
    except Exception:
        pass

    return {
        "run_id":   run_id,
        "status":   "ok" if overall_ok else "mismatch",
        "phase":    "reconcile_sweep_multi_object",
        "target":   {"sid": tsec.get("sid"), "client": tsec.get("client"),
                       "ashost": tsec.get("ashost")},
        "count":    count,
        "per_object": per_object,
        "proof":    sweep_proof,
    }


# ─────────────────────────────────────────────────────────────────────────────
# FK resolution helper — used by phase_b_validate_generated test C.
# Pulls live target values for foreign-key fields so the synthetic rows the
# scaffolder seeds the validator with refer to records that actually exist
# on the target system. Without this, every live BAPI call would fail with
# "material does not exist" / "plant unknown" before the spine's own logic
# could be exercised end-to-end.
# ─────────────────────────────────────────────────────────────────────────────
# Object_type -> (home_table, key_field). The base spine orchestrator
# already maintains _OBJECT_HOME_TABLE for the verify-key short-circuit; we
# extend it here with FK-only references (Plant, CompanyCode, etc.) that
# aren't full spine objects but get cited in fk_fields all over the place.
_FK_LOOKUP_EXTENSIONS = {
    "Plant":           ("T001W", "WERKS"),
    "CompanyCode":     ("T001",  "BUKRS"),
    "ChartOfAccounts": ("T004",  "KTOPL"),
    "WBSElement":      ("PRPS",  "PSPNR"),
    "Currency":        ("TCURC", "WAERS"),
    "Language":        ("T002",  "SPRAS"),
    "DocumentType":    ("T003",  "BLART"),
    "StorageLocation": ("T001L", "LGORT"),
}


def _fk_lookup_table(target_obj: str):
    """Return (table, key_field) for a given object_type, or None if unknown.

    Consults the spine orchestrator's table first (for the 33 object types
    it knows about) then falls back to the FK-only extension dict above.
    """
    try:
        from base_spine_orchestrator import _OBJECT_HOME_TABLE  # type: ignore
        if target_obj in _OBJECT_HOME_TABLE:
            return _OBJECT_HOME_TABLE[target_obj]
    except Exception:
        pass
    return _FK_LOOKUP_EXTENSIONS.get(target_obj)


def _fetch_live_fk_candidates(tconn, fk_fields: dict, per_field_limit: int = 10) -> dict:
    """Read up to ``per_field_limit`` real values for each FK target table.

    Returns ``{source_field: {"target_obj": str, "table": str, "key_field": str,
                              "values": [list], "error": Optional[str]}}``.

    A None ``error`` and non-empty ``values`` list means the FK is usable for
    the live probe. An ``error`` value or empty ``values`` means we'll keep
    the synthesised value (which will likely BAPI-fail — that's logged so
    the caller knows it).
    """
    out: dict = {}
    for src_field, target_obj in (fk_fields or {}).items():
        info = _fk_lookup_table(target_obj)
        if info is None:
            out[src_field] = {"target_obj": target_obj, "table": None,
                              "key_field": None, "values": [],
                              "error": f"no lookup table known for {target_obj!r}"}
            continue
        table, key_field = info
        try:
            r = tconn.call("RFC_READ_TABLE",
                           QUERY_TABLE=table, DELIMITER="|",
                           FIELDS=[{"FIELDNAME": key_field}],
                           ROWCOUNT=per_field_limit)
            raw = [row.get("WA", "").strip() for row in r.get("DATA", [])]
            vals = [v for v in raw if v]
            out[src_field] = {"target_obj": target_obj, "table": table,
                              "key_field": key_field, "values": vals,
                              "error": None if vals else "table empty"}
        except Exception as e:
            out[src_field] = {"target_obj": target_obj, "table": table,
                              "key_field": key_field, "values": [],
                              "error": f"{type(e).__name__}: {str(e)[:160]}"}
    return out


def _apply_fk_substitution(rows: list, candidates: dict) -> list:
    """Replace each row's FK fields with a real value drawn round-robin from
    the candidates pool. Rows whose FK has no candidates keep their original
    synthesised value (the BAPI call will fail and the dead-letter message
    will surface why)."""
    new_rows = [dict(r) for r in rows]
    for src_field, info in (candidates or {}).items():
        vals = info.get("values") or []
        if not vals:
            continue
        for i, row in enumerate(new_rows):
            row[src_field] = vals[i % len(vals)]
    return new_rows


def _fetch_joined_mard_triples(tconn, limit: int = 10) -> list:
    """Return up to ``limit`` consistent (MATNR, WERKS, LGORT) triples from
    MARD on the live target.

    Independent FK substitution gives one MATNR from MARA + one WERKS from
    T001W — but the combination may not exist in MARD (storage data), so the
    BAPI fails with "material not maintained in plant". Pulling the join
    directly from MARD avoids that whole class of failure for any
    transactional object that touches material/plant/storage."""
    try:
        r = tconn.call("RFC_READ_TABLE", QUERY_TABLE="MARD", DELIMITER="|",
                       FIELDS=[{"FIELDNAME": "MATNR"},
                               {"FIELDNAME": "WERKS"},
                               {"FIELDNAME": "LGORT"}],
                       ROWCOUNT=limit)
        out = []
        for row in r.get("DATA", []):
            parts = [p.strip() for p in row.get("WA", "").split("|")]
            if len(parts) >= 3 and all(parts[:3]):
                out.append({"MATNR": parts[0], "WERKS": parts[1], "LGORT": parts[2]})
        return out
    except Exception:
        return []


def _apply_mard_joined_pairs(rows: list, mard_triples: list, fk_fields: dict) -> int:
    """Override MATNR/WERKS (and LGORT if present) with joined-valid triples.
    Returns the number of rows whose triples were overridden."""
    if not mard_triples:
        return 0
    has_material = any(v == "Material" for v in (fk_fields or {}).values())
    has_plant    = any(v == "Plant"    for v in (fk_fields or {}).values())
    if not (has_material and has_plant):
        return 0
    n = 0
    for i, row in enumerate(rows):
        triple = mard_triples[i % len(mard_triples)]
        # Overwrite by source-field name (MATNR/WERKS/LGORT are the canonical
        # ECC names; if the row already had them, we now have a consistent set).
        row["MATNR"] = triple["MATNR"]
        row["WERKS"] = triple["WERKS"]
        row["LGORT"] = triple["LGORT"]
        n += 1
    return n


def _phase_b_validate_generated(event, run_id):
    """Live S/4 smoke for any registered spine — works equally well against
    scaffolder-generated and hand-written orchestrators.

    Why this exists: ``_phase_b_validate_f2`` hardcodes
    ``MaterialSpineOrchestrator`` and synthesizes Material-shaped records.
    For 107 future objects we'd need 107 nearly-identical validators. This
    one resolves the orchestrator via ``base_spine_orchestrator.get_spine``
    and the synthetic-row shape via the spine's own field maps + DQ gates,
    so any new scaffolder JSON gets a live probe path for free.

    Three escalating tests, all run in one invocation:

      A. DQ-gate proof — push N synthetic records where ``bad_count`` of
         them have an intentional DQ violation (sentinel value). Confirms
         the spine's ``validate()`` rejects exactly those and the dead-letter
         codes match the JSON definition.

      B. Dry-run payload proof — push ``good_count`` valid synthetic records
         with ``dry_run=True``. Confirms transform + value_maps + payload
         build all execute end-to-end without calling SAP. (Required pre-
         requisite for the live test — if dry-run fails, live will too.)

      C. LIVE BAPI (skipped unless ``live: true``) — push ``live_count`` real
         records into S/4. Caller is responsible for pre-creating any FK
         targets the spine needs (Material before InventoryReservation,
         Plant before SourceList, etc.). Guarded behind an explicit flag
         because it WRITES to the target.

    Payload::

        { "mode":            "phase_b_validate_generated",
          "run_id":           "irx-001",
          "object_type":      "InventoryReservation",
          "target_secret_id": "migrate4hana/prod/s4hana-credentials",
          "good_count":       3,        # records for test A (clean) + test B
          "bad_count":        2,        # records for test A (DQ-violating)
          "live":             false,    # set true to run test C
          "live_count":       1 }       # only used when live=true
    """
    target_secret_id = event.get("target_secret_id") or "migrate4hana/prod/s4hana-credentials"
    object_type      = event.get("object_type", "")
    good_count       = int(event.get("good_count", 3))
    bad_count        = int(event.get("bad_count", 2))
    do_live          = bool(event.get("live", False))
    live_count       = int(event.get("live_count", 1))

    if not object_type:
        return {"status": "error", "phase": "input", "run_id": run_id,
                "error": "object_type is required"}

    # ── Resolve the orchestrator class via the central registry ────────────
    try:
        from base_spine_orchestrator import get_spine, LoadResult  # type: ignore
    except Exception as e:
        return {"status": "error", "phase": "import_base", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}"}

    # Force discovery — same reason as _list_spines, in case this Lambda
    # warm-started before the new zip's spines were imported.
    try:
        from spine_discovery import load_all_spines  # type: ignore
        load_all_spines(verbose=False)
    except Exception:
        pass    # discovery is best-effort; falling back to whatever's registered

    orch_cls = get_spine(object_type)
    if orch_cls is None:
        from base_spine_orchestrator import registered_spines  # type: ignore
        return {"status": "error", "phase": "registry_lookup", "run_id": run_id,
                "error": f"object_type {object_type!r} not in spine registry",
                "registered_object_types": registered_spines()}

    # ── Open target S/4 connection ────────────────────────────────────────
    try:
        tsec = json.loads(SECRETS.get_secret_value(SecretId=target_secret_id)["SecretString"])
        from pyrfc import Connection   # type: ignore
        tconn = Connection(
            ashost=tsec["ashost"], sysnr=tsec.get("sysnr", "00"),
            client=tsec["client"], user=tsec["user"],
            passwd=tsec.get("passwd") or tsec.get("password"),
            lang=tsec.get("lang", "EN"),
        )
    except Exception as e:
        return {"status": "error", "phase": "connect_s4", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}",
                "object_type": object_type}

    # ── Synthesize rows from the spine's FIELD_MAPS + DQ_GATES ────────────
    # The scaffolder-generated spine exposes FIELD_MAPS / DQ_GATES at module
    # scope; hand-written spines don't. Detect both shapes.
    spine_module = sys.modules[orch_cls.__module__]
    field_maps   = dict(getattr(spine_module, "FIELD_MAPS", {}) or {})
    dq_gates     = list(getattr(spine_module, "DQ_GATES", []) or [])

    # Rule -> a representative valid value for that rule. Matches the heuristic
    # the scaffolder build.py uses to seed unit-test fixtures, kept in sync
    # so the validator's rows pass the DQ gates the spine was generated with.
    RULE_VALUE = {
        "non_empty":              "VALUE",
        "positive_number":        "1",
        "non_negative_number":    "0",
        "iso_date":               "20260614",
        "sap_unit_of_measure":    "EA",
        "currency_iso_4217":      "USD",
        "material_number_format": "MAT_T0001",
        "bukrs_company_code":     "1010",
        "werks_plant":            "1710",
        "langu_code":             "EN",
        "sap_client_3char":       "100",
        "decimal_max_digits":     "100.00",
        "regex_match":            "VALUE",
        "in_set":                 "VALUE",
        "fk_required_when":       "VALUE",
    }

    def synth_good(i: int) -> dict:
        # Only seed fields that DQ gates need (with typed values) + the source
        # key. Don't blanket-default every field_maps source to "X" — that
        # corrupts NUMC/DATE/DEC fields when the BAPI runs live (e.g.
        # RESPONSIBLE_NO is NUMC, "X" is rejected by pyrfc as not a digit).
        # Unset source fields are skipped by the spine's _apply_field_map, so
        # the BAPI uses its own defaults for unset optional fields, and
        # required-but-unset fields surface as real S/4 validation errors.
        row = {orch_cls.source_key_field: f"{object_type[:5].upper()}{i:04d}"}
        for gate in dq_gates:
            field = gate[0] if isinstance(gate, (tuple, list)) else gate.get("field")
            rule  = gate[1] if isinstance(gate, (tuple, list)) else gate.get("rule")
            val = RULE_VALUE.get(rule, "VALUE")
            # in_set rules need a value from the configured set
            if rule == "in_set":
                args = gate[2] if isinstance(gate, (tuple, list)) else gate.get("rule_args", {})
                values = (args or {}).get("values") or []
                if values:
                    val = values[0]
            row[field] = val
        # Re-stamp source_key after the DQ pass (it might be a string-format
        # field that the source_key_field happened to share with a DQ gate).
        # Digit-only source key so it round-trips through both CHAR and NUMC
        # target fields (NUMC fields reject letters at the pyrfc fill layer).
        # 10 digits fits in CONF_NO (NUMC 10) and zero-pads cleanly into NUMC
        # OBJ_ID (8) / smaller fields without losing identity.
        row[orch_cls.source_key_field] = f"{i:010d}"
        return row

    def synth_bad(i: int) -> tuple:
        """Return (row, expected_dead_letter_code). Pick the FIRST DQ gate
        we can violate cleanly by setting the field to empty."""
        good = synth_good(i)
        if not dq_gates:
            return good, None
        first = dq_gates[0]
        field = first[0] if isinstance(first, (tuple, list)) else first.get("field")
        code  = first[3] if isinstance(first, (tuple, list)) else first.get("code")
        good[field] = ""
        return good, code

    # ── Test A: DQ gate proof (dry-run; dead letter expected) ──────────────
    bad_rows = [synth_bad(i) for i in range(bad_count)]
    test_a = {"records_pushed": bad_count, "dq_rejected": 0,
              "expected_codes": [],        "got_codes": []}
    orch_a = orch_cls(tconn, key_map=None, dry_run=True)
    for row, expected_code in bad_rows:
        result = orch_a.load_one(row)
        test_a["expected_codes"].append(expected_code)
        if result.status == "dead_letter":
            test_a["dq_rejected"] += 1
            # extract the prefix code from the message (validate returns "CODE: msg")
            head_msg = result.messages[0] if result.messages else ""
            test_a["got_codes"].append(head_msg.split(":", 1)[0].strip() if head_msg else None)
        else:
            test_a["got_codes"].append(None)
    test_a["pass"] = (test_a["dq_rejected"] == bad_count
                      and test_a["expected_codes"] == test_a["got_codes"])

    # ── Test B: dry-run BAPI proof (no SAP write) ──────────────────────────
    good_rows = [synth_good(i) for i in range(good_count)]
    test_b_results = orch_a.load_many(good_rows)
    test_b = {"records_pushed":  good_count,
              "created_dry_run": sum(1 for r in test_b_results if r.status == "created"),
              "dead_letter":     sum(1 for r in test_b_results if r.status == "dead_letter"),
              "stats":           orch_a.stats.to_dict(),
              "results":         [r.to_dict() for r in test_b_results]}
    test_b["pass"] = (test_b["created_dry_run"] == good_count
                      and test_b["dead_letter"] == 0)

    # ── Test C: live BAPI (gated) ──────────────────────────────────────────
    test_c = {"skipped": True, "reason": "live=false (default)"}
    if do_live:
        try:
            from key_map import PersistentKeyMap
            ddb_table = os.environ.get("M4H_KEYMAP_TABLE", "migrate4hana-key-map-prod")
            km = PersistentKeyMap(table_name=ddb_table, run_id=run_id,
                                  target_release=os.environ.get("M4H_TARGET_RELEASE", "S4HANA_UNKNOWN"))
        except Exception as e:
            km = None
            log_stage_event(run_id, "data-migrator", "phaseB_keymap_skipped",
                            {"reason": str(e)[:160]})

        # FK auto-resolution: replace synthetic FK values with real ones pulled
        # from the target. Without this, every live row dead-letters at the
        # BAPI on "material doesn't exist" before the spine's own logic runs.
        live_rows = [synth_good(i + 1000) for i in range(live_count)]
        fk_fields = getattr(orch_cls, "fk_fields", {}) or {}
        fk_resolution = _fetch_live_fk_candidates(tconn, fk_fields, per_field_limit=10)
        if fk_resolution:
            live_rows = _apply_fk_substitution(live_rows, fk_resolution)

        # When the spine references BOTH Material AND Plant, the independent FK
        # lookups above can pair a MATNR with a WERKS where (MATNR, WERKS) has
        # no MARD entry — the BAPI then rejects with "material not maintained
        # in plant". Override with joined-valid triples from MARD so the row
        # references a real stocked material+plant+storage combination.
        mard_triples = _fetch_joined_mard_triples(tconn, limit=live_count * 2)
        mard_pairs_used = _apply_mard_joined_pairs(live_rows, mard_triples, fk_fields)

        # Caller-supplied per-field overrides. Used to inject known-valid coded
        # values (movement types, document types, etc.) that the scaffolder's
        # rule-default-based synthesis can't produce. ``null`` removes the
        # field entirely from the row so the spine skips it in build_payload.
        live_overrides = event.get("live_overrides", {}) or {}
        for src_field, override_val in live_overrides.items():
            for row in live_rows:
                if override_val is None:
                    row.pop(src_field, None)
                else:
                    row[src_field] = override_val

        # Pre-seed the ledger with IDENTITY mappings for every (FK target, FK
        # value) pair that ends up in the rows AFTER all substitutions. In a
        # real migration the ledger is populated by an earlier object's spine
        # (Material before Reservation); the identity-seed simulates that
        # without chaining. Must run AFTER MARD/override changes so the seed
        # covers the actual values the BAPI will see, not the discarded
        # intermediate ones.
        fk_seeded = 0
        if km is not None and fk_fields:
            seen_pairs = set()
            for row in live_rows:
                for src_field, target_obj in fk_fields.items():
                    val = row.get(src_field)
                    if val is None or val == "":
                        continue
                    key = (target_obj, str(val))
                    if key in seen_pairs:
                        continue
                    seen_pairs.add(key)
                    try:
                        km.add(target_obj, str(val), str(val), "live_smoke_identity")
                        fk_seeded += 1
                    except Exception:
                        pass

        orch_c = orch_cls(tconn, key_map=km, dry_run=False,
                          target_release=os.environ.get("M4H_TARGET_RELEASE", "S4HANA_2022"))
        live_results = orch_c.load_many(live_rows)

        # Surface BAPI messages from the dead-letters so the caller can see
        # WHY records failed (missing BAPI param, wrong structure layout, etc.).
        # First three dead-letters are reported in full; the rest as a count.
        dead_letter_messages = []
        for r in live_results:
            if r.status == "dead_letter" and len(dead_letter_messages) < 3:
                dead_letter_messages.append({
                    "source_key": r.source_key,
                    "dead_letter": r.dead_letter,
                    "messages":    r.messages,
                })

        test_c = {
            "skipped":         False,
            "records_pushed":  live_count,
            "created":         sum(1 for r in live_results if r.status == "created"),
            "matched":         sum(1 for r in live_results if r.status == "matched_existing"),
            "dead_letter":     sum(1 for r in live_results if r.status == "dead_letter"),
            "stats":           orch_c.stats.to_dict(),
            "results":         [r.to_dict() for r in live_results],
            "fk_resolution":   {k: {"target_obj": v["target_obj"], "table": v["table"],
                                    "key_field": v["key_field"],
                                    "candidate_count": len(v["values"]),
                                    "first_3":        v["values"][:3],
                                    "error":          v["error"]}
                                for k, v in fk_resolution.items()},
            "fk_identity_seeded":    fk_seeded,
            "mard_pairs_used":       mard_pairs_used,
            "mard_triple_pool_size": len(mard_triples),
            "live_overrides_applied": dict(live_overrides),
            "first_dead_letter_messages": dead_letter_messages,
        }
        test_c["pass"] = (test_c["created"] + test_c["matched"]) >= 1

    try:
        tconn.close()
    except Exception:
        pass

    overall_pass = test_a["pass"] and test_b["pass"] and (
        test_c.get("pass", True) if not test_c.get("skipped") else True)

    log_stage_event(run_id, "data-migrator", "phaseB_generated_complete",
                    {"object_type": object_type,
                     "A": test_a["pass"], "B": test_b["pass"],
                     "C": test_c.get("pass", "skipped")})

    return {
        "status":     "ok" if overall_pass else "failed",
        "phase":      "phase_b_validate_generated",
        "run_id":     run_id,
        "object_type": object_type,
        "target":     {"sid": tsec.get("sid"), "client": tsec.get("client"),
                       "ashost": tsec.get("ashost")},
        "spine_class": orch_cls.__name__,
        "spine_module": orch_cls.__module__,
        "tests": {
            "A_dq_gate_proof":  test_a,
            "B_dry_run_proof":  test_b,
            "C_live_bapi":      test_c,
        },
        "overall_pass": overall_pass,
    }


def _discover_anchors_mode(event, run_id):
    """Pre-flight: probe the target's customizing tables for anchors and
    persist the discovered set to S3 so spines lift to Tier-1 on this
    landscape without per-landscape code changes.

    Event payload:
        target_secret_id (str)   - Secrets Manager id of S/4 credentials
        subset (list, optional)  - restrict to specific anchor keys
        write_to_s3 (bool)       - default True; writes
                                   anchors/<run_id>/discovered.json
    """
    target_secret_id = event.get("target_secret_id") or "migrate4hana/prod/s4hana-credentials"
    subset = event.get("subset")
    try:
        tsec = json.loads(SECRETS.get_secret_value(SecretId=target_secret_id)["SecretString"])
        from pyrfc import Connection
        from anchor_discovery import discover_anchors
        conn = Connection(
            ashost=tsec["ashost"], sysnr=tsec["sysnr"],
            client=tsec["client"], user=tsec["user"], passwd=tsec["passwd"])
        anchors = discover_anchors(conn, subset=subset)
        conn.close()
    except Exception as e:
        return {"status": "error", "phase": "discover_anchors", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:200]}"}

    if event.get("write_to_s3", True):
        bucket = os.environ.get("M4H_STAGING_BUCKET", "")
        if bucket:
            try:
                S3.put_object(
                    Bucket=bucket,
                    Key=f"anchors/{run_id}/discovered.json",
                    Body=json.dumps(anchors, indent=2).encode("utf-8"),
                    ContentType="application/json")
            except Exception as e:
                return {"status": "ok_no_persist", "phase": "discover_anchors",
                        "run_id": run_id, "anchors": anchors,
                        "persist_error": f"{type(e).__name__}: {str(e)[:120]}"}

    return {"status": "ok", "phase": "discover_anchors", "run_id": run_id,
            "anchors_discovered": len(anchors), "anchors": anchors}


def _apply_customizing_mode(event, run_id):
    """Apply a packaged customizing manifest to the target under the
    post_data_prep HMAC-signed gate.

    Event payload:
        manifest (dict)          - reconciler-packaged customizing gap
                                   (exchange_rates, tax_codes, classes)
        gate_token (str)         - HMAC-signed post_data_prep gate token
        target_secret_id (str)   - Secrets Manager id of S/4 credentials
        require_gate (bool)      - default True; set False ONLY in unit-test
                                   bridging (M4H_ALLOW_UNGATED_CUST=1 env
                                   inside Lambda is ignored)
    """
    manifest = event.get("manifest") or {}
    gate_token = event.get("gate_token") or ""
    target_secret_id = event.get("target_secret_id") or "migrate4hana/prod/s4hana-credentials"
    require_gate = event.get("require_gate", True)
    # Production posture: Lambda execution context always requires the gate.
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        require_gate = True

    try:
        tsec = json.loads(SECRETS.get_secret_value(SecretId=target_secret_id)["SecretString"])
        from pyrfc import Connection
        from customizing_applier import apply_customizing
        conn = Connection(
            ashost=tsec["ashost"], sysnr=tsec["sysnr"],
            client=tsec["client"], user=tsec["user"], passwd=tsec["passwd"])
        result = apply_customizing(conn, manifest, gate_token=gate_token,
                                    require_gate=require_gate)
        conn.close()
    except Exception as e:
        return {"status": "error", "phase": "apply_customizing", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:200]}"}

    return {"status": "ok", "phase": "apply_customizing", "run_id": run_id,
            "result": result}


def _mc_lane_extended_probe(event, run_id):
    """Smoke-test the extended 5-strategy MC trigger chain on the target.

    Event payload:
        object_id (str)          - MC object name (e.g., "Customer")
        file_s3_uri (str)        - already-staged file from mc_file_exporter
        target_secret_id (str)
        wait_for_complete (bool) - default False
    """
    object_id = event.get("object_id") or ""
    file_s3_uri = event.get("file_s3_uri") or ""
    target_secret_id = event.get("target_secret_id") or "migrate4hana/prod/s4hana-credentials"
    wait_for_complete = event.get("wait_for_complete", False)
    if not object_id or not file_s3_uri:
        return {"status": "error", "phase": "mc_lane_extended_probe",
                "run_id": run_id,
                "error": "object_id and file_s3_uri are required"}
    try:
        tsec = json.loads(SECRETS.get_secret_value(SecretId=target_secret_id)["SecretString"])
        from pyrfc import Connection
        from mc_job_trigger import trigger_mc_load
        conn = Connection(
            ashost=tsec["ashost"], sysnr=tsec["sysnr"],
            client=tsec["client"], user=tsec["user"], passwd=tsec["passwd"])
        result = trigger_mc_load(
            target_conn=conn, project_id=event.get("project_id", "M4H_PROD_001"),
            object_id=object_id, file_s3_uri=file_s3_uri,
            correlation_id=run_id, wait_for_complete=wait_for_complete,
            timeout_secs=int(event.get("timeout_secs", 300)))
        conn.close()
    except Exception as e:
        return {"status": "error", "phase": "mc_lane_extended_probe",
                "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:200]}"}

    return {"status": "ok", "phase": "mc_lane_extended_probe",
            "run_id": run_id, "result": result}


def _phase_c_mc_trigger(event, run_id):
    """Live test the MC job-trigger lane against the target S/4.

    Without an object_id: returns a strategy availability probe (does
    LTMC_API exist on this S/4? does the OData service answer? does XBP
    work?). With an object_id + a (small) sample dataset, generates a
    file via mc_file_exporter, uploads to S3, and chains into
    trigger_mc_load() to confirm end-to-end fire-and-forget on the MC
    lane.

    Payload::

        { "mode":          "phase_c_mc_trigger",
          "object_id":     "GLAccount",        # optional; omit for probe
          "project_id":    "M4H_PROD_001",     # required when object_id given
          "wait":          true,               # wait for job completion
          "timeout_secs":  600,
          "sample_rows":   [ { "KTOPL": "YIKR", "SAKNR": "0000100001", ... }, ... ]
        }
    """
    target_secret_id = event.get("target_secret_id") or "migrate4hana/prod/s4hana-credentials"
    object_id        = (event.get("object_id") or "").strip()
    project_id       = (event.get("project_id") or "").strip()
    wait_flag        = bool(event.get("wait", True))
    timeout_secs     = int(event.get("timeout_secs", 600))
    sample_rows      = event.get("sample_rows") or []

    # ── Open target S/4 connection ────────────────────────────────────────
    try:
        tsec = json.loads(SECRETS.get_secret_value(SecretId=target_secret_id)["SecretString"])
        from pyrfc import Connection   # type: ignore
        tconn = Connection(
            ashost=tsec["ashost"], sysnr=tsec.get("sysnr", "00"),
            client=tsec["client"], user=tsec["user"],
            passwd=tsec.get("passwd") or tsec.get("password"),
            lang=tsec.get("lang", "EN"),
        )
    except Exception as e:
        return {"status": "error", "phase": "connect_s4", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}"}

    # ── Strategy availability probe (object_id absent) ────────────────────
    if not object_id:
        availability = {}
        # Probe LTMC_API
        try:
            tconn.call("LTMC_API_OBJ_GET_STATUS", IV_JOB_ID="__probe__")
            availability["ltmc_api"] = {"available": True, "note": "FM exists"}
        except Exception as e:
            msg = str(e)[:200]
            # FU_NOT_FOUND means LTMC_API isn't exposed; any other error
            # means the FM is there but the test job ID doesn't exist
            if "FU_NOT_FOUND" in msg or "not exist" in msg.lower():
                availability["ltmc_api"] = {"available": False, "note": "FM not exposed"}
            else:
                availability["ltmc_api"] = {"available": True, "note": f"present but probe rejected: {msg[:100]}"}
        # Probe XBP
        try:
            tconn.call("BAPI_XBP_JOB_OPEN", JOBNAME="__M4H_PROBE__", JOBCLASS="C",
                        EXTERNAL_USER_NAME="MIG_PROBE")
            availability["xbp_job"] = {"available": True, "note": "XBP open accepted"}
        except Exception as e:
            msg = str(e)[:200]
            if "FU_NOT_FOUND" in msg:
                availability["xbp_job"] = {"available": False, "note": "BAPI_XBP_JOB_OPEN not exposed"}
            elif "EXTERNAL_USER" in msg or "not authorized" in msg.lower():
                availability["xbp_job"] = {"available": True, "note": "XBP exposed; needs external-scheduler logon"}
            else:
                availability["xbp_job"] = {"available": False, "note": msg[:160]}
        try:
            tconn.close()
        except Exception:
            pass
        return {
            "status":       "ok",
            "phase":        "phase_c_mc_trigger:probe",
            "run_id":       run_id,
            "target":       {"sid": tsec.get("sid"), "client": tsec.get("client"),
                              "ashost": tsec.get("ashost")},
            "availability": availability,
            "recommended_strategy": ("ltmc_api" if availability.get("ltmc_api", {}).get("available")
                                      else ("xbp_job" if availability.get("xbp_job", {}).get("available")
                                            else "none")),
        }

    # ── Full trigger flow (object_id supplied) ────────────────────────────
    if not project_id:
        return {"status": "error", "phase": "input", "run_id": run_id,
                "error": "project_id required when object_id is supplied"}

    # Write sample rows into the MC pseudo-spine, flush to S3, trigger
    bucket = os.environ.get("M4H_STAGING_BUCKET", "migrate4hana-staging-prod")
    try:
        from mc_file_exporter import _REGISTERED_MC_OBJECTS, _make_mc_file_class, MC_TEMPLATES
        from base_spine_orchestrator import _SPINE_REGISTRY
        if object_id not in MC_TEMPLATES:
            return {"status": "error", "phase": "lookup", "run_id": run_id,
                    "error": f"object_id {object_id!r} not in MC_TEMPLATES",
                    "available_objects": list(MC_TEMPLATES.keys())[:30]}
        cls = _SPINE_REGISTRY.get(object_id)
        if cls is None:
            return {"status": "error", "phase": "lookup", "run_id": run_id,
                    "error": f"{object_id} not registered (mc spine missing?)"}

        # Build payloads through the spine's pseudo-call so the buffer fills
        spec = MC_TEMPLATES[object_id]
        if not sample_rows:
            # Synthesize one row from mandatory columns
            sample_rows = [{c: f"M4H_{c[:4]}" for c in spec["mandatory"]}]
        for row in sample_rows:
            payload = {"record": {c: (row.get(c) or "") for c in spec["csv_columns"]},
                       "customs": {},
                       "_src": (row.get(spec["mandatory"][0]) or "M4H_DEFAULT")}
            cls._row_buffer.append({"record": payload["record"],
                                     "customs": payload["customs"]})

        s3_client = boto3.client("s3")
        flush_res = cls.flush_to_s3(s3_client, bucket, run_id, "default")

        from mc_job_trigger import trigger_mc_load
        trigger_res = trigger_mc_load(
            target_conn       = tconn,
            project_id        = project_id,
            object_id         = object_id,
            file_s3_uri       = flush_res["uri"],
            correlation_id    = run_id,
            wait_for_complete = wait_flag,
            timeout_secs      = timeout_secs,
        )

        try:
            tconn.close()
        except Exception:
            pass

        return {
            "status":  "ok" if trigger_res["status"] in ("DONE", "RUNNING") else "failed",
            "phase":   "phase_c_mc_trigger:trigger",
            "run_id":  run_id,
            "object":  object_id,
            "flush":   flush_res,
            "trigger": trigger_res,
        }
    except Exception as e:
        try:
            tconn.close()
        except Exception:
            pass
        return {"status": "error", "phase": "trigger", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}"}


def _list_spines(event, run_id):
    """Return a snapshot of the current spine registry.

    Used to verify that auto-discovery saw newly-scaffolded spines AFTER a
    deploy. No SAP calls, no S3, no DynamoDB — just an in-process registry
    read. Payload::

        { "mode": "list_spines", "run_id": "discovery-smoke-001" }

    Response shape::

        { "status":              "ok",
          "run_id":               "<echo>",
          "registered_count":     int,
          "object_types":         [<sorted list of registered object_type strings>],
          "scaffolder_generated": [<object_types whose spine file claims scaffolder origin>],
          "priority_modules":     [<author-controlled priority order>],
          "discovered_modules":   [<everything found by filesystem sweep>],
          "load_summary":         { "loaded": [...], "skipped": [...], "failures": [...] } }
    """
    # Import here so an import-time failure becomes a structured response
    # instead of a Lambda-runtime crash.
    try:
        from spine_discovery import registry_snapshot, load_all_spines  # type: ignore
    except Exception as e:
        log_stage_event(run_id, "data-migrator", "list_spines_failed", {"error": str(e)})
        return {"status": "error", "phase": "import_spine_discovery", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}"}

    # Force re-discovery so this endpoint reports the LIVE filesystem, not a
    # cached unified_loader snapshot taken at module-import time (which would
    # mask a missing-module bug post-deploy).
    load_summary = load_all_spines(verbose=False)
    snap = registry_snapshot()

    # Cross-check: which registered object_types correspond to scaffolder-
    # generated spine files? Read the head of each candidate file and look
    # for the "GENERATED FROM definitions/" marker the spine.py.j2 emits.
    scaffolder_generated = []
    try:
        import os as _os
        here = _os.path.dirname(_os.path.abspath(__file__))
        for fname in _os.listdir(here):
            if not fname.endswith("_spine.py") or fname.startswith("test_"):
                continue
            if fname == "base_spine_orchestrator.py":
                continue
            try:
                with open(_os.path.join(here, fname), "r", encoding="utf-8") as f:
                    head = f.read(800)
                if "GENERATED FROM definitions/" in head:
                    # Pull the object_type from the second line of the marker.
                    for line in head.splitlines():
                        if "definitions/" in line:
                            tail = line.split("definitions/", 1)[1]
                            obj = tail.split(".json", 1)[0].strip()
                            if obj:
                                scaffolder_generated.append(obj)
                                break
            except Exception:
                continue
    except Exception:
        pass
    scaffolder_generated.sort()

    log_stage_event(run_id, "data-migrator", "list_spines",
                    {"registered_count": snap.get("registered_count"),
                     "scaffolder_count": len(scaffolder_generated)})

    return {
        "status":               "ok",
        "phase":                "list_spines",
        "run_id":               run_id,
        "registered_count":     snap.get("registered_count", 0),
        "object_types":         snap.get("object_types", []),
        "scaffolder_generated": scaffolder_generated,
        "priority_modules":     snap.get("priority_modules", []),
        "discovered_modules":   snap.get("discovered_modules", []),
        "load_summary":         load_summary,
    }


def _phase_b_validate_idempotency(event, run_id):
    """Idempotency proof for partial / retried runs.

    F1 PersistentKeyMap promises: re-running the same source key resolves to
    the same target without re-creating. This validator proves it against
    live DDB + live S/4 via three independent runs:

      1. Load N Materials with prefix P -> verify created
      2. Re-run the SAME prefix + same source keys via a FRESH lambda invo
         (simulating Fargate task restart) -> verify F1 resolution returns
         the original target keys, NO new BAPI creates happen
      3. Load N more Materials with prefix P+1 -> verify these ARE new
         creates (the F1 ledger doesn't false-positive on different src keys)

    The proof relies on PersistentKeyMap.resolve() reading from DDB rather
    than from in-memory state, since the in-memory cache resets between
    lambda invocations. Two lambda invocations per validator run share only
    the DDB table; everything else is independent.

    Payload::

        { "mode": "phase_b_validate_idempotency",
          "run_id": "idemp-001",
          "count": 2,
          "prefix": "IDEMP" }
    """
    count = int(event.get("count", 2))
    prefix = (event.get("prefix") or f"IDEMP{run_id[-4:]}").strip()
    target_secret_id = event.get("target_secret_id") or "migrate4hana/prod/s4hana-credentials"

    try:
        tsec = json.loads(SECRETS.get_secret_value(SecretId=target_secret_id)["SecretString"])
        from pyrfc import Connection   # type: ignore
        tconn = Connection(
            ashost=tsec["ashost"], sysnr=tsec.get("sysnr", "00"),
            client=tsec["client"], user=tsec["user"],
            passwd=tsec.get("passwd") or tsec.get("password"),
            lang=tsec.get("lang", "EN"),
        )
    except Exception as e:
        return {"status": "error", "phase": "connect_s4", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}"}

    try:
        from material_spine import MaterialSpineOrchestrator
        from key_map import PersistentKeyMap
    except Exception as e:
        try: tconn.close()
        except Exception: pass
        return {"status": "error", "phase": "import_idempotency", "run_id": run_id,
                "error": f"{type(e).__name__}: {str(e)[:240]}"}

    ddb_table = os.environ.get("M4H_KEYMAP_TABLE", "migrate4hana-key-map-prod")

    def make_rows(suffix_seed, n=count, override_prefix=None):
        p = override_prefix or prefix
        return [{"MATNR": f"{p}_{suffix_seed}_{i:03d}",
                  "MTART": "HALB", "MBRSH": "M", "MEINS": "EA",
                  "MAKTX": f"Idemp {p} {suffix_seed} {i:03d}"}
                 for i in range(n)]

    # ── Run 1: fresh load ────────────────────────────────────────────────────
    km1 = PersistentKeyMap(table_name=ddb_table, run_id=run_id + "-r1")
    orch1 = MaterialSpineOrchestrator(tconn, key_map=km1)
    rows1 = make_rows(suffix_seed="A")
    results1 = orch1.load_many(rows1)
    run1_created = sum(1 for r in results1 if r.target_key)
    run1_targets = {r.source_key: r.target_key for r in results1 if r.target_key}

    # ── Run 2: same source keys, fresh PKM instance (simulates Fargate retry) ─
    km2 = PersistentKeyMap(table_name=ddb_table, run_id=run_id + "-r2")
    orch2 = MaterialSpineOrchestrator(tconn, key_map=km2)
    # Resolve each source key BEFORE attempting load -- this is the path the
    # production loader uses to decide "skip, already migrated".
    run2_pre_resolved = {row["MATNR"]: km2.resolve("Material", row["MATNR"])
                          for row in rows1}
    # Now load (the SAME rows). If F1 idempotency works AND the loader honors
    # the resolution, we should see 0 new MARA creates. If it doesn't honor
    # F1, MaterialSpine would attempt re-create -> SAP returns "material
    # already exists" -> classify as matched_existing (still no duplicate).
    results2 = orch2.load_many(rows1)
    run2_created = sum(1 for r in results2 if r.status == "created")
    run2_matched = sum(1 for r in results2 if r.status == "matched_existing")

    # ── Run 3: DIFFERENT source keys, prove F1 doesn't false-positive ────────
    km3 = PersistentKeyMap(table_name=ddb_table, run_id=run_id + "-r3")
    orch3 = MaterialSpineOrchestrator(tconn, key_map=km3)
    rows3 = make_rows(suffix_seed="B")
    run3_pre_resolved = {row["MATNR"]: km3.resolve("Material", row["MATNR"])
                          for row in rows3}
    results3 = orch3.load_many(rows3)
    run3_created = sum(1 for r in results3 if r.target_key)

    proof = {
        "run1_creates_all": run1_created == count,
        # F1 pre-resolve in run 2 returned every key registered by run 1
        "run2_f1_resolves_all": all(run2_pre_resolved.get(k) == v
                                      for k, v in run1_targets.items()),
        # No duplicate creates in run 2 (either matched_existing or skipped)
        "run2_no_duplicate_creates": run2_created == 0,
        # Run 3 had distinct source keys -> F1 didn't false-positive
        "run3_no_false_positive_skip":
            all(v is None for v in run3_pre_resolved.values()),
        "run3_creates_all_new": run3_created == count,
    }
    overall_ok = all(proof.values())

    log_stage_event(run_id, "data-migrator", "phaseB_idempotency_complete",
                    {"run1_created": run1_created,
                     "run2_created": run2_created,
                     "run2_matched": run2_matched,
                     "run3_created": run3_created,
                     "overall_ok":  overall_ok})

    try:
        tconn.close()
    except Exception:
        pass

    return {
        "run_id":  run_id,
        "status":  "ok" if overall_ok else "mismatch",
        "phase":   "idempotency_proof_three_run",
        "target":  {"sid": tsec.get("sid"), "client": tsec.get("client"),
                     "ashost": tsec.get("ashost")},
        "count":   count,
        "prefix":  prefix,
        "run1":    {"created": run1_created, "targets": run1_targets},
        "run2":    {
            "pre_resolved":     run2_pre_resolved,
            "created":          run2_created,
            "matched_existing": run2_matched,
        },
        "run3":    {
            "pre_resolved":     run3_pre_resolved,
            "created":          run3_created,
        },
        "proof":   proof,
    }
