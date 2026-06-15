// Project page: brutally honest tracker + Start migration button +
// auto-generated link to LiveOps in a new tab + on-demand PDF.
import React, { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, downloadFile } from '../../lib/api';

const STAGES = [
  { id: 'pre',        label: 'Pre-flight (anchor discovery + customizing check)' },
  { id: 'extract',    label: 'Extract from ECC' },
  { id: 'transform',  label: 'Transform + DQ' },
  { id: 'load_bapi',  label: 'Load via BAPI lane' },
  { id: 'load_mc',    label: 'Load via Migration Cockpit lane' },
  { id: 'reconcile',  label: 'Reconcile + audit chain' },
  { id: 'spool',      label: 'Capture FAGLB03 / MB5B spools' },
  { id: 'verdict',    label: 'Cutover verdict (precedence rule)' },
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
  const byStage = {};
  for (const s of steps) {
    const key = (s.step || '').split('.')[0];
    byStage[key] = s;
  }
  return (
    <ul className="space-y-2">
      {STAGES.map((st) => {
        const s = byStage[st.id];
        const status = s?.status || 'pending';
        return (
          <li key={st.id} className="flex items-center gap-3">
            <Badge status={status} />
            <span className="text-sm flex-1">{st.label}</span>
            {s?.duration_ms && (
              <span className="text-xs text-slate-400">{s.duration_ms} ms</span>
            )}
          </li>
        );
      })}
    </ul>
  );
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
  const total = steps?.length || 0;
  const done = (steps || []).filter((s) =>
    ['complete', 'ok'].includes(s.status)).length;
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <Stat label="Steps complete" value={`${done}/${total}`} />
      <Stat label="Rows extracted" value={stats?.rows_extracted ?? '—'} />
      <Stat label="Rows loaded"    value={stats?.rows_loaded ?? '—'} />
      <Stat label="Dead-lettered"  value={stats?.dead_letters ?? '—'} />
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
