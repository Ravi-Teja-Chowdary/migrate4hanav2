import { useCallback, useState } from 'react';
import { ShieldCheck, Check, X, Clock, UserCheck } from 'lucide-react';
import { api } from '../lib/api';
import { useApi } from '../lib/useApi';
import { Card, PageHeader, Badge, Spinner, EmptyState, OfflineBanner, CommandBlock } from '../components/ui';

export default function Gates() {
  const { data, error, loading, reload } = useApi(useCallback(() => api.gates(), []), { pollMs: 8000 });
  const [approver, setApprover] = useState(() => localStorage.getItem('m4h_approver') || '');
  const [busyId, setBusyId] = useState(null);
  const [actionErr, setActionErr] = useState(null);

  const decide = async (gateId, kind) => {
    setBusyId(gateId + kind); setActionErr(null);
    localStorage.setItem('m4h_approver', approver);
    try {
      if (kind === 'approve') await api.approveGate(gateId, approver);
      else await api.rejectGate(gateId, approver);
      await reload();
    } catch (e) {
      setActionErr(e.message);
    } finally {
      setBusyId(null);
    }
  };

  if (loading) return <div className="flex items-center gap-2 text-ink-400 text-sm py-20 justify-center"><Spinner /> Loading gates…</div>;
  if (error) {
    return (
      <div className="space-y-7">
        <PageHeader title="Approval" accentWord="Gates" subtitle="Human GO/NO-GO checkpoints in the pipeline." />
        <OfflineBanner onRetry={reload} />
      </div>
    );
  }

  const gates = data?.gates || [];

  return (
    <div className="space-y-7">
      <PageHeader
        title="Approval" accentWord="Gates"
        subtitle={`The pipeline pauses here for human decisions${data?.source ? ` · source: ${data.source}` : ''}.`}
        actions={
          <div className="flex items-center gap-2 rounded-xl bg-white border border-line px-3 py-2 shadow-soft">
            <UserCheck size={15} className="text-ink-400" />
            <input
              value={approver} onChange={(e) => setApprover(e.target.value)}
              placeholder="Approver name / email"
              className="focusable text-[13px] text-ink-900 bg-transparent outline-none w-48 placeholder:text-ink-300"
            />
          </div>
        }
      />

      {actionErr && (
        <Card className="p-3 border-rose-200/60"><p className="text-xs text-rose-600">{actionErr}</p></Card>
      )}

      {gates.length === 0 ? (
        <Card className="p-6">
          <EmptyState
            icon={ShieldCheck}
            title="No pending gates"
            hint="Gates appear when a run reaches a manual checkpoint (basis handover, pre-cutover, final go-live)."
            action={<CommandBlock cmd="python run_local_lift_and_shift.py --run-id RUN-001" />}
          />
        </Card>
      ) : (
        <div className="space-y-3">
          {gates.map((g) => {
            const id = g.gate_id;
            return (
              <Card key={id} hover className="p-5">
                <div className="flex items-center gap-4 flex-wrap">
                  <div className="w-11 h-11 rounded-2xl bg-amber-50 flex items-center justify-center shrink-0">
                    <Clock size={18} className="text-amber-600" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <h3 className="text-[15px] font-semibold text-ink-900 truncate">{(g.gate || 'gate').replace(/_/g, ' ')}</h3>
                      <Badge tone="warn">pending</Badge>
                    </div>
                    <p className="text-xs text-ink-400 mt-0.5 font-mono">{g.run_id}{g.created_at ? ` · ${new Date(g.created_at).toLocaleString()}` : ''}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => decide(id, 'reject')} disabled={!!busyId}
                      className="focusable inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-rose-50 text-rose-600 text-[13px] font-semibold hover:bg-rose-100 transition disabled:opacity-50"
                    >
                      {busyId === id + 'reject' ? <Spinner size={13} className="text-rose-500" /> : <X size={14} />} Reject
                    </button>
                    <button
                      onClick={() => decide(id, 'approve')} disabled={!!busyId}
                      className="focusable inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-emerald-500 text-white text-[13px] font-semibold hover:bg-emerald-600 transition disabled:opacity-50"
                    >
                      {busyId === id + 'approve' ? <Spinner size={13} className="text-white" /> : <Check size={14} />} Approve
                    </button>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
