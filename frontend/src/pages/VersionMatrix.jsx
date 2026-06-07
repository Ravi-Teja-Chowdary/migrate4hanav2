import { useCallback, useEffect, useState } from 'react';
import {
  GitCompareArrows, ArrowRight, ShieldCheck, AlertTriangle, RefreshCcw,
  ChevronDown, Save, Server, Cloud, Cpu, Database, FileType2,
} from 'lucide-react';
import { api } from '../lib/api';
import { useApi } from '../lib/useApi';
import {
  Card, PageHeader, Badge, Spinner, OfflineBanner, ACCENT,
} from '../components/ui';

function Field({ k, v, mono = true }) {
  return (
    <div className="rounded-xl bg-slate-50 px-3 py-2 border border-line">
      <p className="text-[9px] uppercase tracking-wider text-ink-400 font-semibold">{k}</p>
      <p className={`text-[13px] ${mono ? 'font-mono' : ''} text-ink-700 truncate`}>{v || '—'}</p>
    </div>
  );
}

function VersionSelect({ label, value, onChange, options, icon: Icon, accent }) {
  const a = ACCENT[accent];
  return (
    <Card className="p-5">
      <div className="flex items-center gap-3 mb-4">
        <div className={`w-10 h-10 rounded-2xl ${a.bg} flex items-center justify-center`}>
          <Icon size={18} className={a.text} />
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wider text-ink-400 font-semibold">{label}</p>
        </div>
      </div>
      <div className="relative">
        <select
          value={value || ''}
          onChange={(e) => onChange(e.target.value)}
          className="w-full appearance-none rounded-xl border border-line bg-slate-50 px-3.5 py-2.5 text-sm font-medium text-ink-800 focus:outline-none focus:ring-2 focus:ring-indigo-300/60 pr-9"
        >
          <option value="">— select —</option>
          {options.map((o) => (
            <option key={o.code} value={o.code}>{o.label}</option>
          ))}
        </select>
        <ChevronDown size={16} className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-400 pointer-events-none" />
      </div>
    </Card>
  );
}

function RoutingPanel({ routing }) {
  if (!routing) return null;
  const tiles = [
    { k: 'Extract strategy', v: routing.extract_strategy, icon: Cpu },
    { k: 'Package size', v: routing.package_size?.toLocaleString() + ' rows', icon: Database },
    { k: 'Template format', v: routing.template_format, icon: FileType2 },
    { k: 'Fargate fan-out', v: routing.fargate_fan_out, icon: Server },
    { k: 'Cluster-read safety', v: routing.cluster_read_safety, icon: ShieldCheck },
    { k: 'MC OData supported', v: routing.odata_ltmc_supported ? 'Yes' : 'No (runbook lane)', icon: Cloud },
  ];
  return (
    <Card className="p-6">
      <div className="flex items-center gap-2 mb-4">
        <Badge tone="ok"><ShieldCheck size={12} /> Pair is supported</Badge>
        <span className="text-[11px] text-ink-400">
          {routing.source.label} <ArrowRight size={11} className="inline" /> {routing.target.label}
        </span>
      </div>
      <p className="text-xs font-semibold text-ink-500 uppercase tracking-wider mb-3">Runtime routing the tool will use</p>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-2.5">
        {tiles.map((t) => (
          <div key={t.k} className="rounded-xl bg-slate-50 px-3 py-2.5 border border-line">
            <div className="flex items-center gap-1.5">
              <t.icon size={11} className="text-ink-400" />
              <p className="text-[9px] uppercase tracking-wider text-ink-400 font-semibold">{t.k}</p>
            </div>
            <p className="text-[13px] font-mono text-ink-700 mt-1">{t.v}</p>
          </div>
        ))}
      </div>
    </Card>
  );
}

export default function VersionMatrix() {
  const { data: supported, error, loading, reload } =
    useApi(useCallback(() => api.versionsSupported(), []));
  const { data: selected } = useApi(useCallback(() => api.versionsSelected(), []));

  const [sourceCode, setSourceCode] = useState('');
  const [targetCode, setTargetCode] = useState('');
  const [sourceDb, setSourceDb] = useState('');     // "", "HANA", "ANY_DB"
  const [routing, setRouting] = useState(null);
  const [incompatErr, setIncompatErr] = useState(null);
  const [detected, setDetected] = useState(null);
  const [detecting, setDetecting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveOk, setSaveOk] = useState(false);

  // Hydrate from saved selection
  useEffect(() => {
    if (selected?.selected) {
      setSourceCode(selected.selected.source_code || '');
      setTargetCode(selected.selected.target_code || '');
      setSourceDb(selected.selected.source_db || '');
      setRouting(selected.routing || null);
    }
  }, [selected]);

  // Recompute routing locally whenever selection changes (cheap; just resolve from supported.valid_pairs)
  useEffect(() => {
    if (!sourceCode || !targetCode || !supported) { setRouting(null); setIncompatErr(null); return; }
    const pair = (supported.valid_pairs || []).find(
      (p) => p.source_code === sourceCode && p.target_code === targetCode,
    );
    if (!pair) {
      setIncompatErr(`${sourceCode} -> ${targetCode} is not in the supported matrix.`);
      setRouting(null);
      return;
    }
    setIncompatErr(null);
    // For full routing fields we lean on the backend. Trigger a fetch when we save;
    // here we render the lightweight pair info inline so the user gets instant feedback.
    setRouting({
      source: { label: pair.source_label, code: pair.source_code },
      target: { label: pair.target_label, code: pair.target_code },
      extract_strategy: sourceDb === 'HANA' ? 'MODERN_BULK' : pair.extract_strategy,
      package_size: sourceDb === 'HANA' ? 25000 : 5000,
      template_format: pair.template_format,
      fargate_fan_out: sourceDb === 'HANA' ? 'HIGH' : pair.fargate_fan_out,
      cluster_read_safety: sourceDb === 'HANA' ? 'RELAXED' : 'STRICT',
      odata_ltmc_supported: pair.target_code !== 'S4HANA_1909',
    });
  }, [sourceCode, targetCode, sourceDb, supported]);

  const runDetect = async () => {
    setDetecting(true); setDetected(null);
    try {
      const d = await api.versionsDetected();
      setDetected(d);
      // auto-fill if confidently detected
      if (d?.source?.detected?.code) setSourceCode(d.source.detected.code);
      if (d?.target?.detected?.code) setTargetCode(d.target.detected.code);
      if (d?.source?.detected?.db_default) setSourceDb(d.source.detected.db_default);
    } catch (e) {
      setDetected({ error: e.message });
    } finally { setDetecting(false); }
  };

  const save = async () => {
    setSaving(true); setSaveOk(false);
    try {
      await api.saveVersions({
        source_code: sourceCode,
        target_code: targetCode,
        source_db:   sourceDb || null,
        detected_at: detected?.source?.detected ? new Date().toISOString() : null,
      });
      setSaveOk(true);
      setTimeout(() => setSaveOk(false), 2500);
    } catch (e) {
      setIncompatErr(e.message);
    } finally { setSaving(false); }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-ink-400 text-sm py-20 justify-center">
        <Spinner /> Loading version matrix…
      </div>
    );
  }
  if (error) {
    return (
      <div className="space-y-7">
        <PageHeader title="Version" accentWord="Matrix" subtitle="Pick the source ECC + target S/4 pair the migration will run for." />
        <OfflineBanner onRetry={reload} />
      </div>
    );
  }

  return (
    <div className="space-y-7">
      <PageHeader
        title="Version"
        accentWord="Matrix"
        subtitle="Pick the source ECC + target S/4 pair the migration will run for. The selection drives extract strategy, template format, BAPI version, and Fargate fan-out."
      />

      {/* Auto-detect bar */}
      <Card className="p-5">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
          <div>
            <p className="text-[11px] uppercase tracking-wider text-ink-400 font-semibold mb-1">Auto-detect</p>
            <p className="text-sm text-ink-600">Call RFC_SYSTEM_INFO + read CVERS to determine the live versions of both systems.</p>
          </div>
          <button
            onClick={runDetect}
            disabled={detecting}
            className="btn-primary inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
          >
            {detecting ? <Spinner /> : <RefreshCcw size={14} />}
            {detecting ? 'Detecting…' : 'Detect now'}
          </button>
        </div>

        {detected && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
            <div className="rounded-xl bg-slate-50 px-4 py-3 border border-line">
              <p className="text-[10px] uppercase tracking-wider text-ink-400 font-semibold">Source ECC</p>
              {detected.source?.detected
                ? <Field k="Detected" v={`${detected.source.detected.label}  ·  DB ${detected.source.detected.db_default}`} mono={false} />
                : <p className="text-xs text-amber-700 mt-1.5">{detected.source?.error || 'no detection'}</p>}
            </div>
            <div className="rounded-xl bg-slate-50 px-4 py-3 border border-line">
              <p className="text-[10px] uppercase tracking-wider text-ink-400 font-semibold">Target S/4</p>
              {detected.target?.detected
                ? <Field k="Detected" v={detected.target.detected.label} mono={false} />
                : <p className="text-xs text-amber-700 mt-1.5">{detected.target?.error || 'no detection'}</p>}
            </div>
          </div>
        )}
      </Card>

      {/* Selectors */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <VersionSelect
          label="Source · SAP ECC"
          icon={Server}
          accent="indigo"
          value={sourceCode}
          onChange={setSourceCode}
          options={(supported?.sources || []).map((s) => ({ code: s.code, label: s.label }))}
        />
        <VersionSelect
          label="Target · SAP S/4HANA"
          icon={Cloud}
          accent="teal"
          value={targetCode}
          onChange={setTargetCode}
          options={(supported?.targets || []).map((t) => ({ code: t.code, label: t.label }))}
        />
      </div>

      {/* Source DB override */}
      <Card className="p-5">
        <p className="text-[11px] uppercase tracking-wider text-ink-400 font-semibold mb-2">Source database (override)</p>
        <p className="text-xs text-ink-500 mb-3">
          ECC defaults assume traditional RDBMS (Oracle / MSSQL / DB2). If the source actually runs on SAP HANA, set this to enable
          the MODERN_BULK extract path and ~5× higher Fargate fan-out.
        </p>
        <div className="flex gap-2">
          {['', 'HANA', 'ANY_DB'].map((opt) => (
            <button
              key={opt || 'none'}
              onClick={() => setSourceDb(opt)}
              className={`rounded-xl border px-4 py-2 text-sm font-medium ${
                sourceDb === opt
                  ? 'border-indigo-400 bg-indigo-50 text-indigo-700'
                  : 'border-line bg-slate-50 text-ink-600 hover:bg-white'
              }`}
            >
              {opt || 'Use catalogue default'}
            </button>
          ))}
        </div>
      </Card>

      {/* Compatibility + routing */}
      {incompatErr && (
        <Card className="p-5 border-amber-300 bg-amber-50/60">
          <div className="flex items-start gap-2">
            <AlertTriangle size={16} className="text-amber-600 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-semibold text-amber-800">Pair not supported</p>
              <p className="text-xs text-amber-700 mt-0.5">{incompatErr}</p>
            </div>
          </div>
        </Card>
      )}
      <RoutingPanel routing={routing} />

      {/* Save */}
      <div className="flex items-center justify-end gap-3">
        {saveOk && <Badge tone="ok"><ShieldCheck size={12} /> Saved</Badge>}
        <button
          onClick={save}
          disabled={!sourceCode || !targetCode || !!incompatErr || saving}
          className="btn-primary inline-flex items-center gap-2 rounded-xl px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
        >
          {saving ? <Spinner /> : <Save size={15} />}
          {saving ? 'Saving…' : 'Save selection'}
        </button>
      </div>
    </div>
  );
}
