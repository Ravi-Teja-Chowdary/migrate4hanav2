import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Activity, Download, Search, Filter, X, ChevronDown,
  AlertTriangle, CheckCircle2, Clock, Trash2, Pause, Play,
  FileJson, FileSpreadsheet, ArrowUpDown, AlertOctagon,
} from 'lucide-react';
import { STAGES, PHASES } from '../data/sampleData';

const WS_URL = import.meta.env.VITE_TELEMETRY_WS_URL || '';

const STATUS_CONFIG = {
  ERROR:       { color: 'text-red-400',    bg: 'bg-red-500/10',    border: 'border-red-500/20',    dot: 'bg-red-500',    priority: 0, icon: AlertOctagon },
  WARNING:     { color: 'text-amber-400',  bg: 'bg-amber-500/10',  border: 'border-amber-500/20',  dot: 'bg-amber-500',  priority: 1, icon: AlertTriangle },
  IN_PROGRESS: { color: 'text-yellow-400', bg: 'bg-yellow-500/10', border: 'border-yellow-500/20', dot: 'bg-yellow-500', priority: 2, icon: Clock },
  SUCCESS:     { color: 'text-green-400',  bg: 'bg-green-500/10',  border: 'border-green-500/20',  dot: 'bg-green-500',  priority: 3, icon: CheckCircle2 },
};

const MOCK_STAGES = [
  'discovery-engine', 'maintenance-planner', 'readiness-check', 'simplification-check',
  'code-analyzer', 'data-hygiene', 'data-migrator', 'config-replicator',
  'cutover-orchestrator', 'sum-orchestrator',
  'code-deployer', 'data-loader', 'config-applier', 'role-provisioner',
  'integration-activator', 'migration-validator', 'test-generator',
];

const MOCK_ACTIONS = [
  'Scanning custom programs via RFC_READ_TABLE',
  'Parsing stack.xml for target release validation',
  'Executing RC_COLLECT_ANALYSIS_DATA',
  'Running /SDF/RC_START_CHECK on simplification items',
  'Analyzing ABAP AST — 4200-line compiler active',
  'ATC check variant S4HANA_READINESS applied',
  'BP deduplication — Levenshtein fuzzy matching',
  'CVI_UPGRADE_CHECK_RESOLVE pre-validation',
  'Extracting SPRO customizing tables T001, T004, T009',
  'Mapping RFC destinations and IDoc partners',
  'Pre-conversion gate — validating all phases complete',
  'SUM/DMO monitoring — phase MAIN_IMPORT in progress',
  'SPAU worklist — 34 objects queued for adjustment',
  'FINS_MASS_DATA_MONITOR — BSIS to ACDOCA conversion',
  'Material Ledger activation — CKMSTART executing',
  'PFCG role creation — 15 single roles provisioned',
  'Reconciliation — GL balance variance check: 0.00',
  'Validation scorecard — 85/85 checks passed',
];

const MOCK_STATUSES = ['SUCCESS', 'SUCCESS', 'IN_PROGRESS', 'SUCCESS', 'WARNING', 'ERROR', 'SUCCESS', 'IN_PROGRESS'];

export default function Telemetry() {
  const [logs, setLogs] = useState([]);
  const [isLive, setIsLive] = useState(true);
  const [connectionStatus, setConnectionStatus] = useState('disconnected');
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [stageFilter, setStageFilter] = useState('ALL');
  const [phaseFilter, setPhaseFilter] = useState('ALL');
  const [sortBy, setSortBy] = useState('time_desc'); // time_desc, time_asc, priority
  const [showFilters, setShowFilters] = useState(false);
  const endOfLogsRef = useRef(null);
  const wsRef = useRef(null);
  const reconnectTimer = useRef(null);

  const addLog = useCallback((entry) => {
    setLogs(prev => [...prev.slice(-999), entry]); // Keep 1000 entries for the dedicated page
  }, []);

  // WebSocket / mock connection
  useEffect(() => {
    if (!isLive) return;

    if (WS_URL) {
      const connect = () => {
        setConnectionStatus('connecting');
        const ws = new WebSocket(WS_URL);
        wsRef.current = ws;
        ws.onopen = () => setConnectionStatus('connected');
        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            addLog({
              id: data.event_id || crypto.randomUUID?.() || Math.random().toString(36).substr(2, 12),
              timestamp: data.timestamp || new Date().toISOString(),
              stage: data.stage || 'unknown',
              action: data.action || '',
              status: data.status || 'IN_PROGRESS',
              details: data.details || {},
              payload: typeof data.details === 'object' ? JSON.stringify(data.details) : String(data.details || ''),
              duration_ms: data.duration_ms,
            });
          } catch {
            addLog({
              id: crypto.randomUUID?.() || Math.random().toString(36).substr(2, 12),
              timestamp: new Date().toISOString(),
              stage: 'system',
              action: 'message',
              status: 'IN_PROGRESS',
              details: {},
              payload: event.data,
            });
          }
        };
        ws.onclose = () => {
          setConnectionStatus('disconnected');
          wsRef.current = null;
          reconnectTimer.current = setTimeout(connect, 3000);
        };
        ws.onerror = () => ws.close();
      };
      connect();
      return () => {
        clearTimeout(reconnectTimer.current);
        if (wsRef.current) { wsRef.current.close(); wsRef.current = null; }
      };
    }

    // Mock mode
    setConnectionStatus('mock');
    let idx = 0;
    const mockInterval = setInterval(() => {
      const stageIdx = idx % MOCK_STAGES.length;
      const actionIdx = idx % MOCK_ACTIONS.length;
      const statusIdx = idx % MOCK_STATUSES.length;
      addLog({
        id: crypto.randomUUID?.() || Math.random().toString(36).substr(2, 12),
        timestamp: new Date().toISOString(),
        stage: MOCK_STAGES[stageIdx],
        action: MOCK_ACTIONS[actionIdx],
        status: MOCK_STATUSES[statusIdx],
        details: { mock: true, cycle: Math.floor(idx / MOCK_STAGES.length) + 1 },
        payload: JSON.stringify({ mock: true, cycle: Math.floor(idx / MOCK_STAGES.length) + 1 }),
        duration_ms: Math.floor(Math.random() * 5000) + 100,
      });
      idx++;
    }, 1500);
    return () => clearInterval(mockInterval);
  }, [isLive, addLog]);

  // Auto-scroll
  useEffect(() => {
    if (isLive && sortBy === 'time_desc' && endOfLogsRef.current) {
      endOfLogsRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, isLive, sortBy]);

  // Map stage name to phase
  function getPhaseForStage(stageName) {
    const stageObj = STAGES.find(s =>
      s.key === stageName ||
      s.key.replace(/_/g, '-') === stageName ||
      stageName.replace(/-/g, '_') === s.key
    );
    return stageObj ? stageObj.phaseNumber : null;
  }

  // Filtered + sorted logs
  const filteredLogs = useMemo(() => {
    let result = [...logs];

    // Search
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter(log =>
        log.action.toLowerCase().includes(q) ||
        log.stage.toLowerCase().includes(q) ||
        log.payload.toLowerCase().includes(q) ||
        log.status.toLowerCase().includes(q)
      );
    }

    // Status filter
    if (statusFilter !== 'ALL') {
      result = result.filter(log => log.status === statusFilter);
    }

    // Stage filter
    if (stageFilter !== 'ALL') {
      result = result.filter(log => log.stage === stageFilter);
    }

    // Phase filter
    if (phaseFilter !== 'ALL') {
      const phaseNum = parseInt(phaseFilter);
      result = result.filter(log => getPhaseForStage(log.stage) === phaseNum);
    }

    // Sort
    if (sortBy === 'priority') {
      result.sort((a, b) => {
        const pa = STATUS_CONFIG[a.status]?.priority ?? 99;
        const pb = STATUS_CONFIG[b.status]?.priority ?? 99;
        return pa - pb; // errors first
      });
    } else if (sortBy === 'time_asc') {
      result.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
    }
    // time_desc is default order (already chronological from append)

    return result;
  }, [logs, searchQuery, statusFilter, stageFilter, phaseFilter, sortBy]);

  // Unique stages in current logs
  const uniqueStages = useMemo(() => {
    const stages = new Set(logs.map(l => l.stage));
    return [...stages].sort();
  }, [logs]);

  // Stats
  const stats = useMemo(() => {
    const total = logs.length;
    const errors = logs.filter(l => l.status === 'ERROR').length;
    const warnings = logs.filter(l => l.status === 'WARNING').length;
    const successes = logs.filter(l => l.status === 'SUCCESS').length;
    const inProgress = logs.filter(l => l.status === 'IN_PROGRESS').length;
    return { total, errors, warnings, successes, inProgress };
  }, [logs]);

  // Download as JSON
  function downloadJSON() {
    const data = {
      export_timestamp: new Date().toISOString(),
      total_entries: filteredLogs.length,
      filters_applied: {
        search: searchQuery || null,
        status: statusFilter,
        stage: stageFilter,
        phase: phaseFilter,
        sort: sortBy,
      },
      summary: {
        total: stats.total,
        errors: stats.errors,
        warnings: stats.warnings,
        successes: stats.successes,
        in_progress: stats.inProgress,
      },
      entries: filteredLogs.map(log => ({
        timestamp: log.timestamp,
        stage: log.stage,
        phase: getPhaseForStage(log.stage),
        action: log.action,
        status: log.status,
        duration_ms: log.duration_ms || null,
        details: log.payload,
      })),
    };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `migrate4hana-telemetry-${new Date().toISOString().replace(/[:.]/g, '-')}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  // Download as CSV
  function downloadCSV() {
    const headers = ['Timestamp', 'Stage', 'Phase', 'Status', 'Action', 'Duration (ms)', 'Details'];
    const rows = filteredLogs.map(log => [
      log.timestamp,
      log.stage,
      getPhaseForStage(log.stage) || '',
      log.status,
      `"${(log.action || '').replace(/"/g, '""')}"`,
      log.duration_ms || '',
      `"${(log.payload || '').replace(/"/g, '""')}"`,
    ]);
    const csv = [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `migrate4hana-telemetry-${new Date().toISOString().replace(/[:.]/g, '-')}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const activeFilters = [statusFilter !== 'ALL', stageFilter !== 'ALL', phaseFilter !== 'ALL', searchQuery.trim()].filter(Boolean).length;

  return (
    <div className="p-8 space-y-6">
      {/* Header */}
      <div className="flex items-end justify-between">
        <div>
          <motion.h1
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            className="text-3xl font-bold text-white"
          >
            Live <span className="gradient-text">Telemetry</span>
          </motion.h1>
          <p className="text-sm text-white/40 mt-1">Real-time pipeline events with search, filter & export</p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full glass ${
            connectionStatus === 'connected' ? 'text-green-400' :
            connectionStatus === 'mock' ? 'text-blue-400' :
            connectionStatus === 'connecting' ? 'text-yellow-400' : 'text-red-400'
          }`}>
            <span className={`w-1.5 h-1.5 rounded-full animate-pulse ${
              connectionStatus === 'connected' ? 'bg-green-500' :
              connectionStatus === 'mock' ? 'bg-blue-500' :
              connectionStatus === 'connecting' ? 'bg-yellow-500' : 'bg-red-500'
            }`} />
            {connectionStatus === 'connected' ? 'Live' : connectionStatus === 'mock' ? 'Mock' : connectionStatus === 'connecting' ? 'Connecting' : 'Offline'}
          </span>
        </div>
      </div>

      {/* Stats bar */}
      <div className="grid grid-cols-5 gap-3">
        {[
          { label: 'Total Events', value: stats.total, color: 'text-white/70', bg: 'bg-white/5' },
          { label: 'Errors', value: stats.errors, color: 'text-red-400', bg: 'bg-red-500/10' },
          { label: 'Warnings', value: stats.warnings, color: 'text-amber-400', bg: 'bg-amber-500/10' },
          { label: 'In Progress', value: stats.inProgress, color: 'text-yellow-400', bg: 'bg-yellow-500/10' },
          { label: 'Success', value: stats.successes, color: 'text-green-400', bg: 'bg-green-500/10' },
        ].map((stat) => (
          <motion.div
            key={stat.label}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className={`glass rounded-xl p-3 text-center ${stat.bg} border border-white/5`}
          >
            <div className={`text-2xl font-bold font-mono ${stat.color}`}>{stat.value}</div>
            <div className="text-[10px] text-white/30 mt-0.5">{stat.label}</div>
          </motion.div>
        ))}
      </div>

      {/* Search + Controls bar */}
      <div className="glass rounded-xl p-3 flex items-center gap-3">
        {/* Search */}
        <div className="relative flex-1">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search events... (stage, action, status, details)"
            className="w-full pl-9 pr-8 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-white/80
                       placeholder:text-white/20 focus:outline-none focus:border-accent-blue/40 focus:bg-white/[0.07] transition-all"
          />
          {searchQuery && (
            <button onClick={() => setSearchQuery('')} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-white/30 hover:text-white/60">
              <X size={14} />
            </button>
          )}
        </div>

        {/* Filter toggle */}
        <button
          onClick={() => setShowFilters(!showFilters)}
          className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all border ${
            showFilters || activeFilters > 0
              ? 'bg-accent-blue/10 text-accent-blue border-accent-blue/20'
              : 'bg-white/5 text-white/40 border-white/10 hover:bg-white/10'
          }`}
        >
          <Filter size={13} />
          Filters
          {activeFilters > 0 && (
            <span className="ml-1 w-4 h-4 rounded-full bg-accent-blue text-white text-[10px] flex items-center justify-center">
              {activeFilters}
            </span>
          )}
        </button>

        {/* Sort */}
        <div className="relative">
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            className="appearance-none pl-7 pr-6 py-2 rounded-lg bg-white/5 border border-white/10 text-xs text-white/60
                       focus:outline-none focus:border-accent-blue/40 cursor-pointer"
          >
            <option value="time_desc">Newest First</option>
            <option value="time_asc">Oldest First</option>
            <option value="priority">Priority (Errors First)</option>
          </select>
          <ArrowUpDown size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-white/30 pointer-events-none" />
          <ChevronDown size={12} className="absolute right-2 top-1/2 -translate-y-1/2 text-white/30 pointer-events-none" />
        </div>

        {/* Divider */}
        <div className="w-px h-6 bg-white/10" />

        {/* Pause/Resume */}
        <button
          onClick={() => setIsLive(!isLive)}
          className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all border ${
            isLive ? 'bg-red-500/10 text-red-400 border-red-500/20' : 'bg-green-500/10 text-green-400 border-green-500/20'
          }`}
        >
          {isLive ? <><Pause size={12} /> Pause</> : <><Play size={12} /> Resume</>}
        </button>

        {/* Clear */}
        <button
          onClick={() => setLogs([])}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-white/5 text-white/40 text-xs border border-white/10 hover:bg-white/10 transition-all"
        >
          <Trash2 size={12} /> Clear
        </button>

        {/* Download buttons */}
        <button
          onClick={downloadJSON}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-accent-blue/10 text-accent-blue text-xs font-medium
                     border border-accent-blue/20 hover:bg-accent-blue/20 transition-all"
        >
          <FileJson size={13} /> JSON
        </button>
        <button
          onClick={downloadCSV}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-accent-green/10 text-accent-green text-xs font-medium
                     border border-accent-green/20 hover:bg-accent-green/20 transition-all"
        >
          <FileSpreadsheet size={13} /> CSV
        </button>
      </div>

      {/* Filter dropdowns (expandable) */}
      <AnimatePresence>
        {showFilters && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="overflow-hidden"
          >
            <div className="glass rounded-xl p-4 flex items-center gap-6">
              {/* Status filter */}
              <div className="flex items-center gap-2">
                <label className="text-[10px] text-white/30 uppercase tracking-wider font-medium">Status</label>
                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  className="appearance-none px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-xs text-white/60 focus:outline-none cursor-pointer"
                >
                  <option value="ALL">All</option>
                  <option value="ERROR">Errors</option>
                  <option value="WARNING">Warnings</option>
                  <option value="IN_PROGRESS">In Progress</option>
                  <option value="SUCCESS">Success</option>
                </select>
              </div>

              {/* Phase filter */}
              <div className="flex items-center gap-2">
                <label className="text-[10px] text-white/30 uppercase tracking-wider font-medium">Phase</label>
                <select
                  value={phaseFilter}
                  onChange={(e) => setPhaseFilter(e.target.value)}
                  className="appearance-none px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-xs text-white/60 focus:outline-none cursor-pointer"
                >
                  <option value="ALL">All Phases</option>
                  {PHASES.map(p => (
                    <option key={p.id} value={p.id}>Phase {p.id}: {p.name}</option>
                  ))}
                </select>
              </div>

              {/* Stage filter */}
              <div className="flex items-center gap-2">
                <label className="text-[10px] text-white/30 uppercase tracking-wider font-medium">Stage</label>
                <select
                  value={stageFilter}
                  onChange={(e) => setStageFilter(e.target.value)}
                  className="appearance-none px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-xs text-white/60 focus:outline-none cursor-pointer max-w-[200px]"
                >
                  <option value="ALL">All Stages</option>
                  {uniqueStages.map(s => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>

              {/* Clear filters */}
              {activeFilters > 0 && (
                <button
                  onClick={() => { setStatusFilter('ALL'); setStageFilter('ALL'); setPhaseFilter('ALL'); setSearchQuery(''); }}
                  className="ml-auto text-xs text-accent-blue hover:text-accent-blue/80 transition-colors"
                >
                  Clear all filters
                </button>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Results count */}
      <div className="flex items-center justify-between text-xs text-white/30">
        <span>
          Showing {filteredLogs.length} of {logs.length} events
          {activeFilters > 0 && <span className="text-accent-blue ml-1">({activeFilters} filter{activeFilters > 1 ? 's' : ''} active)</span>}
        </span>
        <span className="font-mono">
          {logs.length > 0 && `${logs[0].timestamp.split('T')[1]?.slice(0, 8) || ''} — ${logs[logs.length - 1].timestamp.split('T')[1]?.slice(0, 8) || ''}`}
        </span>
      </div>

      {/* Log table */}
      <div className="bg-gray-900/80 border border-gray-700/50 rounded-xl overflow-hidden shadow-2xl">
        {/* Table header */}
        <div className="grid grid-cols-[140px_160px_90px_1fr_80px] gap-3 px-4 py-2.5 bg-white/[0.03] border-b border-white/5 text-[10px] text-white/30 uppercase tracking-wider font-semibold">
          <span>Timestamp</span>
          <span>Stage</span>
          <span>Status</span>
          <span>Action / Details</span>
          <span className="text-right">Duration</span>
        </div>

        {/* Log entries */}
        <div className="overflow-y-auto max-h-[calc(100vh-480px)] min-h-[300px]">
          {filteredLogs.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-64 text-white/20">
              {logs.length === 0 ? (
                <>
                  <Activity size={32} className="mb-3 opacity-30" />
                  <span className="text-sm">Waiting for telemetry events...</span>
                  <span className="text-xs mt-1 text-white/10">Events appear here as the pipeline executes</span>
                </>
              ) : (
                <>
                  <Search size={32} className="mb-3 opacity-30" />
                  <span className="text-sm">No events match your filters</span>
                  <button
                    onClick={() => { setStatusFilter('ALL'); setStageFilter('ALL'); setPhaseFilter('ALL'); setSearchQuery(''); }}
                    className="text-xs text-accent-blue mt-2 hover:underline"
                  >
                    Clear all filters
                  </button>
                </>
              )}
            </div>
          ) : (
            filteredLogs.map((log) => {
              const sc = STATUS_CONFIG[log.status] || STATUS_CONFIG.IN_PROGRESS;
              const StatusIcon = sc.icon;
              return (
                <div
                  key={log.id}
                  className={`grid grid-cols-[140px_160px_90px_1fr_80px] gap-3 px-4 py-2 border-b border-white/[0.03]
                    hover:bg-white/[0.03] transition-colors text-sm ${log.status === 'ERROR' ? 'bg-red-500/[0.03]' : ''}`}
                >
                  {/* Timestamp */}
                  <span className="text-white/30 font-mono text-xs self-center">
                    {log.timestamp.split('T')[1]?.slice(0, 12) || log.timestamp}
                  </span>

                  {/* Stage */}
                  <span className="text-blue-400/80 font-medium text-xs self-center truncate" title={log.stage}>
                    {log.stage}
                  </span>

                  {/* Status */}
                  <span className={`flex items-center gap-1.5 text-xs font-semibold self-center ${sc.color}`}>
                    <StatusIcon size={12} />
                    {log.status}
                  </span>

                  {/* Action */}
                  <span className="text-white/60 text-xs self-center truncate" title={`${log.action}${log.payload ? ': ' + log.payload : ''}`}>
                    {log.action}
                    {log.payload && <span className="text-white/20 ml-1">{log.payload.length > 80 ? log.payload.slice(0, 80) + '...' : log.payload}</span>}
                  </span>

                  {/* Duration */}
                  <span className="text-white/20 font-mono text-xs text-right self-center">
                    {log.duration_ms != null ? `${(log.duration_ms / 1000).toFixed(1)}s` : '—'}
                  </span>
                </div>
              );
            })
          )}
          <div ref={endOfLogsRef} />
        </div>
      </div>

      {/* Download reminder for errors */}
      <AnimatePresence>
        {stats.errors > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="glass rounded-xl p-4 flex items-center gap-3 border border-red-500/20 bg-red-500/5"
          >
            <AlertTriangle size={18} className="text-red-400 shrink-0" />
            <div className="flex-1">
              <p className="text-sm text-red-300 font-medium">{stats.errors} error{stats.errors > 1 ? 's' : ''} detected</p>
              <p className="text-xs text-red-300/50 mt-0.5">Download the report filtered by errors to prioritize fixes</p>
            </div>
            <button
              onClick={() => { setStatusFilter('ERROR'); setSortBy('priority'); downloadJSON(); }}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-red-500/10 text-red-400 text-xs font-medium
                         border border-red-500/20 hover:bg-red-500/20 transition-all shrink-0"
            >
              <Download size={13} /> Download Errors Report
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
