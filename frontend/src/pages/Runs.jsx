import { useCallback, useMemo, useState } from 'react';
import { FileText, Download, X, Award, CheckCircle2, AlertTriangle, ExternalLink } from 'lucide-react';
import { api, authUrl } from '../lib/api';
import { useApi } from '../lib/useApi';
import {
  Panel, PageHeader, StatusPill, MetricTile, Spinner, EmptyState, OfflineBanner, CmdLine, KVList, SearchBox, Sparkline,
} from '../components/dd';

const fmtDate = (s) => {
  try { return new Date(s).toLocaleString(); } catch { return s; }
};

function headline(results) {
  if (!results || typeof results !== 'object') return null;
  const sc = results.go_live_scorecard || results.validation_scorecard?.scorecard;
  const ex = results.executive_summary;
  return { grade: sc?.grade, score: sc?.score, recommendation: ex?.recommendation || sc?.recommendation, target: ex?.target_system };
}

function statusTone(status) {
  const s = String(status || '').toLowerCase();
  if (s === 'success' || s === 'succeeded' || s === 'completed' || s === 'ok') return 'ok';
  if (s === 'running' || s === 'in_progress') return 'info';
  if (s === 'failed' || s === 'error')        return 'err';
  return 'muted';
}

function RunDetailDrawer({ runId, onClose }) {
  const { data, error, loading } = useApi(useCallback(() => api.run(runId), [runId]), { deps: [runId] });
  const [downloading, setDownloading] = useState(false);

  const openPdf = async () => {
    setDownloading(true);
    try { window.open(await authUrl(`/api/runs/${runId}/pdf`), '_blank'); } finally { setDownloading(false); }
  };

  const h = headline(data);
  return (
    <div className="fixed inset-0 z-40 flex">
      <div className="flex-1 bg-black/30 backdrop-blur-sm" onClick={onClose} />
      <div className="w-[640px] max-w-[92vw] flex flex-col" style={{ background: 'var(--surface)', borderLeft: '1px solid var(--border)', boxShadow: 'var(--shadow-popup)' }}>
        <div className="flex items-center gap-2 px-5 py-3 border-b" style={{ borderColor: 'var(--border)' }}>
          <FileText size={14} className="text-accent" />
          <div className="flex-1 min-w-0">
            <div className="font-mono text-[12.5px] text-ink-1 truncate">{runId}</div>
            <div className="text-[10.5px] text-ink-3">Run detail</div>
          </div>
          <button onClick={openPdf} disabled={downloading} className="btn btn-sm btn-primary">
            {downloading ? <Spinner size={12} /> : <Download size={12} />} PDF
          </button>
          <button onClick={onClose} className="btn btn-sm btn-ghost btn-icon"><X size={13} /></button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {loading && <div className="flex items-center gap-2 text-xs text-ink-3 py-12 justify-center"><Spinner /> Loading run…</div>}
          {error && <div className="text-xs" style={{ color: 'var(--err)' }}>{error.message}</div>}
          {data && (
            <>
              {h && (h.grade || h.recommendation) && (
                <div className="grid grid-cols-2 gap-3">
                  {h.grade && (
                    <Panel title="Grade" icon={Award}>
                      <div className="metric-num" style={{ color: 'var(--ok)' }}>{h.grade}<span className="text-sm text-ink-4 font-medium ml-1">{h.score || ''}</span></div>
                    </Panel>
                  )}
                  {h.target && (
                    <Panel title="Target system" icon={CheckCircle2}>
                      <div className="text-[13px] font-semibold text-ink-1 mt-1">{h.target}</div>
                    </Panel>
                  )}
                  {h.recommendation && (
                    <div className="col-span-2">
                      <Panel title="Recommendation" icon={CheckCircle2}>
                        <p className="text-[12.5px] text-ink-2 leading-relaxed">{h.recommendation}</p>
                      </Panel>
                    </div>
                  )}
                </div>
              )}

              <Panel title="Final report payload" subtitle="final-report.json" flush>
                <pre className="code-block max-h-[420px] overflow-auto text-[11px] leading-relaxed m-0" style={{ borderRadius: 0 }}>
{JSON.stringify(data, null, 2)}
                </pre>
              </Panel>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function Runs() {
  const { data, error, loading, reload } = useApi(useCallback(() => api.runs(), []));
  const [selected, setSelected] = useState(null);
  const [filter, setFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');

  const runs = Array.isArray(data) ? data : [];
  const filtered = useMemo(() => {
    const q = filter.toLowerCase();
    return runs.filter((r) => {
      if (statusFilter !== 'all' && statusTone(r.status) !== statusFilter) return false;
      if (!q) return true;
      const idStr = (r.id || r.run_id || '').toString().toLowerCase();
      return idStr.includes(q);
    });
  }, [runs, filter, statusFilter]);

  const stats = useMemo(() => {
    const total = runs.length;
    const ok = runs.filter((r) => statusTone(r.status) === 'ok').length;
    const err = runs.filter((r) => statusTone(r.status) === 'err').length;
    const dqs = runs.filter((r) => r?.data_quality?.dead_letter_pct != null);
    const avgDq = dqs.length ? (dqs.reduce((a, r) => a + Number(r.data_quality.dead_letter_pct), 0) / dqs.length) : null;
    return { total, ok, err, avgDq };
  }, [runs]);

  if (loading) return <div className="flex items-center gap-2 text-xs text-ink-3 py-20 justify-center"><Spinner /> Loading runs…</div>;
  if (error) {
    return (
      <div className="space-y-4">
        <PageHeader title="Runs" breadcrumb={['Migrate4HANA', 'Runs']} subtitle="Pipeline executions and their reports." />
        <OfflineBanner onRetry={reload} />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Runs"
        breadcrumb={['Migrate4HANA', 'Runs']}
        subtitle={`${runs.length} execution${runs.length === 1 ? '' : 's'} on disk · click a row for detail`}
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <MetricTile label="Total runs" value={stats.total} sub="on disk" />
        <MetricTile label="Succeeded" value={stats.ok} sub={stats.total ? `${Math.round(stats.ok / stats.total * 100)}%` : ''} tone="ok" />
        <MetricTile label="Failed" value={stats.err} sub={stats.total ? `${Math.round(stats.err / stats.total * 100)}%` : ''} tone={stats.err > 0 ? 'err' : null} />
        <MetricTile label="Avg dead-letter %" value={stats.avgDq != null ? stats.avgDq.toFixed(2) : '—'} unit={stats.avgDq != null ? '%' : ''} sub="across runs reporting DQ" />
      </div>

      <Panel
        title="Run history"
        actions={
          <>
            <div className="inline-flex items-center gap-0.5">
              {['all', 'ok', 'info', 'err'].map((f) => (
                <button key={f} onClick={() => setStatusFilter(f)} className={`btn btn-sm ${statusFilter === f ? 'btn-primary' : 'btn-ghost'}`}>
                  {f === 'all' ? 'All' : f === 'ok' ? 'Succeeded' : f === 'info' ? 'Running' : 'Failed'}
                </button>
              ))}
            </div>
            <SearchBox value={filter} onChange={setFilter} placeholder="Filter run id…" />
          </>
        }
        flush
      >
        {filtered.length === 0 ? (
          <EmptyState
            icon={FileText}
            title="No runs match"
            hint="Adjust the filter or trigger a new run."
            action={<div className="w-[420px]"><CmdLine cmd="python run_local_lift_and_shift.py --run-id RUN-001" /></div>}
          />
        ) : (
          <table className="dt">
            <thead>
              <tr>
                <th>Run ID</th>
                <th>Status</th>
                <th>Created</th>
                <th>DQ %</th>
                <th>Stages</th>
                <th>Spark</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => {
                const id = r.id || r.run_id;
                const dq = r?.data_quality?.dead_letter_pct;
                // Synthesize a tiny sparkline from stage durations if present
                const spark = Array.isArray(r.stage_durations) && r.stage_durations.length > 1 ? r.stage_durations : null;
                return (
                  <tr key={id} className="cursor-pointer" onClick={() => setSelected(id)}>
                    <td className="font-mono text-[11.5px] text-ink-1 truncate max-w-[260px]">{id}</td>
                    <td><StatusPill tone={statusTone(r.status)}>{r.status || (r.has_execution ? 'executed' : 'assessment')}</StatusPill></td>
                    <td className="text-ink-3 tabular-nums">{r.created_at ? fmtDate(r.created_at) : '—'}</td>
                    <td className="tabular-nums">
                      {dq == null ? '—' : (
                        <span style={{ color: dq > (r.data_quality?.threshold_pct ?? 5) ? 'var(--warn)' : 'var(--ink-2)' }}>{Number(dq).toFixed(1)}%</span>
                      )}
                    </td>
                    <td className="tabular-nums text-ink-2">{r.stage_count ?? r.stages ?? '—'}</td>
                    <td>{spark ? <Sparkline values={spark} /> : <span className="text-ink-5 text-xs">—</span>}</td>
                    <td><button className="btn btn-sm btn-ghost btn-icon" onClick={(e) => { e.stopPropagation(); setSelected(id); }} title="Open detail"><ExternalLink size={12} /></button></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Panel>

      {selected && <RunDetailDrawer runId={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
