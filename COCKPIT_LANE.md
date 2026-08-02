# Cockpit lane — no-BAPI object tail — target client 100

_Generated 2026-08-02 14:11. Read-only. These objects have no official create BAPI, so they migrate via SAP's Migration Cockpit (stage → prepare → simulate → migrate). Staging is programmatic; the RUN trigger depends on the gate below._

**Staging infrastructure (DS_MAPPING catalog reachable):** ✅ yes
**MC RUN trigger:** unknown (probe inconclusive) — verify MC OData / LTMC on target

| object | MC object | source rows | source table | staging object |
|---|---|---:|---|---|
| Activity Type | Activity Type | 676 | CSLA | S_CSLA |
| QM Inspection Method | Inspection Method | 27 | QMTB | S_QMTB |
| QM Master Inspection Characteristic | Master Inspection Characteristic | 320 | QPMK | S_QPMK |
| Work Center | Work Center | 3604 | CRHD | S_CRHD |

### Path per object (SAP-sanctioned)
1. **Stage** the source rows into the MC staging table (direct HANA — `hana_staging.load_staging`, programmatic, no file-size cap).
2. **Prepare → Simulate → Migrate** via the MC OData runtime — **programmatic once the gate above is satisfied**; today it needs the one-time activation/LTMC step noted above.
3. **Read results** (application log / transfer list) back by API into the same reconcile path.

> Honest status: the routing + staging are buildable now; the automated RUN is gated on a one-time client Basis action (activate the MC OData service, or create the project in LTMC once). This is a target-activation prerequisite, not a tool gap — the same objects run at volume through this lane once it's satisfied. Full loop detail: `UNIFIED_PLAN.md` MC-1..MC-4.