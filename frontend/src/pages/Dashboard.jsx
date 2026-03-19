import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import {
  Code, Database, Settings, Shield, Plug, Search,
  PlayCircle, Upload, HardDrive, Wrench, UserCheck, Zap, CheckCircle2,
  Activity, Clock, Building2, ArrowRight, BarChart2, TrendingDown,
  ClipboardCheck, ShieldCheck, ListChecks, ShieldAlert, DollarSign,
  TestTube2, Rocket,
} from 'lucide-react';
import MetricCard from '../components/MetricCard';
import StageCard from '../components/StageCard';
import { STAGES, PHASES, PHASE_COLORS, SAMPLE_RUN, getStageStatus } from '../data/sampleData';

const ICONS = {
  Search, Code, Database, Settings, Shield, Plug, PlayCircle, Upload, HardDrive, Wrench, UserCheck, Zap, CheckCircle2,
  ClipboardCheck, ShieldCheck, ListChecks, ShieldAlert, DollarSign, TestTube2, Rocket,
};

const PHASE_GRADIENT = {
  blue: 'from-blue-500/30 to-blue-500/5',
  purple: 'from-purple-500/30 to-purple-500/5',
  amber: 'from-amber-500/30 to-amber-500/5',
  cyan: 'from-cyan-500/30 to-cyan-500/5',
  green: 'from-green-500/30 to-green-500/5',
};

const PHASE_DOT = {
  blue: 'bg-blue-500',
  purple: 'bg-purple-500',
  amber: 'bg-amber-500',
  cyan: 'bg-cyan-500',
  green: 'bg-green-500',
};

const PHASE_LINE = {
  blue: 'from-blue-500/30',
  purple: 'from-purple-500/30',
  amber: 'from-amber-500/30',
  cyan: 'from-cyan-500/30',
  green: 'from-green-500/30',
};

export default function Dashboard() {
  const run = SAMPLE_RUN;
  const disc = run.results.discovery.summary;
  const code = run.results.code_analysis;
  const data = run.results.data_assessment.results;
  const sc = run.results.validation_scorecard.scorecard;
  const navigate = useNavigate();

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex items-end justify-between">
        <div>
          <motion.h1
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            className="text-3xl font-bold text-white"
          >
            Migration <span className="gradient-text">Dashboard</span>
          </motion.h1>
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.1 }}
            className="text-sm text-white/40 mt-1 flex items-center gap-2"
          >
            <Building2 size={14} />
            {run.company}
          </motion.p>
        </div>

        <motion.button
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.2 }}
          onClick={() => navigate('/pipeline')}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-accent-blue/10 text-accent-blue text-sm font-medium
                     hover:bg-accent-blue/20 transition-all duration-300 border border-accent-blue/20 hover:border-accent-blue/40"
        >
          <PlayCircle size={16} />
          Run Pipeline
          <ArrowRight size={14} />
        </motion.button>
      </div>

      {/* Key Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Custom Programs" value={disc.total_programs} icon={Code} color="#3b82f6" delay={0} />
        <MetricCard label="Finance Records" value={data.finance_lines} icon={Database} color="#10b981" delay={0.05} />
        <MetricCard label="Business Partners" value={data.bp_created} icon={UserCheck} color="#8b5cf6" delay={0.1} />
        <MetricCard
          label="GO-LIVE Score"
          value={sc.score}
          sub={`Grade ${sc.grade} · ${sc.recommendation}`}
          icon={CheckCircle2}
          color="#10b981"
          delay={0.15}
        />
      </div>

      {/* Additional metrics row */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <MetricCard label="Code Issues" value={code.total_issues} sub={`${code.critical_issues} critical`} icon={Code} color="#ef4444" delay={0.1} />
        <MetricCard label="Auto-Fixed" value={code.auto_remediated} sub={`${code.fix_rate}% fix rate`} icon={Wrench} color="#10b981" delay={0.12} />
        <MetricCard label="PFCG Roles" value={disc.total_roles} sub={`${disc.total_users} users`} icon={Shield} color="#8b5cf6" delay={0.14} />
        <MetricCard label="RFC Destinations" value={disc.rfc_destinations} icon={Plug} color="#ef4444" delay={0.16} />
        <MetricCard label="RFC Calls" value={run.rfc_calls} sub={`${run.duration}s total`} icon={Activity} color="#06b6d4" delay={0.18} />
      </div>

      {/* SAP Activate Compliance Banner */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="glass rounded-2xl p-4 relative overflow-hidden"
      >
        <div className="absolute inset-0 bg-gradient-to-r from-accent-blue/5 via-accent-purple/5 to-accent-green/5" />
        <div className="relative flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-accent-blue/10 flex items-center justify-center">
              <ShieldCheck size={16} className="text-accent-blue" />
            </div>
            <span className="text-xs font-semibold text-white/70 uppercase tracking-wider">SAP Activate Compliance</span>
          </div>
          <div className="h-6 w-px bg-white/10 hidden md:block" />
          <div className="flex items-center gap-3 flex-wrap text-[11px] font-medium text-white/50">
            <span className="flex items-center gap-1"><CheckCircle2 size={11} className="text-accent-green" /> Maintenance Planner</span>
            <span className="text-white/15">|</span>
            <span className="flex items-center gap-1"><CheckCircle2 size={11} className="text-accent-green" /> Readiness Check</span>
            <span className="text-white/15">|</span>
            <span className="flex items-center gap-1"><CheckCircle2 size={11} className="text-accent-green" /> SI-Check</span>
            <span className="text-white/15">|</span>
            <span className="flex items-center gap-1"><CheckCircle2 size={11} className="text-accent-green" /> SUM/DMO</span>
            <span className="text-white/15">|</span>
            <span className="flex items-center gap-1"><CheckCircle2 size={11} className="text-accent-green" /> FINS Monitor</span>
          </div>
        </div>
      </motion.div>

      {/* Process Mining Insights */}
      <div className="flex items-center gap-4 mt-8">
        <h2 className="text-lg font-semibold text-white/80 shrink-0 flex items-center gap-2">
          <BarChart2 size={18} className="text-accent-blue" /> Process Mining Insights
        </h2>
        <div className="h-px flex-1 bg-gradient-to-r from-accent-blue/30 to-transparent" />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Active T-Codes" value={disc.active_tcodes || 142} sub="Last 6 months (ST03N)" icon={Activity} color="#f59e0b" delay={0.2} />
        <MetricCard label="Unused Z-Programs" value={disc.unused_zprograms || 312} sub="Candidates for Deletion" icon={TrendingDown} color="#ef4444" delay={0.22} />
        <MetricCard label="Custom Tables Accessed" value={disc.active_ztables || 89} sub="High Priority for HANA" icon={Database} color="#8b5cf6" delay={0.24} />
        <MetricCard label="Fiori Replacements" value={disc.fiori_mapped || 85} sub="Standard Apps Found" icon={Zap} color="#10b981" delay={0.26} />
      </div>

      {/* 5-Phase Stage Layout */}
      {PHASES.map((phase, phaseIdx) => {
        const phaseStages = STAGES.filter((s) => s.phaseNumber === phase.id);
        return (
          <div key={phase.id}>
            {/* Phase separator */}
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-3">
                <div className={`w-2 h-2 rounded-full ${PHASE_DOT[phase.color] || 'bg-white/30'}`} />
                <h2 className="text-lg font-semibold text-white/80 shrink-0">{phase.name}</h2>
                <span className="text-xs text-white/30 font-medium">{phase.subtitle}</span>
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-white/5 text-white/30 font-mono">
                  {phaseStages.length} stages
                </span>
              </div>
              <div className={`h-px flex-1 bg-gradient-to-r ${PHASE_LINE[phase.color] || 'from-white/10'} to-transparent`} />
            </div>

            {/* Phase Stages */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 mt-4 mb-8">
              {phaseStages.map((stage, i) => (
                <StageCard
                  key={stage.key}
                  stage={{ ...stage, icon: ICONS[stage.icon] }}
                  status={getStageStatus(run, stage.key)}
                  delay={phaseIdx * 0.05 + i * 0.03}
                />
              ))}
            </div>
          </div>
        );
      })}

      {/* Quick scorecard banner */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
        onClick={() => navigate('/scorecard')}
        className="glass glass-hover rounded-2xl p-6 cursor-pointer relative overflow-hidden"
      >
        <div className="absolute inset-0 bg-gradient-to-r from-accent-green/5 via-transparent to-accent-blue/5" />
        <div className="relative flex items-center justify-between">
          <div className="flex items-center gap-6">
            <div className="w-16 h-16 rounded-2xl bg-accent-green/10 flex items-center justify-center">
              <span className="text-3xl font-bold text-accent-green">{sc.grade}</span>
            </div>
            <div>
              <h3 className="text-lg font-semibold text-white">{sc.recommendation}</h3>
              <p className="text-sm text-white/40">
                {sc.total_passed}/{sc.total_checks} checks passed · Score: {sc.score}
              </p>
            </div>
          </div>
          <ArrowRight size={20} className="text-white/20 group-hover:text-white/50 transition-colors" />
        </div>
      </motion.div>

      {/* Run info */}
      <div className="flex items-center justify-center gap-6 text-[11px] text-white/20 font-mono">
        <span className="flex items-center gap-1.5"><Clock size={11} /> {run.timestamp}</span>
        <span>·</span>
        <span>Run: {run.id}</span>
        <span>·</span>
        <span>{run.rfc_calls.toLocaleString()} RFC calls</span>
      </div>
    </div>
  );
}
