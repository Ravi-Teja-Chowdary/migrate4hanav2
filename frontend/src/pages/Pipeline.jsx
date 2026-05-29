import { useCallback, useMemo } from 'react';
import { motion } from 'framer-motion';
import {
  Search, Rocket, CheckCircle2, Circle, AlertTriangle, Activity, ListChecks,
} from 'lucide-react';
import { api } from '../lib/api';
import { useApi, useAction } from '../lib/useApi';
import {
  Card, PageHeader, Badge, Spinner, ProgressBar, OfflineBanner, CommandBlock, EmptyState, ACCENT,
} from '../components/ui';
import { STAGE_ENGINES, engineFor } from '../lib/stages';

const PHASE_TONE = {
  ASSESS: 'indigo', PROVISION: 'violet', CODE: 'sky', CONFIG: 'teal',
  DATA_PREP: 'amber', DATA_LOAD: 'amber', VALIDATE: 'emerald', CUTOVER: 'rose', RUN: 'emerald',
};
const PHASE_HEX = {
  indigo: '#6366f1', violet: '#8b5cf6', sky: '#0ea5e9', teal: '#14b8a6',
  amber: '#f59e0b', emerald: '#10b981', rose: '#f43f5e',
};

function pretty(handler, extra) {
  if (!handler) return extra?.gate ? `Gate · ${extra.gate.replace(/_/g, ' ')}` : 'Manual gate';
  return handler.replace('.handler', '').replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}
function token(handler) {
  return (handler || '').split('.')[0];
}

const STEP_TONE = (s) => {
  const u = String(s || '').toUpperCase();
  if (u.includes('COMPLETE') || u === 'SUCCESS' || u === 'OK' || u === 'DONE') return 'completed';
  if (u.includes('PROGRESS') || u === 'RUNNING') return 'running';
  if (u.includes('FAIL') || u.includes('ERROR')) return 'failed';
  return 'info';
};

export default function Pipeline() {
  const stagesQ = useApi(useCallback(() => api.stages(), []));
  const statusQ = useApi(useCallback(() => api.status(), []), { pollMs: 3000 });
  const progressQ = useApi(useCallback(() => api.progress(0), []), { pollMs: 3000 });

  const assess = useAction(() => api.trigger('assess'));
  const full = useAction(() => api.trigger('full'));

  const running = statusQ.data?.status === 'running';
  const steps = progressQ.data?.steps || [];

  // best-effort live highlight from real progress steps (no fabrication)
  const { doneTokens, runningToken } = useMemo(() => {
    const done = new Set();
    let run = null;
    for (const s of steps) {
      const t = STEP_TONE(s.status);
      const key = String(s.stage || '').toLowerCase();
      if (t === 'completed') done.add(key);
      if (t === 'running') run = key;
    }
    return { doneTokens: done, runningToken: run };
  }, [steps]);

  function stageStatus(handler) {
    const k = token(handler).toLowerCase();
    if (!k) return 'idle';
    const matchDone = [...doneTokens].some((d) => d && (d.includes(k) || k.includes(d)));
    const matchRun = runningToken && (runningToken.includes(k) || k.includes(runningToken));
    if (matchRun) return 'running';
    if (matchDone) return 'completed';
    return running ? 'queued' : 'idle';
  }

  if (stagesQ.loading) {
    return <div className="flex items-center gap-2 text-ink-400 text-sm py-20 justify-center"><Spinner /> Loading pipeline…</div>;
  }
  if (stagesQ.error) {
    return (
      <div className="space-y-7">
        <PageHeader title="Migration" accentWord="Pipeline" subtitle="SAP Activate, 28 orchestrated stages." />
        <OfflineBanner onRetry={stagesQ.reload} />
      </div>
    );
  }

  const stages = stagesQ.data?.stages || [];
  const phases = stages.reduce((acc, s) => {
    (acc[s.phase] = acc[s.phase] || []).push(s);
    return acc;
  }, {});
  const completedCount = stages.filter((s) => stageStatus(s.handler) === 'completed').length;
  const pct = stages.length ? Math.round((completedCount / stages.length) * 100) : 0;

  const statusBadge = statusQ.error
    ? null
    : running
      ? <Badge tone="running"><Spinner size={12} /> Running · {statusQ.data?.mode}</Badge>
      : statusQ.data?.status === 'completed'
        ? <Badge tone="ok"><CheckCircle2 size={12} /> Completed</Badge>
        : statusQ.data?.status === 'failed'
          ? <Badge tone="failed"><AlertTriangle size={12} /> Failed</Badge>
          : <Badge tone="pending">Idle</Badge>;

  return (
    <div className="space-y-7">
      <PageHeader
        title="Migration" accentWord="Pipeline"
        subtitle={`${stages.length} orchestrated stages across ${Object.keys(phases).length} phases — live status from the backend.`}
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={() => assess.run()} disabled={running || assess.busy}
              className="focusable inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-indigo-50 text-indigo-700 text-[13px] font-semibold hover:bg-indigo-100 transition disabled:opacity-50"
            >
              {assess.busy ? <Spinner size={14} /> : <Search size={15} />} Assess
            </button>
            <button
              onClick={() => full.run()} disabled={running || full.busy}
              className="focusable btn-primary inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-[13px] font-bold disabled:opacity-60"
            >
              {full.busy ? <Spinner size={14} className="text-white" /> : <Rocket size={15} />} Run Full Pipeline
            </button>
          </div>
        }
      />

      {(assess.error || full.error) && (
        <Card className="p-3 border-rose-200/60">
          <p className="text-xs text-rose-600 flex items-center gap-2"><AlertTriangle size={13} /> {(assess.error || full.error).message}</p>
        </Card>
      )}

      {/* Status + progress */}
      <Card className="p-5">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            {statusBadge}
            {statusQ.data?.run_id && <span className="text-xs font-mono text-ink-400">{statusQ.data.run_id}</span>}
          </div>
          <span className="text-xs font-mono text-ink-400">{completedCount}/{stages.length} · {pct}%</span>
        </div>
        <ProgressBar value={pct} />
        <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-2">
          <CommandBlock cmd="python run_local_lift_and_shift.py --through stage21" />
          <CommandBlock cmd="python run_local_lift_and_shift.py --run-id RUN-001" />
        </div>
      </Card>

      {/* Competitor-grade engines embedded INSIDE these stages */}
      <Card className="p-5">
        <p className="text-[12.5px] font-semibold text-ink-700 mb-3">Competitor-grade engines embedded in our stages</p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {Object.entries(STAGE_ENGINES).map(([tok, e]) => {
            const a = ACCENT[e.accent];
            return (
              <div key={tok} className={`rounded-2xl ${a.bg} p-3.5`}>
                <p className={`text-[13px] font-bold ${a.text}`}>{e.vendor}-class</p>
                <p className="text-[11px] text-ink-500 mt-0.5">{e.label}</p>
                <p className="text-[10px] font-mono text-ink-400 mt-1.5">in stage · {tok}</p>
              </div>
            );
          })}
        </div>
      </Card>

      {/* Stage timeline by phase */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {Object.entries(phases).map(([phase, list]) => {
          const tone = PHASE_TONE[phase] || 'indigo';
          const hex = PHASE_HEX[tone];
          return (
            <Card key={phase} className="p-5">
              <div className="flex items-center gap-2.5 mb-4">
                <span className="w-2 h-2 rounded-full" style={{ background: hex }} />
                <h3 className="text-[13px] font-semibold uppercase tracking-wider text-ink-600">{phase.replace(/_/g, ' ')}</h3>
                <span className="ml-auto text-[10px] font-mono text-ink-300">{list.length}</span>
              </div>
              <div className="space-y-1.5">
                {list.map((s) => {
                  const st = stageStatus(s.handler);
                  return (
                    <div key={s.id} className="flex items-center gap-3 py-1.5">
                      <span className="w-6 shrink-0 flex justify-center">
                        {st === 'completed' ? <CheckCircle2 size={16} style={{ color: hex }} />
                          : st === 'running' ? <Spinner size={15} className="" />
                          : <Circle size={12} className="text-ink-300" />}
                      </span>
                      <span className="text-[10px] font-mono text-ink-300 w-12 shrink-0">{s.id}</span>
                      <span className={`text-[13px] truncate ${st === 'completed' ? 'text-ink-700' : st === 'running' ? 'text-ink-900 font-medium' : 'text-ink-500'}`}>
                        {pretty(s.handler, s.extra)}
                      </span>
                      <span className="ml-auto flex items-center gap-1.5 shrink-0">
                        {engineFor(s.handler) && (
                          <span
                            title={engineFor(s.handler).label}
                            className={`hidden sm:inline-flex items-center gap-1 text-[9.5px] font-semibold px-1.5 py-0.5 rounded-full ${ACCENT[engineFor(s.handler).accent].bg} ${ACCENT[engineFor(s.handler).accent].text}`}
                          >
                            {engineFor(s.handler).vendor}
                          </span>
                        )}
                        {st === 'running' && <Badge tone="running">live</Badge>}
                      </span>
                    </div>
                  );
                })}
              </div>
            </Card>
          );
        })}
      </div>

      {/* Live activity feed */}
      <Card className="p-5">
        <div className="flex items-center gap-2 mb-3">
          <Activity size={16} className="text-indigo-600" />
          <h3 className="text-[13px] font-semibold text-ink-700 uppercase tracking-wider">Live Activity</h3>
          {progressQ.data?.total_steps != null && <span className="ml-auto text-xs font-mono text-ink-400">{progressQ.data.total_steps} events</span>}
        </div>
        {steps.length === 0 ? (
          <EmptyState icon={ListChecks} title="No activity yet" hint="Trigger Assess or Run Full Pipeline — real progress events stream here." />
        ) : (
          <div className="space-y-1 max-h-80 overflow-y-auto pr-1">
            {steps.slice().reverse().map((s) => (
              <motion.div key={s.event_id} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }}
                className="flex items-center gap-3 py-1.5 border-b border-line/70 last:border-0">
                <Badge tone={STEP_TONE(s.status)}>{s.status}</Badge>
                <span className="text-[13px] text-ink-700 truncate">{s.stage}</span>
                <span className="text-xs text-ink-400 truncate flex-1">{s.action}</span>
                {s.duration_ms != null && <span className="text-[10px] font-mono text-ink-300">{(s.duration_ms / 1000).toFixed(1)}s</span>}
              </motion.div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
