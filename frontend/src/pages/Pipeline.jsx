import { useCallback, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Zap, Search, Activity, AlertTriangle, CheckCircle2, Circle, Clock, ListChecks,
  Download, Eye, FileText,
} from 'lucide-react';
import { api, downloadFile, openInTab } from '../lib/api';
import { useApi, useAction } from '../lib/useApi';
import { useToast } from '../lib/toast.jsx';
import { useActiveRun } from '../lib/activeRun.jsx';
import {
  Panel, PageHeader, StatusPill, MetricTile, Spinner, OfflineBanner, EmptyState, CmdLine, KVList,
} from '../components/dd';
import { STAGE_ENGINES, engineFor } from '../lib/stages';

// Phase tone → observability color. Used for the phase ribbon dot.
const PHASE_COLOR = {
  ASSESS: 'var(--accent)', PROVISION: '#a78bfa', CODE: 'var(--info)',
  CONFIG: '#14b8a6', DATA_PREP: 'var(--warn)', DATA_LOAD: 'var(--warn)',
  VALIDATE: 'var(--ok)', CUTOVER: 'var(--err)', RUN: 'var(--ok)',
};

const pretty = (handler, extra) => {
  if (!handler) return extra?.gate ? `Gate · ${extra.gate.replace(/_/g, ' ')}` : 'Manual gate';
  return handler.replace('.handler', '').replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
};
const token = (h) => (h || '').split('.')[0];
const STEP_TONE = (s) => {
  const u = String(s || '').toUpperCase();
  if (u.includes('COMPLETE') || u === 'SUCCESS' || u === 'OK' || u === 'DONE') return 'ok';
  if (u.includes('PROGRESS') || u === 'RUNNING') return 'info';
  if (u.includes('FAIL') || u.includes('ERROR')) return 'err';
  return 'muted';
};

export default function Pipeline() {
  const toast = useToast();
  const { setActiveRunId } = useActiveRun();
  const stagesQ = useApi(useCallback(() => api.stages(), []));
  const statusQ = useApi(useCallback(() => api.status(), []), { pollMs: 3000 });
  const progressQ = useApi(useCallback(() => api.progress(0), []), { pollMs: 3000 });
  const runsQ = useApi(useCallback(() => api.runs(), []), { pollMs: 10000 });
  const [pdfBusy, setPdfBusy] = useState(null);

  // When a new run starts, the api returns its id — make it the active run
  // so every other page (Logs, Report, Runs) immediately follows the new context.
  const adoptRun = (r) => { if (r?.run_id) setActiveRunId(r.run_id); };

  const assess = useAction(async () => {
    try {
      const r = await api.trigger('assess');
      adoptRun(r);
      toast.success('Assessment started', r?.run_id ? `Run ${r.run_id}` : 'Pipeline kicked off');
      return r;
    } catch (e) { toast.error('Could not start assessment', e.message); throw e; }
  });
  const full = useAction(async () => {
    try {
      const r = await api.trigger('full');
      adoptRun(r);
      toast.success('Full pipeline started', r?.run_id ? `Run ${r.run_id}` : 'Pipeline kicked off');
      return r;
    } catch (e) { toast.error('Could not start pipeline', e.message); throw e; }
  });
  const [selected, setSelected] = useState(null);

  const running = statusQ.data?.status === 'running';
  const steps = progressQ.data?.steps || [];

  const { doneTokens, runningToken } = useMemo(() => {
    const done = new Set();
    let run = null;
    for (const s of steps) {
      const t = STEP_TONE(s.status);
      const key = String(s.stage || '').toLowerCase();
      if (t === 'ok') done.add(key);
      if (t === 'info') run = key;
    }
    return { doneTokens: done, runningToken: run };
  }, [steps]);

  const stageStatus = (handler) => {
    const k = token(handler).toLowerCase();
    if (!k) return 'idle';
    const matchDone = [...doneTokens].some((d) => d && (d.includes(k) || k.includes(d)));
    const matchRun = runningToken && (runningToken.includes(k) || k.includes(runningToken));
    if (matchRun) return 'running';
    if (matchDone) return 'completed';
    return running ? 'queued' : 'idle';
  };

  if (stagesQ.loading) {
    return <div className="flex items-center gap-2 text-xs text-ink-3 py-20 justify-center"><Spinner /> Loading pipeline…</div>;
  }
  if (stagesQ.error) {
    return (
      <div className="space-y-4">
        <PageHeader title="Pipeline" breadcrumb={['Migrate4HANA', 'Pipeline']} subtitle="27 orchestrated stages across 9 phases." />
        <OfflineBanner onRetry={stagesQ.reload} />
      </div>
    );
  }

  const stages = stagesQ.data?.stages || [];
  const phases = stages.reduce((acc, s) => { (acc[s.phase] = acc[s.phase] || []).push(s); return acc; }, {});
  const completedCount = stages.filter((s) => stageStatus(s.handler) === 'completed').length;
  const pct = stages.length ? Math.round((completedCount / stages.length) * 100) : 0;
  const selectedStage = selected ? stages.find((s) => s.id === selected || s.handler === selected) : null;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Pipeline"
        breadcrumb={['Migrate4HANA', 'Pipeline']}
        subtitle={`${stages.length} stages · ${Object.keys(phases).length} phases · live status from the orchestration plane.`}
        actions={
          <>
            <button onClick={() => assess.run()} disabled={running || assess.busy} className="btn btn-sm">
              {assess.busy ? <Spinner size={12} /> : <Search size={12} />} Assess
            </button>
            <button onClick={() => full.run()} disabled={running || full.busy} className="btn btn-sm btn-primary">
              {full.busy ? <Spinner size={12} /> : <Zap size={12} />} Run full
            </button>
          </>
        }
      />

      {/* Latest PDF banner — visible whenever there's a run on disk */}
      {(() => {
        const latest = Array.isArray(runsQ.data) && runsQ.data[0];
        if (!latest) return null;
        const latestId = latest.id || latest.run_id;
        const dlPdf = async () => {
          setPdfBusy('download');
          const tId = toast.loading('Generating PDF…', latestId);
          try {
            await downloadFile(`/api/runs/${latestId}/pdf`, `migration-report-${latestId}.pdf`);
            toast.dismiss(tId); toast.success('PDF downloaded', latestId);
          } catch (e) { toast.dismiss(tId); toast.error('Download failed', e.message); }
          finally { setPdfBusy(null); }
        };
        const prevPdf = async () => {
          setPdfBusy('preview');
          try { await openInTab(`/api/runs/${latestId}/pdf`); toast.info('Opening PDF', latestId); }
          catch (e) { toast.error('Preview failed', e.message); }
          finally { setPdfBusy(null); }
        };
        return (
          <Panel
            title="Latest run report"
            icon={FileText}
            subtitle={`${latestId} · ${latest.status || 'unknown'}`}
            actions={<StatusPill tone={latest.status === 'completed' || latest.status === 'success' || latest.status === 'succeeded' ? 'ok' : 'muted'}>{latest.status || 'unknown'}</StatusPill>}
          >
            <div className="flex items-center gap-2 flex-wrap">
              <button onClick={prevPdf} disabled={!!pdfBusy} className="btn btn-sm">
                {pdfBusy === 'preview' ? <Spinner size={12} /> : <Eye size={12} />} Preview PDF
              </button>
              <button onClick={dlPdf} disabled={!!pdfBusy} className="btn btn-sm btn-primary">
                {pdfBusy === 'download' ? <Spinner size={12} /> : <Download size={12} />} Download PDF
              </button>
              <span className="text-[11px] text-ink-4 ml-auto">PDF is generated on demand from this run's artifacts.</span>
            </div>
          </Panel>
        );
      })()}

      {(assess.error || full.error) && (
        <Panel><div className="text-xs flex items-center gap-2" style={{ color: 'var(--err)' }}><AlertTriangle size={13} /> {(assess.error || full.error).message}</div></Panel>
      )}

      {/* Metric strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <MetricTile
          label="Run state"
          value={running ? 'Running' : statusQ.data?.status === 'completed' ? 'Completed' : statusQ.data?.status === 'failed' ? 'Failed' : 'Idle'}
          sub={statusQ.data?.mode}
          tone={running ? null : statusQ.data?.status === 'completed' ? 'ok' : statusQ.data?.status === 'failed' ? 'err' : null}
        />
        <MetricTile label="Stages complete" value={`${completedCount}/${stages.length}`} sub={`${pct}%`} />
        <MetricTile label="Phases" value={Object.keys(phases).length} sub="SAP Activate" />
        <MetricTile label="Events" value={progressQ.data?.total_steps ?? steps.length} sub="lifetime" />
      </div>

      {/* Progress bar */}
      <Panel title="Run progress" icon={Activity} subtitle={statusQ.data?.run_id || 'no active run'}>
        <div className="flex items-center gap-3">
          <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: 'var(--bg-elev)' }}>
            <motion.div
              className="h-full rounded-full"
              style={{ background: 'var(--accent)' }}
              initial={{ width: 0 }} animate={{ width: `${pct}%` }}
              transition={{ duration: 0.6, ease: [0.4, 0, 0.2, 1] }}
            />
          </div>
          <span className="text-xs font-mono text-ink-3 tabular-nums shrink-0">{pct}%</span>
        </div>
        <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-2">
          <CmdLine cmd="python run_local_lift_and_shift.py --through stage21" />
          <CmdLine cmd="python run_local_lift_and_shift.py --run-id RUN-001" />
        </div>
      </Panel>

      {/* Stage tracks by phase + drill panel */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-3 items-start">
        <div className="space-y-3">
          {Object.entries(phases).map(([phase, list]) => (
            <Panel
              key={phase}
              title={phase.replace(/_/g, ' ')}
              icon={() => <span className="w-2 h-2 rounded-full shrink-0" style={{ background: PHASE_COLOR[phase] || 'var(--accent)' }} />}
              actions={<span className="text-[10px] text-ink-4 font-mono">{list.length} stages</span>}
              flush
            >
              <div className="divide-y" style={{ borderColor: 'var(--border)' }}>
                {list.map((s) => {
                  const st = stageStatus(s.handler);
                  const isSel = selected === s.id;
                  const engine = engineFor(s.handler);
                  return (
                    <button
                      key={s.id}
                      onClick={() => setSelected(isSel ? null : s.id)}
                      className={`w-full flex items-center gap-3 px-3.5 py-2.5 text-left hover:bg-bg-elev ${isSel ? 'bg-bg-elev' : ''}`}
                      style={isSel ? { background: 'var(--bg-elev)' } : undefined}
                    >
                      <span className="shrink-0 w-5 flex justify-center">
                        {st === 'completed' ? <CheckCircle2 size={14} style={{ color: 'var(--ok)' }} /> :
                         st === 'running'   ? <Spinner size={14} /> :
                         st === 'queued'    ? <Clock size={13} className="text-ink-4" /> :
                                              <Circle size={12} className="text-ink-5" />}
                      </span>
                      <span className="text-[10.5px] font-mono text-ink-4 w-9 shrink-0">{s.id}</span>
                      <span className={`text-[12.5px] truncate flex-1 ${st === 'completed' ? 'text-ink-2' : st === 'running' ? 'text-ink-1 font-semibold' : 'text-ink-3'}`}>
                        {pretty(s.handler, s.extra)}
                      </span>
                      {engine && (
                        <span className="text-[9.5px] font-semibold px-1.5 py-0.5 rounded-full text-accent" style={{ background: 'var(--accent-soft)' }} title={engine.label}>
                          {engine.vendor}
                        </span>
                      )}
                      {st === 'running' && <StatusPill tone="info">live</StatusPill>}
                    </button>
                  );
                })}
              </div>
            </Panel>
          ))}
        </div>

        {/* Drill panel */}
        <div className="sticky top-3">
          {selectedStage ? (
            <Panel title={pretty(selectedStage.handler, selectedStage.extra)} subtitle={`Stage ${selectedStage.id}`}>
              <StatusPill tone={stageStatus(selectedStage.handler) === 'completed' ? 'ok' : stageStatus(selectedStage.handler) === 'running' ? 'info' : 'muted'}>
                {stageStatus(selectedStage.handler)}
              </StatusPill>
              <div className="mt-3">
                <KVList
                  cols={2}
                  items={[
                    { label: 'Phase', value: selectedStage.phase?.replace(/_/g, ' ') || '—' },
                    { label: 'Handler', value: selectedStage.handler || '—' },
                    { label: 'Engine', value: engineFor(selectedStage.handler)?.vendor || '—' },
                    { label: 'Class', value: engineFor(selectedStage.handler)?.label || '—' },
                  ]}
                />
              </div>
              <div className="mt-4">
                <div className="metric-label mb-1.5">Engine description</div>
                <p className="text-[11.5px] text-ink-2 leading-relaxed">
                  {engineFor(selectedStage.handler)?.label || 'Standard orchestration stage. No specialised engine attached.'}
                </p>
              </div>
            </Panel>
          ) : (
            <Panel title="Engines embedded" icon={Activity}>
              <div className="space-y-2.5">
                {Object.entries(STAGE_ENGINES).map(([tok, e]) => (
                  <div key={tok} className="flex items-center gap-2.5">
                    <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--accent)' }} />
                    <div className="min-w-0">
                      <div className="text-[12px] font-semibold text-ink-1">{e.vendor}-class</div>
                      <div className="text-[10.5px] text-ink-3 truncate">{e.label}</div>
                    </div>
                  </div>
                ))}
              </div>
              <p className="text-[10.5px] text-ink-4 mt-3">Click any stage to see its detail.</p>
            </Panel>
          )}
        </div>
      </div>

      {/* Live activity feed */}
      <Panel
        title="Live activity"
        icon={Activity}
        actions={<span className="text-[10.5px] font-mono text-ink-4">{steps.length} events</span>}
        flush
      >
        {steps.length === 0 ? (
          <EmptyState icon={ListChecks} title="No activity yet" hint="Trigger Assess or Run full pipeline — real progress events stream here." />
        ) : (
          <div className="max-h-80 overflow-y-auto">
            <table className="dt">
              <thead><tr><th>Status</th><th>Stage</th><th>Action</th><th>Duration</th></tr></thead>
              <tbody>
                {steps.slice().reverse().map((s) => (
                  <tr key={s.event_id}>
                    <td><StatusPill tone={STEP_TONE(s.status)}>{s.status}</StatusPill></td>
                    <td className="font-medium text-ink-1">{s.stage}</td>
                    <td className="text-ink-3 truncate max-w-[260px]">{s.action}</td>
                    <td className="text-ink-4 tabular-nums">{s.duration_ms != null ? `${(s.duration_ms / 1000).toFixed(1)}s` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
