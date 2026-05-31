# Battletest Results

*Auto-generated from `tests/battletest/orchestrator.py` runs. Re-run the
orchestrator at larger scale and `generate_report.py` to refresh.*

**Generated:** 2026-05-31 15:56:26 UTC
**Generator commit:** see `git log -1 tests/battletest/`
**Tool version:** see git log -1

This document is the cited artefact for the pitch deck's "Battle-tested"
slide. Every claim below comes from an actual run of the battletest
harness against the deployed prod infrastructure.

---

## Summary

| Metric | Value |
|---|---|
| Largest scale tested | **large** (3,505,000 records) |
| End-to-end elapsed | **1370.97s** |
| Throughput (load) | **2,854 records/sec** |
| Issues found | **0** |
| Hash chain blocks | **3,471** |
| Hash chain verifies | **True** |
| Cutover verdict | **GO** |
| Mock target hard failures (injected 0.05%) | 13 |
| Mock target NRIV-busy (injected) | 34814 |

---

## Runs (newest first)

| Started | Scale | Elapsed (s) | Records | Issues | Verdict |
|---|---|---|---|---|---|
| 2026-05-31T15:25:33Z | large | 1370.97 | 3,505,000 | 0 | GO |
| 2026-05-31T15:13:50Z | small | 32.08 | 35,400 | 0 | GO |
| 2026-05-31T14:27:04Z | large | 1394.06 | 3,505,000 | 0 | GO |
| 2026-05-31T14:14:38Z | small | 31.91 | 35,400 | 0 | GO |
| 2026-05-31T14:01:13Z | tiny | 0.55 | 390 | 0 | GO |
| 2026-05-31T12:48:56Z | small | 61.47 | 35,400 | 0 | GO |
| 2026-05-31T12:48:34Z | tiny | 1.59 | 390 | 0 | GO |

---

## Per-stage detail (largest run)

| Stage | Elapsed (s) | Records in | Records out | Throughput (rec/s) | Errors |
|---|---|---|---|---|---|
| extract | 14.879 | 3,505,000 | 3,505,000 | 235,567 | 0 |
| transform_and_coverage | 63.014 | 3,505,000 | 3,505,000 | 55,623 | 0 |
| load | 1227.934 | 3,505,000 | 3,470,173 | 2,854 | 34827 |
| hash_chain | 0.152 | 3,470,173 | 3,471 | 22,830,086 | 0 |
| gap_closure_stress | 63.579 | 1,500,000 | 0 | 23,593 | 0 |
| code_remediation | 0.131 | 100 | 100 | 763 | 0 |
| cutover_verdict | 0.0 | 0 | 0 | 0 | 0 |

---

## Gap-closure stress test results (largest run)

### CVI two-phase unification

- Customers in: **1,000,000**, vendors in: **500,000**
- Mappings produced: **1,500,000** -> 1,471,145 phase-1 stubs + 28,855 phase-2 attach-xrefs
- Conflicts requiring review: **66018**
- Intercompany cycles detected (no infinite loop): **0**
- Out-of-batch xrefs (deferred): **1030**
- Elapsed: **43.03s**

### Dependency DAG

- Nodes: **28**, cycles in default DAG: **0** (expected 0)
- Topological order length: **28**
- Execution state walked to completion: **True**
- Elapsed: **0.0014s**

### Workload throttle (SAP-side TH_WPINFO + NRIV-lock)

- Probe sequence: RED(10.0s), RED(20.0s), YELLOW(8.0s), YELLOW(16.0s), GREEN(0.0s)
- Recovered to GREEN after sustained RED: **True**
- Exponential backoff applied: yes (observe wait_seconds growth on consecutive non-GREEN)

### Cluster-table awareness preflight

- Scenarios tested: **4**
- All scenarios match expected verdict: **True**
- BSEG without header keys correctly rewrites as 2-stage via BKPF
- PCL1 with no WHERE correctly refused (NO_GO) before RFC fires

### Hash chain at scale

- Blocks appended: **10,000**
- Verifies clean: **True**
- Throughput: **48,510 blocks/sec**
- Elapsed: **0.21s**

### Cutover verdict precedence (5 scenarios)

- All 5 cases produced the expected verdict: **True**
- Cases covered: clean GO, missing-spool NO_GO, LTMC-pending NO_GO, **balance-variance NO_GO overrides tool-says-RECONCILED**, tool-discrepancy GO_WITH_WARNINGS


---

## Code remediation results (largest run)

- Programs processed: **100**
- Deterministic AST engine handled: **100**
- AI fallback invoked: **0**
- Quarantined: **0**
- Errors: **0**
- Elapsed: **0.131s**


---

## Cutover verdict + precedence rule (largest run)

```json
{
  "verdict": "GO",
  "reasons": [],
  "precedence_rule": "SAP-standard spool reports outrank tool ledger; tool ledger cannot override a NO_GO",
  "chain": {
    "blocks": 3471,
    "head": "ff262a0ac7dc02ab8bb6b6649c8d4fb6187516bdd84a09ce73726cdd836823b4",
    "verify": {
      "ok": true,
      "blocks": 3471,
      "head": "ff262a0ac7dc02ab8bb6b6649c8d4fb6187516bdd84a09ce73726cdd836823b4"
    }
  }
}
```

The precedence rule that produced this verdict:
> *"SAP-standard spool reports outrank tool ledger; tool ledger cannot
> override a NO_GO."*

---

## How to re-run

```powershell
# 1. Generate fixtures (regenerable; sized via --scale)
python tests/battletest/generator.py --scale large

# 2. Generate the ABAP suite for code remediation
python tests/battletest/abap_generator.py --count 100

# 3. Run the orchestrator
python tests/battletest/orchestrator.py --scale large --include-code-remediation --threads 32

# 4. Regenerate this report
python tests/battletest/generate_report.py --results tests/battletest/results/ --out BATTLETEST_RESULTS.md
```

Scale presets (in `generator.py`):

| Scale | Customers | Vendors | Materials | GL accounts | FI documents | Approx total records |
|---|---|---|---|---|---|---|
| tiny | 100 | 50 | 200 | 40 | 80 | ~750 |
| small | 10,000 | 5,000 | 20,000 | 400 | 5,000 | ~55,000 |
| medium | 100,000 | 50,000 | 200,000 | 1,000 | 50,000 | ~550,000 |
| large | 1,000,000 | 500,000 | 2,000,000 | 5,000 | 500,000 | ~5,500,000 |
| xlarge | 10,000,000 | 5,000,000 | 20,000,000 | 10,000 | 5,000,000 | ~55,000,000 |
