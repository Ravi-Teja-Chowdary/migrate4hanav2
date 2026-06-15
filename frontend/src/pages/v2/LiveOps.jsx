// Live ops view (opened in a new tab from the Project page).
// Shows real-time logs + step events as they stream. Auto-scrolls.
//
// Backend shape (from /api/logs/tail): {events: [{ts:int_ms, msg, src, id}], next_token}
// Backend shape (from /api/progress): {steps: [{event_id, timestamp, ts, stage, action,
//                                                 step, message, status, details, duration_ms}]}
import React, { useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { api } from '../../lib/api';
import ErrorBoundary from '../../components/v2/ErrorBoundary';

export default function LiveOpsWrapper() {
  const { runId } = useParams();
  return (
    <ErrorBoundary>
      <LiveOps runId={runId} />
    </ErrorBoundary>
  );
}

function LiveOps({ runId }) {
  // Default to the "local" source — always works, no CloudWatch required.
  // If the sources endpoint returns CloudWatch groups we'll keep the user
  // on local until they explicitly switch.
  const [source, setSource] = useState('local');
  const [sources, setSources] = useState(['local']);
  const [events, setEvents] = useState([]);
  const [steps, setSteps] = useState([]);
  const [paused, setPaused] = useState(false);
  const [filter, setFilter] = useState('');
  const [err, setErr] = useState('');
  const tailEnd = useRef(null);

  // Load available log sources (CloudWatch groups + local fallback).
  useEffect(() => {
    let cancelled = false;
    api.logSources()
      .then((d) => {
        if (cancelled) return;
        const list = (d.sources || []).map((s) =>
          typeof s === 'string' ? s : (s.key || s.name || 'local'));
        setSources(list.length ? list : ['local']);
      })
      .catch(() => { /* default 'local' is fine */ });
    return () => { cancelled = true; };
  }, []);

  // Poll logs + progress. EVERY shape access is defensive; we never let a
  // missing field crash the page (that was the root cause of the blank page).
  useEffect(() => {
    let cancelled = false;
    let timer = null;
    async function poll() {
      try {
        const [logs, prog] = await Promise.all([
          api.logTail({ source, run_id: runId, limit: 200, q: filter || undefined }),
          api.progress(0),
        ]);
        if (cancelled) return;
        const incoming = Array.isArray(logs?.events) ? logs.events : [];
        setEvents((cur) => {
          // Dedup on a stable key. The backend returns id (CloudWatch event
          // id) when available; fall back to ts + msg prefix otherwise.
          const idOf = (e) =>
            e.id || `${e.ts || 0}|${String(e.msg || '').slice(0, 60)}`;
          const seen = new Set(cur.map(idOf));
          const fresh = incoming.filter((e) => !seen.has(idOf(e)));
          const next = [...cur, ...fresh];
          return next.length > 2000 ? next.slice(next.length - 2000) : next;
        });
        const incomingSteps = Array.isArray(prog?.steps) ? prog.steps : [];
        setSteps(incomingSteps);
        if (logs?.error) setErr(`logs source error: ${logs.error}`);
        else setErr('');
      } catch (e) {
        if (!cancelled) setErr(e?.message || String(e));
      }
      if (!cancelled && !paused) timer = setTimeout(poll, 2000);
    }
    if (!paused) poll();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [source, runId, paused, filter]);

  useEffect(() => {
    if (!paused) tailEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [events.length, paused]);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 px-4 py-3 flex items-center gap-4 flex-wrap">
        <div className="font-semibold">Live ops</div>
        <div className="text-xs text-slate-400">{runId}</div>
        <select
          value={source} onChange={(e) => setSource(e.target.value)}
          className="text-xs bg-slate-800 border border-slate-700 rounded px-2 py-1"
        >
          {sources.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <input
          value={filter} onChange={(e) => setFilter(e.target.value)}
          placeholder="filter (regex)"
          className="text-xs bg-slate-800 border border-slate-700 rounded px-2 py-1 w-48"
        />
        <button
          onClick={() => setPaused((p) => !p)}
          className={`text-xs px-3 py-1 rounded ${
            paused ? 'bg-emerald-700 hover:bg-emerald-600' : 'bg-slate-700 hover:bg-slate-600'
          }`}
        >
          {paused ? 'Resume' : 'Pause'}
        </button>
        <button
          onClick={() => setEvents([])}
          className="text-xs px-3 py-1 rounded bg-slate-700 hover:bg-slate-600"
        >
          Clear
        </button>
        <div className="ml-auto text-xs text-slate-400">
          {events.length} log lines · {steps.length} step events
        </div>
      </header>

      {err && (
        <div className="bg-red-900/40 border-b border-red-800 px-4 py-2 text-xs text-red-200">
          {err}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-[1fr_280px] gap-0 h-[calc(100vh-49px)]">
        <div className="overflow-y-auto p-4 font-mono text-xs leading-relaxed">
          {events.length === 0 ? (
            <div className="text-slate-500">
              Waiting for log events… (source: {source}; run: {runId})
            </div>
          ) : (
            <pre className="whitespace-pre-wrap break-words">
              {events.map((e, i) => (
                <div key={`${e.id || i}`} className={severityClass(e.msg)}>
                  <span className="text-slate-500">{formatTs(e.ts)}</span>{'  '}
                  <span>{e.msg || ''}</span>
                </div>
              ))}
              <div ref={tailEnd} />
            </pre>
          )}
        </div>
        <aside className="border-l border-slate-800 overflow-y-auto p-3 bg-slate-900">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-2">
            Pipeline steps
          </div>
          {steps.length === 0 ? (
            <div className="text-xs text-slate-500">No step events yet.</div>
          ) : (
            <ul className="space-y-1">
              {steps.slice(-30).map((s, i) => (
                <li key={s.event_id || i} className="text-xs">
                  <span className={`inline-block w-2 h-2 rounded-full mr-2 ${
                    statusColor(s.status)
                  }`} />
                  <span className="font-mono">{s.step || s.stage || '(step)'}</span>
                  <span className="text-slate-500"> · {s.status || ''}</span>
                </li>
              ))}
            </ul>
          )}
        </aside>
      </div>
    </div>
  );
}

function severityClass(msg) {
  const t = String(msg || '').toUpperCase();
  if (t.includes('ERROR') || t.includes('CRITICAL') || t.includes('FAIL')) return 'text-red-400';
  if (t.includes('WARN'))                                                  return 'text-amber-300';
  if (t.includes('SUCCESS') || t.includes('DONE') || t.includes(' OK ')) return 'text-emerald-300';
  return 'text-slate-300';
}

function formatTs(ts) {
  if (!ts) return '';
  // ts may be epoch-ms (number) or an ISO string. Handle both.
  if (typeof ts === 'number') {
    try { return new Date(ts).toISOString().slice(0, 19); } catch { return ''; }
  }
  return String(ts).slice(0, 19);
}

function statusColor(status) {
  const s = String(status || '').toUpperCase();
  if (s === 'COMPLETE' || s === 'OK' || s === 'SUCCESS')   return 'bg-emerald-500';
  if (s === 'FAILED'   || s === 'ERROR')                    return 'bg-red-500';
  if (s === 'IN_PROGRESS' || s === 'RUNNING')               return 'bg-blue-500 animate-pulse';
  return 'bg-slate-500';
}
