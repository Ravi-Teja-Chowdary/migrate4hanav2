// Clients (tenants) page — list, add, switch, delete.
//
// Every other page in the app honors the active client picked here (via
// X-Client-Id header attached by lib/api.js). Adding a client gives you a
// fresh slate: its own ECC + S4 connections, its own runs, its own outputs.
import { useCallback, useState } from 'react';
import { Users, Plus, CheckCircle2, Trash2, AlertTriangle } from 'lucide-react';
import { api } from '../lib/api';
import { useApi } from '../lib/useApi';
import { useToast } from '../lib/toast.jsx';
import { useActiveClient } from '../lib/activeClient.jsx';
import {
  Panel, PageHeader, StatusPill, Spinner, EmptyState, OfflineBanner, KVList,
} from '../components/dd';

const fmtDate = (s) => { try { return new Date(s).toLocaleString(); } catch { return s; } };

function AddClientForm({ onAdded }) {
  const toast = useToast();
  const [id, setId] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!id.trim()) { toast.error('Client id is required', 'lowercase a-z, 0-9, _ or -'); return; }
    setBusy(true);
    try {
      const c = await api.createClient({ id: id.trim(), name: name.trim() || undefined });
      toast.success('Client created', c.id);
      setId(''); setName('');
      onAdded?.(c.id);
    } catch (err) {
      toast.error('Could not create client', err.message);
    } finally { setBusy(false); }
  };

  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-2.5">
      <div className="flex-1 min-w-[160px]">
        <label className="block text-[10.5px] uppercase tracking-wider font-semibold text-ink-3 mb-1">Client id</label>
        <input
          value={id}
          onChange={(e) => setId(e.target.value.toLowerCase())}
          placeholder="acme-corp"
          className="w-full font-mono"
          style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 3, padding: '6px 10px', color: 'var(--ink-1)', fontSize: 12 }}
        />
      </div>
      <div className="flex-1 min-w-[180px]">
        <label className="block text-[10.5px] uppercase tracking-wider font-semibold text-ink-3 mb-1">Display name</label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Acme Corp (optional)"
          className="w-full"
          style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 3, padding: '6px 10px', color: 'var(--ink-1)', fontSize: 12 }}
        />
      </div>
      <button type="submit" disabled={busy || !id.trim()} className="btn btn-primary">
        {busy ? <Spinner size={11} /> : <Plus size={11} />} Add client
      </button>
    </form>
  );
}

export default function Clients() {
  const toast = useToast();
  const { activeClientId, setActiveClientId, refresh } = useActiveClient();
  const { data, error, loading, reload } = useApi(useCallback(() => api.listClients(), []));
  const [confirmDelete, setConfirmDelete] = useState(null);

  if (loading) return <div className="flex items-center gap-2 text-xs text-ink-3 py-20 justify-center"><Spinner /> Loading clients…</div>;
  if (error) {
    return (
      <div className="space-y-4">
        <PageHeader title="Clients" breadcrumb={['Migrate4HANA', 'Clients']} subtitle="Multi-tenant: each client has its own connections + runs." />
        <OfflineBanner onRetry={reload} />
      </div>
    );
  }

  const clients = data?.clients || [];
  const defaultId = data?.default_client_id || 'default';

  const onAdded = async (newId) => {
    await reload();
    await refresh();
    setActiveClientId(newId);
  };

  const onDelete = async (id) => {
    try {
      await api.deleteClient(id);
      toast.success('Client deleted', id);
      // If we just nuked the active one, snap back to default.
      if (activeClientId === id) setActiveClientId(defaultId);
      setConfirmDelete(null);
      await reload();
      await refresh();
    } catch (err) {
      toast.error('Delete failed', err.message);
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Clients"
        breadcrumb={['Migrate4HANA', 'Clients']}
        subtitle={
          <>
            Multi-tenant control plane · each client has its own ECC + S/4 credentials and runs ·
            active: <span className="font-mono">{activeClientId}</span>
          </>
        }
      />

      <Panel title="Add a new client" icon={Plus}>
        <p className="text-[11.5px] text-ink-3 mb-3">
          Use a short, lowercase id (it shows up in S3 prefixes and run paths). The display name is what the picker shows.
        </p>
        <AddClientForm onAdded={onAdded} />
      </Panel>

      <Panel title={`Clients (${clients.length})`} flush>
        {clients.length === 0 ? (
          <EmptyState
            icon={Users}
            title="No clients yet"
            hint="Add one above. The 'default' client is always present for backwards compatibility with pre-tenancy runs."
          />
        ) : (
          <table className="dt">
            <thead>
              <tr>
                <th>Active</th>
                <th>Client id</th>
                <th>Name</th>
                <th>Created</th>
                <th>ECC session</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {clients.map((c) => {
                const isActive = c.id === activeClientId;
                const isDefault = c.id === defaultId;
                return (
                  <tr key={c.id} className="cursor-pointer" onClick={() => setActiveClientId(c.id)} style={{ background: isActive ? 'var(--surface-2)' : undefined }}>
                    <td>{isActive
                      ? <CheckCircle2 size={13} style={{ color: 'var(--ok)' }} />
                      : <button onClick={(e) => { e.stopPropagation(); setActiveClientId(c.id); }} className="btn btn-sm btn-ghost">Switch</button>}
                    </td>
                    <td className="font-mono text-[11.5px] text-ink-1">{c.id}</td>
                    <td className="text-ink-2">{c.name || '—'}</td>
                    <td className="text-ink-3 tabular-nums">{c.created_at ? fmtDate(c.created_at) : '—'}</td>
                    <td>
                      <StatusPill tone={c.has_ecc_session ? 'ok' : 'muted'}>
                        {c.has_ecc_session ? 'authenticated' : 'not connected'}
                      </StatusPill>
                    </td>
                    <td onClick={(e) => e.stopPropagation()}>
                      {isDefault ? (
                        <span className="text-[10.5px] text-ink-4">protected</span>
                      ) : confirmDelete === c.id ? (
                        <span className="inline-flex items-center gap-1.5">
                          <button onClick={() => onDelete(c.id)} className="btn btn-sm" style={{ background: 'var(--err)', color: '#fff' }}>
                            Confirm delete
                          </button>
                          <button onClick={() => setConfirmDelete(null)} className="btn btn-sm btn-ghost">Cancel</button>
                        </span>
                      ) : (
                        <button onClick={() => setConfirmDelete(c.id)} className="btn btn-sm btn-ghost" title="Delete client">
                          <Trash2 size={11} />
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel title="How tenancy works" icon={AlertTriangle}>
        <KVList
          cols={1}
          items={[
            { label: 'Active client header', value: <span className="font-mono">X-Client-Id: {activeClientId}</span> },
            { label: 'Connections',          value: 'Each client has its own ECC + S/4 credentials. Save and test them per-client on the Connections page.' },
            { label: 'Runs',                 value: <>Runs land under <span className="font-mono">outputs/clients/&lt;client_id&gt;/</span>. The default client uses the legacy flat path.</> },
            { label: 'Switching',            value: 'Use the topbar picker or click a row above. The whole UI swaps tenants — no reload needed.' },
            { label: 'Delete',               value: 'Removing a client drops its registry entry. Its on-disk outputs remain (clean them up separately).' },
          ]}
        />
      </Panel>
    </div>
  );
}
