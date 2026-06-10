// Catalog of every terminal-equivalent action the platform exposes.
// Used by the Command Center to surface CLI ops in the UI with parameter
// hints + copyable command. Groups roughly map to the operator's mental
// model (Pipeline / Spine / Connections / Secrets / Tunnels / KeyMap /
// Terraform / Tenant / Battletest / Diagnostics / Reports).

export const COMMAND_GROUPS = [
  {
    id: 'pipeline',
    title: 'Migration Pipeline',
    icon: 'GitBranch',
    accent: 'indigo',
    commands: [
      { id: 'assess',     label: 'Run Assessment',  cmd: 'python run_local_lift_and_shift.py --through stage21', desc: 'Phases 1-2: discovery, readiness, simplification, code & data assessment (read-only).' },
      { id: 'full',       label: 'Full Lift & Shift', cmd: 'python run_local_lift_and_shift.py --run-id RUN-001', desc: 'All 27 stages: assess → provision → code → config → data → validate → cutover.' },
      { id: 'list-stages', label: 'List Stages',     cmd: 'python run_local_lift_and_shift.py --list-stages',     desc: 'Print the ordered stage table and exit.' },
      { id: 'resume',     label: 'Resume Run',      cmd: 'python run_local_lift_and_shift.py --run-id RUN-001 --resume', desc: 'Resume a previously-paused run from its last checkpoint.' },
    ],
  },
  {
    id: 'spine',
    title: 'Master Spine (4-layer)',
    icon: 'Layers',
    accent: 'violet',
    commands: [
      { id: 'spine-run',     label: 'Run Master Spine',   cmd: 'python pipeline_spine_master.py',                     desc: 'Natuvion → Syniti → SmartShift → Governance. Writes progress.json.' },
      { id: 'spine-payload', label: 'Run from Payload',   cmd: 'python pipeline_spine_master.py --payload run.json',  desc: 'Drive the spine from a state-machine payload (identical local/cloud contract).' },
      { id: 'spine-self',    label: 'Data Spine Self-Test', cmd: 'python data_spine_orchestrator.py',                 desc: 'FK integrity (BUT000/020/100), deterministic self-heal, SHA-256 idempotency ledger.' },
    ],
  },
  {
    id: 'connections',
    title: 'Connections',
    icon: 'Server',
    accent: 'sky',
    commands: [
      { id: 'test-rfc',  label: 'Test ECC RFC',       cmd: 'python test_rfc_connectivity.py',  desc: 'Verify pyrfc against the configured ECC. Honest pass/fail with exception detail.' },
      { id: 'diag-login', label: 'Test S/4 Login',    cmd: 'python diag_login.py',             desc: 'Verify S/4HANA RFC + OData login. Useful to confirm secret rotations.' },
      { id: 'launch-tunnel', label: 'Launch ECC Tunnel', cmd: 'powershell scripts/launch-ecc-tunnel.ps1', desc: 'Bring up the ngrok TCP bridge so AWS Lambda can reach the laptop ECC.' },
      { id: 'sync-ips', label: 'Sync IPs',            cmd: 'powershell scripts/sync-ips.ps1',  desc: 'Refresh hosts/Route53 entries after S/4 stop-start or VM IP drift.' },
    ],
  },
  {
    id: 'secrets',
    title: 'Secrets Rotation',
    icon: 'KeyRound',
    accent: 'amber',
    commands: [
      { id: 'ecc-secret',   label: 'Update ECC Secret',     cmd: 'powershell scripts/update-ecc-secret.ps1',        desc: 'Rotate the ECC credentials in AWS Secrets Manager.' },
      { id: 's4-secret',    label: 'Update S/4 Secret',     cmd: 'powershell scripts/update-s4-secret.ps1',         desc: 'Rotate the S/4HANA target credentials.' },
      { id: 'cal-ecc',      label: 'Update CAL ECC Secret', cmd: 'powershell scripts/update-cal-ecc-secret.ps1',    desc: 'Refresh credentials for the SAP CAL IDES appliance.' },
      { id: 'ngrok-ecc',    label: 'Update ngrok ECC Secret', cmd: 'powershell scripts/update-ngrok-ecc-secret.ps1', desc: 'Refresh the ngrok bridge endpoint after a TCP reservation flip.' },
      { id: 'value-maps',   label: 'Manage Value Maps',     cmd: 'powershell scripts/manage-value-maps.ps1',        desc: 'CRUD on value-mapping rules (currencies, units, country codes).' },
    ],
  },
  {
    id: 'keymap',
    title: 'Key-Map Ledger',
    icon: 'Database',
    accent: 'teal',
    commands: [
      { id: 'backup-km',  label: 'Backup Key-Map',  cmd: 'powershell scripts/backup-key-map.ps1',  desc: 'Snapshot the DynamoDB PersistentKeyMap ledger to S3 (versioned, hash-chained).' },
      { id: 'restore-km', label: 'Restore Key-Map', cmd: 'powershell scripts/restore-key-map.ps1', desc: 'Restore the ledger from a versioned S3 snapshot.' },
      { id: 'swap-km',    label: 'Swap Key-Map',    cmd: 'powershell scripts/swap-key-map.ps1',    desc: 'Atomically swap the active ledger (used during environment rotation).' },
    ],
  },
  {
    id: 'tenant',
    title: 'Tenant Onboarding',
    icon: 'Building2',
    accent: 'violet',
    commands: [
      { id: 'onboard',    label: 'Onboard Tenant',  cmd: 'powershell scripts/onboard-tenant.ps1',  desc: 'Provision a new tenant: secrets, key-map partition, evidence bucket prefix.' },
    ],
  },
  {
    id: 'terraform',
    title: 'Terraform / Deploy',
    icon: 'CloudCog',
    accent: 'indigo',
    commands: [
      { id: 'pkg-lambdas', label: 'Package Lambdas', cmd: 'powershell scripts/package-lambdas-with-utils.ps1', desc: 'Bulk re-zip Lambdas with lambda/utils alongside the handler (fixes the archive_file gap).' },
      { id: 'pkg-missing', label: 'Package Only Missing', cmd: 'powershell scripts/package-lambdas-with-utils.ps1 -OnlyMissing', desc: 'Same as above, only for Lambdas missing utils. Fast incremental.' },
      { id: 'push-fargate', label: 'Push Fargate Image', cmd: 'powershell scripts/push-fargate-image.ps1',     desc: 'Build + push the data-loader Fargate container to ECR.' },
      { id: 'tf-plan',    label: 'Terraform Plan',  cmd: 'cd terraform/environments/prod && terraform plan',  desc: 'Preview infrastructure changes.' },
      { id: 'tf-apply',   label: 'Terraform Apply', cmd: 'cd terraform/environments/prod && terraform apply', desc: 'Apply infrastructure changes (confirm carefully).' },
    ],
  },
  {
    id: 'natuvion',
    title: 'Natuvion — Carve-Out',
    icon: 'Scissors',
    accent: 'teal',
    commands: [
      { id: 'carve', label: 'Generate Carve-Out ABAP', cmd: 'python agent/in_system_agent_generator.py', desc: 'Org/time-filtered, cursor-streamed, dependency-aware in-system extraction ABAP.' },
    ],
  },
  {
    id: 'smartshift',
    title: 'SmartShift — Code Fix',
    icon: 'Code2',
    accent: 'amber',
    commands: [
      { id: 'fix',          label: 'Run Code Remediation',    cmd: 'python lambda/code-analyzer/llm_fallback_router.py', desc: 'Deterministic AST fix; AI fail-safe; mock-ATC gate → transport or quarantine.' },
      { id: 'ast-scan',     label: 'AST Coverage Scan',       cmd: 'python ast_coverage_scan.py',                     desc: 'Scan source for AST coverage gaps before remediation.' },
    ],
  },
  {
    id: 'stress',
    title: 'Stress / Synthetic Data',
    icon: 'FlaskConical',
    accent: 'rose',
    commands: [
      { id: 'gen',           label: 'Generate Synthetic Data', cmd: 'python scripts/stress_test_generator.py',         desc: 'Faker + deterministic SAP rows → Parquet, with 1% chaos injection.' },
      { id: 'gen-gemini',    label: 'Gemini Dirty-Data Gen',   cmd: 'python scripts/gemini-data-gen.py',                desc: 'Generate synthetic dirty corpora for the SLO gate / spine rejection tests.' },
      { id: 'load-gemini',   label: 'Load Gemini Dirt to ECC', cmd: 'python scripts/load-gemini-to-ecc.py',             desc: 'Push the generated dirty rows into ECC tables to drive end-to-end dirty-data validation.' },
      { id: 'battletest',    label: 'Run Battletest (AWS)',    cmd: 'powershell scripts/run-battletest-aws.ps1',        desc: '1M-sample proof run across all dimensions, with code remediation + iterate-until-clean.' },
      { id: 'parallel-probe', label: 'Parallel Scale Probe',   cmd: 'python parallel_scale_probe.py',                   desc: 'Throughput probe with configurable concurrency.' },
    ],
  },
  {
    id: 'diagnostics',
    title: 'Diagnostics',
    icon: 'Activity',
    accent: 'sky',
    commands: [
      { id: 'bp-probe',     label: 'BP BAPI Probe',     cmd: 'python bp_bapi_probe.py',         desc: 'Live BUPA_CREATE_FROM_DATA / role-attach probe.' },
      { id: 'mat-diag',     label: 'Material Diag',     cmd: 'python material_diag.py',         desc: 'BAPI_MATERIAL_SAVEDATA probe with field coverage classifier.' },
      { id: 'mc-probe',     label: 'MC Role Probe',     cmd: 'python mc_role_probe.py',         desc: 'Migration Cockpit role membership check.' },
      { id: 'idoc-prove',   label: 'IDoc Prove',        cmd: 'python idoc_prove.py',            desc: 'IDoc inbound proof flow.' },
      { id: 'idoc-mat',     label: 'IDoc Post Material', cmd: 'python idoc_post_material.py',   desc: 'Post a single material via IDoc.' },
      { id: 'idoc-setup',   label: 'IDoc Setup Probe',  cmd: 'python idoc_setup_probe.py',      desc: 'Validate SICF/WE20/SM59 wiring for IDoc inbound.' },
      { id: 'partner-chk',  label: 'Check Partner',     cmd: 'python check_partner.py',         desc: 'Look up a Business Partner by various keys to verify creates.' },
      { id: 'fix-admin',    label: 'Fix migrate-admin', cmd: 'python fix_migrate_admin.py',     desc: 'Repair the migrate-admin user/role on a fresh appliance.' },
      { id: 'audit',        label: 'Audit Pipeline',    cmd: 'python audit_pipeline.py',        desc: 'Walk the hash-chained audit ledger for a given run.' },
      { id: 'applog-probe', label: 'AppLog Probe',      cmd: 'python applog_probe.py',          desc: 'Read SAP application-log entries by object/sub-object.' },
    ],
  },
  {
    id: 'vm',
    title: 'VM / Networking',
    icon: 'Network',
    accent: 'teal',
    commands: [
      { id: 'vm-fwd',      label: 'VM Port Forwarder',   cmd: 'powershell scripts/vm-forwarder-range.ps1', desc: 'Range port forwarder for VMnet → ECC reachability.' },
    ],
  },
  {
    id: 'reports',
    title: 'Reports & API',
    icon: 'FileText',
    accent: 'indigo',
    commands: [
      { id: 'api',          label: 'Start API Server',      cmd: 'python api_server.py',                            desc: 'FastAPI on :8000 — pipeline triggers, gates, runs, PDF report endpoints.' },
      { id: 'ui',           label: 'Start UI (dev)',        cmd: 'cd frontend && npm run dev',                      desc: 'This dashboard on http://localhost:5173.' },
      { id: 'pdf-local',    label: 'Render PDF (local)',    cmd: 'python pdf_report_generator.py',                  desc: 'Render a PDF report from a local run artifact directory.' },
      { id: 'pdf-multi',    label: 'Render Multi-Volume',   cmd: 'python multi_volume_report_generator.py',         desc: 'Produce the multi-volume executive report.' },
    ],
  },
];

// flat lookup by id
export const COMMANDS = Object.fromEntries(
  COMMAND_GROUPS.flatMap((g) => g.commands.map((c) => [c.id, { ...c, group: g.title, accent: g.accent }]))
);
