# Deprecated Lambdas (kept for reference)

These handlers were authored for the **in-place SUM/DMO conversion** model
that lives on `aws-branch`. The `aws-lift-and-shift` branch uses a
different mechanism — a brand-new S/4HANA target stood up alongside ECC,
with data and code shipped over via SAP-shipped tools (Migration Cockpit,
LTMOM, IDoc inbound, CTS+/abapGit).

## What's here

| Handler | Why it's deprecated for lift-and-shift |
|---|---|
| `sum-orchestrator/` | SUM is the in-place conversion engine — there is no SUM step in greenfield. Reusable patterns (SSM Run Command, SM37 job watch, host-log collection) have been extracted to `lambda/utils/sap_host_runner.py`, `sap_job_monitor.py`, `sap_log_collector.py`. |
| `maintenance-planner/` | Maintenance Planner produces the SUM stack.xml. Greenfield S/4HANA installations use a different download-basket mechanism (driven by the `target-provisioner` Lambda). Some of the planner's add-on/Note logic could still be useful for greenfield — see `sap_note_planner.py` (TODO). |

## Why we kept them instead of deleting

1. Reference for the patterns above (3,800+ lines of SAP RFC orchestration).
2. The `aws-branch` is preserved unchanged, but a future maintainer working
   from the lift-and-shift branch may need to see how SUM was driven.
3. Some customer engagements may need a **hybrid** (in-place for some
   landscape components + lift-and-shift for ERP). Restoring these is then
   a `git mv` away.

## What the static-scan test thinks

`tests/test_no_direct_writes.py` excludes `lambda/_deprecated/` so these
files do not block the build even though they call forbidden write FMs
in the lift-and-shift world.
