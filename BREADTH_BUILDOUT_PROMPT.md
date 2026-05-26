# Prompt — Migrate4HANA breadth build-out: load + reconcile ALL natural object candidates

> **When to run this:** ONLY after the audit of the unverified end-to-end stages
> (`code-analyzer` / `simplification-check` / `transport-*`) is complete and those
> stages are production-grade. This phase is about *breadth of the data-migration spine*,
> not the assessment/remediation/transport stages.
>
> **How to use:** paste everything below into a fresh Claude Code session on this repo.
> It is self-contained: context + principles + the exact proven per-object recipe +
> the candidate backlog + acceptance criteria.

---

## Mission

Extend live, **support-clean, reconciled** load coverage from the **11 objects proven today**
toward the full SAP S/4HANA Migration Cockpit catalog (~120 standard objects; ~40–60 of
them fit our released-BAPI/OData spine cleanly). Do it **production-grade, one object at a
time**, each proven on a **live ECC→S/4 run with a RECONCILED verdict before commit**.

Already live + reconciled (do NOT redo): BusinessPartner, Customer/Vendor (OData),
Material, ExchangeRates, OpenPO, OpenAR, OpenAP, CostCenter, ProfitCenter, FixedAsset.

## What the tool is (context)

Migrate4HANA is a support-clean ECC→S/4HANA **data-migration + reconciliation + cutover
engine** (Greenfield / selective lane — NOT Brownfield/SUM/DMO). A single dispatcher
(`UnifiedLoader`) picks the best **SAP-released** mechanism per object; auto-discovery adapts
to the target landscape; every object is reconciled and attested. See `CAPABILITY_DOSSIER.md`.

## Non-negotiable principles (production-grade or don't ship it)

1. **Released SAP APIs only** — BAPI or released OData. NEVER raw table writes, arbitrary
   ABAP, `SE16N` edits, or any SUM/Maintenance-Planner bypass. Every write must keep SAP support intact.
2. **Landscape-agnostic** — discover all org units / accounts / config from the *target*
   system (prefer values that DEMONSTRABLY work, e.g. read from real existing records).
   Env-overridable. Never hardcode an appliance-specific value.
3. **Idempotent** — cross-run ledger (`migration-ledger/key_mapping.json`); a re-run RESUMES,
   never duplicates. Source key registered per object in `OBJECT_SOURCE_KEY`.
4. **Reconcile everything** — read every loaded record back; tie out existence (created ==
   verified) and value where a value exists. Emit a hard `RECONCILED` / `DISCREPANCY` verdict.
5. **No silent corruption** — collision-safe keys; when you must remap (number range, asset
   class, company code), record the remap transparently in `key_mapping`/messages. Genuine
   failures go to the **dead-letter**, never an inline retry that could double-post.
6. **Probe-first, never guess** — introspect the API live and **TESTRUN/dry-run-validate the
   exact call shape BEFORE writing the loader** (FixedAsset proved this saves rework).
7. **Honest evidence** — commit an object only after a **live run shows RECONCILED**, and put
   the numbers (extracted/created/verified) in the commit message.

## The proven per-object recipe (follow exactly)

1. **Connectivity** — run the prerequisites below FIRST.
2. **Map it** — ECC source table(s) + key; the released create API; target table + reconcile key.
3. **Probe live** — `conn.get_function_description("<BAPI>")` → IMPORT/EXPORT/TABLES + the field
   names of each key structure. Read a real sample SOURCE record (ECC) and a real TARGET record (S/4).
4. **Validate the call** — build the minimal call and dry-run it against S/4 until it passes
   (`TESTRUN='X'` where supported; otherwise create + `BAPI_TRANSACTION_ROLLBACK`).
5. **Loader** — add `create_<object>` + `_<object>_exists` to `lambda/utils/bapi_loader.py`
   (idempotent; rollback on E/A; commit on success; return `status`, `verify_key`,
   `key_mapping`, `messages`). For OData objects use/extend `odata_client.py` / `bp_odata.py`.
   Handle source→target config differences via discovery + a transparent fallback (see
   `create_fixed_asset`'s `_asset_class_valid` cached TESTRUN fallback as the template).
6. **Discovery** — add any needed config to `lambda/utils/config_discovery.py`, choosing
   values proven on the target (most-common among real records); env-overridable; add to the
   returned dict + `summary`.
7. **Dispatcher** — `lambda/utils/unified_loader.py`: add `OBJECT_SOURCE_KEY[...]`,
   `OBJECT_MECHANISM[...]`, a `_load_one` branch, and (if it needs its own config) a new
   `self.<x>_org` attribute initialized in `__init__` and copied in `_make_worker`.
   Add to `PARALLEL_MECHS` only if it's safe to parallelize (per-document, no shared sequence).
8. **Handler** — `lambda/data-migrator/handler.py`: add a `DEFAULT_OBJECT_TABLES` entry
   (source table + fields + lane) and set `loader.<x>_org = _cfg.get("<x>", {})` in the
   discovery wiring block.
9. **Live proof** — extract real rows from ECC → `loader.load_object(obj, rows, N)` →
   `Reconciler(loader.c).reconcile(obj, load, extracted=len(rows))`. **Require `status ==
   RECONCILED`, `missing == 0`.** Then re-run to confirm **0 duplicates** (idempotency).
10. **Hygiene** — `ast.parse` every edited file; delete temp probe scripts (`.*_probe.py`).
11. **Commit** — one object per commit, live reconcile numbers in the message; bump the
    object count + table in `CAPABILITY_DOSSIER.md`. End message with the standard
    `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` line.

## Files you touch every time

- `lambda/utils/bapi_loader.py` (BAPI objects) or `lambda/utils/odata_client.py`/`bp_odata.py` (OData)
- `lambda/utils/config_discovery.py`
- `lambda/utils/unified_loader.py` — `OBJECT_SOURCE_KEY`, `OBJECT_MECHANISM`, `_load_one`, `_make_worker`
- `lambda/data-migrator/handler.py` — `DEFAULT_OBJECT_TABLES`, `loader.<x>_org` wiring
- `CAPABILITY_DOSSIER.md` — count + table

## Connectivity prerequisites (do FIRST — these eat sessions if skipped)

- **Passwords via env**: `M4H_ECC_PASSWD`, `M4H_TARGET_PASSWD`; set `SAPNWRFC_HOME=sapnwrfc`.
- **ECC** (sysnr 41 → port 3341, client 800, user `sapuser`): VM on the **host-only** adapter
  (`192.168.100.x`). SAP often isn't auto-started after a VM boot — `WSAECONNREFUSED` on
  3341 = host up, SAP down. IP drifts on VM restart → get fresh `ipconfig`, update
  `connections.json` → `ecc.ashost`.
- **S/4** (sysnr 00, client 100, user `MIGRATE_ADMI`): AWS public IP **drifts on EVERY
  restart**. Repoint the Windows hosts file (needs admin):
  `$h="$env:windir\System32\drivers\etc\hosts"; Set-Content $h @("<IP> vhcals4hci.dummy.nodomain","<IP> vhcals4hcs.dummy.nodomain"); Get-Content $h`
- **CRITICAL gotcha**: `timeout during allocate / no connect of TP sapdp00 from host <IP>`
  where `<IP>` is the OLD address = **STALE HOSTS, not ABAP startup**. SAP's gateway accepts
  the connection then re-resolves the appliance hostname for the work-process allocate, so a
  raw-IP connect does NOT bypass it. Fix = repoint hosts to the CURRENT IP and connect **by
  hostname** (`vhcals4hci.dummy.nodomain`). Do not wait for "ABAP to finish starting" — it's up.
- **Permanent fix**: assign an **AWS Elastic IP** to the S/4 instance so the IP stops drifting.

## Candidate backlog (ordered by value; ~25–30 named, long tail to ~120)

Build **master data before transactional/balances** (dependencies), highest-reuse first.

| Wave | Domain | Object → released API |
|---|---|---|
| 1 | CO master | Internal Order `BAPI_INTERNALORDER_CREATE`; Activity Type `BAPI_ACTIVITYTYPE_CREATEMULTIPLE`; Statistical Key Figure |
| 1 | FI master | G/L Account `BAPI_GL_ACC_CREATE`/`...GLACC`; Bank master `BAPI_BANK_CREATE` |
| 2 | MM master | Purchasing Info Record `BAPI_INFORECORD_*`; Source List; Batch master; Material extensions |
| 2 | Classification | Characteristic `BAPI_CHARACT_CREATE`; Class `BAPI_CLASS_CREATE` |
| 3 | Balances/open | G/L balances `BAPI_ACC_DOCUMENT_POST`; Inventory/stock `BAPI_GOODSMVT_CREATE`; Open Sales Orders `BAPI_SALESORDER_CREATEFROMDAT2`; Purchase Requisitions `BAPI_PR_CREATE`; Open Deliveries |
| 4 | PP | BOM `CSAP_MAT_BOM_MAINTAIN`; Routing; Work Center; Production version |
| 4 | PM/PS | Equipment `BAPI_EQUIPMENT_CREATE`; Functional Location; WBS/Project `BAPI_PROJECT_MAINTAIN` |
| 5 | SD pricing | Conditions/pricing `BAPI_PRICES_CONDITIONS` |

For the exact catalog on THIS S/4 release, query the system's Migration-Cockpit object list
and reconcile against this backlog before starting (some objects are file-load-only in the MC,
or are customizing best moved by transport — document WHY each non-fit object is skipped).

## Definition of done

**Per object:** live run with `created == verified_in_target`, `missing == 0`, status
`RECONCILED`; idempotent re-run creates 0 duplicates; writes use released APIs only; committed
with evidence; dossier updated.

**Per phase:** every spine-fit object (~40–60) loads + reconciles live, OR each non-fit object
is documented with the reason it can't/shouldn't follow this pattern.

## Honest expectation

"Follows the proven pattern" means the *architecture* absorbs each object — but each still
costs a real probe→validate→discover→wire→reconcile cycle (FixedAsset *fit the pattern* and
still took the full cycle). Realistic pace: ~1–3 solid objects per focused session.
