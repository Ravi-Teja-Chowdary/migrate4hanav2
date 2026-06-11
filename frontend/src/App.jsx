import { Routes, Route } from 'react-router-dom';
import { ActiveRunProvider } from './lib/activeRun.jsx';
import { ActiveClientProvider } from './lib/activeClient.jsx';
import Shell from './components/Shell';
import Dashboard from './pages/Dashboard';
import Connections from './pages/Connections';
import VersionMatrix from './pages/VersionMatrix';
import Pipeline from './pages/Pipeline';
import ProjectTracker from './pages/ProjectTracker';
import Gates from './pages/Gates';
import Runs from './pages/Runs';
import CommandCenter from './pages/CommandCenter';
import DataQuality from './pages/DataQuality';
import Logs from './pages/Logs';
import Report from './pages/Report';
import Clients from './pages/Clients';

export default function App() {
  return (
    <ActiveClientProvider>
    <ActiveRunProvider>
    <Routes>
      <Route path="/" element={<Shell />}>
        <Route index element={<Dashboard />} />
        <Route path="connections"  element={<Connections />} />
        <Route path="versions"     element={<VersionMatrix />} />
        <Route path="tracker"      element={<ProjectTracker />} />
        <Route path="pipeline"     element={<Pipeline />} />
        <Route path="gates"        element={<Gates />} />
        <Route path="runs"         element={<Runs />} />
        <Route path="data-quality" element={<DataQuality />} />
        <Route path="logs"         element={<Logs />} />
        <Route path="report"       element={<Report />} />
        <Route path="clients"      element={<Clients />} />
        <Route path="commands"     element={<CommandCenter />} />
      </Route>
    </Routes>
    </ActiveRunProvider>
    </ActiveClientProvider>
  );
}
