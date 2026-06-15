// Migrate4HANA UI v2 — AWS-style auth + 9-page wizard flow.
//
// Public routes:    /login
// Protected:        / (home), /wizard/:runId/* (versions|scope|connect),
//                    /project/:runId
// Live (new tab):   /live/:runId, /conversion/:runId
// Root only:        /admin

import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, ProtectedRoute, RootOnlyRoute } from './lib/auth';
import AppShell from './components/v2/AppShell';

import Login from './pages/v2/Login';
import Home from './pages/v2/Home';
import WizardVersions from './pages/v2/WizardVersions';
import WizardScope from './pages/v2/WizardScope';
import WizardConnect from './pages/v2/WizardConnect';
import Project from './pages/v2/Project';
import LiveOps from './pages/v2/LiveOps';
import ConversionDashboard from './pages/v2/ConversionDashboard';
import SuperuserConsole from './pages/v2/SuperuserConsole';

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        {/* Public */}
        <Route path="/login" element={<Login />} />

        {/* Live ops + conversion dashboard open in new tabs — they are full-screen,
            so they don't sit inside the AppShell. They still require auth. */}
        <Route
          path="/live/:runId"
          element={<ProtectedRoute><LiveOps /></ProtectedRoute>}
        />
        <Route
          path="/conversion/:runId"
          element={<ProtectedRoute><ConversionDashboard /></ProtectedRoute>}
        />

        {/* Main app — inside the AppShell */}
        <Route
          path="/"
          element={<ProtectedRoute><AppShell /></ProtectedRoute>}
        >
          <Route index element={<Home />} />
          <Route path="wizard/:runId/versions" element={<WizardVersions />} />
          <Route path="wizard/:runId/scope" element={<WizardScope />} />
          <Route path="wizard/:runId/connect" element={<WizardConnect />} />
          <Route path="project/:runId" element={<Project />} />
          <Route
            path="admin"
            element={<RootOnlyRoute><SuperuserConsole /></RootOnlyRoute>}
          />
          {/* Fallback inside shell */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>

        {/* Top-level fallback */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}
