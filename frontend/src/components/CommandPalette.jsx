import { useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, ArrowRight, LayoutDashboard, GitBranch, FileText, ShieldCheck, Server, Terminal, GitCompareArrows, Activity, Database } from 'lucide-react';

// Cmd+K palette: fuzzy-jump to pages + (later) actions/runs.
// Keeps the action list extensible — pages can contribute via a future hook.
const ITEMS = [
  { kind: 'nav', to: '/',             title: 'Overview',     hint: 'Dashboard',  icon: LayoutDashboard },
  { kind: 'nav', to: '/pipeline',     title: 'Pipeline',     hint: '27-stage SFN', icon: GitBranch },
  { kind: 'nav', to: '/runs',         title: 'Runs',         hint: 'Execution history', icon: FileText },
  { kind: 'nav', to: '/gates',        title: 'Gates',        hint: 'Manual gate queue', icon: ShieldCheck },
  { kind: 'nav', to: '/data-quality', title: 'Data Quality', hint: 'Dirty-data SLO',    icon: Activity },
  { kind: 'nav', to: '/connections',  title: 'Connections',  hint: 'ECC + S/4 secrets', icon: Server },
  { kind: 'nav', to: '/versions',     title: 'Version Matrix', hint: 'Source/target pairs', icon: GitCompareArrows },
  { kind: 'nav', to: '/commands',     title: 'Command Center', hint: 'Terminal-equivalent actions', icon: Terminal },
  { kind: 'nav', to: '/tracker',      title: 'Project Tracker', hint: 'Migration status', icon: Database },
];

function score(s, q) {
  if (!q) return 1;
  s = s.toLowerCase(); q = q.toLowerCase();
  if (s.startsWith(q)) return 3;
  if (s.includes(q)) return 2;
  // letter-by-letter loose match
  let i = 0;
  for (const c of s) { if (c === q[i]) i++; if (i === q.length) return 1; }
  return 0;
}

export default function CommandPalette({ open, onClose, onNavigate }) {
  const [q, setQ] = useState('');
  const [idx, setIdx] = useState(0);
  const inputRef = useRef(null);

  useEffect(() => {
    if (open) { setQ(''); setIdx(0); setTimeout(() => inputRef.current?.focus(), 30); }
  }, [open]);

  const filtered = useMemo(() => {
    return ITEMS
      .map((it) => ({ ...it, _s: Math.max(score(it.title, q), score(it.hint || '', q) * 0.8) }))
      .filter((it) => it._s > 0)
      .sort((a, b) => b._s - a._s);
  }, [q]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key === 'Escape') onClose?.();
      else if (e.key === 'ArrowDown') { e.preventDefault(); setIdx((i) => Math.min(i + 1, filtered.length - 1)); }
      else if (e.key === 'ArrowUp')   { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)); }
      else if (e.key === 'Enter')     { e.preventDefault(); const it = filtered[idx]; if (it) onNavigate?.(it.to); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, filtered, idx, onClose, onNavigate]);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-40"
            style={{ background: 'rgba(0,0,0,0.30)', backdropFilter: 'blur(4px)' }}
            onClick={onClose}
          />
          <motion.div
            initial={{ opacity: 0, y: -8, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -8, scale: 0.98 }}
            transition={{ duration: 0.16, ease: [0.4, 0, 0.2, 1] }}
            className="fixed left-1/2 top-[14%] -translate-x-1/2 z-50 w-[560px] max-w-[92vw] panel-elev"
            style={{ boxShadow: 'var(--shadow-popup)' }}
          >
            <div className="flex items-center gap-2 px-3 py-2.5 border-b" style={{ borderColor: 'var(--border)' }}>
              <Search size={14} className="text-ink-4" />
              <input
                ref={inputRef}
                value={q}
                onChange={(e) => { setQ(e.target.value); setIdx(0); }}
                placeholder="Jump to a page, action, or run…"
                className="flex-1 bg-transparent outline-none text-sm text-ink-1 placeholder:text-ink-4"
              />
              <span className="kbd">esc</span>
            </div>
            <div className="max-h-[340px] overflow-y-auto py-1.5">
              {filtered.length === 0 ? (
                <div className="px-3 py-6 text-center text-xs text-ink-4">No matches</div>
              ) : filtered.map((it, i) => (
                <button
                  key={it.to + i}
                  onMouseEnter={() => setIdx(i)}
                  onClick={() => onNavigate?.(it.to)}
                  className={`w-full flex items-center gap-3 px-3 py-2 text-left ${i === idx ? 'bg-bg-elev' : ''}`}
                  style={i === idx ? { background: 'var(--bg-elev)' } : undefined}
                >
                  <div className="w-7 h-7 rounded flex items-center justify-center" style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}>
                    <it.icon size={14} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-[13px] text-ink-1 font-medium truncate">{it.title}</div>
                    {it.hint && <div className="text-[11px] text-ink-3 truncate">{it.hint}</div>}
                  </div>
                  {i === idx && <ArrowRight size={13} className="text-accent" />}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-3 px-3 py-1.5 border-t text-[10.5px] text-ink-3" style={{ borderColor: 'var(--border)' }}>
              <span className="kbd">↑↓</span> navigate
              <span className="kbd">↵</span> open
              <span className="ml-auto opacity-70">⌘K</span>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
