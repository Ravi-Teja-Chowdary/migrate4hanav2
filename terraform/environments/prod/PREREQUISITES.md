# Migrate4HANA — Prerequisites Before First `terraform apply`

`terraform init && terraform apply` on this stack stands up the entire AWS platform on
its own. Two pieces are produced outside Terraform — but for **testing** the platform
end-to-end, you can use the **SAP NW RFC SDK already committed in this repo** under
`nwrfcsdk-linux/`, so you don't need an SAP S-User to start. The container image still
needs to be built + pushed once.

| Prerequisite | Fast path (testing) | Production-grade path |
|---|---|---|
| **pyrfc Lambda layer** | use the in-repo `nwrfcsdk-linux/` — one command — §1 | download fresh SDK with S-User — §3 |
| **Fargate worker image** | build + push from this repo — §2 | same — §2 |

> **Reality check on the in-repo SDK.** It's the real SAP NW RFC SDK 7.50 Linux x86_64
> binaries. For a **testing / non-production** account it's fine; for a customer-facing
> production run, switch to your own SAP-Support-portal-downloaded SDK (§3) so the
> license trail is unambiguous. Either way the layer build is the same shape.

---

## 1. Fast path — build the pyrfc layer from the in-repo SDK

The repository already contains `nwrfcsdk-linux/lib/*.so` (libsapnwrfc, libsapucum,
ICU libraries). The build script bundles those with a manylinux pyrfc wheel from PyPI
into `layer-build/pyrfc-layer.zip`, and **Terraform auto-detects + publishes it on
the next `terraform apply`** — no manual `pyrfc_layer_arn` tfvar required for testing.

```powershell
# from the repo root (PowerShell)
python layer-build\build_pyrfc_layer.py
# -> layer-build\pyrfc-layer.zip  (~15 MB)

cd terraform\environments\prod
terraform apply
# Terraform sees the zip, publishes it as aws_lambda_layer_version.pyrfc,
# and every SAP-touching Lambda gets it as their `layers` automatically.
```

That's it. Pin a specific pyrfc version when needed:

```powershell
$env:M4H_PYRFC_VERSION = "3.3.1"
python layer-build\build_pyrfc_layer.py
```

Re-run the script + apply whenever you want a fresh wheel.

**What this avoids vs. the production path:** no SAP S-User, no Docker, no manual
`aws lambda publish-layer-version`. The local Python on your machine only has to be
≥3.7 (we use it purely to drive `pip download` — the wheel itself is cp311 manylinux
to match the Lambda runtime).

---

## 3. Production-grade — download a fresh SDK from SAP (skip if you ran §1)

### What you need
- An **SAP S-User** (your company's SAP support account on `support.sap.com`).
- ~50 MB disk space.

### Where to get it
1. Sign in to **<https://support.sap.com/swdc>** (Software Downloads).
2. Top search → **"SAP NW RFC SDK 7.50"**.
3. Pick **Linux on x86_64 64bit** (this is what AWS Lambda + Fargate need).
   The file is named something like:
   ```
   nwrfc750P_<patch>-70002752.zip      (~12 MB)
   ```
   The exact patch number changes; the latest 7.50 SDK is fine.
4. Download → place the zip in **two locations** of this repo:
   ```
   ecs/nwrfc750P_<patch>-70002752.zip                 # used by the Fargate image build
   layer-build/nwrfc750P_<patch>-70002752.zip         # used by the Lambda-layer build (create this dir)
   ```

> **arm64 note:** the Lambda module defaults to `x86_64`. If you switch any function to
> `arm64`, also download the `linuxarm64` SDK variant and build a matching arm64 layer.

---

## 4. Production-grade — build & publish the layer with Docker (skip if you ran §1)

This is what `pyrfc_layer_arn` in your `terraform.tfvars` will point to. Most of the
Lambda stages import `pyrfc` at startup; without the layer, they cold-start, fail
`import pyrfc`, and the Step Functions execution aborts.

### One-shot build (runs in Docker so the wheel + .so match the Lambda runtime)

Use the committed PowerShell builder. Drop your SAP-downloaded `nwrfc750P_*.zip`
into `layer-build/`, then:

```powershell
cd layer-build
# (one-time, if execution policy blocks unsigned scripts)
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\build_pyrfc_layer.ps1
```

You should end up with `layer-build\pyrfc-layer.zip` (~10–15 MB). The script
mounts the cwd into an `amazonlinux:2023` container, installs python3.11 +
the build tooling, extracts the SDK, `pip install`s pyrfc against it, copies
the SDK `.so` files into the layer's `lib/`, and zips it. See
`layer-build\build_pyrfc_layer.ps1` for the full source.

### Publish to AWS

```powershell
$REGION = "us-east-1"
$LAYER_ARN = aws lambda publish-layer-version `
  --region $REGION `
  --layer-name pyrfc `
  --description "SAP NW RFC SDK 7.50 + pyrfc for python3.11" `
  --zip-file fileb://layer-build/pyrfc-layer.zip `
  --compatible-runtimes python3.11 `
  --compatible-architectures x86_64 `
  --query LayerVersionArn --output text
$LAYER_ARN
```

Add the printed ARN to `terraform.tfvars` so every Lambda picks it up:

```hcl
pyrfc_layer_arn = "arn:aws:lambda:us-east-1:<acct>:layer:pyrfc:1"
```

Then `terraform apply` again — the previously-empty `layers = []` becomes
`layers = [<your-arn>]` and the SAP-touching Lambdas can `import pyrfc`.

### Verify

Test from a Lambda you've deployed:

```powershell
aws lambda invoke --function-name migrate4hana-readiness-check-prod `
  --payload '{\"mode\":\"healthcheck\"}' $env:TEMP\out.json
Get-Content $env:TEMP\out.json
```

If the response is no longer `"errorMessage": "Unable to import module..."`, the layer
is wired correctly.

---

## 2. Build & push the **Fargate worker image** (required for heavy stages)

This is the container that the `ComputeDispatcher` (Pillar 1.1) launches whenever an
object's row estimate exceeds the Fargate threshold (default 20,000 rows). The image
bundles the SAP SDK + pyrfc + the whole `lambda/` directory + a unified entrypoint —
so any stage that doesn't fit in a Lambda's 15-min / 10 GB envelope runs here instead.

`ecs/Dockerfile` already exists in the repo (multi-stage Amazon Linux 2023 build). It
expects the SAP SDK zip at `ecs/nwrfc750P_*.zip`.

### Build (from the repo root, PowerShell)

```powershell
# Build context MUST be the repo root so the Dockerfile can copy lambda\ into the image
docker build -f ecs\Dockerfile -t migrate4hana-worker:latest .
```

### Push to ECR

The Terraform stack creates the ECR repository on first apply; grab its URL from outputs.

```powershell
cd terraform\environments\prod
$REPO     = terraform output -raw ecr_repository_url   # e.g. <acct>.dkr.ecr.us-east-1.amazonaws.com/migrate4hana/worker
$REGION   = "us-east-1"
$Registry = $REPO.Substring(0, $REPO.LastIndexOf('/'))  # strip "/migrate4hana/worker" -> registry host

# log Docker into the ECR registry
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $Registry

# tag + push
docker tag  migrate4hana-worker:latest "${REPO}:latest"
docker push "${REPO}:latest"
```

> **Apple Silicon (M1/M2) note:** Mac users only. Docker on Apple Silicon defaults to
> `linux/arm64` and Fargate here is `linux/amd64`; add `--platform linux/amd64` to
> the `build` command. Windows + Intel Macs already build `linux/amd64` by default.

### Re-apply so the task definition pins to your image digest (optional but recommended)

```powershell
cd terraform\environments\prod
terraform apply
```

### Verify

```powershell
# task definition is registered and the image points at your push
$TaskFamily = terraform output -raw ecs_task_definition_family
aws ecs describe-task-definition --task-definition $TaskFamily `
  --query 'taskDefinition.containerDefinitions[0].image'

# fire a one-off test run (fill in <subnet-id> + <sg-id> from your stack outputs)
$Cluster = (terraform output -raw ecs_cluster_arn).Split('/')[-1]
$Net     = 'awsvpcConfiguration={subnets=[<subnet-id>],securityGroups=[<sg-id>],assignPublicIp=DISABLED}'
$Over    = '{"containerOverrides":[{"name":"migrate4hana","environment":[{"name":"M4H_TASK_PAYLOAD","value":"{\"stage\":\"healthcheck\"}"}]}]}'
aws ecs run-task --cluster $Cluster --launch-type FARGATE `
  --task-definition $TaskFamily --network-configuration $Net --overrides $Over
```

CloudWatch Logs under `/ecs/migrate4hana-worker` should show the entrypoint running.

---

## 5. Drop everything into `terraform.tfvars` and apply

After §1 (or §3-§4) + §2 are done once, your `terraform.tfvars` looks like this and
**every subsequent `terraform apply` is one command**:

```hcl
aws_region  = "us-east-1"
alert_email = "migrations@yourcorp.com"
# Fast path (§1): layer auto-published from layer-build/pyrfc-layer.zip — no tfvar needed.
# Production-grade path (§3-§4): uncomment and set the ARN from `publish-layer-version`.
# pyrfc_layer_arn = "arn:aws:lambda:us-east-1:<acct>:layer:pyrfc:1"
# Fargate image is read from the ECR repo this stack creates;
# `terraform apply` after `docker push` is all that's needed.
```

`terraform destroy` tears everything down (subject to the WORM Object-Lock caveat in
`DEPLOY.md`). The ECR repo + the Lambda layer are independent of the stack — `destroy`
removes the ECR repo (so you'd re-push) but the layer survives (Lambda layers are
account-scoped, not stack-scoped); re-applying the stack with the same layer ARN
re-wires it instantly.

---

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `terraform apply` doesn't publish a Lambda layer | `layer-build/pyrfc-layer.zip` is missing | re-run `python layer-build/build_pyrfc_layer.py` from the repo root and re-apply |
| Lambda: `Unable to import module: pyrfc` | layer not attached or arch mismatch | confirm the zip exists (fast path) OR re-publish with `--compatible-architectures x86_64` and set `pyrfc_layer_arn` (production path); re-apply |
| Lambda: `libsapnwrfc.so: cannot open shared object file` | SDK `.so` not on the loader path | layer zip must include `lib/` at the top (Lambda mounts it as `/opt/lib`, which is on `LD_LIBRARY_PATH` automatically) — re-run the build script |
| Fargate: `exec format error` | image built for arm64, Fargate task is amd64 | rebuild with `docker build --platform linux/amd64 ...` |
| `docker push` -> `denied: requested access to the resource is denied` | not logged into ECR or wrong region | re-run the `aws ecr get-login-password ... \| docker login ...` step with the correct `--region` |
| PowerShell: `.\build_pyrfc_layer.ps1 : cannot be loaded because running scripts is disabled` | execution policy | one-shot: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force` then re-run; or `powershell -ExecutionPolicy Bypass -File .\build_pyrfc_layer.ps1` |
| `terraform apply` says ECR repo already has an image but the task still fails | task def caches the previous digest | force redeploy: `aws ecs update-service ... --force-new-deployment` (n/a here since we use `run-task`, but for any service version of this) — or re-`apply` after the push |
| SAP-side: `RFC error PARTNER NOT REACHED` / `WSAETIMEDOUT` | network path / IPs / hosts file — *not* a prereq problem | see `~/.claude/.../memory/connectivity-quirks.md` — the most-burned-on connectivity gotcha |

That's it. Once §1 and §2 are done once, **every future deploy is**:

```powershell
cd terraform\environments\prod
terraform apply
```
