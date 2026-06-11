// Topbar client (tenant) picker. Click to swap the active client; every
// subsequent API request is auto-tagged with X-Client-Id by api.js.
import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, Users, Plus, CheckCircle2, Search, X } from 'lucide-react';
import { useActiveClient } from '../lib/activeClient.jsx';
import { Link } from 'react-router-dom';

const trim = (s, n = 18) => (!s ? '—' : (s.length > n ? `${s.slice(0, n - 1)}…` : s));

export default function ClientPicker() {
  const { activeClientId, setActiveClientId, clients, loading, refresh } = useActiveClient();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const rootRef = useRef(null);
  const inputRef = useRef(null);

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
    if (!q.trim()) return clients;
    const needle = q.toLowerCase();
    return clients.filter((c) => c.id.toLowerCase().includes(needle) || (c.name || '').toLowerCase().includes(needle));
  }, [clients, q]);

  const active = clients.find((c) => c.id === activeClientId);
  const isDefault = activeClientId === 'default';

  return (
    <div ref={rootRef} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="btn btn-sm"
        title="Active client (multi-tenant)"
        style={{ minWidth: 170, justifyContent: 'flex-start', gap: 6 }}
      >
        <Users size={12} className="text-ink-3 shrink-0" />
        <span className="text-[10.5px] text-ink-4 uppercase tracking-wider font-semibold shrink-0">client</span>
        <span className="font-mono text-[11.5px] text-ink-1 truncate" style={{ color: isDefault ? 'var(--ink-3)' : 'var(--ink-1)' }}>
          {trim(active?.name || activeClientId)}
        </span>
        <ChevronDown size={11} className="text-ink-4 ml-auto shrink-0" />
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-1.5 z-50 w-[360px] max-h-[70vh] flex flex-col rounded-md"
          style={{ background: 'var(--surface)', border: '1px solid var(--border)', boxShadow: 'var(--shadow-popup)' }}
        >
          <div className="flex items-center gap-2 px-3 py-2 border-b" style={{ borderColor: 'var(--border)' }}>
            <Search size={12} className="text-ink-4 shrink-0" />
            <input
              ref={inputRef}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Filter clients…"
              className="flex-1 bg-transparent outline-none text-[12px] text-ink-1"
            />
            {q && (
              <button onClick={() => setQ('')} className="btn btn-sm btn-ghost btn-icon">
                <X size={11} />
              </button>
            )}
            <button onClick={refresh} className="text-[10px] text-ink-3 hover:text-ink-1 font-medium">
              {loading ? 'loading…' : 'reload'}
            </button>
          </div>

          <div className="flex-1 overflow-y-auto py-1">
            {filtered.length === 0 ? (
              <div className="px-3 py-6 text-center text-[11.5px] text-ink-3">
                {clients.length === 0 ? 'No clients yet.' : 'No clients match.'}
              </div>
            ) : (
              filtered.map((c) => {
                const isActive = c.id === activeClientId;
                return (
                  <button
                    key={c.id}
                    onClick={() => { setActiveClientId(c.id); setOpen(false); }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[var(--surface-2)]"
                    style={{ background: isActive ? 'var(--surface-2)' : 'transparent' }}
                  >
                    <Users size={12} className="text-ink-3 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="text-[12px] text-ink-1 truncate">{c.name || c.id}</div>
                      <div className="font-mono text-[10.5px] text-ink-4 truncate">{c.id}</div>
                    </div>
                    {c.has_ecc_session && (
                      <span className="text-[9.5px] uppercase tracking-wider font-semibold" style={{ color: 'var(--ok)' }}>ECC ✓</span>
                    )}
                    {isActive && <CheckCircle2 size={12} style={{ color: 'var(--ok)' }} />}
                  </button>
                );
              })
            )}
          </div>

          <div className="px-3 py-1.5 border-t flex items-center justify-between gap-2" style={{ borderColor: 'var(--border)' }}>
            <Link to="/clients" onClick={() => setOpen(false)} className="btn btn-sm btn-ghost text-[11px]">
              <Plus size={11} /> Manage clients
            </Link>
            <span className="text-[10.5px] text-ink-4">scopes runs + connections</span>
          </div>
        </div>
      )}
    </div>
  );
}
