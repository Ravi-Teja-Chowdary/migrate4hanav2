import { Routes, Route } from 'react-router-dom';
import Shell from './components/Shell';
import Dashboard from './pages/Dashboard';
import Connections from './pages/Connections';
import VersionMatrix from './pages/VersionMatrix';
import Pipeline from './pages/Pipeline';
import ProjectTracker from './pages/ProjectTracker';
import Gates from './pages/Gates';
import Runs from './pages/Runs';
import CommandCenter from './pages/CommandCenter';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Shell />}>
        <Route index element={<Dashboard />} />
        <Route path="connections" element={<Connections />} />
        <Route path="versions" element={<VersionMatrix />} />
        <Route path="tracker" element={<ProjectTracker />} />
        <Route path="pipeline" element={<Pipeline />} />
        <Route path="gates" element={<Gates />} />
        <Route path="runs" element={<Runs />} />
        <Route path="commands" element={<CommandCenter />} />
      </Route>
    </Routes>
  );
}
