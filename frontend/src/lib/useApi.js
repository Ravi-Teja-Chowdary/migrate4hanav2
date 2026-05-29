import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Fetch real data from the backend. No mock fallback — on failure it surfaces
 * the error so the UI can show an honest "offline / empty" state.
 *
 * @param {() => Promise<any>} fetcher  stable-ish async fn (wrap in useCallback)
 * @param {object} opts  { pollMs?: number, deps?: any[] }
 */
export function useApi(fetcher, { pollMs = 0, deps = [] } = {}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const load = useCallback(async () => {
    try {
      const d = await fetcherRef.current();
      setData(d);
      setError(null);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    load();
    let timer = null;
    if (pollMs > 0) {
      timer = setInterval(() => { if (alive) load(); }, pollMs);
    }
    return () => { alive = false; if (timer) clearInterval(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, reload: load };
}

/** Run a one-shot mutation (POST). Returns { run, busy, result, error }. */
export function useAction(fn) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const run = useCallback(async (...args) => {
    setBusy(true); setError(null);
    try {
      const r = await fn(...args);
      setResult(r);
      return r;
    } catch (e) {
      setError(e);
      throw e;
    } finally {
      setBusy(false);
    }
  }, [fn]);
  return { run, busy, result, error };
}
