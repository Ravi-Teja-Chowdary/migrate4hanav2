// Migrate4HANA UI v2 — AWS-style auth + 9-page wizard flow.
//
// Every protected route is wrapped in ErrorBoundary so a single render
// failure doesn't blank the whole page — you'll see the error + a Retry
// button instead.

import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, ProtectedRoute, RootOnlyRoute } from './lib/auth';
import AppShell from './components/v2/AppShell';
import ErrorBoundary from './components/v2/ErrorBoundary';

import Login from './pages/v2/Login';
import Home from './pages/v2/Home';
import WizardVersions from './pages/v2/WizardVersions';
import WizardScope from './pages/v2/WizardScope';
import WizardConnect from './pages/v2/WizardConnect';
import Project from './pages/v2/Project';
import LiveOps from './pages/v2/LiveOps';
import ConversionDashboard from './pages/v2/ConversionDashboard';
import SuperuserConsole from './pages/v2/SuperuserConsole';

const guard = (el) => <ErrorBoundary>{el}</ErrorBoundary>;

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<ErrorBoundary><Login /></ErrorBoundary>} />

        {/* Full-screen new-tab views — outside the AppShell. */}
        <Route
          path="/live/:runId"
          element={<ProtectedRoute>{guard(<LiveOps />)}</ProtectedRoute>}
        />
        <Route
          path="/conversion/:runId"
          element={<ProtectedRoute>{guard(<ConversionDashboard />)}</ProtectedRoute>}
        />

        <Route
          path="/"
          element={<ProtectedRoute><AppShell /></ProtectedRoute>}
        >
          <Route index element={guard(<Home />)} />
          <Route path="wizard/:runId/versions" element={guard(<WizardVersions />)} />
          <Route path="wizard/:runId/scope" element={guard(<WizardScope />)} />
          <Route path="wizard/:runId/connect" element={guard(<WizardConnect />)} />
          <Route path="project/:runId" element={guard(<Project />)} />
          <Route
            path="admin"
            element={<RootOnlyRoute>{guard(<SuperuserConsole />)}</RootOnlyRoute>}
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}
