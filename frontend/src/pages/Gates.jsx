import { useCallback, useState, useMemo } from 'react';
import { ShieldCheck, Check, X, Clock, UserCheck, AlertTriangle, Activity, FileText, ChevronDown, ChevronUp } from 'lucide-react';
import { api } from '../lib/api';
import { useApi } from '../lib/useApi';
import { useToast } from '../lib/toast.jsx';
import { Panel, PageHeader, StatusPill, MetricTile, Spinner, EmptyState, OfflineBanner, CmdLine, KVList, SearchBox } from '../components/dd';

// Map gate names → display + tone + icon. Includes the new DataQuality gate
// shipped 2026-06-10 (ManualGate_DataQuality / data_quality).
const GATE_KIND = {
  basis_handover:  { label: 'Basis handover',  desc: 'Target S/4 install complete (HANA + ASCS + ERS + cluster)?', tone: 'info' },
  data_quality:    { label: 'Data quality',    desc: 'Dirty-data rate exceeded SLO threshold. Accept and continue, or cleanse upstream.', tone: 'warn' },
  pre_cutover:     { label: 'Pre-cutover',     desc: 'GO/NO-GO board review of scorecard before cutover begins.', tone: 'info' },
  final_go_live:   { label: 'Final go-live',   desc: 'Last gate before integration flip. After this, switch-back is harder.', tone: 'warn' },
  bods_lane:       { label: 'BODS lane',       desc: 'SAP Data Services manual lane handoff.', tone: 'info' },
};

function tone(g) { return GATE_KIND[g]?.tone || 'muted'; }

export default function Gates() {
  const toast = useToast();
  const { data, error, loading, reload } = useApi(useCallback(() => api.gates(), []), { pollMs: 8000 });
  const [approver, setApprover] = useState(() => localStorage.getItem('m4h_approver') || '');
  const [busyId, setBusyId] = useState(null);
  const [actionErr, setActionErr] = useState(null);
  const [expanded, setExpanded] = useState(null);
  const [filter, setFilter] = useState('');

  const decide = async (gateId, kind) => {
    if (!approver) {
      toast.warn('Approver name required', 'Type your name in the topbar before deciding.');
      return;
    }
    setBusyId(gateId + kind); setActionErr(null);
    localStorage.setItem('m4h_approver', approver);
    try {
      if (kind === 'approve') {
        await api.approveGate(gateId, approver);
        toast.success('Gate approved', `${gateId} · by ${approver}`);
      } else {
        await api.rejectGate(gateId, approver);
        toast.info('Gate rejected', `${gateId} · by ${approver}`);
      }
      await reload();
    } catch (e) {
      setActionErr(e.message);
      toast.error(`Could not ${kind} gate`, e.message);
    } finally {
      setBusyId(null);
    }
  };

  const gates = data?.gates || [];
  const filtered = useMemo(() => {
    const q = filter.toLowerCase();
    if (!q) return gates;
    return gates.filter((g) =>
      (g.gate || '').toLowerCase().includes(q) ||
      (g.run_id || '').toLowerCase().includes(q)
    );
  }, [gates, filter]);

  const stats = useMemo(() => ({
    total: gates.length,
    byKind: gates.reduce((acc, g) => { acc[g.gate] = (acc[g.gate] || 0) + 1; return acc; }, {}),
  }), [gates]);

  if (loading) return <div className="flex items-center gap-2 text-xs text-ink-3 py-20 justify-center"><Spinner /> Loading gates…</div>;
  if (error) {
    return (
      <div className="space-y-4">
        <PageHeader title="Gates" breadcrumb={['Migrate4HANA', 'Gates']} subtitle="Human GO/NO-GO checkpoints." />
        <OfflineBanner onRetry={reload} />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Gates"
        breadcrumb={['Migrate4HANA', 'Gates']}
        subtitle={`${gates.length} pending manual decision${gates.length === 1 ? '' : 's'}. SendTaskSuccess/Failure dispatched via the api server.`}
        actions={
          <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-md" style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
            <UserCheck size={12} className="text-ink-4" />
            <input
              value={approver} onChange={(e) => setApprover(e.target.value)}
              placeholder="Approver"
              className="text-[12px] bg-transparent outline-none w-36 text-ink-1 placeholder:text-ink-4"
            />
          </div>
        }
      />

      {actionErr && (
        <Panel><div className="text-xs flex items-center gap-2" style={{ color: 'var(--err)' }}><AlertTriangle size={13} /> {actionErr}</div></Panel>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <MetricTile label="Pending total" value={gates.length} sub={gates.length ? 'awaiting decision' : 'inbox clear'} tone={gates.length > 0 ? 'warn' : 'ok'} />
        <MetricTile label="Data-quality" value={stats.byKind.data_quality ?? 0} sub="dirty-data SLO halts" tone={(stats.byKind.data_quality ?? 0) > 0 ? 'warn' : null} />
        <MetricTile label="Pre-cutover" value={stats.byKind.pre_cutover ?? 0} sub="GO/NO-GO board" />
        <MetricTile label="Final go-live" value={stats.byKind.final_go_live ?? 0} sub="last gate" />
      </div>

      <Panel
        title="Gate queue"
        icon={ShieldCheck}
        actions={<SearchBox value={filter} onChange={setFilter} placeholder="Filter gate / run id…" />}
        flush
      >
        {filtered.length === 0 ? (
          <EmptyState
            icon={ShieldCheck}
            title="No gates pending"
            hint="Gates appear when a run reaches a manual checkpoint (basis handover, data-quality breach, pre-cutover, final go-live)."
            action={<div className="w-[420px]"><CmdLine cmd="python run_local_lift_and_shift.py --run-id RUN-001" /></div>}
          />
        ) : (
          <div className="divide-y" style={{ borderColor: 'var(--border)' }}>
            {filtered.map((g) => {
              const id = g.gate_id;
              const kind = GATE_KIND[g.gate] || { label: g.gate || 'gate', desc: '', tone: 'muted' };
              const isExpanded = expanded === id;
              const dq = g.payload?.data_quality;
              return (
                <div key={id} className={`px-4 py-3 ${isExpanded ? 'bg-bg-elev' : ''}`} style={isExpanded ? { background: 'var(--bg-elev)' } : undefined}>
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded flex items-center justify-center shrink-0" style={{ background: 'var(--warn-soft)' }}>
                      <Clock size={14} style={{ color: 'var(--warn)' }} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-[13px] font-semibold text-ink-1">{kind.label}</span>
                        <StatusPill tone={tone(g.gate)}>{g.gate}</StatusPill>
                        <StatusPill tone="warn">pending</StatusPill>
                      </div>
                      <div className="font-mono text-[11px] text-ink-3 mt-0.5 truncate">
                        {g.run_id}{g.created_at ? ` · ${new Date(g.created_at).toLocaleString()}` : ''}
                      </div>
                    </div>
                    <button onClick={() => setExpanded(isExpanded ? null : id)} className="btn btn-sm btn-ghost btn-icon" title={isExpanded ? 'Collapse' : 'Inspect'}>
                      {isExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                    </button>
                    <button onClick={() => decide(id, 'reject')} disabled={!!busyId} className="btn btn-sm">
                      {busyId === id + 'reject' ? <Spinner size={11} /> : <X size={12} />} Reject
                    </button>
                    <button onClick={() => decide(id, 'approve')} disabled={!!busyId} className="btn btn-sm btn-primary" style={{ background: 'var(--ok)', borderColor: 'var(--ok)' }}>
                      {busyId === id + 'approve' ? <Spinner size={11} /> : <Check size={12} />} Approve
                    </button>
                  </div>

                  {isExpanded && (
                    <div className="mt-3 ml-11 space-y-3">
                      <p className="text-[12px] text-ink-2 leading-relaxed">{kind.desc}</p>

                      {/* Data-quality drill — special-case the new SLO gate */}
                      {g.gate === 'data_quality' && dq && (
                        <Panel title="Dirty-data context" icon={Activity}>
                          <KVList
                            cols={3}
                            items={[
                              { label: 'attempted',     value: dq.total_attempted ?? '—' },
                              { label: 'dead_letter',   value: dq.total_dead_letter ?? '—' },
                              { label: 'dead_letter_pct', value: dq.dead_letter_pct != null ? `${dq.dead_letter_pct}%` : '—' },
                              { label: 'threshold_pct', value: `${dq.threshold_pct ?? 5}%` },
                              { label: 'slo_breach',    value: String(dq.slo_breach ?? false) },
                              { label: 'gate_disabled', value: String(dq.gate_disabled ?? false) },
                            ]}
                          />
                          <p className="text-[11.5px] text-ink-3 mt-3">
                            <strong>Approve</strong> = accept the dirt and let the pipeline continue (SendTaskSuccess).
                            <br/>
                            <strong>Reject</strong> = halt for upstream cleanse (SendTaskFailure). Re-trigger the run after fixing the source.
                          </p>
                        </Panel>
                      )}

                      <Panel title="Gate payload" subtitle="raw" flush>
                        <pre className="code-block max-h-60 overflow-auto text-[11px] leading-relaxed m-0" style={{ borderRadius: 0 }}>
{JSON.stringify(g, null, 2)}
                        </pre>
                      </Panel>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Panel>
    </div>
  );
}
