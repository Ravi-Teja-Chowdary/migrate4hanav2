# Migrate4HANA — Prerequisites Before First `terraform apply`

`terraform init && terraform apply` on this stack stands up the entire AWS platform on
its own. But two pieces **cannot be created by Terraform or any other tool** — they're
either licensed (SAP) or built from your codebase (a container image). This document
gives you the **exact commands** to produce each one, the first time, in 15–30 minutes.

| Prerequisite | Why Terraform can't make it | How long |
|---|---|---|
| **SAP NW RFC SDK pyrfc Lambda layer** | SDK is licensed; only downloadable with an SAP S-User | ~15 min |
| **Fargate worker container image** | Built from this repo + the SDK, then pushed to your ECR | ~10 min |

Everything else is created by `terraform apply`. Both of these only need to be done
**once per AWS account** (or whenever you upgrade the SDK / change the worker code).

---

## 1. SAP NW RFC SDK — download

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

## 2. Build & publish the **pyrfc Lambda layer**

This is what `pyrfc_layer_arn` in your `terraform.tfvars` will point to. Most of the
Lambda stages import `pyrfc` at startup; without the layer, they cold-start, fail
`import pyrfc`, and the Step Functions execution aborts.

### One-shot build (runs in Docker so the wheel + .so match the Lambda runtime)

Save as `layer-build/build_pyrfc_layer.sh` and run from the `layer-build/` directory
that contains the SAP SDK zip:

```bash
#!/usr/bin/env bash
set -euo pipefail
SDK_ZIP=$(ls nwrfc750P_*.zip | head -1)
[ -n "$SDK_ZIP" ] || { echo "no nwrfc750P_*.zip in $(pwd)"; exit 1; }

# Build the layer inside Amazon Linux 2023 so the compiled wheel matches Lambda
docker run --rm -v "$(pwd):/work" -w /work \
  public.ecr.aws/amazonlinux/amazonlinux:2023 bash -c '
    set -e
    dnf -y -q install python3.11 python3.11-pip python3.11-devel gcc gcc-c++ make unzip
    rm -rf build && mkdir -p build/python build/lib

    # 1. extract the SAP SDK
    unzip -q -o '"$SDK_ZIP"' -d /opt/sap
    if [ -d /opt/sap/nwrfcsdk ]; then cp -r /opt/sap/nwrfcsdk/* /opt/sap/; fi

    # 2. install pyrfc + its runtime deps, compiled against the SDK headers
    export SAPNWRFC_HOME=/opt/sap
    export LD_LIBRARY_PATH=/opt/sap/lib:$LD_LIBRARY_PATH
    python3.11 -m pip install --quiet --target build/python pyrfc

    # 3. the .so libs must live under the layer'\''s /opt/lib at runtime
    cp -r /opt/sap/lib/* build/lib/

    # 4. zip the layer (preserves layer/ -> /opt/ layout when Lambda mounts it)
    cd build && zip -qr ../pyrfc-layer.zip python lib
  '
echo "built: $(pwd)/pyrfc-layer.zip ($(du -h pyrfc-layer.zip | cut -f1))"
```

Make it executable and run it:

```bash
chmod +x layer-build/build_pyrfc_layer.sh
( cd layer-build && ./build_pyrfc_layer.sh )
```

You should end up with `layer-build/pyrfc-layer.zip` (~10–15 MB).

### Publish to AWS

```bash
REGION=us-east-1
LAYER_ARN=$(aws lambda publish-layer-version \
  --region $REGION \
  --layer-name pyrfc \
  --description "SAP NW RFC SDK 7.50 + pyrfc for python3.11" \
  --zip-file fileb://layer-build/pyrfc-layer.zip \
  --compatible-runtimes python3.11 \
  --compatible-architectures x86_64 \
  --query LayerVersionArn --output text)
echo "$LAYER_ARN"
```

Add the printed ARN to `terraform.tfvars` so every Lambda picks it up:

```hcl
pyrfc_layer_arn = "arn:aws:lambda:us-east-1:<acct>:layer:pyrfc:1"
```

Then `terraform apply` again — the previously-empty `layers = []` becomes
`layers = [<your-arn>]` and the SAP-touching Lambdas can `import pyrfc`.

### Verify

Test from a Lambda you've deployed:

```bash
aws lambda invoke --function-name migrate4hana-readiness-check-prod \
  --payload '{"mode":"healthcheck"}' /tmp/out.json && cat /tmp/out.json
```

If the response is no longer `"errorMessage": "Unable to import module..."`, the layer
is wired correctly.

---

## 3. Build & push the **Fargate worker image**

This is the container that the `ComputeDispatcher` (Pillar 1.1) launches whenever an
object's row estimate exceeds the Fargate threshold (default 20,000 rows). The image
bundles the SAP SDK + pyrfc + the whole `lambda/` directory + a unified entrypoint —
so any stage that doesn't fit in a Lambda's 15-min / 10 GB envelope runs here instead.

`ecs/Dockerfile` already exists in the repo (multi-stage Amazon Linux 2023 build). It
expects the SAP SDK zip at `ecs/nwrfc750P_*.zip`.

### Build (from the repo root)

```bash
# Build context MUST be the repo root so the Dockerfile can copy lambda/ into the image
docker build -f ecs/Dockerfile -t migrate4hana-worker:latest .
```

### Push to ECR

The Terraform stack creates the ECR repository on first apply; grab its URL from outputs.

```bash
cd terraform/environments/prod
REPO=$(terraform output -raw ecr_repository_url)        # e.g. <acct>.dkr.ecr.us-east-1.amazonaws.com/migrate4hana/worker
REGION=us-east-1

# log Docker into the ECR registry
aws ecr get-login-password --region $REGION | \
  docker login --username AWS --password-stdin "${REPO%/*}"

# tag + push
docker tag  migrate4hana-worker:latest "$REPO:latest"
docker push "$REPO:latest"
```

> **Apple Silicon (M1/M2) warning:** Docker defaults to `linux/arm64` on Macs. Fargate
> here is `linux/amd64`. Always add `--platform linux/amd64` to **both** the `build` and
> `push` commands — otherwise the task starts but fails with `exec format error`.
> Example: `docker build --platform linux/amd64 -f ecs/Dockerfile -t migrate4hana-worker:latest .`

### Re-apply so the task definition pins to your image digest (optional but recommended)

```bash
cd terraform/environments/prod
terraform apply
```

### Verify

```bash
# task definition is registered and the image points at your push
aws ecs describe-task-definition --task-definition $(terraform output -raw ecs_task_definition_family) \
  --query 'taskDefinition.containerDefinitions[0].image'

# fire a one-off test run
aws ecs run-task \
  --cluster $(terraform output -raw ecs_cluster_arn | awk -F/ '{print $NF}') \
  --launch-type FARGATE \
  --task-definition $(terraform output -raw ecs_task_definition_family) \
  --network-configuration "awsvpcConfiguration={subnets=[<subnet-id>],securityGroups=[<sg-id>],assignPublicIp=DISABLED}" \
  --overrides '{"containerOverrides":[{"name":"migrate4hana","environment":[{"name":"M4H_TASK_PAYLOAD","value":"{\"stage\":\"healthcheck\"}"}]}]}'
```

CloudWatch Logs under `/ecs/migrate4hana-worker` should show the entrypoint running.

---

## 4. Drop both into `terraform.tfvars` and apply

After both prerequisites are done once, your `terraform.tfvars` looks like this and
**every subsequent `terraform apply` is one command**:

```hcl
aws_region      = "us-east-1"
alert_email     = "migrations@yourcorp.com"
pyrfc_layer_arn = "arn:aws:lambda:us-east-1:<acct>:layer:pyrfc:1"
# Fargate image is read from the ECR repo this stack creates;
# `terraform apply` after `docker push` is all that's needed.
```

`terraform destroy` tears everything down (subject to the WORM Object-Lock caveat in
`DEPLOY.md`). The ECR repo + the Lambda layer are independent of the stack — `destroy`
removes the ECR repo (so you'd re-push) but the layer survives (Lambda layers are
account-scoped, not stack-scoped); re-applying the stack with the same layer ARN
re-wires it instantly.

---

## 5. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Lambda: `Unable to import module: pyrfc` | layer not attached or arch mismatch | re-publish layer with `--compatible-architectures x86_64`; confirm `pyrfc_layer_arn` is set + re-apply |
| Lambda: `libsapnwrfc.so: cannot open shared object file` | SDK `.so` not on the loader path | layer zip must include `lib/` at the top (Lambda mounts it as `/opt/lib`, which is on `LD_LIBRARY_PATH` automatically) — re-run the build script |
| Fargate: `exec format error` | image built for arm64, Fargate task is amd64 | rebuild with `docker build --platform linux/amd64 ...` |
| `docker push` → `denied: requested access to the resource is denied` | not logged into ECR or wrong region | re-run the `aws ecr get-login-password ... \| docker login ...` step with the correct `--region` |
| `terraform apply` says ECR repo already has an image but the task still fails | task def caches the previous digest | force redeploy: `aws ecs update-service ... --force-new-deployment` (n/a here since we use `run-task`, but for any service version of this) — or re-`apply` after the push |
| SAP-side: `RFC error PARTNER NOT REACHED` / `WSAETIMEDOUT` | network path / IPs / hosts file — *not* a prereq problem | see `~/.claude/.../memory/connectivity-quirks.md` — the most-burned-on connectivity gotcha |

That's it. Once §1 and §2 are done once, **every future deploy is `cd terraform/environments/prod && terraform apply`**.
