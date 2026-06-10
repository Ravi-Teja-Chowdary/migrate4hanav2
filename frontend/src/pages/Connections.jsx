import { useCallback } from 'react';
import { Server, Cloud, Plug, ShieldCheck, CircleSlash, Activity } from 'lucide-react';
import { api } from '../lib/api';
import { useApi } from '../lib/useApi';
import { Panel, PageHeader, StatusPill, MetricTile, Spinner, EmptyState, OfflineBanner, CmdLine, KVList } from '../components/dd';

function ConnectionPanel({ title, subtitle, icon: Icon, conn, statusNode, testCmd, kindIcon }) {
  const configured = !!(conn && (conn.ashost || conn.api_url));
  return (
    <Panel
      title={title}
      subtitle={subtitle}
      icon={Icon}
      actions={statusNode}
    >
      {configured ? (
        <KVList
          cols={2}
          items={[
            { label: 'Host',       value: conn.ashost || conn.api_url || '—' },
            { label: 'System No',  value: conn.sysnr || '—' },
            { label: 'Client',     value: conn.client || '—' },
            { label: 'User',       value: conn.user || '—' },
            { label: 'Type',       value: conn.connection_type || '—' },
            { label: 'Saved',      value: conn.saved_at ? new Date(conn.saved_at).toLocaleString() : '—' },
          ]}
        />
      ) : (
        <div className="rounded border border-dashed py-6 px-4 text-center" style={{ borderColor: 'var(--border)' }}>
          <CircleSlash size={16} className="text-ink-4 mx-auto mb-1.5" />
          <p className="text-xs text-ink-3">Not configured yet</p>
        </div>
      )}
      <div className="mt-4">
        <div className="metric-label mb-1.5">Configure / test from terminal</div>
        <CmdLine cmd={testCmd} />
      </div>
    </Panel>
  );
}

export default function Connections() {
  const { data: conns, error, loading, reload } = useApi(useCallback(() => api.connections(), []));
  const { data: eccStatus } = useApi(useCallback(() => api.eccStatus(), []), { pollMs: 10000 });

  if (loading) return <div className="flex items-center gap-2 text-xs text-ink-3 py-20 justify-center"><Spinner /> Loading connections…</div>;
  if (error) {
    return (
      <div className="space-y-4">
        <PageHeader title="Connections" breadcrumb={['Migrate4HANA', 'Connections']} subtitle="ECC source and S/4HANA target." />
        <OfflineBanner onRetry={reload} />
      </div>
    );
  }

  const ecc = conns?.ecc;
  const s4 = conns?.s4hana || conns?.lift_and_shift_target;
  const liveReady = eccStatus?.live_ready;

  const eccTone = liveReady ? 'ok' : ecc?.ashost ? 'warn' : 'muted';
  const s4Tone = (s4?.ashost || s4?.api_url) ? 'ok' : 'muted';

  return (
    <div className="space-y-4">
      <PageHeader
        title="Connections"
        breadcrumb={['Migrate4HANA', 'Connections']}
        subtitle="Live read of connections.json. Credentials are never displayed, only their presence."
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <MetricTile
          label="Source ECC"
          value={liveReady ? 'Live' : ecc?.ashost ? 'Saved' : 'None'}
          sub={ecc?.has_password ? 'session active' : 'no live session'}
          tone={eccTone}
        />
        <MetricTile
          label="Target S/4HANA"
          value={(s4?.ashost || s4?.api_url) ? 'Set' : 'None'}
          sub={s4?.connection_type || ''}
          tone={s4Tone}
        />
        <MetricTile
          label="Last ECC test"
          value={ecc?.saved_at ? new Date(ecc.saved_at).toLocaleDateString() : '—'}
          sub={ecc?.saved_at ? new Date(ecc.saved_at).toLocaleTimeString() : ''}
        />
        <MetricTile
          label="Last S/4 test"
          value={s4?.saved_at ? new Date(s4.saved_at).toLocaleDateString() : '—'}
          sub={s4?.saved_at ? new Date(s4.saved_at).toLocaleTimeString() : ''}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <ConnectionPanel
          title="Source — SAP ECC"
          subtitle="Migration source · pyrfc over RFC"
          icon={Server}
          conn={ecc}
          testCmd="python test_rfc_connectivity.py"
          statusNode={
            <StatusPill tone={eccTone}>
              {liveReady ? <><ShieldCheck size={11} /> live-ready</> : ecc?.ashost ? <><Plug size={11} /> saved</> : 'not configured'}
            </StatusPill>
          }
        />
        <ConnectionPanel
          title="Target — S/4HANA"
          subtitle="Greenfield / RISE target · RFC + OData"
          icon={Cloud}
          conn={s4}
          testCmd="python diag_login.py"
          statusNode={
            <StatusPill tone={s4Tone}>
              {(s4?.ashost || s4?.api_url) ? <><ShieldCheck size={11} /> configured</> : 'not configured'}
            </StatusPill>
          }
        />
      </div>

      {!ecc?.ashost && !s4?.ashost && (
        <Panel>
          <EmptyState
            icon={Plug}
            title="No systems configured"
            hint="Connections live in connections.json. Configure them from the Command Center → Connections category, or via the terminal."
            action={<div className="w-[420px]"><CmdLine cmd="python test_rfc_connectivity.py" /></div>}
          />
        </Panel>
      )}

      <Panel title="Active ECC tunnels & secrets" icon={Activity} subtitle="surface the rotational scripts">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <CmdLine label="tunnel" cmd="powershell scripts/launch-ecc-tunnel.ps1" />
          <CmdLine label="ecc secret" cmd="powershell scripts/update-ecc-secret.ps1" />
          <CmdLine label="s4 secret" cmd="powershell scripts/update-s4-secret.ps1" />
          <CmdLine label="cal ecc secret" cmd="powershell scripts/update-cal-ecc-secret.ps1" />
          <CmdLine label="ngrok ecc" cmd="powershell scripts/update-ngrok-ecc-secret.ps1" />
          <CmdLine label="sync ips" cmd="powershell scripts/sync-ips.ps1" />
        </div>
      </Panel>
    </div>
  );
}
