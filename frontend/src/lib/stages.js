// Shared stage helpers: which competitor-grade engine each stage embeds,
// phase colours, and live status derivation from real /api/progress events.

// Engine embedded INSIDE a stage (keyed by the handler module's leading token).
export const STAGE_ENGINES = {
  'code-analyzer': { vendor: 'SmartShift', label: 'AI fail-safe code remediation + ATC gate', accent: 'amber' },
  'data-hygiene': { vendor: 'Syniti', label: 'Data spine — FK integrity · self-heal · ledger', accent: 'sky' },
  'data-migrator': { vendor: 'Natuvion', label: 'Selective carve-out (org/time-filtered)', accent: 'teal' },
};

export const PHASE_TONE = {
  ASSESS: 'indigo', PROVISION: 'violet', CODE: 'amber', CONFIG: 'teal',
  DATA_PREP: 'sky', DATA_LOAD: 'sky', VALIDATE: 'emerald', CUTOVER: 'rose', RUN: 'emerald',
};
export const PHASE_HEX = {
  indigo: '#6366f1', violet: '#8b5cf6', amber: '#f59e0b', teal: '#14b8a6',
  sky: '#0ea5e9', emerald: '#10b981', rose: '#f43f5e',
};

export function stageToken(handler) {
  return (handler || '').split('.')[0].toLowerCase();
}

export function prettyStage(handler, extra) {
  if (!handler) return extra?.gate ? `Gate · ${String(extra.gate).replace(/_/g, ' ')}` : 'Manual gate';
  return handler.replace('.handler', '').replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export function engineFor(handler) {
  return STAGE_ENGINES[stageToken(handler)] || null;
}

export function stepTone(s) {
  const u = String(s || '').toUpperCase();
  if (u.includes('COMPLETE') || u === 'SUCCESS' || u === 'OK' || u === 'DONE') return 'completed';
  if (u.includes('PROGRESS') || u === 'RUNNING') return 'running';
  if (u.includes('FAIL') || u.includes('ERROR')) return 'failed';
  return 'info';
}

/**
 * Best-effort live status per stage from real progress events (no fabrication).
 * Returns a function handler -> 'completed' | 'running' | 'queued' | 'idle'.
 */
export function makeStageStatus(steps = [], running = false) {
  const done = new Set();
  let runKey = null;
  for (const s of steps) {
    const tone = stepTone(s.status);
    const key = String(s.stage || '').toLowerCase();
    if (tone === 'completed') done.add(key);
    if (tone === 'running') runKey = key;
  }
  return (handler) => {
    const k = stageToken(handler);
    if (!k) return running ? 'queued' : 'idle';
    if (runKey && (runKey.includes(k) || k.includes(runKey))) return 'running';
    if ([...done].some((d) => d && (d.includes(k) || k.includes(d)))) return 'completed';
    return running ? 'queued' : 'idle';
  };
}
