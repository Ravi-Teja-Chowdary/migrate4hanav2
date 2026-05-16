# ECC lock-down runbook — run_id=RUN-FRESH, SID=ERP

1. Broadcast SM02 system message: 'Migration cutover in progress, system read-only as of <time>'.
2. SU10 mass-lock all non-Basis users (exclude DDIC, SAP*, BASIS, and the migration service users).
3. RZ04 disable batch-job operation modes for application servers.
4. SMQR / SMQS deregister all queues to stop inbound IDoc/qRFC.
5. SE16 -> TBTCO: cancel scheduled jobs that would create new data.
6. Set RFC destinations from external systems to UNREACHABLE so they queue rather than write to ECC.
7. Confirm zero new entries in CDHDR for the past 5 minutes before proceeding to delta extract.
