# UI Demo Guide — What to Say While Clicking Each Page

*A scripted walkthrough of every page in the Migrate4HANA UI. Each page
has: what it shows, what to click, what to say, and what NOT to click
during the demo.*

*Target audience: an SAP consultant or IT leader at a prospective customer.
Adapt the wording to your audience — sample lines are starting points.*

---

## The 11 pages (left icon rail)

The UI has been rebuilt in a Datadog/Grafana-style observability layout — a
compact icon rail on the left, a slim topbar with active-run / active-client
pickers + time-range + theme toggle + Cmd+K palette, and the page in the
middle. Light theme by default; press the moon icon to switch to dark.

| Group | Page | Demo importance |
|---|---|---|
| **Overview** | Dashboard | **High** — first impression |
| **Execute** | Migration Pipeline | **High** — the live arc |
| **Results** | Runs | **High** — every execution + its PDF |
| **Results** | **Migration Report** (LIVE — NEW) | **High** — same sections as the PDF, refreshing every 7s during a run |
| **Govern** | Approval Gates | **High** — proves human oversight |
| **Quality** | Data Quality | Medium — dead-letter SLO surface |
| **Observe** | **Logs** (NEW) | **High** — full CloudWatch tail in the browser, no AWS console |
| **Setup** | Connections | Medium — ECC + S/4 RFC + OData |
| **Setup** | **Clients** (NEW — multi-tenant) | **High** for consulting firms — one tool, many customers |
| **Reference** | Versions | Low — compatibility matrix |
| **Reference** | Command Center | Low — only show if asked |
| **Reference** | Project Tracker | Medium — kanban view of the 28-stage spine |

---

## Topbar — what every page shares

Before walking any page, point at the topbar (left → right):

1. **Client picker** — *"This is the multi-tenant selector. We're on the
   'default' client right now. A consulting firm running migrations for
   multiple customers would switch contexts here — each client has its own
   credentials and its own run history."*
2. **Run picker** — *"This is the active migration run. Every page below —
   Logs, Report, Data Quality — is scoped to whatever run is selected
   here. Click to switch between runs in seconds."*
3. **Source → Target chips** — `ECC · Y01 → S4H · S4H`
4. **Time-range picker** + **refresh control** — observability convention
   (1h / 24h / 7d / 30d).
5. **Cmd+K palette** — *"Anything I can click, I can also reach with Cmd+K.
   Try it: 'logs' → enter."*
6. **Theme toggle** + **API health dot** (green = backend live).

---

## Page 1 — Dashboard

**URL**: `/`
**What it shows**: A landing page with system health, recent activity,
quick-launch cards to other pages, and connection status badges.

**What to say (as you land on it):**

> *"This is the operator's home base. Top-left tells me whether the
> orchestrator is online. The green badge here means the backend is
> reachable. These two cards — ECC source and S/4HANA target — show me
> at a glance whether my SAP systems are connected. Right now both are
> green, so we're ready to run."*

**What to click during a live demo:** Nothing. This page is the
"establishing shot." Pause for 5-10 seconds so the viewer can read the
quick-launch cards. Then move on.

**Animations to point out (if asked):**
- The metric tiles fade in with Framer Motion as the API responses arrive.
- The "checking..." spinners turn into solid badges as health checks
  complete (every 10 seconds).

**What NOT to do:** Don't click "Run Assess" from here without the
client expecting it — it triggers a real backend call and you don't
want a 3-min wait at the wrong moment.

---

## Page 2 — Project Tracker

**URL**: `/tracker`
**What it shows**: Visual kanban-style view of the migration: Start (ECC)
on the left, End (S/4HANA) on the right, and the **28 stages laid out as
a pipeline** in between. Stages move from "Queued" → "In-Progress" →
"Completed" with smooth animations as the actual backend execution
progresses.

**Why this is the best visual:** Even a non-technical executive
understands "left side is the old system, right side is the new system,
and the box in the middle is the migration in motion." It's the most
"obvious-what's-happening" page.

**What to say:**

> *"This is what an active migration looks like. On the left is the
> client's ECC system. On the right is the target S/4HANA. In between are
> the 28 stages our orchestrator runs through. Each stage tells you which
> embedded engine handles it — Syniti-class for data quality, SmartShift-
> class for code, Natuvion-class for carve-outs. Green is done. Blue with
> a spinner is running. Grey is queued."*

> *"What's important: each completed stage emits a record into the
> cryptographic audit chain. So when the client's Big-4 auditor asks
> 'how do I know this record actually loaded correctly?' — we have a
> tamper-evident answer at the row level."*

**What to click during a live demo:**
1. Hover over a stage chip to show its engine tag.
2. If a run is active, point at the running stage as it animates.
3. Click any completed stage to expand it (shows per-stage detail).

**The wow moment:** If you trigger a real run and let the audience watch
3-4 stages move from "Queued" to "Completed" with the animation, that's
the closest thing this product has to a magic moment. Time the demo so
this happens during your "trust spine" pitch line.

---

## Page 3 — Connections

**URL**: `/connections`
**What it shows**: Two big cards: **Source (SAP ECC)** and **Target
(SAP S/4HANA)**. Each card shows connection details (host, system number,
client, user) and a connectivity status badge.

**What to say:**

> *"This is where we tell the orchestrator how to reach the SAP systems.
> Notice: we're using SAP's released RFC protocol for ECC, and OData over
> HTTPS for the S/4HANA Business Partner API. We **never** write to the
> SAP database directly — that's what breaks SAP support contracts. Every
> action goes through SAP's official APIs."*

> *"For the demo, both endpoints are real systems: the ECC on the left is
> SAP IDES — basically SAP's training/demo system, used by tens of
> thousands of consultants worldwide. The S/4HANA on the right is the SAP
> CAL (Cloud Appliance Library) — SAP's official trial appliance. So
> we're not talking to mocks; we're talking to real SAP code paths."*

**What to click:** Just hover on the cards so the field detail is visible.
Don't click "Edit" during a demo — that opens a form mid-presentation.

**Honest disclaimer to add:**
> *"For a real customer engagement, we'd point this at their dev landscape
> first, then their pre-prod, then prod. The connection mechanism is the
> same; only the credentials change."*

---

## Page 4 — Migration Pipeline

**URL**: `/pipeline`
**What it shows**: All 28 stages in a vertical list, grouped by phase
(ASSESS, PROVISION, CODE, CONFIG, DATA-PREP, DATA-LOAD, VALIDATE, CUTOVER).
Each stage shows: handler name, engine (deterministic / AI-augmented /
crypto-audit), and live status.

Two big action buttons at the top:
- **Run Assess** (~3 min) — discovery + readiness, safe to run anytime
- **Run Full** (~10 min on fixtures) — the whole migration

**What to say BEFORE clicking anything:**

> *"This is the operator's control surface. The 28 stages are grouped
> into 8 phases. The phase colours tell you the kind of work happening:
> indigo for assessment, violet for infrastructure provisioning, sky for
> custom-code remediation, teal for configuration, amber for data, green
> for validation, red for the cutover decision."*

> *"What's important is the lane label next to each stage. We have three
> embedded competitor-grade engines:"*
> - *"`Syniti DataSpine` — for foreign-key integrity and self-heal"*
> - *"`SmartShift FailSafe` — for ABAP code remediation"*
> - *"`Natuvion Carveout` — for selective-data-transition extraction"*

> *"All three run inside our stages, not as parallel pipelines."*

**Live demo: click "Run Assess" first**

When you click Run Assess, the stages start lighting up sequentially.
Narrate as it runs:

> *"Stage 1 — discovery. The orchestrator just connected to the target
> S/4HANA system and is probing the configuration: what company codes
> exist, what currencies are in play, what number ranges are configured.
> This is auto-discovery. The standard Migration Cockpit doesn't do this;
> a human has to look it up and type it in."*

> *"Stage 2 — readiness check. We're pulling SAP's standard Readiness
> Check report. That's free if you have an SAP S-user — we just automate
> the fetch + analysis."*

> *"Stages 3-7 — sizing, routing, target provisioning, basis validation.
> All assessment-side, no changes made yet."*

**If a stage fails red:**
> *"This is by design. A failed stage halts the pipeline — it doesn't
> push partial state to the target. We have explicit error reporting per
> stage. Let me click on it to show you the detail."*

(Click the red stage; the detail pane shows the exact RFC error or
validation message.)

**Live demo: trigger "Run Full" for the human-gate moment**

The most impressive part of the demo is hitting a `waitForTaskToken` gate.
About 3 minutes in, the pipeline will stop at the **ASSESS Approval gate**.

> *"This is the safety mechanism. The pipeline has paused, not because
> something failed, but because it requires a human to approve the
> assessment before it proceeds to provisioning. You'd get an email
> notification right now."*

(Click over to the Gates page — see Page 5.)

---

## Page 5 — Approval Gates

**URL**: `/gates`
**What it shows**: Active gates waiting for human approval, with the
detailed payload of each (extracted row counts, data quality metrics,
quarantine counts, infrastructure health).

**What to say:**

> *"The pipeline has 4 of these gates. After every major phase, a human
> has to explicitly approve before the next phase starts: after ASSESS,
> after DATA-PREP, after VALIDATE, and finally for CUTOVER. This is the
> SOX requirement for separation of duties — a tool cannot self-promote;
> a human has to put their name on it."*

> *"What's on this page right now is the gate that's currently pending.
> The payload shows me what the orchestrator wants me to approve — total
> rows extracted, quality metrics, infrastructure status. I read this,
> then I either approve or reject."*

**Show the approver field:**
> *"My name goes here. This name gets sealed into the audit chain
> alongside the timestamp. So an auditor can later prove who approved
> what, when. The approval mechanism is HMAC-signed — there's a one-time
> token in the approval URL that can't be forged or replayed."*

**Live click:** Type "demo@example.com" in the approver field, then
click **Approve** on the pending gate. The pipeline resumes within 2-3
seconds.

> *"And we're running again. The Project Tracker page would show the
> next phase starting now."*

(Click back to Project Tracker to show the animation.)

---

## Page 6 — Runs & Reports

**URL**: `/runs`
**What it shows**: List of every migration run with its grade, score,
and recommendation. Click any run to see the detailed result + download
the PDF report.

**What to say:**

> *"Every run produces a graded result. We use an A-F scale based on
> reconciliation completeness, data quality, and infrastructure health.
> A grade of A means the load was 100% reconciled with no quality
> rejections; a C means there are flags worth reviewing; an F means
> NO_GO."*

> *"Click any run to see the detail."*

(Click a recent run.)

**What's on the run detail page:**
- Grade + score badge
- Per-object load breakdown (created, reconciled, dead-letter)
- Reconciliation verdict (RECONCILED / DISCREPANCY)
- Hash chain status (chain length + verification result)
- Captured spool reports (FAGLB03, MB5B) with their SHA-256s
- **PDF Report** button (top-right)

**Click the PDF Report button:**

> *"This is the artefact the auditor wants. It's a multi-page PDF with:
> per-object summaries, the full cryptographic audit chain, the SAP
> standard balance reports we captured at cutover with their hashes,
> and the cutover verdict with the precedence rule that produced it."*

> *"Importantly: our precedence rule says **SAP-standard reports outrank
> the tool's ledger**. If FAGLB03 says there's a 1-cent variance between
> source and target — even if our internal reconciliation says everything
> matches — the cutover verdict is NO_GO. The tool cannot self-approve
> over an SAP-standard report."*

**This is the killer line for the audit conversation.** Practice
delivering it in one breath.

---

## Page 7 — Migration Report (LIVE)

**URL**: `/report`
**What it shows**: The same 10 sections as the PDF the auditor receives —
**but live**, refreshing every 7 seconds as the pipeline runs. Each section
has a "pending / ready" pill, so the audience watches the report build
itself in real time. Preview + Download PDF buttons sit at the top.

The 10 sections (order matches the PDF):

1. Executive Summary
2. Code Remediation
3. Data Migration
4. Dead-Letter SLO / Data Quality
5. Configuration
6. Roles & Authorizations
7. Integrations
8. Go-Live Scorecard
9. Risk Assessment
10. Post Go-Live Roadmap
11. Technical Metrics

A completion progress bar at the top shows "Report completion: 5/11 sections
ready (45%)" while the run is in flight.

**Why this exists:** Customers asked "where's the PDF?" mid-demo and we
had no answer except "after the run finishes." This page makes the report
visible from the moment Stage 1 lands its first metric.

**What to say:**

> *"This is the auditor's deliverable, but you don't have to wait for the
> migration to finish to see it. Every section here is the same data the
> PDF will contain — pulled live from the same sources, refreshing every
> few seconds as the pipeline runs. Each pill tells you whether that
> section has its data yet."*

> *"Notice the Executive Summary is already complete — that's because
> source-system assessment ran in Stage 1. The Code Remediation section
> is filling in now as the SmartShift engine processes ABAP files. The
> Go-Live Scorecard at the bottom stays pending until the very last
> stage validates the cutover decision."*

> *"When the run completes, every pill turns green and the Download PDF
> button at the top delivers the exact same content as a sealed report."*

**Live click:** Hit **Refresh** to force a poll mid-narration if you want
the audience to see a section transition from "pending" to "ready" on cue.

---

## Page 8 — Logs (LIVE, CloudWatch in the browser)

**URL**: `/logs`
**What it shows**: A live tail of every CloudWatch log group the platform
writes to — Step Functions executions, the Fargate api-server, and **27+
individual Lambda functions** — surfaced directly in the browser. No AWS
console required.

Features:
- **Source picker** (top-left): pick which log group to tail (e.g.
  `Lambda · data-migrator`, `Step Functions executions`, `API server`).
- **Time window**: 1 hour / 6 hours / 24 hours / 7 days / 30 days.
  30 days is the retention cap (enforced via terraform on every log group).
- **Level filter**: All / ERR / WARN / OK / INFO. Server-side string
  filter via CloudWatch's `filterPattern`.
- **Live tail**: polls every 4 seconds. Pause / Resume button keeps the
  view stable mid-conversation.
- **Search**: free-text filter, also server-side.
- **Download**: dumps the current window as a `.log` text file.

**Why this exists:** A customer's compliance team needs proof of every
event in the migration. Without this page, they'd have to be granted IAM
read on the AWS account — which is a non-starter for most. This page
shows everything they need without giving them console access.

**What to say:**

> *"This is the full operational view. Every Lambda invocation, every
> Step Functions transition, every error the api-server logs — all
> visible here, live. We never ask the customer to open the AWS console.
> The api-server reads from CloudWatch on their behalf and pushes events
> down to the browser every four seconds."*

> *"Retention is locked to 30 days at the terraform level — that's the
> SLA we advertise. After 30 days CloudWatch ages events out automatically
> and they're gone from this view too. Compliance teams like that because
> it bounds the retention liability."*

**Live demo:**
1. Pick `Lambda · data-migrator` from the source dropdown.
2. Watch events scroll if a run is active.
3. Click **Pause** mid-tail to freeze the view — narrate a specific error
   line if one is visible.
4. Click **Download** to show the `.log` file landing in their browser.

**Why this matters to the audit story:** *"Every event in this view is
also written to S3 Object Lock evidence storage for the full 7-year SOX
retention. CloudWatch is just the live operational view — the immutable
copy lives in WORM storage."*

---

## Page 9 — Clients (multi-tenant control plane)

**URL**: `/clients`
**What it shows**: A list of every tenant ("client") the platform manages.
Each tenant has its own ECC + S/4 credentials, its own runs, its own
outputs directory. The "default" tenant is the legacy single-tenant
context — every fresh install starts there.

Features:
- **Add a client**: short form (id + display name). Id must be lowercase
  `a-z`, digits, `_`, or `-`. Used in S3 prefixes and run paths.
- **Switch active client**: click any row. The whole UI swaps — no
  reload. Subsequent API calls carry an `X-Client-Id` header automatically.
- **Delete**: protected for the default client; other tenants can be
  removed (registry entry only — on-disk outputs are left alone).
- **ECC session badge**: shows which tenants are currently authenticated
  with their ECC system.

**Why this exists:** A consulting firm or MSP runs migrations for many
customers. Without tenancy, customer A's ECC password lives in the same
global as customer B's — and switching customers means restarting the
api-server. This page gives them per-customer isolation in one process.

**What to say:**

> *"This is the multi-tenant control plane. If you're an SAP system
> integrator running migrations for ten different end-customers, each one
> has its own ECC, its own S/4, its own run history. Switching between
> them is one click in the topbar — no restart, no credential overwrite,
> no session bleed."*

> *"Behind the scenes, each tenant has its own bucket prefix in S3 and
> its own outputs path on disk. So the auditor for Customer A can never
> see Customer B's data, even by accident."*

> *"On AWS, the api-server is on Fargate and auto-scales 1 → 4 tasks
> when CPU hits 60%. So a fleet of customers hitting it at once doesn't
> saturate the single uvicorn worker."*

**Live demo:**
1. Add a client (id: `acme-corp`, name: `Acme Corporation`).
2. Watch it appear in the table and in the topbar picker.
3. Click "Switch" — every page now scopes to Acme. The Runs page will be
   empty (Acme has no runs yet). The Logs page will be empty too.
4. Switch back to `default` — runs and logs reappear.

**Honest disclaimer to add:**
> *"Today, connection credentials are still stored once per api-server
> instance. The per-tenant credential split is the next iteration — it's
> on the roadmap because it's required for true SaaS deployment to
> multiple customers from the same instance."*

---

## Page 10 — Command Center

**URL**: `/commands`
**What it shows**: A whitelisted catalogue of server-side scripts the UI
can trigger (connection tests, spine orchestrators, diagnostics, PDF
re-generation). Each script has a one-click **Run** button; output streams
into an inline console with stdout / stderr / exit code, polled at 1.5s.

**When to show this:** Only if your audience is technical (CTO,
architect, DevOps lead) and asks "what does this look like under the
hood?"

**What to say:**

> *"For people who like a terminal feel, every operational script the
> platform supports — connection tests, spine loaders, diagnostics —
> can be triggered from here. No shell access required; the server-side
> registry is hard-whitelisted, so there's no arbitrary command
> execution. Output streams back live."*

**What NOT to do:** Don't kick off a long-running spine orchestrator
mid-demo (some run 5-10 minutes).

---

## Pages worth knowing exist, but rarely demoed

| Page | URL | When to mention |
|---|---|---|
| **Data Quality** | `/data-quality` | Only if the audience asks "what's a dead-letter?" The page surfaces the dead-letter SLO percentage, the threshold, and breach status. The same data is already on the Migration Report under section 4 — prefer that. |
| **Versions** | `/versions` | Only if the audience asks "what ECC + S/4 versions do you support?" Compatibility matrix view; useful for technical due-diligence calls, not for sales. |

If asked about either: *"Both surface data you've already seen on the
Report page — they exist so a Basis admin or DBA can drill in without
hunting through the report sections."*

---

## The 5-minute version (when the meeting runs short)

If you have only 5 minutes:

1. **Dashboard** (30s) — "home, both systems connected."
2. **Pipeline → Run Assess** (3 min while talking) — narrate stages.
3. **Logs** (30s, mid-run) — *"and this is what's actually happening — live,
   in the browser, no AWS console."*
4. **Migration Report → Download PDF** (30s) — *"and this is the auditor
   artefact, watching it build live as the run completes."*

---

## The 20-minute deep-demo version

1. **Dashboard** (1 min) — orientation, point at the topbar (client +
   run picker).
2. **Clients** (90s) — *"multi-tenant out of the box; one tool, many
   customers."* Add a demo client + switch back.
3. **Connections** (1 min) — "real SAP systems, released APIs."
4. **Project Tracker** (2 min) — visual storytelling.
5. **Pipeline → Run Full** (kick off, talk through the first 4 stages,
   pivot to Tracker for the animation) (6 min).
6. **Logs** (2 min, mid-run) — switch the source dropdown between
   `data-migrator`, `Step Functions executions`, `data-hygiene`; pause,
   download a `.log`.
7. **Migration Report** (2 min) — let the audience watch sections turn
   from "pending" to "ready" as the data lands.
8. **Approval Gates** (2 min) — handle the first gate, separation of
   duties + HMAC signing.
9. **Continue the run** (1 min) — more gates.
10. **Runs → click most recent → PDF** (1 min) — the sealed auditor
    artefact, identical to the live Report content.
11. **(If asked)** Command Center (30s) — "for the terminal-lovers."

---

## Animations + polish you can point to (when asked "is this UI custom?")

- **Framer Motion**: page-transition fades, panel mounts, dropdown
  enter/exit animations, AnimatePresence on the topbar pickers.
- **Recharts**: time-series + Sparklines on the Dashboard and Runs page.
- **Lucide-React icons**: consistent iconography across the icon rail
  and inline buttons.
- **Tailwind + CSS variables theme**: light/dark via `[data-theme]` on
  `<html>`. Datadog/Grafana observability vibe — compact icon rail,
  metric tiles, pill statuses, monospace data, dense layouts. Not a
  Material/Bootstrap clone.
- **Cmd+K palette** for keyboard-first navigation.
- **Toast notifications** (React Portal + framer-motion) on every
  destructive or async action.
- **Responsive grid**: works on a projector (1920×1080) AND on a
  laptop screen (1280×800).

---

## Demo failure recovery — the polite pivots

| If this fails | Say this + do this |
|---|---|
| ECC connection drops mid-demo | *"While the network re-stabilises, let me show you the audit trail from yesterday's run..."* → switch the **Run picker** in the topbar to a known-good completed run, then open the **Migration Report** page (it'll be 100% green) |
| A stage fails for an SAP-config reason (number range exhausted, etc.) | *"This is exactly the failure mode our SLO gate catches. Let me show you the dead-letter ledger..."* → **Logs** page, filter level ERR, narrate the actual error line in the browser |
| The whole UI freezes (rare, but) | *"Let me refresh — the connection pool needs a kick after a backend restart..."* → Ctrl-Shift-R in the browser |
| Anthropic API key invalid (code-remediation stage fails) | *"AI fallback isn't on the critical path; the deterministic AST engine handled this fragment. Let me skip to the post-load sections..."* → switch to **Migration Report** and scroll to Data Migration |
| Logs page returns nothing | *"CloudWatch takes ~30s for events to land. Let me show you the report sections that have already populated..."* → switch to **Migration Report** |

The general principle: **don't panic, don't apologise excessively,
pivot to a strength.** A graceful demo recovery actually impresses
sophisticated audiences more than a perfect run.

---

## What to do AFTER the demo

While the audience is engaged, ask THESE three questions:

1. *"Looking at this trust spine — auto-discovery, idempotency, hash
   chain — does this match what your audit team would want to see?"*
2. *"Where in your S/4HANA migration timeline do you think this would
   plug in best — early discovery, or pre-cutover validation?"*
3. *"What objects are you most worried about migrating? Customer master?
   Material master? Open AR/AP?"*

These questions:
- Force them to engage with the artefact, not just listen.
- Surface their actual pain points.
- Position you as a consultant, not a vendor pitching a product.

**Then** offer a follow-up: *"Let me write up a brief discovery scope for
your environment — 2-3 master objects, 1-2 transactional objects, 50k
records each, in your sandbox. Two-week paid POC. Interested?"*

That's the close.

---

*Next read: `PITCH_DECK.md` for the slide-by-slide client presentation.*
