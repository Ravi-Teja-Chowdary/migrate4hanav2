import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity, AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, Clock,
  Code2, Database, FileText, FlaskConical, GitBranch, Layers, Play,
  Server, Terminal, X, Zap,
} from 'lucide-react';
import { api } from '../lib/api';
import { useApi } from '../lib/useApi';
import { useToast } from '../lib/toast.jsx';
import { Panel, PageHeader, MetricTile, SearchBox, StatusPill, EmptyState, Spinner } from '../components/dd';

const CATEGORY_META = {
  pipeline:    { title: 'Pipeline',      icon: GitBranch,    accent: 'indigo' },
  spine:       { title: 'Master Spine',  icon: Layers,       accent: 'violet' },
  diagnostics: { title: 'Diagnostics',   icon: Activity,     accent: 'sky' },
  reports:     { title: 'Reports & PDF', icon: FileText,     accent: 'indigo' },
  stress:      { title: 'Stress / DQ',   icon: FlaskConical, accent: 'rose' },
  other:       { title: 'Other',         icon: Terminal,     accent: 'slate' },
};

// ─────────────────────────────────────────────────────────────
// Parameter form rendered inside each script row
// ─────────────────────────────────────────────────────────────
function ParamForm({ params, values, onChange }) {
  if (!params || params.length === 0) return null;
  return (
    <div className="grid grid-cols-2 gap-3 mb-3">
      {params.map((p) => (
        <div key={p.name} className={p.cols === 2 ? 'col-span-2' : ''}>
          <label className="metric-label flex items-center gap-1">
            {p.label || p.name}
            {p.required && <span style={{ color: 'var(--err)' }}>*</span>}
          </label>
          <input
            type={p.type === 'password' ? 'password' : 'text'}
            value={values[p.name] ?? p.default ?? ''}
            onChange={(e) => onChange(p.name, e.target.value)}
            placeholder={p.placeholder || ''}
            className="input w-full mt-1.5 font-mono"
          />
        </div>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Output console — shows stdout/stderr/exit code for a job
// ─────────────────────────────────────────────────────────────
function OutputConsole({ job, onClose }) {
  if (!job) return null;
  const statusTone =
    job.status === 'completed' ? 'ok' :
    job.status === 'running'   ? 'info' :
    job.status === 'failed' || job.status === 'error' || job.status === 'timeout' ? 'err' :
    'muted';
  return (
    <div className="mt-3 panel" style={{ borderColor: 'var(--border)' }}>
      <div className="panel-header">
        <Terminal size={13} className="text-ink-3 shrink-0" />
        <div className="flex-1 min-w-0">
          <span className="text-ink-2 font-semibold">Output</span>
          <span className="ml-2 text-[10.5px] font-mono text-ink-4">job {job.job_id}</span>
        </div>
        <StatusPill tone={statusTone}>{job.status}</StatusPill>
        {job.returncode != null && (
          <span className="text-[10.5px] font-mono text-ink-4">exit {job.returncode}</span>
        )}
        <button onClick={onClose} className="btn btn-sm btn-ghost btn-icon"><X size={12} /></button>
      </div>
      <div className="panel-body-flush">
        {job.stdout && (
          <pre className="code-block max-h-[280px] overflow-auto text-[11.5px] leading-relaxed m-0" style={{ borderRadius: 0 }}>
{job.stdout}
          </pre>
        )}
        {job.stderr && (
          <pre className="code-block max-h-[140px] overflow-auto text-[11.5px] leading-relaxed m-0"
               style={{ borderRadius: 0, background: '#3f1d23', color: '#fecaca' }}>
{job.stderr}
          </pre>
        )}
        {!job.stdout && !job.stderr && (
          <div className="px-4 py-6 text-center text-[11.5px] text-ink-3 flex items-center justify-center gap-2">
            {job.status === 'running' ? <><Spinner size={12} /> Running…</> : 'No output captured'}
          </div>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Script row — toggle expand to show description + form + Run
// ─────────────────────────────────────────────────────────────
function ScriptRow({ script, onRun, busy, job, onClearJob }) {
  const toast = useToast();
  const [expanded, setExpanded] = useState(false);
  const [values, setValues] = useState({});

  const update = (k, v) => setValues((cur) => ({ ...cur, [k]: v }));

  const handleRun = async () => {
    // Validate required params first
    const missing = (script.params || []).filter((p) => p.required && !(values[p.name] ?? p.default)?.toString().trim());
    if (missing.length > 0) {
      toast.warn('Missing parameters', `Required: ${missing.map((p) => p.label || p.name).join(', ')}`);
      setExpanded(true);
      return;
    }
    const merged = {};
    (script.params || []).forEach((p) => {
      merged[p.name] = values[p.name] ?? p.default ?? '';
    });
    setExpanded(true); // open so user sees the output
    onRun(script.id, merged);
  };

  return (
    <div className="border-t first:border-t-0" style={{ borderColor: 'var(--border)' }}>
      <div className="flex items-center gap-3 px-3.5 py-2.5">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-[12.5px] font-semibold text-ink-1">{script.title}</span>
            {script.params?.length > 0 && <StatusPill tone="muted" dot={false}>{script.params.length} param{script.params.length > 1 ? 's' : ''}</StatusPill>}
            {script.max_seconds >= 600 && <StatusPill tone="warn" dot={false}>long-running</StatusPill>}
          </div>
          <p className="text-[11.5px] text-ink-3 mt-0.5">{script.description}</p>
        </div>
        <button onClick={() => setExpanded((e) => !e)} className="btn btn-sm btn-ghost btn-icon" title={expanded ? 'Collapse' : 'Expand'}>
          {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        </button>
        <button onClick={handleRun} disabled={busy === script.id} className="btn btn-sm btn-primary">
          {busy === script.id ? <Spinner size={12} /> : <Play size={12} />} Run
        </button>
      </div>

      {expanded && (
        <div className="px-3.5 pb-3">
          {script.params?.length > 0 && (
            <ParamForm params={script.params} values={values} onChange={update} />
          )}
          {!script.params?.length && !job && (
            <p className="text-[11px] text-ink-4 italic">No parameters. Click Run to execute server-side.</p>
          )}
          {job && <OutputConsole job={job} onClose={() => onClearJob(script.id)} />}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// CommandCenter — main page
// ─────────────────────────────────────────────────────────────
export default function CommandCenter() {
  const toast = useToast();
  const { data, error, loading, reload } = useApi(useCallback(() => api.scriptList(), []));
  const [q, setQ] = useState('');
  const [activeCat, setActiveCat] = useState('all');
  const [busy, setBusy] = useState(null); // script_id currently running
  const [jobs, setJobs] = useState({});   // script_id → job state

  // Poll any running jobs every 1.5s
  useEffect(() => {
    const running = Object.entries(jobs).filter(([, j]) => j?.status === 'running');
    if (running.length === 0) return;
    const t = setInterval(async () => {
      for (const [sid, j] of running) {
        try {
          const fresh = await api.scriptOutput(j.job_id);
          setJobs((cur) => ({ ...cur, [sid]: fresh }));
          if (fresh.status !== 'running' && busy === sid) {
            setBusy(null);
            if (fresh.status === 'completed') toast.success(`${sid} completed`, `exit ${fresh.returncode}`);
            else if (fresh.status === 'timeout') toast.error(`${sid} timed out`, '');
            else toast.error(`${sid} failed`, fresh.stderr?.slice(0, 80) || `exit ${fresh.returncode}`);
          }
        } catch (e) { /* swallow, retry next tick */ }
      }
    }, 1500);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobs, busy]);

  const runScript = async (sid, params) => {
    setBusy(sid);
    toast.info(`Starting ${sid}…`);
    try {
      const r = await api.scriptRun(sid, params);
      setJobs((cur) => ({ ...cur, [sid]: { ...r, stdout: '', stderr: '' } }));
    } catch (e) {
      toast.error('Could not start script', e.message);
      setBusy(null);
    }
  };

  const clearJob = (sid) => setJobs((cur) => { const c = { ...cur }; delete c[sid]; return c; });

  const scripts = data?.scripts || [];
  const filtered = useMemo(() => {
    const term = q.toLowerCase().trim();
    return scripts.filter((s) => {
      if (activeCat !== 'all' && (s.category || 'other') !== activeCat) return false;
      if (!term) return true;
      return (
        s.title.toLowerCase().includes(term) ||
        s.description.toLowerCase().includes(term) ||
        (s.id || '').toLowerCase().includes(term)
      );
    });
  }, [scripts, q, activeCat]);

  const byCategory = useMemo(() => {
    const out = {};
    for (const s of filtered) {
      const cat = s.category || 'other';
      (out[cat] = out[cat] || []).push(s);
    }
    return out;
  }, [filtered]);

  const totalCount = scripts.length;
  const catCounts = useMemo(() => {
    const out = {};
    for (const s of scripts) {
      const cat = s.category || 'other';
      out[cat] = (out[cat] || 0) + 1;
    }
    return out;
  }, [scripts]);

  if (loading) return <div className="flex items-center gap-2 text-xs text-ink-3 py-20 justify-center"><Spinner /> Loading commands…</div>;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Command Center"
        breadcrumb={['Migrate4HANA', 'Commands']}
        subtitle={`${totalCount} server-side scripts you can run directly from the UI. Click Run on any row.`}
        actions={<SearchBox value={q} onChange={setQ} placeholder="Search commands…" />}
      />

      {error && (
        <Panel>
          <div className="flex items-start gap-2">
            <AlertTriangle size={14} className="shrink-0 mt-0.5" style={{ color: 'var(--err)' }} />
            <div>
              <div className="text-[13px] font-semibold text-ink-1">Could not load command list</div>
              <p className="text-[11.5px] text-ink-3 mt-0.5">{error.message}</p>
              <button className="btn btn-sm mt-2" onClick={reload}>Retry</button>
            </div>
          </div>
        </Panel>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <MetricTile label="Total commands" value={totalCount} sub={`${Object.keys(catCounts).length} categories`} />
        <MetricTile label="Currently running" value={Object.values(jobs).filter((j) => j?.status === 'running').length} sub={busy ? 'one in progress' : 'idle'} tone={busy ? 'info' : null} />
        <MetricTile label="Completed (session)" value={Object.values(jobs).filter((j) => j?.status === 'completed').length} sub="this browser session" />
        <MetricTile label="Failed (session)" value={Object.values(jobs).filter((j) => j?.status === 'failed' || j?.status === 'error' || j?.status === 'timeout').length} sub="this browser session" tone={Object.values(jobs).some((j) => j?.status !== 'running' && j?.status !== 'completed') ? 'warn' : null} />
      </div>

      {/* Category chips */}
      <Panel title="Categories" icon={Terminal} flush>
        <div className="flex flex-wrap gap-1.5 p-3">
          <button onClick={() => setActiveCat('all')} className={`btn btn-sm ${activeCat === 'all' ? 'btn-primary' : ''}`}>
            All <span className="text-[10px] opacity-70 ml-1">{totalCount}</span>
          </button>
          {Object.entries(catCounts).map(([cat, n]) => {
            const meta = CATEGORY_META[cat] || CATEGORY_META.other;
            const Icon = meta.icon;
            return (
              <button key={cat} onClick={() => setActiveCat(activeCat === cat ? 'all' : cat)}
                      className={`btn btn-sm ${activeCat === cat ? 'btn-primary' : ''}`}>
                <Icon size={12} /> {meta.title} <span className="text-[10px] opacity-70 ml-1">{n}</span>
              </button>
            );
          })}
        </div>
      </Panel>

      {filtered.length === 0 ? (
        <Panel><EmptyState icon={Terminal} title="No commands match" hint="Adjust the search or pick a different category." /></Panel>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
          {Object.entries(byCategory).map(([cat, list]) => {
            const meta = CATEGORY_META[cat] || CATEGORY_META.other;
            const Icon = meta.icon;
            return (
              <Panel key={cat} title={meta.title} icon={Icon} actions={<StatusPill tone="muted" dot={false}>{list.length}</StatusPill>} flush>
                {list.map((s) => (
                  <ScriptRow
                    key={s.id}
                    script={s}
                    onRun={runScript}
                    onClearJob={clearJob}
                    busy={busy}
                    job={jobs[s.id]}
                  />
                ))}
              </Panel>
            );
          })}
        </div>
      )}

      <Panel title="How this works" icon={Activity}>
        <ul className="text-[12px] text-ink-2 space-y-1.5 leading-relaxed list-disc list-inside">
          <li>Every command above maps to a whitelisted script in <span className="font-mono text-accent">api_server.py</span>. Arbitrary shell exec is never permitted.</li>
          <li>Required parameters are validated server-side. Missing params are rejected with HTTP 400.</li>
          <li>Long-running commands (assess, full pipeline, spine) run in a background thread. Poll output via <span className="font-mono text-accent">/api/scripts/output/{'{'}{'job_id'}{'}'}</span>.</li>
          <li>Each job is capped by a max-seconds timeout per script (15s for list-stages, up to 2h for full pipeline).</li>
          <li>Output is captured (last 50 KB stdout, 20 KB stderr) and returned in the console panel.</li>
        </ul>
      </Panel>
    </div>
  );
}
