# Battletest HOWTO — Run on Your Deployed AWS Stack

*One-page runbook. Runs the comprehensive proof run on AWS (Fargate cluster
on your deployed prod stack). Produces `BATTLETEST_RESULTS.md` — the artefact
you cite in the pitch deck.*

---

## What this proves

The battletest is **one comprehensive proof run** that exercises every stage
of Migrate4HANA at real-customer-class volume, **on the AWS infrastructure
you've actually deployed** (not locally).

| Dimension | `large` scale |
|---|---|
| Customers | 1,000,000 |
| Vendors | 500,000 |
| Materials | 2,000,000 |
| GL Accounts | 5,000 |
| FI Headers (BKPF) | 500,000 |
| FI Lines (BSEG) | ~2,000,000 |
| **Total records** | **~5,500,000** |
| Custom Z-programs | 100 (configurable) |
| Where the work runs | **AWS Fargate task on your prod cluster** |
| Where results land | **S3 staging bucket + local `BATTLETEST_RESULTS.md`** |

What's exercised:
- Real AWS infrastructure (Fargate, S3, DynamoDB, KMS, CloudWatch)
- All gap closures (CVI two-phase, DAG, WorkloadThrottle, cluster-awareness,
  hash chain at scale, cutover_verdict precedence)
- All transformation + DQ + BAPI coverage logic
- Code remediation pipeline (deterministic AST + Claude fallback)

What's NOT in scope (separate POC engagement):
- Real ECC connectivity (still needs VPN to your network)
- Real S/4 BAPIs (load goes to in-process mock target; the 5K real-load
  sample to CAL is a separate demo step)

---

## The 3 commands

```powershell
# 1. Deploy AWS infrastructure (one-time per environment)
cd terraform\environments\prod
terraform apply -auto-approve

# 2. Push the Fargate worker image (rebuilds when battletest code changes)
cd ..\..\..
.\scripts\push-fargate-image.ps1

# 3. RUN THE BATTLETEST  ◄── this is the one you run after every code change
.\scripts\run-battletest-aws.ps1 -Scale large -IncludeCodeRemediation
```

That's it. The script does everything — generate fixtures locally, upload
to S3, trigger the Fargate task, poll for completion, download results,
regenerate `BATTLETEST_RESULTS.md`.

---

## Scale options

| Scale | Total records | Approx wall time (Fargate) | Cost estimate |
|---|---|---|---|
| `tiny` | ~750 | ~1 min | ~$0.05 |
| `small` | ~55,000 | ~5 min | ~$0.50 |
| `medium` | ~550,000 | ~15-25 min | ~$3 |
| `large` | ~5,500,000 | ~45-90 min | ~$10-20 |
| `xlarge` | ~55,000,000 | ~6-10 hours (overnight) | ~$60-150 |

Recommended sequence the first time:
1. `tiny` to verify the AWS plumbing works end-to-end (~1 min, ~$0.05)
2. `small` to validate timing + log shape (~5 min, ~$0.50)
3. `large` for the real proof you'll cite (~1 hour, ~$15)

---

## What happens behind the scenes

```
Your laptop                              AWS (your deployed prod stack)
─────────────                            ────────────────────────────────
 1. Generate fixtures locally
    (generator.py → JSONL.gz files)
                          ┌─────────────►  S3 staging bucket
 2. aws s3 sync           │                migrate4hana-staging-prod-<acct>/
                          │                  battletest/scale-<scale>/
                                              ├── customers.jsonl.gz
                                              ├── vendors.jsonl.gz
                                              ├── materials.jsonl.gz
                                              ├── gl_accounts.jsonl.gz
                                              ├── bkpf.jsonl.gz
                                              └── bseg.jsonl.gz

 3. aws ecs run-task ────────────────────►  Fargate task
                                              ├── entrypoint.py sees M4H_MODE=battletest
                                              ├── downloads fixtures from S3
                                              ├── runs orchestrator.py:
                                              │     extract → transform → coverage
                                              │     → load (mock target, in-process)
                                              │     → hash chain → gap-closure stress
                                              │     → code remediation
                                              │     → cutover_verdict
                                              └── uploads results JSON to S3
                                                  battletest/results/battletest-<scale>-aws-<ts>.json

 4. Poll for STOPPED ◄───── status ──────  ECS task lifecycle
 5. aws s3 cp        ◄───── results ──────  S3 results prefix
 6. python generate_report.py
    → BATTLETEST_RESULTS.md  ← cite in pitch deck
```

---

## Reading the results

Open `BATTLETEST_RESULTS.md` and look for:

| Section | What to verify |
|---|---|
| **Summary** | `cutover_verdict = GO`, `hash chain verifies = true`, total elapsed reasonable |
| **Per-stage detail** | `errors = 0` on every stage |
| **Gap closure stress** | `CVI cycles_detected > 0`, `cluster awareness all_match = true`, `cutover_verdict_precedence all_correct = true` |
| **Code remediation** | `ai_fallback_invoked` non-zero (proves the AI path was exercised) |
| **Mock target stats** | `created` count matches expectation, `nriv_busy > 0` at large scale (proves throttle backoff) |

If `cutover_verdict != GO`, read the `reasons` array — it names exactly which
precedence rule fired.

---

## Pitch-deck wiring

`PITCH_DECK.md` already has a **Slide 8.5 — Battle-tested at scale** that
cites this report. After every run:

1. Open `BATTLETEST_RESULTS.md`
2. Note the headline metrics (total records, elapsed, throughput, issues)
3. If the numbers improved (e.g. you ran at a larger scale), copy them into
   slide 8.5

---

## Cost guard

The launcher script doesn't auto-tear-down the stack. After running:

```powershell
# Verify nothing else is using the cluster
aws ecs list-tasks --cluster migrate4hana-prod --region us-east-1

# If you're not actively demoing, tear it all down to stop the AWS clock
cd terraform\environments\prod
terraform destroy -auto-approve
```

Idle stack cost is ~$60-100/month. A single full-large battletest run is
~$15. So if you're not demoing for >2 weeks, destroy + redeploy is cheaper.

---

## When something goes wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| `terraform apply` not run | prod stack not deployed | `cd terraform\environments\prod && terraform apply -auto-approve` |
| `ECR image not found` | Fargate image not pushed | `.\scripts\push-fargate-image.ps1` |
| `Cluster not ACTIVE` | terraform apply incomplete | check terraform output, re-apply if needed |
| `Task launched but immediately stopped` | likely a Docker image issue | check CloudWatch logs at `/ecs/migrate4hana-prod-worker` for the task ID |
| `Pyrfc import error` | layer not in the image | rebuild + push image |
| Task takes much longer than expected | smaller Fargate task tier than expected | check task definition CPU/memory in terraform |
| Results not appearing in S3 | task crashed mid-run | check CloudWatch logs; the launcher already auto-prints the last 50 lines |
| `BATTLETEST_RESULTS.md` shows old run as headline | new results haven't synced | re-run step 6 manually: `aws s3 sync s3://<bucket>/battletest/results/ tests/battletest/results/ && python tests/battletest/generate_report.py` |

---

## Manual mode (advanced)

If you want to drive the steps manually instead of using
`run-battletest-aws.ps1`:

```powershell
# 1. Generate locally
python tests\battletest\generator.py --scale large
python tests\battletest\abap_generator.py --count 100

# 2. Upload
aws s3 sync tests\battletest\fixtures\scale-large s3://<bucket>/battletest/scale-large/
aws s3 sync tests\battletest\abap-suite           s3://<bucket>/battletest/abap-suite/

# 3. Trigger Fargate
aws ecs run-task --cluster migrate4hana-prod --task-definition migrate4hana-prod-worker `
  --launch-type FARGATE --count 1 `
  --network-configuration '{...}' `
  --overrides '{"containerOverrides":[{"name":"worker","environment":[
    {"name":"M4H_MODE","value":"battletest"},
    {"name":"M4H_BATTLETEST_SCALE","value":"large"},
    {"name":"M4H_BATTLETEST_S3_BUCKET","value":"<bucket>"},
    {"name":"M4H_BATTLETEST_S3_FIXTURES_PREFIX","value":"battletest/scale-large/"},
    {"name":"M4H_BATTLETEST_S3_RESULTS_PREFIX","value":"battletest/results/"},
    {"name":"M4H_BATTLETEST_THREADS","value":"16"},
    {"name":"M4H_BATTLETEST_CODE_REM","value":"1"}]}]}'

# 4. Download results + generate report
aws s3 sync s3://<bucket>/battletest/results/ tests\battletest\results\ --exclude "*" --include "*aws*.json"
python tests\battletest\generate_report.py
```

---

*Local-only mode (`python tests\battletest\orchestrator.py --scale <s>`) still
works for quick smoke tests during development — see `tests/battletest/README.md`.
But for the showcase pitch artefact, use the AWS run.*
