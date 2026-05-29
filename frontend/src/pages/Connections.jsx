import { useCallback } from 'react';
import { Server, Cloud, Plug, ShieldCheck, CircleSlash } from 'lucide-react';
import { api } from '../lib/api';
import { useApi } from '../lib/useApi';
import {
  Card, PageHeader, Badge, Spinner, EmptyState, OfflineBanner, CommandBlock, ACCENT,
} from '../components/ui';

function Field({ k, v }) {
  return (
    <div className="rounded-xl bg-slate-50 px-3 py-2 border border-line">
      <p className="text-[9px] uppercase tracking-wider text-ink-400 font-semibold">{k}</p>
      <p className="text-[13px] font-mono text-ink-700 truncate">{v || '—'}</p>
    </div>
  );
}

function ConnectionCard({ kind, title, icon: Icon, accent, conn, statusNode, testCmd }) {
  const a = ACCENT[accent];
  const configured = !!(conn && conn.ashost) || !!(conn && conn.api_url);
  return (
    <Card hover className="p-6">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className={`w-11 h-11 rounded-2xl ${a.bg} flex items-center justify-center`}>
            <Icon size={20} className={a.text} />
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-ink-400 font-semibold">{kind}</p>
            <h3 className="text-[15px] font-semibold text-ink-900">{title}</h3>
          </div>
        </div>
        {statusNode}
      </div>

      {configured ? (
        <div className="grid grid-cols-2 gap-2.5">
          <Field k="Host" v={conn.ashost || conn.api_url} />
          <Field k="System No" v={conn.sysnr} />
          <Field k="Client" v={conn.client} />
          <Field k="User" v={conn.user} />
          {conn.connection_type && <Field k="Type" v={conn.connection_type} />}
          {conn.saved_at && <Field k="Saved" v={new Date(conn.saved_at).toLocaleString()} />}
        </div>
      ) : (
        <div className="rounded-xl bg-slate-50 border border-dashed border-line px-4 py-5 text-center">
          <CircleSlash size={18} className="text-ink-300 mx-auto mb-1.5" />
          <p className="text-xs text-ink-400">Not configured yet</p>
        </div>
      )}

      <div className="mt-4">
        <p className="text-[11px] font-semibold text-ink-500 mb-1.5">Configure / test from terminal</p>
        <CommandBlock cmd={testCmd} />
      </div>
    </Card>
  );
}

export default function Connections() {
  const { data: conns, error, loading, reload } = useApi(useCallback(() => api.connections(), []));
  const { data: eccStatus } = useApi(useCallback(() => api.eccStatus(), []), { pollMs: 10000 });

  if (loading) {
    return <div className="flex items-center gap-2 text-ink-400 text-sm py-20 justify-center"><Spinner /> Loading connections…</div>;
  }
  if (error) {
    return (
      <div className="space-y-7">
        <PageHeader title="System" accentWord="Connections" subtitle="Source ECC and target S/4HANA RISE." />
        <OfflineBanner onRetry={reload} />
      </div>
    );
  }

  const ecc = conns?.ecc;
  const s4 = conns?.s4hana || conns?.lift_and_shift_target;
  const liveReady = eccStatus?.live_ready;

  return (
    <div className="space-y-7">
      <PageHeader
        title="System" accentWord="Connections"
        subtitle="Live read of connections.json — credentials are never displayed, only their presence."
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <ConnectionCard
          kind="Start · Source" title="SAP ECC" icon={Server} accent="indigo" conn={ecc}
          testCmd="python test_rfc_connectivity.py"
          statusNode={
            liveReady
              ? <Badge tone="ok"><ShieldCheck size={12} /> Live-ready</Badge>
              : ecc?.ashost
                ? <Badge tone="warn"><Plug size={12} /> Saved · no live session</Badge>
                : <Badge tone="pending">Not configured</Badge>
          }
        />
        <ConnectionCard
          kind="End · Target" title="S/4HANA (RISE)" icon={Cloud} accent="teal" conn={s4}
          testCmd="python diag_login.py"
          statusNode={
            s4?.ashost || s4?.api_url
              ? <Badge tone="ok"><ShieldCheck size={12} /> Configured</Badge>
              : <Badge tone="pending">Not configured</Badge>
          }
        />
      </div>

      {!ecc?.ashost && !s4?.ashost && (
        <Card className="p-6">
          <EmptyState
            icon={Plug}
            title="No systems configured"
            hint="Connections live in connections.json. Configure and verify them from the terminal, then this page reflects them live."
            action={<CommandBlock cmd="python test_rfc_connectivity.py" />}
          />
        </Card>
      )}
    </div>
  );
}
