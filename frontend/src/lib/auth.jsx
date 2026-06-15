// Auth context + route guards for the new UI.
//
// Wraps the whole app; pages read currentUser/role/activeClient through
// useAuth(). ProtectedRoute redirects to /login when not signed in.
// RootOnlyRoute redirects IAM users back to the home page.
import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import {
  api, getToken, setToken,
  getStoredUser, setStoredUser,
  getActiveClient, setActiveClient, clearSession,
} from './api';

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(getStoredUser());
  const [activeClient, setActiveClientState] = useState(getActiveClient());
  const [loading, setLoading] = useState(false);

  // Re-validate on mount if we have a stored token but no user — happens
  // after a hard reload or a different tab updated localStorage.
  useEffect(() => {
    let cancelled = false;
    async function check() {
      if (!getToken()) return;
      if (user) return;
      try {
        const me = await api.me();
        if (cancelled) return;
        setUser(me);
        setStoredUser(me);
      } catch {
        if (cancelled) return;
        clearSession();
        setUser(null);
      }
    }
    check();
    return () => { cancelled = true; };
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const loginRoot = async (email, password) => {
    setLoading(true);
    try {
      const r = await api.loginRoot(email, password);
      setToken(r.token);
      const me = { email: r.user.email, role: r.user.role,
                    scopes: r.user.client_scopes || [],
                    ops:    r.user.allowed_operations || [] };
      setStoredUser(me);
      setActiveClient('');
      setUser(me);
      setActiveClientState('');
      return me;
    } finally { setLoading(false); }
  };

  const loginIAM = async (email, password, client_id) => {
    setLoading(true);
    try {
      const r = await api.loginIAM(email, password, client_id);
      setToken(r.token);
      const me = { email: r.user.email, role: r.user.role,
                    scopes: [r.active_client_id],
                    ops:    r.user.allowed_operations || [] };
      setStoredUser(me);
      setActiveClient(r.active_client_id);
      setUser(me);
      setActiveClientState(r.active_client_id);
      return me;
    } finally { setLoading(false); }
  };

  const logout = async () => {
    try { await api.logout(); } catch { /* ignore */ }
    clearSession();
    setUser(null);
    setActiveClientState('');
  };

  const value = useMemo(() => ({
    user, loading, activeClient,
    isAuthed: Boolean(user),
    isRoot:   user?.role === 'root',
    isIAM:    user?.role === 'iam',
    can: (op) => {
      if (!user) return false;
      if (user.role === 'root') return true;
      const ops = user.ops || [];
      return ops.includes('*') || ops.includes(op);
    },
    loginRoot, loginIAM, logout,
  }), [user, loading, activeClient]);

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error('useAuth must be inside <AuthProvider>');
  return ctx;
}

// ── Route guards ────────────────────────────────────────────────────────
export function ProtectedRoute({ children }) {
  const { isAuthed } = useAuth();
  const loc = useLocation();
  if (!isAuthed) {
    return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  }
  return children;
}

export function RootOnlyRoute({ children }) {
  const { isAuthed, isRoot } = useAuth();
  const loc = useLocation();
  if (!isAuthed) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  if (!isRoot)   return <Navigate to="/" replace />;
  return children;
}
