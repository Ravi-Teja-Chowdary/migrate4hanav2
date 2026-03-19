/**
 * Migrate4HANA — API Client with automatic JWT authentication.
 *
 * Usage:
 *   import { apiFetch, API_BASE } from '../api';
 *   const data = await apiFetch('/api/pipeline/assess', { method: 'POST' });
 */

export const API_BASE = 'http://localhost:8000';

let _token = null;
let _tokenPromise = null;

/**
 * Fetch a JWT token from the API server.  Caches the token for the session.
 */
async function getToken() {
  if (_token) return _token;
  if (_tokenPromise) return _tokenPromise;

  _tokenPromise = fetch(`${API_BASE}/api/auth/token`, { method: 'POST' })
    .then((r) => r.json())
    .then((data) => {
      _token = data.token;
      _tokenPromise = null;
      return _token;
    })
    .catch(() => {
      _tokenPromise = null;
      return null;
    });

  return _tokenPromise;
}

/**
 * Authenticated fetch wrapper.  Automatically attaches Bearer token.
 * Falls back to unauthenticated request if token retrieval fails.
 *
 * @param {string} path  — API path, e.g. '/api/pipeline/assess'
 * @param {RequestInit} [opts] — fetch options (method, body, headers…)
 * @returns {Promise<Response>}
 */
export async function apiFetch(path, opts = {}) {
  const token = await getToken();
  const headers = { ...(opts.headers || {}) };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  return fetch(`${API_BASE}${path}`, { ...opts, headers });
}

/**
 * Build a URL with the auth token as a query parameter.
 * Useful for links that open in new tabs (PDF downloads, etc.)
 * where you can't set headers.
 */
export async function getAuthUrl(path) {
  const token = await getToken();
  return `${API_BASE}${path}${path.includes('?') ? '&' : '?'}token=${token || ''}`;
}
