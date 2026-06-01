# ECC Tunnel HOWTO — Connect AWS Lambda to Your Laptop ECC

*One-page runbook. Lets the deployed Migrate4HANA Lambdas reach your
laptop's SAP ECC (host-only VMnet at 192.168.100.x) via a reverse SSH
tunnel through an AWS bastion in the migrate4hana VPC.*

---

## The shape of the connection

```
┌──────────────────┐                  ┌──────────────────────────┐
│  Your laptop     │                  │  AWS migrate4hana VPC    │
│                  │                  │                          │
│  SAP ECC VM at   │                  │  ┌──────────────────┐    │
│  192.168.100.129 │                  │  │ Lambda functions │    │
│  port 3341       │                  │  └────────┬─────────┘    │
│  (host-only      │                  │           │              │
│   VMnet)         │                  │           │ pyrfc.Connection
│        ▲         │                  │           │ (ashost=<bastion-priv-ip>)
│        │         │                  │           ▼              │
│  ssh -R 0.0.0.0:3341:192.168.100.129:3341 ──── bastion:3341 ───┤
│  ec2-user@bastion-public-ip │       │  ┌───────┴────────┐    │
│  (this script runs from laptop)     │  │ t3.micro       │    │
└──────────────────┘                  │  │ EIP + sshd     │    │
                                       │  │ GatewayPorts:y │    │
                                       │  └────────────────┘    │
                                       └──────────────────────────┘
```

---

## One-time setup (~15 min)

### Step 1 — Generate an SSH key pair (laptop)

```powershell
cd C:\Users\ajays\Downloads\migrate4hanav2
ssh-keygen -t ed25519 -f migrate4hana-bastion -C migrate4hana-bastion
# Press Enter twice to skip passphrase (or set one if you want extra security
# - but you'll have to type it every time the tunnel reconnects).
```

You now have:
- `migrate4hana-bastion`     ← private key (keep secret, never commit)
- `migrate4hana-bastion.pub` ← public key (goes to terraform.tfvars)

### Step 2 — Add the public key to terraform.tfvars

```powershell
# Get the contents of the .pub file
$pub = (Get-Content .\migrate4hana-bastion.pub -Raw).Trim()

# Open terraform.tfvars (or create it)
cd terraform\environments\prod
notepad terraform.tfvars
```

Add this line (paste the public key value):

```hcl
ssh_public_key = "ssh-ed25519 AAAAC3Nz...your-public-key-here... migrate4hana-bastion"
```

Optional but recommended — also restrict SSH to your home IP:

```powershell
$myIp = (Invoke-WebRequest -Uri "https://checkip.amazonaws.com").Content.Trim()
# Add this too:
#   ssh_allowed_cidrs = ["YOUR_IP/32"]
```

### Step 3 — Apply terraform to provision the bastion (~3-5 min)

```powershell
cd terraform\environments\prod
terraform apply -auto-approve
```

Expect 3 new resources: `aws_instance.bastion`, `aws_eip.bastion`,
`aws_security_group.bastion`, plus one `aws_key_pair.bastion`. After apply
completes, terraform outputs `bastion_public_ip` and `bastion_private_ip`.

### Step 4 — Update the SAP-credentials secret

```powershell
cd ..\..\..\
.\scripts\update-ecc-secret.ps1
# Prompts for ECC password; reads bastion private IP from terraform output;
# writes the new value to migrate4hana/prod/sap-credentials.
```

---

## Per-session use (each time you want to run a Lambda against ECC)

### Step 5 — Wake the ECC VM

1. Open VMware Workstation; resume / start the NPL VM.
2. Inside the VM, confirm SAP is up. If not, log in as `npladm`, run `startsap`.
3. (If ECC's host-only IP drifted from `192.168.100.129`, run
   `ipconfig` inside the VM and update the `EccHost` param of step 6.)

### Step 6 — Open the reverse tunnel (laptop)

```powershell
.\scripts\launch-ecc-tunnel.ps1 `
    -SshKeyPath .\migrate4hana-bastion `
    -Persistent
```

Leave that window open. Output looks like:

```
==> Pre-flight checks
  Local ECC reachable: OK
==> Resolve bastion public IP from terraform output
  Bastion public IP:  3.x.x.x
  Bastion private IP: 10.30.101.x  (use this in connections.json / Secrets Manager)
==> Open reverse SSH tunnel (Ctrl-C to stop)
[14:23:01] starting ssh -R ...
```

**Leave running.** Ctrl-C closes the tunnel.

### Step 7 — Verify the tunnel is alive (from AWS side)

In another PowerShell window:

```powershell
# Find any Lambda log group and tail it; OR just hit the bastion directly.
# Easiest test: run the data-migrator with a tiny payload via the AWS Console
# or aws cli, then watch for "pyrfc connection established" in CloudWatch.

# Or test from the bastion itself:
ssh -i .\migrate4hana-bastion ec2-user@<bastion-public-ip> `
    "nc -zv 127.0.0.1 3341"
# Expect: "Connection to 127.0.0.1 3341 port [tcp/*] succeeded!"
```

### Step 8 — Trigger an actual migration

The Migrate4HANA tool's normal entry points now reach laptop ECC:

```powershell
# Via the data-migrator Lambda (single object spec)
aws lambda invoke --function-name migrate4hana-data-migrator-prod `
    --payload (@{
        run_id      = "tunnel-test-$(Get-Date -Format yyyyMMddHHmmss)"
        mode        = "extract_only"
        object_spec = @{
            object       = "Customer"
            source_table = "KNA1"
            fields       = @("KUNNR","NAME1","LAND1","ORT01")
            where_clause = ""
        }
    } | ConvertTo-Json -Compress | ForEach-Object { [System.Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($_)) }) `
    --cli-binary-format raw-in-base64-out `
    out.json
Get-Content out.json
```

If the tunnel + secret are correctly set up, the response includes a
`status:"success"` with the extracted KNA1 rows.

---

## Troubleshooting

| Symptom | Probable cause | Fix |
|---|---|---|
| `Pre-flight: Cannot reach ECC at 192.168.100.129:3341` | VM not started or SAP not started | Resume VM, run `startsap` inside |
| `ssh: Permission denied (publickey)` | Wrong private key, or key not registered with bastion | Check `-SshKeyPath` is the right file; verify `terraform output bastion_public_ip` matches the host you're connecting to |
| `Lambda: pyrfc connection refused` | Tunnel not running on laptop | Check the laptop window — is the tunnel still active? Re-launch with `-Persistent` |
| `Lambda: pyrfc connect timeout` | Lambda's SG can't reach bastion's private IP | Confirm `bastion_security_group_id` allows inbound 3341 from `10.0.0.0/8`; check Lambda SG outbound rules |
| `aws secretsmanager get-secret-value: not found` | Secret name mismatch | Run with `-Environment` matching your stack (`prod` by default) |
| `Tunnel works for 5 min then drops` | TCP keep-alive issue | The launcher already sets `ServerAliveInterval=30`; if drops persist, check your home router's NAT timeout |
| `ECC IP drifted to 192.168.100.x.y after VM reboot` | DHCP gave a new IP inside VM | Inside VM: `ipconfig`; re-run launcher with `-EccHost <new-ip>` |

---

## Cost

- **Bastion EC2 (t3.micro)**: ~$7.50/month if you leave it running 24×7
- **Elastic IP**: free while attached to a running instance; ~$3.60/month if you stop the instance
- **Data transfer**: ~$0.09/GB out — negligible for typical migration testing (a few hundred MB per run)
- **Tear down when done**: `terraform destroy -auto-approve` removes everything including the bastion + EIP

**Total** if used a few hours per week: ~$8-12/month.

---

## When you're done testing

```powershell
# 1. Close the tunnel (Ctrl-C in the launcher window)
# 2. Optionally stop the bastion to save money but keep the config:
aws ec2 stop-instances --instance-ids (
    aws ec2 describe-instances `
        --filters "Name=tag:Name,Values=migrate4hana-bastion-prod" `
        --query "Reservations[].Instances[].InstanceId" --output text
)
# 3. To fully remove: `terraform destroy` from prod env
```

---

## What this proves

After Step 8 returns clean data, you have **the AWS-deployed Migrate4HANA
data-migrator Lambda successfully reading from your real laptop ECC**. That's
the end-to-end claim you couldn't make before. Pair this with the
S/4HANA-side connectivity (separate runbook coming) for the full
ECC → AWS Lambda → S/4HANA migration loop.
