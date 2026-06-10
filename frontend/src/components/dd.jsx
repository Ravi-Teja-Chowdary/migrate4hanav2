// Datadog/Grafana-style observability components.
// Light/dark themed via CSS variables (see ../lib/theme.js + ../index.css).
// Keep this module the source of truth for the new design system —
// pages should compose from here, not redefine.
import { useMemo, useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ChevronDown, MoreHorizontal, ArrowUp, ArrowDown, Minus,
  Loader2, Copy, Check, Terminal, RefreshCw, X, Search,
} from 'lucide-react';

// ── Panel ──────────────────────────────────────────────────────
// Wraps each chart / table / KV block. Header has title + optional
// actions. Body has padding; pass flush for tables/charts.
export function Panel({ title, subtitle, icon: Icon, actions, children, flush = false, className = '' }) {
  return (
    <div className={`panel ${className}`}>
      {(title || actions) && (
        <div className="panel-header">
          {Icon && <Icon size={14} className="text-ink-3 shrink-0" />}
          <div className="min-w-0 flex-1">
            <div className="text-ink-2 font-semibold truncate">{title}</div>
            {subtitle && <div className="text-[11px] text-ink-3 font-normal mt-0.5 truncate">{subtitle}</div>}
          </div>
          {actions && <div className="flex items-center gap-1.5 shrink-0">{actions}</div>}
        </div>
      )}
      <div className={flush ? 'panel-body-flush' : 'panel-body'}>{children}</div>
    </div>
  );
}

// ── StatusPill ─────────────────────────────────────────────────
// Tone keyed by string; dot optional.
const TONE_MAP = {
  ok: 'pill-ok', success: 'pill-ok', succeeded: 'pill-ok', completed: 'pill-ok',
  running: 'pill-info', pending: 'pill-muted', queued: 'pill-muted',
  warn: 'pill-warn', warning: 'pill-warn', breach: 'pill-warn',
  error: 'pill-err', err: 'pill-err', failed: 'pill-err',
  info: 'pill-info', muted: 'pill-muted',
};
export function StatusPill({ tone = 'muted', dot = true, children }) {
  const cls = TONE_MAP[tone?.toLowerCase()] || 'pill-muted';
  return (
    <span className={`pill ${cls}`}>
      {dot && <span className="w-1.5 h-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

// ── MetricTile ─────────────────────────────────────────────────
// Big number + label + delta + optional inline sparkline.
// Spark accepts an array of numbers (any length).
export function MetricTile({ label, value, unit, sub, delta, deltaTone, spark, tone, className = '' }) {
  const deltaIcon = delta == null ? null : (delta > 0 ? <ArrowUp size={11} /> : delta < 0 ? <ArrowDown size={11} /> : <Minus size={11} />);
  const dTone = deltaTone || (delta == null ? 'muted' : delta > 0 ? 'ok' : delta < 0 ? 'err' : 'muted');
  const valueColor = tone === 'warn' ? 'var(--warn)'
                    : tone === 'err'  ? 'var(--err)'
                    : tone === 'ok'   ? 'var(--ok)'
                    : 'var(--ink-1)';
  return (
    <div className={`panel ${className}`}>
      <div className="panel-body">
        <div className="metric-label">{label}</div>
        <div className="flex items-baseline gap-1.5 mt-2">
          <div className="metric-num" style={{ color: valueColor }}>{value}</div>
          {unit && <div className="text-xs text-ink-3 font-semibold">{unit}</div>}
        </div>
        <div className="flex items-center justify-between mt-2.5 gap-3">
          <div className="flex items-center gap-2 min-w-0">
            {delta != null && (
              <StatusPill tone={dTone} dot={false}>
                {deltaIcon}{Math.abs(delta)}%
              </StatusPill>
            )}
            {sub && <span className="text-[11px] text-ink-3 truncate">{sub}</span>}
          </div>
          {spark && spark.length > 0 && <Sparkline values={spark} className="shrink-0" />}
        </div>
      </div>
    </div>
  );
}

// ── Sparkline ──────────────────────────────────────────────────
// Inline SVG sparkline; no axis, just a line + soft fill.
export function Sparkline({ values, width = 92, height = 28, tone = 'accent', className = '' }) {
  const path = useMemo(() => {
    if (!values || values.length === 0) return { line: '', fill: '' };
    const min = Math.min(...values), max = Math.max(...values);
    const range = max - min || 1;
    const stepX = width / Math.max(1, values.length - 1);
    const pts = values.map((v, i) => {
      const x = i * stepX;
      const y = height - ((v - min) / range) * (height - 4) - 2;
      return [x, y];
    });
    const line = pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
    const fill = `${line} L${pts[pts.length - 1][0].toFixed(1)},${height} L${pts[0][0].toFixed(1)},${height} Z`;
    return { line, fill };
  }, [values, width, height]);
  const color = tone === 'ok' ? 'var(--ok)'
              : tone === 'warn' ? 'var(--warn)'
              : tone === 'err'  ? 'var(--err)'
              : 'var(--accent)';
  return (
    <svg width={width} height={height} className={className}>
      <path d={path.fill} fill={color} opacity={0.12} />
      <path d={path.line} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

// ── TimeSeriesChart ────────────────────────────────────────────
// Recharts area chart with the observability theme baked in.
// `series` = [{ts, value}] OR multi-series via `seriesList`.
// Keeps recharts as the heavy-lift impl; could be swapped later.
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
export function TimeSeriesChart({ series = [], height = 180, tone = 'accent', unit = '', threshold = null, thresholdLabel = '' }) {
  const color = tone === 'ok' ? 'var(--ok)'
              : tone === 'warn' ? 'var(--warn)'
              : tone === 'err'  ? 'var(--err)'
              : 'var(--accent)';
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={series} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id={`tsg-${tone}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.30} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis dataKey="ts" tick={{ fill: 'var(--ink-4)', fontSize: 10 }} axisLine={{ stroke: 'var(--border)' }} tickLine={false} />
        <YAxis tick={{ fill: 'var(--ink-4)', fontSize: 10 }} axisLine={false} tickLine={false} width={32}
               tickFormatter={(v) => unit === '%' ? `${v}%` : v} />
        <Tooltip
          contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6, fontSize: 12, color: 'var(--ink-1)', boxShadow: 'var(--shadow-popup)' }}
          labelStyle={{ color: 'var(--ink-3)', fontSize: 11 }}
          formatter={(v) => [unit === '%' ? `${v}%` : v, '']}
        />
        {threshold != null && (
          <ReferenceLine y={threshold} stroke="var(--warn)" strokeDasharray="3 3"
                         label={{ value: thresholdLabel, fill: 'var(--warn)', fontSize: 10, position: 'right' }} />
        )}
        <Area type="monotone" dataKey="value" stroke={color} strokeWidth={1.8}
              fill={`url(#tsg-${tone})`} dot={false} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// ── Gantt ──────────────────────────────────────────────────────
// Time-axis bar chart for stage durations.
// `stages` = [{name, start, end, status}], times in ms or sec (any consistent unit).
export function Gantt({ stages = [], rowHeight = 22, gap = 4 }) {
  const min = useMemo(() => Math.min(...stages.map(s => s.start)) || 0, [stages]);
  const max = useMemo(() => Math.max(...stages.map(s => s.end)) || 1, [stages]);
  const range = max - min || 1;
  const colorFor = (s) => s === 'ok' || s === 'success' || s === 'succeeded' ? 'var(--ok)'
                       : s === 'running' ? 'var(--info)'
                       : s === 'failed' || s === 'error' ? 'var(--err)'
                       : s === 'warn' || s === 'breach' ? 'var(--warn)'
                       : 'var(--ink-5)';
  return (
    <div className="space-y-1">
      {stages.map((s, i) => {
        const left = ((s.start - min) / range) * 100;
        const width = Math.max(((s.end - s.start) / range) * 100, 0.4);
        return (
          <div key={s.name + i} className="flex items-center gap-3 text-[11.5px]" style={{ height: rowHeight }}>
            <div className="w-44 truncate text-ink-2 font-medium shrink-0" title={s.name}>{s.name}</div>
            <div className="flex-1 relative" style={{ background: 'var(--bg-elev)', borderRadius: 4, height: rowHeight - 6 }}>
              <div
                className="absolute top-0 bottom-0 rounded transition-all"
                style={{ left: `${left}%`, width: `${width}%`, background: colorFor(s.status), opacity: 0.85 }}
                title={`${s.name}: ${(s.end - s.start).toFixed(1)}`}
              />
            </div>
            <div className="w-16 text-right text-ink-3 tabular-nums shrink-0">
              {((s.end - s.start) >= 60 ? `${((s.end - s.start) / 60).toFixed(1)}m` : `${(s.end - s.start).toFixed(0)}s`)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── RefreshControl ─────────────────────────────────────────────
// Controls the auto-refresh interval. Calls onTick at the chosen cadence.
const INTERVALS = [
  { label: 'Off',  value: 0 },
  { label: '5s',   value: 5_000 },
  { label: '10s',  value: 10_000 },
  { label: '30s',  value: 30_000 },
  { label: '1m',   value: 60_000 },
];
export function RefreshControl({ value, onChange, onRefresh }) {
  const [open, setOpen] = useState(false);
  const cur = INTERVALS.find((i) => i.value === value) || INTERVALS[1];
  useEffect(() => {
    if (!value || !onRefresh) return;
    const t = setInterval(onRefresh, value);
    return () => clearInterval(t);
  }, [value, onRefresh]);
  return (
    <div className="relative inline-flex">
      <button className="btn btn-sm" onClick={onRefresh} title="Refresh now">
        <RefreshCw size={12} />
      </button>
      <button className="btn btn-sm" style={{ marginLeft: -1, borderTopLeftRadius: 0, borderBottomLeftRadius: 0 }} onClick={() => setOpen(o => !o)}>
        {cur.label} <ChevronDown size={11} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
            className="absolute top-full right-0 mt-1 panel min-w-[120px] z-30"
            onMouseLeave={() => setOpen(false)}
          >
            {INTERVALS.map((i) => (
              <button
                key={i.value}
                onClick={() => { onChange?.(i.value); setOpen(false); }}
                className={`w-full text-left px-3 py-1.5 text-xs hover:bg-bg-elev ${i.value === value ? 'text-accent font-semibold' : 'text-ink-2'}`}
              >
                {i.label}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── TimeRangePicker ────────────────────────────────────────────
const RANGES = [
  { label: 'Last 1h',  value: '1h' },
  { label: 'Last 6h',  value: '6h' },
  { label: 'Last 24h', value: '24h' },
  { label: 'Last 7d',  value: '7d' },
  { label: 'Last 30d', value: '30d' },
  { label: 'All time', value: 'all' },
];
export function TimeRangePicker({ value = '24h', onChange }) {
  const [open, setOpen] = useState(false);
  const cur = RANGES.find((r) => r.value === value) || RANGES[2];
  return (
    <div className="relative inline-flex">
      <button className="btn btn-sm" onClick={() => setOpen(o => !o)}>
        {cur.label} <ChevronDown size={11} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
            className="absolute top-full right-0 mt-1 panel min-w-[140px] z-30"
            onMouseLeave={() => setOpen(false)}
          >
            {RANGES.map((r) => (
              <button
                key={r.value}
                onClick={() => { onChange?.(r.value); setOpen(false); }}
                className={`w-full text-left px-3 py-1.5 text-xs hover:bg-bg-elev ${r.value === value ? 'text-accent font-semibold' : 'text-ink-2'}`}
              >
                {r.label}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── PageHeader ─────────────────────────────────────────────────
// Replaces fluidic gradient title — keep it terse like Datadog.
export function PageHeader({ title, breadcrumb, subtitle, actions }) {
  return (
    <div className="flex items-end justify-between gap-4 mb-5">
      <div className="min-w-0">
        {breadcrumb && breadcrumb.length > 0 && (
          <div className="flex items-center gap-1.5 text-[11px] text-ink-3 mb-1.5">
            {breadcrumb.map((b, i) => (
              <span key={i} className="flex items-center gap-1.5">
                {i > 0 && <span className="text-ink-4">/</span>}
                <span className={i === breadcrumb.length - 1 ? 'text-ink-2' : ''}>{b}</span>
              </span>
            ))}
          </div>
        )}
        <h1 className="page-title">{title}</h1>
        {subtitle && <p className="page-sub mt-1">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
    </div>
  );
}

// ── Spinner + Skeleton ─────────────────────────────────────────
export function Spinner({ size = 14, className = '' }) {
  return (
    <motion.span animate={{ rotate: 360 }} transition={{ duration: 1, repeat: Infinity, ease: 'linear' }} className={`inline-flex text-accent ${className}`}>
      <Loader2 size={size} />
    </motion.span>
  );
}
export function Skeleton({ width = '100%', height = 14, className = '' }) {
  return <div className={`skeleton ${className}`} style={{ width, height }} />;
}

// ── Inline copyable command (parameterized) ────────────────────
export function CmdLine({ cmd, label }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(cmd); setCopied(true); setTimeout(() => setCopied(false), 1400); } catch { /* noop */ }
  };
  return (
    <div className="code-block group flex items-center gap-3">
      <Terminal size={12} className="text-accent shrink-0" />
      {label && <span className="text-[11px] text-ink-4 shrink-0">{label}</span>}
      <code className="flex-1 overflow-x-auto whitespace-pre">{cmd}</code>
      <button onClick={copy} className="focusable shrink-0 text-slate-400 hover:text-white transition-colors" title="Copy command">
        {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
      </button>
    </div>
  );
}

// ── EmptyState — terse, observability-tool feel ────────────────
export function EmptyState({ title, hint, action, icon: Icon }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-10 px-6">
      {Icon && (
        <div className="w-10 h-10 rounded-lg bg-bg-elev flex items-center justify-center mb-3">
          <Icon size={18} className="text-ink-4" />
        </div>
      )}
      <p className="text-sm font-semibold text-ink-2">{title}</p>
      {hint && <p className="text-xs text-ink-3 mt-1 max-w-md">{hint}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

// ── OfflineBanner — clear, not dramatic ────────────────────────
export function OfflineBanner({ onRetry }) {
  return (
    <div className="panel mb-4" style={{ borderColor: 'var(--warn)' }}>
      <div className="panel-body flex items-center gap-3">
        <div className="w-8 h-8 rounded bg-warn-soft flex items-center justify-center shrink-0" style={{ background: 'var(--warn-soft)' }}>
          <X size={14} style={{ color: 'var(--warn)' }} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-ink-1">Backend API offline</div>
          <div className="text-[11.5px] text-ink-3 mt-0.5">Start it locally to load live data — no values are faked.</div>
        </div>
        {onRetry && <button className="btn btn-sm" onClick={onRetry}>Retry</button>}
        <CmdLine cmd="python api_server.py" />
      </div>
    </div>
  );
}

// ── KVList — key/value strip for stat dumps ────────────────────
export function KVList({ items, cols = 2 }) {
  return (
    <div className={`grid grid-cols-${cols === 4 ? '4' : cols === 3 ? '3' : '2'} gap-x-6 gap-y-2.5`}>
      {items.map((it, i) => (
        <div key={i}>
          <div className="text-[10.5px] uppercase tracking-wider text-ink-4 font-semibold">{it.label}</div>
          <div className="text-[12.5px] text-ink-1 font-medium mt-0.5 tabular-nums">{it.value}</div>
        </div>
      ))}
    </div>
  );
}

// ── SearchBox ──────────────────────────────────────────────────
export function SearchBox({ value, onChange, placeholder = 'Search…', shortcut, autoFocus = false }) {
  const ref = useRef(null);
  useEffect(() => { if (autoFocus) ref.current?.focus(); }, [autoFocus]);
  return (
    <div className="relative inline-flex items-center">
      <Search size={13} className="absolute left-2.5 text-ink-4 pointer-events-none" />
      <input
        ref={ref}
        className="input pl-8 pr-12 w-[260px]"
        value={value} onChange={(e) => onChange?.(e.target.value)}
        placeholder={placeholder}
      />
      {shortcut && <span className="kbd absolute right-2">{shortcut}</span>}
    </div>
  );
}
