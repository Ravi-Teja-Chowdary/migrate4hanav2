# Migrate4HANA Roadmap — From "13 objects working" to "migrate-all-SAP button"

*Last updated: 2026-06-11*

## The constraint

The roadmap below assumes the **4 existing manual gates stay in place**
(ASSESS, DATA-PREP, VALIDATE, CUTOVER). They exist for SOX separation-of-duties
and no regulated customer will buy without them. Everything else can become
a button — the gates are the human-judgment seams.

---

## Where we are today (2026-06-11)

- **13 objects load live** end-to-end via spine orchestrators (Customer,
  Vendor, Material, BusinessPartner, and others).
- Idempotent loads via hash-chained ledger (PersistentKeyMap).
- Dirty-data SLO gate halts the pipeline if dead-letter rate > threshold.
- AWS deploy: CloudFront → ALB → Fargate api-server, Step Functions +
  Lambda data plane, 27 Lambda log groups at 30-day retention.
- UI control plane: live logs, live migration report, multi-tenant client
  switcher, run picker.
- Tool maturity: ~TRL 4-5.

The remaining ~107 objects + customizing alignment + connectivity templates
+ self-service surface are what stands between "working tool" and
"any-SAP-customer button."

---

## Tier 1 — Object & customizing breadth (the foundation)

Without this, nothing downstream matters. **Build the scaffolder first;
everything else multiplies on it.**

| Stream | Scope | Solo estimate | What it unlocks |
|---|---|---|---|
| **Object scaffolder framework** — code-gen: feed a SAP object name → get extraction RFC + transform skeleton + load BAPI + dead-letter classes + reconciliation rules. Cuts each new object from 1 week to 1 day. | **Build this first** | 6-8 weeks | 5-10× multiplier on every Tier-1 stream below |
| **Master-data spine completion** | 17 more master objects (Vendor variants, Pricing master, Cost center, Profit center, Asset master, BOM, Routing, Work center, Source list, Info record, etc.) | 4-5 months | Any customer's reference data |
| **Transactional spine** | 30 open-item objects (open POs, open SOs, open deliveries, open WO, open AP/AR, GR/IR, ATP reservations, etc.) | 6-7 months | "Day 1 in S/4" goes live |
| **Historical/closed data** | 15 archived-doc objects + DART export support | 3-4 months | Compliance retention |
| **Configuration spine** | 50+ customizing tables auto-packaged as BC Sets / transports | 4-5 months | Removes "must align target IMG first" caveat |

**Total Tier 1: ~15-18 months solo.**

---

## Tier 2 — Auto-discovery (so customers don't pre-scope)

Today a consultant has to inspect any new ECC system and say "you have these
company codes, these plants, this much custom code." For "press the button,"
the tool must do this automatically on day 1.

| Component | Estimate | What it produces |
|---|---|---|
| ECC profiler — read-only RFC against any ECC, profiles every table volume, every industry add-on, every modified-standard footprint, every Z-table | 2 months | "You have 3.2M open SO items, 240k customers, 18 Z-tables, IS-U not active" |
| Custom code inventory — SE38 / class / function module / SCI scan with complexity scores | 1 month | "1,840 ABAP units; 65% AST-fixable, 30% AI-needed, 5% manual review" |
| Integration / interface inventory — IDoc partner profiles, RFC destinations, PI/PO scenarios, third-party direct DB reads | 1 month | "12 inbound IDOCs, 8 RFC dests, 1 PI scenario, 1 SFDC connector" |
| Cutover effort estimator — math model from profiler output → "your migration is 14 weeks, $X cost" | 3 weeks | Sales conversion artifact |

**Total Tier 2: ~4-5 months.** Runs in parallel with Tier 1 once the
profiler is built.

---

## Tier 3 — Universal connectivity (so any customer can plug in)

Today: ngrok TCP tunnel from your laptop. For real customers:

| Path | Estimate | When used |
|---|---|---|
| AWS Site-to-Site VPN — terraform templates for Customer Gateway + VGW + BGP | 3 weeks | Most customers (their on-prem ECC) |
| AWS Direct Connect playbook | 2 weeks | Large enterprises |
| SAP Cloud Connector path (SAP-blessed reverse tunnel) | 3 weeks | SAP BTP-aware customers |
| PrivateLink RFC endpoint | 2 weeks | SOC 2 customers who can't VPN |

**Total Tier 3: ~2.5 months.** Independent of Tier 1.

---

## Tier 4 — Target provisioning (so the button creates the destination)

Today: tool assumes target S/4 exists. For "migrate-all-SAP-button":

| Component | Estimate | What it does |
|---|---|---|
| Sizing → BTP / AWS RISE auto-spec | 6 weeks | Reads profiler output → calls SAP BTP API → provisions sized target |
| IMG checklist auto-population — uses customizing matrix from Tier 1 to apply IMG settings via SAP Build Process Automation | 6 weeks | "Target IMG ready" |
| License compliance check — SAP S/4 license vs object scope | 3 weeks | Pre-flight, before any data flow |
| SUM/DMO orchestration (system-conversion path) — for customers who don't want greenfield | 2 months | Alternative to greenfield path |

**Total Tier 4: ~4 months.** Needs Tier 1 customizing matrix.

---

## Tier 5 — Code-remediation coverage

Today: AST engine + Claude Sonnet 4.6 (escalating to Opus 4.7) handles
common patterns. SAP publishes ~1,700 simplification rules.

| Stream | Estimate | Coverage |
|---|---|---|
| Top 200 simplifications (covers ~85% of typical custom code) | 4 months | Hits the volume |
| Long-tail 1,500 simplifications (the obscure stuff) | 6 months | Hits the corner cases |
| Test-generation for remediated code — auto-build ABAP unit tests against migrated logic | 2 months | Auditor confidence |
| Fiori / WebDynpro migration | 3 months | UI layer |

**Total Tier 5: ~12-15 months.** Largely independent.

---

## Tier 6 — Selective Data Transition (so customers can scope)

Most customers don't want everything. They want "last 5 years of finance +
active vendors only + just the EU subsidiary."

| Component | Estimate |
|---|---|
| Filter-definition UI (company codes, plants, sales orgs, posting dates, status) | 4 weeks |
| Dependency graph — exclude vendor X → also exclude that vendor's open POs | 6 weeks |
| Carve-out support — split source data across multiple targets | 8 weeks |

**Total Tier 6: ~4-5 months.** Needs Tier 1 object breadth.

---

## Tier 7 — Self-service SaaS surface (so it's actually one button per customer)

The multi-tenant control plane shipped in this session. To make it real SaaS:

| Component | Estimate |
|---|---|
| Per-tenant credentials in Secrets Manager (not in `_ecc_passwd` global) | 2 weeks |
| Per-tenant S3 prefixes for outputs + evidence | 1 week |
| Per-tenant JWT scopes | 1 week |
| Stripe / SAP Store billing | 4 weeks |
| Customer onboarding wizard | 4 weeks |
| SOC 2 Type II prep (control evidence, vendor risk, etc.) | **3-6 months** (audit-dependent) |

**Total Tier 7: ~3-4 months engineering + 3-6 months SOC 2.**

---

## Tier 8 — Cutover orchestration (so the button closes the loop)

Today: tool produces a NO_GO / GO verdict. For the full button:

| Component | Estimate |
|---|---|
| Downtime planning UI (window calculator from object scope) | 2 weeks |
| User comms templates (auto-sent on gate transitions) | 2 weeks |
| DNS / LB switchover automation (cuts ECC clients to S/4) | 4 weeks |
| Auto-rollback (if any post-cutover check fails) | 4 weeks |
| Hypercare runbook + 14-day monitoring | 4 weeks |

**Total Tier 8: ~4 months.**

---

## Critical-path summary

```
                                                              ┌─ Tier 4 (target prov, 4 mo) ─┐
                                                              │                              │
Tier 1.A (scaffolder, 2 mo) ─ Tier 1.B-1.E (breadth, 14 mo) ──┼─ Tier 6 (SDT, 5 mo) ─────────┼─ Tier 8 (cutover, 4 mo)
                                                              │                              │
                                                              └─ Tier 2 (discovery, 5 mo) ───┘

Parallel tracks:
  - Tier 3 (connectivity, 3 mo) — anywhere
  - Tier 5 (code coverage, 14 mo) — anywhere
  - Tier 7 (SaaS, 7 mo) — anywhere
```

| Team size | Critical-path duration |
|---|---|
| Solo founder (beast mode) | ~28-32 months |
| 2 engineers | ~14-18 months |
| 4 engineers | ~9-12 months |

---

## What this roadmap does NOT promise to automate

These stay human even after the button is built. Anyone who promises
otherwise is selling a fantasy that regulated customers will reject.

- **Strategic scope decisions** — "should we include the EU subsidiary in
  this migration?"
- **Business approvals at the 4 SOX gates** (ASSESS, DATA-PREP, VALIDATE,
  CUTOVER) — the whole compliance model breaks without these
- **Custom-code business intent** — when AST and AI both fail on a Z-program,
  a human must read it
- **Industry-add-on customizing** — IS-U / IS-Retail / IS-Pharma config
  decisions
- **Cutover go-live timing** — a human says "tonight at midnight"

That's not a limitation; that's what the manual gates *exist* for.

---

## The honest 90-day starting point

If you're solo and want maximum leverage in the next quarter:

1. **Build the object scaffolder first (8 weeks).** It's the multiplier.
   Without it, every new object is a week of hand-coding.
2. **ECC profiler (4 weeks).** Sales artifact — *"give me 4 hours of
   read-RFC access; I'll tell you what your migration looks like"* is a
   closer.
3. **Three master objects via the scaffolder (4 weeks).** Proves the
   scaffolder works.

After 90 days: a working object-generator, a customer-facing profiler that
turns into pre-sales conversations, and 3 new objects proving the
generator's output is production-quality. *Then* the breadth grind becomes
weekly instead of monthly.

---

## How to use this document

- **Sales conversations:** Tier 1 / Tier 2 / Tier 7 are the customer-visible
  story. The rest is engineering plumbing.
- **Investor / partner conversations:** the critical-path summary is the
  honest answer to *"how long until you can sign Fortune 500?"*
- **Engineering planning:** Tiers are ordered by dependency. Don't start
  Tier 4 (target provisioning) before Tier 1's customizing matrix exists.
- **Maintenance:** when you finish a tier, mark it ✅ and add a one-line
  date. When a customer surfaces a gap, add it to the appropriate tier.

---

## Status tracking

| Tier | Status |
|---|---|
| Tier 1 — Object & customizing breadth | 🟡 13 / 120 objects live; scaffolder not built |
| Tier 2 — Auto-discovery | 🔴 Not started |
| Tier 3 — Universal connectivity | 🟡 ngrok works; templates not built |
| Tier 4 — Target provisioning | 🔴 Not started |
| Tier 5 — Code-remediation coverage | 🟡 AST + GenAI working; long tail not built |
| Tier 6 — Selective Data Transition | 🔴 Not started |
| Tier 7 — Self-service SaaS | 🟡 Multi-tenant control plane shipped; per-tenant credentials TBD |
| Tier 8 — Cutover orchestration | 🟡 Verdict logic works; switchover automation TBD |
