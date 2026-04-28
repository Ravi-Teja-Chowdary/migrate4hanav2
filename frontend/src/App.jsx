import { Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Connections from './pages/Connections';
import Pipeline from './pages/Pipeline';
import LiftAndShift from './pages/LiftAndShift';
import Telemetry from './pages/Telemetry';
import Scorecard from './pages/Scorecard';
import StageDetail from './pages/StageDetail';
import Report from './pages/Report';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="connections" element={<Connections />} />
        <Route path="pipeline" element={<Pipeline />} />
        <Route path="lift-and-shift" element={<LiftAndShift />} />
        <Route path="telemetry" element={<Telemetry />} />
        <Route path="scorecard" element={<Scorecard />} />
        <Route path="report" element={<Report />} />
        <Route path="stage/:stageKey" element={<StageDetail />} />
      </Route>
    </Routes>
  );
}
