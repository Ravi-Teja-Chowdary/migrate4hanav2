// Toast notification system. Any component can call useToast() to fire
// success / error / info messages. Toasts auto-dismiss after 4s (longer
// for errors) and stack from the top-right.
import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Check, X, AlertTriangle, Info, Loader2 } from 'lucide-react';

const ToastCtx = createContext(null);
let _next = 1;

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const dismiss = useCallback((id) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const push = useCallback((toast) => {
    const id = _next++;
    const t = { id, kind: 'info', ttl: 4000, ...toast };
    setToasts((cur) => [...cur, t]);
    if (t.ttl > 0) setTimeout(() => dismiss(id), t.ttl);
    return id;
  }, [dismiss]);
  // Convenience helpers — most callers use these
  const api = {
    success: (title, sub) => push({ kind: 'ok', title, sub, ttl: 4000 }),
    error:   (title, sub) => push({ kind: 'err', title, sub, ttl: 8000 }),
    info:    (title, sub) => push({ kind: 'info', title, sub, ttl: 4000 }),
    warn:    (title, sub) => push({ kind: 'warn', title, sub, ttl: 5000 }),
    loading: (title, sub) => push({ kind: 'loading', title, sub, ttl: 0 }),
    dismiss, push,
  };
  return (
    <ToastCtx.Provider value={api}>
      {children}
      {typeof document !== 'undefined' && createPortal(<ToastViewport toasts={toasts} onDismiss={dismiss} />, document.body)}
    </ToastCtx.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastCtx);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}

function ToastViewport({ toasts, onDismiss }) {
  return (
    <div className="fixed top-3 right-3 z-[60] flex flex-col gap-2 pointer-events-none">
      <AnimatePresence>
        {toasts.map((t) => <ToastItem key={t.id} t={t} onDismiss={() => onDismiss(t.id)} />)}
      </AnimatePresence>
    </div>
  );
}

function ToastItem({ t, onDismiss }) {
  const cfg = {
    ok:      { icon: Check,          color: 'var(--ok)',   bg: 'var(--ok-soft)' },
    err:     { icon: AlertTriangle,  color: 'var(--err)',  bg: 'var(--err-soft)' },
    warn:    { icon: AlertTriangle,  color: 'var(--warn)', bg: 'var(--warn-soft)' },
    info:    { icon: Info,           color: 'var(--info)', bg: 'var(--info-soft)' },
    loading: { icon: Loader2,        color: 'var(--accent)', bg: 'var(--accent-soft)' },
  }[t.kind] || { icon: Info, color: 'var(--info)', bg: 'var(--info-soft)' };
  const Icon = cfg.icon;
  return (
    <motion.div
      initial={{ opacity: 0, x: 20, scale: 0.95 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: 20, scale: 0.95 }}
      transition={{ duration: 0.18, ease: [0.4, 0, 0.2, 1] }}
      className="panel-elev w-[340px] pointer-events-auto"
      style={{ boxShadow: 'var(--shadow-popup)' }}
    >
      <div className="flex items-start gap-3 p-3">
        <div className="w-8 h-8 rounded shrink-0 flex items-center justify-center" style={{ background: cfg.bg }}>
          {t.kind === 'loading' ? (
            <motion.span animate={{ rotate: 360 }} transition={{ duration: 1, repeat: Infinity, ease: 'linear' }} className="inline-flex">
              <Icon size={14} style={{ color: cfg.color }} />
            </motion.span>
          ) : (
            <Icon size={14} style={{ color: cfg.color }} />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[12.5px] font-semibold text-ink-1">{t.title}</div>
          {t.sub && <div className="text-[11.5px] text-ink-3 mt-0.5 break-words">{t.sub}</div>}
        </div>
        <button onClick={onDismiss} className="text-ink-4 hover:text-ink-1 shrink-0">
          <X size={13} />
        </button>
      </div>
    </motion.div>
  );
}
