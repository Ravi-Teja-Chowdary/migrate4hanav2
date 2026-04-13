import { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Server, Wifi, WifiOff, CheckCircle2, AlertTriangle,
  XCircle, Loader2, Save, TestTube, ChevronDown, ChevronUp,
  Shield, Database, Eye, EyeOff, Rocket, FileText, Download,
  Activity, Clock,
} from 'lucide-react';
import { apiFetch, getAuthUrl } from '../api';

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

const STATUS_COLORS = {
  SUCCESS: 'text-green-400',
  IN_PROGRESS: 'text-yellow-400',
  WARNING: 'text-amber-400',
  ERROR: 'text-red-400',
};

const STATUS_ICONS = {
  SUCCESS: CheckCircle2,
  IN_PROGRESS: Clock,
  WARNING: AlertTriangle,
  ERROR: XCircle,
};

function ProgressPanel({ steps, status, runId, pdfGenerated }) {
  const endRef = useRef(null);

  useEffect(() => {
    if (endRef.current) endRef.current.scrollIntoView({ behavior: 'smooth' });
  }, [steps]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass rounded-2xl overflow-hidden"
    >
      <div className="px-6 py-4 border-b border-white/[0.04] flex items-center gap-3">
        <Activity size={16} className="text-accent-cyan" />
        <h3 className="text-sm font-semibold text-white/80">Real-Time Progress</h3>
        <div className="ml-auto flex items-center gap-2">
          {status === 'running' && (
            <span className="flex items-center gap-1.5 text-xs text-accent-cyan">
              <span className="w-1.5 h-1.5 rounded-full bg-accent-cyan animate-pulse" />
              Running
            </span>
          )}
          {status === 'completed' && (
            <span className="flex items-center gap-1.5 text-xs text-accent-green">
              <CheckCircle2 size={12} /> Completed
            </span>
          )}
          {status === 'failed' && (
            <span className="flex items-center gap-1.5 text-xs text-accent-red">
              <XCircle size={12} /> Failed
            </span>
          )}
        </div>
      </div>
      <div className="max-h-80 overflow-y-auto p-4 space-y-1 font-mono text-xs">
        {steps.length === 0 ? (
          <div className="text-white/20 text-center py-8">Waiting for progress updates...</div>
        ) : (
          steps.map((step, i) => {
            const Icon = STATUS_ICONS[step.status] || Clock;
            const color = STATUS_COLORS[step.status] || 'text-white/40';
            return (
              <div key={step.event_id || i} className="flex items-start gap-3 py-1.5 border-b border-white/[0.02] last:border-0">
                <span className="text-white/20 shrink-0 w-16 text-right">
                  {step.timestamp?.split('T')[1]?.slice(0, 8) || ''}
                </span>
                <Icon size={12} className={`${color} mt-0.5 shrink-0`} />
                <span className={`${color} w-20 shrink-0 font-semibold uppercase text-[10px]`}>{step.status}</span>
                <span className="text-white/60 flex-1">{step.action}</span>
                {step.duration_ms != null && (
                  <span className="text-white/20 shrink-0">{(step.duration_ms / 1000).toFixed(1)}s</span>
                )}
              </div>
            );
          })
        )}
        <div ref={endRef} />
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

  // Run & Report state
  const [runState, setRunState] = useState('idle'); // idle | running | completed | failed
  const [runError, setRunError] = useState(null);
  const [progressSteps, setProgressSteps] = useState([]);
  const [runId, setRunId] = useState(null);
  const [pdfGenerated, setPdfGenerated] = useState(false);
  const [pdfUrl, setPdfUrl] = useState(null);
  const pollRef = useRef(null);
  const stepIndexRef = useRef(0);

  const isEccConnected = eccStatus === 'connected' || eccStatus === 'mock';

  // Load saved connections and check live readiness
  useEffect(() => {
    apiFetch('/api/connections')
      .then((r) => r.ok ? r.json() : Promise.reject(r.statusText))
      .then((data) => {
        if (data.ecc) {
          setEccHost(data.ecc.ashost || '');
          setEccSysnr(data.ecc.sysnr || '00');
          setEccClient(data.ecc.client || '100');
          setEccUser(data.ecc.user || '');
          setEccRouter(data.ecc.saprouter || '');
          // Check if password is still in server memory (survives page reload, not server restart)
          apiFetch('/api/connections/ecc/status')
            .then((r) => r.ok ? r.json() : Promise.reject(r.statusText))
            .then((status) => {
              if (status.live_ready) {
                setEccStatus('connected');
              } else {
                setEccStatus('saved');
              }
            })
            .catch(() => setEccStatus('saved'));
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

  // --- Run Conversion & Generate PDF ---
  const startRunAndReport = useCallback(async () => {
    setRunState('running');
    setRunError(null);
    setProgressSteps([]);
    setRunId(null);
    setPdfGenerated(false);
    setPdfUrl(null);
    stepIndexRef.current = 0;

    try {
      const r = await apiFetch('/api/pipeline/run_and_report', { method: 'POST' });
      const data = await r.json();
      if (data.error) {
        setRunError(data.error);
        setRunState('failed');
        return;
      }
      // Start polling for progress
      startProgressPolling();
    } catch {
      setRunError('Cannot reach API server. Start it with: python api_server.py');
      setRunState('failed');
    }
  }, []);

  function startProgressPolling() {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const r = await apiFetch(`/api/progress?since=${stepIndexRef.current}`);
        const data = await r.json();

        if (data.steps && data.steps.length > 0) {
          setProgressSteps(prev => [...prev, ...data.steps]);
          stepIndexRef.current = data.total_steps;
        }

        if (data.status === 'completed' || data.status === 'failed') {
          clearInterval(pollRef.current);
          pollRef.current = null;
          setRunState(data.status);
          if (data.run_id) setRunId(data.run_id);
          if (data.pdf_generated) {
            setPdfGenerated(true);
            const url = await getAuthUrl(`/api/runs/${data.run_id}/pdf`);
            setPdfUrl(url);
          }
        }
      } catch { /* keep polling */ }
    }, 1500);
  }

  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  const resetRun = () => {
    if (pollRef.current) clearInterval(pollRef.current);
    setRunState('idle');
    setRunError(null);
    setProgressSteps([]);
    setRunId(null);
    setPdfGenerated(false);
    setPdfUrl(null);
    stepIndexRef.current = 0;
  };

  return (
    <div className="p-8 max-w-3xl mx-auto space-y-6">
      <div>
        <motion.h1 initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }}
          className="text-3xl font-bold text-white">
          SAP ECC <span className="gradient-text">Connection</span>
        </motion.h1>
        <p className="text-sm text-white/40 mt-1">Configure your SAP ECC source system for live assessment</p>
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
            <b className="text-white/70">How it works:</b> Enter your SAP ECC connection details below.
            The tool connects via <b>RFC protocol</b> (PyRFC) to read your ECC system for migration assessment.
            Passwords are never stored on disk — they are only held in memory during the session.
          </p>
          <p className="text-[10px] text-white/25 mt-1">
            <b>Important:</b> Test the connection before running the pipeline. The password is passed securely to the pipeline process.
          </p>
        </div>
      </motion.div>

      {/* ECC Connection */}
      <ConnectionCard
        title="SAP ECC Source System"
        subtitle="RFC connection to your existing ECC system"
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
            helpText="Held in memory only — used for connection test & pipeline"
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

      {/* Run Conversion & Generate PDF — shown when ECC is connected */}
      <AnimatePresence>
        {isEccConnected && runState === 'idle' && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ delay: 0.2 }}
            className="glass rounded-2xl p-6 text-center relative overflow-hidden"
          >
            <div className="absolute inset-0 bg-gradient-to-br from-accent-blue/5 to-accent-green/5" />
            <div className="relative">
              <div className="w-14 h-14 mx-auto rounded-2xl bg-gradient-to-br from-accent-blue/20 to-accent-green/20 flex items-center justify-center mb-4">
                <Rocket size={28} className="text-accent-cyan" />
              </div>
              <h3 className="text-lg font-bold text-white">ECC System Connected</h3>
              <p className="text-xs text-white/40 mt-1 max-w-md mx-auto">
                Your SAP ECC system is ready. Click below to extract all data, run the full conversion analysis,
                and generate a comprehensive PDF report — all in one step.
              </p>
              <button
                onClick={startRunAndReport}
                className="mt-5 inline-flex items-center gap-2.5 px-6 py-3 rounded-xl bg-gradient-to-r from-accent-blue/20 to-accent-green/20
                           text-white text-sm font-bold hover:from-accent-blue/30 hover:to-accent-green/30
                           transition-all duration-300 border border-accent-cyan/20 animate-pulse-glow shadow-lg shadow-accent-cyan/10"
              >
                <Rocket size={16} /> Run Conversion & Generate PDF Report
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Running / Progress Panel */}
      <AnimatePresence>
        {runState !== 'idle' && (
          <ProgressPanel
            steps={progressSteps}
            status={runState}
            runId={runId}
            pdfGenerated={pdfGenerated}
          />
        )}
      </AnimatePresence>

      {/* Error banner */}
      <AnimatePresence>
        {runError && (
          <motion.div
            initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
            className="glass rounded-xl p-3 flex items-center gap-2 border border-accent-red/20"
          >
            <XCircle size={14} className="text-accent-red shrink-0" />
            <p className="text-xs text-accent-red flex-1">{runError}</p>
            <button onClick={resetRun} className="text-xs text-white/40 hover:text-white/60 px-2 py-1 rounded-lg bg-white/5">
              Dismiss
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Completion panel with PDF download */}
      <AnimatePresence>
        {runState === 'completed' && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="glass rounded-2xl p-8 text-center relative overflow-hidden"
          >
            <div className="absolute inset-0 bg-gradient-to-br from-accent-green/5 to-accent-blue/5" />
            <div className="relative">
              <motion.div
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ type: 'spring', stiffness: 200, delay: 0.2 }}
                className="w-16 h-16 mx-auto rounded-2xl bg-accent-green/10 flex items-center justify-center mb-4"
              >
                <CheckCircle2 size={32} className="text-accent-green" />
              </motion.div>
              <h3 className="text-xl font-bold text-white">Conversion Complete!</h3>
              <p className="text-sm text-white/40 mt-1">
                All ECC data has been extracted, converted, and analyzed successfully.
              </p>
              <div className="flex items-center justify-center gap-3 mt-5">
                <button
                  onClick={async () => {
                    const url = pdfUrl || await getAuthUrl(`/api/runs/${runId || 'latest'}/pdf`);
                    window.open(url, '_blank');
                  }}
                  className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-gradient-to-r from-accent-green/20 to-accent-cyan/20
                             text-white text-sm font-bold hover:from-accent-green/30 hover:to-accent-cyan/30
                             transition-all duration-300 border border-accent-green/30 animate-pulse-glow shadow-lg shadow-accent-green/10"
                >
                  <Download size={16} /> Download PDF Report
                </button>
                <button
                  onClick={resetRun}
                  className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white/5 text-white/60 text-sm font-medium
                             hover:bg-white/10 transition-all border border-white/10"
                >
                  Run Again
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* What happens next — only shown when NOT connected */}
      {!isEccConnected && runState === 'idle' && (
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
              { step: '2', text: 'Save the connection — password stays in memory for the pipeline', icon: Database, color: '#06b6d4' },
              { step: '3', text: 'Once connected, click "Run Conversion & Generate PDF Report"', icon: Rocket, color: '#f59e0b' },
              { step: '4', text: 'Download the comprehensive migration assessment PDF', icon: FileText, color: '#10b981' },
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
      )}
    </div>
  );
}
