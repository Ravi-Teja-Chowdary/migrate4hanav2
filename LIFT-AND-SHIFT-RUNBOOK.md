# Migrate4HANA — Lift-and-Shift Runbook
## End-to-end: laptop ECC (Ameerpet) → SAP S/4HANA on AWS (SAP CAL trial)

**Read `LIFT-AND-SHIFT-SETUP.md` first.** This runbook assumes:
- Your laptop ECC is up, reachable from the AWS VPC over Tailscale.
- The SAP CAL S/4HANA 2023 Fully-Activated Appliance is provisioned and running.
- `connections.json` has both `ecc` and `lift_and_shift_target` blocks filled in.
- Smoke test (§7 of setup) passed (steps 1–3 always; steps 4–5 once pyrfc is installed).
- `M4H_TARGET_MODE=basis_handover_only` is set in your shell (SAP CAL provisioned the S/4).

## Environment values used in every command below

| Side | Host | sysnr | client | user |
|---|---|---|---|---|
| **Source — laptop ECC** | `192.168.0.5` | `41` | `800` | `sapuser` |
| **Target — S/4HANA on AWS** | `32.195.65.246` | `00` | `100` | `MIGRATE_ADMI` |

Required env vars in every PowerShell session (the runner reads these — do not skip):
```powershell
$env:M4H_ECC_PASSWD     = "<password for sapuser on the laptop ECC>"
$env:M4H_TARGET_PASSWD  = "<password for SAP* on the S/4HANA target>"
$env:M4H_TARGET_MODE    = "basis_handover_only"
$env:SAPNWRFC_HOME      = "$PWD\sapnwrfc"
```

> **PowerShell gotcha:** `MIGRATE_ADMI` is a literal SAP superuser name and is safe inside
> single-quoted strings (`user='MIGRATE_ADMI'`). Do NOT pass it unquoted to PowerShell or it
> will be interpreted as a glob. Always wrap it in single quotes.

> **Local-mode architecture (verified by audit 2026-05-11):** the runner auto-activates
> `local_aws_shim.py` which monkey-patches `boto3` to emulate Secrets Manager (creds from
> `connections.json` + `M4H_ECC_PASSWD` / `M4H_TARGET_PASSWD`), S3 (filesystem at
> `./local-staging/<bucket>/<key>`), DynamoDB (in-process dict persisted to
> `local-staging/_dynamodb.json`), SSM (records would-be remote commands to
> `local-staging/_ssm_manual/*.sh` — you run them by hand), and a handful of others.
> So **no AWS-side IAM/S3/DDB setup is required for a first end-to-end test run**.
> The same handlers run unchanged against real AWS when `M4H_LOCAL_MODE=0` is set.

This runbook walks you through all **28 stages, 9 phases, 3 manual gates** of the
lift-and-shift pipeline. Each stage tells you:
1. **What it does** (one sentence)
2. **Command to run**
3. **What to expect** (logs, artifacts on S3, UI page to check)
4. **What to do if it fails**

> **Pace yourself.** A real migration of a tiny Ameerpet ECC into a Fully-Activated CAL S/4
> takes ~6–8 hours of *active* wall-clock time spread across 2–3 sessions. The CAL S/4 can
> be suspended between phases — just remember to **resume** before resuming the runbook.

---

## Visual map of the pipeline

```
PHASE 0 ─ ASSESS ─────────────  stage 1 → 2 → 3
PHASE 1 ─ PROVISION ──────────  stage 4 ─[gate1]→ stage 5
PHASE 2 ─ CODE ───────────────  stage 6 → 7 → 8 → 9a → 9b → 9c
PHASE 3 ─ CONFIG ─────────────  stage 10 → 11 → 12 → 12a → 12b → 12c
PHASE 4 ─ DATA-PREP ──────────  stage 13 → 14 → 15
PHASE 5 ─ DATA-LOAD (parallel)  stage 16 (MC) + stage 17 (LTMOM) + stage 18 (IDoc)
PHASE 6 ─ VALIDATE ───────────  stage 19 → 20 → 21 ─[gate2]→
PHASE 7 ─ CUTOVER ────────────  stage 22 → 23 → 24 → 25 ─[gate3]→ stage 26
PHASE 8 ─ RUN ────────────────  stage 27 (report)
```

Manual gates: **gate1** (basis handover) · **gate2** (pre-cutover) · **gate3** (final go-live).

---

## Command idiom

```powershell
# always activate venv first
.\.venv\Scripts\Activate.ps1

# run a single stage:
python run_local_lift_and_shift.py --only stage6 --run-id RUN-001 --ecc-host 192.168.0.5 --target-host 32.195.65.246

# run a phase (stage range):
python run_local_lift_and_shift.py --from-stage stage6 --through stage9c --run-id RUN-001

# resume after a manual gate:
python run_local_lift_and_shift.py --from-stage stage5 --through stage9c --run-id RUN-001
```

**Tip:** keep `--run-id` consistent across the whole migration so all artifacts on S3
group under `s3://<bucket>/runs/RUN-001/…`. Use a date-stamped ID like `RUN-2025-01-15`.

---

# PHASE 0 — ASSESS

**Goal:** Learn the source ECC, size the target, decide which migration object goes through which lane.
**Plane:** Orchestration only (read-only on ECC). Target S/4 is not touched yet.
**Duration:** 20–40 min on a small Ameerpet ECC.

## Stage 1 — System Discovery
**Handler:** `discovery-engine`
**What:** Reads ECC tables (DD02L, DD03L, REPOSRC, TFDIR, T000, T001, USR02, etc.) and
produces an inventory: custom programs, custom tables, function modules, org structure,
users/roles, integration endpoints.

**Run:**
```powershell
python run_local_lift_and_shift.py --only stage1 --run-id RUN-2025-01-15 --ecc-host 192.168.0.5
```

**Expect:**
- Console prints `[stage1] discovery-engine.handler` then a counts summary.
- Local artifact: `./local-staging/m4h-local/runs/RUN-2025-01-15/discovery/inventory.json`
  (this is where the shim materializes S3 `put_object` calls; if you have a real S3
  bucket and `M4H_LOCAL_MODE=0`, the object lands in S3 instead.)
- UI: Pipeline page → stage 1 turns green.

**If it fails:**
- `pyrfc.RFCError: Connection failed`: laptop ECC is down, or `M4H_ECC_PASSWD` wrong.
- `RFC_READ_TABLE: AUTHORIZATION FAILURE`: `sapuser` missing `S_TABU_DIS` (grant in SU01).

## Stage 2 — Sizing & Target Design
**Handler:** `sizing-advisor`
**What:** Reads ST03N + DBA stats from ECC, recommends HANA + app-server sizing for the target.
For SAP CAL you don't act on this — CAL has pre-set instance sizes — but the report is
useful evidence.

**Run:**
```powershell
python run_local_lift_and_shift.py --only stage2 --run-id RUN-2025-01-15
```

**Expect:** `s3://…/sizing/recommendation.json` with `recommended_hana_ram_gb`, etc.

## Stage 3 — Object Inventory & Lane Routing
**Handler:** `object-router`
**What:** For every migration object (Customers, Materials, Open POs, GL balances, …), decide:
- **MC lane** (~80% of objects): use SAP Migration Cockpit
- **LTMOM lane**: custom Z-objects requiring LTMOM modeling
- **IDoc lane**: interface data (bank statements, EDI partners)
- **Skip**: out-of-scope objects
Output is a DAG (objects with `depends_on`) — Phase 5 executes it as a Map.

**Run:**
```powershell
python run_local_lift_and_shift.py --only stage3 --run-id RUN-2025-01-15
```

**Expect:** `s3://…/object-router/routing.json`. Open it — you'll see entries like:
```json
{ "object": "Customer (BP)", "lane": "MC", "depends_on": ["CompanyCode","BPGrouping"] }
```

**Pause point:** Eyeball the routing. If anything looks wrong (e.g., a Z-table mis-routed
to MC), override by editing the JSON and re-uploading — or just press on for the first run.

---

# PHASE 1 — PROVISION

**Goal:** Validate the SAP CAL S/4 target is healthy and ready to receive transports + data.
**Duration:** 30 min (mostly basis-validator).

## Stage 4 — Target Stand-up
**Handler:** `target-provisioner`
**What:** For self-hosted (Launch Wizard / SWPM) deployments, this drives the install. For
**SAP CAL** you don't need this to do anything — the CAL appliance is already provisioned.
**Use `basis_handover_only` mode.**

**Run:**
```powershell
# Confirm M4H_TARGET_MODE is set; the runner reads it and passes basis_handover_only.
$env:M4H_TARGET_MODE = "basis_handover_only"
python run_local_lift_and_shift.py --only stage4 --run-id RUN-2025-01-15
```

**Expect:** `status=success, mode=basis_handover_only` immediately. Manifest at
`local-staging\m4h-local\runs\RUN-2025-01-15\target-provisioner\manifest.json` says
"Basis owns this install; Lambda will only validate."

## ⛔ Gate 1 — Basis Handover

**Manual checkpoint.** Confirm the CAL S/4 is reachable and the master password works.

```powershell
# from laptop, RFC ping via pyrfc:
python -c "from pyrfc import Connection; c=Connection(ashost='32.195.65.246',sysnr='00',client='100',user='MIGRATE_ADMI',passwd='$env:M4H_TARGET_PASSWD'); print(c.call('RFC_PING'))"
```

If you see `{}` it's good. The runner auto-approves the gate in local mode.

## Stage 5 — Basis Sanity
**Handler:** `basis-validator`
**What:** Connects to the target S/4 and validates:
- Clients (SCC4): client 100 exists, customizing-allowed
- Transport system (STMS): domain controller is the target, routes defined
- ICM endpoints: `/sap/bc/idoc_xml`, `/sap/opu/odata/sap/CA_DATA_MIGRATION_SRV` respond
- HANA & ABAP versions match expected `SAP S/4HANA 2023` floor

**Run:**
```powershell
python run_local_lift_and_shift.py --only stage5 --run-id RUN-2025-01-15 --target-host 32.195.65.246
```

**Expect:** 5 green checks. If any fail, go back to `LIFT-AND-SHIFT-SETUP.md §6` and fix.

---

# PHASE 2 — CODE

**Goal:** Extract every Z*/Y* from the laptop ECC, AI-remediate it for S/4HANA, package as
a CTS+ transport, deliver to the target, import, verify.
**Duration:** 1–2 hr (Ameerpet has very little custom code so it's quick).

## Stage 6 — Code Extraction
**Handler:** `code-analyzer` mode=`extract`
**What:** Pulls Z* programs, includes, classes, function modules, DDIC objects out of
ECC via `REPOSRC` / `TADIR` reads. Stores raw ABAP source on S3.

**Run:**
```powershell
python run_local_lift_and_shift.py --only stage6 --run-id RUN-2025-01-15
```

**Expect:** `s3://…/code/extracted/*.abap` files, count printed.

## Stage 7 — AST + GenAI Remediation
**Handler:** `code-analyzer` mode=`remediate`
**What:** Builds AST, scans for S/4-incompatible patterns (MATNR length, deprecated FMs,
BSEG direct access, etc.). If Bedrock is configured, asks Claude to rewrite. Writes
remediated source + diff alongside the original.

**Run:**
```powershell
python run_local_lift_and_shift.py --only stage7 --run-id RUN-2025-01-15
```

**Expect:** `s3://…/code/remediated/*.abap` + `s3://…/code/remediation-report.html`.

**Note:** If `M4H_BEDROCK_ENABLED` isn't set, GenAI is skipped — you still get the AST-based
deterministic fixes, just not the AI-suggested ones. That's fine for Ameerpet's small Z*.

## Stage 8 — Transport Build
**Handler:** `transport-artifact-builder` (object_kind=`code`)
**What:** Packages the remediated objects into a CTS+ transport — cofile + data files
(`K<TRKORR>` + `R<TRKORR>`). Validates the object list against `E071`.

**Run:**
```powershell
python run_local_lift_and_shift.py --only stage8 --run-id RUN-2025-01-15
```

**Expect:** `s3://…/transports/code/<TRKORR>/K…` and `R…`. Note the TRKORR (e.g. `NPLK900042`).

## Stage 9a — Transport File Placer
**Handler:** `transport-file-placer`
**What:** Copies the cofile + data file from S3 into `/usr/sap/trans/{cofiles,data}/` on
the target's transport host using SSM Run Command (or SFTP). Reads
`transport_host_instance_id` from `connections.json`.

**Run:**
```powershell
python run_local_lift_and_shift.py --only stage9a --run-id RUN-2025-01-15
```

**Expect:** SSM command id printed, exit code 0.

**If it fails:** SSM agent on the CAL S/4 EC2 may not be installed — SAP CAL doesn't put it
there by default. In **local mode**, the runner doesn't actually call AWS SSM — the shim
records the would-be command to `local-staging/_ssm_manual/local-ssm-<id>.sh` and prints
the file path; you then run that script yourself on the target host via SSH:
```powershell
type local-staging\_ssm_manual\local-ssm-<id>.sh   # inspect the commands
scp local-staging\_ssm_manual\local-ssm-<id>.sh s4hadm@32.195.65.246:/tmp/
ssh s4hadm@32.195.65.246 "sh /tmp/local-ssm-<id>.sh"
```

If you prefer pure manual STMS: download the cofile + data file from the local-staging
folder, then `scp` to the S/4 host:
```powershell
$src = "local-staging\m4h-local\runs\RUN-2025-01-15\transports\code"
scp $src\K9000042.NPL s4hadm@32.195.65.246:/usr/sap/trans/cofiles/
scp $src\R9000042.NPL s4hadm@32.195.65.246:/usr/sap/trans/data/
```

## Stage 9b — Transport Import Executor
**Handler:** `transport-import-executor`
**What:** Triggers `tp import` on the target via SSM (or via STMS RFC). This is the
**first stage that actually writes to S/4** — and it does so through `tp`, the SAP-shipped
transport tool. Every write is logged in STMS, fully supported.

**Run:**
```powershell
python run_local_lift_and_shift.py --only stage9b --run-id RUN-2025-01-15
```

**Expect:** RC 0 (success), 4 (warnings — usually OK), or 8/12 (errors — investigate).

**If RC=4:** look at the tp log — most likely missing object dependency. The runner will
print the offending object. Fix in stage 7's remediation rules, re-build, re-import.

**If SSM is unavailable / running in local mode:** SAP GUI on the target → **STMS →
Import Queue → Refresh → select your TRKORR → Import**. Watch the import monitor. Then
mark stage 9b done by hand:
```powershell
# Just create an empty success marker so 9c can read it:
New-Item local-staging\m4h-local\runs\RUN-2025-01-15\transports\code\imported.flag -Force
```

## Stage 9c — Transport Import Verifier
**Handler:** `transport-import-verifier`
**What:** Reads tp log + activation status via RFC. Confirms all objects activated, no
syntax errors. Output: pass/fail per object.

**Run:**
```powershell
python run_local_lift_and_shift.py --only stage9c --run-id RUN-2025-01-15
```

**Pause point:** Open the verification report. If a Z-program has a syntax error on S/4,
go back to stage 7, add the failing pattern to the remediation rules, re-run phase 2 with
a new transport.

---

# PHASE 3 — CONFIG

**Goal:** Extract customizing tables (T-tables) from ECC, package as BC Sets / customizing
transports, import to target.
**Duration:** 1–2 hr. **Pattern is identical to Phase 2.**

| Stage | Handler | Mode |
|---|---|---|
| 10 | `config-replicator` | mode=extract |
| 11 | `bc-set-builder` | — |
| 12 | `transport-artifact-builder` | object_kind=config |
| 12a | `transport-file-placer` | — |
| 12b | `transport-import-executor` | — |
| 12c | `transport-import-verifier` | — |

**Run as a phase:**
```powershell
python run_local_lift_and_shift.py --from-stage stage10 --through stage12c --run-id RUN-2025-01-15
```

**Watch out for:**
- The SAP CAL Fully-Activated Appliance has its **own** customizing pre-loaded. You will
  see conflicts (same T-key, different values). For the first run, **let the appliance
  win** — i.e., skip the conflicting BC Set entries. The honest answer here is: configuration
  is something a functional consultant must review object-by-object; this tool generates
  candidates, not final config.
- BC Set activation (`SCPR20`) is **manual via Fiori**, not headless. The runner will
  produce a manual_gate event with the BC Set names. Activate them in batch in SAP GUI →
  `/nSCPR20`, then resume.

---

# PHASE 4 — DATA-PREP

**Goal:** Read master + transactional data from ECC, cleanse + dedupe (BPs), generate
load-ready templates (MC XML / IDoc XML / staging CSV).
**Duration:** 1–3 hr depending on data volume.

## Stage 13 — Data Extraction
**Handler:** `data-migrator` mode=`extract`
**What:** For each object in the routing DAG (stage 3 output), reads source tables from
ECC. Customers from KNA1/KNVV/ADRC, Vendors from LFA1/LFB1/LFM1, Materials from
MARA/MARC/MARD/MBEW, Open POs from EKKO/EKPO with EBELP not yet GR'd, etc.

**Run:**
```powershell
python run_local_lift_and_shift.py --only stage13 --run-id RUN-2025-01-15
```

**Expect:** `s3://…/data/raw/{object}/*.csv` per object.

**If the laptop ECC has no real data:** that's fine for a smoke test. The Ameerpet system
usually has a few hundred sample customers. Real volume is irrelevant for the first
end-to-end proof.

## Stage 14 — Data Hygiene (BP Dedup)
**Handler:** `data-hygiene`
**What:** Runs AWS Entity Resolution (or local fallback) over Customer + Vendor records,
identifies dupes that should converge to a single Business Partner on S/4. Writes
`bp_canonical.csv` + `dedup_report.html`.

**Run:**
```powershell
python run_local_lift_and_shift.py --only stage14 --run-id RUN-2025-01-15
```

> AWS Entity Resolution costs ~$1.00 per 1000 records. For a few hundred Ameerpet
> records, total cost is cents. If you want to skip ER entirely, set
> `M4H_DEDUP_MODE=local` — the lambda has a deterministic in-process matcher.

## Stage 15 — Template Generation
**Handler:** `data-migrator` mode=`generate_templates`
**What:** For each object, emit the load-time artifact for its lane:
- **MC lane** → `<object>.xml` matching the Migration Cockpit XML schema
- **LTMOM lane** → staging-table CSV
- **IDoc lane** → IDoc XML payloads

**Run:**
```powershell
python run_local_lift_and_shift.py --only stage15 --run-id RUN-2025-01-15
```

**Expect:** `s3://…/data/templates/mc/*.xml`, `…/templates/ltmom/*.csv`,
`…/templates/idoc/*.xml`.

---

# PHASE 5 — DATA-LOAD

**Goal:** Feed the templates into Migration Cockpit, LTMOM, and IDoc inbound — in parallel,
respecting the DAG dependencies.
**Duration:** 2–4 hr for a small dataset; days for real volume.

## Stage 16 — Migration Cockpit lane
**Handler:** `migration-cockpit-orchestrator`
**What:** For each MC-lane object:
1. Calls MC OData `POST /CA_DATA_MIGRATION_SRV/Projects` to create a project (if missing).
2. Uploads the XML template via `POST .../Files`.
3. Triggers **Simulate** via `POST .../Actions/SimulateRun`.
4. Polls the BAL log for completion.
5. On success, triggers **Production run** (after the pre-cutover gate, see Phase 7).

**Run:**
```powershell
python run_local_lift_and_shift.py --only stage16 --run-id RUN-2025-01-15
```

**Honest caveat:** SAP MC OData is partial. Some objects (e.g., activations, deferred
postings) require a **click in Fiori UI**. When the orchestrator hits one, it emits
`status=manual_gate` with an explicit instruction:
> *"Open Fiori → Migrate Your Data → project M4H_RUN_2025_01_15 → Customer → click Start
> Production Run. Press Enter here when done."*

Click, return to the runner, press Enter. The runner resumes monitoring.

## Stage 17 — LTMOM lane
**Handler:** `ltmom-orchestrator`
**What:** **Honest scope:** LTMOM has no API. This stage emits a **design document**
(`s3://…/ltmom/<object>-design.md`) and prints the SAP GUI clicks for a Basis admin to
build the LTMOM custom object. After they build it, the runner verifies via RFC reads
that the staging tables are populated, then triggers the import via the standard MC
framework (which LTMOM custom objects run on).

If your routing has no LTMOM-lane objects, this stage is a no-op.

## Stage 18 — IDoc lane
**Handler:** `idoc-orchestrator`
**What:** POSTs every generated IDoc XML to `https://<S/4>:44300/sap/bc/idoc_xml`,
monitors DOCNUMs via `IDOC_INBOUND_SINGLE` / RFC reads of `EDIDC`. **This is the genuinely
headless lane.**

**Run all three in parallel:**
```powershell
# In three PowerShell windows:
python run_local_lift_and_shift.py --only stage16 --run-id RUN-2025-01-15
python run_local_lift_and_shift.py --only stage17 --run-id RUN-2025-01-15
python run_local_lift_and_shift.py --only stage18 --run-id RUN-2025-01-15
```

---

# PHASE 6 — VALIDATE

**Goal:** Prove the data on S/4 matches the source. Generate UAT scripts. Produce a
85-check scorecard.
**Duration:** 30 min.

## Stage 19 — Reconciliation
**Handler:** `migration-validator`
**What:** Read-only on both sides. Counts, balance sums, key coverage, sample hash
comparison. Generates `recon_report.html`.

```powershell
python run_local_lift_and_shift.py --only stage19 --run-id RUN-2025-01-15
```

**Acceptance:** All recon items must show source==target counts within tolerance. If a
delta exists, investigate before the cutover gate.

## Stage 20 — Test Generation (DITL)
**Handler:** `test-generator`
**What:** Reads ST03N from ECC for top-100 transaction codes, generates UAT scripts
("walk a customer create on S/4 — expect screen X"). Output: `s3://…/uat/scripts.html`.

## Stage 21 — GO-LIVE Scorecard
**Handler:** `migration-completeness-analyzer`
**What:** 85 checks across data, code, config, integrations. Renders `scorecard.html`.
UI: Scorecard page.

## ⛔ Gate 2 — Pre-Cutover

**Stop. This is a real human gate.** Review the scorecard. Get UAT sign-off. Only when
you're satisfied, type:
```
gate2: approved
```
(Or in local mode: the runner auto-approves and prints a warning.)

---

# PHASE 7 — CUTOVER

**Goal:** Lock ECC, extract delta, load delta, re-recon, flip integrations.
**Duration:** typically a weekend window (4–12 hr). For your Ameerpet smoke test, 30 min.

> **Critical ordering note:** ECC-lock comes BEFORE final-delta-extract. Stage 22 →
> Stage 23. This avoids the brownfield race where users keep posting while you're
> extracting. The state machine enforces this order.

## Stage 22 — ECC Lock
**Handler:** `cutover-orchestrator` action=`lock_ecc`
**What:** Sets the laptop ECC to read-only mode via **SM02** (system message) +
**SCC4** (client → "no changes allowed") + locks dialog users via mass `SU10`. Users get
"Migration in progress" on logon.

```powershell
python run_local_lift_and_shift.py --only stage22 --run-id RUN-2025-01-15
```

## Stage 23 — Delta Extract
**Handler:** `delta-extractor`
**What:** Re-reads ECC for everything that changed since the Phase-4 extract timestamp.
Uses table change-pointers / `ERDAT`/`AEDAT` columns where available; for the rest, full
re-read (which is fine after lock — no new writes can happen).

## Stage 24 — Delta Load
**Handler:** `migration-cockpit-orchestrator` mode=`delta_load`
**What:** Same as stage 16 but on the delta-only templates.

## Stage 25 — Final Reconciliation
**Handler:** `migration-validator` mode=`final`
**What:** Same as stage 19 but compared against locked ECC. **Result is binding for
go/no-go.**

## ⛔ Gate 3 — Final Go-Live
Review final recon. If green and business signs off, approve.

## Stage 26 — Integration Activation
**Handler:** `integration-activator`
**What:** Re-points downstream integrations (CPI, PI/PO, custom RFC destinations) from
the laptop ECC to the CAL S/4. For your smoke test you probably have none — stage is
near-no-op.

---

# PHASE 8 — RUN

## Stage 27 — Final PDF Report
**Handler:** `pdf_report_generator`
**What:** Builds the executive PDF combining: discovery report, scorecard, recon, test
results, transport list, BC Set list, MC load summaries, IDoc tally, cutover timing,
rollback plan. Output: `s3://…/report/migration-report.pdf`.

```powershell
python run_local_lift_and_shift.py --only stage27 --run-id RUN-2025-01-15
```

**At this point your laptop ECC is converted to S/4HANA on AWS.** The Ameerpet system is
locked and effectively decommissioned (you can resurrect it for read-only history if
needed). The CAL S/4 holds your migrated data + code + config.

---

# Rollback (if anything goes wrong before gate 3)

```powershell
python -c "from importlib import import_module; m=import_module('rollback-manager.handler'.replace('-','_')); print(m.lambda_handler({'run_id':'RUN-2025-01-15','action':'switch_back'},None))"
```

This unlocks the laptop ECC (`SM02` message removed, `SCC4` restored, users unlocked),
re-points integrations back, and tags the CAL S/4 as "do not use" (you can suspend the
appliance to stop costs).

**Rollback is honest:** it switches back to ECC. It does **not** un-post anything already
written on S/4. After gate 3 + business hours, real rollback is a forward-fix project,
not a switch.

---

# Troubleshooting appendix

### "pyrfc connection refused"
Tailscale is down, or the SAP CAL appliance is suspended. Check `tailscale status` and
the CAL Web UI.

### "MC OData returns 401"
The `mc_user` in `connections.json` lacks the `/IWFND/RT_GW_USER` role. Use `MIGRATE_ADMI` for the
first run.

### "Transport import RC=12"
A pre-req object is missing on target. Usually means stage 7 missed a remediation. Add the
pattern to the AST rules in `lambda/code-analyzer/rules/*.json`, rebuild from stage 6.

### "IDoc status 51 — Application error"
Partner profile (`WE20`) doesn't accept the IDoc type. Add it on the target. Re-post via
`BD87`.

### "BC Set activation failed"
The customizing key already exists with a different value. Decide who wins (you or the
CAL appliance). For the first run let the appliance win — skip and document.

### "I broke connections.json"
Restore from the original committed:
```powershell
git checkout connections.json
```
Then re-enter the target block.

### "I'm running out of AWS Free Tier"
The orchestration plane is well within free tier. The only big spend is the SAP CAL
S/4 EC2. **Suspend it from CAL Web UI between phases.** A suspended appliance costs
storage only (~$5/day) instead of compute (~$200/day).

### "I want to start over"
```powershell
# new run id, fresh artifacts on the local filesystem
python run_local_lift_and_shift.py --run-id RUN-FRESH --dry-run
# then real run from stage1:
python run_local_lift_and_shift.py --run-id RUN-FRESH
```
The old run's artifacts stay in `local-staging/m4h-local/runs/<old-id>/` for forensics.
If you want a truly clean slate: `Remove-Item local-staging -Recurse -Force`.

### "I see `[local-shim] active. staging=…` everywhere — is that supposed to happen?"
Yes. The runner sets `M4H_LOCAL_MODE=1` automatically and prints that banner on every
invocation. It means: AWS Secrets Manager / S3 / DynamoDB / SSM calls are emulated
against `./local-staging/` instead of going to real AWS. To run against real AWS
(deployed via Terraform), prefix the invocation with `$env:M4H_LOCAL_MODE="0"`.

### "Stage 1 fails with `ModuleNotFoundError: pyrfc`"
You haven't installed pyrfc yet. The SDK is already in the repo (`sapnwrfc/lib/`);
just point `SAPNWRFC_HOME` at it and pip-install:
```powershell
$env:SAPNWRFC_HOME = "$PWD\sapnwrfc"
pip install pyrfc        # or: pip install pynwrfc (no compiler needed)
```

### "Stage 27 PDF says `skipped in local mode`"
That stage runs `pdf_report_generator.generate_pdf_from_file` against a stub input when
no upstream JSON exists yet. After you've successfully run stages 1–26 with real data,
the final PDF assembles from those artifacts. For a smoke test it's a no-op success.

---

# What to do after the migration is "done"

1. **Hypercare (1–2 weeks)** — keep the laptop ECC running read-only for reference; users
   on CAL S/4. Watch SAP CAL costs daily.
2. **Decommission ECC** — once you trust the new S/4, snapshot the laptop ECC volume,
   archive, shut down the VM.
3. **CAL renewal** — the free trial is 30 days. To keep the S/4 alive past day 30 you
   either: extend the trial (one-time), pay for CAL hours, or migrate the CAL appliance
   to a customer-owned S/4HANA license (this is a BYOL handover, not a re-migration).

You now have a working SAP S/4HANA system on AWS that was migrated from your laptop
ECC using only SAP-shipped tools on the write path — meaning a hypothetical S-user
holder could open any of Migrate4HANA's artifacts on the SAP support portal, replay
them with `tp`/MC/LTMOM/IDoc, and reproduce the exact same outcome. That's the
"support-preserving" property this branch is designed to deliver.
