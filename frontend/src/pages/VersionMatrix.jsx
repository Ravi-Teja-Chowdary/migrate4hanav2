import { useCallback, useEffect, useState } from 'react';
import {
  ArrowRight, ShieldCheck, AlertTriangle, RefreshCcw, ChevronDown, Save,
  Server, Cloud, Cpu, Database, FileType2, GitCompareArrows,
} from 'lucide-react';
import { api } from '../lib/api';
import { useApi } from '../lib/useApi';
import { Panel, PageHeader, StatusPill, MetricTile, Spinner, OfflineBanner, KVList } from '../components/dd';

function VersionSelect({ label, value, onChange, options, icon: Icon }) {
  return (
    <Panel title={label} icon={Icon}>
      <div className="relative">
        <select
          value={value || ''}
          onChange={(e) => onChange(e.target.value)}
          className="input w-full pr-9 appearance-none"
        >
          <option value="">— select —</option>
          {options.map((o) => (
            <option key={o.code} value={o.code}>{o.label}</option>
          ))}
        </select>
        <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-4 pointer-events-none" />
      </div>
    </Panel>
  );
}

function RoutingPanel({ routing }) {
  if (!routing) return null;
  const items = [
    { label: 'Extract strategy',     value: routing.extract_strategy },
    { label: 'Package size',         value: `${routing.package_size?.toLocaleString()} rows` },
    { label: 'Template format',      value: routing.template_format },
    { label: 'Fargate fan-out',      value: routing.fargate_fan_out },
    { label: 'Cluster-read safety',  value: routing.cluster_read_safety },
    { label: 'MC OData supported',   value: routing.odata_ltmc_supported ? 'Yes' : 'No (runbook lane)' },
  ];
  return (
    <Panel
      title="Runtime routing"
      subtitle={`${routing.source.label} → ${routing.target.label}`}
      icon={GitCompareArrows}
      actions={<StatusPill tone="ok"><ShieldCheck size={11} /> supported</StatusPill>}
    >
      <KVList cols={3} items={items} />
    </Panel>
  );
}

export default function VersionMatrix() {
  const { data: supported, error, loading, reload } = useApi(useCallback(() => api.versionsSupported(), []));
  const { data: selected } = useApi(useCallback(() => api.versionsSelected(), []));

  const [sourceCode, setSourceCode] = useState('');
  const [targetCode, setTargetCode] = useState('');
  const [sourceDb, setSourceDb] = useState('');
  const [routing, setRouting] = useState(null);
  const [incompatErr, setIncompatErr] = useState(null);
  const [detected, setDetected] = useState(null);
  const [detecting, setDetecting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveOk, setSaveOk] = useState(false);

  useEffect(() => {
    if (selected?.selected) {
      setSourceCode(selected.selected.source_code || '');
      setTargetCode(selected.selected.target_code || '');
      setSourceDb(selected.selected.source_db || '');
      setRouting(selected.routing || null);
    }
  }, [selected]);

  useEffect(() => {
    if (!sourceCode || !targetCode || !supported) { setRouting(null); setIncompatErr(null); return; }
    const pair = (supported.valid_pairs || []).find(
      (p) => p.source_code === sourceCode && p.target_code === targetCode,
    );
    if (!pair) {
      setIncompatErr(`${sourceCode} → ${targetCode} is not in the supported matrix.`);
      setRouting(null);
      return;
    }
    setIncompatErr(null);
    setRouting({
      source: { label: pair.source_label, code: pair.source_code },
      target: { label: pair.target_label, code: pair.target_code },
      extract_strategy: sourceDb === 'HANA' ? 'MODERN_BULK' : pair.extract_strategy,
      package_size:     sourceDb === 'HANA' ? 25000 : 5000,
      template_format:  pair.template_format,
      fargate_fan_out:  sourceDb === 'HANA' ? 'HIGH' : pair.fargate_fan_out,
      cluster_read_safety: sourceDb === 'HANA' ? 'RELAXED' : 'STRICT',
      odata_ltmc_supported: pair.target_code !== 'S4HANA_1909',
    });
  }, [sourceCode, targetCode, sourceDb, supported]);

  const runDetect = async () => {
    setDetecting(true); setDetected(null);
    try {
      const d = await api.versionsDetected();
      setDetected(d);
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
        source_db: sourceDb || null,
        detected_at: detected?.source?.detected ? new Date().toISOString() : null,
      });
      setSaveOk(true);
      setTimeout(() => setSaveOk(false), 2500);
    } catch (e) {
      setIncompatErr(e.message);
    } finally { setSaving(false); }
  };

  if (loading) {
    return <div className="flex items-center gap-2 text-xs text-ink-3 py-20 justify-center"><Spinner /> Loading version matrix…</div>;
  }
  if (error) {
    return (
      <div className="space-y-4">
        <PageHeader title="Version matrix" breadcrumb={['Migrate4HANA', 'Versions']} subtitle="Pick the source ECC + target S/4 pair." />
        <OfflineBanner onRetry={reload} />
      </div>
    );
  }

  const totalPairs = supported?.valid_pairs?.length || 0;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Version matrix"
        breadcrumb={['Migrate4HANA', 'Versions']}
        subtitle="Pick the source ECC + target S/4 pair. Selection drives extract strategy, template format, BAPI version, and Fargate fan-out."
        actions={
          <button onClick={runDetect} disabled={detecting} className="btn btn-sm btn-primary">
            {detecting ? <Spinner size={12} /> : <RefreshCcw size={12} />} {detecting ? 'Detecting…' : 'Auto-detect'}
          </button>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <MetricTile label="Supported pairs" value={totalPairs} sub="in catalogue" />
        <MetricTile label="Sources" value={supported?.sources?.length || 0} sub="ECC variants" />
        <MetricTile label="Targets" value={supported?.targets?.length || 0} sub="S/4 variants" />
        <MetricTile
          label="Selection"
          value={sourceCode && targetCode && !incompatErr ? 'Valid' : sourceCode && targetCode ? 'Invalid' : 'None'}
          sub={sourceCode && targetCode ? `${sourceCode} → ${targetCode}` : 'pick both'}
          tone={incompatErr ? 'err' : sourceCode && targetCode ? 'ok' : null}
        />
      </div>

      {detected && (
        <Panel title="Auto-detect result" icon={RefreshCcw}>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <div className="metric-label">Source ECC</div>
              {detected.source?.detected
                ? <div className="text-[12.5px] text-ink-1 mt-1.5">{detected.source.detected.label} <span className="text-ink-4 font-mono ml-1">· DB {detected.source.detected.db_default}</span></div>
                : <div className="text-[11.5px] mt-1.5" style={{ color: 'var(--warn)' }}>{detected.source?.error || 'no detection'}</div>}
            </div>
            <div>
              <div className="metric-label">Target S/4</div>
              {detected.target?.detected
                ? <div className="text-[12.5px] text-ink-1 mt-1.5">{detected.target.detected.label}</div>
                : <div className="text-[11.5px] mt-1.5" style={{ color: 'var(--warn)' }}>{detected.target?.error || 'no detection'}</div>}
            </div>
          </div>
        </Panel>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <VersionSelect
          label="Source · SAP ECC"
          icon={Server}
          value={sourceCode}
          onChange={setSourceCode}
          options={(supported?.sources || []).map((s) => ({ code: s.code, label: s.label }))}
        />
        <VersionSelect
          label="Target · SAP S/4HANA"
          icon={Cloud}
          value={targetCode}
          onChange={setTargetCode}
          options={(supported?.targets || []).map((t) => ({ code: t.code, label: t.label }))}
        />
      </div>

      <Panel title="Source database override" icon={Database} subtitle="HANA enables MODERN_BULK extract + ~5× higher fan-out">
        <div className="flex flex-wrap gap-2">
          {[{ v: '', label: 'Use catalogue default' }, { v: 'HANA', label: 'HANA' }, { v: 'ANY_DB', label: 'ANY_DB' }].map((opt) => (
            <button
              key={opt.v || 'none'}
              onClick={() => setSourceDb(opt.v)}
              className={`btn btn-sm ${sourceDb === opt.v ? 'btn-primary' : ''}`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </Panel>

      {incompatErr && (
        <Panel>
          <div className="flex items-start gap-2">
            <AlertTriangle size={14} className="shrink-0 mt-0.5" style={{ color: 'var(--warn)' }} />
            <div>
              <div className="text-[13px] font-semibold text-ink-1">Pair not supported</div>
              <p className="text-[11.5px] text-ink-3 mt-0.5">{incompatErr}</p>
            </div>
          </div>
        </Panel>
      )}

      <RoutingPanel routing={routing} />

      <div className="flex items-center justify-end gap-3">
        {saveOk && <StatusPill tone="ok"><ShieldCheck size={11} /> saved</StatusPill>}
        <button
          onClick={save}
          disabled={!sourceCode || !targetCode || !!incompatErr || saving}
          className="btn btn-sm btn-primary"
        >
          {saving ? <Spinner size={12} /> : <Save size={12} />} {saving ? 'Saving…' : 'Save selection'}
        </button>
      </div>
    </div>
  );
}
