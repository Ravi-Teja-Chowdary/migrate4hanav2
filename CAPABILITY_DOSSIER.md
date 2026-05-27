# Migrate4HANA — Capability Dossier

*An honest, evidence-backed summary of what this tool does and where it stands. Written
for SAP-experienced partners, prospective design-partner customers, and evaluators.*

---

## 1. What it is (positioning)

Migrate4HANA is a **support-clean, highly-automated SAP ECC → S/4HANA *data-migration*
engine** for the **Greenfield / Selective Data Transition** lane — i.e. it extracts data
from an ECC source and loads it into an S/4HANA target through **SAP-released APIs**, with
end-to-end reconciliation, idempotency, delta, parallelism, and a governed cutover.

**What it is *not* (by design):** it is **not** a Brownfield in-place system conversion. It
does **not** run, replace, or bypass **SUM/DMO** or the **Maintenance Planner** — those are
SAP-proprietary and replacing them would break support. Brownfield conversion is a separate
lane; this tool plays the same lane as the **SAP S/4HANA Migration Cockpit** (data load),
but with far more automation around it (discovery, reconciliation, idempotency, cutover).

**Why now:** SAP ends ECC mainstream maintenance ~2027 (extended ~2030). Thousands of
companies must migrate — and data migration + reconciliation is the costly, error-prone
core of every one of those projects.

---

## 2. The migration spine (architecture)

Every object flows through one governed pipeline:

```
delta/CDC extract  →  best-mechanism load (RFC BAPIs + OData)  →  collision-safe key strategy
   →  cross-run idempotent ledger  →  reconciliation (existence + value)
   →  dead-letter (safe reprocessing)  →  support-compliance attestation
   →  cutover GO / NO-GO runbook
```

A single dispatcher (`UnifiedLoader`) picks the **best SAP-supported mechanism per object**;
auto-discovery adapts the run to the target system; everything is reconciled and attested.

---

## 3. What's built and proven (on a live ECC → S/4HANA pair)

### Object coverage — **12 object types load live**, ~20 extract
| Object | Mechanism (released SAP API) |
|---|---|
| BusinessPartner | BAPI_BUPA_CREATE_FROM_DATA |
| Customer / Vendor | **OData `API_BUSINESS_PARTNER`** (transaction-ready: company-code + sales/purchasing) |
| Material | BAPI_MATERIAL_SAVEDATA |
| ExchangeRates | BAPI_EXCHRATE_CREATEMULTIPLE (batched) |
| OpenPO | BAPI_PO_CREATE1 |
| OpenAR / OpenAP | BAPI_ACC_DOCUMENT_POST |
| CostCenter | BAPI_COSTCENTER_CREATEMULTIPLE |
| ProfitCenter | BAPI_PROFITCENTER_CREATE |
| FixedAsset | BAPI_FIXEDASSET_CREATE1 (asset-class defaults; source→target class auto-validated) |
| Bank | BAPI_BANK_CREATE (global master; idempotent on country+bank-key) |

Adding a new object is **systematic**: its SAP API + discovered config + reconciliation
keys slot into the spine (ProfitCenter and FixedAsset were added this way as the 10th and
11th types — FixedAsset proven on a live ECC→S/4 cross-company-code run: 5 extracted, 5
created, 5 reconciled in ANLA).

### Production-grade capabilities (each proven live)
- **Auto-discovery / landscape-agnostic** — reads a coherent config (company, sales area,
  recon accounts, cost/profit centers, GLs) from *whatever* target it connects to. The PO
  expense account is **probe-validated** (a rolled-back test PO). Env-overridable, cached.
- **Collision-safe key strategy** — never silently corrupts a target record; remaps colliding
  keys (e.g. material) and records a `source → target` mapping.
- **Cross-run idempotent ledger** — a re-run **resumes, never duplicates** (proven: re-run
  reused 21 records, created 0 duplicates).
- **Delta / CDC** — extracts only records changed since a watermark, including **changed
  masters via change documents (CDHDR)**, not just new (cutover-complete).
- **Reconciliation** — reads every loaded record back and ties out **existence *and* value**
  (FI amounts, factor-aware exchange rates, recon accounts) with a hard `RECONCILED` /
  `DISCREPANCY` verdict. It has caught real defects (e.g. a MATNR collision).
- **Dead-letter** — genuine failures captured with source key + SAP reason, reprocessable
  via the idempotent re-run (no risky inline retry that could double-post a document).
- **Parallel mass-load** — connection-pool parallelism (pyrfc frees the GIL); **proven 936
  documents in ~100s at ~9× single-thread throughput, 936/936 reconciled**.
- **Support-compliance attestation** — every run proves all writes used released SAP APIs
  (no raw table writes, no arbitrary ABAP, no SUM/Maintenance-Planner bypass).
- **Cutover runbook** — orchestrates *initial full load → delta → reconcile → GO/NO-GO* as
  one signed-off-able operation (proven verdict: **GO**).

---

## 4. SAP-support compliance (the critical question)

**Every data write goes through SAP-shipped, business-logic-honoring APIs** — released BAPIs
and the released `API_BUSINESS_PARTNER` OData service. The tool **explicitly rejects**
support-breaking shortcuts (raw table writes, `SE16N` edit, arbitrary-ABAP execution); when
it hit a customizing gap it **packaged a transport-grade delta** rather than hack tables.
Reconciliation is read-only. Each run emits a machine-checkable compliance attestation.

---

## 5. Honest maturity & gaps

**Maturity: ~TRL 6** — demonstrated end-to-end in a relevant environment (real ECC + real
S/4HANA, real APIs, real reconciliation). **Not** yet TRL 8–9 (proven in operational use
across customers).

**What's proven:** the full data-migration spine, at volume (~1k docs), support-clean, on a
live system pair.

**Remaining bars to "production-ready at customer scale" (largely external):**
1. **A second, non-IDES landscape** — validate it generalizes beyond the appliance it was
   built on. *(Auto-discovery is the code-side enabler; done.)*
2. **A real pilot go-live** with a customer — the only true proof. **Requires SAP functional
   + Basis expertise on the team** (this tool automates the data movement, not the whole
   project) — best pursued with an SAP consultancy partner.
3. **Breadth to the full ~100 Migration-Cockpit objects** — 12 load today; each additional
   object follows the proven pattern.
4. **Operational hardening** — monitoring, secrets management, packaging/deployment.

**The honest bottom line:** a genuinely strong, support-clean, architecturally-differentiated
ECC→S/4 *data-migration engine*, proven at volume on a live system — not yet a battle-tested,
full-scope, go-live-proven product. The gap is real but well-understood, and the hardest
parts (the trust + automation spine) are built.

---

## 6. How to run (operator quick-reference)

```
# Connectivity: connections.json (ECC + S/4 hosts/sysnr/client/user); passwords via env.
setx-equivalent:  M4H_ECC_PASSWD, M4H_TARGET_PASSWD
# A governed cutover rehearsal (initial full load → delta → reconcile → GO/NO-GO):
python cutover.py
# A volume mass-load (parallel) of a transactional object:
M4H_VOL_N=1000 M4H_VOL_WORKERS=6 python volume_load.py
# The data-migrator stage directly (env: M4H_LOAD_TO_S4=1, M4H_LOAD_MAX_ROWS, M4H_LOAD_WORKERS,
# M4H_CDC_DELTA, M4H_REDISCOVER, per-object M4H_LOAD_MAX_ROWS_<OBJECT>):
python run_local_lift_and_shift.py --only stage13 --run-id <RUN>
```
Every run writes `runs/<id>/data-migrator/summary.json` with the reconciliation verdict,
support-compliance attestation, key-mapping registry, discovered config, and dead-letter.
