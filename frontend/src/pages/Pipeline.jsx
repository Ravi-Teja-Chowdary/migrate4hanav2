import { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Play, Square, RotateCcw, CheckCircle2, Clock, AlertTriangle,
  Code, Database, Settings, Shield, Plug, Search,
  PlayCircle, Upload, HardDrive, Wrench, UserCheck, Zap,
  ClipboardCheck, ShieldCheck, ListChecks, ShieldAlert, DollarSign,
  TestTube2, Rocket, Activity, Download,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { STAGES, PHASES, PHASE_COLORS, SAMPLE_RUN, getStageDuration } from '../data/sampleData';
import { apiFetch, getAuthUrl } from '../api';
import LogViewer from '../components/LogViewer';

const ICONS = {
  Search, Code, Database, Settings, Shield, Plug, PlayCircle, Upload, HardDrive, Wrench, UserCheck, Zap, CheckCircle2,
  ClipboardCheck, ShieldCheck, ListChecks, ShieldAlert, DollarSign, TestTube2, Rocket,
};

const PHASE_DOT_COLORS = {
  blue: 'bg-blue-500',
  purple: 'bg-purple-500',
  amber: 'bg-amber-500',
  cyan: 'bg-cyan-500',
  green: 'bg-green-500',
};

function StageNode({ stage, status, isCurrent, elapsed, isLast }) {
  const Icon = ICONS[stage.icon] || Zap;
  const isCompleted = status === 'completed';
  const isRunning = status === 'running';
  const isPending = status === 'pending';
  const durations = getStageDuration();

  return (
    <motion.div
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      className="flex items-stretch gap-4"
    >
      {/* Timeline bar */}
      <div className="flex flex-col items-center w-10 shrink-0">
        <motion.div
          className="w-10 h-10 rounded-xl flex items-center justify-center relative"
          style={{
            backgroundColor: isCompleted ? `${stage.color}20` : isRunning ? `${stage.color}15` : 'rgba(15, 23, 42,0.03)',
            border: isRunning ? `2px solid ${stage.color}` : '1px solid rgba(15, 23, 42,0.05)',
          }}
          animate={isRunning ? { boxShadow: [`0 0 0px ${stage.color}00`, `0 0 20px ${stage.color}40`, `0 0 0px ${stage.color}00`] } : {}}
          transition={isRunning ? { duration: 2, repeat: Infinity } : {}}
        >
          {isCompleted ? (
            <CheckCircle2 size={18} style={{ color: stage.color }} />
          ) : isRunning ? (
            <motion.div animate={{ rotate: 360 }} transition={{ duration: 2, repeat: Infinity, ease: 'linear' }}>
              <Clock size={18} style={{ color: stage.color }} />
            </motion.div>
          ) : (
            <Icon size={16} className="text-slate-400" />
          )}
        </motion.div>
        {!isLast && (
          <div className="w-px flex-1 min-h-[16px]" style={{
            background: isCompleted
              ? `linear-gradient(180deg, ${stage.color}50, ${stage.color}20)`
              : 'rgba(15, 23, 42,0.05)',
          }} />
        )}
      </div>

      {/* Content */}
      <div className={`flex-1 pb-4 ${isPending ? 'opacity-30' : ''}`}>
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-slate-400">Stage {stage.id}</span>
          {stage.key === 'pre_conversion_gate' && (
            <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-accent-amber/10 text-accent-amber font-medium">
              GATE
            </span>
          )}
        </div>
        <h3 className={`text-sm font-medium mt-0.5 ${isRunning ? 'text-slate-900' : isCompleted ? 'text-slate-700' : 'text-slate-400'}`}>
          {stage.name}
        </h3>
        {isRunning && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            className="mt-2"
          >
            <div className="h-1 rounded-full bg-slate-50 overflow-hidden">
              <motion.div
                className="h-full rounded-full"
                style={{ background: `linear-gradient(90deg, ${stage.color}, ${stage.color}80)` }}
                animate={{ width: ['0%', '100%'] }}
                transition={{ duration: durations[stage.key] || 0.5, ease: 'easeInOut' }}
              />
            </div>
            <p className="text-[10px] text-slate-400 mt-1 font-mono">Processing...</p>
          </motion.div>
        )}
        {isCompleted && elapsed != null && (
          <p className="text-[10px] text-slate-400 mt-0.5 font-mono">{elapsed.toFixed(1)}s</p>
        )}
      </div>
    </motion.div>
  );
}

export default function Pipeline() {
  const [pipelineState, setPipelineState] = useState('idle'); // idle | running | completed
  const [currentStage, setCurrentStage] = useState(-1);
  const [stageStatuses, setStageStatuses] = useState({});
  const [elapsed, setElapsed] = useState({});
  const [apiMode, setApiMode] = useState(null); // null | 'assess' | 'ecc_full'
  const [apiStatus, setApiStatus] = useState('idle');
  const [apiError, setApiError] = useState(null);
  const timerRef = useRef(null);
  const pollRef = useRef(null);

  const durations = getStageDuration();

  // Get stages for a given mode
  function getStagesForMode(mode) {
    if (mode === 'assess') return STAGES.filter((s) => s.phaseNumber <= 2);
    if (mode === 'ecc_full') return STAGES.filter((s) => s.phaseNumber <= 2);
    return STAGES;
  }

  // --- Visual Stage Runner (runs ALL stages continuously, no pauses between phases) ---
  function startVisualRun(mode) {
    const stages = getStagesForMode(mode);
    setPipelineState('running');
    setCurrentStage(0);
    setApiMode(mode);
    setStageStatuses({});
    setElapsed({});
    runVisualStage(stages, 0);
  }

  function runVisualStage(stages, idx) {
    if (idx >= stages.length) {
      setPipelineState('completed');
      setCurrentStage(-1);
      return;
    }
    const stage = stages[idx];
    setCurrentStage(STAGES.findIndex((s) => s.key === stage.key));
    setStageStatuses((prev) => ({ ...prev, [stage.key]: 'running' }));

    const duration = (durations[stage.key] || 0.3) * 1000;
    timerRef.current = setTimeout(() => {
      setStageStatuses((prev) => ({ ...prev, [stage.key]: 'completed' }));
      setElapsed((prev) => ({ ...prev, [stage.key]: duration / 1000 }));
      // Immediately proceed to next stage — no gates, no pauses
      runVisualStage(stages, idx + 1);
    }, duration);
  }

  // --- API Pipeline Triggers ---
  async function triggerAssess() {
    setApiStatus('polling');
    setApiError(null);
    try {
      const r = await apiFetch('/api/pipeline/assess', { method: 'POST' });
      const data = await r.json();
      if (data.error) { setApiError(data.error); setApiStatus('error'); return; }
      startVisualRun('assess');
      startPolling();
    } catch {
      setApiError('Cannot reach API server. Start it with: python api_server.py');
      setApiStatus('error');
    }
  }

  async function triggerEccFull() {
    setApiStatus('polling');
    setApiError(null);
    try {
      const r = await apiFetch('/api/pipeline/ecc_full', { method: 'POST' });
      const data = await r.json();
      if (data.error) { setApiError(data.error); setApiStatus('error'); return; }
      startVisualRun('ecc_full');
      startPolling();
    } catch {
      setApiError('Cannot reach API server. Start it with: python api_server.py');
      setApiStatus('error');
    }
  }

  function startPolling() {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const r = await apiFetch('/api/status');
        const data = await r.json();
        if (data.status === 'completed' || data.status === 'failed') {
          clearInterval(pollRef.current);
          setApiStatus(data.status === 'completed' ? 'done' : 'error');
          if (data.status === 'failed') setApiError(data.error || 'Pipeline failed');
        }
      } catch { /* keep polling */ }
    }, 3000);
  }

  function resetPipeline() {
    clearTimeout(timerRef.current);
    clearInterval(pollRef.current);
    setPipelineState('idle');
    setCurrentStage(-1);
    setStageStatuses({});
    setElapsed({});
    setApiMode(null);
    setApiStatus('idle');
    setApiError(null);
  }

  useEffect(() => {
    return () => { clearTimeout(timerRef.current); clearInterval(pollRef.current); };
  }, []);

  const completedCount = Object.values(stageStatuses).filter((s) => s === 'completed').length;
  const totalStages = apiMode === 'assess' ? 8 : apiMode === 'ecc_full' ? 8 : 17;

  const modeLabel = {
    assess: 'Running Assessment (Phases 1-2, read-only)...',
    ecc_full: 'Running Full ECC Assessment (Phases 1-2 + Report Generation)...',
  };

  return (
    <div className="p-8 max-w-3xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex items-end justify-between">
        <div>
          <motion.h1
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            className="text-3xl font-bold text-slate-900"
          >
            Migration <span className="gradient-text">Pipeline</span>
          </motion.h1>
          <p className="text-sm text-slate-400 mt-1">SAP Activate assessment — live ECC data extraction & analysis</p>
        </div>

        <div className="flex items-center gap-2">
          {pipelineState === 'idle' && (
            <>
              <motion.button
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                onClick={triggerAssess}
                className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-accent-blue/10 text-accent-blue text-sm font-semibold
                           hover:bg-accent-blue/20 transition-all duration-300 border border-accent-blue/20"
              >
                <Search size={15} /> Assess
              </motion.button>
              <motion.button
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: 0.015 }}
                onClick={triggerEccFull}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-indigo-500 to-accent-blue
                           text-white text-sm font-bold shadow-lg shadow-indigo-500/25 hover:from-indigo-600 hover:to-blue-600
                           transition-all duration-300 animate-pulse-glow"
              >
                <Rocket size={15} /> Run Full Assessment
              </motion.button>
            </>
          )}
          {pipelineState === 'running' && (
            <button
              onClick={resetPipeline}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-accent-red/10 text-accent-red text-sm font-medium
                         hover:bg-accent-red/20 transition-all border border-accent-red/20"
            >
              <Square size={14} /> Stop
            </button>
          )}
          {pipelineState === 'completed' && (
            <button
              onClick={resetPipeline}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-slate-50 text-slate-500 text-sm font-medium
                         hover:bg-slate-100 transition-all border border-slate-200"
            >
              <RotateCcw size={14} /> Reset
            </button>
          )}
        </div>
      </div>

      {/* Error banner */}
      <AnimatePresence>
        {apiError && (
          <motion.div
            initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
            className="glass rounded-xl p-3 flex items-center gap-2 border border-accent-red/20"
          >
            <AlertTriangle size={14} className="text-accent-red shrink-0" />
            <p className="text-xs text-accent-red">{apiError}</p>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Mode indicator */}
      {apiMode && pipelineState === 'running' && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}
          className="glass rounded-xl p-3 flex items-center justify-between text-xs"
        >
          <div className="flex items-center gap-2">
            <div className="pulse-dot bg-accent-cyan" />
            <span className="text-slate-500">{modeLabel[apiMode]}</span>
          </div>
        </motion.div>
      )}

      {/* Progress bar */}
      <div className="glass rounded-2xl p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-slate-400">Overall Progress</span>
          <span className="text-xs font-mono text-slate-500">{completedCount}/{totalStages} stages</span>
        </div>
        <div className="h-2 rounded-full bg-slate-50 overflow-hidden">
          <motion.div
            className="h-full rounded-full bg-gradient-to-r from-accent-blue via-accent-cyan to-accent-green"
            animate={{ width: `${(completedCount / totalStages) * 100}%` }}
            transition={{ duration: 0.5, ease: [0.4, 0, 0.2, 1] }}
          />
        </div>
      </div>

      {/* Render phases — all phases flow continuously */}
      {PHASES.map((phase) => {
        const phaseStages = STAGES.filter((s) => s.phaseNumber === phase.id);
        const isOutOfScope = (apiMode === 'assess' && phase.id > 2)
          || (apiMode === 'ecc_full' && phase.id > 2);

        return (
          <div key={phase.id}>
            {/* Phase container */}
            <div className={`glass rounded-2xl p-6 ${isOutOfScope ? 'opacity-20' : ''}`}>
              <div className="flex items-center gap-3 mb-6">
                <div className={`w-2 h-2 rounded-full ${PHASE_DOT_COLORS[phase.color] || 'bg-slate-100'}`} />
                <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wider">{phase.name}</h2>
                <span className="text-[10px] text-slate-400 font-medium">{phase.subtitle}</span>
                <div className="h-px flex-1 bg-slate-50" />
                {/* Phase status badge */}
                {(() => {
                  const allDone = phaseStages.every(s => stageStatuses[s.key] === 'completed');
                  const anyRunning = phaseStages.some(s => stageStatuses[s.key] === 'running');
                  if (allDone) return (
                    <span className="text-[9px] px-2 py-0.5 rounded-full bg-accent-green/10 text-accent-green font-semibold flex items-center gap-1">
                      <CheckCircle2 size={10} /> COMPLETE
                    </span>
                  );
                  if (anyRunning) return (
                    <span className="text-[9px] px-2 py-0.5 rounded-full bg-accent-cyan/10 text-accent-cyan font-semibold">
                      RUNNING
                    </span>
                  );
                  if (isOutOfScope) return (
                    <span className="text-[9px] px-2 py-0.5 rounded-full bg-slate-50 text-slate-400 font-semibold">
                      NOT IN SCOPE
                    </span>
                  );
                  return null;
                })()}
              </div>
              {phaseStages.map((stage, idx) => (
                <StageNode
                  key={stage.key}
                  stage={stage}
                  status={stageStatuses[stage.key] || 'pending'}
                  isCurrent={STAGES[currentStage]?.key === stage.key}
                  elapsed={elapsed[stage.key]}
                  isLast={idx === phaseStages.length - 1}
                />
              ))}
            </div>
          </div>
        );
      })}

      {/* Embedded Live Log Stream */}
      {(pipelineState === 'running' || pipelineState === 'completed') && (
        <div className="glass rounded-2xl p-6">
          <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-4">Live Log Stream</h2>
          <LogViewer />
        </div>
      )}

      {/* Completion banner */}
      <AnimatePresence>
        {pipelineState === 'completed' && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95 }}
            className="glass rounded-2xl p-8 text-center relative overflow-hidden"
          >
            <div className="absolute inset-0 bg-gradient-to-br from-accent-green/5 to-accent-blue/5" />
            <div className="relative">
              <motion.div
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ type: 'spring', stiffness: 200, delay: 0.2 }}
                className="w-16 h-16 mx-auto rounded-2xl bg-accent-green/10 flex items-center justify-center mb-4"
              >
                <CheckCircle2 size={32} className="text-accent-green" />
              </motion.div>
              <h3 className="text-xl font-bold text-slate-900">
                {apiMode === 'assess' ? 'Assessment Complete' : 'Full ECC Assessment Complete'}
              </h3>
              <p className="text-sm text-slate-400 mt-1">
                {apiMode === 'assess'
                  ? 'Phases 1-2 finished. Review results on the Scorecard and Report pages.'
                  : 'Full ECC assessment finished. Review results on the Scorecard and Report pages.'}
              </p>
              <div className="flex items-center justify-center gap-3 mt-5">
                <button
                  onClick={async () => {
                    const url = await getAuthUrl('/api/runs/latest/pdf');
                    window.open(url, '_blank');
                  }}
                  className="flex items-center gap-1.5 px-5 py-2.5 rounded-xl bg-gradient-to-r from-accent-green to-accent-cyan
                             text-white text-sm font-bold shadow-lg shadow-accent-green/25 hover:from-green-600 hover:to-cyan-600
                             transition-all duration-300 animate-pulse-glow"
                >
                  <Download size={15} /> Download Report
                </button>
                <Link
                  to="/telemetry"
                  className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-accent-blue/10 text-accent-blue text-xs font-medium border border-accent-blue/20 hover:bg-accent-blue/20 transition-all"
                >
                  <Activity size={13} /> View Telemetry Report
                </Link>
                <Link
                  to="/scorecard"
                  className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-accent-green/10 text-accent-green text-xs font-medium border border-accent-green/20 hover:bg-accent-green/20 transition-all"
                >
                  <CheckCircle2 size={13} /> View Scorecard
                </Link>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
