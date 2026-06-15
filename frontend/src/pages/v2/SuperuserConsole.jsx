// Root-only command console. Clickable buttons with descriptions, when-
// to-use, danger labels, and an I-UNDERSTAND confirm for danger=danger.
import React, { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import { useAuth } from '../../lib/auth';

export default function SuperuserConsole() {
  const { isRoot } = useAuth();
  const [commands, setCommands] = useState([]);
  const [activeCmd, setActiveCmd] = useState(null);
  const [err, setErr] = useState('');

  useEffect(() => {
    if (!isRoot) return;
    api.adminCommands().then((d) => setCommands(d.commands || []))
      .catch((e) => setErr(e.message));
  }, [isRoot]);

  if (!isRoot) {
    return (
      <div className="text-red-700 bg-red-50 border border-red-200 rounded p-4">
        Root role required.
      </div>
    );
  }

  const byCategory = {};
  for (const c of commands) {
    (byCategory[c.category] = byCategory[c.category] || []).push(c);
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold mb-1">Command Console</h1>
      <p className="text-sm text-slate-500 mb-6">
        CLI-equivalent operations for the root user. Hover any button to see
        when to use it. Danger commands require an "I-UNDERSTAND" confirm.
      </p>

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
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {items.map((c) => (
              <CommandCard key={c.id} cmd={c} onClick={() => setActiveCmd(c)} />
            ))}
          </div>
        </section>
      ))}

      {activeCmd && (
        <ExecuteDialog
          cmd={activeCmd} onClose={() => setActiveCmd(null)}
        />
      )}
    </div>
  );
}

function CommandCard({ cmd, onClick }) {
  const borderByDanger = {
    safe:    'border-slate-200 hover:border-emerald-400',
    caution: 'border-amber-200 hover:border-amber-400',
    danger:  'border-red-300 hover:border-red-500',
  };
  return (
    <button
      onClick={onClick}
      className={`text-left bg-white border-2 ${borderByDanger[cmd.danger]} rounded-lg p-4 transition-colors`}
    >
      <div className="flex items-start gap-3 mb-2">
        <DangerPill danger={cmd.danger} />
        <div className="text-base font-semibold flex-1">{cmd.label}</div>
        {!cmd.reversible && (
          <span className="text-xs text-amber-700 bg-amber-50 px-2 py-0.5 rounded">
            irreversible
          </span>
        )}
      </div>
      <div className="text-sm text-slate-700 leading-relaxed mb-2">
        {cmd.what}
      </div>
      <div className="text-xs text-slate-500 leading-relaxed">
        <strong>When:</strong> {cmd.when}
      </div>
    </button>
  );
}

function DangerPill({ danger }) {
  const styles = {
    safe:    'bg-emerald-100 text-emerald-800',
    caution: 'bg-amber-100 text-amber-800',
    danger:  'bg-red-100 text-red-800',
  };
  return (
    <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded ${styles[danger]}`}>
      {danger}
    </span>
  );
}

function ExecuteDialog({ cmd, onClose }) {
  const [params, setParams] = useState(() => {
    const init = {};
    for (const p of cmd.params || []) init[p.name] = '';
    return init;
  });
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState('');

  const onExec = async () => {
    setExecuting(true); setErr(''); setResult(null);
    try {
      const r = await api.adminExecute(cmd.id, params);
      setResult(r);
    } catch (e) { setErr(e.data?.detail?.error || e.message); }
    finally { setExecuting(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/40 grid place-items-center px-4 z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div className="px-5 py-4 border-b border-slate-200 flex items-center gap-3">
          <DangerPill danger={cmd.danger} />
          <div className="font-semibold flex-1">{cmd.label}</div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700 text-2xl leading-none">×</button>
        </div>

        <div className="p-5 space-y-4">
          <div className="text-sm text-slate-700">{cmd.what}</div>
          <div className="text-sm text-slate-600 bg-slate-50 border border-slate-200 rounded px-3 py-2">
            <strong>When to use:</strong> {cmd.when}
          </div>
          {cmd.danger === 'danger' && (
            <div className="text-sm bg-red-50 border border-red-300 text-red-900 rounded px-3 py-2">
              <strong>⚠️ Dangerous operation.</strong> This action is{' '}
              {cmd.reversible ? 'reversible' : 'irreversible'}. The "confirm"
              field below must be set to exactly <code>I-UNDERSTAND</code> to
              proceed.
            </div>
          )}

          {(cmd.params || []).map((p) => (
            <Param key={p.name} p={p} value={params[p.name]}
                    onChange={(v) => setParams({ ...params, [p.name]: v })} />
          ))}

          {err && (
            <div className="text-red-700 text-sm bg-red-50 border border-red-200 rounded px-3 py-2">
              {err}
            </div>
          )}

          {result && (
            <div className="bg-slate-900 text-slate-100 text-xs rounded p-3 max-h-64 overflow-y-auto">
              <pre className="whitespace-pre-wrap break-words font-mono">
                {JSON.stringify(result, null, 2)}
              </pre>
            </div>
          )}
        </div>

        <div className="px-5 py-4 border-t border-slate-200 flex justify-end gap-2">
          <button onClick={onClose}
                  className="px-4 py-2 text-sm rounded border border-slate-300 hover:bg-slate-50">
            Close
          </button>
          <button onClick={onExec} disabled={executing}
                  className={`px-4 py-2 text-sm rounded text-white font-medium ${
                    cmd.danger === 'danger'
                      ? 'bg-red-600 hover:bg-red-700 disabled:bg-red-400'
                      : 'bg-orange-500 hover:bg-orange-600 disabled:bg-orange-300'
                  }`}>
            {executing ? 'Running…' : 'Execute'}
          </button>
        </div>
      </div>
    </div>
  );
}

function Param({ p, value, onChange }) {
  return (
    <label className="block">
      <div className="text-xs font-medium text-slate-700 mb-1">
        {p.name}
        {p.required && <span className="text-red-600 ml-1">*</span>}
        {p.type && <span className="text-slate-400 ml-2">({p.type})</span>}
      </div>
      <input
        className="w-full text-sm px-3 py-2 border border-slate-300 rounded focus:outline-none focus:border-orange-500"
        type={p.type === 'integer' ? 'number' : 'text'}
        value={value || ''}
        onChange={(e) => onChange(e.target.value)}
        placeholder={p.description}
      />
      {p.description && <div className="text-xs text-slate-500 mt-1">{p.description}</div>}
    </label>
  );
}
