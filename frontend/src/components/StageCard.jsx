import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { CheckCircle2, Clock, AlertTriangle, XCircle } from 'lucide-react';

const STATUS_CONFIG = {
  completed: { icon: CheckCircle2, color: '#10b981', bg: 'rgba(16, 185, 129, 0.1)', label: 'Completed' },
  running: { icon: Clock, color: '#3b82f6', bg: 'rgba(59, 130, 246, 0.1)', label: 'Running' },
  pending: { icon: Clock, color: 'rgba(15, 23, 42,0.2)', bg: 'rgba(15, 23, 42,0.03)', label: 'Pending' },
  warning: { icon: AlertTriangle, color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.1)', label: 'Warning' },
  failed: { icon: XCircle, color: '#ef4444', bg: 'rgba(239, 68, 68, 0.1)', label: 'Failed' },
};

export default function StageCard({ stage, status = 'pending', delay = 0, compact = false }) {
  const navigate = useNavigate();
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.pending;
  const StatusIcon = cfg.icon;

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay, ease: [0.4, 0, 0.2, 1] }}
      onClick={() => navigate(`/stage/${stage.key}`)}
      className="glass glass-hover rounded-2xl p-4 cursor-pointer relative overflow-hidden group"
    >
      {/* Top accent line */}
      <div
        className="absolute top-0 left-0 right-0 h-[2px] opacity-60"
        style={{ background: `linear-gradient(90deg, ${stage.color}, transparent)` }}
      />

      <div className="flex items-center gap-3">
        {/* Stage number */}
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold shrink-0"
          style={{ backgroundColor: `${stage.color}15`, color: stage.color }}
        >
          {stage.id}
        </div>

        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-slate-700 truncate">{stage.name}</div>
          {!compact && (
            <div className="text-[10px] text-slate-400 uppercase tracking-wider mt-0.5">
              {stage.phase} phase
            </div>
          )}
        </div>

        {/* Status */}
        <div
          className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
          style={{ backgroundColor: cfg.bg }}
        >
          <StatusIcon size={14} style={{ color: cfg.color }} />
        </div>
      </div>

      {/* Running animation */}
      {status === 'running' && (
        <div className="absolute bottom-0 left-0 right-0 h-[2px] overflow-hidden">
          <motion.div
            className="h-full w-1/3"
            style={{ background: `linear-gradient(90deg, transparent, ${stage.color}, transparent)` }}
            animate={{ x: ['-100%', '400%'] }}
            transition={{ duration: 1.5, repeat: Infinity, ease: 'linear' }}
          />
        </div>
      )}
    </motion.div>
  );
}
