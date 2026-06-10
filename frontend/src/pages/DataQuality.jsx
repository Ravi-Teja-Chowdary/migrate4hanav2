import { useCallback, useMemo, useState } from 'react';
import { Link, useOutletContext } from 'react-router-dom';
import { Activity, AlertTriangle, ArrowRight, CheckCircle2, Download, Eye } from 'lucide-react';
import { api, downloadFile, openInTab } from '../lib/api';
import { useApi } from '../lib/useApi';
import { useToast } from '../lib/toast.jsx';
import { Panel, MetricTile, TimeSeriesChart, StatusPill, PageHeader, Spinner, EmptyState, KVList } from '../components/dd';

// Data Quality dashboard — surfaces the dead-letter SLO gate shipped 2026-06-10.
// Pulls data_quality blocks from each run and renders trend + per-object breakdown.
export default function DataQuality() {
  const toast = useToast();
  const [pdfBusy, setPdfBusy] = useState(null);
  const runs = useApi(useCallback(() => api.runs(), []), { pollMs: 15000 });
  const latest = Array.isArray(runs.data) && runs.data.length > 0 ? runs.data[0] : null;
  const latestId = latest?.id || latest?.run_id;
  const dq = latest?.data_quality;
  const series = useMemo(() => buildDqSeries(runs.data), [runs.data]);

  const threshold = dq?.threshold_pct ?? 5.0;
  const pct = dq?.dead_letter_pct ?? null;
  const breach = dq?.slo_breach ?? false;
  const gateDisabled = dq?.gate_disabled ?? false;

  const dlPdf = async () => {
    if (!latestId) return;
    setPdfBusy('download');
    const tId = toast.loading('Generating PDF…', latestId);
    try {
      await downloadFile(`/api/runs/${latestId}/pdf`, `migration-report-${latestId}.pdf`);
      toast.dismiss(tId); toast.success('PDF downloaded', latestId);
    } catch (e) { toast.dismiss(tId); toast.error('Download failed', e.message); }
    finally { setPdfBusy(null); }
  };
  const prevPdf = async () => {
    if (!latestId) return;
    setPdfBusy('preview');
    try { await openInTab(`/api/runs/${latestId}/pdf`); toast.info('Opening PDF', latestId); }
    catch (e) { toast.error('Preview failed', e.message); }
    finally { setPdfBusy(null); }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Data Quality"
        breadcrumb={['Migrate4HANA', 'Data Quality']}
        subtitle="Dirty-data SLO gate trends. Shipped 2026-06-10. Gate halts pipeline at ManualGate_DataQuality when dead-letter % exceeds threshold."
        actions={
          <>
            {latestId && (
              <>
                <button onClick={prevPdf} disabled={!!pdfBusy} className="btn btn-sm">
                  {pdfBusy === 'preview' ? <Spinner size={12} /> : <Eye size={12} />} Preview PDF
                </button>
                <button onClick={dlPdf} disabled={!!pdfBusy} className="btn btn-sm btn-primary">
                  {pdfBusy === 'download' ? <Spinner size={12} /> : <Download size={12} />} Download PDF
                </button>
              </>
            )}
            <Link to="/gates" className="btn btn-sm">Open gates queue <ArrowRight size={12} /></Link>
          </>
        }
      />

      {runs.loading && !runs.data && (
        <div className="flex items-center gap-2 text-xs text-ink-3 py-4"><Spinner /> Loading runs…</div>
      )}

      {runs.data && (
        <>
          {/* ── Top metric row ────────────────────────────────── */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <MetricTile
              label="Latest dead-letter rate"
              value={pct == null ? '—' : pct.toFixed(2)}
              unit={pct == null ? '' : '%'}
              sub={latest ? `run ${String(latest.run_id).slice(0, 18)}…` : 'no runs yet'}
              tone={breach ? 'warn' : pct != null ? 'ok' : null}
            />
            <MetricTile
              label="SLO threshold"
              value={threshold}
              unit="%"
              sub={gateDisabled ? 'gate disabled' : 'set via M4H_DEAD_LETTER_THRESHOLD_PCT'}
              tone={gateDisabled ? 'warn' : null}
            />
            <MetricTile
              label="Total attempted"
              value={dq?.total_attempted ?? '—'}
              sub={dq ? `${dq.total_dead_letter ?? 0} dead-letter` : ''}
            />
            <MetricTile
              label="Gate state"
              value={breach ? 'BREACH' : gateDisabled ? 'DISABLED' : 'OK'}
              sub={breach ? 'pipeline would halt' : gateDisabled ? 'dirt flows unblocked' : 'within SLO'}
              tone={breach ? 'warn' : gateDisabled ? 'warn' : 'ok'}
            />
          </div>

          {/* ── Trend chart ───────────────────────────────────── */}
          <Panel
            title="Dead-letter % trend"
            subtitle="across recent runs"
            icon={AlertTriangle}
            actions={<StatusPill tone={breach ? 'warn' : 'ok'} dot={false}>{series.length} runs</StatusPill>}
          >
            {series.length < 2 ? (
              <EmptyState icon={Activity} title="Not enough data yet"
                hint="The trend chart needs at least 2 runs with a data_quality block. Trigger a run from the Pipeline page." />
            ) : (
              <TimeSeriesChart
                series={series}
                unit="%"
                tone={breach ? 'warn' : 'accent'}
                threshold={threshold}
                thresholdLabel={`${threshold}% SLO`}
                height={220}
              />
            )}
          </Panel>

          {/* ── Latest-run breakdown ──────────────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            <Panel title="Latest run data-quality block" subtitle={latest?.run_id} className="lg:col-span-2">
              {dq ? (
                <KVList
                  cols={3}
                  items={[
                    { label: 'total_attempted',   value: dq.total_attempted ?? '—' },
                    { label: 'total_dead_letter', value: dq.total_dead_letter ?? '—' },
                    { label: 'dead_letter_pct',   value: dq.dead_letter_pct != null ? `${dq.dead_letter_pct}%` : '—' },
                    { label: 'threshold_pct',     value: `${dq.threshold_pct ?? threshold}%` },
                    { label: 'slo_breach',        value: String(dq.slo_breach ?? false) },
                    { label: 'gate_disabled',     value: String(dq.gate_disabled ?? false) },
                  ]}
                />
              ) : (
                <EmptyState icon={CheckCircle2} title="No data_quality block yet"
                  hint="The latest run did not emit a data_quality block. Older runs predate the SLO gate (shipped 2026-06-10)." />
              )}
            </Panel>

            <Panel title="How the gate works" icon={Activity}>
              <div className="text-[12px] text-ink-2 space-y-2.5 leading-relaxed">
                <p>The data-migrator rolls up <code className="text-accent">total_attempted</code>, <code className="text-accent">total_dead_letter</code>, and <code className="text-accent">dead_letter_pct</code> from per-object load results (plus CVI conflicts).</p>
                <p>If <code className="text-accent">dead_letter_pct &gt; threshold</code>, <code className="text-accent">slo_breach</code> = true and the SFN halts at <code className="text-accent">ManualGate_DataQuality</code>.</p>
                <p>A steward then either accepts the dirt (<code className="text-accent">SendTaskSuccess</code>) or cleanses upstream and re-runs.</p>
                <p>Set <code className="text-accent">M4H_DEAD_LETTER_THRESHOLD_PCT=0</code> to disable the gate (lets dirt flow through unblocked).</p>
              </div>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}

function buildDqSeries(runs) {
  if (!Array.isArray(runs)) return [];
  return runs
    .filter((r) => r?.data_quality?.dead_letter_pct != null && r?.created_at)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
    .map((r) => ({
      ts: typeof r.created_at === 'string' ? r.created_at.slice(5, 16) : '',
      value: Number(r.data_quality.dead_letter_pct),
    }));
}
