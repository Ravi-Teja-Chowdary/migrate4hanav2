// Live Logs page.
//
// Lets a customer watch the migration pipeline as it runs, search past events
// for the active run, and download the window as a .log file. Source selector
// covers Step Functions, the Fargate api-server, and every Lambda — all routed
// through the api-server's /api/logs/* endpoints (which call CloudWatch with
// FilterLogEvents under the hood).
//
// Retention is 30 days (advertised by /api/logs/sources). Older events are
// dropped by CloudWatch automatically — that's enforced in terraform.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ScrollText, Search, Pause, Play, Download, RefreshCw,
  ChevronDown, AlertTriangle, Clock, X, Filter,
} from 'lucide-react';
import { api, downloadFile } from '../lib/api';
import { useApi } from '../lib/useApi';
import { useToast } from '../lib/toast.jsx';
import { useActiveRun } from '../lib/activeRun.jsx';
import {
  Panel, PageHeader, StatusPill, Spinner, EmptyState, OfflineBanner, SearchBox,
} from '../components/dd';

const POLL_MS = 4000;          // live-tail cadence
const MAX_BUFFER = 5000;       // cap rendered events to keep the DOM happy
const HOUR_OPTIONS = [
  { label: '1 hour', hours: 1 },
  { label: '6 hours', hours: 6 },
  { label: '24 hours', hours: 24 },
  { label: '7 days', hours: 24 * 7 },
  { label: '30 days', hours: 24 * 30 },
];

const fmtTs = (ms) => {
  if (!ms) return '—';
  try { return new Date(ms).toLocaleTimeString([], { hour12: false }) + '.' + String(ms % 1000).padStart(3, '0'); }
  catch { return '—'; }
};

// Best-effort level inference from the message body — log messages don't have
// a standard "level" field across Lambda + SFN + ECS, so we scan for keywords.
function levelOf(msg) {
  if (!msg) return 'info';
  const s = msg.toLowerCase();
  if (s.includes('error') || s.includes('exception') || s.includes('traceback') || s.includes('failed')) return 'err';
  if (s.includes('warn') || s.includes('breach') || s.includes('throttle')) return 'warn';
  if (s.includes('success') || s.includes('completed') || s.includes(' ok ')) return 'ok';
  return 'info';
}

const LEVEL_COLOR = {
  err:  'var(--err)',
  warn: 'var(--warn)',
  ok:   'var(--ok)',
  info: 'var(--ink-3)',
};

function LevelChip({ level }) {
  return (
    <span className="font-mono uppercase text-[9.5px] tracking-wider font-semibold" style={{ color: LEVEL_COLOR[level] }}>
      {level === 'err' ? 'ERROR' : level === 'warn' ? 'WARN ' : level === 'ok' ? 'OK   ' : 'INFO '}
    </span>
  );
}

export default function Logs() {
  const toast = useToast();
  const { activeRunId } = useActiveRun();

  const sourcesQ = useApi(useCallback(() => api.logSources(), []));
  const [source, setSource] = useState('sfn');
  const [paused, setPaused] = useState(false);
  const [query, setQuery] = useState('');
  const [levelFilter, setLevelFilter] = useState('all');
  const [hoursBack, setHoursBack] = useState(1);
  const [events, setEvents] = useState([]);
  const [nextToken, setNextToken] = useState(null);
  const [polling, setPolling] = useState(false);
  const [err, setErr] = useState(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [downloadBusy, setDownloadBusy] = useState(false);

  const scrollRef = useRef(null);
  const seenIds = useRef(new Set());

  // Reset stream when source / activeRunId / query / hoursBack change.
  useEffect(() => {
    setEvents([]);
    setNextToken(null);
    setErr(null);
    seenIds.current = new Set();
  }, [source, activeRunId, query, hoursBack]);

  const fetchMore = useCallback(async () => {
    if (polling) return;
    setPolling(true);
    try {
      const startMs = Date.now() - hoursBack * 3600 * 1000;
      const resp = await api.logTail({
        source, run_id: activeRunId,
        next_token: nextToken,
        start_ms: nextToken ? undefined : startMs,
        limit: 500,
        q: query || undefined,
      });
      if (resp.error) { setErr(resp.error); }
      else            { setErr(null); }
      const fresh = (resp.events || []).filter((e) => {
        const key = e.id || `${e.ts}|${e.src}|${e.msg.slice(0, 64)}`;
        if (seenIds.current.has(key)) return false;
        seenIds.current.add(key);
        return true;
      });
      if (fresh.length) {
        setEvents((prev) => {
          const merged = [...prev, ...fresh];
          // Cap the buffer so the DOM doesn't blow up on long sessions.
          return merged.length > MAX_BUFFER ? merged.slice(-MAX_BUFFER) : merged;
        });
      }
      setNextToken(resp.next_token || null);
    } catch (e) {
      setErr(e.message);
    } finally {
      setPolling(false);
    }
  }, [polling, source, activeRunId, nextToken, query, hoursBack]);

  // Live tail. Pause stops the timer entirely; nextToken=null means we'll
  // re-query from startMs and dedupe via seenIds.
  useEffect(() => {
    if (paused) return undefined;
    fetchMore(); // immediate fetch on mount / dep change
    const t = setInterval(fetchMore, POLL_MS);
    return () => clearInterval(t);
  }, [paused, fetchMore]);

  // Auto-scroll to bottom when new events arrive (unless user disabled it).
  useEffect(() => {
    if (!autoScroll || !scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [events, autoScroll]);

  // Detect manual scroll to disable auto-scroll.
  const onScroll = useCallback((e) => {
    const el = e.target;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    setAutoScroll(atBottom);
  }, []);

  const filtered = useMemo(() => {
    if (levelFilter === 'all') return events;
    return events.filter((e) => levelOf(e.msg) === levelFilter);
  }, [events, levelFilter]);

  const download = async () => {
    setDownloadBusy(true);
    const tId = toast.loading('Building log archive…', `${source} · ${hoursBack}h`);
    try {
      const path = `/api/logs/download?source=${encodeURIComponent(source)}`
        + (activeRunId ? `&run_id=${encodeURIComponent(activeRunId)}` : '')
        + `&hours=${hoursBack}`
        + (query ? `&q=${encodeURIComponent(query)}` : '');
      const fname = `m4h-${source}-${activeRunId || 'all'}-${hoursBack}h.log`;
      await downloadFile(path, fname);
      toast.dismiss(tId);
      toast.success('Logs downloaded', fname);
    } catch (e) {
      toast.dismiss(tId);
      toast.error('Download failed', e.message);
    } finally {
      setDownloadBusy(false);
    }
  };

  if (sourcesQ.error) {
    return (
      <div className="space-y-4">
        <PageHeader title="Logs" breadcrumb={['Migrate4HANA', 'Logs']} subtitle="Pipeline + Lambda + ECS logs (CloudWatch)." />
        <OfflineBanner onRetry={sourcesQ.reload} />
      </div>
    );
  }

  const sources = sourcesQ.data?.sources || [];
  const retentionDays = sourcesQ.data?.retention_days ?? 30;
  const hasCloudWatch = !!sourcesQ.data?.has_cloudwatch;

  const counts = {
    total: events.length,
    err:   events.filter((e) => levelOf(e.msg) === 'err').length,
    warn:  events.filter((e) => levelOf(e.msg) === 'warn').length,
    ok:    events.filter((e) => levelOf(e.msg) === 'ok').length,
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Logs"
        breadcrumb={['Migrate4HANA', 'Logs']}
        subtitle={
          <span>
            Live pipeline & Lambda logs · {hasCloudWatch ? 'CloudWatch' : 'local fallback'} ·{' '}
            <span style={{ color: 'var(--info)' }}>retained for {retentionDays} days</span>
            {activeRunId && <> · scoped to <span className="font-mono">{activeRunId}</span></>}
          </span>
        }
        actions={
          <>
            <button onClick={() => setPaused((p) => !p)} className={`btn btn-sm ${paused ? 'btn-primary' : ''}`} title={paused ? 'Resume tail' : 'Pause tail'}>
              {paused ? <Play size={12} /> : <Pause size={12} />} {paused ? 'Resume' : 'Pause'}
            </button>
            <button onClick={fetchMore} disabled={polling || paused} className="btn btn-sm" title="Force refresh">
              {polling ? <Spinner size={11} /> : <RefreshCw size={11} />} Refresh
            </button>
            <button onClick={download} disabled={downloadBusy} className="btn btn-sm btn-primary" title="Download window as .log">
              {downloadBusy ? <Spinner size={11} /> : <Download size={11} />} Download
            </button>
          </>
        }
      />

      <Panel flush>
        <div className="flex flex-wrap items-center gap-2 px-3 py-2 border-b" style={{ borderColor: 'var(--border)' }}>
          {/* Source picker */}
          <div className="inline-flex items-center gap-1.5">
            <ScrollText size={12} className="text-ink-3" />
            <select
              value={source}
              onChange={(e) => setSource(e.target.value)}
              className="text-[12px] py-1 px-2 rounded-sm font-mono"
              style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--ink-1)' }}
            >
              {sources.length === 0 && <option value="sfn">Step Functions</option>}
              {sources.map((s) => (
                <option key={s.key} value={s.key}>{s.label}</option>
              ))}
            </select>
          </div>

          {/* Window */}
          <div className="inline-flex items-center gap-1.5">
            <Clock size={12} className="text-ink-3" />
            <select
              value={hoursBack}
              onChange={(e) => setHoursBack(Number(e.target.value))}
              className="text-[12px] py-1 px-2 rounded-sm"
              style={{ background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--ink-1)' }}
            >
              {HOUR_OPTIONS
                .filter((o) => o.hours <= retentionDays * 24)
                .map((o) => <option key={o.hours} value={o.hours}>{o.label}</option>)}
            </select>
          </div>

          {/* Level filter */}
          <div className="inline-flex items-center gap-0.5">
            {['all', 'err', 'warn', 'ok', 'info'].map((lv) => (
              <button
                key={lv}
                onClick={() => setLevelFilter(lv)}
                className={`btn btn-sm ${levelFilter === lv ? 'btn-primary' : 'btn-ghost'}`}
                title={`Filter ${lv}`}
              >
                {lv === 'all' ? 'All' : lv.toUpperCase()}
              </button>
            ))}
          </div>

          <div className="ml-auto inline-flex items-center gap-2">
            <SearchBox value={query} onChange={setQuery} placeholder="Filter (server-side)…" />
            <StatusPill tone={paused ? 'warn' : 'info'} dot>
              {paused ? 'paused' : 'live'} · {counts.total}
            </StatusPill>
          </div>
        </div>

        {/* Sticky banner if CloudWatch is unavailable (local dev mode) */}
        {!hasCloudWatch && (
          <div className="px-3 py-1.5 text-[11px] flex items-center gap-2" style={{ background: 'var(--surface-2)', color: 'var(--warn)', borderBottom: '1px solid var(--border)' }}>
            <AlertTriangle size={11} />
            CloudWatch is not reachable from this api-server (likely local dev). Showing local output files + in-memory progress steps instead.
          </div>
        )}

        {err && (
          <div className="px-3 py-1.5 text-[11px] flex items-center gap-2" style={{ background: 'var(--surface-2)', color: 'var(--err)', borderBottom: '1px solid var(--border)' }}>
            <AlertTriangle size={11} /> {err}
          </div>
        )}

        {/* Log viewer */}
        <div
          ref={scrollRef}
          onScroll={onScroll}
          className="font-mono text-[11px] leading-[1.55] overflow-auto"
          style={{
            height: 'calc(100vh - 280px)',
            minHeight: 360,
            background: 'var(--bg)',
            color: 'var(--ink-2)',
            padding: '8px 12px',
          }}
        >
          {filtered.length === 0 ? (
            <div className="py-10">
              <EmptyState
                icon={ScrollText}
                title={polling ? 'Loading events…' : 'No events in this window'}
                hint={
                  paused
                    ? 'Live tail is paused. Click Resume to continue.'
                    : 'Try a wider time range, drop the search filter, or pick a different source. If a pipeline is running right now, it can take ~30s for events to land in CloudWatch.'
                }
              />
            </div>
          ) : (
            filtered.map((e, i) => {
              const lv = levelOf(e.msg);
              return (
                <div key={`${e.id || ''}-${i}`} className="flex gap-3 whitespace-pre-wrap break-words py-[1px] hover:bg-[var(--surface-2)]">
                  <span className="text-ink-4 shrink-0 tabular-nums">{fmtTs(e.ts)}</span>
                  <LevelChip level={lv} />
                  <span className="text-ink-4 shrink-0 truncate max-w-[180px]" title={e.src}>{e.src || '-'}</span>
                  <span style={{ color: lv === 'err' ? 'var(--err)' : lv === 'warn' ? 'var(--warn)' : lv === 'ok' ? 'var(--ok)' : 'var(--ink-2)' }}>
                    {e.msg}
                  </span>
                </div>
              );
            })
          )}
        </div>

        {/* Footer w/ "scroll to bottom" CTA when autoScroll is off */}
        {!autoScroll && (
          <div className="px-3 py-1.5 text-[11px] flex items-center gap-2 justify-between border-t" style={{ borderColor: 'var(--border)', background: 'var(--surface-2)' }}>
            <span className="text-ink-3">Auto-scroll paused (you scrolled up).</span>
            <button onClick={() => setAutoScroll(true)} className="btn btn-sm btn-primary">
              Jump to latest <ChevronDown size={11} />
            </button>
          </div>
        )}
      </Panel>
    </div>
  );
}
