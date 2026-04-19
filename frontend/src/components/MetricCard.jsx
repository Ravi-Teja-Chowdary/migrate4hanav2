import { motion } from 'framer-motion';

export default function MetricCard({ label, value, sub, icon: Icon, color = '#3b82f6', delay = 0 }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay, ease: [0.4, 0, 0.2, 1] }}
      className="glass glass-hover rounded-2xl p-5 relative overflow-hidden group"
    >
      {/* Glow */}
      <div
        className="absolute -top-10 -right-10 w-32 h-32 rounded-full opacity-[0.07] blur-2xl transition-opacity duration-500 group-hover:opacity-[0.12]"
        style={{ background: color }}
      />

      <div className="flex items-start justify-between mb-3">
        <div
          className="w-10 h-10 rounded-xl flex items-center justify-center"
          style={{ backgroundColor: `${color}15` }}
        >
          {Icon && <Icon size={18} style={{ color }} />}
        </div>
      </div>

      <div className="text-2xl font-bold text-white tracking-tight counter-animate">
        {typeof value === 'number' ? value.toLocaleString() : value}
      </div>
      <div className="text-xs text-white/40 mt-1">{label}</div>
      {sub && <div className="text-[10px] text-white/25 mt-0.5 font-mono">{sub}</div>}
    </motion.div>
  );
}
