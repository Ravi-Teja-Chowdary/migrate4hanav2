# CAL ECC IDES → S/4HANA end-to-end runbook

> **⚠️ SUPERSEDED for the ECC half — see [`LAMBDA_TO_LOCAL_ECC.md`](./LAMBDA_TO_LOCAL_ECC.md).**
> The SAP CAL IDES EHP8 appliance had broken in-VM provisioning (no `/usr/sap`,
> no `abaadm` user) and was abandoned. We pivoted to local Windows ECC via ngrok.
> The S/4 half of this runbook (Route 53 + secret update + smoke test against
> the CAL S/4 Fully-Activated Appliance) is still valid — use those parts plus
> the new `LAMBDA_TO_LOCAL_ECC.md` for the ECC half.

Use this once both SAP CAL appliances (ECC IDES + S/4HANA) are running and you
have their **public IPs** from the CAL console.

This replaces the laptop-ECC + bastion-tunnel path. The bastion EC2 can stay
stopped (cheaper) or be destroyed entirely once you confirm this CAL path works.

---

## Pre-conditions

| Item | Where to get it |
|---|---|
| **S/4HANA public IP** | SAP CAL console → S/4HANA appliance → "Connect" |
| **CAL ECC public IP** | SAP CAL console → IDES ECC appliance → "Connect" |
| **CAL ECC hostname** | SAP CAL console → IDES appliance → "System details" (June-2021 IDES build = `vhcalabaci`) |
| **ECC user/password** | **`IDADMIN` / `ides123`** on client `800` — the IDES migration-scenario credentials per the Getting Started Guide. (`DDIC` / `SAP*` on any client use your CAL master password.) |
| **S/4 password** | Already set in `migrate4hana/prod/s4hana-credentials` (or re-enter) |
| **Both SGs allow 0.0.0.0/0** | You confirmed this is open for now — fine for testing |

## Step 1 — Update tfvars + apply

Both IPs go in `terraform/environments/prod/terraform.tfvars`:

```hcl
s4_public_ip       = "<S/4 public IP>"
cal_ecc_public_ip  = "<CAL ECC public IP>"
cal_ecc_hostname   = "vhcalabaci"   # IDES EHP8 June-2021 build (SID=ABA on Connect dialog).
                                    # Change if CAL "Connect" shows different SID.
```

Apply:

```powershell
cd terraform\environments\prod
terraform apply -auto-approve
cd ..\..\..
```

This creates the Route 53 A records inside the VPC so Lambdas can resolve
`vhcalerphci.dummy.nodomain` (ECC) and `vhcals4hci.dummy.nodomain` (S/4).
Without these records, the SAP kernel's back-verify step fails with
`partner not reached` — the exact error we hit before with the laptop bastion.

## Step 2 — Update the two Secrets Manager entries

```powershell
# 1) Point sap-credentials at the CAL ECC
.\scripts\update-cal-ecc-secret.ps1 -CalEccPublicIp <CAL ECC public IP>
# (prompts for ECC password)

# 2) Point s4hana-credentials at the current S/4 public IP
.\scripts\update-s4-secret.ps1 -S4PublicIp <S/4 public IP>
# (prompts for S/4 password)
```

The CAL ECC script writes `ashost = vhcalerphci.dummy.nodomain` — NOT the
public IP — so the kernel's back-verify resolves to the same name from inside
the VPC.

## Step 3 — Smoke-test from the laptop (optional)

You don't strictly need this — Lambda is the real test — but it confirms both
appliances are alive:

```powershell
Test-NetConnection <CAL ECC public IP> -Port 3300 -InformationLevel Quiet  # ECC dispatcher
Test-NetConnection <S/4 public IP>      -Port 3300 -InformationLevel Quiet  # S/4 dispatcher
```

Both should print `True`.

## Step 4 — Smoke test (extract from ECC, write CSV to S3)

The `data-migrator` Lambda is extract-only by default — it reads rows from ECC
over RFC and writes a Migration-Cockpit-shaped CSV to S3. Actual S/4 push
happens via the lane orchestrator (`migration-cockpit-orchestrator`) OR by
setting `M4H_LOAD_TO_S4=1` on the data-migrator (see Step 5).

The payload uses an `object_spec` nested object — flat fields like
`object`/`max_rows` will fall through to batch mode and fail.

```powershell
$payload = @{
    run_id         = "cal-smoke-001"
    ecc_secret_id  = "migrate4hana/prod/sap-credentials"
    object_spec    = @{
        object        = "Customer"
        source_table  = "KNA1"
        fields        = @("KUNNR", "NAME1", "LAND1", "ORT01", "STRAS")
        lane          = "MC"
    }
} | ConvertTo-Json -Depth 4 -Compress
$payload | Out-File -Encoding ASCII payload.json

aws lambda invoke `
    --region us-east-1 `
    --function-name migrate4hana-data-migrator-prod `
    --cli-binary-format raw-in-base64-out `
    --payload file://payload.json `
    cal-smoke.json

Get-Content cal-smoke.json | ConvertFrom-Json | ConvertTo-Json -Depth 6
```

**Expected — happy path:**
```json
{
  "run_id":    "cal-smoke-001",
  "status":   "ok",
  "object":   "Customer",
  "lane":     "MC",
  "row_count": <N from IDES>,
  "artifacts": {
    "mc_csv": "s3://migrate4hana-staging-prod/runs/cal-smoke-001/data-migrator/Customer.csv"
  }
}
```

**If you see `RFC_COMMUNICATION_FAILURE / partner '...' not reached`:**
- The CAL ECC hostname doesn't match `vhcalerphci`. Check the CAL console for
  the real hostname, set `cal_ecc_hostname` in tfvars, `terraform apply`, and
  re-run the secret update script.

**If you see `RFC_LOGON_FAILURE`:**
- Wrong user/client/password. Default user `DEVELOPER` and client `800`
  is the IDES standard; override via `-EccUser` / `-EccClient`.

## Step 5 — Real end-to-end (when smoke passes)

Bump `max_rows` and flip `dry_run` to `$false`. Try Customer then Vendor then
Material to walk the object types Migrate4HANA already proves at scale:

```powershell
foreach ($obj in @("Customer", "Vendor", "Material")) {
    $payload = @{
        object         = $obj
        sap_source     = "ecc"
        sap_target     = "s4hana"
        max_rows       = 500
        dry_run        = $false
        correlation_id = "cal-e2e-$obj-001"
    } | ConvertTo-Json -Compress
    $payload | Out-File -Encoding ASCII payload.json

    Write-Host "`n==> Running $obj"
    aws lambda invoke --region us-east-1 `
        --function-name migrate4hana-data-migrator-prod `
        --cli-binary-format raw-in-base64-out `
        --payload file://payload.json `
        "cal-e2e-$obj.json" | Out-Null

    Get-Content "cal-e2e-$obj.json" | ConvertFrom-Json |
        Select-Object -Property object, extracted, transformed, loaded, errors |
        Format-List
}
```

After all three run clean, the loop is **proved end-to-end**: real ECC, real
RFC extraction, real transformation engine, real BAPI post to real S/4, real
audit-ledger entry. That's the demo/pitch milestone.

## Step 6 — Lock down (before any client demo)

Right now both SGs allow `0.0.0.0/0`. To tighten:

```powershell
# Get the NAT EIP
cd terraform\environments\prod
$natIp = (terraform output -raw nat_gateway_public_ip).Trim()
cd ..\..\..

# Update S/4 SG (already automated by update-s4-secret.ps1 if you re-run it)
# Update CAL ECC SG by re-running with -CalEccSecurityGroupId
.\scripts\update-cal-ecc-secret.ps1 `
    -CalEccPublicIp <CAL ECC public IP> `
    -CalEccSecurityGroupId sg-<your CAL ECC SG>
```

Then revoke the `0.0.0.0/0` rules in EC2 console → SGs → both CAL appliances.

## When CAL public IPs drift

SAP CAL public IPs change every time you stop/start the appliance. When that
happens:

```powershell
# 1) Update tfvars with new IPs
# 2) terraform apply           (updates Route 53 A records)
# 3) re-run update-s4-secret.ps1 + update-cal-ecc-secret.ps1
```

No Lambda redeploy needed — the secret is fetched per cold-start.

## Cleanup of the old bastion path

Once CAL end-to-end is working you don't need the bastion EC2 or the laptop
SSH tunnel:

```powershell
# Stop the bastion (preserves config, ~$3-4/mo for EIP + EBS)
$bastionId = aws ec2 describe-instances `
    --filters "Name=tag:Name,Values=migrate4hana-bastion-prod" `
    --query "Reservations[].Instances[].InstanceId" --output text
aws ec2 stop-instances --instance-ids $bastionId

# Or destroy it entirely:
# in terraform.tfvars set:  bastion_key_pair_name = ""
# then: terraform apply -auto-approve
```
