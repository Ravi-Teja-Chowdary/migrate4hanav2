# SAP CAL S/4HANA — Full Configuration Runbook for Migrate4HANA

> **Purpose:** Every time you spin up a new SAP CAL "Fully-Activated S/4HANA Appliance"
> for the 30-day trial, this is the **complete, ordered list of steps** that have to
> be done **inside S/4** (SAP GUI + a few helper scripts in this repo) to make
> Migrate4HANA talk to it end-to-end (RFC + IDoc + Migration Cockpit + Transport).
>
> Follow top-to-bottom. The whole thing takes ~90 min on a fresh appliance.
> The hard parts are scripted in this repo so you don't have to remember them.
>
> **Last validated:** 2026-06-08 against CAL S/4HANA 2023 FPS01 Fully-Activated Appliance.

---

## 0. The end-state you are building

```
  ┌──────────────────────┐                    ┌───────────────────────────────────┐
  │  YOUR LAPTOP         │                    │  YOUR AWS ACCOUNT (CAL deploys)   │
  │  ─────────────────   │                    │  ─────────────────────────────    │
  │  • ECC VM            │                    │  • S/4HANA EC2 instance           │
  │    192.168.100.129   │                    │    Public IP drifts on restart    │
  │    sysnr 41 client 800│  ── RFC + HTTPS ─►│    Instance ID is STABLE          │
  │    user `sapuser`    │                    │    SID=S4H sysnr=00 client=100    │
  │  • Migrate4HANA      │                    │    user `MIGRATE_ADMI`            │
  │    sapnwrfc SDK      │                    │  • S3 staging bucket              │
  │    api_server.py     │                    │  • IAM role w/ SSM + S3           │
  │    connections.json  │                    │                                   │
  └──────────────────────┘                    └───────────────────────────────────┘
```

The **three doors** Migrate4HANA pushes through:

| Door | Carries | Required for |
|---|---|---|
| **RFC** (BAPI) | master + transactional creates (released BAPIs) | 25-object live spine |
| **IDoc** | bulk master & some transactional | extract+stage lane |
| **OData / Migration Cockpit** | bulk via CSV templates | 102-object MC lane |
| **Transport / `tp`** | code remediation + customizing | code-remediation stages |

You only need RFC for the data spine. IDoc + MC + Transport unlock the other lanes.

---

## 1. Deploy the SAP CAL appliance (one-time per trial, ~90 min)

### 1.1 Sign up & create the appliance
1. Go to **https://cal.sap.com** → register / log in.
2. **Solutions** → search **SAP S/4HANA 2023 FPS01, Fully-Activated Appliance**
   → **Create Appliance**.
3. CAL prompts:
   - **Account / Region:** your AWS account + a region close to you
     (e.g. `us-east-1` for low cost / `ap-south-1` for India).
   - **Instance size:** accept default (`m5.4xlarge` or `m5.8xlarge`).
   - **Master password:** **`Parupallitejaajay#92`**  ⬅ **MUST be this value**
     (every script and runbook in this repo assumes it).
     This password is set on **`DDIC`, `SAP*`, `BPINST`, `S4ADMIN`, `S4HADM`, `SAPADM`, `ROOT`**.
   - **Time-zone / network:** defaults.
4. **Create** → wait **60–90 min** while CAL boots EC2, installs HANA, runs activation jobs.
5. When status = **Active**, click the appliance → **Connect** tab → note:
   - **Public IP** (will drift on every Suspend/Activate).
   - **EC2 Instance ID** (e.g. `i-0dea60b2c9e82b680`) — **stable across restarts**.

### 1.2 Sanity ports
```powershell
Test-NetConnection <S4-public-ip> -Port 3300   # RFC gateway
Test-NetConnection <S4-public-ip> -Port 8000   # ICM HTTP
Test-NetConnection <S4-public-ip> -Port 44300  # ICM HTTPS (Migration Cockpit + IDoc)
Test-NetConnection <S4-public-ip> -Port 22     # SSH (for STMS infra setup)
```
All four should return `True`. If `3300` is closed, the appliance hasn't finished
booting — wait another 10–15 min.

### 1.3 SUSPEND when not in use
**This is the biggest cost lever.** From CAL Web UI → **Suspend**. EC2 stops,
EBS keeps your work. Resume in ~10 min when needed. ~$8/hr running, ~$0.10/GB/mo idle.

---

## 2. Laptop hosts-file repoint (do this EVERY time the IP drifts)

The S/4 calls itself `vhcals4hci.dummy.nodomain`. Your laptop needs a hosts entry mapping
that name to the current public IP. **CAL changes the IP on every Suspend/Activate.**

1. Open **PowerShell as Administrator** (Start → PowerShell → Right-click → Run as administrator).
2. Replace `<NEW-IP>` and paste:
```powershell
$ip="<NEW-IP>"; $h="$env:windir\System32\drivers\etc\hosts"
$body = (Get-Content $h | Where-Object { $_ -notmatch 'vhcals4hc' }) -join "`r`n"
$body += "`r`n$ip`tvhcals4hci.dummy.nodomain`r`n$ip`tvhcals4hcs.dummy.nodomain`r`n"
Set-Content $h $body -NoNewline
Get-Content $h | Select-String vhcals4hc
```
3. Confirm two lines print with the new IP.

> **CRITICAL gotcha:** errors like `timeout during allocate / no connect of TP sapdp00
> from host <OLD-IP>` mean the hosts file is stale, NOT that SAP is still starting.
> SAP's gateway re-resolves the appliance hostname during work-process allocate, so
> a raw-IP connect does NOT bypass it. Always connect **by hostname** after repointing.
>
> **Permanent fix:** allocate an **AWS Elastic IP** to the S/4 instance — IP stops drifting.

---

## 3. Recover / unlock S/4 admin users (FIRST login)

### 3.1 First GUI login — use `SAP*` (the appliance's built-in admin)
Install **SAP GUI for Windows** if not present. Logon parameters:
- **Application server:** `vhcals4hci.dummy.nodomain`
- **Instance no.:** `00`
- **Client:** `100`
- **User:** `SAP*`
- **Password:** `Parupallitejaajay#92`
- **Language:** `EN`

### 3.2 Unlock the standard admin users (one-liner via RFC, no GUI needed)
From the project root, in PowerShell (regular, not admin):
```powershell
cd C:\Users\ajays\Downloads\migrate4hanav2
$env:SAPNWRFC_HOME = "$PWD\sapnwrfc"
$env:M4H_TARGET_PASSWD = "Parupalliajayteja@2020"
python recover_access.py
```
This script:
- Tries to log in as `MIGRATE_ADMI` → falls back to `SAP*` → falls back to `DDIC`.
- Calls `BAPI_USER_UNLOCK` on `SAP*`, `MIGRATE_ADMI`, `DDIC`.
- Reports the user-type + lock-flag (UFLAG: `0`=ok, `64`=admin-lock, `128`=failed-logon-lock, `192`=both).

If it can't log in at all (all three failing), you need SAP GUI: log on as `SAP*` →
**SU01** → user → Unlock icon → Save.

---

## 4. Create the migration service user `MIGRATE_ADMI`

This is the **dedicated service account** Migrate4HANA uses for every RFC call,
IDoc push, and OData write. It must be **user type S (Service)** so:
(a) password isn't subject to first-logon forced-change (RFC would reject it),
(b) it works for both RFC **and** GUI.

### 4.1 Automated path — `fix_migrate_admin.py` (recommended)
Already-working admin (`SAP*`) creates/repairs `MIGRATE_ADMI` over RFC, no GUI needed:
```powershell
$env:M4H_TARGET_PASSWD = "Parupalliajayteja@2020"
python fix_migrate_admin.py --admin-pass "Parupallitejaajay#92"
```
What it does:
1. Logs on as `SAP*` with master password.
2. `BAPI_USER_CHANGE`: sets `MIGRATE_ADMI` user type to `S` (Service).
3. Resets password to `Parupalliajayteja@2020` (`M4H_TARGET_PASSWD`).
4. `BAPI_USER_GET_DETAIL` read-back: confirms `USTYP='S'`, `ISLOCKED` cleared.
5. Verifies by opening a fresh RFC session as `MIGRATE_ADMI` and calling `RFC_SYSTEM_INFO`.

Expected output:
```
SUCCESS — MIGRATE_ADMI logs on via RFC: S4H release 758
```

### 4.2 Manual path (only if script fails) — SAP GUI
1. SAP GUI as `SAP*` → transaction **SU01**.
2. Enter user name `MIGRATE_ADMI` → if not present, click **Create**. If present, **Change**.
3. **Logon Data** tab:
   - **User Type:** `Service` (S)
   - **Initial Password:** `Parupalliajayteja@2020` (Repeat: same)
   - **Valid From:** today, **Valid To:** `31.12.9999`
4. **Roles** tab: leave for §5.
5. **Profiles** tab: leave for §5.
6. Save (💾).

---

## 5. Grant `MIGRATE_ADMI` authorization

For the appliance (test/sandbox) we use the **`SAP_ALL` + `SAP_NEW`** shortcut.
For production you'd assign least-privilege roles instead.

### 5.1 Automated path — `mc_role_probe.py --sap-all`
```powershell
python mc_role_probe.py --sap-all
```
This calls `BAPI_USER_PROFILES_ASSIGN` to append `SAP_ALL` + `SAP_NEW` to
`MIGRATE_ADMI`'s profile list **without removing existing profiles**, then commits.
Re-runnable / idempotent.

### 5.2 Migration-Cockpit-specific roles (only if you don't grant SAP_ALL)
```powershell
python mc_role_probe.py            # see what MC roles exist on this appliance
python mc_role_probe.py --assign   # assigns SAP_CA_DMC_MC_USER + SAP_CA_DMC_MC_DEVELOPER
```
The script handles role **and** profile assignment (assigning a role doesn't activate
authorizations until the generated profile lands in the user's profile list — it reads
`AGR_1016` for each role and pushes the profile via `BAPI_USER_PROFILES_ASSIGN`).

### 5.3 Manual path — SAP GUI
- **SU01** → `MIGRATE_ADMI` → Change → **Profiles** tab → Add `SAP_ALL` and `SAP_NEW` → Save.
- Or **Roles** tab → Add `SAP_CA_DMC_MC_USER` + `SAP_CA_DMC_MC_DEVELOPER` → Save → User Comparison.

---

## 6. Open the client for changes — `SCC4`

Required so any IDoc/Migration-Cockpit/Transport activity is allowed.

1. SAP GUI → **`/nSCC4`** → toggle change mode (✏️) → double-click client `100`.
2. Confirm settings (Fully-Activated Appliance default — usually already OK):
   - **Changes and Transports for Client-Specific Objects:** *Changes allowed*
   - **Cross-Client Object Changes:** *Changes to Repository and cross-client Customizing allowed*
   - **Client Role:** *Customizing*
3. Save → Local Object (`$TMP`) when prompted.

---

## 7. Activate the IDoc inbound HTTP service — `SICF`

This activates `/sap/bc/idoc_xml` so Migrate4HANA can push IDoc XML over HTTPS:44300.

1. SAP GUI → **`/nSICF`** → execute (F8) with default filter (Service Name = `*`).
2. Tree navigate: `default_host` → `sap` → `bc` → **`idoc_xml`**.
3. Right-click the node → **Activate Service** → confirm Yes-Yes.
4. (If the node is grey/inactive elsewhere in the path, activate each ancestor too.)

Verify from the laptop:
```powershell
python writepath_probe.py
```
Expected line: `idoc inbound (HTTP): READY — endpoint live (200)`.

---

## 8. Create the IDoc partner profile — `BD54` + `WE20`

This is what makes a delivered IDoc actually *post* (status 53) rather than just land (status 56).

### 8.1 Define the sender logical system — `BD54`
1. SAP GUI → **`/nBD54`** → Enter.
2. **New Entries**.
3. Add row: **Log. System** = `M4HSENDER`, **Name** = `Migrate4HANA sender`.
4. Save → Local Object (`$TMP`).

### 8.2 (Verify own logical system)
Check that this client has its own logical system set (default for Fully-Activated Appliance is `S4HCLNT100`):
```powershell
python idoc_setup_probe.py
```
Look for `client 100 logical system = S4HCLNT100` (or whatever the appliance uses).

### 8.3 Create the inbound partner profile — `WE20`
1. SAP GUI → **`/nWE20`** → Enter.
2. Left tree: click **Partner Type LS** → click **Create** (blank-page icon).
3. **Partner No.:** `M4HSENDER` · **Partn. Type:** `LS` → Save.
4. In the lower **Inbound parameters** box, click **+** (Create) and add each row below.
   For each: select **Trigger Immediately** ("Trigger by background program" also works,
   but Immediately is simpler for a test appliance). Save after each.

| Message Type | Process Code | Purpose |
|---|---|---|
| `MATMAS` | `MATM` | Material master |
| `DEBMAS` | `DEBM` | Customer master |
| `CREMAS` | `CREM` | Vendor master |
| `COND_A` | `COND` | Pricing conditions |
| `EXCHANGE_RATE` | `EXCHANGE_RATE_IDOC_INBOUND` | Exchange rates |
| `GLMAST` | `GLMA` | G/L master |
| `BANK_CREATE` | `BANK` | Bank master |

> **Minimum for first run:** just `MATMAS` / `MATM`. You can come back and add the
> rest only as you start exercising those object types.

### 8.4 Verify partner profile
```powershell
python check_partner.py            # lists EDPP1 partners + EDP21 inbound rows
python idoc_prove.py               # pushes a test MATMAS IDoc, reads EDIDC back
```
`idoc_prove.py` expected output: a `DOCNUM` with STATUS `53` (posted) or `64`
(ready-to-post). Status `56` = partner profile missing (re-check 8.3).

---

## 9. Activate Migration Cockpit OData service — `/IWFND/MAINT_SERVICE`

The Migration Cockpit lane is unlocked via the embedded SAP Gateway.

1. SAP GUI as `MIGRATE_ADMI` → **`/n/IWFND/MAINT_SERVICE`**.
2. Click **Add Service**.
3. **System Alias:** `LOCAL`.
4. **Technical Service Name:** `*DATA_MIGRATION*` → search.
5. Select **`CA_DATA_MIGRATION_SRV`** → **Add Selected Services** → Package `$TMP` → Save.
6. Repeat for **`CA_DATA_MIGRATION_OBJECT_SRV`**.

Verify:
```powershell
python writepath_probe.py
```
Expected: `migration cockpit (OData): READY — published & authorized (200)`.

> **If "no backend service found":** the service needs registering in the backend
> first via **`/n/IWBEP/REG_SERVICE`** — that's a SAP Basis task. For a first run,
> skip MC and stick to the RFC + IDoc lanes; come back to MC later.

### 9.1 Alternative — the "Migrate Your Data" Fiori app
On S/4 2023/2025, the modern path is the Fiori Launchpad app:
- URL: `https://vhcals4hci.dummy.nodomain:44300/sap/bc/ui2/flp` → tile **Migrate Your Data**.
- Create a migration project there and upload CSVs the tool produced in
  `local-staging/.../data-migrator/mc/`.

---

## 10. Configure STMS (transport system) — `STMS`

Required for the transport-import-executor stages. Fully-Activated Appliance usually
has this done already — verify first.

### 10.1 Verify (do this first)
Via SSH to the S/4 host as `root` or `s4hadm`:
```bash
ls -l /usr/sap/trans/bin/TP_DOMAIN_S4H.PFL
su - s4hadm -c 'tp connect S4H pf=/usr/sap/trans/bin/TP_DOMAIN_S4H.PFL'
```
- If the `.PFL` exists and `tp connect` returns cleanly → ✅ skip 10.2.
- If missing → continue 10.2.

### 10.2 Initialize the transport domain (only if missing)
1. SAP GUI as `MIGRATE_ADMI` → **`/nSTMS`**.
2. SAP prompts: **Configure as single-system transport domain** → accept defaults → Save.
3. This generates `/usr/sap/trans/bin/TP_DOMAIN_S4H.PFL`.

### 10.3 (Optional) Register the laptop ECC as an external source system
Only needed if you want STMS-based transport routes between ECC and S/4 (most setups
don't — they use the file/abapGit lane).
1. **`/nSTMS`** → **Systems** → External System.
2. SID = `NPL` (or your ECC's SID — check via `/nSM51` on ECC).
3. Description = `Laptop ECC source for lift-and-shift`.
4. Communication = **External** (file-based).
5. Activate → **Transport Routes** → add `NPL → S4H` (consolidation).

---

## 11. AWS infrastructure for transport import (SSM + S3)

Migrate4HANA's transport stages run `tp` on the S/4 host **via AWS Systems Manager**
(SSM Run Command). Set this once per appliance — IP-drift-immune because SSM
addresses by instance ID, not IP.

### 11.1 Capture the EC2 instance ID
```powershell
aws ec2 describe-instances --filters "Name=instance-state-name,Values=running" `
  --query "Reservations[].Instances[].{ID:InstanceId,IP:PublicIpAddress,Name:Tags[?Key=='Name']|[0].Value}" --output table
```
Copy the **Instance ID** of the **Linux SLES** host (ignore any Windows RDP jump host).
Current value (this trial): `i-0dea60b2c9e82b680`.

### 11.2 Create the S3 staging bucket
```powershell
aws s3 mb s3://m4h-staging-<your-initials> --region us-east-1
setx S3_STAGING_BUCKET m4h-staging-<your-initials>
```

### 11.3 Attach IAM role to the EC2 (SSM + S3)
Check if CAL has already attached an instance profile:
```powershell
aws ec2 describe-instances --instance-ids <INSTANCE-ID> `
  --query "Reservations[].Instances[].IamInstanceProfile" --output json
```

**Case A — `null` returned (no profile yet):**
```powershell
aws iam create-role --role-name m4h-s4-host `
  --assume-role-policy-document '{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Principal\":{\"Service\":\"ec2.amazonaws.com\"},\"Action\":\"sts:AssumeRole\"}]}'
aws iam attach-role-policy --role-name m4h-s4-host --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam put-role-policy --role-name m4h-s4-host --policy-name m4h-s3-staging `
  --policy-document '{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"s3:GetObject\",\"s3:PutObject\",\"s3:ListBucket\"],\"Resource\":[\"arn:aws:s3:::m4h-staging-<your-initials>\",\"arn:aws:s3:::m4h-staging-<your-initials>/*\"]}]}'
aws iam create-instance-profile --instance-profile-name m4h-s4-host
aws iam add-role-to-instance-profile --instance-profile-name m4h-s4-host --role-name m4h-s4-host
aws ec2 associate-iam-instance-profile --instance-id <INSTANCE-ID> --iam-instance-profile Name=m4h-s4-host
```

**Case B — a profile already exists (typical for CAL):** Do **not** detach it. Just
add the two policies to the existing role:
```powershell
aws iam attach-role-policy --role-name <EXISTING-ROLE> --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam put-role-policy --role-name <EXISTING-ROLE> --policy-name m4h-s3-staging `
  --policy-document '{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"s3:GetObject\",\"s3:PutObject\",\"s3:ListBucket\"],\"Resource\":[\"arn:aws:s3:::m4h-staging-<your-initials>\",\"arn:aws:s3:::m4h-staging-<your-initials>/*\"]}]}'
```

### 11.4 Install SSM agent + AWS CLI on the host (SSH as root)
```bash
sudo zypper install -y amazon-ssm-agent
sudo systemctl enable --now amazon-ssm-agent
sudo systemctl status amazon-ssm-agent     # expect: active (running)

sudo zypper install -y aws-cli || (curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip && unzip awscliv2.zip && sudo ./aws/install)
aws --version
```

### 11.5 Verify SSM can drive the host (from laptop, wait ~2 min after 11.4)
```powershell
aws ssm describe-instance-information `
  --query "InstanceInformationList[].{ID:InstanceId,Ping:PingStatus,OS:PlatformName}" --output table
# expect: <INSTANCE-ID> Online SLES

aws ssm send-command --instance-ids <INSTANCE-ID> --document-name "AWS-RunShellScript" `
  --parameters commands='whoami; ls -d /usr/sap/trans; aws --version' --query "Command.CommandId" --output text
# take the returned <CMD-ID>:
aws ssm get-command-invocation --command-id <CMD-ID> --instance-id <INSTANCE-ID> `
  --query "{Status:Status,Out:StandardOutputContent}"
# expect: Status=Success, /usr/sap/trans listed, aws version printed
```

### 11.6 Caller IAM (your laptop)
Attach this policy to your IAM user/role:
```json
{ "Version": "2012-10-17", "Statement": [
  { "Effect": "Allow", "Action": ["ssm:SendCommand","ssm:GetCommandInvocation","ssm:DescribeInstanceInformation"], "Resource": "*" },
  { "Effect": "Allow", "Action": ["s3:GetObject","s3:PutObject","s3:ListBucket"], "Resource": ["arn:aws:s3:::m4h-staging-<your-initials>","arn:aws:s3:::m4h-staging-<your-initials>/*"] },
  { "Effect": "Allow", "Action": ["secretsmanager:GetSecretValue"], "Resource": "*" }
] }
```

---

## 12. (Optional) Install abapGit for transport automation — `SE38`

Needed only if you want Migrate4HANA to **build and ship code transports** itself
(otherwise it emits a manual to-do manifest). Skip on first run.

### 12.1 Install the standalone report
1. SAP GUI as `MIGRATE_ADMI` → **`/nSE38`** → Program `ZABAPGIT_STANDALONE` → **Create**.
2. Program type: **Executable program** → Package: `$TMP` (or `Z001` for transportable).
3. Source: paste / upload the latest standalone source from
   `https://raw.githubusercontent.com/abapGit/build/main/zabapgit_standalone.prog.abap`
   (SE38 → *Utilities → More Utilities → Upload/Download → Upload* is easier than pasting).
4. Save → Activate (Ctrl+F3) → Run (F8) once to confirm the abapGit screen appears.

### 12.2 Install the developer version (offline)
The standalone gives you a UI but only local classes. The agent needs global
`ZCL_ABAPGIT_*` classes from the dev version:
1. Browser: `https://github.com/abapGit/abapGit` → **Code** → **Download ZIP** → `abapGit-main.zip`.
2. Run `ZABAPGIT_STANDALONE` (SE38 → F8).
3. **+ New** → **Offline repo** → Package = `$ABAPGIT` (create as local if prompted).
4. Import the ZIP → **Pull / Deserialize** → dev version installed.

### 12.3 (Online mode, later) Trust GitHub's SSL cert — `STRUST`
Only needed for full git pull/push automation:
1. Browser: open `https://github.com`, export the full cert chain as Base64 `.cer` files.
2. SAP GUI → **`/nSTRUST`** → **SSL client SSL Client (Standard)** → right-click → *Import certificate*
   for each cert → **Add to Certificate List** → Save.
3. Verify the ICM allows outbound HTTPS: **`/nSMICM`** → Services → port 443 open outbound.

---

## 13. Update `connections.json` with the new appliance details

After every appliance recreate, refresh `connections.json` → `lift_and_shift_target`
with the new public IP and the (usually unchanged) instance ID.

```jsonc
{
  "ecc": {
    "ashost": "192.168.100.129",
    "sysnr": "41",
    "client": "800",
    "user": "sapuser",
    "saprouter": "",
    "bastion_instance_id": "",
    "source_sid": "NPL",
    "saved_at": "2026-06-08T00:00:00"
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
    "saved_at": "<TODAY>"
  }
}
```

Fields to refresh per appliance:
- `target_public_ip` ← from CAL "Connect" tab
- `target_internal_ip` ← from `aws ec2 describe-instances` (PrivateIpAddress)
- `transport_host_instance_id` / `bastion_instance_id` ← from §11.1 (stable across CAL Suspend)
- `saved_at` ← today's ISO date

Fields that **never** change between appliances (with master pw `Parupallitejaajay#92`):
- `target_ashost`, `target_sysnr`, `target_client`, `target_user`, `target_sid`
- `hana_host`, `hana_sysnr`, `hana_schema`, `hana_user`
- `mc_base_url`, `idoc_endpoint`, `idoc_partner`, `idoc_partner_type`

---

## 14. Laptop env vars (one-time per Windows user)

These never change. Set once, every PowerShell window picks them up.
```powershell
[Environment]::SetEnvironmentVariable("M4H_ECC_PASSWD","India123","User")
[Environment]::SetEnvironmentVariable("M4H_TARGET_PASSWD","Parupalliajayteja@2020","User")
[Environment]::SetEnvironmentVariable("M4H_HANA_PASSWD","Parupalliajayteja@2020","User")
[Environment]::SetEnvironmentVariable("M4H_TARGET_MODE","basis_handover_only","User")
[Environment]::SetEnvironmentVariable("SAPNWRFC_HOME","C:\Users\ajays\Downloads\migrate4hanav2\sapnwrfc","User")
```

**Then close PowerShell and reopen** so the new vars take effect.

---

## 15. End-to-end verification — run all probes in order

After §1–§14, run these from the project root and confirm each one prints OK:

```powershell
cd C:\Users\ajays\Downloads\migrate4hanav2
$env:SAPNWRFC_HOME = "$PWD\sapnwrfc"
$env:M4H_TARGET_PASSWD = "Parupalliajayteja@2020"
$env:M4H_ECC_PASSWD    = "India123"

# 1. ECC login
python -c "from pyrfc import Connection; import os; c=Connection(ashost='192.168.100.129',sysnr='41',client='800',user='sapuser',passwd=os.environ['M4H_ECC_PASSWD']); print('ECC login OK'); c.close()"

# 2. S/4 login as MIGRATE_ADMI
python -c "from pyrfc import Connection; import os; c=Connection(ashost='vhcals4hci.dummy.nodomain',sysnr='00',client='100',user='MIGRATE_ADMI',passwd=os.environ['M4H_TARGET_PASSWD']); print('S4 login OK'); c.close()"

# 3. All write paths
python writepath_probe.py
# expected:
#   transport (tp via SSH)        : READY-ish — SSH port open
#   migration cockpit (OData)     : READY — published & authorized (200)
#   idoc inbound (HTTP)           : READY — endpoint live (200)
#   rfc login                     : OK — S4H release 758

# 4. IDoc partner profile present
python idoc_setup_probe.py
# expected: at least one inbound partner with MATMAS

# 5. Live IDoc post
python idoc_prove.py
# expected: a DOCNUM row with STATUS 53 (posted) or 64 (ready)
```

---

## 16. Credentials cheat-sheet (this trial)

| What | Value | Notes |
|---|---|---|
| CAL master password | `Parupallitejaajay#92` | Set during appliance creation. Drives DDIC, SAP*, BPINST, S4ADMIN, OS users, root. **Always use this value.** |
| MIGRATE_ADMI password | `Parupalliajayteja@2020` | Set by `fix_migrate_admin.py`. Env var `M4H_TARGET_PASSWD`. |
| HANA SAPHANADB password | `Parupalliajayteja@2020` | Env var `M4H_HANA_PASSWD`. |
| ECC sapuser password | `India123` | Env var `M4H_ECC_PASSWD`. |
| ECC ashost | `192.168.100.129` | Drifts on VM restart — re-check via `ipconfig` on the ECC VM. |
| ECC sysnr / client | `41 / 800` | |
| S/4 ashost | `vhcals4hci.dummy.nodomain` | Always use hostname (gateway re-resolves); maintain hosts file per §2. |
| S/4 sysnr / client / SID | `00 / 100 / S4H` | |
| Working admin (fallback) | `SAP*` | Same master password. Use for SU01 unlocks, BAPI_USER_CHANGE. |
| Backup admin | `DDIC` | Same master password. |

---

## 17. The recreate-checklist (TL;DR for the next appliance)

When you let the 30-day trial lapse and spin up a fresh one:

- [ ] §1 — Deploy CAL appliance with master pw `Parupallitejaajay#92`. Wait 90 min.
- [ ] §2 — Repoint Windows hosts file to the new public IP (admin PowerShell).
- [ ] §3 — Run `python recover_access.py` to unlock standard users.
- [ ] §4 — Run `python fix_migrate_admin.py --admin-pass "Parupallitejaajay#92"` (creates+repairs MIGRATE_ADMI).
- [ ] §5 — Run `python mc_role_probe.py --sap-all` to grant SAP_ALL.
- [ ] §6 — SAP GUI: `SCC4` → client 100 → Changes allowed.
- [ ] §7 — SAP GUI: `SICF` → activate `/default_host/sap/bc/idoc_xml`.
- [ ] §8 — SAP GUI: `BD54` add `M4HSENDER` ; `WE20` add inbound `MATMAS/MATM` (minimum).
- [ ] §9 — SAP GUI: `/IWFND/MAINT_SERVICE` → add `CA_DATA_MIGRATION_SRV` + `CA_DATA_MIGRATION_OBJECT_SRV`.
- [ ] §10 — SSH to host: verify `/usr/sap/trans/bin/TP_DOMAIN_S4H.PFL` exists; if not, `STMS` setup.
- [ ] §11 — AWS: re-capture instance ID; attach IAM (SSM + S3); install ssm-agent on host; verify `send-command`.
- [ ] §12 — Optional: install abapGit standalone + dev version via SE38 + offline ZIP.
- [ ] §13 — Update `connections.json` → new public IP, new internal IP, current instance ID.
- [ ] §14 — Confirm laptop env vars set (one-time, persists across appliances).
- [ ] §15 — Run all 5 probes in order — all must print OK / READY / 200 / status 53–64.

**If all probes pass: Migrate4HANA is fully wired to the new appliance.**
Proceed to your normal `python run_local_lift_and_shift.py` workflow.

---

## 18. Common failure → fix table

| Symptom | Cause | Fix |
|---|---|---|
| `WSAECONNREFUSED` on `<S4-IP>:3300` | hosts file points to OLD IP | §2 — repoint hosts as Administrator |
| `timeout during allocate / no connect of TP sapdp00 from host <OLD-IP>` | hosts file stale (gateway re-resolves) | §2 — repoint hosts; connect by hostname |
| `RFC_LOGON_FAILURE: name or password is incorrect` for MIGRATE_ADMI | user locked OR is Dialog (forced password change) | §3 then §4 |
| `RFC_LOGON_FAILURE` for SAP* | SAP* not enabled or wrong master password | Verify master pw `Parupallitejaajay#92`; SCC4 → allow SAP* logon |
| `idoc inbound (HTTP): SETUP — /sap/bc/idoc_xml not active (404)` | SICF service not activated | §7 — SICF → activate node |
| IDoc lands with STATUS 56 | no partner profile for the message type | §8 — WE20 → inbound parameters |
| `migration cockpit (OData): HTTP 404 — no backend service found` | service not added in `/IWFND/MAINT_SERVICE` | §9 — Add Service |
| `migration cockpit (OData): HTTP 403 — not authorized` | user missing MC role | §5 — `mc_role_probe.py --sap-all` |
| SSM `send-command` returns no Instance found | IAM role on EC2 missing or ssm-agent down | §11.3 + §11.4 |
| `tp connect` fails on host | STMS not configured | §10.2 |

---

*End of runbook. Keep this file pinned. Every step above is reproducible from scratch.*
