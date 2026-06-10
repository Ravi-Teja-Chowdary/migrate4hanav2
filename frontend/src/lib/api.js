// Real API client for the Migrate4HANA FastAPI backend (api_server.py on :8000).
// In dev, Vite proxies /api -> http://localhost:8000 (see vite.config.js),
// so we use relative paths and never touch mock data.

export const API_BASE = import.meta.env.VITE_API_BASE ?? '';

let _token = null;
let _tokenPromise = null;

async function getToken() {
  if (_token) return _token;
  if (_tokenPromise) return _tokenPromise;
  _tokenPromise = fetch(`${API_BASE}/api/auth/token`, { method: 'POST' })
    .then((r) => (r.ok ? r.json() : null))
    .then((d) => { _token = d?.token || null; _tokenPromise = null; return _token; })
    .catch(() => { _tokenPromise = null; return null; });
  return _tokenPromise;
}

/** Authenticated fetch returning parsed JSON. Throws on network/HTTP error. */
export async function apiFetch(path, opts = {}) {
  const token = await getToken();
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}${path}`, { ...opts, headers });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!res.ok) {
    const msg = data?.detail || data?.error || `HTTP ${res.status}`;
    const err = new Error(msg);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

export async function authUrl(path) {
  const token = await getToken();
  return `${API_BASE}${path}${path.includes('?') ? '&' : '?'}token=${token || ''}`;
}

/** Liveness probe — used to show an honest "API offline" banner. */
export async function ping() {
  try {
    const r = await fetch(`${API_BASE}/api/health`);
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}

// ── typed endpoint helpers ────────────────────────────────────────────────
export const api = {
  health: () => apiFetch('/api/health'),

  // ── Connections (interactive) ──
  connections: () => apiFetch('/api/connections'),
  eccStatus:   () => apiFetch('/api/connections/ecc/status'),
  saveEcc:     (payload) => apiFetch('/api/connections/ecc',
                  { method: 'POST', body: JSON.stringify(payload) }),
  testEcc:     (payload) => apiFetch('/api/connections/ecc/test',
                  { method: 'POST', body: JSON.stringify(payload) }),
  saveS4:      (payload) => apiFetch('/api/connections/s4hana',
                  { method: 'POST', body: JSON.stringify(payload) }),
  testS4:      (payload) => apiFetch('/api/connections/s4hana/test',
                  { method: 'POST', body: JSON.stringify(payload) }),
  saveLiftAndShiftTarget: (payload) => apiFetch('/api/connections/lift-and-shift-target',
                  { method: 'POST', body: JSON.stringify(payload) }),

  // ── Pipeline + runs ──
  stages:   () => apiFetch('/api/pipeline/lift-and-shift/stages'),
  status:   () => apiFetch('/api/status'),
  progress: (since = 0) => apiFetch(`/api/progress?since=${since}`),
  spineProgress: () => apiFetch('/api/spine/progress'),
  runs:     () => apiFetch('/api/runs'),
  run:      (id) => apiFetch(`/api/runs/${id}`),

  // ── Gates ──
  gates:       () => apiFetch('/api/gates'),
  approveGate: (id, decided_by) =>
    apiFetch(`/api/gates/${id}/approve`, { method: 'POST', body: JSON.stringify({ decided_by }) }),
  rejectGate: (id, decided_by) =>
    apiFetch(`/api/gates/${id}/reject`, { method: 'POST', body: JSON.stringify({ decided_by }) }),

  // ── Pipeline triggers ──
  trigger: (mode) => apiFetch(`/api/pipeline/${mode}`, { method: 'POST' }),
  triggerLiftAndShift: (payload = {}) =>
    apiFetch('/api/pipeline/lift-and-shift', { method: 'POST', body: JSON.stringify(payload) }),
  triggerLiftAndShiftAssess: () =>
    apiFetch('/api/pipeline/lift-and-shift/assess', { method: 'POST' }),
  triggerLiftAndShiftCode: () =>
    apiFetch('/api/pipeline/lift-and-shift/code', { method: 'POST' }),
  triggerLiftAndShiftData: () =>
    apiFetch('/api/pipeline/lift-and-shift/data', { method: 'POST' }),

  // ── F6 Version compatibility matrix ──
  versionsSupported: () => apiFetch('/api/versions/supported'),
  versionsDetected:  () => apiFetch('/api/versions/detected'),
  versionsSelected:  () => apiFetch('/api/versions/selected'),
  saveVersions: (payload) =>
    apiFetch('/api/versions/selected', { method: 'POST', body: JSON.stringify(payload) }),

  // ── Script runner (whitelisted server-side scripts) ──
  scriptList:  () => apiFetch('/api/scripts/list'),
  scriptRun:   (script_id, params = {}) =>
    apiFetch('/api/scripts/run', { method: 'POST', body: JSON.stringify({ script_id, params }) }),
  scriptOutput: (job_id) => apiFetch(`/api/scripts/output/${job_id}`),
};
