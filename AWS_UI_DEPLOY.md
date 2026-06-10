# AWS UI Deployment Guide

Deploy the Migrate4HANA customer-facing UI + api-server to your AWS account
so anyone can reach it from a browser.

---

## What you get

A single HTTPS URL — for example `https://d1xxxxxxxxxxxx.cloudfront.net` —
that serves:

- The React UI you've been running locally
- All `/api/*` endpoints (live, calling AWS Lambdas / SFN / Secrets / S3 / DynamoDB)
- PDF download endpoints
- Script-runner endpoints
- Connection management forms

## Architecture

```
              Customer browser
                    │
                    │  HTTPS
                    ▼
        ┌─────────────────────────┐
        │  CloudFront distribution│
        │  (xxx.cloudfront.net)   │
        └──────────┬──────────────┘
             /  /api/*  \
            /            \
           ▼              ▼
   ┌──────────────┐   ┌──────────────────┐
   │   S3 bucket  │   │  Application LB  │
   │ (React dist) │   │  (HTTP listener) │
   └──────────────┘   └────────┬─────────┘
                               │
                               ▼ port 8000
                      ┌─────────────────┐
                      │  Fargate task   │
                      │  api_server.py  │
                      │  + SAP NW RFC   │
                      └────────┬────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
  AWS Lambdas /            Secrets Manager        S3 + DynamoDB
  Step Functions
```

## Cost estimate

| Service        | Configuration | Monthly cost (idle) | Monthly cost (active) |
|----------------|---------------|---------------------|-----------------------|
| Fargate        | 1 vCPU / 2 GB / 1 task | ~$30 | ~$30 |
| ALB            | 1 ALB         | ~$18 | ~$18 |
| CloudFront     | PriceClass 100| ~$0 (1 TB free) | ~$5-20 |
| S3             | UI bucket     | ~$0.10 | ~$0.10 |
| ECR            | 2 images stored | ~$0.20 | ~$0.20 |
| CloudWatch logs| 30-day retention | ~$1-3 | ~$5-10 |
| **Total**      |               | **~$50/month** | **~$60-80/month** |

(Plus any data transfer; usually negligible for a dashboard.)

## Prerequisites

1. **AWS CLI configured** for the target account (`aws configure` or `AWS_PROFILE` env var)
2. **Docker Desktop** running (the Fargate image is built locally before push)
3. **Terraform 1.5+**
4. **Node.js 18+** + **npm**
5. **PowerShell 7+** (`pwsh`)
6. Existing `terraform/environments/prod` already applied (you have this; the
   new ui/api modules slot in alongside)

## One-command deploy

From the repo root:

```powershell
pwsh scripts/deploy-ui-aws.ps1
```

This does, in order:

1. `terraform apply -target=module.api_server -target=module.ui_hosting`
   (creates ECR repo, Fargate cluster wiring, ALB, S3 bucket, CloudFront)
2. `docker build -f Dockerfile.api-server -t migrate4hana-api-server .`
3. `aws ecr get-login-password | docker login` + `docker push`
4. `aws ecs update-service --force-new-deployment` (rolls Fargate onto the new image)
5. `cd frontend && npm install && npm run build`
6. `aws s3 sync frontend/dist/ s3://<bucket>` (sets cache headers correctly)
7. `aws cloudfront create-invalidation` (so users see the new code immediately)
8. Prints the live URL

First deploy takes ~10-15 minutes (mostly waiting on CloudFront propagation +
the first Fargate task pulling the image). Subsequent deploys are ~3-5 min.

## Incremental redeploys

Faster paths when you've only changed one layer:

```powershell
# Changed React code only (skip terraform + docker build)
pwsh scripts/deploy-ui-aws.ps1 -SkipTerraform -SkipApi

# Changed api_server.py only (skip UI build)
pwsh scripts/deploy-ui-aws.ps1 -SkipTerraform -SkipUi
```

## Custom domain (optional)

By default the UI uses CloudFront's built-in `*.cloudfront.net` URL (HTTPS via
the AWS-managed cert, no DNS work needed).

To use a custom domain like `https://migrate4hana.yourdomain.com`:

1. Request an ACM cert **in us-east-1** (CloudFront requires this region):

   ```powershell
   aws acm request-certificate `
     --domain-name migrate4hana.yourdomain.com `
     --validation-method DNS `
     --region us-east-1
   ```

2. Validate it (add the CNAME ACM gives you to your DNS).

3. Set the two new tfvars in `terraform/environments/prod/terraform.tfvars`:

   ```hcl
   ui_custom_domain          = "migrate4hana.yourdomain.com"
   ui_acm_cert_arn_us_east_1 = "arn:aws:acm:us-east-1:905418407458:certificate/abc-..."
   ```

4. Re-run `pwsh scripts/deploy-ui-aws.ps1`.

5. Point your DNS CNAME at the CloudFront domain (terraform output `ui_url`).

## What gets deployed

| Resource | Where defined |
|----------|---------------|
| `Dockerfile.api-server` | repo root — Python 3.11 + SAP NW RFC SDK + pyrfc + FastAPI |
| `terraform/modules/api-server/main.tf` | ECR repo, IAM roles, ALB, target group, Fargate task def, ECS service, security groups, CloudWatch log group |
| `terraform/modules/ui-hosting/main.tf` | S3 bucket (private, OAC), CloudFront distribution (two behaviors: /api/* → ALB, /* → S3), bucket policy |
| `terraform/environments/prod/main.tf` | New `module "api_server"` and `module "ui_hosting"` blocks + outputs |
| `terraform/environments/prod/variables.tf` | New `ui_custom_domain` + `ui_acm_cert_arn_us_east_1` vars (both optional) |
| `scripts/deploy-ui-aws.ps1` | One-command deploy + incremental flags |

## Important: ECC + S/4HANA connectivity

The api-server runs inside your VPC. For it to actually talk to ECC and
S/4HANA from AWS, you need network reach:

- **ECC** — accessed via the same ngrok TCP bridge the data-migrator Lambda
  uses (see your `ngrok local ECC bridge` memory). When the bridge is up,
  the Fargate task can pyrfc-call ECC just like the Lambda does.
- **S/4HANA** — accessed via the Route 53 private zone you've already wired
  for the Lambdas. Same hostname (`vhcalabaci`) resolves.

If those bridges are down, the UI still loads, you can still navigate, but
"Test connection" buttons will fail with the same error the Lambda would.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `docker login` fails | AWS CLI not configured | `aws configure` |
| `terraform apply` errors on ALB | Public subnets missing | Verify `module.vpc.public_subnet_ids` populated |
| 503 from ALB | Fargate task not healthy | Check CloudWatch logs at `/migrate4hana/api-server/prod` |
| UI loads but `/api/*` fails | CloudFront caching old API errors | Force-refresh (Ctrl+F5) or wait for invalidation |
| `Test ECC connection` fails | ngrok bridge down | Start the bridge per `connectivity-quirks` runbook |
| New code not showing | Browser cache | Hard refresh (Ctrl+F5) — index.html is `no-cache` but service workers can stick |

## Watching logs

```powershell
# api-server logs (live tail)
aws logs tail /migrate4hana/api-server/prod --follow

# Or just the last 5 minutes
aws logs tail /migrate4hana/api-server/prod --since 5m
```

## Tearing it down

```powershell
cd terraform/environments/prod
terraform destroy -target=module.ui_hosting -target=module.api_server
```

CloudFront takes ~15 min to fully delete (AWS waits for global edge cache
to expire). The S3 bucket and ECR repo are destroyed in parallel.

---

*See also: `EXPERT_REVIEW_DETAILED.md` for the rest of the AWS architecture,
`PRESENTATION_GUIDE.md` for the client-facing UI walkthrough.*
