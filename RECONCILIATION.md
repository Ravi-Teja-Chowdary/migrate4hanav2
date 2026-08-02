# Whole-company reconciliation — target client 100

_Generated 2026-08-02 13:48. Read-only tie-out of source vs target totals for the migrated scope. GO only if every bucket ties to the cent._

## Overall verdict: **NO-GO ❌**

| bucket | source total | target total | variance | verdict | scope |
|---|---:|---:|---:|---|---|
| G/L trial balance | -13,925,561.93 | 368,641,487.76 | 382,567,049.69 | NO-GO ❌ | 48 accounts in governed COA map; source year 2009 |
| AR open items | 8,184,197.97 | 718,291.01 | -7,465,906.96 | NO-GO ❌ | 14 migrated customers |
| AP open items | -32,493,652.07 | -3,379,079.49 | 29,114,572.58 | NO-GO ❌ | 6 migrated vendors |

### G/L account detail (largest variances first)

| target account | intended (source) | posted (target) | variance |
|---|---:|---:|---:|
| `0010010000` | 103,643.74 | 374,593,856.06 | 374,490,212.32 |
| `0021105000` | -10,006,287.50 | 0.00 | 10,006,287.50 |
| `0065002000` | 1,606,003.70 | 0.00 | -1,606,003.70 |
| `0065100000` | 179,171.76 | 0.00 | -179,171.76 |
| `0065001000` | 109,013.42 | 0.00 | -109,013.42 |
| `0063002000` | 30,403.98 | 0.00 | -30,403.98 |
| `0016009000` | 5,624.21 | 0.00 | -5,624.21 |
| `0014107000` | -766.94 | 0.00 | 766.94 |
| `0012562000` | -28,613.58 | -28,613.58 | 0.00 |
| `0021730000` | -125,226.67 | -125,226.67 | 0.00 |
| `0021740000` | -4,103.26 | -4,103.26 | 0.00 |
| `0024090000` | -5,693,019.76 | -5,693,019.76 | 0.00 |
| `0024098600` | -101,405.03 | -101,405.03 | 0.00 |

> **How to read a NO-GO:** a non-zero variance names exactly where source and target disagree. A common cause on a repeated demo run is a takeover posted more than once (the P0-3 idempotency guard prevents that in production). Fix the cause, re-run, and the gate flips to GO — this is the sign-off artifact the finance team needs.