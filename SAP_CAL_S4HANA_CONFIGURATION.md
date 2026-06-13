# SAP CAL S/4HANA + ECC — Unrestricted-Access Configuration Runbook

> **Purpose:** Give Migrate4HANA **unconditional, unrestricted, gate-free access** to BOTH systems
> (laptop ECC + AWS CAL S/4HANA) so the tool can be developed and run in **full automated mode**
> with zero authorization friction, zero password prompts, zero network blocks, zero "service not
> active" 404s, zero "no partner profile" 56s, zero "client not modifiable" rejects, zero forced
> password changes, zero session timeouts, zero audit-log throttling.
>
> **Scope:** Your own private dev/test appliance + your own laptop ECC VM. **Not for production.**
> This runbook deliberately removes safety nets that real customers would keep.
>
> **Follow top-to-bottom every time you spin up a fresh appliance.** ~90 min on a clean CAL deploy.
>
> **Last validated:** 2026-06-13.

---

## 0. The principle — "no gate, no friction"

Every SAP component has gates. To go from "tool authenticates but fails on every write" to
"tool does whatever it wants," we knock down all of them, on **both** systems:

| Gate | Where it lives | Our kill-switch |
|---|---|---|
| Authorization | User profiles/roles | `SAP_ALL` + `SAP_NEW` + `S_DEVELOP` on service users |
| Password rules | Profile parameters | `login/password_max_idle_*=0`, `login/min_password_lng=1` |
| Forced password change | User type Dialog/A | Set user type to **Service (S)** — never forced |
| Client-modifiable | SCC4 | Changes & cross-client allowed |
| HTTPS endpoints inactive | SICF | Bulk-activate all `/sap/bc/*` we need |
| OData services unpublished | /IWFND/MAINT_SERVICE | Bulk-add MC + Gateway services |
| IDocs land but don't post | WE20 / BD54 | Partner profile w/ ALL message types |
| Multi-logon block | login/disable_multi_gui_login | Set to `0` (allow) |
| Failed-logon lockout | login/fails_to_user_lock | Set to `99` |
| Security audit throttling | SM19 | Disabled |
| Session timeout | rdisp/max_wprun_time | `0` (no timeout) |
| OS firewall | iptables/firewalld | Stopped + disabled |
| AWS Security Group | EC2 SG inbound | Wide-open to YOUR public IP |
| Transport `tp` gate | STMS / TP_DOMAIN | Configured + open |
| SSH gate to host | sshd | Open with key auth |
| HANA SQL gate | xs.cfg / hdbuserstore | SAPHANADB password set, port `32202` open |

We close all 16. Then nothing in either system can say "no" to Migrate4HANA.

---

## PART A — Initial deployment (per fresh CAL appliance)

### A.1 Deploy SAP CAL S/4HANA Fully-Activated Appliance
1. **https://cal.sap.com** → log in → **Solutions** → search **SAP S/4HANA 2023 FPS01, Fully-Activated Appliance** → **Create Appliance**.
2. CAL prompts:
   - **AWS account / region:** your AWS account + region.
   - **Instance size:** default (`m5.4xlarge` / `m5.8xlarge`).
   - **Master password:** **`Parupallitejaajay#92`** ⬅ **MUST be this exact value** (everything downstream assumes it).
     Sets the password for `DDIC`, `SAP*`, `BPINST`, `S4ADMIN`, `S4HADM`, `SAPADM`, `root`.
   - **Time-zone / network:** defaults.
3. Wait **60–90 min** until status = **Active**.
4. Note from the **Connect** tab:
   - **Public IP** (drifts on every Suspend/Activate)
   - **EC2 Instance ID** (stable across restarts, e.g. `i-0dea60b2c9e82b680`)
   - **Private IP** (for `connections.json` → `target_internal_ip`)

### A.2 (Optional but recommended) Allocate an Elastic IP to stop drift forever
```powershell
$instanceId = "<INSTANCE-ID>"
$eip = (aws ec2 allocate-address --domain vpc --query "{Alloc:AllocationId,IP:PublicIp}" --output json | ConvertFrom-Json)
aws ec2 associate-address --instance-id $instanceId --allocation-id $eip.Alloc
$eip.IP   # this IP is now permanent for this trial
```
After this, you only update the hosts file ONCE per appliance, not per restart.

### A.3 Repoint Windows hosts file → S/4 hostname
PowerShell **as Administrator**:
```powershell
$ip="<S4-PUBLIC-IP-OR-EIP>"; $h="$env:windir\System32\drivers\etc\hosts"
$body = (Get-Content $h | Where-Object { $_ -notmatch 'vhcals4hc' }) -join "`r`n"
$body += "`r`n$ip`tvhcals4hci.dummy.nodomain`r`n$ip`tvhcals4hcs.dummy.nodomain`r`n"
Set-Content $h $body -NoNewline
Get-Content $h | Select-String vhcals4hc
```
**Always connect by hostname** (`vhcals4hci.dummy.nodomain`), never by raw IP — the gateway re-resolves
the hostname during work-process allocate, so raw-IP connects still need this entry.

---

## PART B — ECC side: unrestricted access (Windows VM)

Source: laptop ECC VM running **Windows Server** (Ameerpet-style install), IP `192.168.100.129`,
sysnr `41`, client `800`. SID typically `NPL` (or `ABA` for IDES CAL).

> **All ECC-side commands below are Windows-native** (PowerShell / `cmd` / SAP MMC).
> Run them **inside the Windows VM**, logged in as the local Administrator account.

### B.1 Boot the VM + start SAP

#### B.1.1 Power-on the VM
VMware Workstation / Player → power on the `ECC` VM → wait for the Windows login prompt →
log in as **Administrator** (or whichever local Windows account was used to install SAP).

#### B.1.2 Start the SAP services
Two equivalent paths — pick whichever is easier.

**Path A — SAP Management Console (recommended, visual)**
1. Start Menu → **SAP Management Console** (`sapmmc.msc`).
2. Tree → `<your-host>` → `NPL` (or whatever SID) → right-click the instance
   (e.g. `41 — DVEBMGS41`) → **Start**.
3. Wait for the traffic-light icons to all turn **green** — `MessageServer`, `Dispatcher`,
   `IGS`, and the `Gateway` must all be green. Takes 2–5 minutes.

**Path B — Windows Services (faster, scriptable)**
Open PowerShell **as Administrator** inside the VM:
```powershell
# Replace NPL with your actual SID if different
Get-Service -Name "SAP*" | Format-Table Name,Status,StartType
Start-Service -Name "SAPNPL_41"          # the main ABAP instance
Start-Service -Name "SAPHostControl"     # host agent
Start-Service -Name "SAPHostExec"        # host executor
Start-Service -Name "SAPOSCol"           # OS collector (optional)
```

#### B.1.3 Verify SAP is listening
In the VM, PowerShell:
```powershell
# RFC gateway + dispatcher + message server ports (sysnr 41 → 3341/3241/3641)
netstat -ano | findstr /R /C:"32[0-9][0-9] " /C:"33[0-9][0-9] " /C:"36[0-9][0-9] "
# expect lines with 0.0.0.0:3341, 0.0.0.0:3241, 0.0.0.0:3641 LISTENING
```
Or via SAP MMC: every node under the instance should be **green**.

### B.2 **Kill the Windows Firewall inside the ECC VM** (permanent)

Open PowerShell **as Administrator** inside the VM and turn off all three profiles:
```powershell
# Disable Windows Defender Firewall for Domain, Private, Public profiles
netsh advfirewall set allprofiles state off

# Verify — all three should say "State OFF"
netsh advfirewall show allprofiles | findstr /I "Profile State"

# (Belt-and-braces) ensure the firewall service won't auto-restart it
Set-Service -Name MpsSvc -StartupType Manual
# Note: MpsSvc can't be fully disabled on modern Windows, but Manual + state=off is enough
```

If you prefer the GUI: **Control Panel → Windows Defender Firewall → Turn Windows Defender Firewall on or off** → choose **Turn off** for all three network locations → OK.

> If a corporate antivirus (McAfee, Symantec, ESET, Defender ATP) is also installed, **add an
> exception for ports `3200-3699` and `8000-9999`** or temporarily disable real-time protection
> while developing. Antivirus is the silent killer for RFC throughput.

### B.3 VMware network — Bridged mode + verify the IP

1. VMware Workstation / Player → ECC VM → **Settings** → **Network Adapter** →
   select **Bridged: Connected directly to the physical network** → tick **Replicate physical
   network connection state** → OK.
2. Inside the Windows VM, PowerShell:
```powershell
ipconfig | findstr /I "IPv4"
# expect: IPv4 Address. . . . . . . . . . . : 192.168.100.x
```
3. From the **laptop host** (outside the VM):
```powershell
ping 192.168.100.129
# expect: 4 replies, no timeouts
Test-NetConnection 192.168.100.129 -Port 3341    # SAP dispatcher (sysnr 41)
# expect: TcpTestSucceeded : True
```

> **If the IP drifted** (DHCP gave the VM a different address after reboot): just refresh
> `connections.json` → `ecc.ashost` with the new value from `ipconfig`. Or set a **DHCP
> reservation** on your home router for the VM's MAC to pin the IP permanently.

### B.4 First SAP GUI login to ECC
- **App server:** `192.168.100.129` (or whatever ECC `ipconfig` shows)
- **Instance:** `41`
- **Client:** `800`
- **User:** `sapuser`
- **Password:** `India123` (your `M4H_ECC_PASSWD`)

### B.5 **Create `M4H_ECC_ADMIN` — Service-type god user**

```
SAP GUI → /nSU01
```
1. **User:** `M4H_ECC_ADMIN` → **Create**.
2. **Address** tab → Last name: `Migration`.
3. **Logon Data** tab:
   - **User Type:** **Service (S)** ← critical: NOT Dialog, NOT System
   - **Password:** `India123` (same as `M4H_ECC_PASSWD`)
   - **Valid From:** today, **Valid Through:** `31.12.9999`
4. **Profiles** tab → add `SAP_ALL` and `SAP_NEW` → Enter.
5. **Save** (💾).

Or do it over RFC instantly (no GUI clicks):
```powershell
$env:SAPNWRFC_HOME = "C:\Users\ajays\Downloads\migrate4hanav2\sapnwrfc"
python -c @"
import os
from pyrfc import Connection
c = Connection(ashost='192.168.100.129', sysnr='41', client='800',
               user='sapuser', passwd=os.environ['M4H_ECC_PASSWD'], lang='EN')
# Create or refresh the service user with SAP_ALL + SAP_NEW
c.call('BAPI_USER_CREATE1',
       USERNAME='M4H_ECC_ADMIN',
       LOGONDATA={'USTYP':'S'},
       PASSWORD={'BAPIPWD':'India123'},
       ADDRESS={'LASTNAME':'Migration'},
       PROFILES=[{'BAPIPROF':'SAP_ALL'},{'BAPIPROF':'SAP_NEW'}])
c.call('BAPI_TRANSACTION_COMMIT', WAIT='X')
print('M4H_ECC_ADMIN created with SAP_ALL+SAP_NEW')
c.close()
"@
```

> If user already exists, swap `BAPI_USER_CREATE1` → `BAPI_USER_CHANGE` and add a `BAPI_USER_PROFILES_ASSIGN` call.

### B.6 **Open ECC client 800 for changes — `SCC4`**
1. SAP GUI → **`/nSCC4`** → ✏️ (change mode) → double-click client `800`.
2. **Changes and Transports for Client-Specific Objects:** `Changes without automatic recording`
3. **Cross-Client Object Changes:** `Changes to Repository and cross-client Customizing allowed`
4. **Protection: Client Copier and Comparison Tool:** `Protection level 0: No restriction`
5. **Restrictions when Starting CATTs and eCATTs:** `eCATT and CATT allowed`
6. Save → Local Object (`$TMP`).

### B.7 **Disable password policy + lockout — ECC profile parameters (`RZ10`)**

This makes the tool immune to password expiry / lockout / complexity:
```
SAP GUI → /nRZ10 → Profile: DEFAULT.PFL → Extended maintenance → Change
```
Add (or set) these parameters:
```
login/min_password_lng            = 1
login/password_expiration_time    = 0
login/password_max_idle_initial   = 0
login/password_max_idle_productive = 0
login/fails_to_session_end        = 99
login/fails_to_user_lock          = 99
login/disable_multi_gui_login     = 0
login/no_automatic_user_sapstar   = 0
rdisp/max_wprun_time              = 0
icm/host_name_full                = vhcalnplci
```
**Copy** → **Save** → next ECC restart picks them up. For an immediate effect on the running instance use **`/nRZ11`** → look up each parameter → change in-memory value.

### B.8 **Disable security audit log — `SM19`**
```
SAP GUI → /nSM19 → Filter 1 → Detail Configuration → Filter Active = ❌ → Save
```
Then `SM20` → confirm no audit profile is active.

### B.9 **Open all SICF services on ECC** (one-shot)
```
SAP GUI → /nSICF → execute (F8) with default filter
```
Right-click `default_host` → **Activate Service** → choose **Activate (recursive)** when prompted.
Yes-to-all. This activates every `/sap/bc/*` endpoint in one go.

If `Activate (recursive)` is grey, do these individually (the minimum Migrate4HANA needs):
- `default_host/sap/bc/idoc_xml`
- `default_host/sap/bc/srt/rfc/sap/*` (web service RFC)
- `default_host/sap/bc/soap/rfc`
- `default_host/sap/bc/webdynpro/sap/*`
- `default_host/sap/bc/ping`
- `default_host/sap/public/info`

### B.10 **Set ECC logical system + enable IDoc outbound — `BD54` + `WE21`**
1. `/nBD54` → New Entries → `M4H_LAPTOP_ECC` LS / "Migrate4HANA ECC source" → Save → `$TMP`.
2. `/nSCC4` → confirm client `800` LOGSYS = `M4H_LAPTOP_ECC` (or set via `BD54` → assign in `SALE` if blank).
3. `/nWE21` → Port → **Transactional RFC** → Create → Port `M4HS4HTRFC`, RFC destination `M4H_S4H` (we'll create next).

### B.11 **Trust S/4 from ECC — `SM59`** (creates RFC destination ECC → S/4)
1. `/nSM59` → expand **R/3 connections** → **Create**.
2. RFC destination: `M4H_S4H`
3. Connection type: `3` (ABAP connection)
4. **Technical Settings:**
   - Target Host: `vhcals4hci.dummy.nodomain`
   - Instance Number: `00`
5. **Logon & Security:**
   - Client: `100`
   - User: `MIGRATE_ADMI`
   - Password: `Parupalliajayteja@2020`
   - Lang: `EN`
6. **Connection Test** → success required. **Authorization Test** → success required.
7. Save.

(Symmetrical RFC destination S/4 → ECC is created in **PART C** below.)

---

## PART C — S/4HANA side: unrestricted access

### C.1 First login (use SAP GUI on Windows RDP box `3.237.83.66` or local SAP GUI)
- **App server:** `vhcals4hci.dummy.nodomain`
- **Instance:** `00`, **Client:** `100`
- **User:** `SAP*`, **Password:** `Parupallitejaajay#92`

### C.2 **Unlock all standard admins** (one shot, RFC, no GUI clicks)
```powershell
cd C:\Users\ajays\Downloads\migrate4hanav2
$env:SAPNWRFC_HOME = "$PWD\sapnwrfc"
$env:M4H_TARGET_PASSWD = "Parupalliajayteja@2020"
python recover_access.py
```
Output expected: `unlocked` for `SAP*`, `MIGRATE_ADMI`, `DDIC`.

### C.3 **Repair / create `MIGRATE_ADMI` as a Service user with SAP_ALL**
```powershell
python fix_migrate_admin.py --admin-pass "Parupallitejaajay#92"
python mc_role_probe.py --sap-all
```
Result: `MIGRATE_ADMI` is `USTYP='S'`, password = `Parupalliajayteja@2020`, profiles include `SAP_ALL` + `SAP_NEW`.

### C.4 **Open client 100 for changes — `SCC4`**
```
SAP GUI → /nSCC4 → ✏️ → double-click client 100
```
- **Changes and Transports for Client-Specific Objects:** `Changes without automatic recording`
- **Cross-Client Object Changes:** `Changes to Repository and cross-client Customizing allowed`
- **Client Role:** `Customizing` (or `Test` — either is unrestricted)
- **Protection: Client Copier and Comparison Tool:** `Protection level 0: No restriction`
- **Restrictions when Starting CATTs and eCATTs:** `eCATT and CATT allowed`
- **CATT and eCATT Restrictions:** `No Restrictions`
- Save → Local Object.

### C.5 **Disable password policy + lockout on S/4 — `RZ10` / `RZ11`**
Same parameters as B.7, in **DEFAULT.PFL** of the S/4 system. For an immediate (no-restart) effect use `RZ11`:
```
SAP GUI → /nRZ11
```
For each parameter, change current value:
```
login/min_password_lng            = 1
login/password_expiration_time    = 0
login/password_max_idle_initial   = 0
login/password_max_idle_productive = 0
login/fails_to_session_end        = 99
login/fails_to_user_lock          = 99
login/disable_multi_gui_login     = 0
login/no_automatic_user_sapstar   = 0
rdisp/max_wprun_time              = 0
icf/user_recheck                  = 0
```
Persist by also updating DEFAULT.PFL via `RZ10`.

### C.6 **Disable security audit on S/4 — `SM19`**
Same as B.8 — deactivate all filters.

### C.7 **Bulk-activate ALL SICF services Migrate4HANA needs**

```
SAP GUI → /nSICF → execute (F8)
```
Right-click **`default_host`** → **Activate Service** → confirm "with sub-elements" → Yes-to-all.

If that's blocked, activate this **minimum set** individually (right-click each → Activate):

| Path | Purpose |
|---|---|
| `/sap/bc/idoc_xml` | IDoc HTTP inbound |
| `/sap/bc/srt/rfc/sap/*` | Web Service RFC |
| `/sap/bc/soap/rfc` | SOAP RFC |
| `/sap/opu/odata/sap/CA_DATA_MIGRATION_SRV` | Migration Cockpit OData |
| `/sap/opu/odata/sap/CA_DATA_MIGRATION_OBJECT_SRV` | MC objects metadata |
| `/sap/opu/odata/sap/API_BUSINESS_PARTNER` | Business Partner OData write |
| `/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV` | Material doc OData |
| `/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV` | PO OData |
| `/sap/opu/odata/sap/API_SALES_ORDER_SRV` | Sales order OData |
| `/sap/bc/ui2/flp` | Fiori Launchpad ("Migrate Your Data" app) |
| `/sap/bc/adt` | ADT (ABAP Development Tools) |
| `/sap/bc/srt/scs/sap/*` | SOAP runtime |
| `/sap/public/*` | Public services (no auth required) |
| `/sap/bc/gui/sap/its/webgui` | SAP GUI for HTML |
| `/sap/bc/webdynpro/sap/*` | WebDynpro apps |
| `/sap/bc/bsp/sap/*` | BSP apps |
| `/sap/bc/ping` | Heartbeat |

### C.8 **Bulk-add ALL Gateway services — `/IWFND/MAINT_SERVICE`**
1. `/n/IWFND/MAINT_SERVICE` → **Add Service**.
2. **System Alias:** `LOCAL` → **Technical Service Name:** wildcards below → search → select all → **Add Selected Services** → Package `$TMP` → Save.

Add these (search one at a time, then Add Selected):
| Search pattern | Catches |
|---|---|
| `*DATA_MIGRATION*` | `CA_DATA_MIGRATION_SRV`, `CA_DATA_MIGRATION_OBJECT_SRV` |
| `*BUSINESS_PARTNER*` | `API_BUSINESS_PARTNER` |
| `*MATERIAL*` | Material APIs |
| `*PURCHASE_ORDER*` | PO APIs |
| `*SALES_ORDER*` | Sales-order APIs |
| `*COSTCENTER*` | Cost-center APIs |
| `*FIXEDASSET*` | Asset APIs |

Verify:
```powershell
python writepath_probe.py
# expect: "migration cockpit (OData): READY — published & authorized (200)"
```

### C.9 **IDoc partner profile for ALL message types — `BD54` + `WE20`**

#### C.9.1 Define both logical systems
```
SAP GUI → /nBD54 → New Entries
```
Add:
| Log. System | Name |
|---|---|
| `M4HSENDER` | Migrate4HANA generic sender |
| `M4H_LAPTOP_ECC` | Migrate4HANA ECC source |
| `S4HCLNT100` | This S/4 client (target — usually already exists) |

Save → `$TMP`.

#### C.9.2 Create the inbound partner profile — `WE20`
1. `/nWE20` → tree → **Partner Type LS** → Create.
2. **Partner No.:** `M4H_LAPTOP_ECC`, **Partn. Type:** `LS` → Save.
3. **Post Processing: Permitted Agent** tab: set user to `MIGRATE_ADMI` (User class = `US`).
4. **Inbound parameters** box → **+** → add every row below (Trigger Immediately, Save after each):

| Message Type | Process Code | What it carries |
|---|---|---|
| `MATMAS` | `MATM` | Material master |
| `DEBMAS` | `DEBM` | Customer master |
| `CREMAS` | `CREM` | Vendor master |
| `COND_A` | `COND` | Pricing conditions |
| `EXCHANGE_RATE` | `EXCHANGE_RATE_IDOC_INBOUND` | Currency rates |
| `GLMAST` | `GLMA` | G/L master |
| `BANK_CREATE` | `BANK` | Bank master |
| `CLFMAS` | `CLFM` | Classification |
| `CHRMAS` | `CHRM` | Characteristics |
| `BUS3001` | `BBP3` | Purchase requisition |
| `ORDERS` | `ORDE` | Sales orders |
| `INVOIC` | `INVL` | Incoming invoices |
| `DELVRY` | `DELI` | Deliveries |
| `PROACT` | `PROA` | Profit center master |
| `COSMAS` | `COSM` | Cost center master |
| `ACTMAS` | `ACTM` | Activity type master |
| `INTERNALORDER` | `KO01` | Internal orders |

5. Repeat the create with **Partner No.** = `M4HSENDER` (so both sender names work).

### C.10 **Trust ECC from S/4 — `SM59`** (RFC destination S/4 → ECC)
1. `/nSM59` → **R/3 connections** → **Create**.
2. RFC destination: `M4H_ECC`
3. Connection type: `3`
4. **Technical Settings:**
   - Target Host: `192.168.100.129` (ECC IP — won't be reachable from cloud S/4 unless you tunnel; usually NOT needed because tool pulls from ECC and pushes to S/4)
   - Instance: `41`
5. **Logon & Security:** Client `800`, User `M4H_ECC_ADMIN`, Password `India123`.
6. Skip "Connection Test" if no tunnel — the destination is metadata only; the tool runs RFC from the laptop, not from the cloud S/4.

### C.11 **STMS / `tp` — verify on the S/4 host (SSH)**
```bash
# SSH as root @ <s4-public-ip>
ls -l /usr/sap/trans/bin/TP_DOMAIN_S4H.PFL
su - s4hadm -c 'tp connect S4H pf=/usr/sap/trans/bin/TP_DOMAIN_S4H.PFL'
# both should succeed cleanly
```
If `.PFL` is missing: `/nSTMS` in GUI → accept "Configure as single-system transport domain" → Save.

### C.12 **HANA SQL access wide-open**
1. SSH as root → switch to `s4hadm`:
```bash
sudo -i -u s4hadm
hdbsql -i 02 -u SYSTEM -p Parupalliajayteja@2020 -d SystemDB <<'EOF'
ALTER USER SAPHANADB DISABLE PASSWORD LIFETIME;
ALTER USER SAPHANADB DISABLE PASSWORD CHECK;
ALTER USER SAPHANADB CLEAR FAILED LOGIN ATTEMPTS;
EOF
```
2. Confirm port `32202` open externally (B.13 already opens it via SG).

### C.13 **Disable application log throttling — `SLG2` cleanup, retention `0`**
Long runs filled the log → throttling. Disable by setting all application-log retention to 0 days (per object) or wipe old logs:
```
SAP GUI → /nSLG2 → execute with date < today → Delete
```

### C.14 **Increase work-process tolerance — `RZ04` (optional, for parallel loads)**
```
SAP GUI → /nRZ04 → Operation Mode → confirm Day mode has enough Dialog (DIA) + Background (BTC) processes (default ~10 each is fine; raise if needed).
```

---

## PART D — Network: kill every firewall in the path

### D.1 **Open ALL relevant ports on the S/4 EC2 Security Group**

From the laptop (use **your** public IP — find via `curl ifconfig.me`):
```powershell
$instanceId = "<INSTANCE-ID>"
$myIp = (Invoke-RestMethod -Uri "https://ifconfig.me/ip").Trim() + "/32"
$sgId = (aws ec2 describe-instances --instance-ids $instanceId `
        --query "Reservations[].Instances[].SecurityGroups[].GroupId" --output text)

# RFC + Dispatcher + Gateway + HTTP + HTTPS + SSH + HANA SQL
$ports = @(22, 1128, 1129, 3200, 3300, 3600, 8000, 8001, 8100, 44300, 50013, 50014, 32200, 32201, 32202, 32215, 32269)
foreach ($p in $ports) {
  aws ec2 authorize-security-group-ingress --group-id $sgId `
    --protocol tcp --port $p --cidr $myIp 2>$null
}
# Confirm:
aws ec2 describe-security-groups --group-ids $sgId `
  --query "SecurityGroups[].IpPermissions[].{Port:FromPort,Cidr:IpRanges[0].CidrIp}" --output table
```

> **Even more permissive** (if your home IP rotates and you don't want to keep updating): replace
> `$myIp` with `0.0.0.0/0` to open to the whole internet. Risky for a dev appliance with `SAP_ALL`
> credentials in code, so only do this if you must. Better — keep `/32` and re-run when your IP changes.

### D.2 Port reference (what dies if you close each)

| Port | Purpose | Loses if closed |
|---|---|---|
| `22` | SSH | Transport `tp`, host SSM access |
| `1128 / 1129` | HANA system replication / start service | HANA admin |
| `3200` | SAP Dispatcher | SAP GUI login |
| `3300` | SAP Gateway (RFC) | **All BAPI / RFC writes** |
| `3600` | Message Server | Group-logon, some discovery |
| `8000 / 8001 / 8100` | ICM HTTP | Fallback HTTP RFC, ADT |
| `44300` | ICM HTTPS | **IDoc inbound + Migration Cockpit OData + Fiori** |
| `50013 / 50014` | HostAgent / SAPControl | Basis ops |
| `32200 / 32201 / 32202` | HANA SQL (sysnr 02) | Direct HANA reads |
| `32215` | HANA system port | HANA admin |
| `32269` | HANA system port | HANA admin |

### D.3 **Kill the OS firewall on the S/4 host too** (belt-and-braces)
SSH as root:
```bash
systemctl stop SuSEfirewall2 2>/dev/null
systemctl disable SuSEfirewall2 2>/dev/null
systemctl stop firewalld 2>/dev/null
systemctl disable firewalld 2>/dev/null
iptables -F; iptables -X; iptables -P INPUT ACCEPT
```

### D.4 **Windows Defender Firewall — allow Python / pyrfc outbound**
Usually not blocking (outbound is permitted by default), but for safety:
```powershell
New-NetFirewallRule -DisplayName "Migrate4HANA python outbound" -Direction Outbound `
  -Program "C:\Users\ajays\AppData\Local\Programs\Python\Python311\python.exe" -Action Allow
```
Adjust the path to your actual Python.

---

## PART E — AWS infrastructure (transport door + S3 staging)

### E.1 Capture stable infra IDs
```powershell
aws ec2 describe-instances --filters "Name=instance-state-name,Values=running" `
  --query "Reservations[].Instances[].{ID:InstanceId,IP:PublicIpAddress,SG:SecurityGroups[0].GroupId,SUB:SubnetId,Name:Tags[?Key=='Name']|[0].Value}" --output table
```
Pick the Linux SLES host. Note `InstanceId`, `SecurityGroupId`, `SubnetId`.

### E.2 S3 staging bucket (one-time, reusable across appliances)
```powershell
aws s3 mb s3://m4h-staging-ajays --region us-east-1
setx S3_STAGING_BUCKET m4h-staging-ajays
```

### E.3 IAM role on EC2 — SSM + S3 (full access on the bucket)

Check existing profile first (CAL usually attaches one):
```powershell
aws ec2 describe-instances --instance-ids <INSTANCE-ID> `
  --query "Reservations[].Instances[].IamInstanceProfile" --output json
```

**If profile is `null`**:
```powershell
aws iam create-role --role-name m4h-s4-host `
  --assume-role-policy-document '{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Principal\":{\"Service\":\"ec2.amazonaws.com\"},\"Action\":\"sts:AssumeRole\"}]}'
aws iam attach-role-policy --role-name m4h-s4-host --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam put-role-policy --role-name m4h-s4-host --policy-name m4h-s3-full `
  --policy-document '{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"s3:*\",\"Resource\":[\"arn:aws:s3:::m4h-staging-ajays\",\"arn:aws:s3:::m4h-staging-ajays/*\"]}]}'
aws iam create-instance-profile --instance-profile-name m4h-s4-host
aws iam add-role-to-instance-profile --instance-profile-name m4h-s4-host --role-name m4h-s4-host
aws ec2 associate-iam-instance-profile --instance-id <INSTANCE-ID> --iam-instance-profile Name=m4h-s4-host
```

**If a profile already exists** (typical for CAL): add policies to the existing role rather than detaching.

### E.4 SSM agent + AWS CLI on the host (SSH as root, one-time per appliance)
```bash
sudo zypper install -y amazon-ssm-agent
sudo systemctl enable --now amazon-ssm-agent
sudo zypper install -y aws-cli || (curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip && unzip awscliv2.zip && sudo ./aws/install)
```

### E.5 Verify SSM (wait ~2 min after E.4)
```powershell
aws ssm describe-instance-information `
  --query "InstanceInformationList[].{ID:InstanceId,Ping:PingStatus}" --output table
# expect: Online

aws ssm send-command --instance-ids <INSTANCE-ID> --document-name "AWS-RunShellScript" `
  --parameters commands='whoami; ls -d /usr/sap/trans; tp --help | head' `
  --query "Command.CommandId" --output text
# take returned <CMD-ID>:
aws ssm get-command-invocation --command-id <CMD-ID> --instance-id <INSTANCE-ID> `
  --query "{Status:Status,Out:StandardOutputContent}"
```
Status = Success → transport door is wide open.

### E.6 Caller IAM on your laptop — wide-open dev policy
Attach this to your IAM user:
```json
{ "Version": "2012-10-17", "Statement": [
  { "Effect": "Allow", "Action": "ssm:*", "Resource": "*" },
  { "Effect": "Allow", "Action": "s3:*", "Resource": ["arn:aws:s3:::m4h-staging-ajays","arn:aws:s3:::m4h-staging-ajays/*"] },
  { "Effect": "Allow", "Action": "ec2:Describe*", "Resource": "*" },
  { "Effect": "Allow", "Action": "secretsmanager:*", "Resource": "*" },
  { "Effect": "Allow", "Action": "iam:Get*", "Resource": "*" }
] }
```

---

## PART F — Optional but unblocks edge cases

### F.1 abapGit dev version (for transport automation by the agent)
1. SAP GUI → `/nSE38` → `ZABAPGIT_STANDALONE` → Create → paste source from
   `https://raw.githubusercontent.com/abapGit/build/main/zabapgit_standalone.prog.abap` → Save → Activate.
2. Run (F8) → **+ New** → **Offline repo** → Package `$ABAPGIT` → import the `abapGit-main.zip`
   (download from `https://github.com/abapGit/abapGit`) → **Pull/Deserialize**.
3. After install, the agent can drive `zcl_abapgit_*` over RFC to record + ship transports.

### F.2 STRUST — trust GitHub SSL (for full online abapGit pull/push)
Skip if abapGit offline mode is enough.

### F.3 Number range buffers (avoid number-range exhaustion mid-run)
```
SAP GUI → /nSNRO → for each object you load:
  CUSTOMER, MATNR_NEW, BELNR, EBELN, VBELN, BUKRS, etc.
  → Number Ranges → confirm buffer set; reset if "exhausted"
```

### F.4 Background job authorization
Already covered by `SAP_ALL`. But make sure batch processes aren't all consumed:
```
SAP GUI → /nSM37 → cancel any orphan / stuck migration jobs
SAP GUI → /nSM50 → look for "PRIV" or "DEBUG" stuck WPs → end externally
```

---

## PART G — `connections.json` (refresh per fresh appliance)

```jsonc
{
  "ecc": {
    "ashost": "192.168.100.129",
    "sysnr": "41",
    "client": "800",
    "user": "M4H_ECC_ADMIN",
    "saprouter": "",
    "bastion_instance_id": "",
    "source_sid": "NPL",
    "saved_at": "<TODAY-ISO>"
  },
  "s4hana": null,
  "lift_and_shift_target": {
    "target_ashost": "vhcals4hci.dummy.nodomain",
    "target_sysnr": "00",
    "target_client": "100",
    "target_user": "MIGRATE_ADMI",
    "target_sid": "S4H",
    "target_public_ip": "<NEW-PUBLIC-IP>",
    "target_internal_ip": "<NEW-PRIVATE-IP>",
    "hana_host": "vhcals4hci.dummy.nodomain",
    "hana_sysnr": "02",
    "hana_schema": "SAPHANADB",
    "hana_user": "SAPHANADB",
    "saprouter": "",
    "mc_base_url": "https://vhcals4hci.dummy.nodomain:44300/sap/opu/odata/sap/CA_DATA_MIGRATION_SRV",
    "mc_user": "MIGRATE_ADMI",
    "ltmom_user": "MIGRATE_ADMI",
    "idoc_endpoint": "https://vhcals4hci.dummy.nodomain:44300/sap/bc/idoc_xml",
    "idoc_partner": "M4H_LAPTOP_ECC",
    "idoc_partner_type": "LS",
    "transport_host_instance_id": "<INSTANCE-ID>",
    "bastion_instance_id": "<INSTANCE-ID>",
    "saved_at": "<TODAY-ISO>"
  }
}
```

**Constants across appliances** (with master pw `Parupallitejaajay#92`):
`target_ashost`, `target_sysnr`, `target_client`, `target_user`, `target_sid`, `hana_*`, `mc_base_url`, `idoc_endpoint`, `idoc_partner*`.

**Refresh per appliance:** `target_public_ip`, `target_internal_ip`, `transport_host_instance_id`, `bastion_instance_id`, `saved_at`.

---

## PART H — Laptop env vars (one-time per Windows user)

```powershell
[Environment]::SetEnvironmentVariable("M4H_ECC_PASSWD","India123","User")
[Environment]::SetEnvironmentVariable("M4H_TARGET_PASSWD","Parupalliajayteja@2020","User")
[Environment]::SetEnvironmentVariable("M4H_HANA_PASSWD","Parupalliajayteja@2020","User")
[Environment]::SetEnvironmentVariable("M4H_TARGET_MODE","basis_handover_only","User")
[Environment]::SetEnvironmentVariable("SAPNWRFC_HOME","C:\Users\ajays\Downloads\migrate4hanav2\sapnwrfc","User")
[Environment]::SetEnvironmentVariable("AWS_DEFAULT_REGION","us-east-1","User")
[Environment]::SetEnvironmentVariable("S3_STAGING_BUCKET","m4h-staging-ajays","User")
```

Close + reopen PowerShell so they take effect.

---

## PART I — End-to-end verification (run all 9 probes)

```powershell
cd C:\Users\ajays\Downloads\migrate4hanav2
$env:SAPNWRFC_HOME = "$PWD\sapnwrfc"

# 1. ECC RFC login as M4H_ECC_ADMIN
python -c "from pyrfc import Connection; import os; c=Connection(ashost='192.168.100.129',sysnr='41',client='800',user='M4H_ECC_ADMIN',passwd=os.environ['M4H_ECC_PASSWD']); print('ECC login OK'); c.close()"

# 2. ECC RFC login as legacy sapuser (sanity)
python -c "from pyrfc import Connection; import os; c=Connection(ashost='192.168.100.129',sysnr='41',client='800',user='sapuser',passwd=os.environ['M4H_ECC_PASSWD']); print('ECC sapuser OK'); c.close()"

# 3. S/4 RFC login as MIGRATE_ADMI
python -c "from pyrfc import Connection; import os; c=Connection(ashost='vhcals4hci.dummy.nodomain',sysnr='00',client='100',user='MIGRATE_ADMI',passwd=os.environ['M4H_TARGET_PASSWD']); print('S4 login OK'); c.close()"

# 4. S/4 RFC login as SAP* (admin fallback)
python -c "from pyrfc import Connection; c=Connection(ashost='vhcals4hci.dummy.nodomain',sysnr='00',client='100',user='SAP*',passwd='Parupallitejaajay#92'); print('SAP* OK'); c.close()"

# 5. All three write paths
python writepath_probe.py
# expect:
#   transport (tp via SSH)        : READY-ish
#   migration cockpit (OData)     : READY — 200
#   idoc inbound (HTTP)           : READY — 200
#   rfc login                     : OK — S4H release 758

# 6. IDoc partner profile
python idoc_setup_probe.py
# expect: MATMAS + DEBMAS + CREMAS (or more) listed under M4H_LAPTOP_ECC

# 7. Live IDoc post + read-back
python idoc_prove.py
# expect: DOCNUM with STATUS 53 (posted) or 64 (ready)

# 8. SSM driving S/4 host
aws ssm describe-instance-information --query "InstanceInformationList[].PingStatus" --output text
# expect: Online

# 9. HANA SQL (optional)
python -c "import hdbcli.dbapi as h; c=h.connect(address='vhcals4hci.dummy.nodomain',port=32215,user='SAPHANADB',password='Parupalliajayteja@2020'); cur=c.cursor(); cur.execute('SELECT 1 FROM DUMMY'); print('HANA OK', cur.fetchone()); c.close()"
```

**All 9 must pass.** If they do: Migrate4HANA has *unconditional, unrestricted, gate-free* access to both systems.

---

## PART J — Credentials cheat-sheet

| What | Value | Used by |
|---|---|---|
| CAL master password | `Parupallitejaajay#92` | DDIC, SAP*, BPINST, S4ADMIN, S4HADM, SAPADM, root |
| `MIGRATE_ADMI` password | `Parupalliajayteja@2020` | `$M4H_TARGET_PASSWD` — RFC + IDoc + MC writes |
| `M4H_ECC_ADMIN` password | `India123` | `$M4H_ECC_PASSWD` — ECC RFC reads |
| Legacy `sapuser` (ECC) | `India123` | Fallback ECC login |
| HANA SAPHANADB | `Parupalliajayteja@2020` | `$M4H_HANA_PASSWD` |
| ECC hostname/IP | `192.168.100.129` | Drifts on VM restart — `ipconfig` to refresh |
| S/4 hostname | `vhcals4hci.dummy.nodomain` | Always connect by hostname |
| S/4 SID / client / sysnr | `S4H / 100 / 00` | Constant across appliances |
| HANA sysnr | `02` | Constant |
| HANA SQL port | `32215` (or `32202` on older builds) | Wide open per D.1 |
| OData base | `https://vhcals4hci.dummy.nodomain:44300/sap/opu/odata/sap/` | Constant |
| IDoc endpoint | `https://vhcals4hci.dummy.nodomain:44300/sap/bc/idoc_xml` | Constant |

---

## PART K — Per-appliance recreate checklist (TL;DR)

When the 30-day trial lapses and you spin up a fresh CAL appliance:

- [ ] **A.1** — Deploy CAL with master pw `Parupallitejaajay#92`. Wait 90 min.
- [ ] **A.2** — Allocate Elastic IP (optional, kills drift).
- [ ] **A.3** — Repoint Windows hosts file (admin PowerShell).
- [ ] **B.1–B.2** — Boot ECC VM, kill OS firewall inside it.
- [ ] **B.5** — Create / refresh `M4H_ECC_ADMIN` (Service type, SAP_ALL+SAP_NEW).
- [ ] **B.6** — ECC `SCC4` → changes allowed, cross-client allowed.
- [ ] **B.7** — ECC `RZ10`/`RZ11` → disable password policy + lockout + timeout.
- [ ] **B.8** — ECC `SM19` → disable security audit.
- [ ] **B.9** — ECC `SICF` → activate `default_host` recursively.
- [ ] **B.10–B.11** — ECC `BD54`/`WE21`/`SM59` → set logical system + RFC dest `M4H_S4H`.
- [ ] **C.2** — `python recover_access.py` (unlocks SAP*, MIGRATE_ADMI, DDIC).
- [ ] **C.3** — `python fix_migrate_admin.py --admin-pass "Parupallitejaajay#92"` + `python mc_role_probe.py --sap-all`.
- [ ] **C.4** — S/4 `SCC4` → unrestricted.
- [ ] **C.5** — S/4 `RZ10`/`RZ11` → same params as ECC.
- [ ] **C.6** — S/4 `SM19` → audit off.
- [ ] **C.7** — S/4 `SICF` → bulk-activate `default_host`.
- [ ] **C.8** — S/4 `/IWFND/MAINT_SERVICE` → add all MC + API services.
- [ ] **C.9** — S/4 `BD54` + `WE20` → logical systems + inbound partner profile (17 message types).
- [ ] **C.10** — S/4 `SM59` → RFC dest `M4H_ECC` (optional).
- [ ] **C.11** — SSH verify `TP_DOMAIN_S4H.PFL` + `tp connect`.
- [ ] **C.12** — `hdbsql` disable password rules on SAPHANADB.
- [ ] **D.1** — AWS SG → open all 17 ports to your IP.
- [ ] **D.3** — S/4 host: kill OS firewall (SSH as root).
- [ ] **E.2** — S3 staging bucket created (one-time).
- [ ] **E.3–E.5** — IAM role + SSM agent + verify online.
- [ ] **G** — Refresh `connections.json` with new IP + instance ID.
- [ ] **H** — Env vars set (one-time, persists).
- [ ] **I** — Run all 9 verification probes — all must pass.

When the checklist passes top-to-bottom, **Migrate4HANA can do whatever it wants on both systems**. No SAP gate, no auth check, no port block, no client lock, no password expiry, no audit throttle, no service 404, no IDoc 56 — nothing — will stop the tool. You're cleared to develop and iterate in full automated mode.

---

## PART L — Failure → fix table (every common block)

| Symptom | Cause | Fix |
|---|---|---|
| `WSAECONNREFUSED` on S/4 RFC | hosts file stale | **A.3** — repoint hosts as Admin |
| `timeout during allocate / no connect of TP sapdp00 from host <OLD-IP>` | hosts file stale (gateway re-resolves) | **A.3** — repoint + connect by hostname |
| `RFC_LOGON_FAILURE: name or password is incorrect` (MIGRATE_ADMI) | user locked OR type Dialog | **C.2** + **C.3** |
| `RFC_LOGON_FAILURE` for SAP* | wrong master pw OR `login/no_automatic_user_sapstar=1` | confirm pw; **C.5** set param to 0 |
| `RFC_LOGON_FAILURE: User is locked` | failed-logon lockout triggered | **C.2** unlock; **C.5** raise `fails_to_user_lock` |
| IDoc HTTP returns 404 | `/sap/bc/idoc_xml` inactive | **C.7** — SICF activate |
| IDoc lands with STATUS 56 | partner profile missing | **C.9** — WE20 inbound parameters |
| IDoc lands with STATUS 51 (application error) | payload incomplete | tool-side payload hardening — not a gate |
| MC OData returns 404 "no backend service found" | service not in /IWFND/MAINT_SERVICE | **C.8** — add service |
| MC OData returns 403 | user missing MC role | **C.3** — `mc_role_probe.py --sap-all` |
| MC OData returns 500 — "client not modifiable" | SCC4 setting too tight | **C.4** — changes allowed |
| `tp connect` fails | STMS not configured | **C.11** — STMS single-system setup |
| SSM `send-command` no Instance found | IAM role missing on EC2 / SSM agent not running | **E.3** + **E.4** |
| Long RFC call dies at 600s | `rdisp/max_wprun_time` default | **C.5** — set to `0` |
| "Password is initial — change it" | user type Dialog | **C.3** — Service (S) user type |
| HANA `08001 / authentication failed` | SAPHANADB password expired | **C.12** — disable lifetime |
| `SM21` shows "session manager terminated" repeatedly | audit log full | **C.13** — wipe SLG2 |

---

*End of runbook. This is the definitive "no SAP gate, no infra gate, no network gate" configuration. Keep it pinned; every step is reproducible from scratch.*
