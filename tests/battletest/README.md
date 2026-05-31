# tests/battletest — the comprehensive proof-run harness

| File | What it does |
|---|---|
| `generator.py` | Synthesises SAP-shaped data (KNA1/LFA1/MARA/SKA1/BKPF/BSEG) at configurable scale with realistic dirty-data scenarios baked in |
| `abap_generator.py` | Synthesises Z-program suite (60% auto-fixable / 30% ATC-flagged / 10% broken) for code-remediation testing |
| `mock_target.py` | In-process mock SAP target with realistic latency + failure injection + NRIV-lock simulation |
| `orchestrator.py` | The runner. Extracts fixtures → transforms → BAPI-coverage → loads to mock target → builds hash chain → runs gap-closure stress → cutover verdict |
| `generate_report.py` | Reads results JSONs and writes the top-level `BATTLETEST_RESULTS.md` cited in the pitch deck |

## Quick start

```powershell
# Tiny smoke test (~2 sec end-to-end)
python tests/battletest/generator.py --scale tiny
python tests/battletest/abap_generator.py --count 50
python tests/battletest/orchestrator.py --scale tiny --include-code-remediation
python tests/battletest/generate_report.py
```

For the full real-environment proof run (1M+ records), see
`../../BATTLETEST_HOWTO.md`.

## Output layout

```
tests/battletest/
├── fixtures/<scale>/        ← gz JSON-Lines from generator (gitignored)
├── abap-suite/              ← .abap files + catalog.json from abap_generator (gitignored)
└── results/                 ← orchestrator output JSONs (gitignored)
```

All artefacts under those three directories are regenerable.
