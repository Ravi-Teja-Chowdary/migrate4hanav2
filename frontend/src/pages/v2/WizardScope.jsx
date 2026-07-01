// Wizard step 2: full vs selective migration scope.
import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { api } from '../../lib/api';
import { WizardStep, WizardNav } from './WizardVersions';

export default function WizardScope() {
  const { runId } = useParams();
  const nav = useNavigate();
  const [type, setType] = useState('full');
  const [selectedObjects, setSelectedObjects] = useState([]);
  const [mappings, setMappings] = useState([]);
  const [err, setErr] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.wizardGet(runId).then((w) => {
      setType(w.migration_type || 'full');
      setSelectedObjects(w.selective_objects || []);
    }).catch((e) => setErr(e.message));
    api.mappingAll().then((d) => setMappings(d.mappings || []))
      .catch((e) => setErr(e.message));
  }, [runId]);

  const toggle = (obj) => {
    setSelectedObjects((cur) =>
      cur.includes(obj) ? cur.filter((x) => x !== obj) : [...cur, obj]);
  };

  const onNext = async () => {
    if (type === 'selective' && selectedObjects.length === 0) {
      setErr('Pick at least one object for selective migration.');
      return;
    }
    setSaving(true); setErr('');
    try {
      await api.wizardPatch(runId, {
        page: 'wizard-3-connect',
        migration_type: type,
        selective_objects: type === 'selective' ? selectedObjects : [],
      });
      nav(`/wizard/${runId}/connect`);
    } catch (e) {
      setErr(e.message);
    } finally { setSaving(false); }
  };

  return (
    <WizardStep step={2} total={3} title="Migration scope">
      <p className="text-sm text-slate-600 mb-6">
        Migrate everything in the catalog, or only the objects you care
        about. Selective migration uses tighter SAP authorisations and a
        faster pre-flight check.
      </p>

      {err && (
        <div className="text-red-700 text-sm bg-red-50 border border-red-200 rounded px-3 py-2 mb-4">
          {err}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <ScopeCard
          title="Full migration"
          desc="Migrate every applicable object across the curated catalog: master data, customising, open items, stock, transaction data. Best for end-state cutover."
          accent="orange"
          selected={type === 'full'}
          onClick={() => setType('full')}
        />
        <ScopeCard
          title="Selective migration"
          desc="Migrate only the objects you choose below. Best for phased cutovers, pilots, or testing a single domain end-to-end."
          accent="blue"
          selected={type === 'selective'}
          onClick={() => setType('selective')}
        />
      </div>

      {type === 'selective' && (
        <div>
          <div className="text-sm font-medium text-slate-700 mb-2">
            Pick objects to migrate ({selectedObjects.length} selected)
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2 max-h-96 overflow-y-auto pr-2">
            {mappings.map((m) => (
              <ObjectRow
                key={m.object} m={m}
                checked={selectedObjects.includes(m.object)}
                onToggle={() => toggle(m.object)}
              />
            ))}
          </div>
        </div>
      )}

      <div className="mt-6">
        <MappingUpload />
      </div>

      <WizardNav
        onBack={() => nav(`/wizard/${runId}/versions`)}
        onNext={onNext}
        disabled={saving}
      >
        Next: connect
      </WizardNav>
    </WizardStep>
  );
}

// Small self-contained widget: download the mapping template, edit in Excel,
// drop it back onto the zone. Validation runs server-side (rules from the
// backend transformation_engine) and results render inline. Optional: the
// wizard flow does not require this to proceed.
function MappingUpload() {
  const [state, setState] = useState({ status: 'idle', result: null, filename: '' });
  const inputRef = React.useRef(null);

  const onFile = async (file) => {
    if (!file) return;
    setState({ status: 'validating', result: null, filename: file.name });
    try {
      const text = await file.text();
      const result = await api.validateMapping(text);
      setState({ status: result.ok ? 'ok' : 'error', result, filename: file.name });
    } catch (e) {
      setState({ status: 'error',
                 result: { ok: false, row_count: 0,
                           errors: [{ row: 0, column: '', message: e.message }] },
                 filename: file.name });
    }
  };

  const onDrop = (e) => {
    e.preventDefault();
    onFile(e.dataTransfer.files?.[0]);
  };

  return (
    <div className="border-t border-slate-200 pt-5">
      <div className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-2">
        Optional — Custom field mappings
      </div>
      <p className="text-xs text-slate-600 mb-3 leading-relaxed">
        Download the template, add source-field → target-field pairs in Excel,
        and drop it back here. Validation runs against the target metadata; you
        get a pass/fail list with row-specific callouts before the migration
        touches anything.
      </p>
      <div className="flex items-start gap-4 flex-wrap">
        <a
          href={api.mappingTemplatePath()}
          className="px-3 py-2 rounded border border-slate-300 text-sm hover:bg-slate-50"
          download
        >
          Download template
        </a>
        <div
          onDragOver={(e) => e.preventDefault()}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
          className="flex-1 min-w-[240px] border-2 border-dashed border-slate-300 rounded p-4 text-center text-sm text-slate-500 cursor-pointer hover:border-blue-400 hover:bg-blue-50"
        >
          {state.filename
            ? `Selected: ${state.filename}`
            : 'Drop mapping CSV here, or click to browse'}
          <input
            ref={inputRef}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={(e) => onFile(e.target.files?.[0])}
          />
        </div>
      </div>

      {state.status === 'validating' && (
        <div className="mt-3 text-sm text-slate-500">Validating…</div>
      )}
      {state.status === 'ok' && (
        <div className="mt-3 text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-3 py-2">
          ✓ Mapping valid — {state.result.row_count} rows accepted.
        </div>
      )}
      {state.status === 'error' && (
        <div className="mt-3 text-sm bg-red-50 border border-red-200 rounded px-3 py-2">
          <div className="font-medium text-red-800 mb-1">
            {state.result.errors.length} validation error{state.result.errors.length === 1 ? '' : 's'}
          </div>
          <ul className="space-y-0.5 max-h-40 overflow-y-auto text-xs text-red-700">
            {state.result.errors.map((e, i) => (
              <li key={i}>
                <span className="font-mono">row {e.row}</span>
                {e.column ? <> · <span className="font-mono">{e.column}</span></> : null}
                : {e.message}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ScopeCard({ title, desc, accent, selected, onClick }) {
  const accents = {
    orange: selected ? 'border-orange-500 bg-orange-50' : 'border-slate-200 hover:border-orange-300',
    blue:   selected ? 'border-blue-500 bg-blue-50'     : 'border-slate-200 hover:border-blue-300',
  };
  return (
    <button
      type="button" onClick={onClick}
      className={`text-left border-2 ${accents[accent]} rounded-lg p-4 transition-colors`}
    >
      <div className="font-semibold text-base mb-1">{title}</div>
      <div className="text-sm text-slate-600 leading-relaxed">{desc}</div>
    </button>
  );
}

function ObjectRow({ m, checked, onToggle }) {
  return (
    <label
      className={`flex items-start gap-3 p-3 border rounded cursor-pointer ${
        checked ? 'border-orange-400 bg-orange-50' : 'border-slate-200 bg-white hover:border-slate-300'
      }`}
    >
      <input
        type="checkbox" checked={checked} onChange={onToggle}
        className="mt-1 accent-orange-500"
      />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium truncate">{m.object}</div>
        <div className="text-xs text-slate-500 truncate">
          {m.ecc_tables.join(', ')} → {m.s4_targets.join(', ')}
        </div>
        <div className="text-xs text-slate-400 mt-0.5">
          {m.category} · {m.lane} · ~{m.expected_rps}rps · {m.complexity} complexity
        </div>
      </div>
    </label>
  );
}
