import { useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Server, Cloud, ArrowRight, CheckCircle2, Circle, Clock3, Gauge, Cpu } from 'lucide-react';
import { api } from '../lib/api';
import { useApi } from '../lib/useApi';
import { Panel, PageHeader, StatusPill, MetricTile, Spinner, OfflineBanner, EmptyState } from '../components/dd';
import { prettyStage, engineFor, makeStageStatus } from '../lib/stages';

function SystemBoard({ icon: Icon, label, system, host, online, tone }) {
  return (
    <Panel
      title={label}
      icon={Icon}
      actions={<StatusPill tone={online ? 'ok' : 'muted'}>{online ? 'connected' : 'not set'}</StatusPill>}
    >
      <div className="text-[13px] font-semibold text-ink-1 truncate">{system}</div>
      <div className="font-mono text-[11.5px] text-ink-3 mt-1 truncate">{host || '—'}</div>
    </Panel>
  );
}

function StageChip({ stage, status }) {
  const eng = engineFor(stage.handler);
  const running = status === 'running';
  const done = status === 'completed';
  const borderColor = running ? 'var(--info)' : 'var(--border)';
  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.97 }}
      animate={{ opacity: 1, scale: 1 }}
      className="rounded panel px-3 py-2"
      style={{ borderColor }}
    >
      <div className="flex items-center gap-2.5">
        <span className="shrink-0">
          {done ? <CheckCircle2 size={13} style={{ color: 'var(--ok)' }} />
            : running ? <Spinner size={12} />
            : <Circle size={10} className="text-ink-5" />}
        </span>
        <span className="text-[10px] font-mono text-ink-4 shrink-0">{stage.id}</span>
        <span className={`text-[12px] truncate ${done ? 'text-ink-2' : running ? 'text-ink-1 font-semibold' : 'text-ink-3'}`}>
          {prettyStage(stage.handler, stage.extra)}
        </span>
      </div>
      {eng && (
        <div className="mt-1 ml-6 flex items-center gap-1">
          <Cpu size={9} className="text-accent" />
          <span className="text-[10px] font-semibold text-accent">{eng.vendor}-class</span>
        </div>
      )}
    </motion.div>
  );
}

function Column({ title, icon: Icon, tone, stages, statusOf }) {
  return (
    <Panel
      title={title}
      icon={Icon}
      actions={<StatusPill tone={tone} dot={false}>{stages.length}</StatusPill>}
    >
      <div className="space-y-2">
        <AnimatePresence>
          {stages.map((s) => <StageChip key={s.id} stage={s} status={statusOf(s.handler)} />)}
        </AnimatePresence>
        {stages.length === 0 && (
          <div className="rounded border border-dashed py-6 text-center" style={{ borderColor: 'var(--border)' }}>
            <p className="text-[11px] text-ink-4">None</p>
          </div>
        )}
      </div>
    </Panel>
  );
}

export default function ProjectTracker() {
  const stagesQ = useApi(useCallback(() => api.stages(), []));
  const statusQ = useApi(useCallback(() => api.status(), []), { pollMs: 3000 });
  const progressQ = useApi(useCallback(() => api.progress(0), []), { pollMs: 3000 });
  const connQ = useApi(useCallback(() => api.connections(), []));

  const running = statusQ.data?.status === 'running';
  const statusOf = useMemo(
    () => makeStageStatus(progressQ.data?.steps || [], running),
    [progressQ.data, running]
  );

  if (stagesQ.loading) {
    return <div className="flex items-center gap-2 text-xs text-ink-3 py-20 justify-center"><Spinner /> Loading tracker…</div>;
  }
  if (stagesQ.error) {
    return (
      <div className="space-y-4">
        <PageHeader title="Project tracker" breadcrumb={['Migrate4HANA', 'Tracker']} subtitle="End-to-end migration status." />
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
  const eccHost = ecc?.ashost;
  const s4Host = s4?.ashost || s4?.api_url;

  const runStatus = statusQ.data?.status || 'idle';
  const runTone = running ? 'info' : runStatus === 'completed' ? 'ok' : runStatus === 'failed' ? 'err' : 'muted';

  return (
    <div className="space-y-4">
      <PageHeader
        title="Project tracker"
        breadcrumb={['Migrate4HANA', 'Tracker']}
        subtitle="Live end-to-end status across all stages: Start/End systems, overall progress, completed / in-progress / queued board."
        actions={<StatusPill tone={runTone}>{running ? 'running' : runStatus}</StatusPill>}
      />

      {/* Metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <MetricTile label="Completed" value={completed.length} sub={`of ${stages.length}`} tone="ok" />
        <MetricTile label="In progress" value={inProgress.length} sub={running ? 'live' : 'idle'} tone={inProgress.length > 0 ? 'info' : null} />
        <MetricTile label="Queued" value={queued.length} sub="not yet started" />
        <MetricTile label="Progress" value={pct} unit="%" sub={`${stages.length} stages`} />
      </div>

      {/* Start / End boards */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_28px_1fr] gap-3 items-stretch">
        <SystemBoard
          icon={Server}
          label="Start · Source"
          system={eccHost ? 'SAP ECC' : 'SAP ECC (not configured)'}
          host={eccHost}
          online={!!eccHost}
        />
        <div className="hidden lg:flex items-center justify-center text-ink-4"><ArrowRight size={20} /></div>
        <SystemBoard
          icon={Cloud}
          label="End · Target"
          system={s4Host ? 'S/4HANA' : 'S/4HANA (not configured)'}
          host={s4Host}
          online={!!s4Host}
        />
      </div>

      {/* Overall progress */}
      <Panel title="Overall progress" icon={Gauge} subtitle={statusQ.data?.run_id || 'no active run'}>
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
        {!running && completed.length === 0 && (
          <p className="text-[11px] text-ink-4 mt-2">No active run. Start one from the Pipeline page.</p>
        )}
      </Panel>

      {/* Kanban */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <Column title="Completed" icon={CheckCircle2} tone="ok" stages={completed} statusOf={statusOf} />
        <Column title="In-progress" icon={Spinner} tone="info" stages={inProgress} statusOf={statusOf} />
        <Column title="Queued" icon={Clock3} tone="muted" stages={queued} statusOf={statusOf} />
      </div>
    </div>
  );
}
