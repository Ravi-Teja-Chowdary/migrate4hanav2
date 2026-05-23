# HOW TO RUN — Complete End-to-End Pipeline (for non-SAP people)

> This guide assumes **zero SAP knowledge**. Copy-paste each block exactly.
> Every step says (a) what to type, (b) what you should see, (c) what to do if
> it looks wrong. Do the steps **in order**, top to bottom.

---

## 0. The 30-second mental model

You have **two computers** that matter:

| Nickname | What it is | Address | Where it lives |
|---|---|---|---|
| **ECC** | Your *old* SAP system (the source) | `192.168.0.6` | your local network |
| **S/4** | Your *new* SAP system (the target) | name `vhcals4hci.dummy.nodomain` (currently IP `3.231.211.143`) | AWS cloud |

> **Why a name instead of an IP for S/4?** The cloud SAP system always refers to
> itself by the name `vhcals4hci.dummy.nodomain`. Your laptop needs a "phonebook"
> entry mapping that name to the current IP — that's Step 1.0 below. The cloud
> machine's IP **changes every time it reboots**, so if logins start timing out,
> redo Step 1.0 with the new IP.

The tool (**Migrate4HANA**) runs on **this laptop**. It *reads* from ECC and
*writes* into S/4 — but only through official SAP tools, so nothing gets
corrupted. It runs in **28 small steps** ("stages") grouped into **9 phases**.

Two rules that save you pain:
1. **Keep the S/4 cloud machine powered ON** the whole time you run. If it
   sleeps, the run stops. (It went to sleep on us once already.)
2. **Don't run the last phase (CUTOVER) on your first try.** That one locks
   your old ECC system. Do everything up to it first, look at the results,
   then decide.

---

## 1. One-time prep on THIS laptop (5 minutes)

### 1.0 Tell your laptop where the cloud S/4 is (admin — REDO after any S/4 reboot)
The cloud S/4 calls itself `vhcals4hci.dummy.nodomain`. Map that name to its
**current** public IP. **Do this whenever the S/4's IP changes** (it changes on
every cloud reboot).

1. Find the current S/4 public IP (from your cloud console / the "External IP"
   you were given). Right now it is `3.231.211.143`.
2. Open PowerShell **as Administrator**: Start → type `PowerShell` →
   **right-click** → **Run as administrator** → **Yes**.
3. Paste this, replacing the IP if yours is different:
```powershell
$ip="3.231.211.143"; $h="$env:windir\System32\drivers\etc\hosts"
$body = (Get-Content $h | Where-Object { $_ -notmatch 'vhcals4hc' }) -join "`r`n"
$body += "`r`n$ip`tvhcals4hci.dummy.nodomain`r`n$ip`tvhcals4hcs.dummy.nodomain`r`n"
Set-Content $h $body -NoNewline
Get-Content $h | Select-String vhcals4hc
```
You should see the two lines printed with the **current** IP. Done — close the
admin window; you don't need admin again.

### 1.1 Open PowerShell in the project folder
Press Start → type `PowerShell` → Enter. Then paste:
```powershell
cd C:\Users\ajays\Downloads\migrate4hanav2
```

### 1.2 Set the secret values (passwords + paths)
Paste this **whole block** once. It saves the settings so every future
PowerShell window already has them — you won't need to do this again.
```powershell
[Environment]::SetEnvironmentVariable("M4H_ECC_PASSWD","India123","User")
[Environment]::SetEnvironmentVariable("M4H_TARGET_PASSWD","Parupallitejaajay#92","User")
[Environment]::SetEnvironmentVariable("M4H_HANA_PASSWD","Parupallitejaajay#92","User")
[Environment]::SetEnvironmentVariable("M4H_TARGET_MODE","basis_handover_only","User")
[Environment]::SetEnvironmentVariable("SAPNWRFC_HOME","C:\Users\ajays\Downloads\migrate4hanav2\sapnwrfc","User")
"Saved. Now CLOSE this PowerShell window and open a NEW one."
```
**Important:** close this window and open a **new** PowerShell after running it,
so the new settings take effect. Then `cd` back into the folder again:
```powershell
cd C:\Users\ajays\Downloads\migrate4hanav2
```

### 1.3 Check both SAP systems answer
```powershell
Test-NetConnection 192.168.0.6 -Port 3241    # ECC  — want TcpTestSucceeded : True
Test-NetConnection 3.231.211.143 -Port 3300    # S/4  — want TcpTestSucceeded : True
```
- **Both say `True`** → great, continue.
- **ECC says False** → your old SAP machine is off or unplugged from the network. Turn it on.
- **S/4 says False** → the AWS cloud machine is asleep. Wake it (start the EC2 instance / resume the appliance), wait ~5 min, try again.

### 1.4 Prove the tool can actually log in to both
```powershell
python -c "from pyrfc import Connection; import os; c=Connection(ashost='192.168.0.6',sysnr='41',client='800',user='sapuser',passwd=os.environ['M4H_ECC_PASSWD']); print('ECC login OK'); c.close()"
python -c "from pyrfc import Connection; import os; c=Connection(ashost='vhcals4hci.dummy.nodomain',sysnr='00',client='100',user='SAP*',passwd=os.environ['M4H_TARGET_PASSWD']); print('S4 login OK'); c.close()"
```
- **Both print `... OK`** → you are fully ready. Skip to Section 3.
- **`S4 login OK` does NOT appear** (says "name or password is incorrect" or
  "user is locked") → see Section 2 — the S/4 login needs a small fix.

---

## 2. One-time prep on S/4 — ONLY if Section 1.4 failed for S/4

You only need this if the **S/4 login test failed**. Skip otherwise.

The user `SAP*` is often locked on a fresh system. Easiest fixes, in order of
preference:

**Option A — use a different login that already works.** Many S/4 systems ship
with `DDIC` or `BPINST` enabled using the same master password. Try:
```powershell
python -c "from pyrfc import Connection; import os; c=Connection(ashost='vhcals4hci.dummy.nodomain',sysnr='00',client='100',user='DDIC',passwd=os.environ['M4H_TARGET_PASSWD']); print('DDIC login OK'); c.close()"
```
If `DDIC login OK` appears, tell me and I'll switch the config from `SAP*` to
`DDIC` (one line in `connections.json`).

**Option B — unlock `SAP*`.** This needs someone to log into the S/4 system's
graphical screen (SAP GUI) once and run transaction `SU01` → user `SAP*` →
Unlock. If you have the **Windows Remote Desktop** machine (`3.237.83.66`), SAP
GUI is usually installed there. If this sounds unfamiliar, just use Option A.

---

## 3. The single most important command

This runs the **safe portion** of the pipeline — everything **except** the
destructive last phase. It reads your ECC, fixes the custom code, extracts the
data, loads what it can into S/4, reconciles, and produces a scorecard.

Paste this whole block:
```powershell
cd C:\Users\ajays\Downloads\migrate4hanav2
$env:SAPNWRFC_HOME    = "C:\Users\ajays\Downloads\migrate4hanav2\sapnwrfc"
$env:M4H_ECC_PASSWD   = "India123"
$env:M4H_TARGET_PASSWD= "Parupallitejaajay#92"
$env:M4H_TARGET_MODE  = "basis_handover_only"
python run_local_lift_and_shift.py `
    --from-stage stage1 --through stage21 `
    --run-id RUN-LIVE-001 `
    --ecc-host 192.168.0.6 `
    --target-host vhcals4hci.dummy.nodomain
```

That's stages **1 → 21** (Phases 0 through 6). It deliberately STOPS before the
cutover. A small ECC has this finish in roughly 30–60 minutes.

### What you'll see scroll past
Lines like `[stage6] code-analyzer.handler` then `status=success`. That's normal.

### When it pauses and asks you something ("manual gate")
Some SAP actions can't be done automatically and must be clicked by a human in
SAP GUI. When the tool hits one it prints a clear instruction and, in local
mode, **auto-approves and keeps going** so your first run isn't blocked. You do
**not** have to do anything — just let it continue. It also saves a file
describing the manual step (a "manifest") so you can action it properly later.

### If a stage says `status=failed` or `manual_required`
- `manual_required` = **not an error.** It means "a human needs to finish this
  in SAP GUI." The run continues. Fine for a first pass.
- `status=failed` and the run **stops** = something real broke. Copy the last
  ~20 lines and send them to me. The usual cause is the S/4 machine going to
  sleep mid-run (re-check Section 1.3).

---

## 4. Look at your results

After Section 3 finishes, see the scorecard and report:
```powershell
# The GO-LIVE scorecard (grade A best, D worst):
Get-Content local-staging\m4h-local\migrations\RUN-LIVE-001\execution\go-live-scorecard.json

# Everything produced this run:
Get-ChildItem local-staging\m4h-local\runs\RUN-LIVE-001 -Recurse -File | Select-Object FullName
Get-ChildItem local-staging\m4h-local\migrations\RUN-LIVE-001 -Recurse -File | Select-Object FullName
```
Key things to look for:
- `code-analysis\remediated\*.abap` — your custom programs, auto-fixed for S/4.
- `data-migrator\mc\*.csv` and `...\idoc\*.xml` — your data, packaged for loading.
- `execution\go-live-scorecard.json` — the overall grade.

Want a single PDF summarising it all? Run the report stage:
```powershell
python run_local_lift_and_shift.py --only stage27 --run-id RUN-LIVE-001
Get-Content local-staging\m4h-local\runs\RUN-LIVE-001\report\report_input.json | Select-Object -First 5
```
The PDF lands at `local-staging\m4h-local\runs\RUN-LIVE-001\report\migration-report.pdf`.

---

## 5. The final phase — CUTOVER (do this ONLY when you're ready)

> ⚠️ **Read this before running.** The cutover phase (stages 22–26) will set
> your **old ECC system to read-only** ("locked"). After that, nobody can post
> new transactions in ECC — the new S/4 becomes the system of record. This is
> the real go-live switch. Do NOT run it on day one. Run it only after you've
> reviewed the Section 4 results and you're satisfied.

When you're ready:
```powershell
cd C:\Users\ajays\Downloads\migrate4hanav2
$env:SAPNWRFC_HOME    = "C:\Users\ajays\Downloads\migrate4hanav2\sapnwrfc"
$env:M4H_ECC_PASSWD   = "India123"
$env:M4H_TARGET_PASSWD= "Parupallitejaajay#92"
$env:M4H_TARGET_MODE  = "basis_handover_only"
python run_local_lift_and_shift.py `
    --from-stage stage22 --through stage27 `
    --run-id RUN-LIVE-001 `
    --ecc-host 192.168.0.6 `
    --target-host vhcals4hci.dummy.nodomain
```

### If you change your mind after locking ECC (undo)
```powershell
python -c "from importlib import import_module; m=import_module('rollback-manager.handler'.replace('-','_')); print(m.lambda_handler({'run_id':'RUN-LIVE-001','action':'switch_back'},None))"
```
This unlocks ECC again. (It does **not** erase anything already written into
S/4 — that's a separate cleanup if needed.)

---

## 6. The few SAP-side things that make stages fully automatic (optional)

For your **first run you can ignore this whole section** — those stages will
just produce "manual_required" manifests and the run continues. Action these
later, with help, to make the transport/load stages run hands-free:

| What | Why | Who does it |
|---|---|---|
| Activate Migration Cockpit OData service `CA_DATA_MIGRATION_SRV` on S/4 (txn `/IWFND/MAINT_SERVICE`) | lets stage 16 load data automatically | a Basis person, once |
| Create IDoc partner `M4H_LAPTOP_ECC` on S/4 (txn `WE20`) | lets stage 18 post interface data | a Basis person, once |
| Fill `bastion_instance_id` in `connections.json` with the S/4 server's AWS instance ID | lets the tool build & import transports automatically instead of writing a manual to-do | you (copy the EC2 instance id from AWS console) |
| STMS transport route ECC → S/4 (txn `STMS`) | lets stage 9b import code automatically | a Basis person, once |

None of these block a first end-to-end run — they only upgrade specific stages
from "writes a to-do file" to "does it for you."

---

## 7. Cheat-sheet (everything in one place)

```powershell
# --- always start a session like this ---
cd C:\Users\ajays\Downloads\migrate4hanav2
$env:SAPNWRFC_HOME    = "C:\Users\ajays\Downloads\migrate4hanav2\sapnwrfc"
$env:M4H_ECC_PASSWD   = "India123"
$env:M4H_TARGET_PASSWD= "Parupallitejaajay#92"
$env:M4H_TARGET_MODE  = "basis_handover_only"

# health check
Test-NetConnection 192.168.0.6 -Port 3241
Test-NetConnection 3.231.211.143 -Port 3300

# the safe run (phases 0-6)
python run_local_lift_and_shift.py --from-stage stage1 --through stage21 --run-id RUN-LIVE-001 --ecc-host 192.168.0.6 --target-host vhcals4hci.dummy.nodomain

# results
Get-Content local-staging\m4h-local\migrations\RUN-LIVE-001\execution\go-live-scorecard.json

# the go-live cutover (only when ready)
python run_local_lift_and_shift.py --from-stage stage22 --through stage27 --run-id RUN-LIVE-001 --ecc-host 192.168.0.6 --target-host vhcals4hci.dummy.nodomain
```

If anything says `failed` and stops, copy the last 20 lines of output and send
them over — that's almost always the S/4 machine napping or a single SAP
setting from Section 6.
