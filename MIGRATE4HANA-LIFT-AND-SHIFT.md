# Migrate4HANA — Lift & Shift Architecture (`aws-lift-and-shift` branch)

> Greenfield ECC → S/4HANA on AWS migration, end-to-end automated, with **zero direct writes** into the target S/4HANA system. Every byte of data, every config change, every line of code lands inside S/4HANA exclusively through SAP-shipped tools — preserving full SAP support with no "reproduce in a standard tool first" friction.

---

## The Two-Plane Principle

```
ORCHESTRATION PLANE (our code, AWS-native)
    Step Functions • Lambdas • pyrfc (READ-only on ECC) • S3 staging • Bedrock
    ↓ generates artifacts, triggers SAP tools, monitors, reconciles
EXECUTION PLANE (100% SAP-shipped tools, runs INSIDE S/4HANA)
    Migration Cockpit • LTMOM • IDoc inbound • CTS+/abapGit • BC Sets • BODS
```

**Inviolable rule:** the orchestration plane **never** issues `INSERT`/`UPDATE` against S/4HANA — not even via "harmless" BAPIs. Reads from ECC are fine. Every write lands through an SAP tool that an SAP support engineer can reproduce inside their own product.

A CI test (`tests/test_no_direct_writes.py`) statically scans every Lambda for forbidden function modules and fails the build. Allowed and forbidden lists are documented in `plan.md` §10b-A.

---

## Pipeline — 9 Phases / 28 Stages

| Phase | Stage | Plane |
|---|---|---|
| **0. ASSESS** | Discovery → Sizing → Object Routing (DAG) | Orch |
| **1. PROVISION** | Target stand-up (Launch Wizard / SWPM) → Basis-handover gate → Basis Validation | Mixed |
| **2. CODE** | Extract Z*/Y* → AST + GenAI Remediation → Transport Build → Place → Import → Verify | Orch + Exec |
| **3. CONFIG** | Foundation customizing → Object customizing → BC Set/transport build → Import → Verify | Orch + Exec |
| **4. DATA-PREP** | Extract → Cleanse + BP Dedup → Generate MC/IDoc/LTMOM templates | Orch |
| **5. DATA-LOAD** | MC lane • LTMOM lane • IDoc lane (executed in topologically-sorted DAG order) | Exec |
| **6. VALIDATE** | Reconciliation → DITL → 85-check Scorecard | Orch |
| **7. CUTOVER** | **ECC Lock** → Final Delta Extract → Final Delta Load → Final Recon → GO/NO-GO Gate (manual) → Integration/DNS Flip | Mixed |
| **8. RUN** | Hypercare Monitoring → Final PDF Report → (Rollback path if needed) | Orch |

> Stage ordering correction from earlier draft: **ECC lock precedes final delta** to eliminate the race window.

See `plan.md` §2 for the full per-stage table and `terraform/modules/step-functions/lift_and_shift_pipeline.asl.json` for the executable state machine.

---

## SAP-Tool-by-Lane Mapping

| Workload | Primary lane | Fallback | Notes |
|---|---|---|---|
| Master data (BP, Material, GL, CC, PC) | Migration Cockpit | LTMOM | ~80% of objects |
| Open transactional (POs, SOs, balances) | Migration Cockpit | BODS for high-volume | MC has standard objects |
| Custom Z-data | LTMOM | MC custom object | Manual gate for object-model changes |
| Interface bootstrapping data | IDoc inbound | MC | Posts to `/sap/bc/idoc_xml` |
| Custom code (Z*/Y*) | CTS+ transport | abapGit / gCTS | Customer choice |
| Customizing (T-tables) | BC Set + customizing transport | Manual STMS | |
| Roles/auth | PFCG transport | — | User assignments to CSV — security team applies |
| SM59/WE20/SICF | Customizing transport | — | DNS flip at cutover is AWS-side |
| High-TPS delta | SLT/DMIS or BODS CDC | — | pyrfc only for low-TPS / post-freeze |

---

## What Migrate4HANA does (and doesn't) automate

**Automates end-to-end:**
- Source discovery, sizing, object routing (DAG)
- Code extraction + 4,200-rule AST + GenAI remediation
- Data extraction, cleansing, BP deduplication, template generation
- Triggering & monitoring SAP-tool execution
- Reconciliation across 85 checks, DITL test execution
- Cutover sequencing, rollback (switch-back to ECC)
- Final PDF report generation

**Deliberate human-in-loop gates:**
- Basis handover after target stand-up (production HANA/ASCS/HSR is Basis-owned)
- Functional UAT sign-off
- Pre-cutover GO/NO-GO board
- Final PROD cutover trigger
- Hypercare incident triage

These exist by design — automating them would be irresponsible for compliance/audit.

---

## Honesty about Migration Cockpit automation

MC is **artifact-generation + monitored execution**, not full headless API drive. Where SAP exposes documented OData operations we use them; where they're missing, our tool prepares everything (templates, runbooks, checksums) and Basis kicks off the run inside MC's Fiori UI. We monitor logs and reconcile regardless. No `/SAPDMC/*` internal-FM hacking in production paths.

---

## Lambda Inventory

See `plan.md` §3 for full keep / retool / new / remove table. Summary:
- **20 kept** (code-analyzer + GenAI rule pack stays — it's the crown jewel)
- **9 retooled** to remove direct writes
- **11 new** for greenfield-specific workflows
- **2 deprecated** (sum-orchestrator, maintenance-planner) — moved to `lambda/_deprecated/` with reusable utilities first extracted into `lambda/utils/`

---

## Customer-supplied prerequisites

| Item | For |
|---|---|
| ECC source + read-only RFC user | Extraction |
| Target S/4HANA license + S-user | New install |
| Migration Cockpit credentials in target | Data lane |
| LTMOM authorization in target | Custom-object lane |
| IDoc inbound config + partner profiles | Interface lane |
| CTS+ / Solution Manager OR abapGit / gCTS endpoint | Code & config |
| STMS configured (transport routes ECC ↔ target) | Transport import |
| Roles/auth strategy (PFCG, BRF+) | Role lane |
| Integration endpoints inventory | Phase 7 cutover |

---

## Status — `aws-lift-and-shift` branch

This branch is a structural pivot from the in-place SUM/DMO conversion model on `aws-branch`. See `plan.md` for the implementation roadmap. The original `aws-branch` continues to support SUM/DMO orchestration and is preserved.
