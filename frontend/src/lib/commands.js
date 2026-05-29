// Catalog of everything the platform can do from the terminal.
// The UI surfaces each as a clickable option that reveals its exact command.

export const COMMAND_GROUPS = [
  {
    id: 'pipeline',
    title: 'Migration Pipeline',
    icon: 'GitBranch',
    accent: 'indigo',
    commands: [
      { id: 'assess', label: 'Run Assessment', cmd: 'python run_local_lift_and_shift.py --through stage21', desc: 'Phases 1–2 — discovery, readiness, simplification, code & data assessment (read-only).' },
      { id: 'full', label: 'Full Lift & Shift', cmd: 'python run_local_lift_and_shift.py --run-id RUN-001', desc: 'All 28 stages end-to-end: assess → provision → code → config → data → validate → cutover.' },
      { id: 'list-stages', label: 'List Stages', cmd: 'python run_local_lift_and_shift.py --list-stages', desc: 'Print the ordered stage table and exit.' },
    ],
  },
  {
    id: 'spine',
    title: 'Master Spine (4-layer)',
    icon: 'Layers',
    accent: 'violet',
    commands: [
      { id: 'spine-run', label: 'Run Master Spine', cmd: 'python pipeline_spine_master.py', desc: 'Natuvion → Syniti → SmartShift → Governance, with RFC throttling. Writes progress.json.' },
      { id: 'spine-payload', label: 'Run from Payload', cmd: 'python pipeline_spine_master.py --payload run.json', desc: 'Drive the spine from a state-machine payload (identical local/cloud contract).' },
    ],
  },
  {
    id: 'natuvion',
    title: 'Natuvion — Carve-Out',
    icon: 'Scissors',
    accent: 'teal',
    commands: [
      { id: 'carve', label: 'Generate Carve-Out ABAP', cmd: 'python agent/in_system_agent_generator.py', desc: 'Emit org/time-filtered, cursor-streamed, dependency-aware in-system extraction ABAP.' },
    ],
  },
  {
    id: 'syniti',
    title: 'Syniti — Data Spine',
    icon: 'Database',
    accent: 'sky',
    commands: [
      { id: 'spine-self', label: 'Run Data Spine Self-Test', cmd: 'python data_spine_orchestrator.py', desc: 'FK integrity (BUT000/020/100), deterministic self-heal, SHA-256 idempotency ledger.' },
    ],
  },
  {
    id: 'smartshift',
    title: 'SmartShift — Code Fix',
    icon: 'Code2',
    accent: 'amber',
    commands: [
      { id: 'fix', label: 'Run Code Remediation', cmd: 'python lambda/code-analyzer/llm_fallback_router.py', desc: 'Deterministic AST fix; AI fail-safe for crashes; mock-ATC gate → transport or quarantine.' },
    ],
  },
  {
    id: 'stress',
    title: 'Stress / Synthetic Data',
    icon: 'FlaskConical',
    accent: 'rose',
    commands: [
      { id: 'gen', label: 'Generate Synthetic Data', cmd: 'python scripts/stress_test_generator.py', desc: 'Faker + deterministic SAP rows → Parquet, with 1% chaos injection. (Local self-test.)' },
      { id: 'gen-10m', label: '10M-Row AWS Fan-Out', cmd: '# 100 Lambda workers × 100k rows → S3 Parquet (see runbook)', desc: 'Serverless fan-out for the 10M-row stress test. User-executed on AWS.' },
    ],
  },
  {
    id: 'reports',
    title: 'Reports & API',
    icon: 'FileText',
    accent: 'indigo',
    commands: [
      { id: 'api', label: 'Start API Server', cmd: 'python api_server.py', desc: 'FastAPI on :8000 — pipeline triggers, gates, runs, PDF report endpoints.' },
      { id: 'ui', label: 'Start UI (dev)', cmd: 'cd frontend && npm run dev', desc: 'This dashboard, on http://localhost:3000.' },
    ],
  },
];

// flat lookup by id (so action buttons can reference a command)
export const COMMANDS = Object.fromEntries(
  COMMAND_GROUPS.flatMap((g) => g.commands.map((c) => [c.id, { ...c, group: g.title, accent: g.accent }]))
);
