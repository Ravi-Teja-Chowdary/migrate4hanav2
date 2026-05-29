import { useCallback } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  Rocket, TerminalSquare, Server, FileText, ShieldCheck, Activity,
  GitBranch, KanbanSquare, ArrowRight, Wifi, Gauge,
} from 'lucide-react';
import { api } from '../lib/api';
import { useApi } from '../lib/useApi';
import { Card, PageHeader, Stat, Badge, ProgressBar, OfflineBanner, CommandBlock, Spinner, ACCENT } from '../components/ui';

function QuickLink({ to, icon: Icon, title, desc, accent = 'indigo' }) {
  const a = ACCENT[accent] || ACCENT.indigo;
  return (
    <Link to={to} className="focusable block">
      <Card hover className="p-5 h-full">
        <div className="flex items-center gap-3">
          <div className={`w-10 h-10 rounded-2xl ${a.bg} flex items-center justify-center`}>
            <Icon size={18} className={a.text} />
          </div>
          <div className="min-w-0">
            <p className="text-[14px] font-semibold text-ink-900">{title}</p>
            <p className="text-xs text-ink-400 truncate">{desc}</p>
          </div>
          <ArrowRight size={16} className="ml-auto text-ink-300" />
        </div>
      </Card>
    </Link>
  );
}

export default function Dashboard() {
  const health = useApi(useCallback(() => api.health(), []), { pollMs: 10000 });
  const ecc = useApi(useCallback(() => api.eccStatus(), []));
  const status = useApi(useCallback(() => api.status(), []), { pollMs: 5000 });
  const gates = useApi(useCallback(() => api.gates(), []), { pollMs: 10000 });
  const runs = useApi(useCallback(() => api.runs(), []));
  const spine = useApi(useCallback(() => api.spineProgress(), []), { pollMs: 6000 });

  const online = !!health.data;
  const checking = health.loading;

  const runStatus = status.data?.status || 'idle';
  const pendingGates = gates.data?.gates?.length ?? 0;
  const runCount = Array.isArray(runs.data) ? runs.data.length : 0;

  return (
    <div className="space-y-7">
      <PageHeader
        title="Welcome to" accentWord="Migrate4HANA"
        subtitle="A support-clean ECC → S/4HANA migration spine. Everything here runs against the live backend — no mock data."
        actions={
          <div className="flex items-center gap-2">
            <Link to="/commands" className="focusable inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-slate-50 text-ink-700 text-[13px] font-semibold hover:bg-slate-100 transition">
              <TerminalSquare size={15} /> Commands
            </Link>
            <Link to="/pipeline" className="focusable btn-primary inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-[13px] font-bold">
              <Rocket size={15} /> Run Pipeline
            </Link>
          </div>
        }
      />

      {checking ? (
        <div className="flex items-center gap-2 text-ink-400 text-sm py-6"><Spinner /> Checking backend…</div>
      ) : !online ? (
        <>
          <OfflineBanner onRetry={health.reload} />
          <Card className="p-6">
            <p className="text-[13px] font-semibold text-ink-700 mb-3">Start everything in three commands</p>
            <div className="space-y-2">
              <CommandBlock cmd="python api_server.py" />
              <CommandBlock cmd="cd frontend && npm run dev" />
              <CommandBlock cmd="python pipeline_spine_master.py" />
            </div>
          </Card>
        </>
      ) : (
        <>
          {/* live stat tiles */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <Stat label="Backend" value="Online" sub={`v${health.data.version} · ${health.data.stages} stages`} icon={Wifi} accent="emerald" />
            <Stat label="Source ECC" value={ecc.data?.live_ready ? 'Live-ready' : ecc.data?.has_connection ? 'Saved' : 'Not set'} sub={ecc.data?.has_password ? 'session active' : 'no live session'} icon={Server} accent="indigo" />
            <Stat label="Runs on disk" value={runCount} sub="completed reports" icon={FileText} accent="violet" />
            <Stat label="Pending gates" value={pendingGates} sub="awaiting decision" icon={ShieldCheck} accent={pendingGates ? 'amber' : 'slate'} />
          </div>

          {/* current run + spine */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <Card className="p-6">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Activity size={16} className="text-indigo-600" />
                  <h3 className="text-[14px] font-semibold text-ink-900">Current Run</h3>
                </div>
                <Badge tone={runStatus === 'running' ? 'running' : runStatus === 'completed' ? 'ok' : runStatus === 'failed' ? 'failed' : 'pending'}>
                  {runStatus === 'running' && <Spinner size={11} />} {runStatus}
                </Badge>
              </div>
              {status.data?.run_id ? (
                <p className="text-xs font-mono text-ink-400">{status.data.run_id}{status.data.mode ? ` · ${status.data.mode}` : ''}</p>
              ) : (
                <p className="text-sm text-ink-400">No active run. Start one from the Pipeline page.</p>
              )}
              <Link to="/pipeline" className="focusable inline-flex items-center gap-1.5 text-[13px] font-semibold text-indigo-600 hover:text-indigo-700 mt-4">
                Open pipeline <ArrowRight size={14} />
              </Link>
            </Card>

            <Card className="p-6">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Gauge size={16} className="text-violet-600" />
                  <h3 className="text-[14px] font-semibold text-ink-900">Master Spine</h3>
                </div>
                {spine.data ? <Badge tone="ok">live</Badge> : <Badge tone="pending">no run</Badge>}
              </div>
              {spine.data ? (
                <>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-ink-500">{spine.data.connectivity?.source?.host} → {spine.data.connectivity?.target?.host}</span>
                    <span className="text-xs font-mono text-ink-400">{spine.data.percent_complete ?? 0}%</span>
                  </div>
                  <ProgressBar value={spine.data.percent_complete || 0} accent="violet" />
                </>
              ) : (
                <p className="text-sm text-ink-400">Run <span className="font-mono text-ink-600">pipeline_spine_master.py</span> to populate live spine progress.</p>
              )}
              <Link to="/tracker" className="focusable inline-flex items-center gap-1.5 text-[13px] font-semibold text-violet-600 hover:text-violet-700 mt-4">
                Open tracker <ArrowRight size={14} />
              </Link>
            </Card>
          </div>

          {/* quick links */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <QuickLink to="/tracker" icon={KanbanSquare} title="Project Tracker" desc="Live stage board" accent="violet" />
            <QuickLink to="/pipeline" icon={GitBranch} title="Pipeline" desc="28 stages + engines" accent="sky" />
            <QuickLink to="/connections" icon={Server} title="Connections" desc="ECC + S/4HANA" accent="indigo" />
            <QuickLink to="/runs" icon={FileText} title="Reports" desc="Run history + PDF" accent="emerald" />
          </div>
        </>
      )}
    </div>
  );
}
