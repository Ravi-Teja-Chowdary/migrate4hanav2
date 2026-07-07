# Prereq Closer Runbook — customizing gaps blocking S/4 loads

> **📢 2026-07-07 update — automated path now available.** The wizard's
> *Prepare S/4 target* section (Project page, appears when *Load to S/4* is
> ticked) auto-generates a self-contained ABAP report that creates every
> customizing row the migration needs. Two clicks: **Generate** → paste
> into S/4 `SE38` → `F8`. Skip the manual SPRO steps below if the
> auto-generated script runs cleanly (`WRITE:` output at the bottom
> reports total OK / errors). Path A / B below remain the fallback when
> the auto-path can't reach some tables.

## Automated flow — the new default

1. In the wizard, tick *Load to S/4HANA* and (optionally) *Preserve
   source document numbers*.
2. In the newly-visible *Step 1 — Prepare S/4 target* panel, click
   **Generate S/4 prep script**. Takes ~10 seconds — the tool scans ECC
   customizing over pyrfc.
3. The generated ABAP appears inline. Choose one of:
   - **Copy to clipboard** → in S/4 GUI: `SE38` → new program
     `ZM4H_PREP_<runId>` → paste → save → `F8` (~30 sec).
   - **Download .abap** → same as above but via file upload.
   - **Auto-run on S/4** → tool calls `RFC_ABAP_INSTALL_AND_RUN` and
     executes on S/4 for you. Works on CAL/IDES and any tenant that
     hasn't disabled that RFC in `SM19`. Response is surfaced in the UI.
4. Tick *I have run the prep script on S/4* → *Start migration* button
   unlocks.

Rollback: the tool also emits `ZM4H_UNDO_<runId>.abap` (companion file).
Runs the same way in S/4 and deletes every row the prep report created.
Safe to run multiple times.



**Written**: 2026-07-06, in response to run `wiz-20260705T151739Z-0afc3ca1` which
dead-lettered 377 records because target CAL S/4HANA client 100 lacks the
customizing rows the ECC-side data references.

## The problem in one paragraph

`wiz-20260705T151739Z-0afc3ca1` ran the full lift-and-shift pipeline with
`load_to_s4 = true`. The data-migrator surfaced 5 successful ExchangeRates
creates and 377 dead-lettered rows. **Every dead-letter falls into "S/4 lacks
the customizing this row needs"** (see `local-staging/m4h-local/runs/wiz-.../data-migrator/summary.json`
`data_quality` block for the aggregate).

The `bc-set-builder` stage ran but its manifest shows
`"build_method": "ssh_scpr3"`, `"ssh_output": "(local-shim: assumed success)"`,
`"tables": []` — the SSH bridge to the S/4 `scpr3` transaction is **stubbed
locally**. No BC-Set actually deployed. That's the root infra gap.

## Which customizing tables need to move

Extracted from the failed_records.json signatures + reproduced from
`_deprecated` originals + memory `[exchange-rates-customizing]`.

| ECC table | What it holds | Failing ECC row values | Failing objects on S/4 |
|---|---|---|---|
| **TKA01** | Controlling areas | area `1000` | CostCenter (50), ProfitCenter (50) |
| **T023** | Material groups | group `00101` | Material (50) |
| **TCURV** | Exchange rate types | types `001`, `1001` | ExchangeRates (~45) |
| **TCURF** | Exchange rate factors | factor rows keyed by `KURST=001` / `1001` | ExchangeRates (same 45) |
| **TFACD** + **TFAIN** | Factory calendar def + yearly intervals | calendar `01` | OpenPO (~15) |
| **T001** (probably fine but verify) | Company codes | `1000`, `1710` | prereq for CostCenter |
| **T024** / **T024E** | Purchasing groups + orgs | (referenced by PO items) | possibly OpenPO |

All of these are already in the `CONFIG_TABLES` catalog after the
2026-07-06 patch to `lambda/config-replicator/handler.py:110-165`.

## Path A — automated via the tool's config lane (preferred once shim removed)

**Prerequisite that this path requires**: the `ssh_scpr3` bridge in
`bc-set-builder` needs to be un-shimmed. Right now it just writes
`ssh_output = "(local-shim: assumed success)"` without invoking anything on
S/4. Real behavior would SSH into the S/4 host as a Basis user, invoke SCPR3
(BC-Set activation) via `sapevt` or a batch job, and return the actual return
code. That's a separate infrastructure change; not blocking today's demo.

**Once the bridge is real**, this is the one-command path:

1. In the wizard, on the object-selection page, check **Customizing** (or
   whatever the pipeline calls the config lane — verify by opening the
   wizard: look for `config-replicator`, `bc-set-builder`, or "Configuration"
   in the object list).

2. Row cap: irrelevant for config (each customizing table extracts all rows).

3. `Start migration + load to S/4`. The pipeline runs:
   - `config-replicator` extracts every table in the CONFIG_TABLES catalog
     via `RFC_READ_TABLE` and writes `config/ecc-config-dump.json`
   - `bc-set-builder` groups tables by functional area (Financial,
     Controlling, MaterialsMgmt, SalesDistribution, **CurrencyConfig**
     (new), **Calendars** (new)), packages each as a BC Set, generates the
     transport object list
   - `transport-artifact-builder` builds the K/R cofile pair
   - `transport-file-placer` uploads via SSM to `/usr/sap/trans/data|cofiles`
   - `transport-import-executor` triggers `tp import` on the S/4 host
   - `transport-import-verifier` reads E070/E070C to confirm import success

4. Verify each customizing landed (see "Verification" below).

## Path B — SPRO / SM30 manual fallback (the reliable one for the demo)

Because the ssh_scpr3 bridge is currently shimmed, Path A won't actually apply
anything on S/4. **For the client demo, use Path B.** Each step takes 2-5
minutes. Total: about 30 minutes.

**Prerequisites**: SAP GUI logged into CAL S/4 client 100 as user with SAP_ALL
or at least S_TABU_DIS + S_TABU_CLI activity 02 (change).

### B.1. Copy controlling area 1000 from ECC → S/4 (fixes CostCenter + ProfitCenter, 100 rows)

Two options, pick one:

- **Option B.1a — copy an existing controlling area on S/4 to key `1000`**:
  - S/4: `SPRO` → `Controlling` → `General Controlling` → `Organization` → `Maintain Controlling Area` → `Copy Controlling Area`
  - Source area: `A000` (already exists on CAL IDES); Target area: `1000`
  - Copy all subordinate customizing: version, number ranges, standard hierarchy
  - Save.

- **Option B.1b — SE16 direct row copy**:
  - S/4: `SE16` → `TKA01` → Filter `KOKRS = A000` → Display → note the field values
  - `SM30` → `V_TKA01` → New Entries → `KOKRS = 1000`, copy the field values from A000 (adjust BEZEI to "Copied from A000 for M4H migration"), currency WAERS (usually EUR or USD)
  - Save
  - Repeat for **TKA02** (V_TKA02): assign controlling area `1000` to your company codes

Verify: `SE16` → `TKA01` → `KOKRS = 1000` → 1 row exists.

### B.2. Add material group `00101` to T023 (fixes Material, 50 rows)

- S/4: `SPRO` → `Logistics — General` → `Material Master` → `Settings for Key Fields` → `Define Material Groups`
- Or: `SM30` → `V_T023` → New Entries → `MATKL = 00101`, description "M4H Legacy Material Group", valuation class blank (fill from ECC if that field is used)
- Save

Verify: `SE16` → `T023` → `MATKL = 00101` → 1 row exists.

### B.3. Set up exchange rate types `001` and `1001` (fixes ExchangeRates, ~45 rows)

Rate types + factors are the biggest, per your `[exchange-rates-customizing]`
memory.

- **Rate type registration** — `SM30` → `V_TCURV`:
  - New Entries → `KURST = 001`, `BWAER = EUR` (base currency), other fields
    default; save
  - New Entries → `KURST = 1001`, `BWAER = USD` (or whatever ECC uses; check
    ECC `SE16` → `TCURV` → `KURST = 1001` for the value); save

- **Factor rows** — `SM30` → `V_TCURF`:
  - This needs one row per (rate type × currency pair × valid-from date).
    ECC has 358 factor rows per memory. On S/4 you can either:
    - Bulk-copy: export TCURF from ECC via `SE16` → download to Excel →
      `LSMW` recording or `SM30` mass upload
    - Or shortcut for demo: run `S_BCE_68000174` (Rate Types Copy) which
      creates a minimal factor set

Verify: `SE16` → `TCURV` → count of entries increased by 2. `TCURF` → filter
`KURST IN (001, 1001)` → non-zero row count.

### B.4. Create factory calendar `01` (fixes OpenPO, ~15 rows)

- S/4: `SCAL` (Factory Calendar transaction) → `Change` → `Calendar ID = 01`
- Or: `SPRO` → `SAP NetWeaver` → `General Settings` → `Maintain Calendar`
- Configure: description "M4H Legacy Factory Cal", first weekday Monday,
  workdays Mon-Fri, holidays: reference an existing holiday calendar (US or
  copy from your ECC's calendar 01 via SE16 → TFACD/THOL)
- Save & activate

Verify: `SE16` → `TFACD` → `IDENT = 01` → 1 row exists. `SM30` → `V_TFAIN`
should show at least the current year populated.

## Verification once all four are done

**Quick sanity**: SE16 spot check on each table above — all counts non-zero
for the row values the failed_records reference.

**Real proof**: re-run the same wizard config (same object list, same row cap,
same load_to_s4=true, same simulation_mode=false setting). Expected outcome:

| Object | Before (2026-07-05 run) | Expected after prereq closure |
|---|---:|---:|
| ExchangeRates | 50 attempted, 5 created, 45 dead-letter | 50 → 50 created |
| CostCenter | 50 attempted, 0 created, 50 dead-letter | 50 → 40-50 created (a few might still fail on cost-element master data) |
| ProfitCenter | 50 attempted, 0 created, 50 dead-letter | 50 → 45-50 created |
| Material | 50 attempted, 0 created, 50 dead-letter | 50 → 45-50 created (some may fail on plant/valuation) |
| OpenPO | 27 attempted, 0 created, 27 dead-letter | 27 → 20-27 created (some may fail on vendor prerequisites, deliver-to plant, etc.) |
| BusinessPartner | 50 attempted, 0 created, 50 dead-letter (DATA_QUALITY) | **same 50 dead-letter** — this failure is ECC data quality (blank NAME), NOT S/4 customizing. Fix by cleansing KNA1/LFA1 upstream. |
| OpenAR / OpenAP | 100 attempted, 100 dead-letter (DATA_QUALITY) | **same** — blank COMP_CODE/CLEARING_GL/PROFIT_CTR in ECC. Cleanse upstream. |

**Expected success rate**: from 5/377 = 1.3% → ~205/377 = 54%. The residual 45%
is genuine ECC data quality (BP/AR/AP with blank mandatory fields), not
S/4 customizing.

To also close the ECC data-quality half, run `lambda/data-hygiene/handler.py`
against those object types first — it flags blank-required-field rows so a
data steward can decide (patch upstream vs skip).

## Section C — External Number Assignment (needed only if client wants ECC doc numbers preserved on S/4)

### When to do this section

Skip this section if you're happy for S/4 to assign fresh document numbers
(e.g. ECC sales order 12966 becomes S/4 0000110483). The tool records the
source→target map in DynamoDB (`migrate4hana-key-map-prod`) either way, so
audit is intact.

**Do this section if** the client wants to open S/4 VA03 / ME23N / VL03N /
VF03 and type the exact ECC document number — a common demo requirement.
When this is configured and the wizard toggle
`Preserve source document numbers` is on, the BAPI honours the source key
via its external-number field (`SALESDOCUMENTIN`, `DELIVERY`, `DOC_NUMBER`,
etc.) and the S/4 record is created with the ECC number.

### Prereq

SAP GUI logged into CAL S/4 client 100 as user with SAP_ALL or at least
S_TABU_DIS + S_TABU_CLI activity 02 (change).

### C.1. Sales-side document types (VOV8)

Sales order (VA), returns (RE), credit-memo request (CR/G2), debit-memo
request (DR/L2), quotation (QT), inquiry (IN), sales contract (WK/CQ/QC/MV):

1. S/4: `SPRO` → `Sales and Distribution` → `Sales` → `Sales Documents` →
   `Sales Document Header` → `Define Sales Document Types` (or launch `VOV8`
   directly).
2. Select each doc type your ECC data uses (start with `VA` = standard SO
   and `RE` = returns since those are the demo drivers).
3. In the details view, set **Number range ext. assg.** (`NUMKE`) to a
   number range interval that has the **Ext** flag ticked in `SNRO` object
   `RV_BELEG`.
   - Quick check: `SNRO` → object `RV_BELEG` → interval overview →
     the interval assigned to your doc type's `NUMKE` should show `Ext = X`.
   - If not, either flip the `Ext` checkbox on that interval or point
     `NUMKE` at a new interval that has it ticked (e.g. interval `A1`
     covering `0000100000–0000199999` — sized to comfortably cover the ECC
     number range you're bringing over).
4. Leave `NUMKI` (internal range) alone so orders created via the S/4
   Fiori GUI still get internal numbers — external range only kicks in
   when the BAPI passes `SALESDOCUMENTIN`.
5. Save. Transport prompt is OK to `Local Change` for the demo client.

Verify: `SE16` → `TVAK` → filter your doc types → `NUMKE` populated
with the external interval.

### C.2. Delivery types (`0VLK` / SPRO — Logistics Execution → Shipping → Deliveries → Define Delivery Types)

1. Launch `0VLK` or navigate via SPRO.
2. Select each delivery type (`LF` = outbound delivery — usually enough).
3. Set the external number range interval on the delivery type. Same idea
   as C.1: `SNRO` object `RV_BELEG` interval must have `Ext = X`.
4. Save.

Verify: `SE16` → `TVLK` → filter `LFART = LF` → external range populated.

### C.3. Billing types (`VN01` for number ranges + SPRO — Sales and Distribution → Billing → Billing Documents → Define Billing Types)

1. Launch `VN01` and either edit an existing external interval or create
   a new one for billing docs. Tick `Ext.`.
2. Then `SPRO` → billing types → select each `FKART` (`F2` = standard
   invoice, `RE` = return credit note, etc.).
3. Assign that external interval to the billing type's external-range
   field.
4. Save.

Verify: `SE16` → `TVFK` → filter your billing types → external range
populated.

### C.4. Confirm the wizard toggle

In the migrate4hana wizard, on the project page, tick:

- ☑ **Preserve source document numbers (VBELN, EBELN, delivery, billing…)**

Then click *Start migration + load to S/4HANA*. The Live-ops progress log
will show `M4H_PRESERVE_SRC_NUMBERS=1 → source document numbers will be
preserved on S/4`. Any doc type still on internal range will silently keep
its own numbers — no failure; the mapping in `migrate4hana-key-map-prod`
still records the source→target pair for that object.

### C.5. Quick verification after the run

For a single sales order:

```powershell
# get the target key from the ledger
aws dynamodb get-item `
  --table-name migrate4hana-key-map-prod `
  --key '{"source_key":{"S":"12966"},"object_type":{"S":"SalesOrder"}}' `
  --region us-east-1
```

If C.1 was done correctly, `target_key` in the output equals the source key
(here `0000012966`). If C.1 was not done, `target_key` is a fresh S/4
number (e.g. `0000110483`) — both are valid; the demo just needs to show
the client the ledger for provenance.

Then in S/4 GUI: `VA03` → enter the number that came back from the ledger
→ order opens.

## What NOT to do

- **Don't disable the data-quality gate** to force those 377 records through.
  The tool is refusing them because the BAPI on S/4 would have refused them
  anyway; disabling the gate just moves the same rejection one hop
  downstream, and the audit trail becomes noisier.

- **Don't use SE16N in edit mode** to force customizing entries — that's on
  the "forbidden techniques" list in `support_compliance.forbidden_techniques_asserted_absent`
  in the summary.json. Sticks to SM30 / SCPR3 / SPRO.

- **Don't skip TCURF** thinking TCURV alone is enough. The ExchangeRates
  spine explicitly checks both — 27 rate types + 358 factor rows is the
  documented minimum per your memory `[exchange-rates-customizing]`.

## Un-shim `ssh_scpr3` (separate task, not blocking demo)

Once real BC-Set activation is wanted end-to-end, the `bc-set-builder` needs
to actually call SCPR3 on the S/4 host. Current code writes:

```python
ssh_output = "(local-shim: assumed success)"
```

Real behavior needs (a) `paramiko` or `boto3.client("ssm").send_command` to
the S/4 EC2/CAL host, (b) invoke `SAP_SBTI` batch or `sapevt` triggering the
BC-Set activation program, (c) parse the return code + spool ID. About 1-2
days of work — not for this demo.

## Files touched by this runbook

- `lambda/config-replicator/handler.py` — added T023 (Material Groups),
  full `currency_config` area (TCURV, TCURF, TCURC, TCURW), full `calendars`
  area (TFACD, TFAIN, THOC, THOL, THOCD)
- `PREREQ_RUNBOOK.md` — this document
