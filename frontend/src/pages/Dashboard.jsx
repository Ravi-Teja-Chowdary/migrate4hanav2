import { useCallback, useMemo } from 'react';
import { useState } from 'react';
import { Link, useOutletContext } from 'react-router-dom';
import {
  Activity, ShieldCheck, FileText, Server, AlertTriangle, Clock, CheckCircle2,
  ArrowRight, Zap, Database, Download, Eye,
} from 'lucide-react';
import { api, downloadFile, openInTab } from '../lib/api';
import { useApi } from '../lib/useApi';
import { useToast } from '../lib/toast.jsx';
import {
  Panel, MetricTile, Sparkline, TimeSeriesChart, Gantt, StatusPill,
  PageHeader, Spinner, OfflineBanner, KVList, EmptyState,
} from '../components/dd';

// Generate a fake-but-not-misleading short sparkline from a single number when
// no real time-series exists — used purely as visual continuity. Honest UIs
// don't pretend they have data they don't; here we only show the sparkline
// when there's at least 2 real data points.
function spineToSpark(spine) {
  const obj = spine?.objects;
  if (!Array.isArray(obj) || obj.length < 2) return null;
  return obj.map((o) => o.percent_complete ?? 0);
}

export default function Dashboard() {
  const toast = useToast();
  const { triggerRefresh } = useOutletContext() || {};
  const [pdfBusy, setPdfBusy] = useState(null); // 'download' | 'preview' | null
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
  const spineSpark = useMemo(() => spineToSpark(spine.data), [spine.data]);

  // Latest dirty-data SLO from the most recent run (if any)
  const latestRun = Array.isArray(runs.data) && runs.data.length > 0 ? runs.data[0] : null;
  const latestRunId = latestRun?.id || latestRun?.run_id;
  const dqPct = latestRun?.data_quality?.dead_letter_pct ?? null;
  const dqThreshold = latestRun?.data_quality?.threshold_pct ?? 5.0;
  const dqBreach = dqPct != null && dqPct > dqThreshold;

  const downloadLatestPdf = async () => {
    if (!latestRunId) return;
    setPdfBusy('download');
    const tId = toast.loading('Generating PDF…', latestRunId);
    try {
      await downloadFile(`/api/runs/${latestRunId}/pdf`, `migration-report-${latestRunId}.pdf`);
      toast.dismiss(tId);
      toast.success('PDF downloaded', `migration-report-${latestRunId}.pdf`);
    } catch (e) { toast.dismiss(tId); toast.error('Download failed', e.message); }
    finally { setPdfBusy(null); }
  };
  const previewLatestPdf = async () => {
    if (!latestRunId) return;
    setPdfBusy('preview');
    try {
      await openInTab(`/api/runs/${latestRunId}/pdf`);
      toast.info('Opening PDF', latestRunId);
    } catch (e) { toast.error('Preview failed', e.message); }
    finally { setPdfBusy(null); }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Overview"
        breadcrumb={['Migrate4HANA', 'Overview']}
        subtitle="Live observability for the ECC → S/4HANA migration pipeline."
        actions={
          <>
            {latestRunId && (
              <>
                <button onClick={previewLatestPdf} disabled={!!pdfBusy} className="btn btn-sm">
                  {pdfBusy === 'preview' ? <Spinner size={12} /> : <Eye size={12} />} Preview latest PDF
                </button>
                <button onClick={downloadLatestPdf} disabled={!!pdfBusy} className="btn btn-sm btn-primary">
                  {pdfBusy === 'download' ? <Spinner size={12} /> : <Download size={12} />} Download latest PDF
                </button>
              </>
            )}
            <Link to="/commands" className="btn btn-sm"><span>Commands</span></Link>
            <Link to="/pipeline" className="btn btn-sm btn-primary"><Zap size={12} /><span>Run pipeline</span></Link>
          </>
        }
      />

      {checking && (
        <div className="flex items-center gap-2 text-xs text-ink-3 py-4"><Spinner /> Checking backend…</div>
      )}

      {!checking && !online && <OfflineBanner onRetry={health.reload} />}

      {online && (
        <>
          {/* ── Metric row ──────────────────────────────────────── */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <MetricTile
              label="Pipeline runs"
              value={runCount}
              sub="total on disk"
            />
            <MetricTile
              label="Active gates"
              value={pendingGates}
              sub={pendingGates ? 'awaiting decision' : 'none pending'}
              tone={pendingGates > 0 ? 'warn' : null}
            />
            <MetricTile
              label="Dead-letter rate"
              value={dqPct == null ? '—' : `${dqPct.toFixed(1)}`}
              unit={dqPct == null ? '' : '%'}
              sub={dqPct == null ? 'no recent run' : `SLO ${dqThreshold}%${dqBreach ? ' · breach' : ''}`}
              tone={dqBreach ? 'warn' : dqPct != null ? 'ok' : null}
            />
            <MetricTile
              label="Spine progress"
              value={spine.data?.percent_complete != null ? `${spine.data.percent_complete}` : '—'}
              unit={spine.data?.percent_complete != null ? '%' : ''}
              sub={spine.data ? `${spine.data.objects?.length ?? 0} objects` : 'no spine running'}
              spark={spineSpark}
              tone={spine.data?.percent_complete === 100 ? 'ok' : null}
            />
          </div>

          {/* ── Active gates + current run ─────────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            <Panel
              title="Active gates"
              icon={ShieldCheck}
              actions={<Link to="/gates" className="btn btn-sm btn-ghost"><ArrowRight size={12} /></Link>}
              flush
              className="lg:col-span-2"
            >
              {pendingGates === 0 ? (
                <EmptyState icon={CheckCircle2} title="No gates pending" hint="The pipeline is either idle, succeeded, or hasn't reached a manual gate." />
              ) : (
                <table className="dt">
                  <thead><tr><th>Gate</th><th>Run</th><th>Status</th><th>Waiting</th><th></th></tr></thead>
                  <tbody>
                    {gates.data.gates.slice(0, 5).map((g) => (
                      <tr key={g.id}>
                        <td className="font-medium text-ink-1">{g.name || g.gate}</td>
                        <td className="font-mono text-[11.5px] text-ink-3 truncate max-w-[200px]">{g.run_id}</td>
                        <td><StatusPill tone="warn">awaiting</StatusPill></td>
                        <td className="text-ink-3 tabular-nums">{g.waiting_for || '—'}</td>
                        <td><Link to="/gates" className="btn btn-sm btn-ghost">open</Link></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Panel>

            <Panel title="Current run" icon={Activity}>
              <StatusPill tone={runStatus === 'running' ? 'info' : runStatus === 'completed' ? 'ok' : runStatus === 'failed' ? 'err' : 'muted'}>
                {runStatus}
              </StatusPill>
              {status.data?.run_id ? (
                <div className="mt-3">
                  <div className="text-[10.5px] uppercase tracking-wider text-ink-4 font-semibold">Run ID</div>
                  <div className="font-mono text-[12px] text-ink-1 mt-0.5 truncate">{status.data.run_id}</div>
                  {status.data.mode && (
                    <>
                      <div className="text-[10.5px] uppercase tracking-wider text-ink-4 font-semibold mt-2.5">Mode</div>
                      <div className="text-[12.5px] text-ink-1 mt-0.5">{status.data.mode}</div>
                    </>
                  )}
                </div>
              ) : (
                <p className="text-xs text-ink-3 mt-3">No active run. Start one from the Pipeline page.</p>
              )}
              <Link to="/pipeline" className="btn btn-sm w-full mt-4 justify-center">
                Open pipeline <ArrowRight size={12} />
              </Link>
            </Panel>
          </div>

          {/* ── Dirty-data SLO chart + latest run summary ──────── */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            <Panel
              title="Dirty-data SLO"
              subtitle="dead-letter rate vs threshold"
              icon={AlertTriangle}
              actions={<Link to="/data-quality" className="btn btn-sm btn-ghost"><ArrowRight size={12} /></Link>}
              className="lg:col-span-2"
            >
              {(() => {
                const series = buildDqSeries(runs.data);
                if (series.length < 2) {
                  return <EmptyState icon={Activity} title="Not enough runs yet" hint="The SLO trend appears once 2+ runs report a dead-letter rate." />;
                }
                return <TimeSeriesChart series={series} unit="%" tone={dqBreach ? 'warn' : 'accent'} threshold={dqThreshold} thresholdLabel={`${dqThreshold}% SLO`} height={200} />;
              })()}
            </Panel>

            <Panel title="Latest run" icon={FileText} actions={<Link to="/runs" className="btn btn-sm btn-ghost"><ArrowRight size={12} /></Link>}>
              {latestRun ? (
                <>
                  <div className="font-mono text-[11.5px] text-ink-2 mb-2 truncate">{latestRun.run_id}</div>
                  <StatusPill tone={latestRun.status === 'success' || latestRun.status === 'succeeded' ? 'ok' : latestRun.status === 'running' ? 'info' : latestRun.status === 'failed' ? 'err' : 'muted'}>
                    {latestRun.status || 'unknown'}
                  </StatusPill>
                  <div className="mt-4">
                    <KVList
                      cols={2}
                      items={[
                        { label: 'Stages',     value: latestRun.stage_count ?? latestRun.stages ?? '—' },
                        { label: 'Gates',      value: latestRun.gate_count ?? '—' },
                        { label: 'Created',    value: latestRun.created_in_s4 ?? '—' },
                        { label: 'Dead-letter', value: latestRun.data_quality?.total_dead_letter ?? '—' },
                      ]}
                    />
                  </div>
                  <div className="mt-4 grid grid-cols-2 gap-2">
                    <button onClick={previewLatestPdf} disabled={!!pdfBusy} className="btn btn-sm justify-center">
                      {pdfBusy === 'preview' ? <Spinner size={12} /> : <Eye size={12} />} Preview
                    </button>
                    <button onClick={downloadLatestPdf} disabled={!!pdfBusy} className="btn btn-sm btn-primary justify-center">
                      {pdfBusy === 'download' ? <Spinner size={12} /> : <Download size={12} />} PDF
                    </button>
                  </div>
                  <Link to="/runs" className="btn btn-sm w-full mt-2 justify-center">View all runs <ArrowRight size={12} /></Link>
                </>
              ) : (
                <EmptyState icon={FileText} title="No runs yet" hint="Trigger a run from the Pipeline page or via the Command Center." />
              )}
            </Panel>
          </div>

          {/* ── ECC connection chip ─────────────────────────────── */}
          <Panel title="Source ECC" icon={Server} subtitle={ecc.data?.host ? `${ecc.data.host}:${ecc.data.sysnr || '00'} · client ${ecc.data.client || '?'}` : 'not configured'}>
            <div className="flex items-center gap-3">
              <StatusPill tone={ecc.data?.live_ready ? 'ok' : ecc.data?.has_connection ? 'warn' : 'muted'}>
                {ecc.data?.live_ready ? 'live-ready' : ecc.data?.has_connection ? 'saved' : 'not set'}
              </StatusPill>
              <div className="divider-v h-4" />
              <span className="text-xs text-ink-3">{ecc.data?.has_password ? 'session active' : 'no live session'}</span>
              <Link to="/connections" className="btn btn-sm btn-ghost ml-auto">Configure <ArrowRight size={12} /></Link>
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}

// Build a time-series of dead-letter % across runs (oldest → newest).
// Honest: only includes runs that actually have a data_quality block.
function buildDqSeries(runs) {
  if (!Array.isArray(runs)) return [];
  const withDq = runs
    .filter((r) => r?.data_quality?.dead_letter_pct != null && r?.created_at)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
  return withDq.map((r) => ({
    ts: typeof r.created_at === 'string' ? r.created_at.slice(5, 16) : '',
    value: Number(r.data_quality.dead_letter_pct),
  }));
}
