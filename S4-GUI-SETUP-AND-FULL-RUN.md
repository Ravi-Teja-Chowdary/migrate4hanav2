# S/4 GUI Setup + Full End-to-End Run

> Read this with `HOW-TO-RUN.md` (laptop side). This doc covers the **S/4-side
> switches** that have to be flipped in SAP GUI before a full ECC→S/4 run, then
> the run itself, then an **honest statement of what the result will be**.
>
> Do the GUI steps on your **Windows Remote Desktop box (3.237.83.66)**, which has
> SAP GUI. Log on: System = the S/4 (vhcals4hci), Client `100`, User `SAP*`,
> password = your master password.

---

## Where we already are (proven)
- ✅ RFC to both ECC and S/4 works; `SAP*` has full authorization (`SAP_ALL`).
- ✅ IDoc web service `/sap/bc/idoc_xml` is **active** (you did this).
- ✅ A test IDoc physically landed in S/4 (DOCNUM created, status 56).
- ⏳ Status 56 = "no partner profile" → the data arrived but didn't post into a
  business object yet. The GUI steps below close that gap.

There are **three doors** into S/4. You do **not** need all three for a first
full run — pick based on what you want to move:

| Door | Moves | GUI setup effort |
|---|---|---|
| **IDoc** | master + some transactional data | Low–Medium (2 steps) |
| **Migration Cockpit** | bulk master/transactional data | High (Gateway + project) |
| **Transport (tp)** | custom code + config | High (STMS + OS access) |

**Recommended first full run: use the IDoc door for data.** It's the closest to
done. Migration Cockpit and Transport are bigger setups — treat them as phase 2.

---

# PART 1 — S/4 GUI setup

## 1A. IDoc door (data) — finish this one

### Step 1 — Define the sender system  (transaction `BD54`)
1. In SAP GUI, type `/nBD54` in the top command box → Enter.
2. Click **New Entries**.
3. Add a row: **Log. System** = `M4HSENDER`, **Name** = `Migrate4HANA sender`.
4. Save (💾). If asked for a transport request, choose **Local Object** (`$TMP`).

### Step 2 — Create the inbound partner profile  (transaction `WE20`)
1. `/nWE20` → Enter.
2. Left tree: click **Partner Type LS** → click the **Create** icon (blank page).
3. **Partner No.** = `M4HSENDER`, **Partn. Type** = `LS`. Save.
4. In the lower **Inbound parameters** box, click the **+** (Create) icon.
5. **Message Type** = `MATMAS`, **Process Code** = `MATM`,
   select **Trigger Immediately**. Save.
6. (Repeat step 4–5 for each data type you'll load:
   `DEBMAS`/`DEBM` = customers, `CREMAS`/`CREM` = vendors,
   `COND_A`/`COND` = pricing, etc. For a first run, just `MATMAS` is enough.)

### Step 3 — Allow changes in the client  (transaction `SCC4`) — usually already OK
1. `/nSCC4` → Enter → switch to change mode (pencil) → double-click client `100`.
2. Ensure **"Changes and Transports for Client-Specific Objects"** =
   *Changes allowed*. Save. (On a Fully-Activated Appliance this is normally set.)

**That's the IDoc door done.** After this, an IDoc for `MATMAS` will *process*
(not just land). See Part 3 for the honest caveat about payload completeness.

## 1B. Migration Cockpit door (data) — phase 2, needs Gateway work
This door returned *"no backend service found"* — the OData service isn't
published on the embedded Gateway. Unlocking it:
1. `/n/IWFND/MAINT_SERVICE` → **Add Service**.
2. System Alias = `LOCAL` → search Technical Name `*DATA_MIGRATION*` → if it
   appears, select it → **Add Selected Services** → package `$TMP`.
3. If it does **not** appear ("no backend service found"), the service must first
   be registered in the backend (`/n/IWBEP/REG_SERVICE`) — **this is a genuine
   SAP Basis/Gateway task; get Basis help for it.**
4. On S/4 2025 the modern path is the **"Migrate Your Data" Fiori app** (Fiori
   Launchpad) — create a migration project there and upload the CSVs the tool
   produced in `local-staging/.../data-migrator/mc/`.

> Honest note: Migration Cockpit is the *proper* bulk-data tool, but its setup
> (Gateway publish + project + object mapping) is real SAP work. Don't block your
> first run on it — use IDoc.

## 1C. Transport door (code/config) — phase 2, needs Basis + OS access
To auto-import the remediated code/config transports:
1. `/nSTMS` → **Systems** → add the laptop ECC as an external system; create a
   transport route ECC → S4H. (Basis task.)
2. Provide OS login (SSH as `<sid>adm`) so the tool's `tp` path can run — set the
   S/4 host's AWS instance id in `connections.json` → `bastion_instance_id`, with
   the SSM agent installed; **or** import the transports by hand in the STMS
   import queue.

> Honest note: until this is set, the pipeline's code/config stages write a
> "manual to-do" manifest instead of importing — by design, not a failure.

---

# PART 2 — Run the full pipeline (laptop)

Open PowerShell (the env vars are saved from `HOW-TO-RUN.md` step 1.2):
```powershell
cd C:\Users\ajays\Downloads\migrate4hanav2
$env:SAPNWRFC_HOME    = "C:\Users\ajays\Downloads\migrate4hanav2\sapnwrfc"
$env:M4H_ECC_PASSWD   = "India123"
$env:M4H_TARGET_PASSWD= "Parupallitejaajay#92"
$env:M4H_TARGET_MODE  = "basis_handover_only"
```

Run the safe portion (phases 0–6, everything except the destructive cutover):
```powershell
python run_local_lift_and_shift.py `
    --from-stage stage1 --through stage21 `
    --run-id RUN-FULL-001 `
    --ecc-host 192.168.0.6 `
    --target-host vhcals4hci.dummy.nodomain
```

Check results:
```powershell
Get-Content local-staging\m4h-local\migrations\RUN-FULL-001\execution\go-live-scorecard.json
python run_local_lift_and_shift.py --only stage27 --run-id RUN-FULL-001   # PDF report
```

The cutover (stages 22–27) locks your ECC — **only run it after you've reviewed
the results and you're satisfied** (see `HOW-TO-RUN.md` §5).

---

# PART 3 — What the result will REALISTICALLY be (read this)

After Part 1A + Part 2, here is the honest outcome:

| Stage area | Result |
|---|---|
| Discovery, sizing, routing | ✅ Completes (live) |
| Code remediation (8,500+ programs) | ✅ Produced on disk (`remediated/`) |
| Data extraction → load templates | ✅ Produced (CSV/IDoc XML) |
| **IDoc data load into S/4** | ⚠️ IDocs deliver; *posting* a complete object also needs full payloads (see below) |
| Code/config transport import | ⏳ Manual to-do unless Part 1C done |
| Migration Cockpit load | ⏳ Manual/Fiori unless Part 1B done |
| Scorecard | Improves, but **not Grade A** in one run |

**Two honest gaps that one run will not close:**
1. **Payload completeness.** The tool currently generates *simplified* IDoc/MC
   content. A real material/customer needs its full mandatory field set. Getting
   clean status-53 posts (objects actually created) requires hardening the tool's
   per-object generation — that's iterative development work, not a config switch.
2. **Per-object config.** Each data object type needs its partner profile (1A) or
   MC object mapping (1B); each is a small SAP task.

**So:** one full run gives you a complete *assessment + remediation + prepared,
partially-delivered* migration on SAP-supported rails — a genuine, demonstrable
accelerator. A fully-posted, Grade-A end-to-end migration of every object is an
**iterative program** (object type by object type), which is true for every SAP
migration tool, commercial ones included. Plan and price around that.

---

# Quick reference — fastest path to "a real object created in S/4"
1. GUI: `BD54` add `M4HSENDER`; `WE20` add inbound `MATMAS`/`MATM`. (Part 1A)
2. Laptop: `python idoc_prove.py` — re-pushes the test IDoc.
3. GUI: `/nWE05` (IDoc list) or `/nBD87` to view/reprocess — status should move
   past 56. (Status 51 = payload incomplete → expected for the minimal test IDoc;
   that's the payload-hardening gap, not a setup error.)
