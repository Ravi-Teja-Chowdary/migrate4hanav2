import { useCallback, useState } from 'react';
import { FileText, Download, ChevronRight, FolderOpen, Award, CheckCircle2 } from 'lucide-react';
import { api, authUrl } from '../lib/api';
import { useApi } from '../lib/useApi';
import { Card, PageHeader, Badge, Spinner, EmptyState, OfflineBanner, CommandBlock } from '../components/ui';

function headline(results) {
  if (!results || typeof results !== 'object') return null;
  const sc = results.go_live_scorecard || results.validation_scorecard?.scorecard;
  const ex = results.executive_summary;
  return {
    grade: sc?.grade,
    score: sc?.score,
    recommendation: ex?.recommendation || sc?.recommendation,
    target: ex?.target_system,
  };
}

function RunDetail({ runId }) {
  const { data, error, loading } = useApi(useCallback(() => api.run(runId), [runId]), { deps: [runId] });
  const [downloading, setDownloading] = useState(false);

  const openPdf = async () => {
    setDownloading(true);
    try { window.open(await authUrl(`/api/runs/${runId}/pdf`), '_blank'); } finally { setDownloading(false); }
  };

  if (loading) return <div className="flex items-center gap-2 text-ink-400 text-sm py-12 justify-center"><Spinner /> Loading run…</div>;
  if (error) return <p className="text-sm text-rose-600 py-6">{error.message}</p>;

  const h = headline(data);
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FolderOpen size={16} className="text-indigo-600" />
          <span className="font-mono text-[13px] text-ink-700">{runId}</span>
        </div>
        <button onClick={openPdf} disabled={downloading}
          className="focusable btn-primary inline-flex items-center gap-2 px-4 py-2 rounded-xl text-[13px] font-semibold disabled:opacity-60">
          {downloading ? <Spinner size={14} className="text-white" /> : <Download size={14} />} PDF Report
        </button>
      </div>

      {h && (h.grade || h.recommendation) && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {h.grade && (
            <div className="rounded-2xl bg-emerald-50 p-4">
              <div className="flex items-center gap-1.5 text-emerald-600"><Award size={14} /><span className="text-[10px] uppercase tracking-wider font-semibold">Grade</span></div>
              <p className="text-2xl font-bold text-ink-900 mt-1">{h.grade}{h.score ? <span className="text-sm font-medium text-ink-400 ml-1">{h.score}</span> : null}</p>
            </div>
          )}
          {h.recommendation && (
            <div className="rounded-2xl bg-indigo-50 p-4 col-span-2">
              <div className="flex items-center gap-1.5 text-indigo-600"><CheckCircle2 size={14} /><span className="text-[10px] uppercase tracking-wider font-semibold">Recommendation</span></div>
              <p className="text-sm font-semibold text-ink-900 mt-1">{h.recommendation}</p>
            </div>
          )}
        </div>
      )}

      <div>
        <p className="text-[11px] font-semibold text-ink-500 mb-1.5 uppercase tracking-wider">Full report (final-report.json)</p>
        <pre className="rounded-2xl bg-ink-900 text-slate-100 text-[11.5px] font-mono p-4 overflow-auto max-h-[420px] leading-relaxed">
{JSON.stringify(data, null, 2)}
        </pre>
      </div>
    </div>
  );
}

export default function Runs() {
  const { data, error, loading, reload } = useApi(useCallback(() => api.runs(), []));
  const [selected, setSelected] = useState(null);

  if (loading) return <div className="flex items-center gap-2 text-ink-400 text-sm py-20 justify-center"><Spinner /> Loading runs…</div>;
  if (error) {
    return (
      <div className="space-y-7">
        <PageHeader title="Runs &" accentWord="Reports" subtitle="Completed migration runs and their reports." />
        <OfflineBanner onRetry={reload} />
      </div>
    );
  }

  const runs = Array.isArray(data) ? data : [];
  const active = selected || runs[0]?.id;

  return (
    <div className="space-y-7">
      <PageHeader title="Runs &" accentWord="Reports" subtitle={`${runs.length} completed run${runs.length === 1 ? '' : 's'} on disk.`} />

      {runs.length === 0 ? (
        <Card className="p-6">
          <EmptyState
            icon={FileText}
            title="No runs yet"
            hint="Runs appear here once a pipeline completes and writes its final report."
            action={<CommandBlock cmd="python run_local_lift_and_shift.py --run-id RUN-001" />}
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-[300px_1fr] gap-5">
          <div className="space-y-2">
            {runs.map((r) => (
              <button key={r.id} onClick={() => setSelected(r.id)}
                className={`focusable w-full text-left rounded-2xl p-4 transition border ${active === r.id ? 'bg-indigo-50 border-indigo-200' : 'bg-white border-line hover:border-indigo-200'}`}>
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[12.5px] text-ink-800 truncate">{r.id}</span>
                  <ChevronRight size={14} className={active === r.id ? 'text-indigo-500' : 'text-ink-300'} />
                </div>
                <div className="mt-1.5">
                  {r.has_execution ? <Badge tone="ok">executed</Badge> : <Badge tone="info">assessment</Badge>}
                </div>
              </button>
            ))}
          </div>
          <Card className="p-6">
            {active ? <RunDetail runId={active} /> : <EmptyState title="Select a run" hint="Pick a run from the list to see its report." />}
          </Card>
        </div>
      )}
    </div>
  );
}
