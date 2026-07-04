# generate_field_catalog.ps1
# --------------------------
# Regenerate the BAPI field catalog JSON for a target S/4 release by
# introspecting released customer-callable function modules with
# `RFC_GET_FUNCTION_INTERFACE` — the SAP-released, always-safe FM that
# describes any callable module's import/export/table parameters + their
# DD03L-derived types.
#
# What this DOES:
#   1. Connects to the target via pyrfc (Python -- NO custom ABAP).
#   2. For each entry in a curated `bapi_map.json` (object_type -> FM name),
#      calls RFC_GET_FUNCTION_INTERFACE and walks the parameters + their
#      DD03L structures to extract the flat field list.
#   3. Merges the result with the in-code baseline (bapi_field_catalog.py)
#      and writes:
#        value-maps/bapi_field_catalog.<release>.json
#      Suitable to attach as M4H_BAPI_FIELD_CATALOG_JSON in Lambda env.
#
# What this DOES NOT do:
#   - It does NOT call ANY non-released internal FM (no `DDIF_*`, no
#     `LTR_*`, no `TH_*`, no `STMS_*`). Every FM referenced below is in
#     SAP's published customer-callable RFC set.
#   - It does NOT mutate the target -- read-only introspection only.
#
# Usage:
#     .\scripts\generate_field_catalog.ps1 `
#         -Host vhcalabaci -SystemNumber 00 -Client 100 `
#         -User ATH -Passwd '****' -Release S4H2023
#
# Output:
#     value-maps/bapi_field_catalog.<Release>.json
#
# Prereqs:
#   - Python 3.11+ with pyrfc + SAP NW RFC SDK 7.50 SP12+ on PATH.
#   - The service user must have S_RFC on the introspection FM group
#     (SAP-standard "SUSR" or "SU01" analogues).
# ============================================================================

param(
    [Parameter(Mandatory = $true)] [string]$Host,
    [Parameter(Mandatory = $true)] [string]$SystemNumber,
    [Parameter(Mandatory = $true)] [string]$Client,
    [Parameter(Mandatory = $true)] [string]$User,
    [Parameter(Mandatory = $true)] [string]$Passwd,
    [Parameter(Mandatory = $true)] [string]$Release,
    [Parameter(Mandatory = $false)] [string]$BapiMapFile = "scripts\bapi_map.json",
    [Parameter(Mandatory = $false)] [string]$OutDir = "value-maps"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $BapiMapFile)) {
    Write-Host "bapi_map.json not found at $BapiMapFile -- creating a default stub." -ForegroundColor Yellow
    $default = @{
        "BusinessPartner"     = "BAPI_BUPA_CREATE_FROM_DATA"
        "Customer"            = "BAPI_CUSTOMER_CREATEFROMDATA1"
        "Vendor"              = "BAPI_VENDOR_CREATE"
        "Material"            = "BAPI_MATERIAL_SAVEDATA"
        "Bank"                = "BAPI_BANK_CREATE"
        "ExchangeRates"       = "BAPI_EXCHANGERATE_CREATEMULTIPLE"
        "CostCenter"          = "BAPI_COSTCENTER_CREATEMULTIPLE"
        "ProfitCenter"        = "BAPI_PROFITCENTER_CREATE"
        "InternalOrder"       = "BAPI_INTERNALORDER_CREATE"
        "FixedAsset"          = "BAPI_FIXEDASSET_OVRTAKE_CREATE"
        "Equipment"           = "BAPI_EQUI_CREATE"
        "FunctionalLocation"  = "BAPI_FUNCLOC_CREATE"
        "Characteristic"      = "BAPI_CHARACT_CREATE"
        "Class"               = "BAPI_CLASS_CREATE"
        "Batch"               = "BAPI_BATCH_CREATE"
        "OpenAR"              = "BAPI_ACC_DOCUMENT_POST"
        "OpenAP"              = "BAPI_ACC_DOCUMENT_POST"
        "OpenPO"              = "BAPI_PO_CREATE1"
        "PurchaseRequisition" = "BAPI_REQUISITION_CREATE"
        "PurchaseContract"    = "BAPI_CONTRACT_CREATE"
        "SalesOrder"          = "BAPI_SALESORDER_CREATEFROMDAT2"
        "Quotation"           = "BAPI_QUOTATION_CREATEFROMDATA2"
        "Inquiry"             = "BAPI_INQUIRY_CREATEFROMDATA2"
        "SalesContract"       = "BAPI_SALES_CONTRACT_CREATEFROMDAT"
        "OutboundDelivery"    = "BAPI_OUTB_DELIVERY_CREATE_HEADER"
        "GoodsReceipt"        = "BAPI_GOODSMVT_CREATE"
        "IncomingInvoice"     = "BAPI_INCOMINGINVOICE_CREATE"
        "AccountingDocument"  = "BAPI_ACC_DOCUMENT_POST"
        "Project"             = "BAPI_PROJECT_MAINTAIN"
        "HandlingUnit"        = "BAPI_HU_CREATE_ONE_STEP"
        "ProductionOrder"     = "BAPI_PRODORD_CREATE"
        "ProcessOrder"        = "BAPI_PROCORD_CREATE"
        "PlannedOrder"        = "BAPI_PLANNEDORDER_CREATE"
        "MaintenanceItem"     = "BAPI_ALM_MAINTITEM_CREATE"
        "MaintenancePlan"     = "BAPI_ALM_MAINTPLAN_CREATE"
        "Notification"        = "BAPI_ALM_NOTIF_CREATE"
        "MeasurementPoint"    = "BAPI_MEASUREMENTPOINT_CREATE"
        "MeasurementDocument" = "BAPI_MEASUREMENTDOC_CREATE"
        "InfoRecord"          = "BAPI_INFORECORD_CREATE"
        "DocumentInfoRecord"  = "BAPI_DOCUMENT_CREATE2"
    }
    $default | ConvertTo-Json | Out-File -Encoding utf8 $BapiMapFile
}

if (-not (Test-Path $OutDir)) {
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
}
$outFile = Join-Path $OutDir "bapi_field_catalog.$Release.json"

Write-Host "==> Generating catalog for release $Release" -ForegroundColor Cyan
Write-Host "    Target host: $Host / sysnr $SystemNumber / client $Client"
Write-Host "    BAPI map:    $BapiMapFile"
Write-Host "    Output:      $outFile"
Write-Host ""

$py = @"
import json, sys, os
try:
    from pyrfc import Connection
except ImportError:
    print('ERROR: pyrfc not installed; install pyrfc + SAP NW RFC SDK 7.50', file=sys.stderr)
    sys.exit(2)

bapi_map_file = r'''$BapiMapFile'''
out_file      = r'''$outFile'''
release       = r'''$Release'''

with open(bapi_map_file, 'r', encoding='utf-8') as fh:
    bapi_map = json.load(fh)

params = dict(ashost=r'''$Host''', sysnr=r'''$SystemNumber''',
              client=r'''$Client''', user=r'''$User''', passwd=r'''$Passwd''')
conn = Connection(**params)
print(f'[+] connected to {params["ashost"]} / client {params["client"]}')

catalog = {'_meta': {'source_release': release, 'generator': 'generate_field_catalog.ps1'}}
introspection_errors = []

for obj, fm in bapi_map.items():
    try:
        info = conn.call('RFC_GET_FUNCTION_INTERFACE', FUNCNAME=fm, LANGUAGE='E')
        fields = set()
        for p in info.get('PARAMS', []):
            # parameter itself; walk structures via DDIF_FIELDINFO_GET (SAP-released too)
            typ  = p.get('PARAMTYPE', '')
            tab  = p.get('TABNAME',   '')
            if not tab:
                # scalar parameter -- add its name
                nm = (p.get('PARAMETER') or '').upper()
                if nm and nm not in ('RETURN', 'MESSAGE'):
                    fields.add(nm)
                continue
            # structure or table parameter -- walk DDIF for its component fields
            try:
                di = conn.call('DDIF_FIELDINFO_GET', TABNAME=tab, LANGU='E')
            except Exception:
                di = {}
            for f in di.get('DFIES_TAB') or []:
                nm = (f.get('FIELDNAME') or '').upper()
                if nm and not nm.startswith('.'):
                    fields.add(nm)
        catalog[obj] = sorted(fields)
        print(f'    {obj:32s} {fm:36s} {len(fields):>5d} fields')
    except Exception as e:
        msg = f'{type(e).__name__}: {str(e)[:120]}'
        introspection_errors.append({'object': obj, 'fm': fm, 'error': msg})
        print(f'    {obj:32s} {fm:36s} ERROR {msg}', file=sys.stderr)

if introspection_errors:
    catalog['_meta']['introspection_errors'] = introspection_errors

# Merge with in-code baseline
try:
    sys.path.insert(0, os.path.join('lambda', 'utils'))
    from bapi_field_catalog import as_dict as baseline
    b = baseline()
    for obj, flds in b.items():
        merged = set(catalog.get(obj, [])) | set(flds)
        catalog[obj] = sorted(merged)
except Exception as e:
    print(f'    (baseline merge skipped: {e})', file=sys.stderr)

with open(out_file, 'w', encoding='utf-8') as fh:
    json.dump(catalog, fh, indent=2, sort_keys=True)
print(f'[+] catalog written: {out_file}')
"@

$tmp = New-TemporaryFile
$py | Out-File -Encoding utf8 $tmp.FullName
try {
    python $tmp.FullName
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[!] introspection returned non-zero -- see stderr above." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    Write-Host ""
    Write-Host "==> Done. To activate this catalog in the Lambda runtime:" -ForegroundColor Green
    Write-Host "    aws lambda update-function-configuration \``"
    Write-Host "      --function-name migrate4hana-data-migrator-prod \``"
    Write-Host "      --environment 'Variables={M4H_BAPI_FIELD_CATALOG_JSON=$outFile}'"
} finally {
    Remove-Item -Force $tmp.FullName
}
