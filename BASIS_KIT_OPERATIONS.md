# migrate4hana Basis Kit — Operations Reference

**Kit version:** 1.1 · **Doc updated:** 2026-07-16 · **Code home:** `lambda/utils/basis_kit_installer.py`

The Basis Kit is a small, scoped, auditable set of Z-namespace function modules installed
**once** on the target S/4HANA system. After that one install, every migrate4hana migration
runs 100% over RFC — no SSH, no per-migration SAP GUI steps. This document is the single
reference for what the kit contains, how to install it (including on a brand-new CAL
instance), every operation migrate4hana performs through it, and every failure mode we have
hit and solved.

---

## 1. What the kit is (and why it exists)

Enterprises do not allow SSH into SAP systems, and modern S/4 releases removed the generic
"run arbitrary ABAP over RFC" functions (`RFC_ABAP_INSTALL_AND_RUN` is gone on 1809+).
The kit replaces both with the **enterprise-acceptable pattern**: a Basis admin reviews and
installs a handful of small, whitelisted, RFC-enabled function modules ONE time. From then
on migrate4hana calls only those functions.

Security properties (what a customer's Basis/security team will ask):

- **No arbitrary code execution.** Nothing in the kit takes ABAP source as input and runs it.
- **Whitelisted table writes only.** `Z_M4H_TABLE_UPDATE` refuses any table outside its
  hard-coded 10-table customizing whitelist.
- **Single-object number-range changes.** No bulk operations; one named interval per call.
- **Fully uninstallable.** Delete function group ZM4H + 3 DDIC types + 1 role — done.
- **Auditable.** Every call can be logged (Z_M4H_HEALTH_LOG / ZM4H_LOG); sources are ~500
  lines total and reviewable in one sitting.

## 2. Kit contents

| Component | Type | Purpose |
|---|---|---|
| `ZM4H_ABAP_LINE` | DDIC structure | One CHAR255 line (**must be CHAR255, not STRING** — DDIC rejects STRING as a component type; live-verified error: "could not determine structure width") |
| `ZM4H_ABAP_LINES` | DDIC table type | Table of `ZM4H_ABAP_LINE` — used to pass key-value lists |
| `ZM4H_LOG_ROW` | DDIC structure | TIMESTAMP / LEVEL / MSG for the optional audit log |
| `Z_M4H_STATUS` | RFC FM | Read-only: kit version, install timestamp, caller, health |
| `Z_M4H_NR_MODIFY` | RFC FM | Flip EXTERNIND on an **existing** number-range interval |
| `Z_M4H_NR_MAINTAIN` | RFC FM | **Create** a number-range interval (from/to/extern) |
| `Z_M4H_TABLE_UPDATE` | RFC FM | Whitelisted customizing writes (e.g. point TVAK.NUMKE at an interval) |
| `Z_M4HTABLE_UPSERT` | RFC FM | **v1.1** — full-row customizing upserts (material groups, exchange-rate config, …); replaces the SE38 prep-script paste |
| `Z_M4H_HEALTH_LOG` | RFC FM | Audit-trail probe (works with or without the ZM4H_LOG table) |
| `ZM4H_MIGRATION_ADMIN` | PFCG role | S_RFC on FUGR ZM4H + S_NUMBER 02/03 + S_TABU_DIS on the 10 tables (optional on CAL trials where the RFC user has SAP_ALL) |

**Table whitelist for `Z_M4H_TABLE_UPDATE`** (and the key field used per table):

| Table | Key field | What it customizes |
|---|---|---|
| TVAK | AUART | Sales order types → number range (NUMKE) |
| TVLK | LFART | Delivery types |
| TVFK | FKART | Billing types |
| T161 | BSART | Purchasing document types |
| TB003 | BU_GROUP | Business-partner groupings |
| T077K | KTOKD | Customer account groups |
| T077Y | KTOKK | Vendor account groups |
| T134 | MTART | Material types |
| T003O | AUART | Internal-order types |
| T093B | ANLKL | Asset classes |

## 3. Installing the kit (fresh S/4 instance runbook)

This is the exact sequence for a **new CAL instance** (what we'll do after the 2026-07-14
termination). Total hands-on time ≈ 20–30 minutes, once.

### 3.0 Prerequisites (SAP GUI, as the admin user)

1. Create the RFC user if it doesn't exist: SU01 → user `MIGRATE_ADMI`, type
   Dialog (or Service), assign SAP_ALL on CAL trials (no PFCG available there).
2. Tell migrate4hana the connection: update `connections.json` → `s4hana.ashost`
   with the new IP, and set the password env var (PowerShell):
   ```powershell
   $env:M4H_TARGET_PASSWD = '<password>'   # set inline per command/session
   ```

### 3.1 Get the install scripts from migrate4hana

Two ways to obtain identical content:

- **UI:** Project wizard → "Prepare S/4 target" panel → Basis Kit section →
  Download / Copy buttons.
- **API:**
  `POST /api/pipeline/basis-kit/install.abap` → the SE38 bootstrap report
  `POST /api/pipeline/basis-kit/fm-sources.abap` → the 5 FM sources bundle

### 3.2 Create the DDIC types + function group (SE38 report)

1. SE38 → create program `ZM4H_KIT_INSTALL` (type: Executable program, save as Local Object).
2. Paste the install report, activate (Ctrl+F3), execute (F8).
3. It creates `ZM4H_ABAP_LINE`, `ZM4H_ABAP_LINES`, `ZM4H_LOG_ROW` and function group `ZM4H`.

### 3.3 Create the 5 function modules (SE37, one at a time)

For each FM in the bundle (`Z_M4H_STATUS`, `Z_M4H_NR_MODIFY`, `Z_M4H_NR_MAINTAIN`,
`Z_M4H_TABLE_UPDATE`, `Z_M4H_HEALTH_LOG`):

1. SE37 → Function Module → Create → name exactly as above, function group `ZM4H`.
2. **Attributes tab → Processing Type → tick "Remote-Enabled Module".**
   (Skipping this causes `CALL_FUNCTION_NOT_REMOTE` at runtime — we hit this live.)
3. Import/Export/Tables tabs: enter the parameters exactly as declared in the
   `*"Local Interface:` comment block of each source (names, types, defaults).
4. Source Code tab: paste ONLY the body (between `FUNCTION …` and `ENDFUNCTION.`).
   **Do not paste a second `FUNCTION Z_…` header into an existing FM** — duplicate
   FUNCTION declarations are a syntax error; each FM is its own object.
5. Activate.

### 3.4 Verify from migrate4hana (no GUI needed after this point)

- **API:** `POST /api/pipeline/basis-kit/verify` — calls `Z_M4H_STATUS` and dry-probes
  the two write FMs with non-existent keys (expects "not found" / "0 rows updated").
- The **preflight panel** (wizard section 8) runs the same checks as rows 4/7/8 of its
  10-check table before any migration is allowed to start.

## 4. FM reference — signatures and pyrfc calls

### 4.1 Z_M4H_STATUS (read-only)

```
EXPORTING  EV_VERSION TYPE STRING, EV_INSTALL_TS TYPE STRING,
           EV_USER TYPE SY-UNAME, EV_KIT_HEALTH TYPE STRING
```
```python
conn.call("Z_M4H_STATUS")   # -> {'EV_VERSION': 'M4H_KIT_1.0', 'EV_KIT_HEALTH': 'OK', ...}
```

### 4.2 Z_M4H_NR_MODIFY — flip the external flag on an EXISTING interval

```
IMPORTING  IV_OBJECT CHAR10, IV_SUBOBJECT CHAR6 DEFAULT ' ',
           IV_INTERVAL_NR CHAR02, IV_EXTERN CHAR01 DEFAULT 'X'
EXPORTING  EV_STATUS TYPE BAPI_MSG
```
```python
r = conn.call("Z_M4H_NR_MODIFY", IV_OBJECT="RV_BELEG", IV_INTERVAL_NR="02", IV_EXTERN="X")
# r["EV_STATUS"] -> "OK: interval 02 on RV_BELEG flipped to extern=X"
#                or "OK: ... (already had extern=X)"   <- NR 009 mapped to idempotent OK
#                or "ERROR: interval 02 not found on RV_BELEG"
```
Reads the existing NRIV row first (preserves FROMNUMBER/TONUMBER), sets `PROCIND='M'`,
then `NUMBER_RANGE_INTERVAL_UPDATE` + `NUMBER_RANGE_UPDATE_CLOSE` + COMMIT.

### 4.3 Z_M4H_NR_MAINTAIN — CREATE a new interval

```
IMPORTING  IV_OBJECT CHAR10, IV_INTERVAL_NR CHAR02 DEFAULT 'A1',
           IV_FROM CHAR20, IV_TO CHAR20, IV_EXTERN CHAR01 DEFAULT 'X'
EXPORTING  EV_STATUS TYPE BAPI_MSG
```
```python
r = conn.call("Z_M4H_NR_MAINTAIN", IV_OBJECT="EINKBELEG", IV_INTERVAL_NR="M4",
              IV_FROM="3000000000", IV_TO="3099999999", IV_EXTERN="X")
# "OK: interval M4 on EINKBELEG (created)"  or  "(already existed)"
```

### 4.4 Z_M4H_TABLE_UPDATE — whitelisted customizing write

```
IMPORTING  IV_TABLE CHAR30, IT_KEY_VALUES ZM4H_ABAP_LINES,
           IV_FLAG_FIELD CHAR30 DEFAULT 'NUMKE', IV_FLAG_VALUE CHAR02 DEFAULT 'A1'
EXPORTING  EV_STATUS STRING, EV_ROWS_UPDATED I
```
```python
r = conn.call("Z_M4H_TABLE_UPDATE", IV_TABLE="TVAK",
              IT_KEY_VALUES=[{"LINE": "TA"}, {"LINE": "OR"}],
              IV_FLAG_FIELD="NUMKE", IV_FLAG_VALUE="02")
# r["EV_ROWS_UPDATED"] -> 2 ; r["EV_STATUS"] -> "OK: 2 rows updated, 0 errors"
```
Rows that don't exist count as errors in EV_STATUS but never abort the call.
Non-whitelisted tables return `ERROR: table X not in kit whitelist` and write nothing.

### 4.5 Z_M4HTABLE_UPSERT (v1.1) — full-row customizing upsert over RFC

```
IMPORTING  IV_TABLE CHAR30, IV_FIELDS CHAR255 (comma-separated field names),
           IT_ROWS TYPE SOLI_TAB (pass value; pipe-delimited values per row)
EXPORTING  EV_STATUS BAPI_MSG, EV_ROWS_UPSERTED I, EV_ROWS_FAILED I
```
(IT_ROWS is an IMPORTING table-type param — classic TABLES params are flagged
"obsolete" by SE37. It is typed **SOLI_TAB**, not ZM4H_ABAP_LINES: the kit's own
table type was created with a GENERIC key, which RFC interfaces refuse
("no generic types allowed"). Same live pattern as Z_M4H_TABLE_UPDATE.)
```python
from basis_kit_installer import push_rows_via_kit
r = push_rows_via_kit(conn, "T023", ["MATKL", "BKLAS"],
                      [{"MATKL": "002"}, {"MATKL": "004"}])
# r -> {"upserted": 2, "failed": 0, ...}
```
**Guardrail — stronger than a name whitelist:** the FM reads the table's
delivery class from DD02L and refuses anything that isn't C/G/E/S
(customizing). It can never write master or transaction data, no matter what
table name is passed. MODIFY semantics → idempotent re-runs; MANDT is stamped
server-side. Values must not contain `|` (pipe is the row delimiter).

**Why it exists:** kit v1.0 still needed one SE38 paste per migration for prep
rows (material groups, TCURV/TCURF, …). v1.1 closes that: the ONLY SE38/SE37
touch on a target is the one-time kit install itself.
`apply_prep_scan_via_kit(conn, scan)` pushes a whole abap_generator scan.

### 4.6 Z_M4H_HEALTH_LOG

```
IMPORTING IV_LAST_N I DEFAULT 100   EXPORTING EV_TOTAL I, EV_STATUS STRING
```
Returns the audit-log row count if the optional ZM4H_LOG table was created, else a
clean "audit trail disabled" status.

## 5. Operations migrate4hana performs through the kit

These are driven by `preservation_planner.apply_approved_plan()` (API:
`POST /api/pipeline/preservation-plan/apply`; called automatically in Auto mode):

| Strategy | Kit calls | What happens on the target |
|---|---|---|
| **A** — point at existing external interval | `Z_M4H_TABLE_UPDATE` | e.g. TVAK.NUMKE for the doc types → the external interval number; documents keep their ECC numbers if they fit that interval's range |
| **B** — modify SAP-shipped interval | `Z_M4H_NR_MODIFY` | flips EXTERNIND on the interval the doc type already uses (needs Basis approval; auto-downgraded to next-best in support-safe mode) |
| **C** — shift keys via offset | none (loader-side) | source keys shifted by an offset into a free external band; `M4H_KEY_SHIFT_<OBJ>` env |
| **D** — renumber + ledger | none | target assigns numbers; key_mapping.json is the cross-reference |
| *(planned)* **interval-coverage extension** | `Z_M4H_NR_MAINTAIN` | create additional external intervals covering source number bands that no existing interval spans (closes the AUTO2 OpenPO gap: 9,619 × "Document number not within defined interval") |

The **preflight verifier** (10 checks) probes `Z_M4H_STATUS`, dry-calls `Z_M4H_NR_MODIFY`
with a non-existent interval and `Z_M4H_TABLE_UPDATE` with a non-existent key — proving
the FMs run without changing anything — before any migration button unlocks.

## 6. Hard-earned platform lessons (do not re-learn these)

Every item below cost a live debugging round; the kit sources already encode them.

1. **`EV_STATUS` must be `BAPI_MSG`, not `STRING`** — the RFC layer rejects STRING exports
   on these FMs ("not half baked" iteration with the user, 2026-07-12).
2. **INRIV's external flag field is `EXTERNIND`, not `EXTERN`.**
3. **`PROCIND` is mandatory:** `'I'` to insert an interval, `'M'` to modify one. Without it
   `NUMBER_RANGE_INTERVAL_UPDATE` silently no-ops and returns NR 009.
4. **NR 009 ("no changes") is often SUCCESS** — it means "already in the requested state".
   Both NR FMs map it to an idempotent `OK … (already existed)`.
5. **`EXCEPTIONS OTHERS = 4` is required** on the `CALL FUNCTION` — NR 009 is raised as a
   MESSAGE of type E, which **bypasses TRY/CATCH** and would dump the FM otherwise.
6. **`NUMBER_RANGE_INTERVAL_UPDATE` real signature (FUPARAREF-verified on S/4 2020):**
   ERROR is an EXPORT of type `INRER` (fields MSGNR/TABLENAME/FIELDNAME/TABIX — *not*
   NRMESSAGE), and `ERROR_IV` is a **mandatory TABLES** parameter of type INRIV.
7. **DDIC structures cannot contain STRING** → `ZM4H_ABAP_LINE.LINE` is CHAR255.
8. **Remote-Enabled radio button** in SE37 Attributes, or `CALL_FUNCTION_NOT_REMOTE`.
9. **One FUNCTION header per FM** — never paste a second `FUNCTION Z_…` block into an
   existing module; create a new FM instead.
10. **SAP number ranges are structurally internal-or-external by design**: an interval that
    a doc type uses for *internal* numbering often cannot simply be flipped external
    (NR 009 rejection with no change). That is why Strategy B is frequently inapplicable
    and the planner auto-downgrades it — expect A (point at an existing external interval)
    or interval creation via `Z_M4H_NR_MAINTAIN` to do the real work.
11. **`RFC_READ_TABLE` rejects `IN (…)` predicates** on hardened systems ("suspicious WHERE
    condition") — the kit's callers issue one query per key instead.
12. **A long-lived RFC connection can die mid-run** (and does, if the CAL suspends or
    terminates); calls then fail with "connection is closed". Late-run loaders and the
    reconciler must expect this (auto-reconnect is on the roadmap, task #343).
13. **SE37 flags classic TABLES parameters as "obsolete"** on modern releases — declare
    RFC table inputs as IMPORTING parameters typed with a DDIC table type and
    pass-by-value instead. The FM body (`LOOP AT it_rows`) is identical either way;
    pyrfc calls it identically too.
14. **RFC interfaces refuse generic types** ("no generic types are allowed") — the kit's
    `ZM4H_ABAP_LINES` table type was created with a generic key (DD40L KEYKIND=G), so
    it can't type an RFC parameter. Use standard **SOLI_TAB** (row = SOLI, one LINE
    CHAR255 field) for 255-char line tables — it's on every system and RFC-clean; the
    live `Z_M4H_TABLE_UPDATE` was already using it.
15. **`&&` concatenation takes character-like operands only** — integers (`TYPE i`) in a
    status message must be embedded in the string template as `{ ev_count }`, not
    chained with `&&` (activation fails with a hard syntax error in the function group,
    which then breaks ALL kit FMs until fixed).

## 7. Uninstall

1. SE80 → Function Group `ZM4H` → delete (removes all 5 FMs).
2. SE11 → delete `ZM4H_ABAP_LINE`, `ZM4H_ABAP_LINES`, `ZM4H_LOG_ROW`.
3. PFCG → delete role `ZM4H_MIGRATION_ADMIN` (if created).

No SAP standard object is modified by the kit at any point; uninstall leaves zero residue.

## 8. Current status

- Kit v1.0 was installed and fully verified on the S/4 2020 CAL instance
  (35.168.102.2) — that instance was **terminated by AWS on 2026-07-14**, so the kit
  must be reinstalled on the replacement instance using §3 of this document.
- All FM sources in `basis_kit_installer.py` are the live-debugged, working versions;
  reinstall is copy-paste, no rediscovery needed.
