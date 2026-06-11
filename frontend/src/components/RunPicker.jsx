// Topbar run-picker dropdown. Shows the active run id (short form) and a
// chevron; click opens a panel listing recent runs with search + status pills.
// Selecting a run updates the global ActiveRun context (and triggers all
// pages to refetch via the m4h:active-run-changed event).
import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, FileText, Search, CheckCircle2, AlertTriangle, Circle, X } from 'lucide-react';
import { useActiveRun } from '../lib/activeRun.jsx';

const shortId = (id) => {
  if (!id) return '— no run —';
  // run_20260610_124235 → 20260610_124235; further trim to last 14 chars.
  const s = id.replace(/^run_/, '');
  return s.length > 16 ? `${s.slice(0, 14)}…` : s;
};

function statusTone(r) {
  const s = String(r?.status || '').toLowerCase();
  if (s === 'success' || s === 'succeeded' || s === 'completed' || s === 'ok') return 'ok';
  if (s === 'running' || s === 'in_progress') return 'info';
  if (s === 'failed' || s === 'error')        return 'err';
  // Older runs may not have status — infer from has_execution.
  return r?.has_execution ? 'ok' : 'muted';
}

function ToneDot({ tone }) {
  const color =
    tone === 'ok'   ? 'var(--ok)' :
    tone === 'info' ? 'var(--info)' :
    tone === 'err'  ? 'var(--err)' :
                      'var(--ink-4)';
  return <span className="w-1.5 h-1.5 rounded-full inline-block" style={{ background: color, boxShadow: `0 0 4px ${color}` }} />;
}

export default function RunPicker() {
  const { activeRunId, setActiveRunId, runs, loading, refresh } = useActiveRun();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const rootRef = useRef(null);
  const inputRef = useRef(null);

  // Close on outside-click + Escape.
  useEffect(() => {
    if (!open) return;
    const onDoc = (e) => { if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false); };
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    setTimeout(() => inputRef.current?.focus(), 30);
    return () => { document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onKey); };
  }, [open]);

  const filtered = useMemo(() => {
    if (!q.trim()) return runs;
    const needle = q.toLowerCase();
    return runs.filter((r) => (r.id || r.run_id || '').toLowerCase().includes(needle));
  }, [runs, q]);

  const active = runs.find((r) => (r.id || r.run_id) === activeRunId);
  const activeTone = active ? statusTone(active) : 'muted';

  return (
    <div ref={rootRef} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="btn btn-sm"
        title="Active migration run (click to switch)"
        style={{ minWidth: 180, justifyContent: 'flex-start', gap: 6 }}
      >
        <FileText size={12} className="text-ink-3 shrink-0" />
        <span className="text-[10.5px] text-ink-4 uppercase tracking-wider font-semibold shrink-0">run</span>
        <ToneDot tone={activeTone} />
        <span className="font-mono text-[11.5px] text-ink-1 truncate">{shortId(activeRunId)}</span>
        <ChevronDown size={11} className="text-ink-4 ml-auto shrink-0" />
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-1.5 z-50 w-[420px] max-h-[70vh] flex flex-col rounded-md"
          style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            boxShadow: 'var(--shadow-popup)',
          }}
        >
          <div className="flex items-center gap-2 px-3 py-2 border-b" style={{ borderColor: 'var(--border)' }}>
            <Search size={12} className="text-ink-4 shrink-0" />
            <input
              ref={inputRef}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Filter runs…"
              className="flex-1 bg-transparent outline-none text-[12px] text-ink-1"
            />
            {q && (
              <button onClick={() => setQ('')} className="btn btn-sm btn-ghost btn-icon" title="Clear">
                <X size={11} />
              </button>
            )}
            <button onClick={() => refresh()} className="text-[10px] text-ink-3 hover:text-ink-1 font-medium">
              {loading ? 'loading…' : 'reload'}
            </button>
          </div>

          <div className="flex-1 overflow-y-auto py-1">
            {filtered.length === 0 ? (
              <div className="px-3 py-6 text-center text-[11.5px] text-ink-3">
                {runs.length === 0 ? 'No runs on disk yet.' : 'No runs match the filter.'}
              </div>
            ) : (
              filtered.map((r) => {
                const id = r.id || r.run_id;
                const tone = statusTone(r);
                const isActive = id === activeRunId;
                return (
                  <button
                    key={id}
                    onClick={() => { setActiveRunId(id); setOpen(false); }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[var(--surface-2)]"
                    style={{ background: isActive ? 'var(--surface-2)' : 'transparent' }}
                  >
                    <ToneDot tone={tone} />
                    <div className="flex-1 min-w-0">
                      <div className="font-mono text-[11.5px] text-ink-1 truncate">{id}</div>
                      <div className="text-[10.5px] text-ink-3 truncate">
                        {r.timestamp ? `created ${r.timestamp}` : ''}
                        {r.has_execution ? ' · executed' : r.timestamp ? ' · assessment' : ''}
                      </div>
                    </div>
                    {isActive && <CheckCircle2 size={12} style={{ color: 'var(--ok)' }} />}
                  </button>
                );
              })
            )}
          </div>

          <div className="px-3 py-1.5 border-t text-[10.5px] text-ink-4 flex items-center justify-between" style={{ borderColor: 'var(--border)' }}>
            <span>{runs.length} run{runs.length === 1 ? '' : 's'}</span>
            <span>Selection applies to every page</span>
          </div>
        </div>
      )}
    </div>
  );
}
