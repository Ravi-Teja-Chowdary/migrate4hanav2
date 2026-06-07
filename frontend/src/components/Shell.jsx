import { useEffect, useState } from 'react';
import { Outlet, NavLink, useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  LayoutDashboard, Server, GitBranch, KanbanSquare, ShieldCheck, FileText,
  TerminalSquare, Boxes, ArrowRight, Circle, GitCompareArrows,
} from 'lucide-react';
import { ping } from '../lib/api';

const NAV = [
  {
    group: 'Overview',
    items: [
      { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
      { to: '/tracker', label: 'Project Tracker', icon: KanbanSquare },
    ],
  },
  {
    group: 'Setup',
    items: [
      { to: '/connections', label: 'Connections', icon: Server },
      { to: '/versions', label: 'Version Matrix', icon: GitCompareArrows },
    ],
  },
  {
    group: 'Execute',
    items: [
      { to: '/pipeline', label: 'Migration Pipeline', icon: GitBranch },
    ],
  },
  {
    group: 'Govern',
    items: [{ to: '/gates', label: 'Approval Gates', icon: ShieldCheck }],
  },
  {
    group: 'Results',
    items: [{ to: '/runs', label: 'Runs & Reports', icon: FileText }],
  },
  {
    group: 'Reference',
    items: [{ to: '/commands', label: 'Command Center', icon: TerminalSquare }],
  },
];

function NavItem({ to, label, icon: Icon, end }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `focusable group relative flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-[13.5px] font-medium transition-all duration-200
        ${isActive ? 'bg-indigo-50 text-indigo-700' : 'text-ink-500 hover:text-ink-900 hover:bg-slate-50'}`}
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <motion.span layoutId="navpill" className="absolute left-0 top-1.5 bottom-1.5 w-1 rounded-full bg-indigo-500" />
          )}
          <Icon size={17} className="shrink-0" />
          <span>{label}</span>
          <ArrowRight size={13} className="ml-auto opacity-0 -translate-x-1 group-hover:opacity-40 group-hover:translate-x-0 transition-all" />
        </>
      )}
    </NavLink>
  );
}

function HealthDot() {
  const [health, setHealth] = useState(undefined); // undefined=checking, null=offline, obj=online
  useEffect(() => {
    let alive = true;
    const check = async () => { const h = await ping(); if (alive) setHealth(h); };
    check();
    const t = setInterval(check, 8000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  const online = !!health;
  return (
    <div className="flex items-center gap-2">
      <span className={`dot ${online ? 'bg-emerald-500' : 'bg-amber-500'}`} />
      <span className="text-[11px] font-medium text-ink-500">
        {health === undefined ? 'Checking API…' : online ? 'API online · live data' : 'API offline'}
      </span>
    </div>
  );
}

export default function Shell() {
  const location = useLocation();
  return (
    <div className="relative min-h-screen">
      <div className="app-aurora" />
      <div className="relative z-10 flex min-h-screen">
        {/* Sidebar */}
        <aside className="w-[264px] shrink-0 hidden lg:flex flex-col px-4 py-6 border-r border-line/80 bg-white/55 backdrop-blur-xl">
          <div className="flex items-center gap-3 px-2 mb-7">
            <div className="w-10 h-10 rounded-2xl btn-primary flex items-center justify-center">
              <Boxes size={20} className="text-white" />
            </div>
            <div>
              <h1 className="text-[15px] font-bold gradient-text leading-none">Migrate4HANA</h1>
              <p className="text-[10px] text-ink-400 font-mono tracking-[0.2em] uppercase mt-1">ECC → S/4HANA</p>
            </div>
          </div>

          <nav className="flex-1 space-y-5 overflow-y-auto">
            {NAV.map((section) => (
              <div key={section.group}>
                <p className="px-3.5 mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-ink-300">{section.group}</p>
                <div className="space-y-0.5">
                  {section.items.map((it) => <NavItem key={it.to} {...it} />)}
                </div>
              </div>
            ))}
          </nav>

          <div className="mt-4 rounded-2xl bg-slate-50 p-3.5">
            <HealthDot />
            <p className="text-[10px] text-ink-400 font-mono mt-2">v3.0 · 17-stage SAP Activate</p>
          </div>
        </aside>

        {/* Main */}
        <div className="flex-1 min-w-0 flex flex-col">
          {/* Topbar */}
          <header className="sticky top-0 z-20 px-6 lg:px-10 h-16 flex items-center gap-4 border-b border-line/70 bg-white/55 backdrop-blur-xl">
            <div className="lg:hidden flex items-center gap-2">
              <Boxes size={18} className="text-indigo-600" />
              <span className="font-bold gradient-text text-sm">Migrate4HANA</span>
            </div>
            <div className="ml-auto flex items-center gap-3">
              <EnvChip label="Source" value="ECC · Y01" tone="text-indigo-600 bg-indigo-50" />
              <ArrowRight size={14} className="text-ink-300" />
              <EnvChip label="Target" value="S/4HANA · S4H" tone="text-teal-600 bg-teal-50" />
            </div>
          </header>

          <main className="flex-1 overflow-y-auto">
            <AnimatePresence mode="wait">
              <motion.div
                key={location.pathname}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.28, ease: [0.4, 0, 0.2, 1] }}
                className="px-6 lg:px-10 py-8 max-w-[1180px] mx-auto"
              >
                <Outlet />
              </motion.div>
            </AnimatePresence>
          </main>
        </div>
      </div>
    </div>
  );
}

function EnvChip({ label, value, tone }) {
  return (
    <div className="flex items-center gap-2">
      <Circle size={7} className="fill-current text-ink-300" />
      <div className="leading-tight">
        <p className="text-[9px] uppercase tracking-wider text-ink-300 font-semibold">{label}</p>
        <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-md ${tone}`}>{value}</span>
      </div>
    </div>
  );
}
