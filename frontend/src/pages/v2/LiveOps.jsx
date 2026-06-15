// Live ops view (opened in a new tab from the Project page).
// Shows real-time logs + step events as they stream. Auto-scrolls.
import React, { useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { api } from '../../lib/api';

export default function LiveOps() {
  const { runId } = useParams();
  const [source, setSource] = useState('sfn');
  const [sources, setSources] = useState(['sfn']);
  const [events, setEvents] = useState([]);
  const [steps, setSteps] = useState([]);
  const [paused, setPaused] = useState(false);
  const [filter, setFilter] = useState('');
  const tailEnd = useRef(null);

  useEffect(() => {
    api.logSources().then((d) => setSources(d.sources || ['sfn'])).catch(() => {});
  }, []);

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
        setEvents((cur) => {
          const ids = new Set(cur.map((e) => e.timestamp + '|' + e.message?.slice(0, 60)));
          const fresh = (logs.events || []).filter(
            (e) => !ids.has(e.timestamp + '|' + (e.message || '').slice(0, 60)));
          const next = [...cur, ...fresh];
          // keep last 2000 lines
          return next.length > 2000 ? next.slice(next.length - 2000) : next;
        });
        setSteps(prog.steps || []);
      } catch { /* network blip */ }
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

      <div className="grid grid-cols-1 md:grid-cols-[1fr_280px] gap-0 h-[calc(100vh-49px)]">
        <div className="overflow-y-auto p-4 font-mono text-xs leading-relaxed">
          {events.length === 0 ? (
            <div className="text-slate-500">Waiting for log events…</div>
          ) : (
            <pre className="whitespace-pre-wrap break-words">
              {events.map((e, i) => (
                <div key={i} className={severityClass(e.level || e.message)}>
                  <span className="text-slate-500">
                    {e.timestamp?.slice(0, 19) || ''}
                  </span>{'  '}
                  <span>{e.message}</span>
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
                <li key={i} className="text-xs">
                  <span className={`inline-block w-2 h-2 rounded-full mr-2 ${
                    s.status === 'complete' || s.status === 'ok' ? 'bg-emerald-500'
                    : s.status === 'failed'                       ? 'bg-red-500'
                    : s.status === 'running'                      ? 'bg-blue-500 animate-pulse'
                    : 'bg-slate-500'
                  }`} />
                  <span className="font-mono">{s.step}</span>
                  <span className="text-slate-500"> · {s.status}</span>
                </li>
              ))}
            </ul>
          )}
        </aside>
      </div>
    </div>
  );
}

function severityClass(s) {
  const t = String(s || '').toUpperCase();
  if (t.includes('ERROR') || t.includes('CRITICAL') || t.includes('FAIL')) return 'text-red-400';
  if (t.includes('WARN'))                                                  return 'text-amber-300';
  if (t.includes('SUCCESS') || t.includes('DONE'))                          return 'text-emerald-300';
  return 'text-slate-300';
}
