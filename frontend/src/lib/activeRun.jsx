// Active-run context. Persists the currently-selected run id to localStorage
// so a refresh keeps the user on the same context. Pages read activeRunId
// from useActiveRun() and scope their queries to it.
//
// Default behavior: if nothing is stored, select the latest run on first load.
// If the stored id is no longer present in the runs list, fall back to latest.
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api } from './api';

const KEY = 'm4h:activeRunId';

const ActiveRunCtx = createContext({
  activeRunId: null,
  setActiveRunId: () => {},
  runs: [],
  loading: false,
  refresh: () => {},
});

export function ActiveRunProvider({ children }) {
  const [activeRunId, _setActiveRunId] = useState(() => {
    try { return localStorage.getItem(KEY) || null; } catch { return null; }
  });
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(false);

  const setActiveRunId = useCallback((id) => {
    _setActiveRunId(id);
    try {
      if (id) localStorage.setItem(KEY, id);
      else    localStorage.removeItem(KEY);
    } catch { /* ignore storage errors (private mode etc) */ }
    // Tell pages the context just changed so they refetch.
    window.dispatchEvent(new CustomEvent('m4h:active-run-changed', { detail: { runId: id } }));
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const list = await api.runs();
      const arr = Array.isArray(list) ? list : [];
      setRuns(arr);
      // If we don't have a stored id, OR the stored id isn't in the list,
      // pick the newest run as a sensible default.
      const ids = new Set(arr.map((r) => r.id || r.run_id));
      if (!activeRunId || !ids.has(activeRunId)) {
        const latest = arr[0]?.id || arr[0]?.run_id || null;
        if (latest) setActiveRunId(latest);
      }
    } catch {
      // Leave runs as-is; UI shows offline banner via the api ping elsewhere.
    } finally {
      setLoading(false);
    }
  }, [activeRunId, setActiveRunId]);

  useEffect(() => { refresh(); /* initial load */ }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Client switch → re-fetch runs for the new tenant + clear stale run
  // selection until we know what runs that client has.
  useEffect(() => {
    const onClientChange = () => { setActiveRunId(null); refresh(); };
    window.addEventListener('m4h:active-client-changed', onClientChange);
    return () => window.removeEventListener('m4h:active-client-changed', onClientChange);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Refresh the run list every 15s while the tab is visible — picks up new
  // runs that finished without the user opening the Runs page.
  useEffect(() => {
    let t;
    const tick = () => { if (!document.hidden) refresh(); };
    t = setInterval(tick, 15000);
    document.addEventListener('visibilitychange', tick);
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', tick); };
  }, [refresh]);

  const value = useMemo(
    () => ({ activeRunId, setActiveRunId, runs, loading, refresh }),
    [activeRunId, setActiveRunId, runs, loading, refresh],
  );
  return <ActiveRunCtx.Provider value={value}>{children}</ActiveRunCtx.Provider>;
}

export function useActiveRun() {
  return useContext(ActiveRunCtx);
}
