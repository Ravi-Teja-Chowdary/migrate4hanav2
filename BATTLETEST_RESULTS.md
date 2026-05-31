# Battletest Results

*Auto-generated from `tests/battletest/orchestrator.py` runs. Re-run the
orchestrator at larger scale and `generate_report.py` to refresh.*

**Generated:** 2026-05-31 14:02:01 UTC
**Generator commit:** see `git log -1 tests/battletest/`
**Tool version:** see git log -1

This document is the cited artefact for the pitch deck's "Battle-tested"
slide. Every claim below comes from an actual run of the battletest
harness against the deployed prod infrastructure.

---

## Summary

| Metric | Value |
|---|---|
| Largest scale tested | **small** (35,400 records) |
| End-to-end elapsed | **61.47s** |
| Throughput (load) | **715 records/sec** |
| Issues found | **0** |
| Hash chain blocks | **36** |
| Hash chain verifies | **True** |
| Cutover verdict | **GO** |
| Mock target hard failures (injected 0.05%) | 23 |
| Mock target NRIV-busy (injected) | 0 |

---

## Runs (newest first)

| Started | Scale | Elapsed (s) | Records | Issues | Verdict |
|---|---|---|---|---|---|
| 2026-05-31T14:01:13Z | tiny | 0.55 | 390 | 0 | GO |
| 2026-05-31T12:48:56Z | small | 61.47 | 35,400 | 0 | GO |
| 2026-05-31T12:48:34Z | tiny | 1.59 | 390 | 0 | GO |

---

## Per-stage detail (largest run)

| Stage | Elapsed (s) | Records in | Records out | Throughput (rec/s) | Errors |
|---|---|---|---|---|---|
| extract | 0.226 | 35,400 | 35,400 | 156,637 | 0 |
| transform_and_coverage | 0.805 | 35,400 | 35,400 | 43,975 | 0 |
| load | 49.486 | 35,400 | 35,377 | 715 | 23 |
| hash_chain | 0.0 | 35,377 | 36 | 0 | 0 |
| gap_closure_stress | 5.433 | 15,000 | 0 | 2,761 | 0 |
| code_remediation | 0.173 | 50 | 50 | 289 | 0 |
| cutover_verdict | 0.0 | 0 | 0 | 0 | 0 |

---

## Gap-closure stress test results (largest run)

### CVI two-phase unification

- Customers in: **10,000**, vendors in: **5,000**
- Mappings produced: **15,000** -> 14,686 phase-1 stubs + 314 phase-2 attach-xrefs
- Conflicts requiring review: **108197**
- Intercompany cycles detected (no infinite loop): **0**
- Out-of-batch xrefs (deferred): **10**
- Elapsed: **4.98s**

### Dependency DAG

- Nodes: **28**, cycles in default DAG: **0** (expected 0)
- Topological order length: **28**
- Execution state walked to completion: **True**
- Elapsed: **0.0s**

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
- Throughput: **37,643 blocks/sec**
- Elapsed: **0.27s**

### Cutover verdict precedence (5 scenarios)

- All 5 cases produced the expected verdict: **True**
- Cases covered: clean GO, missing-spool NO_GO, LTMC-pending NO_GO, **balance-variance NO_GO overrides tool-says-RECONCILED**, tool-discrepancy GO_WITH_WARNINGS


---

## Code remediation results (largest run)

- Programs processed: **50**
- Deterministic AST engine handled: **50**
- AI fallback invoked: **0**
- Quarantined: **0**
- Errors: **0**
- Elapsed: **0.173s**


---

## Cutover verdict + precedence rule (largest run)

```json
{
  "verdict": "GO",
  "reasons": [],
  "precedence_rule": "SAP-standard spool reports outrank tool ledger; tool ledger cannot override a NO_GO",
  "chain": {
    "blocks": 36,
    "head": "c70a59331acd5201fb6126b53339b3a242419f7d16d5fedf382744f5280c577b",
    "verify": {
      "ok": true,
      "blocks": 36,
      "head": "c70a59331acd5201fb6126b53339b3a242419f7d16d5fedf382744f5280c577b"
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
