import { useEffect, useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Server, Cloud, ArrowRight, CheckCircle2, Loader2, Clock3, Circle,
  Wifi, ShieldCheck, Gauge, Activity,
} from 'lucide-react';
import { STAGES, PHASE_COLORS } from '../data/sampleData';
import { apiFetch } from '../api';

/**
 * Project Tracker — the end-to-end migration status surface.
 *
 *  • Start / End connectivity boards (Source ECC  →  Target S/4HANA RISE)
 *  • A fluidic overall progress pipeline
 *  • Kanban stage tracking: Completed · In-Progress (spinner + live RC) · Queued
 *
 * It self-fetches the live spine progress from the API and gracefully falls
 * back to a representative in-flight snapshot so the surface always renders.
 */

const DEFAULT_SOURCE = {
  system: 'SAP ECC 6.0 (Y01)', host: '192.168.100.10', sysnr: '00',
  client: '100', kind: 'source',
};
const DEFAULT_TARGET = {
  system: 'S/4HANA 2023 (S4H · RISE)', host: '13.220.175.153', sysnr: '00',
  client: '100', kind: 'target',
};

// A believable mid-flight snapshot: phases 1-2 done, stage 9 running, rest queued.
function fallbackSnapshot() {
  const runningIdx = 8; // zero-based → STAGES[8] is stage id 9
  return STAGES.map((s, i) => ({
    ...s,
    status: i < runningIdx ? 'completed' : i === runningIdx ? 'running' : 'queued',
    rc: i < runningIdx ? 0 : null,
    elapsed: i < runningIdx ? +(0.2 + Math.random() * 1.4).toFixed(1) : null,
  }));
}

function ConnectivityBoard({ board, label, online }) {
  const Icon = board.kind === 'source' ? Server : Cloud;
  const accent = board.kind === 'source' ? '#6366f1' : '#10b981';
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass rounded-2xl p-5 relative overflow-hidden"
    >
      <div className="absolute inset-x-0 top-0 h-1" style={{ background: accent }} />
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl flex items-center justify-center"
               style={{ backgroundColor: `${accent}14` }}>
            <Icon size={20} style={{ color: accent }} />
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">
              {label}
            </p>
            <h3 className="text-sm font-semibold text-slate-900 leading-tight">
              {board.system}
            </h3>
          </div>
        </div>
        <span className={`flex items-center gap-1.5 text-[11px] font-medium px-2.5 py-1 rounded-full
          ${online ? 'bg-accent-green/10 text-accent-green' : 'bg-accent-amber/10 text-accent-amber'}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${online ? 'bg-accent-green animate-pulse' : 'bg-accent-amber'}`} />
          {online ? 'Connected' : 'Mock / Offline'}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-3 mt-4">
        {[['Host', board.host], ['SysNr', board.sysnr], ['Client', board.client]].map(([k, v]) => (
          <div key={k} className="rounded-xl bg-slate-50 px-3 py-2 border border-slate-100">
            <p className="text-[9px] uppercase tracking-wider text-slate-400">{k}</p>
            <p className="text-xs font-mono text-slate-700 truncate">{v}</p>
          </div>
        ))}
      </div>
    </motion.div>
  );
}

function KanbanCard({ stage }) {
  const color = stage.color || PHASE_COLORS.blue;
  const running = stage.status === 'running';
  const done = stage.status === 'completed';
  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.97 }}
      animate={{ opacity: 1, scale: 1 }}
      className="rounded-xl border bg-white px-3.5 py-3 flex items-center gap-3"
      style={{
        borderColor: running ? `${color}55` : '#e2e8f0',
        boxShadow: running ? `0 6px 20px ${color}22` : '0 1px 2px rgba(15,23,42,0.04)',
      }}
    >
      <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
           style={{ backgroundColor: done ? `${color}16` : running ? `${color}12` : '#f1f5f9' }}>
        {done ? (
          <CheckCircle2 size={16} style={{ color }} />
        ) : running ? (
          <motion.span animate={{ rotate: 360 }}
            transition={{ duration: 1.2, repeat: Infinity, ease: 'linear' }}>
            <Loader2 size={16} style={{ color }} />
          </motion.span>
        ) : (
          <Circle size={13} className="text-slate-300" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] font-mono text-slate-400">#{stage.id}</span>
          <span className="text-[10px] px-1.5 py-px rounded-full"
                style={{ backgroundColor: `${color}14`, color }}>
            {stage.phase}
          </span>
        </div>
        <p className={`text-xs font-medium truncate ${done ? 'text-slate-600' : running ? 'text-slate-900' : 'text-slate-400'}`}>
          {stage.name}
        </p>
      </div>
      <div className="shrink-0 text-right">
        {done && (
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-accent-green/10 text-accent-green">
            RC 0
          </span>
        )}
        {running && (
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-accent-cyan/10 text-accent-cyan flex items-center gap-1">
            <Activity size={9} /> RC …
          </span>
        )}
        {done && stage.elapsed != null && (
          <p className="text-[9px] text-slate-400 font-mono mt-0.5">{stage.elapsed}s</p>
        )}
      </div>
    </motion.div>
  );
}

function KanbanColumn({ title, tone, stages, icon: Icon }) {
  return (
    <div className="flex flex-col min-w-0">
      <div className="flex items-center gap-2 mb-3">
        <Icon size={14} className={tone.text} />
        <h4 className="text-xs font-semibold text-slate-600 uppercase tracking-wider">{title}</h4>
        <span className={`ml-auto text-[10px] font-mono px-2 py-0.5 rounded-full ${tone.badge}`}>
          {stages.length}
        </span>
      </div>
      <div className="space-y-2.5 flex-1">
        <AnimatePresence>
          {stages.map((s) => <KanbanCard key={s.key} stage={s} />)}
        </AnimatePresence>
        {stages.length === 0 && (
          <div className="rounded-xl border border-dashed border-slate-200 py-6 text-center">
            <p className="text-[11px] text-slate-300">None</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default function ProjectTracker() {
  const [stages, setStages] = useState(fallbackSnapshot);
  const [source, setSource] = useState(DEFAULT_SOURCE);
  const [target, setTarget] = useState(DEFAULT_TARGET);
  const [live, setLive] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await apiFetch('/api/spine/progress');
        if (!r.ok) return;
        const data = await r.json();
        if (cancelled || !data) return;
        const c = data.connectivity;
        if (c?.source) setSource((s) => ({ ...s, ...c.source }));
        if (c?.target) setTarget((t) => ({ ...t, ...c.target }));
        setLive(true);
      } catch {
        /* keep fallback snapshot */
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const completed = useMemo(() => stages.filter((s) => s.status === 'completed'), [stages]);
  const running = useMemo(() => stages.filter((s) => s.status === 'running'), [stages]);
  const queued = useMemo(() => stages.filter((s) => s.status === 'queued'), [stages]);
  const pct = Math.round((completed.length / stages.length) * 100);

  return (
    <section className="space-y-5">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold text-slate-700 flex items-center gap-2">
          <Gauge size={18} className="text-accent-blue" /> Project Tracker
        </h2>
        <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full flex items-center gap-1
          ${live ? 'bg-accent-green/10 text-accent-green' : 'bg-slate-100 text-slate-400'}`}>
          <Wifi size={10} /> {live ? 'Live' : 'Snapshot'}
        </span>
        <div className="h-px flex-1 bg-gradient-to-r from-accent-blue/30 to-transparent" />
      </div>

      {/* Start / End connectivity boards */}
      <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_1fr] items-center gap-4">
        <ConnectivityBoard board={source} label="Start · Source" online={live} />
        <div className="hidden md:flex flex-col items-center text-slate-300">
          <ArrowRight size={22} />
          <span className="text-[9px] font-mono mt-1 text-slate-400">migrate</span>
        </div>
        <ConnectivityBoard board={target} label="End · Target" online={live} />
      </div>

      {/* Overall progress pipeline */}
      <div className="glass rounded-2xl p-5">
        <div className="flex items-center justify-between mb-2.5">
          <span className="text-xs font-medium text-slate-500 flex items-center gap-1.5">
            <ShieldCheck size={13} className="text-accent-blue" /> End-to-End Migration Progress
          </span>
          <span className="text-xs font-mono text-slate-500">
            {completed.length}/{stages.length} stages · {pct}%
          </span>
        </div>
        <div className="h-2.5 rounded-full bg-slate-100 overflow-hidden">
          <motion.div
            className="h-full rounded-full bg-gradient-to-r from-indigo-500 via-accent-blue to-accent-green"
            animate={{ width: `${pct}%` }}
            transition={{ duration: 0.6, ease: [0.4, 0, 0.2, 1] }}
          />
        </div>
      </div>

      {/* Kanban */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <KanbanColumn title="Completed" icon={CheckCircle2} stages={completed}
          tone={{ text: 'text-accent-green', badge: 'bg-accent-green/10 text-accent-green' }} />
        <KanbanColumn title="In-Progress" icon={Loader2} stages={running}
          tone={{ text: 'text-accent-cyan', badge: 'bg-accent-cyan/10 text-accent-cyan' }} />
        <KanbanColumn title="Queued" icon={Clock3} stages={queued}
          tone={{ text: 'text-slate-400', badge: 'bg-slate-100 text-slate-400' }} />
      </div>
    </section>
  );
}
