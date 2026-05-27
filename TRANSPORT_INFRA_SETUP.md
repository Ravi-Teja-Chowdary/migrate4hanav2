# Gap #4 Infrastructure Setup — live-validate the transport / config chain

*This enables the four transport stages (`transport-artifact-builder` → `transport-file-placer`
→ `transport-import-executor` → `transport-import-verifier`) and `config-applier` to actually
run against the live S/4HANA target, the same way the data-migration spine was validated.*

---

## 1. Why this infra is needed (grounded in the code)

The transport stages do **not** write to SAP over RFC. They run real SAP host commands — `tp`
(the transport control program) and `aws s3 cp` — **on the S/4 host's operating system**, via
**AWS Systems Manager (SSM) Run Command**. From the code:

- `lambda/utils/sap_host_runner.py` → `ssm.send_command(InstanceIds=[instance_id],
  DocumentName="AWS-RunShellScript", …)` then polls `get_command_invocation`.
- `transport-file-placer` runs on the host: `aws s3 cp <cofile_s3> /usr/sap/trans/cofiles/K…` +
  `aws s3 cp <datafile_s3> /usr/sap/trans/data/R…` + `chown <sid>adm:sapsys …`.
- `transport-import-executor` runs on the host: `su - <sid>adm -c 'tp addtobuffer <TR> <SID>
  pf=/usr/sap/trans/bin/TP_DOMAIN_<SID>.PFL'` then `tp import <TR> <SID> client=<C> U16 …`,
  and certifies success only on a clean `tp` return code.

So three things must be true:

| # | Requirement | Used by |
|---|---|---|
| **A** | SSM can run shell commands on the S/4 host EC2 instance | all transport stages |
| **B** | The S/4 host can read/write the S3 staging bucket (has AWS CLI + S3 perms) | file-placer (read), artifact-builder export (write) |
| **C** | STMS + `tp` work on the S/4 host (transport domain configured) | import-executor, artifact-builder |

---

## 2. Your setup: SAP CAL free-trial appliance in your own AWS account

Good news — a **SAP CAL "fully-activated appliance" deploys the EC2 instance(s) into YOUR AWS
account**, so you have full EC2 + IAM control and the standard SSM path works. A few CAL-specific
facts that shape the steps below:

- **The EC2 *instance ID* is stable across CAL Suspend/Activate** — only the *public IP* drifts (the
  thing that keeps breaking your hosts file). So you set `transport_host_instance_id` **once** and it
  keeps working through restarts. 🎉 (SSM addresses the host by instance ID, not IP — immune to the drift.)
- CAL usually deploys the SAP system on a **single SLES (SUSE Linux) host**; some templates add a
  small **Windows RDP/jump host**. You want the **Linux** instance (the one you RFC to on `:3200/3300`).
- ⚠️ **CAL may have already attached an IAM instance profile/role to the instance.** An instance can
  have only ONE instance profile, so in Step 3 you **check first** and *add policies to the existing
  role* rather than attaching a second one.
- You have OS access to the Linux host via **SSH as the master user** (the master password you set
  during CAL deployment) — that's how you install the SSM agent in Step 4. CAL's security group
  already opens your IP to the SAP ports; confirm it also allows your SSH (port 22).

**Before starting:** AWS CLI on your laptop (`aws sts get-caller-identity` works); know your **region**
(`setx AWS_DEFAULT_REGION us-east-1`, new shell after). SID is **`S4H`**, instance **`00`**, OS user
**`s4hadm`** (CAL S/4 defaults — adjust if your appliance differs).

---

## 3. Step-by-step

### Step 1 — Identify the S/4 (Linux) EC2 instance
List your running instances and pick the **Linux SLES** one (the SAP/HANA host you RFC to). If CAL
also made a Windows RDP host, ignore it. Confirm the IP matches the one in your `connections.json`.
```powershell
aws ec2 describe-instances --filters "Name=instance-state-name,Values=running" `
  --query "Reservations[].Instances[].{ID:InstanceId,IP:PublicIpAddress,OS:PlatformDetails,Name:Tags[?Key=='Name']|[0].Value}" --output table
```
Copy the **Instance ID** (`i-0abc123…`) of the Linux host — this is stable across CAL Suspend/Activate.

### Step 2 — Create (or reuse) the S3 staging bucket
The stages read/write `s3://<bucket>/runs/<run_id>/…`. Create one (globally-unique name):
```powershell
aws s3 mb s3://m4h-staging-<your-initials> --region us-east-1
```
Remember this bucket name — it becomes `S3_STAGING_BUCKET` for the run.

### Step 3 — Give the host an IAM role (SSM + S3) — **check for an existing one first**
An EC2 instance can have only ONE instance profile, and **CAL may have already attached one**. Check:
```powershell
aws ec2 describe-instances --instance-ids i-0abc123… `
  --query "Reservations[].Instances[].IamInstanceProfile" --output json
```

**Case A — it returns `null` (no profile attached).** Create and attach a fresh one:
```powershell
aws iam create-role --role-name m4h-s4-host `
  --assume-role-policy-document '{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Principal\":{\"Service\":\"ec2.amazonaws.com\"},\"Action\":\"sts:AssumeRole\"}]}'
aws iam attach-role-policy --role-name m4h-s4-host --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam put-role-policy --role-name m4h-s4-host --policy-name m4h-s3-staging `
  --policy-document '{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"s3:GetObject\",\"s3:PutObject\",\"s3:ListBucket\"],\"Resource\":[\"arn:aws:s3:::m4h-staging-<your-initials>\",\"arn:aws:s3:::m4h-staging-<your-initials>/*\"]}]}'
aws iam create-instance-profile --instance-profile-name m4h-s4-host
aws iam add-role-to-instance-profile --instance-profile-name m4h-s4-host --role-name m4h-s4-host
aws ec2 associate-iam-instance-profile --instance-id i-0abc123… --iam-instance-profile Name=m4h-s4-host
```

**Case B — a profile/role IS already attached (typical for CAL).** Do NOT detach CAL's role —
just **add the two policies to the existing role**. Grab the role name from the ARN the check
returned (`…:instance-profile/<name>` → find its role), then:
```powershell
# <EXISTING_ROLE> = the role behind CAL's attached instance profile
aws iam attach-role-policy --role-name <EXISTING_ROLE> --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam put-role-policy --role-name <EXISTING_ROLE> --policy-name m4h-s3-staging `
  --policy-document '{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"s3:GetObject\",\"s3:PutObject\",\"s3:ListBucket\"],\"Resource\":[\"arn:aws:s3:::m4h-staging-<your-initials>\",\"arn:aws:s3:::m4h-staging-<your-initials>/*\"]}]}'
```
(To find the role name behind an instance profile: `aws iam get-instance-profile --instance-profile-name <NAME> --query "InstanceProfile.Roles[].RoleName"`.)

### Step 4 — Install the SSM agent + AWS CLI on the S/4 host
SSH into the Linux host as the **master user** (the password you set during CAL deployment) — e.g.
`ssh root@<current-public-ip>` or the CAL-provided user, then `sudo -i`. If SSH refuses, open port
22 to your IP in the instance's security group (AWS console → EC2 → Security Groups). The appliance
is SUSE Linux (SLES). As **root**:
```bash
# SSM agent (SUSE)
sudo zypper install -y amazon-ssm-agent   # or: download the .rpm from AWS docs for SLES
sudo systemctl enable --now amazon-ssm-agent
sudo systemctl status amazon-ssm-agent     # expect: active (running)

# AWS CLI (needed by transport-file-placer's `aws s3 cp`)
sudo zypper install -y aws-cli || (curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip && unzip awscliv2.zip && sudo ./aws/install)
aws --version
```
The instance needs **outbound HTTPS (443)** to the SSM + S3 endpoints (default with an internet
gateway / NAT — usually already true since the host has a public IP).

### Step 5 — Verify SSM can drive the host
From your laptop (give it ~2 min after Step 4):
```powershell
aws ssm describe-instance-information --query "InstanceInformationList[].{ID:InstanceId,Ping:PingStatus,OS:PlatformName}" --output table
# Expect your i-0abc123… with Ping=Online. Then a live test:
aws ssm send-command --instance-ids i-0abc123… --document-name "AWS-RunShellScript" `
  --parameters commands='whoami; ls -d /usr/sap/trans; aws --version' --query "Command.CommandId" --output text
# take the returned command-id:
aws ssm get-command-invocation --command-id <CMD_ID> --instance-id i-0abc123… --query "{Status:Status,Out:StandardOutputContent}"
```
✅ Success = `Status: Success` and you see `/usr/sap/trans` + an `aws` version. **If this works, the
hard part is done** — it's exactly what `sap_host_runner.run` does.

### Step 6 — Caller IAM (the machine running the handlers — your laptop)
Your local AWS identity needs to drive SSM + S3 + secrets. Attach this policy to your IAM user/role:
```json
{ "Version": "2012-10-17", "Statement": [
  { "Effect": "Allow", "Action": ["ssm:SendCommand","ssm:GetCommandInvocation","ssm:DescribeInstanceInformation"], "Resource": "*" },
  { "Effect": "Allow", "Action": ["s3:GetObject","s3:PutObject","s3:ListBucket"], "Resource": ["arn:aws:s3:::m4h-staging-<your-initials>","arn:aws:s3:::m4h-staging-<your-initials>/*"] },
  { "Effect": "Allow", "Action": ["secretsmanager:GetSecretValue"], "Resource": "*" }
] }
```

### Step 7 — Confirm STMS / `tp` works on the S/4 host
On the S/4 host shell:
```bash
ls -l /usr/sap/trans/bin/TP_DOMAIN_S4H.PFL    # the transport profile the import-executor uses
su - s4hadm -c 'tp connect S4H pf=/usr/sap/trans/bin/TP_DOMAIN_S4H.PFL'   # expect a clean connect
```
- If `TP_DOMAIN_S4H.PFL` **exists** and `tp connect` returns cleanly → STMS is configured (the
  fully-activated CAL appliance usually has this). ✅
- If it's **missing**, configure STMS once: log into SAP GUI (S4H/000, user `DDIC` or `MIGRATE_ADMI`),
  run transaction **`STMS`** → accept "Configure as single-system transport domain" → Save. That
  generates the domain profile. (I can walk you through the exact screens if needed.)

### Step 8 — Wire the instance ID into the tool (one value, one place)
The **EC2 instance ID** (`i-0abc123…`, from Step 1) is how SSM finds the host. In this
single-appliance setup it's the same value everywhere the code reads it (the various
`*_bastion_instance_id` / `transport_host_instance_id` names all mean "the host that runs
`tp`"). You only set it in **one place** — `connections.json` → `lift_and_shift_target`:
```json
"transport_host_instance_id": "i-0abc123…",
"bastion_instance_id": "i-0abc123…"
```
The local shim (`local_aws_shim.target_creds`) now **automatically copies this instance ID and the
SID into the "target secret"** the transport stages load — so no separate secret edit is needed.
(`target_sid` is already `"S4H"`.) Finally, set the bucket for the run:
`setx S3_STAGING_BUCKET m4h-staging-<your-initials>` (open a new shell after `setx`).

---

## 4. The one decision that affects scope: BUILD system

`transport-artifact-builder` creates the transport on a **BUILD/source** system, then it's imported
to the **target**. For a first *mechanism* validation we use the **S/4 appliance as a single-system
transport domain** (build = target = `S4H`): create a transport there, release, export cofile/datafile
to S3, place them back, and `tp import` into a second client to prove the round-trip. That needs no
extra system. (A real code-remediation flow would use a separate DEV→S/4 STMS route; that's a later step.)

---

## 5. What I'll do once it's up (you don't do this)

Reply **"infra ready"** with the **instance ID** + **bucket name**, and I will:
1. SSM-ping the host + confirm `/usr/sap/trans` and `tp` (the Step-5/7 checks, automated).
2. Build a **harmless test transport** (a throwaway workbench object / text), release + export it.
3. Run it through file-placer → import-executor → verifier and **certify the `tp` return code** (RC 0 = success, 4 = review, ≥8 = fail) — the same evidence standard as the data spine.
4. Capture the result to `runs/<id>/transports/…` and record it in `AUDIT_REPORT.md` (Gap #4 → done).

---

## 6. Cost & safety

- **SSM Run Command is free**; S3 staging is a few cents. No new EC2 needed.
- Least-privilege IAM (S3 scoped to the one bucket).
- The test transport is a throwaway object; nothing destructive. The import-executor already
  refuses to certify on a bad/again missing `tp` return code.

---

## 7. Quick checklist

- [ ] S/4 EC2 instance ID known, region set
- [ ] S3 staging bucket created
- [ ] `m4h-s4-host` IAM role (SSM core + S3) attached to the instance
- [ ] SSM agent + AWS CLI installed/running on the host (`describe-instance-information` shows Online)
- [ ] Test `send-command` returns Success and sees `/usr/sap/trans`
- [ ] Caller IAM (laptop) has ssm + s3 + secrets perms
- [ ] `TP_DOMAIN_S4H.PFL` exists / STMS configured
- [ ] `connections.json` instance-id fields set; `S3_STAGING_BUCKET` exported

---

## 8. SAP CAL specifics — gotchas to expect

- **Suspend/Activate keeps the same instance ID** → your transport infra survives the IP drift; you
  only ever re-point the *hosts file* for RFC/OData (the data spine), never the transport instance ID.
- **Existing instance profile** (Step 3 Case B) is the most common CAL surprise — add policies to the
  existing role, don't fight it.
- **Trial expiry (30 days):** if you let the trial lapse and redeploy, you get a NEW instance ID —
  just update `connections.json` and re-run Step 4 on the new host.
- **Don't reconfigure CAL's STMS destructively.** If `TP_DOMAIN_S4H.PFL` already exists (it usually
  does on a fully-activated appliance), leave it; only run the `STMS` single-system setup if it's missing.
- **Optional, if you'd rather not install the SSM agent:** I can add a `paramiko`-based SSH runner as a
  drop-in alternative to `sap_host_runner.run` (key/password SSH to the Linux host). Say the word and
  I'll build it — but since the instance is in your account, the SSM path above is cleaner and free.
