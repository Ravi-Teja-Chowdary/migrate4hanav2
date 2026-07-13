// Project page: brutally honest tracker + Start migration button +
// auto-generated link to LiveOps in a new tab + on-demand PDF.
import React, { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, downloadFile } from '../../lib/api';

// The 8 phases the lift-and-shift runner actually emits. Stage IDs (stage1..
// stage27, gate1/2/3) map to these phases server-side via _STAGE_PHASE_MAP
// in api_server.py. The Project tracker shows ONE row per phase, rolled up
// from however many stages it contains.
// `expected` is the number of real stages the lift-and-shift runner emits
// for each phase (kept in sync with _STAGE_PHASE_MAP in api_server.py).
// Sum is 35, matching ALL_STAGE_IDS below.
const STAGES = [
  { id: 'ASSESS',    label: 'Assess - discovery, sizing, object routing',     expected: 3 },
  { id: 'PROVISION', label: 'Provision - target system + basis gate',         expected: 3 },
  { id: 'CODE',      label: 'Code - analyze, remediate, transport, import',   expected: 6 },
  { id: 'CONFIG',    label: 'Config - replicate customizing + BC sets',       expected: 6 },
  { id: 'DATA_PREP', label: 'Data prep - extract, hygiene, templates',        expected: 3 },
  { id: 'DATA_LOAD', label: 'Data load - Migration Cockpit / LTMOM / IDoc',   expected: 3 },
  { id: 'VALIDATE',  label: 'Validate - completeness + pre-cutover gate',     expected: 4 },
  { id: 'CUTOVER',   label: 'Cutover - lock ECC, delta, final go-live',       expected: 6 },
  { id: 'RUN',       label: 'Run - PDF report + archive',                     expected: 1 },
];
const ALL_STAGE_IDS = [
  'stage1','stage2','stage3','stage4','gate1','stage5',
  'stage6','stage7','stage8','stage9a','stage9b','stage9c',
  'stage10','stage11','stage12','stage12a','stage12b','stage12c',
  'stage13','stage14','stage15','stage16','stage17','stage18',
  'stage19','stage20','stage21','gate2',
  'stage22','stage23','stage24','stage25','stage26','gate3',
  'stage27',
];

export default function Project() {
  const { runId } = useParams();
  const [wizard, setWizard] = useState(null);
  const [progress, setProgress] = useState({ steps: [], stats: null });
  const [starting, setStarting] = useState(false);
  const [activeRun, setActiveRun] = useState(null);   // pipeline run id
  const [err, setErr] = useState('');
  // Defaults to false (extract-only) for safety - flipping this on writes
  // to S/4HANA via BAPIs and is not reversible. We hydrate from wizard
  // state so the choice survives page refresh.
  const [loadToS4, setLoadToS4] = useState(false);
  // Simulation mode routes live BAPIs through TEST_RUN + staging tables;
  // it's only meaningful when loadToS4=true. Default true when the user
  // first flips on live-load, so the very first live run is safe by default.
  const [simulationMode, setSimulationMode] = useState(true);
  // Per-object row cap. Blank = use server default (M4H_LOAD_MAX_ROWS in
  // lambda/data-migrator/handler.py). Wizard user can bump for a bigger
  // sample without editing env vars. Server clamps to [1, 1_000_000].
  const [maxRows, setMaxRows] = useState('');
  // When true, transactional spines pass the source doc number into the
  // BAPI's external-number field so S/4 inherits ECC's VBELN/EBELN/etc.
  // instead of assigning fresh internal-range numbers. Prereq: target
  // S/4 doc types must be marked external range — see PREREQ_RUNBOOK.md §C.
  const [preserveSourceNumbers, setPreserveSourceNumbers] = useState(false);
  // Auto-generated S/4 prep script (ABAP). The wizard walks through:
  //   Generate  →  view/copy/download  →  either auto-run or admin runs SE38
  //   →  ticks "Ran on S/4" checkbox  →  Start migration button unlocks.
  // Gates the Start button so a run can't kick off against an unprepared S/4.
  const [prepScript, setPrepScript] = useState(null);       // {abap, summary, warnings, download_url, ...}
  const [prepGenerating, setPrepGenerating] = useState(false);
  const [prepAutoRunning, setPrepAutoRunning] = useState(false);
  const [prepAutoRunResult, setPrepAutoRunResult] = useState(null);
  const [prepConfirmedRun, setPrepConfirmedRun] = useState(false);
  const [prepCopyOk, setPrepCopyOk] = useState(false);
  // Honest breadth report — every object the tool knows about, with a tier
  // badge (Tier-1 verified, Tier-2 awaiting live verification, MC-lane
  // template, or blocked on customizing/data). Lazy-loaded on demand.
  const [coverage, setCoverage] = useState(null);
  const [coverageLoading, setCoverageLoading] = useState(false);
  const [coverageOpen, setCoverageOpen] = useState(false);
  // Preservation planner state — 4-strategy decision matrix per object.
  // computed lazily; decisions map = {object_type: 'A'|'B'|'C'|'D'}.
  const [preservationPlan, setPreservationPlan] = useState(null);
  const [preservationLoading, setPreservationLoading] = useState(false);
  const [preservationApplying, setPreservationApplying] = useState(false);
  const [preservationApplyResult, setPreservationApplyResult] = useState(null);
  const [decisions, setDecisions] = useState({}); // per-object choice
  // Run mode: 'auto' = one-click fire-and-forget (server chains plan +
  // apply non-B + migration). 'step' = existing per-step confirmations
  // (Compute → Apply → Start). Defaults to auto for demo; enterprise
  // Basis teams often switch to step for approval visibility.
  const [runMode, setRunMode] = useState('auto');
  const [autoRunning, setAutoRunning] = useState(false);
  const [autoResult, setAutoResult] = useState(null);
  const [allowStrategyB, setAllowStrategyB] = useState(false);
  const [confirmingLive, setConfirmingLive] = useState(false);
  // Aggregated telemetry + error buckets — populated by /telemetry poll.
  const [telemetry, setTelemetry] = useState(null);
  const [errorBuckets, setErrorBuckets] = useState([]);

  useEffect(() => {
    api.wizardGet(runId).then((w) => {
      setWizard(w);
      if (typeof w?.load_to_s4 === 'boolean') setLoadToS4(w.load_to_s4);
    }).catch((e) => setErr(e.message));
  }, [runId]);

  // Poll live progress AND aggregated telemetry + error buckets while a
  // run is active. Telemetry is what drives the metric cards; the raw
  // progress steps still power the phase tracker below.
  useEffect(() => {
    let cancelled = false;
    let timer = null;
    async function poll() {
      try {
        const [p, t, eb] = await Promise.all([
          api.progress(0),
          activeRun ? api.runTelemetry(activeRun) : Promise.resolve(null),
          activeRun ? api.runErrorBuckets(activeRun) : Promise.resolve(null),
        ]);
        if (cancelled) return;
        setProgress({ steps: p.steps || [], stats: p.stats });
        if (t) setTelemetry(t);
        if (eb) setErrorBuckets(eb.buckets || []);
      } catch { /* network blip is fine */ }
      if (!cancelled) timer = setTimeout(poll, 3000);
    }
    if (activeRun) poll();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [activeRun]);

  const startMigration = async () => {
    // Block accidental live load - require an explicit confirm step when
    // load_to_s4 is on. The confirm modal sets confirmingLive=false then
    // re-enters this function.
    if (loadToS4 && !confirmingLive) {
      setConfirmingLive(true);
      return;
    }
    setConfirmingLive(false);
    setStarting(true); setErr('');
    try {
      const r = await api.triggerLiftAndShift({
        run_id: runId,
        migration_type: wizard.migration_type,
        selective_objects: wizard.selective_objects || [],
        ecc_version: wizard.ecc_version,
        s4_version:  wizard.s4_version,
        load_to_s4:  loadToS4,
        simulation_mode: loadToS4 && simulationMode,
        max_rows: maxRows === '' ? null : Number(maxRows),
        preserve_source_numbers: preserveSourceNumbers,
      });
      const pipeline_run_id = r.run_id || r.execution_id || runId;
      setActiveRun(pipeline_run_id);
      await api.wizardPatch(runId, {
        page: 'project',
        pipeline_run_id,
        load_to_s4: loadToS4,
        started_at: new Date().toISOString(),
      });
    } catch (e) {
      setErr(e.message);
    } finally { setStarting(false); }
  };

  // Preservation planner — compute + apply
  const computePreservationPlan = async () => {
    setPreservationLoading(true); setErr('');
    try {
      const r = await api.preservationCompute();
      setPreservationPlan(r);
      // Auto-populate decisions with the planner's recommendation per object
      const dec = {};
      for (const [obj, entry] of Object.entries(r.plan || {})) {
        dec[obj] = entry.recommended || 'D';
      }
      setDecisions(dec);
    } catch (e) { setErr(e.message); }
    finally { setPreservationLoading(false); }
  };
  const applyPreservationPlan = async () => {
    setPreservationApplying(true); setErr(''); setPreservationApplyResult(null);
    try {
      const r = await api.preservationApply(preservationPlan.plan, decisions);
      setPreservationApplyResult(r);
    } catch (e) { setErr(e.message); }
    finally { setPreservationApplying(false); }
  };
  const setDecision = (obj, choice) => {
    setDecisions((prev) => ({ ...prev, [obj]: choice }));
  };

  // Auto-mode fire-and-forget
  const startAutoRun = async () => {
    setErr(''); setAutoRunning(true); setAutoResult(null);
    try {
      const r = await api.autoRun({
        run_id: runId,
        migration_type: wizard.migration_type,
        selective_objects: wizard.selective_objects || [],
        load_to_s4: loadToS4,
        simulation_mode: loadToS4 && simulationMode,
        max_rows: maxRows === '' ? null : Number(maxRows),
        preserve_source_numbers: preserveSourceNumbers,
        allow_strategy_b: allowStrategyB,
      });
      setAutoResult(r);
      const pipeline_run_id = r.run_id || runId;
      setActiveRun(pipeline_run_id);
      await api.wizardPatch(runId, {
        page: 'project', pipeline_run_id, load_to_s4: loadToS4,
        started_at: new Date().toISOString(), auto_mode: true,
      });
    } catch (e) { setErr(e.message); }
    finally { setAutoRunning(false); }
  };

  const loadCoverage = async () => {
    if (coverage) { setCoverageOpen((v) => !v); return; }
    setCoverageLoading(true); setErr('');
    try {
      const r = await api.coverage();
      setCoverage(r);
      setCoverageOpen(true);
    } catch (e) { setErr(e.message); }
    finally { setCoverageLoading(false); }
  };

  const downloadPdf = async () => {
    setErr('');
    try {
      await downloadFile(
        `/api/runs/${encodeURIComponent(activeRun || runId)}/pdf`,
        `migrate4hana-${activeRun || runId}.pdf`);
    } catch (e) { setErr(e.message); }
  };

  // Scan ECC + generate S/4 prep ABAP. On success, `prepScript.abap` holds
  // the SE38-pastable source; `prepScript.download_url` streams the same
  // as a .abap file. The user then either runs it manually in S/4 or, if
  // RFC_ABAP_INSTALL_AND_RUN is enabled on the target, clicks Auto-run.
  const generatePrepScript = async () => {
    setErr(''); setPrepGenerating(true); setPrepAutoRunResult(null);
    setPrepConfirmedRun(false);
    try {
      const r = await api.generatePrepScript({
        run_id: runId,
        preserve_source_numbers: preserveSourceNumbers,
      });
      if (r.status === 'error') {
        setErr(r.message || 'Prep script generation failed.');
        return;
      }
      setPrepScript(r);
    } catch (e) {
      setErr(e.message);
    } finally { setPrepGenerating(false); }
  };

  const copyPrepScript = async () => {
    if (!prepScript?.abap) return;
    try {
      await navigator.clipboard.writeText(prepScript.abap);
      setPrepCopyOk(true);
      setTimeout(() => setPrepCopyOk(false), 2500);
    } catch (e) { setErr(`Copy failed: ${e.message}`); }
  };

  const downloadPrepScript = async () => {
    if (!prepScript?.download_url) return;
    setErr('');
    try {
      await downloadFile(prepScript.download_url,
                         `ZM4H_PREP_${runId}.abap`);
    } catch (e) { setErr(e.message); }
  };

  const downloadUndoScript = async () => {
    if (!prepScript?.download_undo_url) return;
    setErr('');
    try {
      await downloadFile(prepScript.download_undo_url,
                         `ZM4H_UNDO_${runId}.abap`);
    } catch (e) { setErr(e.message); }
  };

  // Optional: ship the prep script to S/4 via RFC_ABAP_INSTALL_AND_RUN.
  // If S/4 has this RFC disabled (production-hardened tenants often do),
  // the response comes back with status='disabled' and the wizard directs
  // the user to run it manually via SE38 instead.
  const autoRunPrepScript = async () => {
    setErr(''); setPrepAutoRunning(true); setPrepAutoRunResult(null);
    try {
      const r = await api.autoRunPrepScript(runId);
      setPrepAutoRunResult(r);
      if (r.status === 'success') setPrepConfirmedRun(true);
    } catch (e) {
      setErr(e.message);
    } finally { setPrepAutoRunning(false); }
  };

  if (!wizard) return <div className="text-slate-500">Loading…</div>;

  return (
    <div>
      <ConfirmLiveLoad
        open={confirmingLive}
        onCancel={() => setConfirmingLive(false)}
        onConfirm={startMigration}
        wizard={wizard}
      />
      <Crumb runId={runId} />
      <h1 className="text-2xl font-semibold mb-1">{runId}</h1>
      <div className="text-sm text-slate-500 mb-6">
        {wizard.ecc_version} → {wizard.s4_version} ·{' '}
        {wizard.migration_type} migration ·{' '}
        {wizard.migration_type === 'selective'
          ? `${wizard.selective_objects?.length || 0} object(s)`
          : 'all catalog objects'}
      </div>

      {err && (
        <div className="text-red-700 text-sm bg-red-50 border border-red-200 rounded px-3 py-2 mb-4">
          {err}
        </div>
      )}

      <Section title="How should this migration run?">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <RunModeCard
            selected={runMode === 'auto'}
            title="Full auto (fire-and-forget)"
            subtitle="One click. Server orchestrates everything."
            body="Preservation plan computed → non-B strategies auto-applied → migration starts. Zero SAP GUI activity. Strategy B (which modifies SAP-shipped intervals) is deferred to the step-by-step mode because it needs your Basis team's explicit approval."
            accent="emerald"
            onClick={() => setRunMode('auto')}
            disabled={!!activeRun || starting}
          />
          <RunModeCard
            selected={runMode === 'step'}
            title="Step-by-step (per-change confirmations)"
            subtitle="Review each SAP-side change before it lands."
            body="Enterprise Basis-team pattern. You click through: Compute preservation plan → review per-object coverage → override recommendations if needed → apply → then start migration. Full visibility into every RFC change made on target."
            accent="blue"
            onClick={() => setRunMode('step')}
            disabled={!!activeRun || starting}
          />
        </div>
        {runMode === 'auto' && (
          <div className="mt-3">
            <label className="flex items-start gap-2 text-sm p-2 border border-amber-200 bg-amber-50 rounded">
              <input
                type="checkbox"
                checked={allowStrategyB}
                onChange={(e) => setAllowStrategyB(e.target.checked)}
                className="mt-0.5"
              />
              <span>
                <strong>Allow Strategy B in Auto mode</strong> (modifies SAP-shipped
                internal intervals to external). Only tick this if your Basis team
                has pre-approved changes to SAP-designated internal number ranges.
                Default off = auto-downgrades B to next-best option.
              </span>
            </label>
          </div>
        )}
      </Section>

      <Section title="Migration coverage (what this tool knows about)">
        <div className="flex items-start gap-3 flex-wrap">
          <button
            onClick={loadCoverage}
            disabled={coverageLoading}
            className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-900 disabled:bg-slate-400 text-white text-sm font-medium"
          >
            {coverageLoading
              ? 'Loading…'
              : coverage
                ? (coverageOpen ? 'Hide detail' : 'Show detail')
                : 'Show what will be migrated'}
          </button>
          {coverage?.totals && (
            <div className="text-xs text-slate-600 flex flex-wrap gap-3 items-center">
              <span>Total objects: <strong>{coverage.totals.total_objects}</strong></span>
              <span className="text-emerald-700">Tier-1 (live BAPI, verified): <strong>{coverage.totals.tier_1}</strong></span>
              <span className="text-blue-700">Tier-2 (live BAPI, awaiting verify): <strong>{coverage.totals.tier_2}</strong></span>
              <span className="text-slate-600">MC-lane (template): <strong>{coverage.totals.pseudo_spine_mc}</strong></span>
              <span className="text-amber-700">Blocked: <strong>{coverage.totals.blocked}</strong></span>
              <span className="text-slate-500">Registered spines: <strong>{coverage.totals.registered_spines}</strong></span>
            </div>
          )}
        </div>
        {coverage?.objects && coverageOpen && (
          <div className="mt-3 border border-slate-200 rounded overflow-hidden">
            <div className="overflow-auto max-h-96">
              <table className="w-full text-xs">
                <thead className="bg-slate-100 sticky top-0">
                  <tr className="text-left">
                    <th className="px-2 py-1.5 font-semibold">Object</th>
                    <th className="px-2 py-1.5 font-semibold">Tier</th>
                    <th className="px-2 py-1.5 font-semibold">DAG</th>
                    <th className="px-2 py-1.5 font-semibold">Extract</th>
                    <th className="px-2 py-1.5 font-semibold">BAPI / Note</th>
                  </tr>
                </thead>
                <tbody>
                  {coverage.objects.map((o) => (
                    <tr key={o.name} className="border-t border-slate-100 hover:bg-slate-50">
                      <td className="px-2 py-1 font-mono">{o.name}</td>
                      <td className="px-2 py-1">
                        <span className={`px-1.5 py-0.5 rounded text-white text-[10px] ${
                          o.tier === 'T1' ? 'bg-emerald-600' :
                          o.tier === 'T2' ? 'bg-blue-600' :
                          o.tier === 'MC' ? 'bg-slate-500' :
                          o.tier === 'BLOCKED' ? 'bg-amber-600' :
                          'bg-slate-300'
                        }`}>{o.tier}</span>
                      </td>
                      <td className="px-2 py-1">{o.in_dag ? '✓' : '·'}</td>
                      <td className="px-2 py-1">
                        {o.extractable
                          ? <span className="text-slate-600"><code>{o.extract_table}</code> <span className="text-slate-400">({o.extract_lane})</span></span>
                          : <span className="text-slate-300">—</span>}
                      </td>
                      <td className="px-2 py-1 text-slate-500">
                        {o.bapi ? <code>{o.bapi}</code> : o.blocked_reason || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="text-[11px] text-slate-500 px-2 py-1.5 bg-slate-50 border-t border-slate-200">
              <strong>T1</strong> = verified landing on live S/4. {' '}
              <strong>T2</strong> = spine written, awaits per-object BAPI verification (attempted during run; success promotes to T1). {' '}
              <strong>MC</strong> = Migration Cockpit / LTMOM template lane (no live BAPI needed). {' '}
              <strong>BLOCKED</strong> = target-side customizing or missing source data — see <code>PREREQ_RUNBOOK.md</code>.
            </div>
          </div>
        )}
      </Section>

      <Section title="Source-key preservation strategy (ECC ID → S/4 ID fidelity)">
        <PreservationPanel
          plan={preservationPlan}
          loading={preservationLoading}
          applying={preservationApplying}
          applyResult={preservationApplyResult}
          decisions={decisions}
          onCompute={computePreservationPlan}
          onApply={applyPreservationPlan}
          onDecision={setDecision}
        />
      </Section>

      {activeRun && telemetry && (
        <Section title="Live telemetry">
          <TelemetryCards t={telemetry} />
        </Section>
      )}

      <Section title="Project tracker">
        <StageList steps={progress.steps} />
      </Section>

      <Section title="Stats">
        <Stats stats={progress.stats} steps={progress.steps} />
      </Section>

      {activeRun && errorBuckets.length > 0 && (
        <Section title="Errors — triage">
          <ErrorBucketsList
            buckets={errorBuckets}
            runId={activeRun}
          />
        </Section>
      )}

      {activeRun && (
        <Section title="Fix &amp; retry — reprocess dead-letters">
          <ReprocessPanel runId={activeRun} />
        </Section>
      )}

      <Section title="What this run will do">
        <LoadModeChooser
          loadToS4={loadToS4}
          setLoadToS4={setLoadToS4}
          disabled={!!activeRun || starting}
        />
        {loadToS4 && (
          <label className="mt-4 flex items-start gap-3 p-3 border-2 border-blue-200 bg-blue-50 rounded text-sm">
            <input
              type="checkbox"
              checked={simulationMode}
              onChange={(e) => setSimulationMode(e.target.checked)}
              disabled={!!activeRun || starting}
              className="mt-0.5 accent-blue-600"
            />
            <span>
              <strong>Simulation mode (dry run)</strong> — call BAPIs with{' '}
              <code>TEST_RUN</code> and staging tables. Nothing commits to S/4HANA.{' '}
              <span className="text-slate-500">
                Recommended for the first live-load run.
              </span>
            </span>
          </label>
        )}

        <div className="mt-4 flex flex-col gap-2 p-3 border border-slate-200 bg-slate-50 rounded text-sm">
          <label className="flex items-center gap-3 flex-wrap">
            <span className="font-medium text-slate-700">Rows per object</span>
            <input
              type="number"
              min="1"
              max="1000000"
              step="1"
              value={maxRows}
              placeholder="server default (10)"
              onChange={(e) => setMaxRows(e.target.value)}
              disabled={!!activeRun || starting}
              className="input w-40"
            />
            <span className="text-slate-500">
              Cap on records per object type sent to S/4HANA this run.
            </span>
          </label>
          <span className="text-xs text-slate-500 pl-1">
            Leave blank to use the server default. Range: 1–1,000,000. Values
            outside the range are clamped. Overrides <code>M4H_LOAD_MAX_ROWS</code>{' '}
            for this run only.
          </span>
        </div>

        <div className="mt-3 flex flex-col gap-2 p-3 border border-slate-200 bg-slate-50 rounded text-sm">
          <label className="flex items-start gap-3">
            <input
              type="checkbox"
              checked={preserveSourceNumbers}
              onChange={(e) => setPreserveSourceNumbers(e.target.checked)}
              disabled={!!activeRun || starting}
              className="mt-1"
            />
            <span className="flex flex-col gap-1">
              <span className="font-medium text-slate-700">
                Preserve source document numbers (VBELN, EBELN, delivery, billing…)
              </span>
              <span className="text-slate-500">
                When enabled, the S/4 sales order / return / credit-memo /
                contract / delivery / billing document inherits the ECC number
                instead of getting a fresh internal-range number. Requires the
                target S/4 doc types (VA/RE/CR/CQ/LF/F2…) to be marked{' '}
                <strong>External Number Assignment</strong> in VOV8 / 0VLK / VN01
                before the run — see <code>PREREQ_RUNBOOK.md §C</code>. If a doc
                type is still internal-range, the BAPI silently keeps its own
                number and the run continues (no failure).
              </span>
            </span>
          </label>
        </div>
      </Section>

      {loadToS4 && !activeRun && (
        <Section title="Step 1 — Prepare S/4 target (auto-generated ABAP)">
          <div className="text-sm text-slate-600 mb-3">
            migrate4hana scans your ECC now, figures out every controlling area,
            plant, material group, exchange rate, factory calendar, tax code,
            and (if you ticked the number-preservation box) document-type
            external-range flag your data will reference — and writes an ABAP
            report you paste into <code>SE38</code> on S/4. About 30 seconds to
            run in S/4. Idempotent — safe to re-run.
          </div>

          {!prepScript && (
            <button
              onClick={generatePrepScript}
              disabled={prepGenerating}
              className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white text-sm font-medium"
            >
              {prepGenerating
                ? 'Scanning ECC + generating…'
                : 'Generate S/4 prep script'}
            </button>
          )}

          {prepScript && (
            <div className="space-y-3">
              <div className="text-xs text-slate-500 flex flex-wrap gap-3">
                <span>Tables scanned: <strong>{prepScript.summary.tables_scanned}</strong></span>
                <span>Tables with data: <strong>{prepScript.summary.tables_covered}</strong></span>
                <span>Rows to create/update: <strong>{prepScript.summary.total_rows_generated}</strong></span>
                <span>Report name: <code>{prepScript.summary.report_name}</code></span>
              </div>

              {prepScript.warnings?.length > 0 && (
                <div className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded p-2">
                  <div className="font-medium">Scanner warnings:</div>
                  <ul className="list-disc ml-5">
                    {prepScript.warnings.map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                </div>
              )}

              <div className="border border-slate-300 rounded overflow-hidden">
                <div className="bg-slate-100 px-3 py-2 flex flex-wrap gap-2 items-center border-b border-slate-300">
                  <span className="text-xs text-slate-600 font-medium mr-auto">
                    Preview — {prepScript.summary.report_name}.abap
                  </span>
                  <button
                    onClick={copyPrepScript}
                    className="px-3 py-1 rounded bg-slate-200 hover:bg-slate-300 text-xs font-medium"
                  >
                    {prepCopyOk ? '✓ Copied' : 'Copy to clipboard'}
                  </button>
                  <button
                    onClick={downloadPrepScript}
                    className="px-3 py-1 rounded bg-slate-800 hover:bg-slate-900 text-white text-xs font-medium"
                  >
                    Download .abap
                  </button>
                  <button
                    onClick={downloadUndoScript}
                    className="px-3 py-1 rounded border border-slate-300 hover:bg-slate-50 text-xs font-medium"
                    title="Companion rollback report — deletes what the prep script inserted."
                  >
                    Download undo
                  </button>
                </div>
                <pre className="max-h-72 overflow-auto text-xs bg-slate-900 text-slate-100 p-3 font-mono leading-snug whitespace-pre">
{prepScript.abap}
                </pre>
              </div>

              <div className="p-3 rounded border border-slate-200 bg-slate-50 text-sm">
                <div className="font-medium mb-2 text-slate-700">
                  Run on S/4 — two options:
                </div>
                <ol className="list-decimal ml-5 space-y-2 text-slate-600">
                  <li>
                    <strong>Manual (recommended for production tenants).</strong>{' '}
                    In S/4 GUI: <code>SE38</code> → New program{' '}
                    <code>{prepScript.summary.report_name}</code> → paste the
                    script above → save → press <code>F8</code> to execute.
                    Takes ~30 sec.
                  </li>
                  <li>
                    <strong>Automatic (CAL/IDES + tenants that allow RFC_ABAP_INSTALL_AND_RUN).</strong>{' '}
                    Click the button below — migrate4hana ships the script
                    over RFC and executes it on S/4 for you. Many
                    production tenants disable this RFC for security; if
                    so you'll get a clear message and can fall back to the
                    manual path.
                  </li>
                </ol>
                <div className="mt-3 flex flex-wrap gap-3 items-center">
                  <button
                    onClick={autoRunPrepScript}
                    disabled={prepAutoRunning}
                    className="px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-700 disabled:bg-emerald-300 text-white text-sm font-medium"
                  >
                    {prepAutoRunning
                      ? 'Executing on S/4…'
                      : 'Auto-run on S/4 now'}
                  </button>
                  {prepAutoRunResult && (
                    <span className={`text-xs ${
                      prepAutoRunResult.status === 'success' ? 'text-emerald-700' :
                      prepAutoRunResult.status === 'disabled' ? 'text-amber-700' :
                      'text-red-700'
                    }`}>
                      {prepAutoRunResult.status === 'success' && '✓ Executed on S/4. '}
                      {prepAutoRunResult.status === 'disabled' && '⚠️ RFC_ABAP_INSTALL_AND_RUN is disabled on S/4 — use manual path. '}
                      {prepAutoRunResult.status === 'error' && '✗ Failed: '}
                      {prepAutoRunResult.message}
                    </span>
                  )}
                </div>
                {prepAutoRunResult?.output?.length > 0 && (
                  <pre className="mt-3 max-h-40 overflow-auto text-xs bg-slate-900 text-emerald-200 p-2 font-mono">
{prepAutoRunResult.output.join('\n')}
                  </pre>
                )}
              </div>

              <label className="flex items-start gap-2 p-3 border border-blue-200 bg-blue-50 rounded text-sm">
                <input
                  type="checkbox"
                  checked={prepConfirmedRun}
                  onChange={(e) => setPrepConfirmedRun(e.target.checked)}
                  className="mt-0.5"
                />
                <span>
                  <strong>I have run the prep script on S/4</strong> (either
                  manually via SE38 or via the Auto-run button above), and
                  the report finished successfully. This unlocks the{' '}
                  <em>Start migration</em> button below.
                </span>
              </label>
            </div>
          )}
        </Section>
      )}

      <Section title={runMode === 'auto' ? "Fire and forget" : (loadToS4 ? "Step 2 — Actions" : "Actions")}>
        {runMode === 'step' && loadToS4 && !prepConfirmedRun && (
          <div className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded p-2 mb-3">
            (Step-by-step mode) Generate + run the S/4 prep script above, then
            tick the confirmation box — the <em>Start migration</em> button
            unlocks once that's done. Extract-only mode (unset <em>Load to S/4</em>)
            skips this gate entirely.
          </div>
        )}
        {runMode === 'auto' && (
          <div className="text-xs text-emerald-800 bg-emerald-50 border border-emerald-200 rounded p-2 mb-3">
            <strong>Auto mode</strong>: one click orchestrates preservation
            plan compute → non-B strategy apply → migration start. Zero SAP
            GUI activity. Basis Kit must be installed on target
            {allowStrategyB ? ' — Strategy B enabled (assumes Basis pre-approval).' : ' — Strategy B DEFERRED to step-by-step mode (needs Basis approval).'}
          </div>
        )}
        <div className="flex flex-wrap gap-3 items-center">
          {runMode === 'auto' ? (
            <button
              onClick={startAutoRun}
              disabled={autoRunning || activeRun}
              className="px-5 py-2.5 rounded bg-emerald-600 hover:bg-emerald-700 disabled:bg-emerald-300 text-white font-medium"
            >
              {autoRunning
                ? 'Auto-migrating (plan → apply → run) ...'
                : activeRun
                  ? 'Running'
                  : '🚀 Fire and forget — Auto-migrate ECC → S/4HANA'}
            </button>
          ) : (
            <button
              onClick={startMigration}
              disabled={starting || activeRun || (loadToS4 && !prepConfirmedRun)}
              className={`px-5 py-2.5 rounded text-white font-medium ${
                loadToS4
                  ? 'bg-red-600 hover:bg-red-700 disabled:bg-red-300'
                  : 'bg-orange-500 hover:bg-orange-600 disabled:bg-orange-300'
              }`}
            >
              {starting
                ? 'Starting…'
                : activeRun
                  ? 'Running'
                  : loadToS4
                    ? 'Start migration + load to S/4HANA'
                    : 'Start migration (extract-only)'}
            </button>
          )}
          {autoResult && (
            <span className="text-xs text-slate-600">
              Auto plan applied · {(autoResult.plan_applied?.outcomes || []).length} objects processed
              {autoResult.downgraded_from_B?.length > 0 && (
                <span className="text-amber-700">
                  {' '}· {autoResult.downgraded_from_B.length} downgraded from B
                </span>
              )}
            </span>
          )}

          {activeRun && (
            <>
              <Link
                to={`/live/${encodeURIComponent(activeRun)}`}
                target="_blank" rel="noreferrer"
                className="px-4 py-2 rounded border border-slate-300 text-sm font-medium hover:bg-slate-50"
              >
                Open live ops (new tab) ↗
              </Link>
              <Link
                to={`/conversion/${encodeURIComponent(activeRun)}`}
                target="_blank" rel="noreferrer"
                className="px-4 py-2 rounded border border-slate-300 text-sm font-medium hover:bg-slate-50"
              >
                Open conversion dashboard ↗
              </Link>
            </>
          )}

          <button
            onClick={downloadPdf}
            className="px-4 py-2 rounded border border-slate-300 text-sm font-medium hover:bg-slate-50"
            title="Snapshot the run state right now as a PDF"
          >
            Download PDF snapshot
          </button>

          {activeRun && (
            <button
              onClick={() => downloadFile(
                `/api/runs/${encodeURIComponent(activeRun)}/evidence-pack`,
                `evidence_pack_${activeRun}.json`)
                .catch((e) => setErr(e.message))}
              className="px-4 py-2 rounded border border-emerald-300 bg-emerald-50 text-emerald-800 text-sm font-medium hover:bg-emerald-100"
              title="Cryptographically-sealed audit manifest (SHA-256 chain, WORM-eligible)"
            >
              Download Compliance Evidence
            </button>
          )}
        </div>
        <div className="text-xs text-slate-500 mt-3 leading-relaxed">
          The PDF can be downloaded any time during the run — each download
          captures the comprehensive state up to that moment. After the run
          completes, the PDF is the full final report. The Compliance Evidence
          pack is a tamper-proof JSON manifest (SHA-256 hash chain) for auditors.
        </div>
      </Section>
    </div>
  );
}

function TelemetryCards({ t }) {
  const pct = Math.max(0, Math.min(100, Number(t?.percentage_complete) || 0));
  const barColor = t?.status === 'Failed'    ? 'bg-red-500'
                 : t?.status === 'Completed' ? 'bg-emerald-500'
                 : t?.status === 'Simulating'? 'bg-amber-500'
                                              : 'bg-blue-500';
  const statusPillClasses = t?.status === 'Failed'
    ? 'bg-red-100 text-red-800'
    : t?.status === 'Completed'
      ? 'bg-emerald-100 text-emerald-800'
      : t?.status === 'Simulating'
        ? 'bg-amber-100 text-amber-800'
        : 'bg-blue-100 text-blue-800';
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className={`text-xs font-semibold px-2 py-0.5 rounded ${statusPillClasses}`}>
            {t?.status || '—'}
          </span>
          <span className="text-sm text-slate-600">
            {pct.toFixed(1)}% complete
          </span>
        </div>
        <span className="text-xs text-slate-500 tabular-nums">
          runtime {formatElapsed(t?.runtime_elapsed_seconds || 0)}
        </span>
      </div>
      <div className="h-2 rounded-full bg-slate-100 overflow-hidden mb-4">
        <div className={`h-full ${barColor} transition-all duration-300`}
             style={{ width: `${pct}%` }} />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Total records"       value={fmt(t?.total_records)} />
        <MetricCard label="Processed successfully" value={fmt(t?.processed_successfully)} tone="ok" />
        <MetricCard label="Failed records"      value={fmt(t?.failed_records)}
                    tone={t?.failed_records ? 'bad' : 'ok'} />
        <MetricCard label="Runtime"             value={formatElapsed(t?.runtime_elapsed_seconds || 0)} />
      </div>
    </div>
  );
}

function MetricCard({ label, value, tone = 'neutral' }) {
  const tones = {
    ok:      'text-emerald-800 bg-emerald-50 border-emerald-200',
    bad:     'text-red-800 bg-red-50 border-red-200',
    neutral: 'text-slate-800 bg-slate-50 border-slate-200',
  };
  return (
    <div className={`border rounded-lg p-3 ${tones[tone] || tones.neutral}`}>
      <div className="text-xs uppercase tracking-wide opacity-70">{label}</div>
      <div className="text-2xl font-semibold tabular-nums mt-1">{value}</div>
    </div>
  );
}

// Run-mode card - one of two choices (auto vs step-by-step). Emerald when
// selected auto, blue when selected step. Muted when unselected.
function RunModeCard({ selected, title, subtitle, body, accent, onClick, disabled }) {
  const accentBg = accent === 'emerald' ? 'bg-emerald-50 border-emerald-300' : 'bg-blue-50 border-blue-300';
  const mutedBg  = 'bg-slate-50 border-slate-200';
  const cls = selected
    ? `${accentBg} ring-2 ring-offset-1 ${accent === 'emerald' ? 'ring-emerald-500' : 'ring-blue-500'}`
    : `${mutedBg} hover:bg-slate-100`;
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`text-left p-4 border rounded ${cls} disabled:opacity-60 disabled:cursor-not-allowed`}
    >
      <div className={`text-sm font-semibold ${selected ? '' : 'text-slate-700'}`}>{title}</div>
      <div className="text-xs text-slate-600 mb-2">{subtitle}</div>
      <div className="text-xs text-slate-600">{body}</div>
    </button>
  );
}


// Source-key preservation strategy panel.
// Presents the 4-strategy decision matrix per object type, with the
// planner's auto-recommendation pre-selected. Customer can override
// per object. Includes clear risk banners (esp. for option B which
// changes SAP-shipped defaults).
function PreservationPanel({ plan, loading, applying, applyResult,
                              decisions, onCompute, onApply, onDecision }) {
  const strategyMeta = {
    A: { label: 'A. Point NUMKE at existing external interval',
         short: 'Partial preservation. Zero SAP risk.',
         color: 'bg-blue-100 text-blue-800 border-blue-300' },
    B: { label: 'B. Modify SAP-shipped interval to external',
         short: 'Full preservation (source ID = target ID). Requires Basis approval.',
         color: 'bg-emerald-100 text-emerald-800 border-emerald-300' },
    C: { label: 'C. Shift source keys via mapping table',
         short: 'Source X → target X+offset. Deterministic. Zero SAP risk.',
         color: 'bg-amber-100 text-amber-800 border-amber-300' },
    D: { label: 'D. Accept target-assigned numbers (renumber + ledger)',
         short: 'No preservation. Zero target-side changes.',
         color: 'bg-slate-100 text-slate-700 border-slate-300' },
  };

  if (!plan) {
    return (
      <div className="space-y-3">
        <div className="text-sm text-slate-600">
          For a true ECC → S/4 replication (same IDs everywhere), the tool
          needs to know your preservation strategy per object type. Run
          the planner — it queries live ECC + S/4, computes coverage for
          each of 4 strategies, and pre-recommends the highest-fidelity
          option (typically <strong>B</strong>) that's applicable.
        </div>
        <button
          onClick={onCompute}
          disabled={loading}
          className="px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 text-white text-sm font-medium"
        >
          {loading ? 'Analysing ECC + S/4...' : 'Compute preservation plan'}
        </button>
      </div>
    );
  }

  const objects = Object.entries(plan.plan || {});
  return (
    <div className="space-y-4">
      <div className="text-sm text-slate-600 flex flex-wrap gap-4">
        <span>Analysed at: <strong>{new Date(plan.generated_at).toLocaleTimeString()}</strong></span>
        <span>Objects: <strong>{plan.objects_analyzed}</strong></span>
        <button
          onClick={onCompute}
          disabled={loading}
          className="text-xs px-2 py-0.5 rounded border border-slate-300 hover:bg-slate-50"
        >
          {loading ? 'Re-analysing...' : 'Re-analyse'}
        </button>
      </div>

      <div className="bg-slate-50 border border-slate-200 rounded p-3 text-xs text-slate-700 space-y-1">
        <div className="font-medium mb-1">4 strategies (per-object choice):</div>
        {Object.entries(strategyMeta).map(([k, m]) => (
          <div key={k}>
            <span className={`inline-block px-1.5 py-0.5 rounded font-mono ${m.color} border`}>
              {k}
            </span>
            {' '}<strong>{m.label.replace(/^. /, '')}</strong>: {m.short}
          </div>
        ))}
        <div className="mt-2 text-amber-800">
          ⚠️ Choosing <strong>B</strong> for any object means the tool will
          modify a SAP-shipped number-range interval. This is the highest
          fidelity option — source keys will match target keys exactly —
          but SAP support does not cover incidents on modified designated-
          internal intervals. Confirm with your Basis team before applying.
        </div>
      </div>

      <div className="border border-slate-200 rounded overflow-hidden">
        <div className="overflow-auto max-h-96">
          <table className="w-full text-xs">
            <thead className="bg-slate-100 sticky top-0">
              <tr className="text-left">
                <th className="px-2 py-1.5">Object</th>
                <th className="px-2 py-1.5">Source range</th>
                <th className="px-2 py-1.5">SNRO</th>
                <th className="px-2 py-1.5">Strategy A coverage</th>
                <th className="px-2 py-1.5">Strategy B coverage</th>
                <th className="px-2 py-1.5">Strategy C coverage</th>
                <th className="px-2 py-1.5">Your choice</th>
              </tr>
            </thead>
            <tbody>
              {objects.map(([obj, entry]) => {
                const src = entry.source || {};
                const strats = entry.strategies || {};
                const choice = decisions[obj] || entry.recommended || 'D';
                return (
                  <tr key={obj} className="border-t border-slate-100 hover:bg-slate-50">
                    <td className="px-2 py-1 font-mono font-semibold">{obj}</td>
                    <td className="px-2 py-1">
                      {src.count > 0
                        ? <span>{src.count.toLocaleString()} rows<br/>
                            <span className="text-slate-500 text-[10px]">
                              min <code>{src.min_key}</code> · max <code>{src.max_key}</code>
                            </span>
                          </span>
                        : <span className="text-slate-400">no rows</span>}
                    </td>
                    <td className="px-2 py-1 font-mono text-slate-500">{entry.snro}</td>
                    <td className="px-2 py-1">
                      <span className={strats.A?.coverage_est_pct >= 90 ? 'text-emerald-700 font-medium' : 'text-slate-600'}>
                        {strats.A?.coverage_est_pct?.toFixed(1) || 0}%
                      </span>
                    </td>
                    <td className="px-2 py-1">
                      <span className={strats.B?.coverage_est_pct >= 90 ? 'text-emerald-700 font-medium' : 'text-slate-600'}>
                        {strats.B?.coverage_est_pct?.toFixed(1) || 0}%
                        {strats.B?.requires_basis_approval && (
                          <span title="Requires Basis approval" className="ml-1 text-amber-600">⚠</span>
                        )}
                      </span>
                    </td>
                    <td className="px-2 py-1">
                      <span className={strats.C?.coverage_est_pct >= 90 ? 'text-emerald-700 font-medium' : 'text-slate-600'}>
                        {strats.C?.coverage_est_pct?.toFixed(1) || 0}%
                      </span>
                    </td>
                    <td className="px-2 py-1">
                      <select
                        value={choice}
                        onChange={(e) => onDecision(obj, e.target.value)}
                        className={`text-xs px-2 py-1 rounded border ${strategyMeta[choice]?.color}`}
                      >
                        <option value="A">A (partial)</option>
                        <option value="B">B (best — needs Basis)</option>
                        <option value="C">C (shifted)</option>
                        <option value="D">D (renumber)</option>
                      </select>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="flex flex-wrap gap-3 items-center">
        <button
          onClick={onApply}
          disabled={applying}
          className="px-4 py-2 rounded bg-emerald-600 hover:bg-emerald-700 disabled:bg-emerald-300 text-white text-sm font-medium"
        >
          {applying ? 'Applying to S/4...' : 'Apply approved plan to S/4'}
        </button>
        <span className="text-xs text-slate-500">
          Applies via Basis Kit RFCs. Idempotent — safe to re-run.
        </span>
      </div>

      {applyResult && (
        <div className="border border-slate-200 rounded overflow-hidden">
          <div className="bg-slate-100 px-3 py-2 text-sm font-medium border-b border-slate-200">
            Apply result — {applyResult.outcomes?.length || 0} objects processed
          </div>
          <table className="w-full text-xs">
            <thead className="bg-slate-50 text-left">
              <tr>
                <th className="px-2 py-1">Object</th>
                <th className="px-2 py-1">Choice</th>
                <th className="px-2 py-1">Status</th>
              </tr>
            </thead>
            <tbody>
              {(applyResult.outcomes || []).map((r) => (
                <tr key={r.object} className="border-t border-slate-100">
                  <td className="px-2 py-1 font-mono">{r.object}</td>
                  <td className="px-2 py-1">
                    <span className={`px-1.5 py-0.5 rounded ${strategyMeta[r.choice]?.color}`}>
                      {r.choice}
                    </span>
                  </td>
                  <td className="px-2 py-1">
                    <span className={
                      (r.status || '').startsWith('OK') ? 'text-emerald-700' :
                      (r.status || '').startsWith('ERROR') ? 'text-red-700' :
                      'text-amber-700'
                    }>{r.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}


// Fix-and-retry loop. Three-step operator flow the panel presents:
//   1. Download either the pre-populated failures Excel or the blank template
//      (with a sample row per object type)
//   2. Correct offline in Excel (the format is deliberately Excel so anyone
//      can fix rows without learning JSON / CLI)
//   3. Upload the corrected workbook back — tool calls each spine's load_one
//      for each row and returns a per-object summary
function ReprocessPanel({ runId }) {
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState('');
  const fileInputRef = React.useRef(null);

  const dlTemplate = () => downloadFile(
    api.reprocessTemplateUrl(runId),
    `M4H_reprocess_template_${runId}.xlsx`);
  const dlFailures = () => downloadFile(
    api.reprocessFailuresUrl(runId),
    `M4H_failures_${runId}.xlsx`);

  const onFilePicked = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setErr(''); setUploading(true); setResult(null);
    try {
      const r = await api.reprocessUpload(runId, file);
      setResult(r);
    } catch (e) { setErr(e.message); }
    finally { setUploading(false); if (fileInputRef.current) fileInputRef.current.value = ''; }
  };

  return (
    <div>
      <div className="text-sm text-slate-600 mb-3">
        Fix the ECC-data rows that dead-lettered on the last run, then push the
        corrected records back into S/4HANA — no re-migration of the whole
        object. Format is standard Excel so any team member can correct
        without CLI or JSON knowledge.
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="p-3 border border-slate-200 rounded bg-slate-50">
          <div className="text-xs uppercase tracking-wider text-slate-500 mb-1">
            Step 1a
          </div>
          <div className="font-medium text-slate-700 mb-2">
            Download failures Excel
          </div>
          <div className="text-xs text-slate-500 mb-3">
            Every dead-letter row with what we had + <code>__failure_reason</code>{' '}
            column so you know exactly what to fix.
          </div>
          <button
            onClick={dlFailures}
            className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-900 text-white text-sm font-medium w-full"
          >
            Download failures.xlsx
          </button>
        </div>
        <div className="p-3 border border-slate-200 rounded bg-slate-50">
          <div className="text-xs uppercase tracking-wider text-slate-500 mb-1">
            Step 1b
          </div>
          <div className="font-medium text-slate-700 mb-2">
            Download blank template
          </div>
          <div className="text-xs text-slate-500 mb-3">
            Blank sheets with column headers + a sample row per object type
            so a fresh corrector knows the format.
          </div>
          <button
            onClick={dlTemplate}
            className="px-3 py-1.5 rounded border border-slate-300 hover:bg-slate-100 text-slate-700 text-sm font-medium w-full"
          >
            Download template.xlsx
          </button>
        </div>
        <div className="p-3 border border-emerald-200 rounded bg-emerald-50">
          <div className="text-xs uppercase tracking-wider text-emerald-700 mb-1">
            Step 3
          </div>
          <div className="font-medium text-emerald-800 mb-2">
            Upload corrected Excel
          </div>
          <div className="text-xs text-emerald-700 mb-3">
            After Step 2 (correct offline), upload the workbook — tool loads
            each row into S/4HANA.
          </div>
          <input
            type="file"
            ref={fileInputRef}
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={onFilePicked}
            disabled={uploading}
            className="text-xs block w-full text-slate-700"
          />
        </div>
      </div>

      {uploading && (
        <div className="mt-3 text-sm text-slate-600">Uploading + reprocessing…</div>
      )}
      {err && (
        <div className="mt-3 text-sm bg-red-50 border border-red-200 text-red-800 p-2 rounded">
          {err}
        </div>
      )}
      {result && result.summary && (
        <div className="mt-4 border border-slate-200 rounded overflow-hidden">
          <div className="bg-slate-100 px-3 py-2 text-sm font-medium text-slate-700 border-b border-slate-200">
            Reprocess result — {result.summary.attempted} rows attempted
          </div>
          <div className="px-3 py-2 text-sm text-slate-600 grid grid-cols-4 gap-3">
            <div>
              <div className="text-xs text-slate-500">Attempted</div>
              <div className="text-lg font-semibold text-slate-800">{result.summary.attempted}</div>
            </div>
            <div>
              <div className="text-xs text-emerald-600">Created</div>
              <div className="text-lg font-semibold text-emerald-700">{result.summary.created}</div>
            </div>
            <div>
              <div className="text-xs text-blue-600">Matched existing</div>
              <div className="text-lg font-semibold text-blue-700">{result.summary.matched}</div>
            </div>
            <div>
              <div className="text-xs text-red-600">Still failed</div>
              <div className="text-lg font-semibold text-red-700">{result.summary.still_failed}</div>
            </div>
          </div>
          {result.per_object && (
            <table className="w-full text-xs border-t border-slate-200">
              <thead className="bg-slate-50 text-left">
                <tr>
                  <th className="px-2 py-1.5">Object</th>
                  <th className="px-2 py-1.5">Attempted</th>
                  <th className="px-2 py-1.5">Created</th>
                  <th className="px-2 py-1.5">Matched</th>
                  <th className="px-2 py-1.5">Still failed</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(result.per_object).map(([obj, s]) => (
                  <tr key={obj} className="border-t border-slate-100">
                    <td className="px-2 py-1 font-mono">{obj}</td>
                    <td className="px-2 py-1">{s.attempted}</td>
                    <td className="px-2 py-1 text-emerald-700">{s.created}</td>
                    <td className="px-2 py-1 text-blue-700">{s.matched}</td>
                    <td className="px-2 py-1 text-red-700">{s.still_failed}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}


function ErrorBucketsList({ buckets, runId }) {
  return (
    <div>
      <div className="space-y-2 mb-3">
        {buckets.map((b, i) => (
          <ErrorBucketCard key={i} b={b} />
        ))}
      </div>
      <button
        onClick={() => downloadFile(
          `/api/runs/${encodeURIComponent(runId)}/failed-records.csv`,
          `failed-records-${runId}.csv`)}
        className="px-4 py-2 rounded border border-red-300 bg-red-50 text-red-800 text-sm font-medium hover:bg-red-100"
      >
        Download Failed Records ({buckets.reduce((s, b) => s + b.count, 0)} rows)
      </button>
    </div>
  );
}

function ErrorBucketCard({ b }) {
  return (
    <div className="border border-red-200 bg-red-50 rounded p-3">
      <div className="flex items-start justify-between gap-3 mb-1">
        <div className="text-sm font-medium text-red-900 flex-1">{b.error}</div>
        <span className="text-xs font-semibold px-2 py-0.5 rounded bg-red-200 text-red-900 tabular-nums">
          {b.count} rows
        </span>
      </div>
      <div className="text-xs text-slate-600 leading-relaxed">
        <strong>Fix:</strong> {b.remediation}
      </div>
      {b.objects?.length > 0 && (
        <div className="text-xs text-slate-500 mt-1">
          Objects: {b.objects.join(', ')}
          {b.sample_source_keys?.length > 0 && (
            <> · Sample keys: <span className="font-mono">{b.sample_source_keys.join(', ')}</span></>
          )}
        </div>
      )}
    </div>
  );
}

function fmt(n) {
  if (n == null) return '—';
  return Number(n).toLocaleString();
}

function formatElapsed(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  if (h > 0) return `${h}h ${m % 60}m ${s % 60}s`;
  if (m > 0) return `${m}m ${s % 60}s`;
  return `${s}s`;
}

function LoadModeChooser({ loadToS4, setLoadToS4, disabled }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      <ModeCard
        title="Extract-only"
        subtitle="Safe default — no S/4 writes"
        body={[
          'Reads from ECC, transforms, and stages Migration Cockpit CSV templates under local-staging/.',
          'You (or basis) import the CSVs via Migration Cockpit when ready.',
          'Reversible: nothing changes on S/4HANA.',
        ]}
        accent="blue"
        selected={!loadToS4}
        onClick={() => setLoadToS4(false)}
        disabled={disabled}
      />
      <ModeCard
        title="Extract + load to S/4HANA"
        subtitle="Calls BAPIs against S/4 — writes real data"
        body={[
          'Runs every extract-only step, then calls released BAPIs to write into ACDOCA / BUT000 / MARA / etc.',
          'Use this for cutover. The Go-Live Scorecard can only reach Grade A/B when this lane runs end-to-end.',
          'NOT reversible: rows land in S/4. Make sure your S/4 client is non-production OR you have authorisation for cutover.',
        ]}
        accent="red"
        selected={loadToS4}
        onClick={() => setLoadToS4(true)}
        disabled={disabled}
      />
    </div>
  );
}

function ModeCard({ title, subtitle, body, accent, selected, onClick, disabled }) {
  const accents = {
    blue: selected
      ? 'border-blue-500 bg-blue-50'
      : 'border-slate-200 hover:border-blue-300',
    red: selected
      ? 'border-red-500 bg-red-50'
      : 'border-slate-200 hover:border-red-300',
  };
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`text-left border-2 rounded-lg p-4 transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${accents[accent]}`}
    >
      <div className="flex items-center gap-2 mb-1">
        <div className="font-semibold">{title}</div>
        {selected && (
          <span className={`text-xs font-medium px-2 py-0.5 rounded ${
            accent === 'red' ? 'bg-red-200 text-red-900' : 'bg-blue-200 text-blue-900'
          }`}>
            selected
          </span>
        )}
      </div>
      <div className={`text-xs mb-2 ${
        accent === 'red' ? 'text-red-700' : 'text-blue-700'
      }`}>
        {subtitle}
      </div>
      <ul className="text-xs text-slate-600 space-y-1 list-disc list-inside">
        {body.map((line, i) => <li key={i}>{line}</li>)}
      </ul>
    </button>
  );
}

function ConfirmLiveLoad({ open, onCancel, onConfirm, wizard }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
      <div className="bg-white rounded-lg shadow-xl max-w-lg w-full p-6">
        <div className="text-lg font-semibold text-red-700 mb-2">
          Confirm live load to S/4HANA
        </div>
        <div className="text-sm text-slate-700 leading-relaxed space-y-2 mb-4">
          <p>
            This will call <strong>BAPIs against your saved S/4HANA system</strong>
            {' '}({wizard?.s4_version || '—'}) and write real rows into ACDOCA,
            BUT000, MARA, and the other target tables for{' '}
            <strong>
              {wizard?.migration_type === 'selective'
                ? `${wizard?.selective_objects?.length || 0} selected object(s)`
                : 'every catalog object'}
            </strong>.
          </p>
          <p className="text-red-700 font-medium">
            Writes are not reversible. Confirm you are running against a
            non-production client OR you have explicit cutover authorisation.
          </p>
        </div>
        <div className="flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm rounded border border-slate-300 hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="px-4 py-2 text-sm rounded bg-red-600 hover:bg-red-700 text-white font-medium"
          >
            Yes, start live load
          </button>
        </div>
      </div>
    </div>
  );
}

function Crumb({ runId }) {
  return (
    <div className="text-xs text-slate-500 mb-1">
      <Link to="/" className="hover:underline">Home</Link>
      {' / '}
      <span>{runId.slice(0, 32)}…</span>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div className="bg-white border border-slate-200 rounded-lg p-5 mb-4">
      <div className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-3">
        {title}
      </div>
      {children}
    </div>
  );
}

function StageList({ steps }) {
  if (!steps?.length) {
    return (
      <div className="text-sm text-slate-500">
        Pipeline hasn't started yet. Click "Start migration" below to begin.
      </div>
    );
  }
  // Only consider "real stage" rows - the api_server tags these with
  // details.is_stage === true. Everything else (runner log echoes from
  // streamed stderr) is just noise for this view; Live Ops shows that.
  const stageRows = steps.filter(
    (s) => s?.details?.is_stage || STAGES.some((st) => st.id === s.stage)
  );
  // Roll up by PHASE id. Per-stage status drives both the phase badge AND
  // the percentage: each stage in a phase contributes 1/expected of that
  // phase's progress, and the overall % is the average across all phases.
  const byPhase = {};
  for (const s of stageRows) {
    const phaseId = s.stage;
    if (!STAGES.some((st) => st.id === phaseId)) continue;
    const cur = byPhase[phaseId] || {
      seen: 0, done: 0, hasErr: false, hasRun: false, last: null,
    };
    cur.seen += 1;
    const norm = normalizeStatus(s.status);
    if (norm === 'complete')    cur.done   += 1;
    if (norm === 'failed')      cur.hasErr  = true;
    if (norm === 'running' || norm === 'complete' || norm === 'failed') cur.hasRun = true;
    cur.last = s;
    byPhase[phaseId] = cur;
  }

  // Build per-phase progress + overall total
  let totalDone = 0;
  const totalExpected = STAGES.reduce((acc, st) => acc + st.expected, 0);
  const rows = STAGES.map((st) => {
    const ph = byPhase[st.id];
    const done = Math.min(ph?.done || 0, st.expected);
    totalDone += done;
    const percent = Math.round((done / st.expected) * 100);
    let status = 'pending';
    if (ph) {
      if (ph.hasErr) status = 'failed';
      else if (done >= st.expected) status = 'complete';
      else if (ph.hasRun) status = 'running';
    }
    return { st, done, percent, status };
  });
  const overallPct = Math.round((totalDone / totalExpected) * 100);

  return (
    <div className="space-y-3">
      <OverallProgress percent={overallPct} done={totalDone} total={totalExpected} />
      <ul className="space-y-2">
        {rows.map(({ st, done, percent, status }) => (
          <PhaseRow key={st.id} st={st} done={done} percent={percent} status={status} />
        ))}
      </ul>
    </div>
  );
}

function OverallProgress({ percent, done, total }) {
  // Colour the overall bar by overall status: green if 100%, blue while
  // in flight, slate before anything starts.
  const bar = percent >= 100 ? 'bg-emerald-500'
            : percent > 0    ? 'bg-blue-500'
                              : 'bg-slate-300';
  return (
    <div className="mb-2">
      <div className="flex items-baseline justify-between mb-1">
        <div className="text-sm font-medium text-slate-700">Overall progress</div>
        <div className="text-sm font-semibold text-slate-900">
          {percent}% <span className="text-slate-400 font-normal">· {done}/{total} stages</span>
        </div>
      </div>
      <div className="h-2 rounded-full bg-slate-100 overflow-hidden">
        <div
          className={`h-full ${bar} transition-all duration-300`}
          style={{ width: `${Math.min(100, percent)}%` }}
        />
      </div>
    </div>
  );
}

function PhaseRow({ st, done, percent, status }) {
  // Phase bar colour follows row status so the eye groups colour=meaning.
  const bar = status === 'complete' ? 'bg-emerald-500'
            : status === 'failed'   ? 'bg-red-500'
            : status === 'running'  ? 'bg-blue-500'
                                    : 'bg-slate-200';
  return (
    <li>
      <div className="flex items-center gap-3">
        <Badge status={status} />
        <span className="text-sm flex-1">{st.label}</span>
        <span className="text-xs text-slate-400 tabular-nums whitespace-nowrap">
          {done}/{st.expected} · {percent}%
        </span>
      </div>
      <div className="h-1 mt-1.5 rounded-full bg-slate-100 overflow-hidden ml-[3.25rem]">
        <div
          className={`h-full ${bar} transition-all duration-300`}
          style={{ width: `${Math.min(100, percent)}%` }}
        />
      </div>
    </li>
  );
}

// Backend writes IN_PROGRESS / OK / FAILED / COMPLETE; UI buckets them.
function normalizeStatus(s) {
  const t = String(s || 'pending').toUpperCase();
  if (t === 'COMPLETE' || t === 'OK' || t === 'SUCCESS')   return 'complete';
  if (t === 'FAILED'   || t === 'ERROR')                    return 'failed';
  if (t === 'IN_PROGRESS' || t === 'RUNNING')               return 'running';
  if (t === 'PENDING') return 'pending';
  return s ? 'running' : 'pending';
}

function Badge({ status }) {
  const styles = {
    pending:   'bg-slate-200 text-slate-700',
    running:   'bg-blue-100 text-blue-700 animate-pulse',
    complete:  'bg-emerald-100 text-emerald-700',
    failed:    'bg-red-100 text-red-700',
    ok:        'bg-emerald-100 text-emerald-700',
  };
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded ${styles[status] || styles.pending}`}>
      {status}
    </span>
  );
}

function Stats({ stats, steps }) {
  // Count REAL stages only - the runner has 35 stages incl. gates. Log-echo
  // rows from streamed stderr (one per ABAP file, one per scan line, etc.)
  // are NOT counted - that was the "2/38277" bug.
  const stageRows = (steps || []).filter((s) => s?.details?.is_stage);
  const total = ALL_STAGE_IDS.length;
  const done = stageRows.filter((s) => {
    const t = String(s.status || '').toUpperCase();
    return t === 'COMPLETE' || t === 'OK' || t === 'SUCCESS';
  }).length;
  const percent = total > 0 ? Math.round((done / total) * 100) : 0;
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <Stat label="Stages complete" value={`${done}/${total} · ${percent}%`} />
      <Stat label="Rows extracted"  value={stats?.rows_extracted ?? '—'} />
      <Stat label="Rows loaded"     value={stats?.rows_loaded ?? '—'} />
      <Stat label="Dead-lettered"   value={stats?.dead_letters ?? '—'} />
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div>
      <div className="text-xs text-slate-500 uppercase tracking-wide">{label}</div>
      <div className="text-xl font-semibold">{String(value)}</div>
    </div>
  );
}
