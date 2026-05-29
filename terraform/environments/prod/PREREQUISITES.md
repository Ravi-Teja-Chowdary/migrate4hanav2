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

```bash
# from the repo root
python layer-build/build_pyrfc_layer.py
# -> layer-build/pyrfc-layer.zip  (~15 MB)

cd terraform/environments/prod
terraform apply
# Terraform sees the zip, publishes it as aws_lambda_layer_version.pyrfc,
# and every SAP-touching Lambda gets it as their `layers` automatically.
```

That's it. Pin a specific pyrfc version with `M4H_PYRFC_VERSION=3.3.1
python layer-build/build_pyrfc_layer.py` if you need it. Re-run the script + apply
whenever you want a fresh wheel.

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

## 2. Build & push the **Fargate worker image** (required for heavy stages)

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
| `docker push` → `denied: requested access to the resource is denied` | not logged into ECR or wrong region | re-run the `aws ecr get-login-password ... \| docker login ...` step with the correct `--region` |
| `terraform apply` says ECR repo already has an image but the task still fails | task def caches the previous digest | force redeploy: `aws ecs update-service ... --force-new-deployment` (n/a here since we use `run-task`, but for any service version of this) — or re-`apply` after the push |
| SAP-side: `RFC error PARTNER NOT REACHED` / `WSAETIMEDOUT` | network path / IPs / hosts file — *not* a prereq problem | see `~/.claude/.../memory/connectivity-quirks.md` — the most-burned-on connectivity gotcha |

That's it. Once §1 and §2 are done once, **every future deploy is `cd terraform/environments/prod && terraform apply`**.
