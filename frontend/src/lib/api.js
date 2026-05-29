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
  connections: () => apiFetch('/api/connections'),
  eccStatus: () => apiFetch('/api/connections/ecc/status'),
  stages: () => apiFetch('/api/pipeline/lift-and-shift/stages'),
  status: () => apiFetch('/api/status'),
  progress: (since = 0) => apiFetch(`/api/progress?since=${since}`),
  spineProgress: () => apiFetch('/api/spine/progress'),
  runs: () => apiFetch('/api/runs'),
  run: (id) => apiFetch(`/api/runs/${id}`),
  gates: () => apiFetch('/api/gates'),
  approveGate: (id, decided_by) =>
    apiFetch(`/api/gates/${id}/approve`, { method: 'POST', body: JSON.stringify({ decided_by }) }),
  rejectGate: (id, decided_by) =>
    apiFetch(`/api/gates/${id}/reject`, { method: 'POST', body: JSON.stringify({ decided_by }) }),
  trigger: (mode) => apiFetch(`/api/pipeline/${mode}`, { method: 'POST' }),
};
