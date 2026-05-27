# abapGit setup on the S/4HANA CAL appliance — to automate transport build + code shipping

*Why: abapGit robustly handles the one step the raw CTS function modules choke on in a non-dialog
context — creating/recording repository objects into a transportable package + transport. It's the
standard, support-clean (100% released ABAP) tool used across the SAP world, and it doubles as the
mechanism for shipping `code-analyzer`'s remediated ABAP into S/4. Once it's in, the Migrate4HANA
in-system agent can drive it over RFC to build transports automatically.*

---

## Two modes — we start with OFFLINE (simplest), then optionally ONLINE

| Mode | What it needs | What it gives |
|---|---|---|
| **OFFLINE** *(start here)* | just the abapGit **standalone report** installed (no git host, no SSL/STRUST, no internet from S/4) | import/export objects as a **ZIP** → deserialize into a transportable package + record to a transport. Enough to **certify Gap #4** and to ship remediated code via ZIP. |
| **ONLINE** *(automation upgrade)* | git repo + **STRUST** SSL cert + abapGit developer version | full git **pull/push** automation (push remediated code from our side → S/4 pulls → records to a transport). The end-state "maximum automation". |

You picked abapGit — let's do **OFFLINE first** (it unblocks everything and needs no STRUST/git), then ONLINE when you want full git automation.

---

## Part A — OFFLINE abapGit (do this first)

### A1. Install the abapGit standalone report
The standalone version is a **single self-contained ABAP report** (no installation dependencies).

1. On a browser, open the raw standalone source (one file):
   `https://raw.githubusercontent.com/abapGit/build/main/zabapgit_standalone.prog.abap`
   (Save it / copy all of it. It's large — that's expected.)
2. In SAP GUI on S/4 (user `MIGRATE_ADMI`, client 100): transaction **SE38** → Program
   `ZABAPGIT_STANDALONE` → **Create** → type **Executable program** → for package, you can use
   `$TMP` (local) for now or `Z001` (transportable) → paste the entire source → **Save** → **Activate**.
   - If pasting 100k+ lines in the GUI editor is painful: SE38 → *Utilities → More Utilities →
     Upload/Download → Upload* and select the saved `.abap` file, then Activate.
3. Run it (**F8**) once to confirm the abapGit screen appears. ✅

> Tip: if `MIGRATE_ADMI` lacks developer authorization, you may get a prompt for an SSCR developer
> key or an auth error — tell me and I'll confirm the exact role/object (`S_DEVELOP`) you need.

### A2. Tell me — then I drive it
Reply **"abapGit offline ready"**. I will then, via the in-system agent (over RFC):
1. Generate a tiny harmless object (the `ZM4H_TPROBE01` report) as an abapGit-format ZIP from my side,
   stage it to the host (S3 → SSM, the proven path).
2. Drive abapGit's deserialize API (`zcl_abapgit_*`) to import it into package **Z001** and **record it
   to a transport** (abapGit does the TADIR + transport assignment cleanly).
3. Release the transport (`BAPI_CTREQUEST_RELEASE`) → cofile/datafile exported.
4. Run the proven **place → `tp import` → verify** chain and **certify the `tp` return code**.
   → **Gap #4 closed**, with a real transported object.

---

## Part B — ONLINE abapGit (later, for full git automation)

### B1. A git repository
Create a repo on **GitHub** (or GitLab/Azure DevOps/self-hosted). For private repos, create a
**Personal Access Token** (PAT) with `repo` scope — abapGit uses it as the password.

### B2. Trust the git host's SSL cert in S/4 (STRUST)
S/4 must trust the HTTPS endpoint:
1. Get the cert chain: in a browser open `https://github.com`, view the certificate, export the
   **full chain** (the server cert + DigiCert intermediates + root) as Base64 `.cer` files. (I can
   also fetch these for you and hand you the files.)
2. SAP GUI → transaction **STRUST** → **SSL client SSL Client (Standard)** → right-click → *Import
   certificate* for each cert in the chain → **Add to Certificate List** → **Save**.
3. Make sure the ICM allows outbound HTTPS: transaction **SMICM** → the system should have an
   active client; outbound 443 from the EC2 host is open (it already reaches AWS/S3).

### B3. Install the abapGit developer version (online)
With STRUST trusting GitHub, the standalone report (A1) can install the full developer version:
in the standalone abapGit screen → install the online repo `https://github.com/abapGit/abapGit.git`
into package `$ABAPGIT` (it self-installs). Or keep using standalone — both expose the API the agent needs.

### B4. Tell me — then I drive the git flow
Reply **"abapGit online ready"** with the repo URL (+ PAT if private). I'll wire the pipeline so
remediated code is pushed to the repo and S/4 pulls it into a transportable package → transport,
fully automated.

---

## Network / appliance notes (CAL specifics)
- The S/4 EC2 host already has outbound internet (it reaches S3 in our transport tests), so GitHub
  HTTPS will work once STRUST trusts the cert. Online mode adds **no** new inbound exposure.
- Everything stays **support-clean**: abapGit is 100% released ABAP; objects flow into the system
  via the standard repository + **CTS transport** (not raw table writes).

## Cleanup of my earlier probe attempts (anytime, ~1 min)
In transaction **SE09** (or SE10), user `MIGRATE_ADMI`: select the empty unreleased requests
`S4HK903321` … `S4HK903328` (description "M4H transport-chain probe") and **delete** them. The
`$TMP` probe programs (`ZM4H_AGENT_PROBE*`, `ZM4H_TR_BUILDER*`, `ZM4H_TPROBE01`) are local and
harmless; delete in SE38 if you wish. (Or say the word and I'll script the cleanup via the agent.)
