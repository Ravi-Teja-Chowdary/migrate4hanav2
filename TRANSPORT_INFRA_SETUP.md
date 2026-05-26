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

## 2. Assumptions / what you need before starting

- **You control the S/4HANA EC2 instance in your own AWS account** (you can attach an IAM role
  and open an OS shell on it). ⚠️ *If the S/4 appliance lives in a SAP-managed CAL account where
  you can't attach an IAM instance profile, SSM can't manage it — see §8 for the fallback.*
- AWS CLI installed on **your laptop**, logged in (`aws sts get-caller-identity` works).
- The S/4 host SID is **`S4H`**, instance **`00`**, OS user **`s4hadm`** (CAL default). Adjust if different.
- Your AWS **region** (e.g. `us-east-1`). Set it once: `setx AWS_DEFAULT_REGION us-east-1` (new shell after).

---

## 3. Step-by-step

### Step 1 — Identify the S/4 EC2 instance
In the AWS console → EC2 → Instances, find the S/4HANA appliance and copy its **Instance ID**
(`i-0abc123…`). Note its **region**. Quick CLI check:
```powershell
aws ec2 describe-instances --filters "Name=instance-state-name,Values=running" `
  --query "Reservations[].Instances[].{ID:InstanceId,IP:PublicIpAddress,Name:Tags[?Key=='Name']|[0].Value}" --output table
```

### Step 2 — Create (or reuse) the S3 staging bucket
The stages read/write `s3://<bucket>/runs/<run_id>/…`. Create one (globally-unique name):
```powershell
aws s3 mb s3://m4h-staging-<your-initials> --region us-east-1
```
Remember this bucket name — it becomes `S3_STAGING_BUCKET` for the run.

### Step 3 — IAM role for the S/4 host (instance profile)
This lets SSM manage the host **and** lets the host pull/push transport files from S3.

1. Create the role with the SSM trust + managed policy:
```powershell
aws iam create-role --role-name m4h-s4-host `
  --assume-role-policy-document '{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Principal\":{\"Service\":\"ec2.amazonaws.com\"},\"Action\":\"sts:AssumeRole\"}]}'
aws iam attach-role-policy --role-name m4h-s4-host `
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
```
2. Add S3 read+write on just the staging bucket (least-privilege):
```powershell
aws iam put-role-policy --role-name m4h-s4-host --policy-name m4h-s3-staging `
  --policy-document '{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"s3:GetObject\",\"s3:PutObject\",\"s3:ListBucket\"],\"Resource\":[\"arn:aws:s3:::m4h-staging-<your-initials>\",\"arn:aws:s3:::m4h-staging-<your-initials>/*\"]}]}'
```
3. Wrap it in an instance profile and attach to the S/4 instance:
```powershell
aws iam create-instance-profile --instance-profile-name m4h-s4-host
aws iam add-role-to-instance-profile --instance-profile-name m4h-s4-host --role-name m4h-s4-host
aws ec2 associate-iam-instance-profile --instance-id i-0abc123… `
  --iam-instance-profile Name=m4h-s4-host
```

### Step 4 — Install the SSM agent + AWS CLI on the S/4 host
Open a shell on the S/4 host (SSH as your admin user, or the CAL web console). The CAL appliance
is SUSE Linux. As **root**:
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

### Step 8 — Wire the instance ID into the tool
Edit `connections.json` → `lift_and_shift_target`, set the S/4 EC2 instance ID in both fields the
stages read:
```json
"transport_host_instance_id": "i-0abc123…",
"bastion_instance_id": "i-0abc123…"
```
And make sure the target secret the stages load (Secrets Manager, or the local shim) carries the
same `bastion_instance_id` / `target_bastion_instance_id`, `target_sid: "S4H"`, `target_client`.
Set the bucket for the run: `setx S3_STAGING_BUCKET m4h-staging-<your-initials>`.

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

## 8. Fallback if you DON'T control the S/4 instance in your AWS account

If the S/4 appliance is in a SAP-managed CAL account (no IAM access to attach a role), SSM can't
manage it. Options, in order of preference:
1. **SSM hybrid activation** — register the host as a *managed instance* (works for non-EC2/non-owned
   hosts) and install the agent with an activation code. Then everything else is identical.
2. **Switch the host runner to SSH** — I can add a small `paramiko`-based alternative to
   `sap_host_runner.run` (key-based SSH to `s4hadm@<host>`) so transports run over SSH instead of SSM.
   Tell me and I'll build it; you'd just provide an SSH key on the host.
