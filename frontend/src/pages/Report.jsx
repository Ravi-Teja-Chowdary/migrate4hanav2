// Live Migration Report page.
//
// Renders the same 10 sections the PDF (pdf_report_generator.py) generates, but
// live — refreshing every 7s while the active run is in progress. Each section
// shows a "pending" pill until its source data lands in final-report.json (or
// any intermediate file under outputs/<run_id>/). PDF download CTA at the top.
import { useCallback, useMemo, useState } from 'react';
import {
  FileText, Download, Eye, RefreshCw, Activity, AlertTriangle, CheckCircle2,
  Layers, ShieldCheck, Code2, Database, Sliders, Users, Link2, Award, AlertOctagon, Map, Cpu,
} from 'lucide-react';
import { api, downloadFile, openInTab } from '../lib/api';
import { useApi } from '../lib/useApi';
import { useToast } from '../lib/toast.jsx';
import { useActiveRun } from '../lib/activeRun.jsx';
import {
  Panel, PageHeader, StatusPill, MetricTile, Spinner, EmptyState, OfflineBanner, KVList,
} from '../components/dd';

const SECTION_ICON = {
  executive:    Layers,
  code:         Code2,
  data:         Database,
  data_quality: Activity,
  config:       Sliders,
  auth:         Users,
  integrations: Link2,
  scorecard:    Award,
  risk:         AlertOctagon,
  roadmap:      Map,
  tech:         Cpu,
};

const num = (n) => (n == null ? '—' : Number(n).toLocaleString());
const pct = (n) => (n == null ? '—' : `${Number(n).toFixed(1)}%`);

// ──────────────────────────────────────────────────────────────
// Section renderers — kept inline so each one stays readable.
// They all accept (data) and return a React fragment.
// ──────────────────────────────────────────────────────────────
function RenderExecutive({ data }) {
  const ex  = data?.executive_summary || {};
  const ssa = data?.source_system_assessment || {};
  return (
    <KVList
      cols={2}
      items={[
        { label: 'Client',           value: ex.client || '—' },
        { label: 'Source system',    value: ex.source_system || '—' },
        { label: 'Target system',    value: ex.target_system || '—' },
        { label: 'Approach',         value: ex.migration_approach || '—' },
        { label: 'Custom programs',  value: num(ssa.total_custom_programs) },
        { label: 'Custom tables',    value: num(ssa.total_custom_tables) },
        { label: 'Function modules', value: num(ssa.function_modules) },
        { label: 'Company codes',    value: num(ssa.company_codes) },
        { label: 'Plants',           value: num(ssa.plants) },
        { label: 'Sales orgs',       value: num(ssa.sales_organizations) },
        { label: 'Users',            value: num(ssa.total_users) },
        { label: 'Roles',            value: num(ssa.total_roles) },
        { label: 'Blocking issues',  value: num(ssa.blocking_issues_identified) },
      ]}
    />
  );
}

function RenderCode({ data }) {
  const sum = data?.summary || {};
  const fb  = data?.fix_breakdown || {};
  return (
    <>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <MetricTile label="Issues detected"  value={num(sum.total_issues_detected)} />
        <MetricTile label="Auto-remediated"  value={num(sum.auto_remediated)} tone="ok" />
        <MetricTile label="Fixes applied"    value={num(sum.total_fixes_applied)} />
        <MetricTile label="Fix rate"         value={sum.fix_rate_percentage != null ? `${sum.fix_rate_percentage}` : '—'} unit="%" tone="ok" />
      </div>
      {Object.keys(fb).length > 0 && (
        <div className="mt-3">
          <div className="text-[11px] text-ink-3 uppercase tracking-wider font-semibold mb-1.5">Fix engines</div>
          <table className="dt">
            <thead><tr><th>Engine</th><th className="text-right">Fixes</th></tr></thead>
            <tbody>{Object.entries(fb).map(([k, v]) => (
              <tr key={k}><td>{k.replace(/_/g, ' ')}</td><td className="text-right tabular-nums">{num(v)}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {sum.remaining_manual_review > 0 && (
        <div className="mt-3 p-2.5 rounded-sm text-[11.5px]" style={{ background: 'var(--surface-2)', border: '1px solid var(--warn)', color: 'var(--ink-2)' }}>
          <strong>Manual review required:</strong> {sum.remaining_manual_review} items
        </div>
      )}
    </>
  );
}

function RenderData({ data }) {
  const fin = data?.finance || {};
  const bp  = data?.business_partner_conversion || {};
  const ct  = data?.custom_tables || {};
  const ddh = data?.dirty_data_handling || {};
  return (
    <div className="space-y-4">
      <div>
        <div className="text-[11px] text-ink-3 uppercase tracking-wider font-semibold mb-1.5">Financial (BKPF/BSEG → ACDOCA)</div>
        <KVList cols={2} items={[
          { label: 'Source docs (BKPF)',  value: num(fin.source_documents_bkpf) },
          { label: 'Source items (BSEG)', value: num(fin.source_line_items_bseg) },
          { label: 'Target ACDOCA',       value: num(fin.target_acdoca_records) },
          { label: 'Reconciliation',      value: fin.reconciliation || '—' },
        ]} />
      </div>
      <div>
        <div className="text-[11px] text-ink-3 uppercase tracking-wider font-semibold mb-1.5">Business Partner (KNA1/LFA1 → BUT000)</div>
        <KVList cols={2} items={[
          { label: 'Customers migrated',     value: num(bp.customers_migrated) },
          { label: 'Vendors migrated',       value: num(bp.vendors_migrated) },
          { label: 'BP created',             value: num(bp.business_partners_created) },
          { label: 'Duplicates merged',      value: num(bp.duplicates_merged) },
          { label: 'CVI sync',               value: bp.cvi_synchronization || '—' },
        ]} />
      </div>
      <div>
        <div className="text-[11px] text-ink-3 uppercase tracking-wider font-semibold mb-1.5">Custom tables</div>
        <KVList cols={2} items={[
          { label: 'Tables migrated', value: num(ct.tables_migrated) },
          { label: 'Rows transferred', value: num(ct.total_rows_transferred) },
        ]} />
      </div>
      {ddh && Object.keys(ddh).length > 0 && (
        <div>
          <div className="text-[11px] text-ink-3 uppercase tracking-wider font-semibold mb-1.5">
            Dirty-data handling
            <span className="ml-2 text-ink-4 normal-case">
              LOAD_TO_S4: {ddh.load_to_s4_enabled ? <strong style={{ color: 'var(--ok)' }}>ENABLED</strong> : <strong style={{ color: 'var(--warn)' }}>OFF (extract-only)</strong>}
            </span>
          </div>
          <table className="dt">
            <thead><tr><th>Outcome</th><th className="text-right">Count</th><th className="text-right">Rate</th></tr></thead>
            <tbody>
              <tr><td>Attempted</td><td className="text-right tabular-nums">{num(ddh.total_attempted)}</td><td className="text-right text-ink-4">—</td></tr>
              <tr><td>Created in S/4</td><td className="text-right tabular-nums">{num(ddh.total_created_in_s4)}</td><td className="text-right text-ink-3">{ddh.create_rate || 'n/a'}</td></tr>
              <tr><td>Matched existing (idempotency)</td><td className="text-right tabular-nums">{num(ddh.total_matched_existing)}</td><td className="text-right text-ink-3">{ddh.idempotency_hit_rate || 'n/a'}</td></tr>
              <tr><td>Dead-lettered</td><td className="text-right tabular-nums" style={{ color: 'var(--warn)' }}>{num(ddh.total_dead_lettered)}</td><td className="text-right" style={{ color: 'var(--warn)' }}>{ddh.dead_letter_rate || 'n/a'}</td></tr>
            </tbody>
          </table>
          {Array.isArray(ddh.dead_letter_classes) && ddh.dead_letter_classes.length > 0 && (
            <div className="mt-2 text-[11px] text-ink-3">
              <strong>Dead-letter classes:</strong> {ddh.dead_letter_classes.join(', ')}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function RenderDataQuality({ data }) {
  if (!data || Object.keys(data).length === 0) return <p className="text-[11.5px] text-ink-3">No DQ data yet.</p>;
  const breach = !!data.slo_breach;
  return (
    <>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <MetricTile label="Attempted" value={num(data.total_attempted)} />
        <MetricTile label="Dead-letter" value={num(data.total_dead_letter)} tone={breach ? 'err' : null} />
        <MetricTile label="DQ %"    value={data.dead_letter_pct != null ? Number(data.dead_letter_pct).toFixed(2) : '—'} unit="%" tone={breach ? 'err' : 'ok'} />
        <MetricTile label="Threshold" value={data.threshold_pct != null ? data.threshold_pct : '—'} unit="%" />
      </div>
      {breach && (
        <div className="mt-3 p-2.5 rounded-sm text-[11.5px] flex items-start gap-2" style={{ background: 'var(--surface-2)', border: '1px solid var(--err)', color: 'var(--ink-2)' }}>
          <AlertTriangle size={13} style={{ color: 'var(--err)' }} className="mt-0.5 shrink-0" />
          <div>
            <strong style={{ color: 'var(--err)' }}>SLO breach.</strong> The pipeline halted at <code>ManualGate_DataQuality</code> because dirty-data rate exceeded the threshold.
            Review the dead-letter ledger in the Gates page before approving.
          </div>
        </div>
      )}
    </>
  );
}

function RenderScorecard({ data }) {
  const sc = data?.scorecard || data || {};
  return (
    <KVList cols={2} items={[
      { label: 'Grade',          value: sc.grade || '—' },
      { label: 'Score',          value: sc.score != null ? sc.score : '—' },
      { label: 'Recommendation', value: sc.recommendation || '—' },
      { label: 'Confidence',     value: sc.confidence || '—' },
    ]} />
  );
}

function RenderConfig({ data }) {
  if (!data || Object.keys(data).length === 0) return <p className="text-[11.5px] text-ink-3">Configuration block empty.</p>;
  return (
    <>
      <div className="text-[12px] text-ink-2 mb-2">
        <strong>{data.checklist_items_applied ?? 0}</strong> configuration checklist items applied
      </div>
      <pre className="code-block max-h-[280px] overflow-auto text-[11px] leading-relaxed m-0">
{JSON.stringify(data, null, 2)}
      </pre>
    </>
  );
}

function RenderGeneric({ data }) {
  if (!data || (typeof data === 'object' && Object.keys(data).length === 0)) {
    return <p className="text-[11.5px] text-ink-3">No data for this section yet.</p>;
  }
  return (
    <pre className="code-block max-h-[280px] overflow-auto text-[11px] leading-relaxed m-0">
{JSON.stringify(data, null, 2)}
    </pre>
  );
}

const RENDERERS = {
  executive:    RenderExecutive,
  code:         RenderCode,
  data:         RenderData,
  data_quality: RenderDataQuality,
  scorecard:    RenderScorecard,
  config:       RenderConfig,
  // auth, integrations, risk, roadmap, tech all fall back to generic JSON.
};

// ──────────────────────────────────────────────────────────────
// Main page
// ──────────────────────────────────────────────────────────────
export default function Report() {
  const toast = useToast();
  const { activeRunId } = useActiveRun();
  const runId = activeRunId;

  const reportQ = useApi(useCallback(
    () => runId ? api.reportSections(runId) : Promise.resolve(null),
    [runId],
  ), { pollMs: runId ? 7000 : 0, deps: [runId] });

  const [pdfBusy, setPdfBusy] = useState(null);

  const downloadPdf = async () => {
    setPdfBusy('download');
    const tId = toast.loading('Generating PDF…', runId);
    try {
      await downloadFile(`/api/runs/${runId}/pdf`, `migration-report-${runId}.pdf`);
      toast.dismiss(tId);
      toast.success('PDF downloaded', `migration-report-${runId}.pdf`);
    } catch (e) {
      toast.dismiss(tId);
      toast.error('Download failed', e.message);
    } finally { setPdfBusy(null); }
  };
  const previewPdf = async () => {
    setPdfBusy('preview');
    try {
      await openInTab(`/api/runs/${runId}/pdf`);
      toast.info('Opening PDF in new tab', runId);
    } catch (e) {
      toast.error('Preview failed', e.message);
    } finally { setPdfBusy(null); }
  };

  if (!runId) {
    return (
      <div className="space-y-4">
        <PageHeader title="Migration Report" breadcrumb={['Migrate4HANA', 'Report']} subtitle="Live customer-facing report — same content as the PDF." />
        <Panel>
          <EmptyState
            icon={FileText}
            title="No active run"
            hint="Pick a run from the topbar selector, or start a new pipeline from the Pipeline page."
          />
        </Panel>
      </div>
    );
  }

  if (reportQ.error && !reportQ.data) {
    return (
      <div className="space-y-4">
        <PageHeader title="Migration Report" breadcrumb={['Migrate4HANA', 'Report']} subtitle={`run · ${runId}`} />
        <OfflineBanner onRetry={reportQ.reload} />
      </div>
    );
  }

  const report = reportQ.data;
  const sections = report?.sections || [];
  const inProgress = report?.status === 'in_progress';
  const readyN = report?.ready_sections ?? 0;
  const totalN = report?.total_sections ?? sections.length;
  const progressPct = totalN ? Math.round((readyN / totalN) * 100) : 0;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Migration Report"
        breadcrumb={['Migrate4HANA', 'Report']}
        subtitle={
          <>
            <span className="font-mono">{runId}</span>
            {' · '}
            <StatusPill tone={inProgress ? 'info' : 'ok'}>
              {inProgress ? 'in progress' : 'complete'} · {readyN}/{totalN} sections
            </StatusPill>
          </>
        }
        actions={
          <>
            <button onClick={() => reportQ.reload()} className="btn btn-sm" title="Refresh now">
              {reportQ.loading ? <Spinner size={11} /> : <RefreshCw size={11} />} Refresh
            </button>
            <button onClick={previewPdf} disabled={!!pdfBusy} className="btn btn-sm">
              {pdfBusy === 'preview' ? <Spinner size={11} /> : <Eye size={11} />} Preview PDF
            </button>
            <button onClick={downloadPdf} disabled={!!pdfBusy} className="btn btn-sm btn-primary">
              {pdfBusy === 'download' ? <Spinner size={11} /> : <Download size={11} />} Download PDF
            </button>
          </>
        }
      />

      {/* Progress strip */}
      <Panel>
        <div className="flex items-center gap-3">
          <div className="flex-1">
            <div className="flex items-center justify-between text-[11px] mb-1.5">
              <span className="text-ink-3 uppercase tracking-wider font-semibold">Report completion</span>
              <span className="tabular-nums text-ink-2 font-semibold">{progressPct}%</span>
            </div>
            <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--surface-2)' }}>
              <div className="h-full" style={{
                width: `${progressPct}%`,
                background: inProgress ? 'var(--info)' : 'var(--ok)',
                transition: 'width 0.6s ease',
              }} />
            </div>
            <div className="text-[10.5px] text-ink-4 mt-1.5">
              {inProgress
                ? 'Sections fill in as their data lands. Page auto-refreshes every ~7s.'
                : 'All sections ready. The PDF download above contains the same content.'}
            </div>
          </div>
        </div>
      </Panel>

      {/* Sections */}
      <div className="space-y-3">
        {sections.map((s) => {
          const Icon = SECTION_ICON[s.id] || FileText;
          const Renderer = RENDERERS[s.id] || RenderGeneric;
          return (
            <Panel
              key={s.id}
              title={s.title}
              icon={Icon}
              actions={
                <StatusPill tone={s.ready ? 'ok' : 'muted'}>
                  {s.ready ? 'ready' : 'pending'}
                </StatusPill>
              }
            >
              {s.ready
                ? <Renderer data={s.data} />
                : (
                  <div className="text-[11.5px] text-ink-3 flex items-center gap-2 py-2">
                    {inProgress ? <Spinner size={11} /> : null}
                    <span>This section will fill in once the pipeline writes its data.</span>
                  </div>
                )
              }
            </Panel>
          );
        })}
      </div>
    </div>
  );
}
