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

/** Authenticated fetch returning parsed JSON. Throws on network/HTTP error.
 *  Automatically attaches X-Client-Id so the api-server can scope tenant data. */
export async function apiFetch(path, opts = {}) {
  const token = await getToken();
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  // Lazy-import activeClient to avoid an init-order cycle when apiFetch is
  // imported before the React provider mounts.
  try {
    const { getActiveClientId } = await import('./activeClient.jsx');
    const cid = getActiveClientId();
    if (cid) headers['X-Client-Id'] = cid;
  } catch { /* ignore — single-tenant fallback */ }
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

  // ── Clients (multi-tenant) ──
  listClients:  () => apiFetch('/api/clients'),
  createClient: (payload) => apiFetch('/api/clients',
                  { method: 'POST', body: JSON.stringify(payload) }),
  deleteClient: (id) => apiFetch(`/api/clients/${encodeURIComponent(id)}`,
                  { method: 'DELETE' }),

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

  // ── PDF reports ──
  reportVolumes: (run_id) => apiFetch(`/api/v1/reports/${run_id}/volumes`),
  reportSections: (run_id) => apiFetch(`/api/runs/${run_id}/report`),

  // ── Logs (CloudWatch + local) ──
  logSources: () => apiFetch('/api/logs/sources'),
  logTail:    ({ source = 'sfn', run_id, next_token, start_ms, limit = 500, q } = {}) => {
    const p = new URLSearchParams();
    p.set('source', source);
    if (run_id)     p.set('run_id', run_id);
    if (next_token) p.set('next_token', next_token);
    if (start_ms)   p.set('start_ms', start_ms);
    if (limit)      p.set('limit', String(limit));
    if (q)          p.set('q', q);
    return apiFetch(`/api/logs/tail?${p.toString()}`);
  },
};

/** Trigger a browser download of a PDF (or any file) at the given API path.
 *  Uses an authenticated fetch + blob URL so the browser downloads it.
 *  Falls back to opening the authUrl in a new tab if blob fetch fails.
 */
export async function downloadFile(path, filename) {
  const token = await getToken();
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) {
      const txt = await res.text().catch(() => '');
      let msg = `HTTP ${res.status}`;
      try { msg = JSON.parse(txt).detail || msg; } catch { /* ignore */ }
      throw new Error(msg);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename || path.split('/').pop() || 'download';
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 100);
    return true;
  } catch (e) {
    // Fall back: open in new tab with token query param
    const u = await authUrl(path);
    window.open(u, '_blank');
    throw e;
  }
}

/** Open a PDF in a new tab (read-only preview) with auth via query param. */
export async function openInTab(path) {
  const u = await authUrl(path);
  window.open(u, '_blank');
}
