// Active-client context. Multi-tenant: every API request adds X-Client-Id so
// the server scopes connections, runs, and outputs to the right tenant.
//
// The "default" client is the legacy single-tenant context — every fresh
// install starts there. Customers managing multiple SAP estates create
// additional clients on the Clients page.
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { apiFetch } from './api';

const KEY = 'm4h:activeClientId';

const ActiveClientCtx = createContext({
  activeClientId: 'default',
  setActiveClientId: () => {},
  clients: [],
  loading: false,
  refresh: () => {},
});

// Exported so api.js can synchronously read the current tenant for each
// outgoing request without dragging React state in (cleaner than a hook
// inside the fetch wrapper).
let _activeClientId = null;
try { _activeClientId = localStorage.getItem(KEY) || 'default'; } catch { _activeClientId = 'default'; }
export function getActiveClientId() { return _activeClientId || 'default'; }

export function ActiveClientProvider({ children }) {
  const [activeClientId, _setActiveClientId] = useState(getActiveClientId());
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(false);

  const setActiveClientId = useCallback((id) => {
    const next = id || 'default';
    _activeClientId = next;
    _setActiveClientId(next);
    try {
      localStorage.setItem(KEY, next);
    } catch { /* ignore (private mode etc) */ }
    window.dispatchEvent(new CustomEvent('m4h:active-client-changed', { detail: { clientId: next } }));
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const d = await apiFetch('/api/clients');
      const arr = Array.isArray(d?.clients) ? d.clients : [];
      setClients(arr);
      // If our stored id isn't in the list any more, snap back to default.
      const ids = new Set(arr.map((c) => c.id));
      if (!ids.has(activeClientId)) setActiveClientId(d?.default_client_id || 'default');
    } catch {
      // Older api-server builds may not have /api/clients yet; treat as
      // single-tenant: pretend "default" is the only client.
      setClients([{ id: 'default', name: 'Default tenant' }]);
    } finally { setLoading(false); }
  }, [activeClientId, setActiveClientId]);

  useEffect(() => { refresh(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const value = useMemo(
    () => ({ activeClientId, setActiveClientId, clients, loading, refresh }),
    [activeClientId, setActiveClientId, clients, loading, refresh],
  );
  return <ActiveClientCtx.Provider value={value}>{children}</ActiveClientCtx.Provider>;
}

export function useActiveClient() { return useContext(ActiveClientCtx); }
