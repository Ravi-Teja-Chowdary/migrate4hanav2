# What is Migrate4HANA? (Plain English Edition)

*This document is written for two people: **you** (the solo founder), so you
have the vocabulary to talk about your own tool; and **a curious client or
investor** who has never heard of SAP and wants to understand what you've
built and why it matters.*

*Read time: 10 minutes. No SAP jargon for the first half.*

---

## Part 1 — The plain-English version (no SAP)

### What problem do enterprises have?

Imagine a Fortune 500 company. They've been using the same accounting,
inventory, sales, and HR software for the last 20 years. That software runs
their **entire business** — every invoice, every shipment, every paycheque.
It's so deeply embedded that "the software" basically *is* the company.

That software was sold to them by a German company called **SAP**. It's
called **SAP ECC** (ECC stands for ERP Central Component). Tens of thousands
of large companies run on SAP ECC.

### The problem

SAP told its customers: **"We will stop supporting ECC after 2027."** (It was
2025, then 2027, soon it'll likely slide again — but the cliff is real.)

If you don't move off ECC by then, you get no security patches, no bug fixes,
no help. Your business runs on un-supported software. Auditors freak out.
Insurance freaks out. Boards freak out.

So **every** SAP customer in the world has to migrate to the new product
called **SAP S/4HANA** — a modernised version of ECC. Same idea, but
re-architected for the cloud and for in-memory databases.

### Why is this hard?

Because the data inside ECC is **enormous and intricate**:

- **Millions of records** per company (every invoice ever issued, every
  shipment, every employee, every product).
- **Customised over 20 years** — every company has bolted on their own
  fields, their own rules, their own special-case logic.
- **Highly interconnected** — you can't move "the customer list" without
  also moving "the orders that point at those customers" without also
  moving "the products in those orders" without also moving "the
  warehouses where those products live."
- **Auditable to the penny** — for any company over a certain size,
  this is regulated by SOX (Sarbanes-Oxley) and similar laws. Every record
  that moves must be **proven** to have arrived correctly. If the
  migration loses 3 cents, the auditor wants to know which 3 cents and why.

### How does this normally get done?

Today, an SAP migration project for a mid-size company is:
- **18-36 months** of work.
- **$5M-$50M** in consultant fees.
- **20-100 people** on the project (data engineers, SAP functional
  consultants, business analysts, project managers, auditors).
- **High risk** — the project often slips, goes over budget, or has data
  problems that aren't caught until after go-live.

There are three main competitors in this space:
- **SmartShift** — focuses on automatically fixing the customer's custom
  code so it runs on the new system.
- **Syniti** — focuses on data quality, mapping legacy values to new ones,
  and providing dashboards for business users.
- **Natuvion** — focuses on "carve-outs" (migrating just one business unit
  or one year of data).

All three are mature, well-funded, and have customer references.

### What did you build?

**Migrate4HANA is a cloud-native (AWS) migration framework that does the
parts of the job that should be automated — and gives you a verifiable audit
trail that auditors can sign off on.**

The big idea: instead of doing migration as a 30-person manual project,
treat it as a **deployable pipeline** that you can run, fail, fix, and
re-run safely. Like modern software deployment — but for SAP data.

Specifically, your tool does:

1. **Auto-discovery** — when it connects to a target system, it figures
   out the configuration automatically (what company codes exist, what
   currency they use, what number ranges are in play). The big tools
   require humans to fill all of this in by hand.

2. **Idempotent loading** — if the migration crashes halfway through, you
   can re-run it and it picks up exactly where it left off. No duplicate
   records, no half-loaded mess. Most tools can't do this.

3. **Cryptographic audit chain** — every record loaded gets sealed into a
   tamper-evident chain (the same crypto principle as a blockchain).
   Auditors can verify after the fact that nothing was changed.

4. **Native SAP report capture** — at the end of a migration, your tool
   automatically pulls the standard SAP balance reports (FAGLB03 for the
   general ledger, MB5B for inventory) and seals their cryptographic
   signature into the audit chain. **This is the artefact a Big-4 auditor
   actually wants.**

5. **Cutover safety gate** — your tool has a hard rule: if the SAP
   standard balance report shows even one cent of variance from the source
   system, the migration is **NO_GO**, regardless of what the tool's own
   internal reconciliation says. The tool ledger can confirm a GO but
   cannot override a NO_GO.

6. **Selective scope** — migrate only what you want (one company code,
   one year of history, one business unit), not everything.

7. **AI-augmented code remediation** — when the customer's custom code
   doesn't work on the new system, your tool first tries a deterministic
   "auto-fix" engine, and only falls back to AI (Claude) for the bits the
   deterministic engine can't handle. The AI sees only masked/pseudonymised
   code, never the customer's real secrets.

8. **Built on AWS** — the entire infrastructure deploys in one command
   (`terraform apply`) and tears down in one command. 200 cloud resources
   wired together, idempotent.

### Who is this for?

For now: **mid-market companies (~$50M-$5B revenue) that need to migrate
off ECC but can't afford a 30-person, $20M, 24-month consulting project.**
Your tool is the discovery-and-automation framework; their data is the
content.

You sell it as: *"I'll bring my automation framework, you bring your data,
together we run a discovery phase + a like-for-like sandbox migration in
weeks not months. If it works, we scale to your real migration."*

### Honest reality check

Your tool today is a **prototype** — sometimes the industry calls this
**TRL 6** (Technology Readiness Level 6 out of 9). That means:

✓ It works on real SAP systems (real ECC + real S/4HANA test appliance).
✓ It has been independently reviewed by a peer AI reviewer (Gemini) and
  passed scrutiny on architecture, security, and engineering.
✓ It has not yet been run against a real customer's real data.

So when you pitch, you're pitching **a paid Proof of Concept**, not a
turnkey product. That's a real, sellable thing. SAP integration consultants
make a living on exactly this proposition.

---

## Part 2 — The slightly-more-technical version (for when you want to drill down)

### The four big architectural ideas

**1. Released-API-only.** Every action that changes data on the target SAP
system goes through SAP's official, documented "BAPIs" (Business
Application Programming Interfaces) or OData web services. No raw table
edits. No custom code dropped into the SAP system. This matters because
SAP can refuse to support your customer if you do it wrong. Your tool
protects that.

**2. The Trust Spine.** Five components in a chain:
- **Auto-discovery**: probes the target system to figure out config.
- **Idempotent ledger**: stores `(source_key, target_key, status)` per
  record, in DynamoDB, so re-runs are safe.
- **Hash-chained audit ledger**: every action becomes a SHA-256-chained
  block; any tamper is detectable.
- **SAP-standard report capture**: pulls FAGLB03 (GL balances) and MB5B
  (stock balances) at cutover time, seals their hash into the chain.
- **Cutover gate**: explicit precedence rule — SAP reports outrank tool
  ledger; tool can confirm GO but cannot override NO_GO.

**3. Embedded competitor-grade engines.** Three modules wired into the
respective stage:
- **SmartShift lane** (`code-analyzer`): deterministic ABAP code parser
  (6,400 lines) with AI fallback on parse errors. Daily code-delta
  detection so the migration keeps up with ongoing customer changes.
- **Syniti lane** (`data-hygiene`): foreign-key integrity, deterministic
  self-heal, cross-field validation rules.
- **Natuvion lane** (`data-migrator`): selective carve-out ABAP
  generator with org/time filtering.

**4. SAP-functional safety nets** (added in response to peer review):
- **CVI (Customer-Vendor Integration)** unification with two-phase load
  for intercompany cycle handling.
- **Target-side workload throttle** (probes SAP work-process availability
  + number-range locks before launching parallel loads).
- **BAPI field-coverage analysis** with automatic fallback to LTMC
  staging when a field can't ride the BAPI.
- **Cluster-table preflight** that refuses unsafe extraction patterns
  (would otherwise dump the source database).
- **Dependency DAG resolver** with cross-object key lookup so
  transactionals wait for their masters.

### Architecture in one diagram

```
       SAP ECC (customer's old system)
                  │
                  │ RFC + change-document delta
                  ▼
         ┌──────────────────────┐
         │  AWS Lambda /        │
         │  Fargate (heavy)     │  ◄── auto-discovery + extract
         └──────────┬───────────┘
                    │
                    │ transform (rules + DQ) + BAPI coverage check
                    ▼
         ┌──────────────────────┐
         │  Released BAPIs      │
         │  + OData services    │  ◄── (only path; no raw writes)
         └──────────┬───────────┘
                    │
                    ▼
       SAP S/4HANA (customer's new system)
                    │
                    │ read-back
                    ▼
         ┌──────────────────────┐
         │  Reconciliation +    │
         │  Hash chain seal +   │  ◄── SOX-grade evidence pack
         │  Cutover verdict     │
         └──────────────────────┘
```

### Tech stack

- **Cloud**: AWS (200 resources via Terraform).
- **Compute**: Lambda (37 functions) + Fargate (heavy stages) + ECS.
- **Orchestration**: AWS Step Functions (state machine with 4
  waitForTaskToken human gates).
- **Storage**: DynamoDB (key-map, audit-ledger, gates, run-events) + S3
  (staging, evidence, audit-logs) + KMS-encrypted.
- **AI**: Claude Sonnet 4.6 default, Opus 4.7 escalation, via direct
  Anthropic API (Bedrock-equivalent path; account doesn't have Bedrock
  access).
- **SAP integration**: pyrfc (Python wrapper over SAP NW RFC SDK 7.50).
- **UI**: React 18 + Tailwind + Material-UI + Framer Motion + Recharts.
- **Backend**: Python 3.11 (Lambda) + FastAPI (`api_server.py`).
- **Deploy**: Terraform 1.5+ for infra, PowerShell for image build.

### Documentation map

- **`README.md`** — basic project info.
- **`WHAT_IS_THIS.md`** (this doc) — plain-English explainer.
- **`DEMO_QUICKSTART.md`** — 30-min deploy + demo runbook.
- **`UI_DEMO_GUIDE.md`** — per-page UI walkthrough with demo scripts.
- **`PITCH_DECK.md`** — slide-by-slide client presentation outline.
- **`EXPERT_REVIEW_BRIEF.md`** — executive-level technical brief
  (557 lines). For peer reviewers.
- **`EXPERT_REVIEW_DETAILED.md`** — engineering-level detailed brief
  (1555 lines). For peer reviewers.
- **`HOW-TO-RUN.md`** — operator runbook.
- **`USAGE_GUIDE.md`** — long-form usage notes.
- **`AUDIT_REPORT.md`** — compliance audit narrative.
- **`BATTLETEST.md`** — stress + chaos report.

### Repo layout

- `lambda/` — 37 AWS Lambda functions (one folder per function).
- `lambda/utils/` — 33 shared Python modules (the actual engine).
- `terraform/` — Infrastructure-as-code (modules + per-env wiring).
- `ecs/` — Fargate Dockerfile.
- `frontend/` — React UI.
- `scripts/` — PowerShell operations (image build, etc.).
- `agent/` — In-system ABAP generator (Natuvion-style carve-outs).
- `pipeline_spine_master.py` — The 4-phase orchestrator (Natuvion →
  Syniti → SmartShift → Governance).
- `api_server.py` — FastAPI backend for the UI + the `/api/spine/approve`
  HMAC-signed gate webhook.

---

## Part 3 — Vocabulary cheat-sheet

When you're talking to a client or investor, here are the terms you'll
hear them throw around, with plain definitions:

| Term | What it really means |
|---|---|
| **SAP** | The German enterprise-software company (and their products) |
| **ECC** | The old SAP business software (going out of support) |
| **S/4HANA** | The new SAP business software (everyone's migrating to it) |
| **BAPI** | A "supported, documented" way to talk to SAP programmatically |
| **OData** | SAP's modern web-services API (HTTPS-based) |
| **RFC** | SAP's older binary network protocol |
| **LTMC** | The standard SAP migration tool (free with SAP). Used for the boring stuff |
| **LTMOM** | The mapping editor inside LTMC. Where business users say "old field X = new field Y" |
| **Greenfield** | Build the new system from scratch; migrate selected data over |
| **Brownfield** | Upgrade the old system in place (different problem; not what we do) |
| **Selective Data Transition (SDT)** | Migrate only what you need (one company, one year, etc). What we do |
| **SUM / DMO** | SAP's in-place upgrade tools. Brownfield. Not us |
| **CVI (Customer-Vendor Integration)** | The headache of merging ECC customers + vendors into S/4HANA's unified "Business Partner" |
| **TRL** | Technology Readiness Level (1-9). 6 = "demonstrated in a relevant environment" |
| **WORM** | Write-Once-Read-Many (immutable storage). What auditors want for evidence |
| **SOX** | The financial-reporting compliance law (Sarbanes-Oxley). Big-4 audit happens because of this |
| **TaskToken** | AWS Step Functions trick for pausing the workflow until a human says GO |
| **Idempotent** | Safe to re-run; running it twice produces the same result as running it once |
| **Hash chain** | Cryptographic technique for tamper-evident logs (like blockchain, simpler) |
| **Fargate** | AWS's serverless container service (for jobs too big for Lambda) |
| **Lambda** | AWS's serverless function service (for short jobs, ≤15 min) |
| **VPC** | Your private network on AWS |
| **Terraform** | The tool that builds the AWS infrastructure from code |
| **Pseudonymizer** | Our PII-masking layer that runs before sending code fragments to Claude |

---

## Part 4 — Your two-line elevator pitch

When someone asks "what is this thing?" answer with one of these:

**For a business person:**
> *"It's a cloud-native automation framework for the unavoidable SAP-ECC-to-S/4HANA
> migration that every SAP customer has to do before SAP cuts off support. It
> shrinks a 24-month, $20M consulting project into a discovery + sandbox phase
> we can run in weeks, with a tamper-evident audit trail that satisfies Big-4
> auditors."*

**For a technical person:**
> *"It's an AWS-native orchestration spine — Step Functions + Lambda + Fargate
> — that wraps SAP's released BAPIs and OData services with auto-discovery,
> cross-run idempotent ledger, SHA-256 hash-chained audit, target-side workload
> throttling, and a precedence-ruled cutover gate. 200-resource Terraform stack
> that applies and destroys cleanly. TRL 6 prototype, ready for a paid POC."*

---

*Next read: `DEMO_QUICKSTART.md` to see how to deploy + demo it in 30 minutes.*
