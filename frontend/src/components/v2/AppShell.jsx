// Minimal AWS-style top bar + content area. Replaces the verbose left-nav
// Shell from v1. The new flow is a wizard; nav lives mostly inside pages.
import React from 'react';
import { Outlet, Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../../lib/auth';

export default function AppShell() {
  const { user, isRoot, activeClient, logout } = useAuth();
  const nav = useNavigate();

  const onLogout = async () => {
    await logout();
    nav('/login', { replace: true });
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="bg-slate-900 text-white border-b border-slate-800">
        <div className="max-w-6xl mx-auto px-4 h-14 flex items-center gap-4">
          <Link to="/" className="font-semibold text-lg tracking-tight">
            Migrate4HANA
          </Link>
          <span className="text-xs px-2 py-0.5 rounded bg-slate-700 text-slate-200">
            {isRoot ? 'ROOT' : 'IAM'}
          </span>
          {activeClient && (
            <span className="text-xs px-2 py-0.5 rounded bg-blue-600 text-white">
              client: {activeClient}
            </span>
          )}
          <div className="ml-auto flex items-center gap-3 text-sm">
            {isRoot && (
              <Link to="/admin" className="text-slate-200 hover:text-white">
                Console
              </Link>
            )}
            <span className="text-slate-300">{user?.email}</span>
            <button
              onClick={onLogout}
              className="px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-xs"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="max-w-6xl mx-auto px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
