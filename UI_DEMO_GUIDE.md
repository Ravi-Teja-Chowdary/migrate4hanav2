# UI Demo Guide — What to Say While Clicking Each Page

*A scripted walkthrough of every page in the Migrate4HANA UI. Each page
has: what it shows, what to click, what to say, and what NOT to click
during the demo.*

*Target audience: an SAP consultant or IT leader at a prospective customer.
Adapt the wording to your audience — sample lines are starting points.*

---

## The 7 pages (left sidebar)

| Group | Page | Demo importance |
|---|---|---|
| **Overview** | Dashboard | **High** — first impression |
| **Overview** | Project Tracker | **High** — best visual storytelling |
| **Setup** | Connections | Medium — shows we're talking to real systems |
| **Execute** | Migration Pipeline | **High** — the live arc |
| **Govern** | Approval Gates | **High** — proves human oversight |
| **Results** | Runs & Reports | **High** — the auditor artefact |
| **Reference** | Command Center | Low — only show if asked |

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

## Page 7 — Command Center

**URL**: `/commands`
**What it shows**: Every CLI command this platform supports, grouped by
function (extract, transform, load, audit, etc.), with copy-able command
blocks.

**When to show this:** Only if your audience is technical (CTO,
architect, DevOps lead) and asks "what does this look like under the
hood?"

**What to say:**

> *"For people who like to drive from the terminal, every UI action has
> a CLI equivalent. This page is the reference. Useful when you're
> automating Migrate4HANA into your CI/CD pipeline, or when you want to
> script a complex migration scenario."*

**What NOT to do:** Don't click commands here. They run for real.

---

## The 5-minute version (when the meeting runs short)

If you have only 5 minutes:

1. **Dashboard** (30s) — "this is the home, both systems connected."
2. **Project Tracker** (90s) — "left is ECC, right is S/4, 28 stages in
   the middle, here's how the trust spine works."
3. **Click Run Assess** (3 min while talking) — narrate stages.
4. **Runs & Reports → PDF** (30s) — "and this is the audit artefact."

---

## The 20-minute deep-demo version

1. **Dashboard** (1 min) — orientation.
2. **Connections** (1 min) — "real SAP systems, released APIs."
3. **Project Tracker** (2 min) — visual storytelling.
4. **Pipeline → Run Full** (kick off, talk through the first 4 stages,
   then pivot back to Tracker for the animation) (8 min).
5. **Approval Gates** (3 min) — handle the first gate, talk about
   separation of duties + HMAC signing.
6. **Continue the run, more gates** (2 min).
7. **Runs & Reports → click most recent → PDF** (2 min) — the auditor
   artefact.
8. **(If asked)** Command Center (1 min) — "for the terminal-lovers."

---

## Animations + polish you can point to (when asked "is this UI custom?")

- **Framer Motion**: smooth fade-ins as data loads (Dashboard cards,
  ProjectTracker chips, Pipeline phase boxes).
- **AnimatePresence**: stage chips animate in/out as their status
  transitions.
- **Recharts**: live charts on the Dashboard for execution metrics.
- **Lucide-React icons**: consistent iconography across all pages.
- **Tailwind + custom theme**: a coherent "fluidic light" design
  language. Soft shadows, rounded-2xl/3xl corners, indigo + violet
  accent gradient. Not a default Bootstrap or MUI dark theme.
- **Material-UI**: form controls + tooltips.
- **Responsive grid**: works on a projector (1920×1080) AND on a
  laptop screen (1280×800).

---

## Demo failure recovery — the polite pivots

| If this fails | Say this + do this |
|---|---|
| ECC connection drops mid-demo | *"While the network re-stabilises, let me show you the audit trail from yesterday's run..."* → click into a previous run from **Runs & Reports** |
| A stage fails for an SAP-config reason (e.g., a number range exhausted on the demo target) | *"This is exactly the failure mode our throttle prevents. The orchestrator detected the number-range lock and aborted before damaging the target — let me show you the throttle log..."* → switch to a CloudWatch tab or fall back to recorded video |
| The whole UI freezes (rare, but) | *"Let me refresh — the connection pool needs a kick after a backend restart..."* → Ctrl-Shift-R in the browser |
| Anthropic API key invalid (code-remediation stage fails) | *"AI fallback isn't on the critical path; the deterministic AST engine handled this fragment. Let me skip to the post-load stages..."* → switch to **Runs & Reports** |

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
