import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Server, Cloud, Wifi, WifiOff, CheckCircle2, AlertTriangle,
  XCircle, Loader2, Save, TestTube, ChevronDown, ChevronUp,
  Shield, Database, Eye, EyeOff,
} from 'lucide-react';
import { apiFetch } from '../api';

function ConnectionCard({ title, subtitle, icon: Icon, color, status, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  const statusColor = { connected: '#10b981', mock: '#f59e0b', error: '#ef4444', saved: '#3b82f6' }[status] || '#ffffff20';
  const statusLabel = { connected: 'Connected', mock: 'Mock Mode', error: 'Error', saved: 'Saved' }[status] || 'Not Configured';

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass rounded-2xl overflow-hidden"
    >
      <button
        onClick={() => setOpen(!open)}
        className="w-full px-6 py-5 flex items-center gap-4 hover:bg-white/[0.02] transition-colors"
      >
        <div className="w-12 h-12 rounded-xl flex items-center justify-center"
          style={{ backgroundColor: `${color}15` }}>
          <Icon size={22} style={{ color }} />
        </div>
        <div className="flex-1 text-left">
          <h3 className="text-sm font-semibold text-white">{title}</h3>
          <p className="text-xs text-white/30 mt-0.5">{subtitle}</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <div className="w-2 h-2 rounded-full" style={{ backgroundColor: statusColor }} />
            <span className="text-[11px] font-medium" style={{ color: statusColor }}>{statusLabel}</span>
          </div>
          {open ? <ChevronUp size={16} className="text-white/30" /> : <ChevronDown size={16} className="text-white/30" />}
        </div>
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="overflow-hidden"
          >
            <div className="px-6 pb-6 pt-2 border-t border-white/[0.04]">
              {children}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

function Field({ label, value, onChange, type = 'text', placeholder, required, helpText }) {
  const [show, setShow] = useState(false);
  const isPassword = type === 'password';

  return (
    <div>
      <label className="block text-xs text-white/40 mb-1.5">
        {label} {required && <span className="text-accent-red">*</span>}
      </label>
      <div className="relative">
        <input
          type={isPassword && !show ? 'password' : 'text'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="w-full px-3 py-2.5 rounded-lg bg-white/[0.04] border border-white/[0.08] text-sm text-white
                     placeholder-white/20 focus:outline-none focus:border-accent-blue/40 focus:bg-white/[0.06]
                     transition-all"
        />
        {isPassword && (
          <button
            type="button"
            onClick={() => setShow(!show)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-white/20 hover:text-white/40"
          >
            {show ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        )}
      </div>
      {helpText && <p className="text-[10px] text-white/20 mt-1">{helpText}</p>}
    </div>
  );
}

function StatusMessage({ result }) {
  if (!result) return null;
  const isOk = result.status === 'connected' || result.status === 'mock';
  const isErr = result.status === 'error';

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      className={`mt-4 p-3 rounded-xl flex items-start gap-2 ${isOk ? 'bg-accent-green/5 border border-accent-green/10' : isErr ? 'bg-accent-red/5 border border-accent-red/10' : 'bg-accent-blue/5 border border-accent-blue/10'}`}
    >
      {isOk ? <CheckCircle2 size={16} className="text-accent-green mt-0.5 shrink-0" /> :
        isErr ? <XCircle size={16} className="text-accent-red mt-0.5 shrink-0" /> :
          <AlertTriangle size={16} className="text-accent-blue mt-0.5 shrink-0" />}
      <div>
        <p className={`text-xs font-medium ${isOk ? 'text-accent-green' : isErr ? 'text-accent-red' : 'text-accent-blue'}`}>
          {result.message}
        </p>
        {result.system_id && (
          <p className="text-[10px] text-white/30 mt-1">
            System: {result.system_id} | Release: {result.sap_release || '—'}
          </p>
        )}
      </div>
    </motion.div>
  );
}

export default function Connections() {
  // ECC state
  const [eccHost, setEccHost] = useState('');
  const [eccSysnr, setEccSysnr] = useState('00');
  const [eccClient, setEccClient] = useState('100');
  const [eccUser, setEccUser] = useState('');
  const [eccPass, setEccPass] = useState('');
  const [eccRouter, setEccRouter] = useState('');
  const [eccStatus, setEccStatus] = useState(null);
  const [eccResult, setEccResult] = useState(null);
  const [eccTesting, setEccTesting] = useState(false);
  const [eccSaving, setEccSaving] = useState(false);

  // S/4HANA state
  const [s4Type, setS4Type] = useState('rfc');
  const [s4Host, setS4Host] = useState('');
  const [s4Sysnr, setS4Sysnr] = useState('00');
  const [s4Client, setS4Client] = useState('100');
  const [s4User, setS4User] = useState('');
  const [s4Pass, setS4Pass] = useState('');
  const [s4ApiUrl, setS4ApiUrl] = useState('');
  const [s4Router, setS4Router] = useState('');
  const [s4Status, setS4Status] = useState(null);
  const [s4Result, setS4Result] = useState(null);
  const [s4Testing, setS4Testing] = useState(false);
  const [s4Saving, setS4Saving] = useState(false);

  // Load saved connections
  useEffect(() => {
    apiFetch('/api/connections')
      .then((r) => r.json())
      .then((data) => {
        if (data.ecc) {
          setEccHost(data.ecc.ashost || '');
          setEccSysnr(data.ecc.sysnr || '00');
          setEccClient(data.ecc.client || '100');
          setEccUser(data.ecc.user || '');
          setEccRouter(data.ecc.saprouter || '');
          setEccStatus('saved');
        }
        if (data.s4hana) {
          setS4Type(data.s4hana.connection_type || 'rfc');
          setS4Host(data.s4hana.ashost || '');
          setS4Sysnr(data.s4hana.sysnr || '00');
          setS4Client(data.s4hana.client || '100');
          setS4User(data.s4hana.user || '');
          setS4ApiUrl(data.s4hana.api_url || '');
          setS4Router(data.s4hana.saprouter || '');
          setS4Status('saved');
        }
      })
      .catch(() => {});
  }, []);

  const testEcc = useCallback(async () => {
    setEccTesting(true);
    setEccResult(null);
    try {
      const r = await apiFetch('/api/connections/ecc/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ashost: eccHost, sysnr: eccSysnr, client: eccClient, user: eccUser, passwd: eccPass, saprouter: eccRouter }),
      });
      const data = await r.json();
      setEccResult(data);
      setEccStatus(data.status);
    } catch {
      setEccResult({ status: 'error', message: 'Cannot reach API server. Is it running on port 8000?' });
      setEccStatus('error');
    }
    setEccTesting(false);
  }, [eccHost, eccSysnr, eccClient, eccUser, eccPass, eccRouter]);

  const saveEcc = useCallback(async () => {
    setEccSaving(true);
    try {
      await apiFetch('/api/connections/ecc', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ashost: eccHost, sysnr: eccSysnr, client: eccClient, user: eccUser, saprouter: eccRouter }),
      });
      setEccStatus('saved');
    } catch {
      setEccResult({ status: 'error', message: 'Failed to save. Is API server running?' });
    }
    setEccSaving(false);
  }, [eccHost, eccSysnr, eccClient, eccUser, eccRouter]);

  const testS4 = useCallback(async () => {
    setS4Testing(true);
    setS4Result(null);
    try {
      const r = await apiFetch('/api/connections/s4hana/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ connection_type: s4Type, ashost: s4Host, sysnr: s4Sysnr, client: s4Client, user: s4User, passwd: s4Pass, api_url: s4ApiUrl, saprouter: s4Router }),
      });
      const data = await r.json();
      setS4Result(data);
      setS4Status(data.status);
    } catch {
      setS4Result({ status: 'error', message: 'Cannot reach API server.' });
      setS4Status('error');
    }
    setS4Testing(false);
  }, [s4Type, s4Host, s4Sysnr, s4Client, s4User, s4Pass, s4ApiUrl, s4Router]);

  const saveS4 = useCallback(async () => {
    setS4Saving(true);
    try {
      await apiFetch('/api/connections/s4hana', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ connection_type: s4Type, ashost: s4Host, sysnr: s4Sysnr, client: s4Client, user: s4User, api_url: s4ApiUrl, saprouter: s4Router }),
      });
      setS4Status('saved');
    } catch {
      setS4Result({ status: 'error', message: 'Failed to save.' });
    }
    setS4Saving(false);
  }, [s4Type, s4Host, s4Sysnr, s4Client, s4User, s4ApiUrl, s4Router]);

  return (
    <div className="p-8 max-w-3xl mx-auto space-y-6">
      <div>
        <motion.h1 initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }}
          className="text-3xl font-bold text-white">
          System <span className="gradient-text">Connections</span>
        </motion.h1>
        <p className="text-sm text-white/40 mt-1">Configure your SAP ECC source and S/4HANA target</p>
      </div>

      {/* Info Banner */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="glass rounded-xl p-4 flex items-start gap-3 border border-accent-blue/10"
      >
        <Shield size={16} className="text-accent-blue mt-0.5 shrink-0" />
        <div>
          <p className="text-xs text-white/50">
            <b className="text-white/70">How it works:</b> Enter your SAP connection details below.
            The tool connects via <b>RFC protocol</b> (PyRFC) to read your ECC system and write to S/4HANA.
            Passwords are never stored — only connection metadata is saved locally.
          </p>
          <p className="text-[10px] text-white/25 mt-1">
            No PyRFC? The tool runs in <b>mock mode</b> with realistic demo data for evaluation.
          </p>
        </div>
      </motion.div>

      {/* ECC Connection */}
      <ConnectionCard
        title="SAP ECC Source System"
        subtitle="RFC connection to your existing ECC 6.0 system"
        icon={Server}
        color="#3b82f6"
        status={eccStatus}
        defaultOpen={true}
      >
        <div className="grid grid-cols-2 gap-4">
          <Field label="Application Server" value={eccHost} onChange={setEccHost}
            placeholder="10.0.1.100 or sapecc.company.com" required
            helpText="SAP application server hostname or IP"
          />
          <Field label="System Number" value={eccSysnr} onChange={setEccSysnr}
            placeholder="00" required
            helpText="0-99, usually 00"
          />
          <Field label="Client" value={eccClient} onChange={setEccClient}
            placeholder="100" required
            helpText="SAP client number (100, 200, etc.)"
          />
          <Field label="User" value={eccUser} onChange={setEccUser}
            placeholder="SAPUSER" required
            helpText="RFC user with read access"
          />
          <Field label="Password" value={eccPass} onChange={setEccPass}
            type="password" placeholder="••••••••"
            helpText="Not stored — only used for connection test"
          />
          <Field label="SAP Router (optional)" value={eccRouter} onChange={setEccRouter}
            placeholder="/H/saprouter.company.com/S/3299/H/"
            helpText="Required if connecting through SAP Router"
          />
        </div>

        <StatusMessage result={eccResult} />

        <div className="flex items-center gap-3 mt-5">
          <button onClick={testEcc} disabled={eccTesting || !eccHost}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-accent-cyan/10 text-accent-cyan text-xs font-semibold
                       hover:bg-accent-cyan/20 transition-all border border-accent-cyan/20 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            {eccTesting ? <Loader2 size={14} className="animate-spin" /> : <TestTube size={14} />}
            Test Connection
          </button>
          <button onClick={saveEcc} disabled={eccSaving || !eccHost}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-accent-blue/10 text-accent-blue text-xs font-semibold
                       hover:bg-accent-blue/20 transition-all border border-accent-blue/20 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            {eccSaving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            Save
          </button>
        </div>
      </ConnectionCard>

      {/* S/4HANA Connection */}
      <ConnectionCard
        title="S/4HANA Target System"
        subtitle="Target system where migration will be executed"
        icon={Cloud}
        color="#10b981"
        status={s4Status}
      >
        {/* Connection type toggle */}
        <div className="mb-5">
          <label className="block text-xs text-white/40 mb-2">Connection Type</label>
          <div className="flex gap-2">
            {[
              { id: 'rfc', label: 'RFC (On-Premise)', icon: Server },
              { id: 'odata', label: 'OData (Cloud)', icon: Cloud },
            ].map((opt) => (
              <button key={opt.id} onClick={() => setS4Type(opt.id)}
                className={`flex items-center gap-2 px-4 py-2.5 rounded-lg text-xs font-medium transition-all
                  ${s4Type === opt.id
                    ? 'bg-accent-green/10 text-accent-green border border-accent-green/30'
                    : 'bg-white/[0.03] text-white/40 border border-white/[0.06] hover:bg-white/[0.05]'
                  }`}
              >
                <opt.icon size={14} /> {opt.label}
              </button>
            ))}
          </div>
        </div>

        {s4Type === 'rfc' ? (
          <div className="grid grid-cols-2 gap-4">
            <Field label="Application Server" value={s4Host} onChange={setS4Host}
              placeholder="10.0.2.100 or s4hana.company.com" required />
            <Field label="System Number" value={s4Sysnr} onChange={setS4Sysnr}
              placeholder="00" required />
            <Field label="Client" value={s4Client} onChange={setS4Client}
              placeholder="100" required />
            <Field label="User" value={s4User} onChange={setS4User}
              placeholder="SAPUSER" required
              helpText="Needs write access (transport, BAPI)"
            />
            <Field label="Password" value={s4Pass} onChange={setS4Pass}
              type="password" placeholder="••••••••" />
            <Field label="SAP Router (optional)" value={s4Router} onChange={setS4Router}
              placeholder="/H/saprouter/S/3299/H/" />
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <Field label="API Endpoint URL" value={s4ApiUrl} onChange={setS4ApiUrl}
                placeholder="https://mycompany.s4hana.cloud.sap/sap/opu/odata/sap/" required
                helpText="S/4HANA Cloud OData service base URL"
              />
            </div>
            <Field label="Host / Tenant" value={s4Host} onChange={setS4Host}
              placeholder="mycompany.s4hana.cloud.sap" required />
            <Field label="Communication User" value={s4User} onChange={setS4User}
              placeholder="COM_USER_001" required
              helpText="From Communication Arrangement in S/4HC"
            />
            <Field label="Password / Secret" value={s4Pass} onChange={setS4Pass}
              type="password" placeholder="••••••••" />
          </div>
        )}

        <StatusMessage result={s4Result} />

        <div className="flex items-center gap-3 mt-5">
          <button onClick={testS4} disabled={s4Testing || !s4Host}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-accent-cyan/10 text-accent-cyan text-xs font-semibold
                       hover:bg-accent-cyan/20 transition-all border border-accent-cyan/20 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            {s4Testing ? <Loader2 size={14} className="animate-spin" /> : <TestTube size={14} />}
            Test Connection
          </button>
          <button onClick={saveS4} disabled={s4Saving || !s4Host}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-accent-green/10 text-accent-green text-xs font-semibold
                       hover:bg-accent-green/20 transition-all border border-accent-green/20 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            {s4Saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            Save
          </button>
        </div>
      </ConnectionCard>

      {/* What happens next */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.3 }}
        className="glass rounded-2xl p-6"
      >
        <h3 className="text-sm font-semibold text-white/70 mb-4">What happens next?</h3>
        <div className="space-y-3">
          {[
            { step: '1', text: 'Configure & test your ECC connection above', icon: Server, color: '#3b82f6' },
            { step: '2', text: 'Go to Pipeline → click "Assess ECC System" (read-only, safe to run anytime)', icon: Database, color: '#06b6d4' },
            { step: '3', text: 'Review the assessment report — code issues, data volumes, risks', icon: AlertTriangle, color: '#f59e0b' },
            { step: '4', text: 'Configure S/4HANA target connection', icon: Cloud, color: '#10b981' },
            { step: '5', text: 'Go to Pipeline → click "Start Migration" when ready for cutover', icon: CheckCircle2, color: '#10b981' },
          ].map((s) => (
            <div key={s.step} className="flex items-center gap-3">
              <div className="w-7 h-7 rounded-lg flex items-center justify-center text-[10px] font-bold"
                style={{ backgroundColor: `${s.color}15`, color: s.color }}>
                {s.step}
              </div>
              <p className="text-xs text-white/50">{s.text}</p>
            </div>
          ))}
        </div>
      </motion.div>
    </div>
  );
}
