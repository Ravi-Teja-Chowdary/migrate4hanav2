// Migrate4HANA API client — UI rebuild 2026-06-15.
//
// Auth model: real per-user JWT (root or IAM) stored in localStorage.
// The old "auto-token" flow (POST /api/auth/token at page load) is gone —
// every page is behind <ProtectedRoute>; users must log in first.

export const API_BASE = import.meta.env.VITE_API_BASE ?? '';
const TOKEN_KEY = 'm4h.token.v2';
const USER_KEY  = 'm4h.user.v2';
const CLIENT_KEY = 'm4h.active_client.v2';

// ── token + user storage (read by the auth context) ──────────────────────
export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || '';
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export function getStoredUser() {
  try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null'); }
  catch { return null; }
}

export function setStoredUser(user) {
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
  else localStorage.removeItem(USER_KEY);
}

export function getActiveClient() {
  return localStorage.getItem(CLIENT_KEY) || '';
}

export function setActiveClient(client_id) {
  if (client_id) localStorage.setItem(CLIENT_KEY, client_id);
  else localStorage.removeItem(CLIENT_KEY);
}

export function clearSession() {
  setToken('');
  setStoredUser(null);
  setActiveClient('');
}

// ── core fetch ───────────────────────────────────────────────────────────
export async function apiFetch(path, opts = {}) {
  const token = getToken();
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const cid = getActiveClient();
  if (cid) headers['X-Client-Id'] = cid;
  const res = await fetch(`${API_BASE}${path}`, { ...opts, headers });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!res.ok) {
    const msg = data?.detail?.error || data?.detail || data?.error || `HTTP ${res.status}`;
    const err = new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    err.status = res.status;
    err.data = data;
    if (res.status === 401) {
      // Auto-logout on 401; the ProtectedRoute will redirect to /login.
      clearSession();
    }
    throw err;
  }
  return data;
}

export async function authUrl(path) {
  const token = getToken();
  return `${API_BASE}${path}${path.includes('?') ? '&' : '?'}token=${encodeURIComponent(token || '')}`;
}

export async function ping() {
  try {
    const r = await fetch(`${API_BASE}/api/health`);
    return r.ok ? await r.json() : null;
  } catch { return null; }
}

// ── typed helpers ────────────────────────────────────────────────────────
export const api = {
  health: () => apiFetch('/api/health'),

  // ── Auth ──
  loginRoot: (email, password) =>
    apiFetch('/api/auth/login', {
      method: 'POST', body: JSON.stringify({ email, password }),
    }),
  loginIAM: (email, password, client_id) =>
    apiFetch('/api/auth/iam-login', {
      method: 'POST', body: JSON.stringify({ email, password, client_id }),
    }),
  me:     () => apiFetch('/api/auth/me'),
  logout: () => apiFetch('/api/auth/logout', { method: 'POST' }),

  // ── User management (root only) ──
  listUsers:  () => apiFetch('/api/users'),
  createUser: (payload) => apiFetch('/api/users',
    { method: 'POST', body: JSON.stringify(payload) }),
  updateUser: (email, payload) => apiFetch(`/api/users/${encodeURIComponent(email)}`,
    { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteUser: (email) => apiFetch(`/api/users/${encodeURIComponent(email)}`,
    { method: 'DELETE' }),
  operations: () => apiFetch('/api/operations'),

  // ── Clients ──
  listClients:  () => apiFetch('/api/clients'),
  createClient: (payload) => apiFetch('/api/clients',
    { method: 'POST', body: JSON.stringify(payload) }),
  deleteClient: (id) => apiFetch(`/api/clients/${encodeURIComponent(id)}`,
    { method: 'DELETE' }),

  // ── Wizard ──
  wizardCreate: (payload = {}) => apiFetch('/api/wizard',
    { method: 'POST', body: JSON.stringify(payload) }),
  wizardList:   () => apiFetch('/api/wizard'),
  wizardGet:    (run_id) => apiFetch(`/api/wizard/${encodeURIComponent(run_id)}`),
  wizardPatch:  (run_id, payload) =>
    apiFetch(`/api/wizard/${encodeURIComponent(run_id)}`,
      { method: 'PATCH', body: JSON.stringify(payload) }),
  wizardDelete: (run_id) =>
    apiFetch(`/api/wizard/${encodeURIComponent(run_id)}`, { method: 'DELETE' }),

  // ── Versions ──
  versionsSupported: () => apiFetch('/api/versions/supported'),
  versionsDetected:  () => apiFetch('/api/versions/detected'),

  // ── Perm-aware connection test ──
  testEccPermAware: (creds, migration_type, selected_objects) =>
    apiFetch('/api/connections/ecc/test-with-permissions', {
      method: 'POST',
      body: JSON.stringify({ creds, migration_type, selected_objects }),
    }),
  testS4PermAware: (creds, migration_type, selected_objects) =>
    apiFetch('/api/connections/s4/test-with-permissions', {
      method: 'POST',
      body: JSON.stringify({ creds, migration_type, selected_objects }),
    }),
  saveEcc: (payload) => apiFetch('/api/connections/ecc',
    { method: 'POST', body: JSON.stringify(payload) }),
  saveS4:  (payload) => apiFetch('/api/connections/s4hana',
    { method: 'POST', body: JSON.stringify(payload) }),

  // ── Conversion mapping ──
  mappingAll: () => apiFetch('/api/mapping'),
  mappingOne: (object_name) => apiFetch(`/api/mapping/${encodeURIComponent(object_name)}`),
  conversionProgress: (run_id) =>
    apiFetch(`/api/runs/${encodeURIComponent(run_id)}/conversion-progress`),

  // ── Runs ──
  runs:     () => apiFetch('/api/runs'),
  run:      (id) => apiFetch(`/api/runs/${encodeURIComponent(id)}`),
  progress: (since = 0) => apiFetch(`/api/progress?since=${since}`),
  spineProgress: () => apiFetch('/api/spine/progress'),
  status:   () => apiFetch('/api/status'),

  // ── Aggregated per-run telemetry (dashboard cards) ──
  runTelemetry: (run_id) =>
    apiFetch(`/api/runs/${encodeURIComponent(run_id)}/telemetry`),
  runErrorBuckets: (run_id) =>
    apiFetch(`/api/runs/${encodeURIComponent(run_id)}/error-buckets`),
  // downloadFailedRecords / downloadEvidencePack are handled via downloadFile
  // (already exported from this module) using these paths:
  failedRecordsCsvPath: (run_id) =>
    `/api/runs/${encodeURIComponent(run_id)}/failed-records.csv`,
  evidencePackPath: (run_id) =>
    `/api/runs/${encodeURIComponent(run_id)}/evidence-pack`,

  // ── Mapping upload flow ──
  mappingTemplatePath: () => '/api/mapping-template.csv',
  validateMapping: (csvText) =>
    apiFetch('/api/mapping-validate',
      { method: 'POST', headers: { 'Content-Type': 'text/csv' }, body: csvText }),

  // ── Pipeline triggers ──
  triggerLiftAndShift: (payload = {}) =>
    apiFetch('/api/pipeline/lift-and-shift',
      { method: 'POST', body: JSON.stringify(payload) }),

  // ── Failed-records reprocessing loop ──
  // Downloads are handled via downloadFile() from this module — those URLs
  // return .xlsx blobs. Upload uses a plain fetch with multipart form data.
  reprocessTemplateUrl: (run_id, objects) => {
    const q = objects && objects.length
      ? `?objects=${encodeURIComponent(objects.join(','))}` : '';
    return `/api/runs/${encodeURIComponent(run_id)}/reprocess/template${q}`;
  },
  reprocessFailuresUrl: (run_id) =>
    `/api/runs/${encodeURIComponent(run_id)}/reprocess/failures`,
  reprocessUpload: async (run_id, file) => {
    const fd = new FormData();
    fd.append('file', file, file.name);
    const url = `${API_BASE}/api/runs/${encodeURIComponent(run_id)}/reprocess/upload`;
    const token = getToken();
    const res = await fetch(url, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: fd,
    });
    if (!res.ok) {
      let msg = res.statusText;
      try { msg = (await res.json()).detail || msg; } catch {}
      throw new Error(msg);
    }
    return res.json();
  },

  // ── Preservation planner ──
  // Compute per-object source-key preservation coverage under each of
  // 4 strategies (A: point NUMKE at existing external; B: modify SAP
  // interval - highest fidelity, needs Basis approval; C: shift source
  // keys via offset; D: renumber + ledger).
  preservationCompute: (object_types) =>
    apiFetch('/api/pipeline/preservation-plan/compute',
      { method: 'POST', body: JSON.stringify({ object_types: object_types || null }) }),
  preservationApply: (plan, decisions) =>
    apiFetch('/api/pipeline/preservation-plan/apply',
      { method: 'POST', body: JSON.stringify({ plan, decisions }) }),

  // ── Migration coverage report ──
  // Full spine catalog with tier badges (T1/T2/MC/BLOCKED). Wizard uses
  // this to render the honest breadth panel.
  coverage: () => apiFetch('/api/pipeline/coverage'),

  // ── S/4 prep script (auto-generated ABAP) ──
  // Scans ECC customizing and emits an ABAP report the S/4 admin runs in
  // SE38 to set up target customizing referenced by the ECC data. Returned
  // payload includes the ABAP source (for inline display + copy button) and
  // a download URL that streams the same source as a .abap file.
  generatePrepScript: (payload = {}) =>
    apiFetch('/api/pipeline/prep-script/generate',
      { method: 'POST', body: JSON.stringify(payload) }),
  autoRunPrepScript: (run_id) =>
    apiFetch('/api/pipeline/prep-script/auto-run',
      { method: 'POST', body: JSON.stringify({ run_id }) }),
  applyPrepViaRfc: (run_id) =>
    apiFetch('/api/pipeline/prep-script/apply-via-rfc',
      { method: 'POST', body: JSON.stringify({ run_id }) }),
  prepScriptBootstrapUrl: () => '/api/pipeline/prep-script/bootstrap.abap',

  // ── Gates ──
  gates: () => apiFetch('/api/gates'),
  approveGate: (id, decided_by) =>
    apiFetch(`/api/gates/${id}/approve`,
      { method: 'POST', body: JSON.stringify({ decided_by }) }),
  rejectGate: (id, decided_by) =>
    apiFetch(`/api/gates/${id}/reject`,
      { method: 'POST', body: JSON.stringify({ decided_by }) }),

  // ── Logs ──
  logSources: () => apiFetch('/api/logs/sources'),
  logTail: ({ source = 'sfn', run_id, next_token, start_ms, limit = 500, q } = {}) => {
    const p = new URLSearchParams();
    p.set('source', source);
    if (run_id)     p.set('run_id', run_id);
    if (next_token) p.set('next_token', next_token);
    if (start_ms)   p.set('start_ms', start_ms);
    if (limit)      p.set('limit', String(limit));
    if (q)          p.set('q', q);
    return apiFetch(`/api/logs/tail?${p.toString()}`);
  },

  // ── Reports ──
  reportSections: (run_id) =>
    apiFetch(`/api/runs/${encodeURIComponent(run_id)}/report`),

  // ── Admin (root only) ──
  adminCommands: (category) => {
    const q = category ? `?category=${encodeURIComponent(category)}` : '';
    return apiFetch(`/api/admin/commands${q}`);
  },
  adminCommand: (id) => apiFetch(`/api/admin/commands/${encodeURIComponent(id)}`),
  adminExecute: (id, params = {}) =>
    apiFetch(`/api/admin/commands/${encodeURIComponent(id)}/execute`,
      { method: 'POST', body: JSON.stringify({ params }) }),
};

// ── PDF download helpers ─────────────────────────────────────────────────
export async function downloadFile(path, filename) {
  const token = getToken();
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      try { msg = JSON.parse(await res.text()).detail || msg; } catch { /* */ }
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
    const u = await authUrl(path);
    window.open(u, '_blank');
    throw e;
  }
}

export async function openInTab(path) {
  const u = await authUrl(path);
  window.open(u, '_blank');
}
