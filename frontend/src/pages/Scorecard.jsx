import { motion } from 'framer-motion';
import {
  PieChart, Pie, Cell, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip,
} from 'recharts';
import {
  Trophy, CheckCircle2, XCircle, Shield, Code, Database, Settings, Plug,
  ArrowLeft, ShieldCheck, DollarSign,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { SAMPLE_RUN } from '../data/sampleData';

const GRADE_COLORS = { A: '#10b981', B: '#f59e0b', C: '#f97316', D: '#ef4444' };
const CATEGORY_ICONS = {
  code: Code,
  data: Database,
  config: Settings,
  roles: Shield,
  integrations: Plug,
  sap_compliance: ShieldCheck,
  finance_reconciliation: DollarSign,
};

const CATEGORY_LABELS = {
  code: 'Code',
  data: 'Data',
  config: 'Config',
  roles: 'Roles',
  integrations: 'Integrations',
  sap_compliance: 'SAP Compliance',
  finance_reconciliation: 'Finance Recon',
};

function ScoreGauge({ score, grade }) {
  const pct = parseFloat(score) / 100;
  const radius = 45;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - pct);
  const color = GRADE_COLORS[grade] || '#3b82f6';

  return (
    <div className="relative w-48 h-48 mx-auto">
      <svg viewBox="0 0 120 120" className="w-full h-full -rotate-90">
        {/* Background circle */}
        <circle cx="60" cy="60" r={radius} fill="none" stroke="rgba(15, 23, 42,0.05)" strokeWidth="8" />
        {/* Score arc */}
        <motion.circle
          cx="60" cy="60" r={radius}
          fill="none" stroke={color} strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: offset }}
          transition={{ duration: 1.5, ease: [0.4, 0, 0.2, 1], delay: 0.3 }}
        />
        {/* Glow */}
        <motion.circle
          cx="60" cy="60" r={radius}
          fill="none" stroke={color} strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: offset }}
          transition={{ duration: 1.5, ease: [0.4, 0, 0.2, 1], delay: 0.3 }}
          style={{ filter: 'blur(8px)', opacity: 0.4 }}
        />
      </svg>
      {/* Center text */}
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <motion.span
          initial={{ opacity: 0, scale: 0.5 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.8, type: 'spring', stiffness: 200 }}
          className="text-4xl font-bold"
          style={{ color }}
        >
          {grade}
        </motion.span>
        <motion.span
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1 }}
          className="text-sm text-slate-500 font-mono"
        >
          {score}
        </motion.span>
      </div>
    </div>
  );
}

export default function Scorecard() {
  const navigate = useNavigate();
  const sc = SAMPLE_RUN.results.validation_scorecard.scorecard;
  const color = GRADE_COLORS[sc.grade] || '#3b82f6';

  const categories = Object.entries(sc.checks).map(([key, val]) => ({
    name: CATEGORY_LABELS[key] || key.charAt(0).toUpperCase() + key.slice(1).replace(/_/g, ' '),
    key,
    passed: val.passed,
    checked: val.checked,
    failed: val.failed || (val.checked - val.passed),
  }));

  const pieData = [
    { name: 'Passed', value: sc.total_passed, color: '#10b981' },
    { name: 'Failed', value: sc.total_failed, color: '#ef4444' },
  ];

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button
          onClick={() => navigate('/')}
          className="w-9 h-9 rounded-xl glass flex items-center justify-center text-slate-400 hover:text-slate-500 transition-colors"
        >
          <ArrowLeft size={16} />
        </button>
        <div>
          <motion.h1
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            className="text-3xl font-bold text-slate-900"
          >
            GO-LIVE <span className="gradient-text">Scorecard</span>
          </motion.h1>
          <p className="text-sm text-slate-400 mt-0.5">End-to-end migration validation results — {sc.total_checks} checks across {categories.length} dimensions</p>
        </div>
      </div>

      {/* Main scorecard */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Gauge */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="glass rounded-2xl p-8 flex flex-col items-center justify-center relative overflow-hidden"
        >
          <div className="absolute inset-0 bg-gradient-to-br from-transparent to-white/[0.01]" />
          <div className="relative">
            <ScoreGauge score={sc.score} grade={sc.grade} />
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 1.2 }}
              className="text-center mt-4"
            >
              <span
                className="inline-block px-4 py-1.5 rounded-full text-xs font-semibold"
                style={{ backgroundColor: `${color}15`, color }}
              >
                {sc.recommendation}
              </span>
            </motion.div>
          </div>
        </motion.div>

        {/* Stats */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          className="glass rounded-2xl p-6 space-y-4"
        >
          <h3 className="text-sm font-semibold text-slate-500 uppercase tracking-wider">Validation Summary</h3>
          <div className="space-y-3">
            <div className="flex items-center justify-between p-3 rounded-xl bg-slate-50">
              <span className="text-sm text-slate-500">Total Checks</span>
              <span className="text-lg font-bold text-slate-900">{sc.total_checks}</span>
            </div>
            <div className="flex items-center justify-between p-3 rounded-xl bg-accent-green/5">
              <span className="text-sm text-accent-green/70 flex items-center gap-2">
                <CheckCircle2 size={14} /> Passed
              </span>
              <span className="text-lg font-bold text-accent-green">{sc.total_passed}</span>
            </div>
            <div className="flex items-center justify-between p-3 rounded-xl bg-accent-red/5">
              <span className="text-sm text-accent-red/70 flex items-center gap-2">
                <XCircle size={14} /> Failed
              </span>
              <span className="text-lg font-bold text-accent-red">{sc.total_failed}</span>
            </div>
          </div>

          <div className="pt-2">
            <div className="flex justify-center">
              <ResponsiveContainer width={160} height={100}>
                <PieChart>
                  <Pie data={pieData} cx="50%" cy="50%" innerRadius={30} outerRadius={42} dataKey="value" strokeWidth={0}>
                    {pieData.map((entry, i) => (
                      <Cell key={i} fill={entry.color} />
                    ))}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>
        </motion.div>

        {/* Category breakdown */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
          className="glass rounded-2xl p-6"
        >
          <h3 className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-4">By Category</h3>
          <div className="space-y-3">
            {categories.map((cat, i) => {
              const CatIcon = CATEGORY_ICONS[cat.key] || CheckCircle2;
              const pct = cat.checked > 0 ? (cat.passed / cat.checked) * 100 : 0;

              return (
                <motion.div
                  key={cat.key}
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.4 + i * 0.08 }}
                  className="p-3 rounded-xl bg-slate-50"
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm text-slate-500 flex items-center gap-2">
                      <CatIcon size={14} className="text-slate-400" />
                      {cat.name}
                    </span>
                    <span className="text-xs font-mono text-slate-400">{cat.passed}/{cat.checked}</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-slate-50 overflow-hidden">
                    <motion.div
                      className="h-full rounded-full"
                      style={{ background: pct === 100 ? '#10b981' : pct > 80 ? '#f59e0b' : '#ef4444' }}
                      initial={{ width: 0 }}
                      animate={{ width: `${pct}%` }}
                      transition={{ duration: 0.8, delay: 0.6 + i * 0.1, ease: [0.4, 0, 0.2, 1] }}
                    />
                  </div>
                </motion.div>
              );
            })}
          </div>
        </motion.div>
      </div>

      {/* Bar chart */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.5 }}
        className="glass rounded-2xl p-6"
      >
        <h3 className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-4">Checks by Category</h3>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={categories} barGap={8}>
            <XAxis dataKey="name" tick={{ fill: 'rgba(15, 23, 42,0.3)', fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fill: 'rgba(15, 23, 42,0.3)', fontSize: 12 }} axisLine={false} tickLine={false} />
            <Tooltip
              contentStyle={{
                backgroundColor: '#ffffff',
                border: '1px solid #e2e8f0',
                borderRadius: '12px',
                fontSize: '12px',
                color: '#0f172a',
                boxShadow: '0 8px 24px rgba(15, 23, 42, 0.08)',
              }}
            />
            <Bar dataKey="passed" fill="#10b981" radius={[6, 6, 0, 0]} name="Passed" />
            <Bar dataKey="failed" fill="#ef4444" radius={[6, 6, 0, 0]} name="Failed" />
          </BarChart>
        </ResponsiveContainer>
      </motion.div>
    </div>
  );
}
