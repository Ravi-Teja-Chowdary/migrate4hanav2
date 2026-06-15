// Wizard step 1: ECC source version × S/4 target version selection.
import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { api } from '../../lib/api';

const ECC_VERSIONS = [
  { id: 'EHP0', label: 'ECC 6.0 EHP0', year: '2005' },
  { id: 'EHP1', label: 'ECC 6.0 EHP1', year: '2006' },
  { id: 'EHP2', label: 'ECC 6.0 EHP2', year: '2007' },
  { id: 'EHP3', label: 'ECC 6.0 EHP3', year: '2008' },
  { id: 'EHP4', label: 'ECC 6.0 EHP4', year: '2009' },
  { id: 'EHP5', label: 'ECC 6.0 EHP5', year: '2011' },
  { id: 'EHP6', label: 'ECC 6.0 EHP6', year: '2013' },
  { id: 'EHP7', label: 'ECC 6.0 EHP7', year: '2014' },
  { id: 'EHP8', label: 'ECC 6.0 EHP8', year: '2016' },
];

const S4_VERSIONS = [
  { id: 'S4HANA_1909', label: 'S/4HANA 1909', year: '2019' },
  { id: 'S4HANA_2020', label: 'S/4HANA 2020', year: '2020' },
  { id: 'S4HANA_2021', label: 'S/4HANA 2021', year: '2021' },
  { id: 'S4HANA_2022', label: 'S/4HANA 2022', year: '2022' },
  { id: 'S4HANA_2023', label: 'S/4HANA 2023', year: '2023' },
  { id: 'S4HANA_2024', label: 'S/4HANA 2024', year: '2024' },
  { id: 'S4HANA_2025', label: 'S/4HANA 2025', year: '2025' },
];

export default function WizardVersions() {
  const { runId } = useParams();
  const nav = useNavigate();
  const [ecc, setEcc] = useState('');
  const [s4, setS4]   = useState('');
  const [err, setErr] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.wizardGet(runId)
      .then((w) => { setEcc(w.ecc_version || ''); setS4(w.s4_version || ''); })
      .catch((e) => setErr(e.message));
  }, [runId]);

  const onNext = async () => {
    if (!ecc || !s4) { setErr('Pick both source and target versions.'); return; }
    setSaving(true); setErr('');
    try {
      await api.wizardPatch(runId, {
        page: 'wizard-2-scope', ecc_version: ecc, s4_version: s4,
      });
      nav(`/wizard/${runId}/scope`);
    } catch (e) {
      setErr(e.message);
    } finally { setSaving(false); }
  };

  return (
    <WizardStep step={1} total={3} title="Source & target versions">
      <p className="text-sm text-slate-600 mb-6">
        Pick the ECC source release and the S/4HANA target release. The tool
        loads per-pair routing automatically (BAPI signatures, MC support,
        cluster-table behaviour).
      </p>

      {err && (
        <div className="text-red-700 text-sm bg-red-50 border border-red-200 rounded px-3 py-2 mb-4">
          {err}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <section>
          <div className="text-sm font-medium text-slate-700 mb-2">ECC source (from)</div>
          <div className="space-y-1">
            {ECC_VERSIONS.map((v) => (
              <Pick
                key={v.id} v={v} selected={ecc === v.id}
                onClick={() => setEcc(v.id)}
              />
            ))}
          </div>
        </section>
        <section>
          <div className="text-sm font-medium text-slate-700 mb-2">S/4HANA target (to)</div>
          <div className="space-y-1">
            {S4_VERSIONS.map((v) => (
              <Pick
                key={v.id} v={v} selected={s4 === v.id}
                onClick={() => setS4(v.id)}
              />
            ))}
          </div>
        </section>
      </div>

      <WizardNav onNext={onNext} disabled={saving || !ecc || !s4}>
        Next: scope
      </WizardNav>
    </WizardStep>
  );
}

function Pick({ v, selected, onClick }) {
  return (
    <button
      type="button" onClick={onClick}
      className={`w-full text-left px-3 py-2 rounded border ${
        selected
          ? 'border-orange-500 bg-orange-50'
          : 'border-slate-200 bg-white hover:border-slate-300'
      } flex items-center gap-3`}
    >
      <span className={`w-4 h-4 rounded-full border-2 ${
        selected ? 'border-orange-500 bg-orange-500' : 'border-slate-300'
      }`} />
      <span className="text-sm font-medium flex-1">{v.label}</span>
      <span className="text-xs text-slate-500">{v.year}</span>
    </button>
  );
}

export function WizardStep({ step, total, title, children }) {
  return (
    <div>
      <div className="text-xs text-slate-500 mb-1">Step {step} of {total}</div>
      <h1 className="text-2xl font-semibold mb-4">{title}</h1>
      <div className="bg-white border border-slate-200 rounded-lg p-6">
        {children}
      </div>
    </div>
  );
}

export function WizardNav({ onBack, onNext, disabled, children }) {
  return (
    <div className="mt-6 flex justify-between">
      {onBack ? (
        <button
          type="button" onClick={onBack}
          className="px-4 py-2 text-sm rounded border border-slate-300 hover:bg-slate-50"
        >
          Back
        </button>
      ) : <div />}
      <button
        type="button" onClick={onNext} disabled={disabled}
        className="px-4 py-2 text-sm rounded bg-orange-500 hover:bg-orange-600 disabled:bg-orange-300 text-white font-medium"
      >
        {children || 'Next'}
      </button>
    </div>
  );
}
