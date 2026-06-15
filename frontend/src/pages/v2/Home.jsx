// Home: choose Existing or New migration.
import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../../lib/api';

export default function Home() {
  const [existing, setExisting] = useState([]);
  const [err, setErr] = useState('');
  const nav = useNavigate();

  useEffect(() => {
    api.wizardList()
      .then((d) => setExisting(d.wizards || []))
      .catch((e) => setErr(e.message));
  }, []);

  const startNew = async () => {
    try {
      const r = await api.wizardCreate({});
      nav(`/wizard/${r.run_id}/versions`);
    } catch (e) {
      setErr(e.message);
    }
  };

  return (
    <div>
      <h1 className="text-2xl font-semibold mb-1">Welcome</h1>
      <p className="text-slate-500 mb-6">Pick up an existing migration or start a fresh one.</p>

      {err && (
        <div className="text-red-700 text-sm bg-red-50 border border-red-200 rounded px-3 py-2 mb-4">
          {err}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card
          title="New migration"
          desc="Start a new ECC → S/4HANA migration. We'll guide you through version selection, scope, credentials, and connection testing before the first row moves."
          cta="Start new migration"
          onClick={startNew}
          accent="orange"
        />
        <Card
          title="Existing migration"
          desc="Continue an in-flight migration. Pick a project below to resume from where you left off."
          accent="blue"
        />
      </div>

      <div className="mt-8">
        <div className="text-sm font-medium text-slate-700 mb-2">In-flight projects</div>
        {existing.length === 0 ? (
          <div className="text-sm text-slate-500 bg-white border border-slate-200 rounded p-4">
            No in-flight migrations. Click "Start new migration" above.
          </div>
        ) : (
          <ul className="bg-white border border-slate-200 rounded divide-y divide-slate-100">
            {existing.map((w) => (
              <ResumeItem key={w.run_id} w={w} nav={nav} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function Card({ title, desc, cta, onClick, accent = 'orange' }) {
  const accents = {
    orange: 'border-orange-200 hover:border-orange-400',
    blue:   'border-blue-200 hover:border-blue-400',
  };
  const buttonAccents = {
    orange: 'bg-orange-500 hover:bg-orange-600 text-white',
    blue:   'bg-blue-600 hover:bg-blue-700 text-white',
  };
  return (
    <div className={`bg-white border-2 ${accents[accent]} rounded-lg p-6 transition-colors`}>
      <div className="text-lg font-semibold mb-2">{title}</div>
      <div className="text-sm text-slate-600 leading-relaxed mb-4">{desc}</div>
      {cta && (
        <button
          onClick={onClick}
          className={`px-4 py-2 rounded text-sm font-medium ${buttonAccents[accent]}`}
        >
          {cta}
        </button>
      )}
    </div>
  );
}

function ResumeItem({ w, nav }) {
  const pageMap = {
    'wizard-1-versions':       'versions',
    'wizard-2-scope':          'scope',
    'wizard-3-connect':        'connect',
    'project':                 'project',
  };
  const route = pageMap[w.page] || 'versions';
  return (
    <li className="p-4 flex items-center gap-4 hover:bg-slate-50">
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium truncate">{w.run_id}</div>
        <div className="text-xs text-slate-500 mt-0.5">
          {w.client_id || 'no client'} ·
          {' '}{w.migration_type ? w.migration_type : 'no scope yet'} ·
          {' '}page {w.page || 'unknown'} ·
          updated {w.updated_at?.replace('T', ' ').replace('Z', '')}
        </div>
      </div>
      <button
        onClick={() => {
          if (route === 'project') nav(`/project/${w.run_id}`);
          else nav(`/wizard/${w.run_id}/${route}`);
        }}
        className="px-3 py-1 text-xs rounded bg-slate-900 text-white hover:bg-slate-700"
      >
        Resume
      </button>
    </li>
  );
}
