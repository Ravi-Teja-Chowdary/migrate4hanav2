# Version-range validation record (road-to-production P2-3 / UNIFIED_PLAN H-VER)

*Honest record of which ECC→S/4 version pairs are **proven live** vs **supported and
schema-adaptive but not yet run on a live pair**. No pair is claimed as proven that isn't.*

**Last updated:** 2026-08-02

## Supported grid (LOCKED scope)
**ECC 6.0 EHP0–EHP8** (source) → **S/4HANA 2020–2025** (target) = **9 × 6 = 54 pairs**.
S/4HANA 1909 is out of scope (see `UNIFIED_PLAN.md` H-VER). The grid is enumerated by
`lambda/utils/version_matrix.py`.

## Why one live pair credibly covers the band (the engineering basis)
The engine **discovers live** instead of hardcoding: `DDIF_FIELDINFO_GET` for schemas,
`FUPARAREF`/`RFC_GET_FUNCTION_INTERFACE` for BAPI signatures, live customizing reads. The
2020–2025 target band is homogeneous (same Fiori MC, CVI/BP-led numbering, largely the same
BAPIs); the EHP source range is additive on a stable core the extractor intersects. So a
representative spread is proven live and the rest is schema-adaptive interpolation — **not**
a claim that all 54 cells were executed.

This session hardened exactly the mechanism that makes it version-robust: handlers already
normalize list-vs-dict BAPI `RETURN`, validate source codes against target config tables
(e.g. equipment `EQTYP` → `T370T`), and adapt to release differences (ProfitCenter `TESTRUN`
is a structure param on this release, not a flag). That is the H-VER.2 "universal signature"
behavior in practice.

## Validation status
| Source (ECC) | Target (S/4) | Status | Evidence |
|---|---|---|---|
| EHP8 (IDES) | S/4HANA 2020, client 100 | ✅ **PROVEN LIVE** | 3-bucket run: 14 object types created + reconciled; GL balance to the cent; AR/AP faithful via key-map; see `OBJECT_COVERAGE.md` + this session's runs |
| EHP0–EHP7 | 2020–2025 | 🟡 supported (schema-adaptive) — **pending first live run** | needs a second live pair; no code change expected |
| EHP8 | 2021–2025 | 🟡 supported (schema-adaptive) — **pending first live run** | homogeneous target band |

**Honest gap:** only **one** live pair is proven. Closing H-VER to "validated" for the corners
(EHP0→2020, EHP8→2025) and a mid pair (EHP6→2023) needs **access to those additional live
systems** — an external prerequisite, not a tool change. The UI must show only the one pair as
"validated" and the rest as "supported (schema-adaptive)" (H-VER.6) — no overclaim.

## Security / consent (H1.1, H1.4)
- **H1.4 signed-consent audit ledger — ✅ built:** `consent_ledger.py` — hash-chained,
  tamper-evident record of who approved which scope, when; `require_consent(scope)` lets a
  governed run refuse to write without a sign-off; `verify()` detects any tamper. Tested:
  grant → verify intact → require True/False → tamper detected.
- **H1.1 code-egress control — partial:** the pseudonymizer (`lambda/utils/pseudonymize.py`)
  masks PII before any external-LLM call and is policy-enforced in Lambda (raw ABAP is refused
  when the masker is unavailable). **Remaining:** finish the local-LLM (Ollama) routing so
  high-sensitivity code never leaves the customer network, OR document the opt-in + masking
  contract as the enforced default. This needs a **security-review sign-off** — an external
  prerequisite, not a code gap.
