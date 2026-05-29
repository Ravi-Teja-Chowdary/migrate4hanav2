import React, { useState, useEffect, useRef, useCallback } from 'react';

const WS_URL = import.meta.env.VITE_TELEMETRY_WS_URL || '';

const LogViewer = ({ runId }) => {
  const [logs, setLogs] = useState([]);
  const [isLive, setIsLive] = useState(true);
  const [connectionStatus, setConnectionStatus] = useState('disconnected');
  const endOfLogsRef = useRef(null);
  const wsRef = useRef(null);
  const reconnectTimer = useRef(null);

  const addLog = useCallback((entry) => {
    setLogs(prev => [...prev.slice(-199), entry]);
  }, []);

  useEffect(() => {
    if (!isLive) return;

    // Real WebSocket mode
    if (WS_URL) {
      let url = WS_URL;
      if (runId) {
        const sep = url.includes('?') ? '&' : '?';
        url = `${url}${sep}run_id=${encodeURIComponent(runId)}`;
      }

      const connect = () => {
        setConnectionStatus('connecting');
        const ws = new WebSocket(url);
        wsRef.current = ws;

        ws.onopen = () => setConnectionStatus('connected');

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            addLog({
              id: data.event_id || Math.random().toString(36).substr(2, 9),
              timestamp: data.timestamp || new Date().toISOString(),
              stage: data.stage || 'unknown',
              action: data.action || '',
              status: data.status || 'IN_PROGRESS',
              payload: typeof data.details === 'object' ? JSON.stringify(data.details) : String(data.details || ''),
              duration_ms: data.duration_ms,
            });
          } catch {
            // non-JSON message — show as raw
            addLog({
              id: Math.random().toString(36).substr(2, 9),
              timestamp: new Date().toISOString(),
              stage: 'system',
              action: 'message',
              status: 'IN_PROGRESS',
              payload: event.data,
            });
          }
        };

        ws.onclose = () => {
          setConnectionStatus('disconnected');
          wsRef.current = null;
          // Reconnect after 3s
          reconnectTimer.current = setTimeout(connect, 3000);
        };

        ws.onerror = () => {
          clearTimeout(reconnectTimer.current);
          ws.close();
        };
      };

      connect();

      return () => {
        clearTimeout(reconnectTimer.current);
        if (wsRef.current) {
          wsRef.current.close();
          wsRef.current = null;
        }
      };
    }

    // Fallback: mock data for local development
    setConnectionStatus('mock');
    const stages = ['discovery-engine', 'code-analyzer', 'data-migrator', 'config-replicator', 'cutover-orchestrator', 'migration-validator'];
    const actions = ['Scanning tables', 'Analyzing ABAP AST', 'Extracting BSEG records', 'Config SPRO payload', 'Pre-flight check', 'Validating scorecard'];
    const statuses = ['IN_PROGRESS', 'SUCCESS', 'IN_PROGRESS', 'SUCCESS', 'IN_PROGRESS', 'SUCCESS'];
    let idx = 0;
    const mockInterval = setInterval(() => {
      const i = idx % stages.length;
      addLog({
        id: Math.random().toString(36).substr(2, 9),
        timestamp: new Date().toISOString(),
        stage: stages[i],
        action: actions[i],
        status: statuses[i],
        payload: `{ "mock": true, "cycle": ${Math.floor(idx / stages.length) + 1} }`,
      });
      idx++;
    }, 2000);

    return () => clearInterval(mockInterval);
  }, [runId, isLive, addLog]);

  // Auto-scroll logic
  useEffect(() => {
    if (isLive && endOfLogsRef.current) {
      endOfLogsRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, isLive]);

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-lg p-4 font-mono text-sm text-green-400 mt-6 shadow-xl h-96 flex flex-col">
      <div className="flex justify-between items-center border-b border-gray-700 pb-2 mb-3">
        <h3 className="text-slate-900 font-semibold flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${
              connectionStatus === 'connected' ? 'bg-green-500 animate-pulse' :
              connectionStatus === 'connecting' ? 'bg-yellow-500 animate-pulse' :
              connectionStatus === 'mock' ? 'bg-blue-500 animate-pulse' :
              'bg-red-500'
            }`}></span>
            Live Telemetry {connectionStatus === 'mock' && <span className="text-xs text-gray-500">(mock)</span>}
        </h3>
        <div className="space-x-3">
            <button 
                onClick={() => setLogs([])}
                className="text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 px-2 py-1 rounded transition-colors"
            >
                Clear
            </button>
            <button 
                onClick={() => setIsLive(!isLive)}
                className={`text-xs px-2 py-1 rounded transition-colors ${
                  isLive ? 'bg-red-900/50 text-red-300 hover:bg-red-900/80' : 'bg-green-900/50 text-green-300 hover:bg-green-900/80'
                }`}
            >
                {isLive ? 'Pause Stream' : 'Resume'}
            </button>
        </div>
      </div>
      
      <div className="overflow-y-auto flex-1 pr-2 space-y-1 scrollbar-thin scrollbar-thumb-gray-700 scrollbar-track-transparent">
        {logs.length === 0 ? (
            <div className="text-gray-500 flex justify-center items-center h-full">Waiting for telemetry...</div>
        ) : (
            logs.map(log => (
            <div key={log.id} className="flex gap-4 opacity-90 hover:opacity-100 hover:bg-gray-800/50 p-1 rounded">
                <span className="text-gray-500 shrink-0">[{log.timestamp?.split('T')[1]?.slice(0, -1) || 'N/A'}]</span>
                <span className="text-blue-400 font-semibold w-36 shrink-0 truncate">[{log.stage}]</span>
                <span className={`w-24 shrink-0 truncate ${
                    log.status === 'ERROR' ? 'text-red-500 font-bold' : 
                    log.status === 'SUCCESS' ? 'text-green-500' : 'text-yellow-400'
                }`}>
                    {log.status}
                </span>
                <span className="text-gray-300">{log.action}{log.action && ': '}{log.payload}{log.duration_ms != null && <span className="text-gray-500 ml-2">({(log.duration_ms / 1000).toFixed(1)}s)</span>}</span>
            </div>
            ))
        )}
        <div ref={endOfLogsRef} />
      </div>
    </div>
  );
};

export default LogViewer;