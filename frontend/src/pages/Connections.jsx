import { useCallback, useEffect, useState } from 'react';
import {
  Server, Cloud, ShieldCheck, CircleSlash, Activity, Save, Zap, Eye, EyeOff,
  CheckCircle2, AlertTriangle, RefreshCcw,
} from 'lucide-react';
import { api } from '../lib/api';
import { useApi } from '../lib/useApi';
import { useToast } from '../lib/toast.jsx';
import { Panel, PageHeader, StatusPill, MetricTile, Spinner, OfflineBanner, KVList } from '../components/dd';

// Editable input row. Renders label + input; supports password mask toggle.
function Field({ label, value, onChange, type = 'text', placeholder = '', autoComplete = 'off', monospace = false, required = false }) {
  const [show, setShow] = useState(false);
  const isPwd = type === 'password';
  const inputType = isPwd ? (show ? 'text' : 'password') : type;
  return (
    <div>
      <label className="metric-label flex items-center gap-1">
        {label}
        {required && <span style={{ color: 'var(--err)' }}>*</span>}
      </label>
      <div className="relative mt-1.5">
        <input
          type={inputType}
          value={value || ''}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          autoComplete={autoComplete}
          className={`input w-full ${monospace ? 'font-mono' : ''} ${isPwd ? 'pr-9' : ''}`}
        />
        {isPwd && (
          <button
            type="button"
            onClick={() => setShow((s) => !s)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-ink-4 hover:text-ink-1"
            tabIndex={-1}
            title={show ? 'Hide password' : 'Show password'}
          >
            {show ? <EyeOff size={13} /> : <Eye size={13} />}
          </button>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// ECC editor — form + Save + Test live against api_server.py
// ─────────────────────────────────────────────────────────────
function ECCEditor({ initial, onSaved }) {
  const toast = useToast();
  const [f, setF] = useState({
    ashost: '', sysnr: '00', client: '100', user: '', passwd: '', saprouter: '',
    ...(initial || {}),
  });
  const [testResult, setTestResult] = useState(null); // {ok:bool, message:string, details?:obj}
  const [busy, setBusy] = useState(null); // 'test' | 'save' | null

  // Rehydrate when the loaded saved connection changes.
  useEffect(() => {
    if (initial) setF((cur) => ({ ...cur, ...initial, passwd: cur.passwd }));
  }, [initial]);

  const upd = (k) => (v) => setF((cur) => ({ ...cur, [k]: v }));

  const valid = !!(f.ashost && f.client && f.user);
  const validForTest = valid && !!f.passwd;

  const runTest = async () => {
    if (!validForTest) {
      toast.warn('Cannot test', 'Host, client, user, and password are all required.');
      return;
    }
    setBusy('test'); setTestResult(null);
    const tId = toast.loading('Testing ECC connection…', `${f.ashost} · client ${f.client}`);
    try {
      const r = await api.testEcc(f);
      const ok = !!r.success;
      setTestResult({ ok, message: r.message || (ok ? 'Connected' : 'Failed'), details: r });
      toast.dismiss(tId);
      if (ok) toast.success('ECC connection live', r.message || `Connected as ${f.user}@${f.ashost}`);
      else    toast.error('ECC test failed', r.message || 'Connection refused');
    } catch (e) {
      toast.dismiss(tId);
      setTestResult({ ok: false, message: e.message });
      toast.error('ECC test errored', e.message);
    } finally {
      setBusy(null);
    }
  };

  const runSave = async () => {
    if (!valid) {
      toast.warn('Cannot save', 'Host, client, and user are required.');
      return;
    }
    setBusy('save');
    try {
      const r = await api.saveEcc(f);
      toast.success('ECC connection saved', `${r.connection?.ashost} · client ${r.connection?.client}`);
      onSaved?.(r.connection);
    } catch (e) {
      toast.error('Save failed', e.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Panel title="Source — SAP ECC" icon={Server} subtitle="Migration source · pyrfc over RFC">
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2"><Field label="Application server host (ashost)" value={f.ashost} onChange={upd('ashost')} placeholder="ecc.example.com or 10.0.0.5" required monospace /></div>
        <Field label="System number" value={f.sysnr} onChange={upd('sysnr')} placeholder="00" monospace />
        <Field label="Client" value={f.client} onChange={upd('client')} placeholder="100" required monospace />
        <Field label="User" value={f.user} onChange={upd('user')} placeholder="MIGRATE_ADMIN" required />
        <Field label="Password" value={f.passwd} onChange={upd('passwd')} type="password" placeholder="(never persisted to disk)" autoComplete="new-password" />
        <div className="col-span-2"><Field label="SAP Router (optional)" value={f.saprouter} onChange={upd('saprouter')} placeholder="/H/sap-router.example.com/S/3299/H/" monospace /></div>
      </div>

      {testResult && (
        <div className="mt-3 panel" style={{ borderColor: testResult.ok ? 'var(--ok)' : 'var(--err)' }}>
          <div className="panel-body flex items-start gap-2.5">
            {testResult.ok
              ? <CheckCircle2 size={14} className="shrink-0 mt-0.5" style={{ color: 'var(--ok)' }} />
              : <AlertTriangle size={14} className="shrink-0 mt-0.5" style={{ color: 'var(--err)' }} />}
            <div className="min-w-0 flex-1">
              <div className="text-[12.5px] font-semibold text-ink-1">
                {testResult.ok ? 'Connection successful' : 'Connection failed'}
              </div>
              <div className="text-[11.5px] text-ink-3 mt-0.5 break-words font-mono">{testResult.message}</div>
              {testResult.details?.system_info && (
                <div className="text-[11px] text-ink-3 mt-1 font-mono">
                  SID {testResult.details.system_info.sid} · DB {testResult.details.system_info.db} · {testResult.details.system_info.release}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      <div className="mt-4 flex items-center gap-2">
        <button onClick={runTest} disabled={!!busy || !validForTest} className="btn btn-sm">
          {busy === 'test' ? <Spinner size={12} /> : <Zap size={12} />} Test connection
        </button>
        <button onClick={runSave} disabled={!!busy || !valid} className="btn btn-sm btn-primary">
          {busy === 'save' ? <Spinner size={12} /> : <Save size={12} />} Save
        </button>
        <span className="text-[11px] text-ink-4 ml-auto">password held in server memory only · never written to disk</span>
      </div>
    </Panel>
  );
}

// ─────────────────────────────────────────────────────────────
// S/4HANA editor — supports rfc | odata variants
// ─────────────────────────────────────────────────────────────
function S4Editor({ initial, onSaved }) {
  const toast = useToast();
  const [f, setF] = useState({
    connection_type: 'rfc',
    ashost: '', sysnr: '00', client: '100', user: '', passwd: '',
    api_url: '', saprouter: '',
    ...(initial || {}),
  });
  const [testResult, setTestResult] = useState(null);
  const [busy, setBusy] = useState(null);

  useEffect(() => {
    if (initial) setF((cur) => ({ ...cur, ...initial, passwd: cur.passwd }));
  }, [initial]);

  const upd = (k) => (v) => setF((cur) => ({ ...cur, [k]: v }));
  const isRfc = f.connection_type === 'rfc';
  const isOdata = f.connection_type === 'odata';

  const valid = isRfc
    ? !!(f.ashost && f.client && f.user)
    : !!(f.api_url && f.user);
  const validForTest = isRfc ? (valid && !!f.passwd) : (valid && !!f.passwd);

  const runTest = async () => {
    if (!validForTest) {
      toast.warn('Cannot test', isRfc ? 'host/client/user/password required' : 'api_url/user/password required');
      return;
    }
    setBusy('test'); setTestResult(null);
    const tId = toast.loading('Testing S/4HANA connection…', f.ashost || f.api_url);
    try {
      const r = await api.testS4(f);
      const ok = !!r.success;
      setTestResult({ ok, message: r.message || (ok ? 'Connected' : 'Failed'), details: r });
      toast.dismiss(tId);
      if (ok) toast.success('S/4HANA connection live', r.message || 'Connected');
      else    toast.error('S/4 test failed', r.message || 'Connection refused');
    } catch (e) {
      toast.dismiss(tId);
      setTestResult({ ok: false, message: e.message });
      toast.error('S/4 test errored', e.message);
    } finally {
      setBusy(null);
    }
  };

  const runSave = async () => {
    if (!valid) { toast.warn('Cannot save', 'Required fields missing'); return; }
    setBusy('save');
    try {
      const r = await api.saveS4(f);
      toast.success('S/4HANA connection saved', `${f.connection_type} · ${r.connection?.ashost || r.connection?.api_url}`);
      onSaved?.(r.connection);
    } catch (e) {
      toast.error('Save failed', e.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Panel title="Target — S/4HANA" icon={Cloud} subtitle="Greenfield / RISE target · RFC or OData">
      {/* Connection type radios */}
      <div className="flex items-center gap-1.5 mb-3">
        {[
          { v: 'rfc',   label: 'RFC (pyrfc)' },
          { v: 'odata', label: 'OData (HTTPS)' },
        ].map((o) => (
          <button
            key={o.v}
            onClick={() => upd('connection_type')(o.v)}
            className={`btn btn-sm ${f.connection_type === o.v ? 'btn-primary' : ''}`}
          >
            {o.label}
          </button>
        ))}
      </div>

      {isRfc && (
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2"><Field label="Application server host (ashost)" value={f.ashost} onChange={upd('ashost')} placeholder="s4.example.com or 10.0.0.6" required monospace /></div>
          <Field label="System number" value={f.sysnr} onChange={upd('sysnr')} placeholder="00" monospace />
          <Field label="Client" value={f.client} onChange={upd('client')} placeholder="100" required monospace />
          <Field label="User" value={f.user} onChange={upd('user')} placeholder="MIGRATE_USER" required />
          <Field label="Password" value={f.passwd} onChange={upd('passwd')} type="password" placeholder="(never persisted to disk)" autoComplete="new-password" />
          <div className="col-span-2"><Field label="SAP Router (optional)" value={f.saprouter} onChange={upd('saprouter')} placeholder="/H/sap-router.example.com/S/3299/H/" monospace /></div>
        </div>
      )}

      {isOdata && (
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2"><Field label="API base URL" value={f.api_url} onChange={upd('api_url')} placeholder="https://s4.example.com/sap/opu/odata/sap/" required monospace /></div>
          <Field label="User" value={f.user} onChange={upd('user')} placeholder="API_USER" required />
          <Field label="Password" value={f.passwd} onChange={upd('passwd')} type="password" placeholder="(never persisted to disk)" autoComplete="new-password" />
        </div>
      )}

      {testResult && (
        <div className="mt-3 panel" style={{ borderColor: testResult.ok ? 'var(--ok)' : 'var(--err)' }}>
          <div className="panel-body flex items-start gap-2.5">
            {testResult.ok
              ? <CheckCircle2 size={14} className="shrink-0 mt-0.5" style={{ color: 'var(--ok)' }} />
              : <AlertTriangle size={14} className="shrink-0 mt-0.5" style={{ color: 'var(--err)' }} />}
            <div className="min-w-0 flex-1">
              <div className="text-[12.5px] font-semibold text-ink-1">
                {testResult.ok ? 'Connection successful' : 'Connection failed'}
              </div>
              <div className="text-[11.5px] text-ink-3 mt-0.5 break-words font-mono">{testResult.message}</div>
            </div>
          </div>
        </div>
      )}

      <div className="mt-4 flex items-center gap-2">
        <button onClick={runTest} disabled={!!busy || !validForTest} className="btn btn-sm">
          {busy === 'test' ? <Spinner size={12} /> : <Zap size={12} />} Test connection
        </button>
        <button onClick={runSave} disabled={!!busy || !valid} className="btn btn-sm btn-primary">
          {busy === 'save' ? <Spinner size={12} /> : <Save size={12} />} Save
        </button>
        <span className="text-[11px] text-ink-4 ml-auto">password held in server memory only · never written to disk</span>
      </div>
    </Panel>
  );
}

// ─────────────────────────────────────────────────────────────
// Saved connection summary (read-only, what's currently stored)
// ─────────────────────────────────────────────────────────────
function SavedSummary({ title, icon: Icon, conn, tone, statusLabel }) {
  if (!conn || (!conn.ashost && !conn.api_url)) {
    return (
      <Panel title={`${title} (saved)`} icon={Icon}>
        <div className="rounded border border-dashed py-6 px-4 text-center" style={{ borderColor: 'var(--border)' }}>
          <CircleSlash size={16} className="text-ink-4 mx-auto mb-1.5" />
          <p className="text-xs text-ink-3">Not configured yet</p>
          <p className="text-[11px] text-ink-4 mt-1">Fill the form on the left, Test, then Save.</p>
        </div>
      </Panel>
    );
  }
  return (
    <Panel
      title={`${title} (saved)`}
      icon={Icon}
      actions={<StatusPill tone={tone}>{statusLabel}</StatusPill>}
    >
      <KVList
        cols={2}
        items={[
          { label: 'Host',      value: conn.ashost || conn.api_url || '—' },
          { label: 'System No', value: conn.sysnr || '—' },
          { label: 'Client',    value: conn.client || '—' },
          { label: 'User',      value: conn.user || '—' },
          { label: 'Type',      value: conn.connection_type || 'rfc' },
          { label: 'Saved',     value: conn.saved_at ? new Date(conn.saved_at).toLocaleString() : '—' },
        ]}
      />
    </Panel>
  );
}

export default function Connections() {
  const toast = useToast();
  const { data: conns, error, loading, reload } = useApi(useCallback(() => api.connections(), []));
  const { data: eccStatus, reload: reloadEccStatus } = useApi(useCallback(() => api.eccStatus(), []), { pollMs: 10000 });

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
  const eccLabel = liveReady ? 'live-ready' : ecc?.ashost ? 'saved · no live session' : 'not configured';
  const s4Tone = (s4?.ashost || s4?.api_url) ? 'ok' : 'muted';
  const s4Label = (s4?.ashost || s4?.api_url) ? 'configured' : 'not configured';

  const onEccSaved = async () => { await reload(); await reloadEccStatus(); };
  const onS4Saved = async () => { await reload(); };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Connections"
        breadcrumb={['Migrate4HANA', 'Connections']}
        subtitle="Configure, test, and save ECC source + S/4HANA target. Passwords are held in server memory only; never written to disk."
        actions={<button onClick={() => { reload(); reloadEccStatus(); }} className="btn btn-sm"><RefreshCcw size={12} /> Refresh</button>}
      />

      {/* Status tiles */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <MetricTile label="Source ECC" value={liveReady ? 'Live' : ecc?.ashost ? 'Saved' : 'None'} sub={ecc?.has_password ? 'session active' : 'no live session'} tone={eccTone} />
        <MetricTile label="Target S/4HANA" value={(s4?.ashost || s4?.api_url) ? 'Set' : 'None'} sub={s4?.connection_type || ''} tone={s4Tone} />
        <MetricTile label="Last ECC test" value={ecc?.saved_at ? new Date(ecc.saved_at).toLocaleDateString() : '—'} sub={ecc?.saved_at ? new Date(ecc.saved_at).toLocaleTimeString() : ''} />
        <MetricTile label="Last S/4 test" value={s4?.saved_at ? new Date(s4.saved_at).toLocaleDateString() : '—'} sub={s4?.saved_at ? new Date(s4.saved_at).toLocaleTimeString() : ''} />
      </div>

      {/* Editor + saved summary side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <ECCEditor initial={ecc} onSaved={onEccSaved} />
        <SavedSummary title="Source ECC" icon={Server} conn={ecc} tone={eccTone} statusLabel={eccLabel} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <S4Editor initial={s4} onSaved={onS4Saved} />
        <SavedSummary title="Target S/4HANA" icon={Cloud} conn={s4} tone={s4Tone} statusLabel={s4Label} />
      </div>
    </div>
  );
}
