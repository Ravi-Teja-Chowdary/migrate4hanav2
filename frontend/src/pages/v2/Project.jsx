// Project page: brutally honest tracker + Start migration button +
// auto-generated link to LiveOps in a new tab + on-demand PDF.
import React, { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, downloadFile } from '../../lib/api';

// The 8 phases the lift-and-shift runner actually emits. Stage IDs (stage1..
// stage27, gate1/2/3) map to these phases server-side via _STAGE_PHASE_MAP
// in api_server.py. The Project tracker shows ONE row per phase, rolled up
// from however many stages it contains.
const STAGES = [
  { id: 'ASSESS',    label: 'Assess - discovery, sizing, object routing' },
  { id: 'PROVISION', label: 'Provision - target system + basis gate' },
  { id: 'CODE',      label: 'Code - analyze, remediate, transport, import' },
  { id: 'CONFIG',    label: 'Config - replicate customizing + BC sets' },
  { id: 'DATA_PREP', label: 'Data prep - extract, hygiene, templates' },
  { id: 'DATA_LOAD', label: 'Data load - Migration Cockpit / LTMOM / IDoc' },
  { id: 'VALIDATE',  label: 'Validate - completeness + pre-cutover gate' },
  { id: 'CUTOVER',   label: 'Cutover - lock ECC, delta, final go-live' },
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

  useEffect(() => {
    api.wizardGet(runId).then(setWizard).catch((e) => setErr(e.message));
  }, [runId]);

  // Poll live progress when a run is active.
  useEffect(() => {
    let cancelled = false;
    let timer = null;
    async function poll() {
      try {
        const p = await api.progress(0);
        if (!cancelled) setProgress({ steps: p.steps || [], stats: p.stats });
      } catch { /* network blip is fine */ }
      if (!cancelled) timer = setTimeout(poll, 3000);
    }
    if (activeRun) poll();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [activeRun]);

  const startMigration = async () => {
    setStarting(true); setErr('');
    try {
      const r = await api.triggerLiftAndShift({
        run_id: runId,
        migration_type: wizard.migration_type,
        selective_objects: wizard.selective_objects || [],
        ecc_version: wizard.ecc_version,
        s4_version:  wizard.s4_version,
      });
      const pipeline_run_id = r.run_id || r.execution_id || runId;
      setActiveRun(pipeline_run_id);
      await api.wizardPatch(runId, {
        page: 'project',
        pipeline_run_id,
        started_at: new Date().toISOString(),
      });
    } catch (e) {
      setErr(e.message);
    } finally { setStarting(false); }
  };

  const downloadPdf = async () => {
    setErr('');
    try {
      await downloadFile(
        `/api/runs/${encodeURIComponent(activeRun || runId)}/pdf`,
        `migrate4hana-${activeRun || runId}.pdf`);
    } catch (e) { setErr(e.message); }
  };

  if (!wizard) return <div className="text-slate-500">Loading…</div>;

  return (
    <div>
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

      <Section title="Project tracker">
        <StageList steps={progress.steps} />
      </Section>

      <Section title="Stats">
        <Stats stats={progress.stats} steps={progress.steps} />
      </Section>

      <Section title="Actions">
        <div className="flex flex-wrap gap-3 items-center">
          <button
            onClick={startMigration}
            disabled={starting || activeRun}
            className="px-5 py-2.5 rounded bg-orange-500 hover:bg-orange-600 disabled:bg-orange-300 text-white font-medium"
          >
            {starting ? 'Starting…' : activeRun ? 'Running' : 'Start migration'}
          </button>

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
        </div>
        <div className="text-xs text-slate-500 mt-3 leading-relaxed">
          The PDF can be downloaded any time during the run — each download
          captures the comprehensive state up to that moment. After the run
          completes, the PDF is the full final report.
        </div>
      </Section>
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
  // Roll up by PHASE id. A phase is COMPLETE only if at least one stage
  // ran AND none of its stages ended in ERROR; otherwise it inherits the
  // worst outcome we've seen.
  const byPhase = {};
  for (const s of stageRows) {
    const phaseId = s.stage;
    if (!STAGES.some((st) => st.id === phaseId)) continue;
    const cur = byPhase[phaseId] || { count: 0, hasErr: false, hasRun: false, last: null };
    cur.count += 1;
    cur.hasErr = cur.hasErr || normalizeStatus(s.status) === 'failed';
    cur.hasRun = cur.hasRun || ['running', 'complete', 'failed'].includes(normalizeStatus(s.status));
    cur.last = s;
    byPhase[phaseId] = cur;
  }
  return (
    <ul className="space-y-2">
      {STAGES.map((st) => {
        const ph = byPhase[st.id];
        let status = 'pending';
        if (ph) {
          if (ph.hasErr) status = 'failed';
          else if (ph.last && normalizeStatus(ph.last.status) === 'complete') {
            status = 'complete';
          } else if (ph.hasRun) status = 'running';
        }
        return (
          <li key={st.id} className="flex items-center gap-3">
            <Badge status={status} />
            <span className="text-sm flex-1">{st.label}</span>
            {ph?.count != null && (
              <span className="text-xs text-slate-400">{ph.count} stage{ph.count === 1 ? '' : 's'}</span>
            )}
          </li>
        );
      })}
    </ul>
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
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <Stat label="Stages complete" value={`${done}/${total}`} />
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
