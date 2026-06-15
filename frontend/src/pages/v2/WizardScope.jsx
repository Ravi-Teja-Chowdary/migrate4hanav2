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
