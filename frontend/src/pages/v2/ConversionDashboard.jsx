// Simplified conversion dashboard: source-table -> target-structure with
// plain-English narratives + live progress bars. Designed for non-technical
// stakeholders.
import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { api } from '../../lib/api';

export default function ConversionDashboard() {
  const { runId } = useParams();
  const [rows, setRows] = useState([]);
  const [err, setErr] = useState('');

  useEffect(() => {
    let cancelled = false;
    let timer = null;
    async function poll() {
      try {
        const d = await api.conversionProgress(runId);
        if (cancelled) return;
        setRows(d.rows || []);
      } catch (e) { if (!cancelled) setErr(e.message); }
      if (!cancelled) timer = setTimeout(poll, 4000);
    }
    poll();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [runId]);

  const byCategory = {};
  for (const r of rows) {
    (byCategory[r.category] = byCategory[r.category] || []).push(r);
  }
  const totals = aggregate(rows);

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-white border-b border-slate-200 px-4 py-3">
        <div className="max-w-6xl mx-auto flex items-center gap-4">
          <div className="font-semibold">What's being converted</div>
          <div className="text-xs text-slate-500">{runId}</div>
          <div className="ml-auto text-sm text-slate-600">
            <strong>{totals.complete}</strong> done · {totals.running} running ·{' '}
            {totals.pending} pending · {totals.rows_loaded.toLocaleString()} rows landed
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto p-6">
        {err && (
          <div className="text-red-700 text-sm bg-red-50 border border-red-200 rounded px-3 py-2 mb-4">
            {err}
          </div>
        )}

        {Object.entries(byCategory).map(([cat, items]) => (
          <section key={cat} className="mb-6">
            <div className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-3">
              {cat}
            </div>
            <div className="space-y-3">
              {items.map((r) => <ConversionRow key={r.object} r={r} />)}
            </div>
          </section>
        ))}

        <div className="text-xs text-slate-400 mt-8 leading-relaxed">
          This dashboard shows the plain-English mapping from ECC tables to
          their S/4HANA structures. Many objects keep the same table name on
          S/4; some (Customer / Vendor) are unified into BUT000 Business
          Partner; FI line items consolidate into ACDOCA Universal Journal.
        </div>
      </main>
    </div>
  );
}

function ConversionRow({ r }) {
  const status = r.status || 'pending';
  const bar = status === 'complete' ? 'bg-emerald-500'
            : status === 'failed'   ? 'bg-red-500'
            : status === 'running'  ? 'bg-blue-500'
                                    : 'bg-slate-300';
  return (
    <div className="bg-white border border-slate-200 rounded-lg p-4">
      <div className="flex items-start gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 mb-1.5">
            <div className="text-base font-semibold">{r.object}</div>
            <StatusPill status={status} />
            <span className="text-xs text-slate-500">{r.lane} lane</span>
          </div>
          <div className="text-sm text-slate-700 mb-2 font-mono">
            <span className="text-slate-500">ECC</span> {r.ecc_tables.join(' + ')}
            <span className="text-slate-400 px-2">→</span>
            <span className="text-slate-500">S/4</span> {r.s4_targets.join(' + ')}
          </div>
          <div className="text-xs text-slate-600 leading-relaxed">{r.narrative}</div>
        </div>
        <div className="text-right text-xs text-slate-500 w-32 shrink-0">
          <div className="text-base font-semibold text-slate-900">
            {r.percent.toFixed(1)}%
          </div>
          <div>{r.rows_loaded.toLocaleString()} / {r.rows_total.toLocaleString()}</div>
          {r.rps > 0 && <div>{r.rps.toFixed(1)} rps</div>}
        </div>
      </div>
      <div className="h-1.5 mt-3 rounded-full bg-slate-100 overflow-hidden">
        <div
          className={`h-full ${bar} transition-all duration-300`}
          style={{ width: `${Math.min(100, r.percent)}%` }}
        />
      </div>
    </div>
  );
}

function StatusPill({ status }) {
  const styles = {
    pending:  'bg-slate-200 text-slate-700',
    running:  'bg-blue-100 text-blue-700',
    complete: 'bg-emerald-100 text-emerald-800',
    failed:   'bg-red-100 text-red-700',
  };
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded ${styles[status] || styles.pending}`}>
      {status}
    </span>
  );
}

function aggregate(rows) {
  const t = { complete: 0, running: 0, pending: 0, failed: 0, rows_loaded: 0 };
  for (const r of rows) {
    t[r.status] = (t[r.status] || 0) + 1;
    t.rows_loaded += r.rows_loaded || 0;
  }
  return t;
}
