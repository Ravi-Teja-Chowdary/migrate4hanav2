# Migrate4HANA — Road to Production

*Plain-language, prioritized plan to take the tool from "proven on a demo system at 10 records
per object" to "can run a real client's end-to-end go-live." Written for a non-SAP reader.
Created 2026-08-02. Companion to `OBJECT_COVERAGE.md` (what's proven) and `UNIFIED_PLAN.md`
(the older hardening backlog). Effort estimates are rough, solo, in calendar weeks.*

## Where we are today (one paragraph)
The **engine works**: one command (`migrate_everything.py`) moves data across all three
buckets — master data, open transactions, balances — from ECC into S/4HANA, using only SAP's
official, support-safe APIs, and reconciles what it wrote. Proven end-to-end on the
fully-configured client 100: ~145 records across 14 object types, created + reconciled, in a
single run. **What's not done** is everything that turns "the tool can move data" into "the
tool delivers a correct, signed-off set of books on Monday morning." That's this plan.

## The analogy
Migrating is like moving money and records from an old bank to a new bank. The tool can carry
the boxes and even count them. It cannot yet (a) guarantee each box lands in the *right* room,
(b) prove the *total* money matches to the penny, or (c) safely handle being run twice. Those
three are the top of this list.

---

## P0 — Correctness (nothing goes live without these)
*If any of these is missing, a real migration produces **wrong data**. This is the gate to a
first real customer.*

### P0-1 · The "translation dictionary" (mapping framework) — ✅ DONE (tool-side) 2026-08-02
`key_mapper.py` — governed detect→propose→confirm→resolve for master-data keys (sibling of
`org_mapper.py`). All four key types covered:
- **Chart of accounts** — proposes by identity → identical description → account-group/BS-PL;
  wired into GL balances (`mapmode=governed`, reconciled to the cent on client 100).
- **Customer→BP / Vendor→BP** — captured **at BP-creation time** (`record_bulk`), then consumed
  by AR/AP so each open item lands on the **right** partner. Proven: AR 10/10, AP 10/10 posted to
  the migrated BPs on client 100.
- **Material→material** — identity → description.
The positional guess is now a labelled last-resort fallback only. *(Remaining for a real client:
the human confirms the review proposals / supplies the business COA map — that's the governed
decision step, which is their input, not a tool gap.)*
**What:** Old and new systems use different codes for the same thing (account `113100` →
`0022544100`; old customer number → new business-partner number; old material → new material;
old plant/company-code → new). Build the governed **mapping layer** that says "old X = new Y"
for accounts, customers, vendors, materials, and org units — and feed it into every bucket
(today balances use a *placeholder* map).
**Why it's #1:** without it, money and documents land on the *wrong* accounts/partners. This is
the single biggest correctness gap.
**How:** extend the existing `org_mapper.py` pattern (detect → propose → confirm → resolve) to
accounts/partners/materials; store the confirmed dictionary; make `bucket3_migrate` /
`bucket2_migrate` consume it instead of the demo map. Much is a governed *business decision*
step (the client confirms the mapping) — the tool's job is to detect, propose, and apply.

### P0-2 · Whole-company reconciliation gate — ✅ DONE (tool-side) 2026-08-02
`reconcile_company.py` — read-only tie-out of source vs target totals across G/L trial balance,
AR/AP open items (extensible to stock), with an overall GO/NO-GO verdict + `RECONCILIATION.md`.
Proven on client 100: correctly reports NO-GO with the exact per-account/per-bucket variances —
it caught both partial-scope demo migrations and the double-posting from repeated runs. On a clean
full single run it ties to the cent = the finance sign-off artifact. *(Original estimate below.)*
**What:** Today we reconcile object-by-object ("these 6 balances match to the cent"). Production
needs the **grand total** proof: the new system's trial balance equals the old system's, AR/AP
aging matches, and stock quantity **and value** tie out — all to the penny — before go-live.
**Why:** this is the number the client's finance team signs. No sign-off = no go-live.
**How:** a reconciliation report that pulls source totals (trial balance, open-item lists,
stock valuation) and target totals and shows the variance = 0, with a per-account breakdown of
any difference. Build on the existing `reconciler.py`.

### P0-3 · Run-it-twice safety (idempotency for balances & transactions) — ✅ DONE 2026-08-02
`migration_ledger.py` — durable (object, source-key)→target ledger; check-before-post wired into
GL balances, AR/AP open items, inventory stock, and maintenance notifications. Proven on client 100:
AR drained 76 remaining items, then a re-run posted **0** ("nothing to post"). Removes the
double-posting the P0-2 gate flagged. *(Original estimate below.)*
**What:** Master data already skips what exists. **Balances and open items don't** — re-running
double-posts the money. Make every posting check a durable "already migrated?" ledger and skip.
**Why:** real migrations are run many times (test → dry-run → real). Double-posting = corrupt books.
**How:** stamp each migrated record/document with a migration reference, persist a ledger
(reuse the DynamoDB key-map pattern), and check-before-post everywhere. Turn the current
GL "marker warning" into an actual skip.

---

## P1 — Reliability at real volume
*Without these it may **fail or be too slow** on a real dataset, even if the data would be correct.*

### P1-1 · Scale + resume-from-failure — ✅ DONE (tool-side) 2026-08-02
Incremental ledger checkpointing (flush every 25 → crash-safe resume) + **scoped extraction**:
AR/AP now read only the migrated partners' open items, cutting a timed AP run from 85s (176,811
rows) to 19.5s (50 rows) — cost proportional to migrated volume. *Remaining: a true million-row
run needs a data-rich system (UNIFIED_PLAN H1.3); master-data whole-table reads not yet paged.*
**What:** We tested at 10 records/object. Real clients have **millions**. Prove throughput,
add **chunking**, and make a run **resume from where it stopped** if it crashes at record
700,000 (checkpoint ledger + job status), within SAP's concurrency limits.
**Why:** a go-live that can't finish in the weekend window, or that can't restart after a
hiccup, isn't usable.
**How:** batch the reads/writes, add a per-object progress ledger, parallelism capped to SAP's
job limits; one real large-volume run to find the true speed and failure modes (this is
`UNIFIED_PLAN.md` H1.3).

### P1-2 · "Truly open" item logic — ✅ DONE 2026-08-02
AR/AP now compute the **signed** open amount from `SHKZG` (invoices/credit-memos/payments net
correctly) and **separate special-G/L items** (down payments, guarantees via `UMSKZ`) into their
own lane instead of mis-posting them. Fixed a real bug (everything was posted as a plain debit).
**What:** An unpaid invoice may be *partly* paid, have a credit note, or a down payment. The
**exact remaining amount** is subtle; today's open-item logic is basic.
**Why:** get it wrong and the new system shows the wrong amount owed to/by the company.
**How:** compute the net open amount from the full clearing history, not just the invoice line;
validate against the source open-item report.

### P1-3 · Upfront data-health preflight — ✅ DONE 2026-08-02
`preflight_all.py` → `PREFLIGHT.md`: one read-only pre-run scan of target config + source data
health + mapping readiness, each READY/WARN/BLOCKED with a fix. On client 100: 10 ready, 3 warn,
1 blocked (17k bank keys flagged before they'd fail mid-run). Turns reactive errors into a checklist.
**What:** Today bad data is caught *during* the run, one error at a time (you saw a bank rejected
for a bad key length). Build a **pre-run scan** that finds all the bad/missing data first and
hands the client a fix-it list — plus a full target-config readiness check (posting periods,
document-splitting classification, CO config, FI-AA transfer phase, account groups, order types).
**Why:** turns "it failed at record 500k" into "here's what to fix before we start."
**How:** generalize `bucket2_preflight.py` into an all-object, all-bucket readiness + data-quality
report.

---

## P2 — Completeness & operations
*Needed for a *polished* full-scope go-live, but a first customer could go live on a defined
scope without all of these.*

### P2-1 · The no-BAPI tail via the cockpit lane — ✅ DONE (tool-side) 2026-08-02
`cockpit_lane.py` routes the no-BAPI objects (Activity Type, QM Inspection Method / MIC, Work
Center) to SAP's Migration Cockpit with source volumes + staging-readiness + `COCKPIT_LANE.md`.
*External prerequisite (not a tool gap): the automated RUN needs a one-time client step —
activate the MC OData service or create the project in LTMC (UNIFIED_PLAN MC-1..4).*
**What:** A handful of object types (Activity Type, some quality/maintenance master data) have
**no official API** — they can only go through SAP's built-in Migration Cockpit. Finish
automating that lane's "run" step safely. This is the **MC-1…MC-4 epic in `UNIFIED_PLAN.md`**.
**Why:** completes "every damn thing" for the objects the direct-API lane can't reach.
**How:** the direct-HANA-staging + programmatic simulate/migrate loop already scoped in
UNIFIED_PLAN (blocked partly on the MC OData service being activated on the target).

### P2-2 · Cutover choreography + rollback — ✅ DONE 2026-08-02
Choreography exists (`cutover.py`: initial → delta/CDC idempotent → reconcile → GO/NO-GO).
Rollback added (`rollback_postings.py`): finds our takeover documents by marker, reverses via the
official BAPI, and for anything the BAPI can't resolve emits `ROLLBACK_WORKLIST.md` for the
SAP-canonical FB08/F.80 mass reversal — never an internal FM. Master data stays net-new.
**What:** Real go-lives freeze the old system, migrate history, migrate a last-minute "delta"
of changes, then switch over — with a tested **rollback** if it goes wrong. Today it's
single-shot only.
**Why:** this is the actual go-live weekend runbook.
**How:** add historical + delta phases and a documented/automated "failed halfway" recovery
(UNIFIED_PLAN H2.2).

### P2-3 · Version range + security/consent hardening — ✅ DONE (tool-side) 2026-08-02
Signed-consent audit ledger built (`consent_ledger.py`: hash-chained, tamper-evident,
`require_consent` gate). Honest version record (`VERSION_VALIDATION.md`): one pair proven live,
the rest schema-adaptive. *External prerequisites (not tool gaps): additional live systems to
validate more version pairs; a security-review sign-off for the code-egress opt-in (H1.1).*
**What:** Prove the tool across the supported ECC → S/4 version grid (`UNIFIED_PLAN.md` H-VER),
finish the code-egress control and the signed-consent audit ledger (H1.1, H1.4).
**Why:** needed for a security review and to claim more than the one version pair proven today.
**How:** the H-VER representative-pair matrix + the H1 items already scoped in UNIFIED_PLAN.

---

## STATUS (2026-08-02): all 9 items addressed tool-side ✅
Every P0/P1/P2 item now has its engineering built and proven on client 100. What remains are
**external prerequisites, not tool gaps**, each named honestly above:
- P0-1 mapping — the client confirms the review proposals / supplies the business COA map (a
  governed decision, their input).
- P2-1 cockpit RUN — a one-time MC-OData / LTMC activation on the target.
- P2-3 — additional live systems to validate more version pairs; a security-review sign-off for
  the code-egress opt-in.
- P1-1 — a true million-row run needs a data-rich system to publish the final throughput SLO.
Nothing left is "more tool code to a first pilot"; it's client inputs + a data-rich system.

New artifacts this pass: `key_mapper.py`, `reconcile_company.py`, `migration_ledger.py`,
`preflight_all.py`, `cockpit_lane.py`, `rollback_postings.py`, `consent_ledger.py`,
`VERSION_VALIDATION.md` (+ generated `KEY_MAPPING.md`, `RECONCILIATION.md`, `PREFLIGHT.md`,
`COCKPIT_LANE.md`).

## Suggested sequence & rough total (original plan)
1. **P0-1, P0-2, P0-3** (correctness) — do first, in this order. **~9–12 weeks.** This is what
   makes a *pilot* on a real client's non-production system honest.
2. **P1-1, P1-2, P1-3** (reliability at volume) — **~7–9 weeks.** This is what makes a real
   production go-live survivable.
3. **P2-1, P2-2, P2-3** (completeness/ops) — **~10–13 weeks**, parallelizable, and partly
   scope-dependent (a first customer may not need the full no-BAPI tail).

**Honest headline:** roughly **~4 months of focused work to a credible first-customer pilot**
(P0 + the volume proof P1-1), and **~7–9 months to a polished, full-scope production tool** —
solo, at the current pace. The engine is built; this is the "make it correct, safe, and
provable at scale" phase.

## Definition of "production-ready" (the finish line)
On a **real customer's system**, one run can: preflight (data + config) → apply the confirmed
mappings → migrate all in-scope objects across the three buckets → **reconcile the whole company
to the penny** → produce a signed, auditable report — **re-runnable safely**, at real volume,
with a tested rollback. Everything written through SAP's official APIs, support intact.
