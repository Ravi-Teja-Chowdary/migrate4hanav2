import { useEffect, useState } from 'react';
import { Outlet, NavLink, useLocation, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  LayoutDashboard, GitBranch, FileText, ShieldCheck, Server, Terminal, GitCompareArrows,
  Boxes, Sun, Moon, Command, Search, Activity, Database,
} from 'lucide-react';
import { ping } from '../lib/api';
import { useTheme } from '../lib/theme';
import { RefreshControl, TimeRangePicker } from './dd';
import CommandPalette from './CommandPalette';

// Compact icon rail — Datadog vibe (no labels, hover-tooltip).
const RAIL = [
  { to: '/',            label: 'Overview',     icon: LayoutDashboard, end: true },
  { to: '/pipeline',    label: 'Pipeline',     icon: GitBranch },
  { to: '/runs',        label: 'Runs',         icon: FileText },
  { to: '/gates',       label: 'Gates',        icon: ShieldCheck },
  { to: '/data-quality', label: 'Data Quality', icon: Activity },
  { to: '/connections', label: 'Connections',  icon: Server },
  { to: '/versions',    label: 'Versions',     icon: GitCompareArrows },
  { to: '/commands',    label: 'Commands',     icon: Terminal },
  { to: '/tracker',     label: 'Tracker',      icon: Database },
];

function RailItem({ to, label, icon: Icon, end }) {
  return (
    <NavLink to={to} end={end} className={({ isActive }) => `rail-item focusable ${isActive ? 'active' : ''}`} title={label}>
      <Icon size={18} />
    </NavLink>
  );
}

function HealthDot() {
  const [h, setH] = useState(undefined);
  useEffect(() => {
    let alive = true;
    const check = async () => { const r = await ping(); if (alive) setH(r); };
    check();
    const t = setInterval(check, 8000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  const online = !!h;
  return (
    <div className="flex items-center gap-1.5">
      <span className={`w-1.5 h-1.5 rounded-full ${online ? 'bg-emerald-500' : 'bg-amber-500'}`} style={{
        background: online ? 'var(--ok)' : 'var(--warn)',
        boxShadow: online ? '0 0 6px var(--ok)' : '0 0 6px var(--warn)',
      }} />
      <span className="text-[10.5px] text-ink-3 font-medium">
        {h === undefined ? 'checking' : online ? 'API live' : 'API offline'}
      </span>
    </div>
  );
}

function EnvChip({ label, value, tone = 'info' }) {
  return (
    <div className="flex items-center gap-1.5 text-[11px]">
      <span className="text-ink-4 uppercase tracking-wider font-semibold">{label}</span>
      <span className={`pill pill-${tone === 'info' ? 'info' : tone}`}>{value}</span>
    </div>
  );
}

export default function Shell() {
  const location = useLocation();
  const navigate = useNavigate();
  const { theme, toggle } = useTheme();
  const [refreshMs, setRefreshMs] = useState(0);
  const [range, setRange] = useState('24h');
  const [paletteOpen, setPaletteOpen] = useState(false);

  // Cmd+K / Ctrl+K opens the palette.
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // Page-level refresh: dispatches a CustomEvent that page hooks listen for.
  const triggerRefresh = () => window.dispatchEvent(new CustomEvent('m4h:refresh', { detail: { ts: Date.now() } }));

  return (
    <div className="min-h-screen flex" style={{ background: 'var(--bg)' }}>
      {/* Icon rail */}
      <aside
        className="w-[56px] shrink-0 flex flex-col items-center py-3 gap-1.5 border-r"
        style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
      >
        <div className="w-9 h-9 rounded-lg flex items-center justify-center mb-2"
             style={{ background: 'var(--accent)', color: '#fff' }}>
          <Boxes size={17} />
        </div>
        <div className="divider-h w-7 mb-1.5" />
        {RAIL.map((r) => <RailItem key={r.to} {...r} />)}
      </aside>

      <div className="flex-1 min-w-0 flex flex-col">
        {/* Topbar */}
        <header
          className="h-12 sticky top-0 z-20 flex items-center gap-3 px-5 border-b"
          style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
        >
          {/* Breadcrumb */}
          <Breadcrumb path={location.pathname} />

          <div className="ml-auto flex items-center gap-2.5">
            <EnvChip label="src" value="ECC · Y01" tone="info" />
            <span className="text-ink-4 text-xs">→</span>
            <EnvChip label="tgt" value="S4H · S4H" tone="ok" />
            <div className="divider-v h-5 mx-1" />
            <TimeRangePicker value={range} onChange={setRange} />
            <RefreshControl value={refreshMs} onChange={setRefreshMs} onRefresh={triggerRefresh} />
            <button className="btn btn-sm btn-ghost btn-icon" onClick={() => setPaletteOpen(true)} title="Command palette (⌘K)">
              <Command size={13} />
            </button>
            <button className="btn btn-sm btn-ghost btn-icon" onClick={toggle} title={theme === 'dark' ? 'Switch to light' : 'Switch to dark'}>
              {theme === 'dark' ? <Sun size={13} /> : <Moon size={13} />}
            </button>
            <div className="divider-v h-5 mx-1" />
            <HealthDot />
          </div>
        </header>

        {/* Main */}
        <main className="flex-1 overflow-y-auto">
          <AnimatePresence mode="wait">
            <motion.div
              key={location.pathname}
              initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.18, ease: [0.4, 0, 0.2, 1] }}
              className="px-6 py-5 max-w-[1480px] mx-auto"
            >
              <Outlet context={{ range, refreshMs, triggerRefresh }} />
            </motion.div>
          </AnimatePresence>
        </main>
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} onNavigate={(to) => { navigate(to); setPaletteOpen(false); }} />
    </div>
  );
}

function Breadcrumb({ path }) {
  const item = (RAIL.find((r) => path === r.to || (r.to !== '/' && path.startsWith(r.to))) || RAIL[0]);
  return (
    <div className="flex items-center gap-2 text-[12px] text-ink-3">
      <span className="text-ink-4">migrate4hana</span>
      <span className="text-ink-4">/</span>
      <span className="text-ink-1 font-semibold">{item.label}</span>
    </div>
  );
}
