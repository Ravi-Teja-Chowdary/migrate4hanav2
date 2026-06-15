// AWS-style login: Root user tab + IAM user tab.
//
// Root tab needs email + password (no client_id).
// IAM tab needs email + password + client_id (the user must already be
// scoped to that client; the backend enforces this).
import React, { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../lib/auth';

export default function Login() {
  const [tab, setTab] = useState('iam');   // default = IAM (most common)
  const { loginRoot, loginIAM, loading } = useAuth();
  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [clientId, setClientId] = useState('');
  const [err, setErr] = useState('');
  const nav = useNavigate();
  const loc = useLocation();

  const onSubmit = async (e) => {
    e.preventDefault();
    setErr('');
    try {
      if (tab === 'root') {
        await loginRoot(email.trim(), password);
      } else {
        if (!clientId.trim()) throw new Error('Client ID is required for IAM login');
        await loginIAM(email.trim(), password, clientId.trim().toLowerCase());
      }
      const from = loc.state?.from || '/';
      nav(from, { replace: true });
    } catch (e2) {
      setErr(e2.message || String(e2));
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 grid place-items-center px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-6">
          <div className="text-2xl font-semibold tracking-tight">Migrate4HANA</div>
          <div className="text-slate-400 text-sm mt-1">Sign in to continue</div>
        </div>

        <div className="bg-white text-slate-900 rounded-lg shadow-xl overflow-hidden">
          <div className="flex border-b border-slate-200">
            <Tab active={tab === 'iam'}  onClick={() => setTab('iam')} label="IAM user" />
            <Tab active={tab === 'root'} onClick={() => setTab('root')} label="Root user" />
          </div>

          <form onSubmit={onSubmit} className="p-6 space-y-4">
            {tab === 'iam' && (
              <Field label="Client ID" hint="Your client / tenant slug (e.g. acme)">
                <input
                  className="input"
                  value={clientId}
                  onChange={(e) => setClientId(e.target.value)}
                  required
                  autoComplete="organization"
                  placeholder="acme"
                />
              </Field>
            )}
            <Field
              label={tab === 'root' ? 'Root user email' : 'IAM user email'}
            >
              <input
                className="input" type="email"
                value={email} onChange={(e) => setEmail(e.target.value)}
                required autoComplete="username"
                placeholder="you@example.com"
              />
            </Field>
            <Field label="Password">
              <input
                className="input" type="password"
                value={password} onChange={(e) => setPassword(e.target.value)}
                required autoComplete="current-password"
              />
            </Field>

            {err && (
              <div className="text-red-700 text-sm bg-red-50 border border-red-200 rounded px-3 py-2">
                {err}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-orange-500 hover:bg-orange-600 disabled:bg-orange-300 text-white font-medium py-2 rounded"
            >
              {loading ? 'Signing in…' : 'Sign in'}
            </button>

            <div className="text-xs text-slate-500 leading-relaxed pt-1">
              {tab === 'root'
                ? 'Root users have full control of the deployment, including creating IAM users.'
                : 'IAM users are scoped to a specific client. Your root admin granted you access.'}
            </div>
          </form>
        </div>
      </div>

      <style>{`
        .input {
          width: 100%;
          padding: 0.5rem 0.75rem;
          border: 1px solid rgb(203 213 225);
          border-radius: 0.375rem;
          background: white;
          outline: none;
          font-size: 0.875rem;
        }
        .input:focus { border-color: rgb(249 115 22); box-shadow: 0 0 0 3px rgba(249,115,22,0.15); }
      `}</style>
    </div>
  );
}

function Tab({ active, onClick, label }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex-1 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
        active
          ? 'border-orange-500 text-orange-600 bg-orange-50'
          : 'border-transparent text-slate-600 hover:text-slate-900'
      }`}
    >
      {label}
    </button>
  );
}

function Field({ label, hint, children }) {
  return (
    <label className="block">
      <div className="text-sm font-medium text-slate-700 mb-1">{label}</div>
      {children}
      {hint && <div className="text-xs text-slate-500 mt-1">{hint}</div>}
    </label>
  );
}
