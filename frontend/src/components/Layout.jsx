import { Outlet, NavLink, useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  LayoutDashboard, Server, GitBranch, Trophy, FileText, Zap, ChevronRight, Activity,
} from 'lucide-react';

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/connections', label: 'Connections', icon: Server },
  { to: '/pipeline', label: 'Pipeline', icon: GitBranch },
  { to: '/lift-and-shift', label: 'Lift & Shift', icon: GitBranch },
  { to: '/telemetry', label: 'Telemetry', icon: Activity },
  { to: '/scorecard', label: 'Scorecard', icon: Trophy },
  { to: '/report', label: 'Report', icon: FileText },
];

function SidebarLink({ to, label, icon: Icon }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        `group flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all duration-300
        ${isActive
          ? 'bg-accent-blue/10 text-accent-blue shadow-lg shadow-accent-blue/5'
          : 'text-white/50 hover:text-white/80 hover:bg-white/[0.03]'
        }`
      }
    >
      <Icon size={18} className="shrink-0" />
      <span>{label}</span>
      <ChevronRight
        size={14}
        className="ml-auto opacity-0 -translate-x-2 group-hover:opacity-50 group-hover:translate-x-0 transition-all duration-300"
      />
    </NavLink>
  );
}

export default function Layout() {
  const location = useLocation();

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="w-64 shrink-0 border-r border-white/[0.06] bg-navy-800/50 flex flex-col">
        {/* Logo */}
        <div className="p-6 pb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-accent-blue to-accent-cyan flex items-center justify-center shadow-lg shadow-accent-blue/20">
              <Zap size={20} className="text-white" />
            </div>
            <div>
              <h1 className="text-base font-bold gradient-text">Migrate4HANA</h1>
              <p className="text-[10px] text-white/30 font-mono tracking-widest uppercase">ECC Assessment</p>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-2 space-y-1">
          {NAV.map((item) => (
            <SidebarLink key={item.to} {...item} />
          ))}
        </nav>

        {/* Footer */}
        <div className="p-4 border-t border-white/[0.04]">
          <div className="glass rounded-xl p-3">
            <div className="flex items-center gap-2 mb-2">
              <div className="pulse-dot bg-accent-green" />
              <span className="text-xs text-white/50">System Ready</span>
            </div>
            <p className="text-[10px] text-white/30 font-mono">v2.0 · 17-Stage Pipeline</p>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <AnimatePresence mode="wait">
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
            className="min-h-full"
          >
            <Outlet />
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}
