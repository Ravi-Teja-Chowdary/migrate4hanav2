import { useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Server, Cloud, ArrowRight, CheckCircle2, Circle, Clock3, Gauge, Cpu,
} from 'lucide-react';
import { api } from '../lib/api';
import { useApi } from '../lib/useApi';
import {
  Card, PageHeader, Badge, Spinner, ProgressBar, OfflineBanner, EmptyState, ACCENT,
} from '../components/ui';
import { PHASE_TONE, PHASE_HEX, prettyStage, engineFor, makeStageStatus } from '../lib/stages';

function Board({ icon: Icon, label, accent, system, host, online }) {
  const a = ACCENT[accent];
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="card rounded-3xl p-5 relative overflow-hidden flex-1 min-w-0">
      <div className="absolute inset-x-0 top-0 h-1" style={{ background: PHASE_HEX[accent] }} />
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3 min-w-0">
          <div className={`w-11 h-11 rounded-2xl ${a.bg} flex items-center justify-center shrink-0`}>
            <Icon size={20} className={a.text} />
          </div>
          <div className="min-w-0">
            <p className="text-[10px] uppercase tracking-widest text-ink-400 font-semibold">{label}</p>
            <h3 className="text-sm font-semibold text-ink-900 truncate">{system}</h3>
          </div>
        </div>
        <Badge tone={online ? 'ok' : 'pending'}>{online ? 'connected' : 'not set'}</Badge>
      </div>
      <p className="text-xs font-mono text-ink-400 mt-3 truncate">{host || '—'}</p>
    </motion.div>
  );
}

function StageChip({ stage, status }) {
  const tone = PHASE_TONE[stage.phase] || 'indigo';
  const hex = PHASE_HEX[tone];
  const eng = engineFor(stage.handler);
  const running = status === 'running';
  const done = status === 'completed';
  return (
    <motion.div layout initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }}
      className="rounded-xl border bg-white px-3.5 py-2.5"
      style={{ borderColor: running ? `${hex}66` : '#eef2f7', boxShadow: running ? `0 6px 18px ${hex}22` : '0 1px 2px rgba(16,24,40,.04)' }}>
      <div className="flex items-center gap-2.5">
        <span className="shrink-0">
          {done ? <CheckCircle2 size={15} style={{ color: hex }} />
            : running ? <Spinner size={14} />
            : <Circle size={11} className="text-ink-300" />}
        </span>
        <span className="text-[10px] font-mono text-ink-300 shrink-0">{stage.id}</span>
        <span className={`text-[12.5px] truncate ${done ? 'text-ink-600' : running ? 'text-ink-900 font-medium' : 'text-ink-500'}`}>
          {prettyStage(stage.handler, stage.extra)}
        </span>
      </div>
      {eng && (
        <div className="mt-1.5 ml-7 flex items-center gap-1">
          <Cpu size={10} className={ACCENT[eng.accent].text} />
          <span className={`text-[10px] font-medium ${ACCENT[eng.accent].text}`}>{eng.vendor}-class engine</span>
        </div>
      )}
    </motion.div>
  );
}

function Column({ title, icon: Icon, tone, stages, statusOf }) {
  return (
    <Card className="p-5 flex flex-col">
      <div className="flex items-center gap-2 mb-3">
        <Icon size={15} className={tone.text} />
        <h3 className="text-[12.5px] font-semibold uppercase tracking-wider text-ink-600">{title}</h3>
        <span className={`ml-auto text-[10px] font-mono px-2 py-0.5 rounded-full ${tone.badge}`}>{stages.length}</span>
      </div>
      <div className="space-y-2 flex-1">
        <AnimatePresence>
          {stages.map((s) => <StageChip key={s.id} stage={s} status={statusOf(s.handler)} />)}
        </AnimatePresence>
        {stages.length === 0 && (
          <div className="rounded-xl border border-dashed border-line py-8 text-center"><p className="text-[11px] text-ink-300">None</p></div>
        )}
      </div>
    </Card>
  );
}

export default function ProjectTracker() {
  const stagesQ = useApi(useCallback(() => api.stages(), []));
  const statusQ = useApi(useCallback(() => api.status(), []), { pollMs: 3000 });
  const progressQ = useApi(useCallback(() => api.progress(0), []), { pollMs: 3000 });
  const connQ = useApi(useCallback(() => api.connections(), []));

  const running = statusQ.data?.status === 'running';
  const statusOf = useMemo(() => makeStageStatus(progressQ.data?.steps || [], running),
    [progressQ.data, running]);

  if (stagesQ.loading) {
    return <div className="flex items-center gap-2 text-ink-400 text-sm py-20 justify-center"><Spinner /> Loading tracker…</div>;
  }
  if (stagesQ.error) {
    return (
      <div className="space-y-7">
        <PageHeader title="Project" accentWord="Tracker" subtitle="End-to-end migration status across all stages." />
        <OfflineBanner onRetry={stagesQ.reload} />
      </div>
    );
  }

  const stages = stagesQ.data?.stages || [];
  const completed = stages.filter((s) => statusOf(s.handler) === 'completed');
  const inProgress = stages.filter((s) => statusOf(s.handler) === 'running');
  const queued = stages.filter((s) => !['completed', 'running'].includes(statusOf(s.handler)));
  const pct = stages.length ? Math.round((completed.length / stages.length) * 100) : 0;

  const ecc = connQ.data?.ecc;
  const s4 = connQ.data?.s4hana || connQ.data?.lift_and_shift_target;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Project" accentWord="Tracker"
        subtitle="Live end-to-end status across the 28 stages — Start/End systems, overall progress, and a Completed / In-Progress / Queued board."
        actions={
          <Badge tone={running ? 'running' : statusQ.data?.status === 'completed' ? 'ok' : 'pending'}>
            {running && <Spinner size={11} />} {statusQ.data?.status || 'idle'}
          </Badge>
        }
      />

      {/* Start / End boards */}
      <div className="flex flex-col md:flex-row items-stretch gap-4">
        <Board icon={Server} label="Start · Source" accent="indigo"
          system={ecc?.ashost ? 'SAP ECC' : 'SAP ECC (not configured)'} host={ecc?.ashost} online={!!ecc?.ashost} />
        <div className="hidden md:flex items-center text-ink-300"><ArrowRight size={22} /></div>
        <Board icon={Cloud} label="End · Target" accent="teal"
          system={s4?.ashost || s4?.api_url ? 'S/4HANA (RISE)' : 'S/4HANA (not configured)'} host={s4?.ashost || s4?.api_url} online={!!(s4?.ashost || s4?.api_url)} />
      </div>

      {/* Overall progress */}
      <Card className="p-5">
        <div className="flex items-center justify-between mb-2.5">
          <span className="text-xs font-medium text-ink-500 flex items-center gap-1.5"><Gauge size={13} className="text-indigo-600" /> Overall migration progress</span>
          <span className="text-xs font-mono text-ink-400">{completed.length}/{stages.length} · {pct}%</span>
        </div>
        <ProgressBar value={pct} />
        {!running && completed.length === 0 && (
          <p className="text-[11px] text-ink-400 mt-2">No active run — all stages queued. Start one from the Pipeline page.</p>
        )}
      </Card>

      {/* Kanban */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <Column title="Completed" icon={CheckCircle2} stages={completed} statusOf={statusOf}
          tone={{ text: 'text-emerald-600', badge: 'bg-emerald-50 text-emerald-600' }} />
        <Column title="In-Progress" icon={Spinner} stages={inProgress} statusOf={statusOf}
          tone={{ text: 'text-sky-600', badge: 'bg-sky-50 text-sky-600' }} />
        <Column title="Queued" icon={Clock3} stages={queued} statusOf={statusOf}
          tone={{ text: 'text-ink-400', badge: 'bg-slate-100 text-ink-500' }} />
      </div>
    </div>
  );
}
