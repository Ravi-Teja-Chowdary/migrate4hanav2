import { useState } from 'react';
import { motion } from 'framer-motion';
import { Check, Copy, Terminal, Loader2, Inbox, WifiOff } from 'lucide-react';

// accent → tailwind class fragments (kept explicit so Tailwind keeps them)
export const ACCENT = {
  indigo: { text: 'text-indigo-600', bg: 'bg-indigo-50', soft: 'bg-indigo-500/10', ring: 'ring-indigo-200', dot: 'bg-indigo-500', grad: 'from-indigo-500 to-indigo-600' },
  violet: { text: 'text-violet-600', bg: 'bg-violet-100', soft: 'bg-violet-500/10', ring: 'ring-violet-200', dot: 'bg-violet-500', grad: 'from-violet-500 to-violet-600' },
  teal: { text: 'text-teal-600', bg: 'bg-teal-50', soft: 'bg-teal-500/10', ring: 'ring-teal-200', dot: 'bg-teal-500', grad: 'from-teal-500 to-teal-600' },
  sky: { text: 'text-sky-600', bg: 'bg-sky-50', soft: 'bg-sky-500/10', ring: 'ring-sky-200', dot: 'bg-sky-500', grad: 'from-sky-500 to-sky-600' },
  emerald: { text: 'text-emerald-600', bg: 'bg-emerald-50', soft: 'bg-emerald-500/10', ring: 'ring-emerald-200', dot: 'bg-emerald-500', grad: 'from-emerald-500 to-emerald-600' },
  amber: { text: 'text-amber-600', bg: 'bg-amber-50', soft: 'bg-amber-500/10', ring: 'ring-amber-200', dot: 'bg-amber-500', grad: 'from-amber-500 to-amber-600' },
  rose: { text: 'text-rose-600', bg: 'bg-rose-50', soft: 'bg-rose-500/10', ring: 'ring-rose-200', dot: 'bg-rose-500', grad: 'from-rose-500 to-rose-600' },
  slate: { text: 'text-ink-500', bg: 'bg-slate-50', soft: 'bg-slate-500/10', ring: 'ring-slate-200', dot: 'bg-ink-300', grad: 'from-slate-400 to-slate-500' },
};

export function Card({ className = '', hover = false, children, ...rest }) {
  return (
    <div className={`card rounded-3xl ${hover ? 'card-hover' : ''} ${className}`} {...rest}>
      {children}
    </div>
  );
}

export function SectionTitle({ icon: Icon, title, subtitle, right }) {
  return (
    <div className="flex items-center gap-3 mb-4">
      {Icon && (
        <div className="w-9 h-9 rounded-xl bg-indigo-50 flex items-center justify-center">
          <Icon size={17} className="text-indigo-600" />
        </div>
      )}
      <div className="min-w-0">
        <h2 className="text-[15px] font-semibold text-ink-900 leading-tight">{title}</h2>
        {subtitle && <p className="text-xs text-ink-400 mt-0.5">{subtitle}</p>}
      </div>
      {right && <div className="ml-auto">{right}</div>}
    </div>
  );
}

const TONE = {
  ok: 'bg-emerald-50 text-emerald-600', success: 'bg-emerald-50 text-emerald-600',
  completed: 'bg-emerald-50 text-emerald-600', running: 'bg-sky-50 text-sky-600',
  pending: 'bg-slate-100 text-ink-500', queued: 'bg-slate-100 text-ink-500',
  warn: 'bg-amber-50 text-amber-600', error: 'bg-rose-50 text-rose-600',
  failed: 'bg-rose-50 text-rose-600', info: 'bg-indigo-50 text-indigo-600',
};

export function Badge({ tone = 'info', children, className = '' }) {
  return (
    <span className={`inline-flex items-center gap-1.5 text-[11px] font-semibold px-2.5 py-1 rounded-full ${TONE[tone] || TONE.info} ${className}`}>
      {children}
    </span>
  );
}

export function Stat({ label, value, sub, icon: Icon, accent = 'indigo' }) {
  const a = ACCENT[accent] || ACCENT.indigo;
  return (
    <Card hover className="p-5">
      <div className="flex items-start justify-between">
        <div className="min-w-0">
          <p className="text-[11px] uppercase tracking-wider text-ink-400 font-semibold">{label}</p>
          <p className="text-2xl font-bold text-ink-900 mt-1 tabular-nums truncate">{value}</p>
          {sub && <p className="text-xs text-ink-400 mt-1">{sub}</p>}
        </div>
        {Icon && (
          <div className={`w-10 h-10 rounded-2xl ${a.bg} flex items-center justify-center shrink-0`}>
            <Icon size={18} className={a.text} />
          </div>
        )}
      </div>
    </Card>
  );
}

export function ProgressBar({ value = 0, accent = 'indigo', className = '' }) {
  const a = ACCENT[accent] || ACCENT.indigo;
  return (
    <div className={`h-2.5 rounded-full bg-slate-100 overflow-hidden ${className}`}>
      <motion.div
        className={`h-full rounded-full bg-gradient-to-r ${a.grad}`}
        initial={{ width: 0 }}
        animate={{ width: `${Math.max(0, Math.min(100, value))}%` }}
        transition={{ duration: 0.6, ease: [0.4, 0, 0.2, 1] }}
      />
    </div>
  );
}

export function Spinner({ size = 16, className = 'text-indigo-500' }) {
  return (
    <motion.span animate={{ rotate: 360 }} transition={{ duration: 1, repeat: Infinity, ease: 'linear' }} className="inline-flex">
      <Loader2 size={size} className={className} />
    </motion.span>
  );
}

/** Copyable terminal command — the bridge between UI actions and the CLI. */
export function CommandBlock({ cmd, label }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(cmd); setCopied(true); setTimeout(() => setCopied(false), 1400); } catch { /* noop */ }
  };
  return (
    <div className="group rounded-xl bg-ink-900 text-slate-100 px-3.5 py-2.5 flex items-center gap-3 font-mono text-[12.5px] shadow-soft">
      <Terminal size={14} className="text-indigo-300 shrink-0" />
      <code className="flex-1 overflow-x-auto whitespace-pre text-slate-100/90">{cmd}</code>
      <button onClick={copy} className="focusable shrink-0 text-slate-400 hover:text-white transition-colors" title="Copy command" aria-label="Copy command">
        {copied ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
      </button>
    </div>
  );
}

export function EmptyState({ icon: Icon = Inbox, title, hint, action }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-12 px-6">
      <div className="w-14 h-14 rounded-2xl bg-slate-50 flex items-center justify-center mb-4">
        <Icon size={24} className="text-ink-300" />
      </div>
      <p className="text-sm font-semibold text-ink-700">{title}</p>
      {hint && <p className="text-xs text-ink-400 mt-1 max-w-sm">{hint}</p>}
      {action && <div className="mt-4 w-full max-w-md">{action}</div>}
    </div>
  );
}

export function OfflineBanner({ onRetry }) {
  return (
    <Card className="p-4 border-amber-200/60">
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-xl bg-amber-50 flex items-center justify-center shrink-0">
          <WifiOff size={16} className="text-amber-600" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-ink-900">Backend API is offline</p>
          <p className="text-xs text-ink-400 mt-0.5">Start it to load live data — no data is faked.</p>
        </div>
        {onRetry && (
          <button onClick={onRetry} className="focusable text-xs font-semibold text-indigo-600 hover:text-indigo-700 px-3 py-1.5 rounded-lg bg-indigo-50">
            Retry
          </button>
        )}
      </div>
      <div className="mt-3">
        <CommandBlock cmd="python api_server.py" />
      </div>
    </Card>
  );
}

export function PageHeader({ title, accentWord, subtitle, actions }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div>
        <motion.h1 initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="text-[26px] font-bold text-ink-900 tracking-tight">
          {title} {accentWord && <span className="gradient-text">{accentWord}</span>}
        </motion.h1>
        {subtitle && <p className="text-sm text-ink-400 mt-1">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
