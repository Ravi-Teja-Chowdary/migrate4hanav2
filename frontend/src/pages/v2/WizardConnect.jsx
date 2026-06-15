// Wizard step 3: ECC + S/4 credentials + SAP-side configuration
// instructions + perm-aware "Test connection" before proceeding.
import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { api } from '../../lib/api';
import { WizardStep, WizardNav } from './WizardVersions';

const EMPTY_CONN = {
  ashost: '', sysnr: '00', client: '100', user: '', passwd: '',
  saprouter: '', gwhost: '', gwserv: '',
};

export default function WizardConnect() {
  const { runId } = useParams();
  const nav = useNavigate();
  const [wizard, setWizard] = useState(null);
  const [ecc, setEcc] = useState(EMPTY_CONN);
  const [s4, setS4]   = useState(EMPTY_CONN);
  const [eccTest, setEccTest] = useState(null);
  const [s4Test, setS4Test]   = useState(null);
  const [testing, setTesting] = useState({ ecc: false, s4: false });
  const [err, setErr] = useState('');

  useEffect(() => {
    api.wizardGet(runId).then((w) => {
      setWizard(w);
      if (w.ecc_conn) setEcc((c) => ({ ...c, ...w.ecc_conn }));
      if (w.s4_conn)  setS4((c)  => ({ ...c, ...w.s4_conn  }));
      if (w.connection_test_results) {
        setEccTest(w.connection_test_results.ecc);
        setS4Test(w.connection_test_results.s4);
      }
    }).catch((e) => setErr(e.message));
  }, [runId]);

  const testEcc = async () => {
    setTesting((t) => ({ ...t, ecc: true })); setErr('');
    try {
      const r = await api.testEccPermAware(
        ecc, wizard.migration_type, wizard.selective_objects);
      setEccTest(r);
    } catch (e) { setErr(e.message); }
    finally { setTesting((t) => ({ ...t, ecc: false })); }
  };

  const testS4 = async () => {
    setTesting((t) => ({ ...t, s4: true })); setErr('');
    try {
      const r = await api.testS4PermAware(
        s4, wizard.migration_type, wizard.selective_objects);
      setS4Test(r);
    } catch (e) { setErr(e.message); }
    finally { setTesting((t) => ({ ...t, s4: false })); }
  };

  const onNext = async () => {
    if (!eccTest?.ok || !s4Test?.ok) {
      setErr('Both connections must pass the permission check before continuing.');
      return;
    }
    try {
      await api.wizardPatch(runId, {
        page: 'project',
        ecc_conn: { ...ecc, passwd: '••••' },  // never persist plaintext password
        s4_conn:  { ...s4,  passwd: '••••' },
        connection_test_results: { ecc: eccTest, s4: s4Test },
        started_at: new Date().toISOString(),
      });
      // Save creds into the live connections store for the runtime
      await api.saveEcc(ecc);
      await api.saveS4(s4);
      nav(`/project/${runId}`);
    } catch (e) {
      setErr(e.message);
    }
  };

  if (!wizard) return <div className="text-slate-500">Loading…</div>;

  return (
    <WizardStep step={3} total={3} title="Connect & verify access">
      <p className="text-sm text-slate-600 mb-6">
        Enter the ECC and S/4 service-user credentials. We test both
        connections and verify the user has the right authorisations for the{' '}
        <strong>{wizard.migration_type || 'full'}</strong> migration you picked.
      </p>

      {err && (
        <div className="text-red-700 text-sm bg-red-50 border border-red-200 rounded px-3 py-2 mb-4">
          {err}
        </div>
      )}

      <SystemPanel
        label="ECC source" creds={ecc} setCreds={setEcc}
        instructions={ECC_INSTRUCTIONS(wizard.migration_type)}
        onTest={testEcc} testing={testing.ecc}
        result={eccTest}
      />

      <div className="h-6" />

      <SystemPanel
        label="S/4HANA target" creds={s4} setCreds={setS4}
        instructions={S4_INSTRUCTIONS(wizard.migration_type)}
        onTest={testS4} testing={testing.s4}
        result={s4Test}
      />

      <WizardNav
        onBack={() => nav(`/wizard/${runId}/scope`)}
        onNext={onNext}
        disabled={!eccTest?.ok || !s4Test?.ok}
      >
        Looks good — go to project
      </WizardNav>
    </WizardStep>
  );
}

function SystemPanel({ label, creds, setCreds, instructions, onTest, testing, result }) {
  return (
    <div className="border border-slate-200 rounded-lg">
      <div className="px-4 py-3 border-b border-slate-200 bg-slate-50 font-semibold">
        {label}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 p-4">
        <CredsForm creds={creds} setCreds={setCreds} />
        <Instructions text={instructions} />
      </div>
      <div className="px-4 pb-4 border-t border-slate-100 pt-4 bg-slate-50/50">
        <div className="flex items-center gap-3">
          <button
            onClick={onTest} disabled={testing || !creds.ashost || !creds.user}
            className="px-4 py-2 text-sm rounded bg-slate-900 hover:bg-slate-700 disabled:bg-slate-400 text-white font-medium"
          >
            {testing ? 'Testing…' : 'Test connection & permissions'}
          </button>
          {result && <TestVerdict r={result} />}
        </div>
        {result && <TestDetails r={result} />}
      </div>
    </div>
  );
}

function CredsForm({ creds, setCreds }) {
  const set = (k) => (e) => setCreds({ ...creds, [k]: e.target.value });
  return (
    <div className="space-y-3">
      <Field label="Application server host">
        <input className="input" value={creds.ashost} onChange={set('ashost')}
               placeholder="vhcalabaci.dummy.nodomain or 10.x.x.x" />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="System number">
          <input className="input" value={creds.sysnr} onChange={set('sysnr')} />
        </Field>
        <Field label="Client">
          <input className="input" value={creds.client} onChange={set('client')} />
        </Field>
      </div>
      <Field label="User">
        <input className="input" value={creds.user} onChange={set('user')}
                placeholder="M4H_MIGRATOR" />
      </Field>
      <Field label="Password">
        <input className="input" type="password" value={creds.passwd} onChange={set('passwd')} />
      </Field>
      <details className="text-xs text-slate-500">
        <summary className="cursor-pointer">SAProuter / gateway (optional)</summary>
        <div className="mt-2 space-y-2">
          <Field label="SAProuter"><input className="input" value={creds.saprouter} onChange={set('saprouter')} /></Field>
          <Field label="Gateway host"><input className="input" value={creds.gwhost} onChange={set('gwhost')} /></Field>
          <Field label="Gateway service"><input className="input" value={creds.gwserv} onChange={set('gwserv')} /></Field>
        </div>
      </details>
      <style>{`
        .input {
          width: 100%;
          padding: 0.45rem 0.625rem;
          border: 1px solid rgb(203 213 225);
          border-radius: 0.375rem;
          background: white;
          font-size: 0.875rem;
        }
        .input:focus {
          outline: none;
          border-color: rgb(249 115 22);
          box-shadow: 0 0 0 2px rgba(249,115,22,0.15);
        }
      `}</style>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label className="block">
      <div className="text-xs font-medium text-slate-600 mb-1">{label}</div>
      {children}
    </label>
  );
}

function Instructions({ text }) {
  return (
    <div className="bg-blue-50 border border-blue-200 rounded p-3">
      <div className="text-xs font-semibold text-blue-900 mb-2 uppercase tracking-wide">
        SAP-side configuration
      </div>
      <pre className="text-xs text-slate-700 leading-relaxed whitespace-pre-wrap font-sans">
        {text}
      </pre>
    </div>
  );
}

function TestVerdict({ r }) {
  if (r.ok) {
    return <span className="text-emerald-700 text-sm font-medium">✓ all permissions OK</span>;
  }
  // Use the explicit failure_class set by the server when available;
  // it disambiguates "host unreachable" (TCP/network), "login_failed"
  // (RFC negotiated, credentials wrong), and "sdk_missing" (pyrfc /
  // SAP NW RFC SDK not loaded — typical on first Windows run).
  const klass = r.failure_class;
  if (klass === 'login_failed' || (!klass && r.host_reachable && !r.login_ok)) {
    return <span className="text-red-700 text-sm font-medium">✗ login failed (user or password)</span>;
  }
  if (klass === 'sdk_missing') {
    return <span className="text-amber-700 text-sm font-medium">⚠ SAP NW RFC SDK missing on this host</span>;
  }
  if (klass === 'bad_input') {
    return <span className="text-amber-700 text-sm font-medium">⚠ connection field empty or malformed</span>;
  }
  if (klass === 'host_unreachable') {
    return <span className="text-red-700 text-sm font-medium">✗ host unreachable</span>;
  }
  if (!r.host_reachable && klass === 'unknown') {
    // Generic fall-through — surface as "couldn't connect" rather than
    // pretending we know it's a network problem.
    return <span className="text-red-700 text-sm font-medium">✗ couldn't connect (see details)</span>;
  }
  if (!r.host_reachable) {
    return <span className="text-red-700 text-sm font-medium">✗ couldn't connect (see details)</span>;
  }
  if (r.missing_auths?.length) {
    return <span className="text-amber-700 text-sm font-medium">✗ {r.missing_auths.length} permission(s) missing</span>;
  }
  return <span className="text-red-700 text-sm font-medium">✗ failed</span>;
}

function TestDetails({ r }) {
  // Always show the raw error string if the connection itself failed,
  // even when no probes ran. That's the part you act on.
  const errorBlock = r.error ? (
    <div className="text-xs font-mono bg-red-50 border border-red-200 rounded p-2 text-red-800 mb-2 whitespace-pre-wrap">
      {r.error}
    </div>
  ) : null;
  if (!r.probes?.length) return errorBlock;
  return (
    <div className="mt-3 bg-white border border-slate-200 rounded p-3">
      {errorBlock}
      <div className="text-xs font-semibold mb-2">Probes</div>
      <ul className="text-xs space-y-1">
        {r.probes.map((p, i) => (
          <li key={i} className="flex items-start gap-2">
            <span className={p.ok ? 'text-emerald-600' : 'text-red-600'}>
              {p.ok ? '✓' : '✗'}
            </span>
            <div className="flex-1">
              <div>
                <span className="font-mono">{p.name}</span>{' '}
                <span className="text-slate-500">— {p.description}</span>
              </div>
              {!p.ok && (
                <div className="text-red-700 mt-0.5">
                  {p.error}
                  {p.fix_hint && <span className="text-slate-700"> · fix: {p.fix_hint}</span>}
                </div>
              )}
            </div>
          </li>
        ))}
      </ul>
      {r.missing_auths?.length > 0 && (
        <div className="mt-3 text-xs">
          <div className="font-semibold mb-1">PFCG fixes needed</div>
          <div className="font-mono text-amber-800 bg-amber-50 border border-amber-200 rounded p-2">
            Recommended role on target: <strong>{r.recommended_role}</strong>
          </div>
        </div>
      )}
    </div>
  );
}

const ECC_INSTRUCTIONS = (migration_type) => `1. Create a service user M4H_MIGRATOR on the ECC system.
2. Type: System (not Dialog).
3. Assign role Z_M4H_${(migration_type || 'full').toUpperCase()}:
   - S_RFC          FUGR=SYST, RFC1, SDTX, SDIFRUNTIME, ACTVT=16
   - S_TABU_DIS     DICBERCLS=&NC&, DDIC, FK, MM, FBU; ACTVT=03
   - S_BTCH_JOB     JOBACTION=PROT, JOBGROUP=M4H_*
   - S_DEVELOP      DEVCLASS=*, OBJTYPE=*, ACTVT=03 (read DDIC)
4. Confirm /SAP/BC/RFC/CONNECT works from any RFC client.
5. Make the ECC reachable from AWS (VPN, Direct Connect, or
   ngrok TCP for laptop ECC). Verify the IP + port pair you'll
   enter on the left is reachable from a test ping.`;

const S4_INSTRUCTIONS = (migration_type) => `1. Create a service user M4H_MIGRATOR on the S/4 target system.
2. Type: System (not Dialog).
3. Assign role Z_M4H_${(migration_type || 'full').toUpperCase()}:
   - S_RFC          all of the above + SBPT (for BAPI calls)
   - S_TABU_DIS     DICBERCLS=&NC&, FBU; ACTVT=03 (anchor discovery)
   - S_BTCH_JOB     JOBACTION=PROT, JOBGROUP=M4H_*
   - S_BTCH_NAM     JOBNAME=M4H_*  (spool capture + MC trigger)
   - S_TABU_NAM     TABLE=<scoped to your selective objects>
   - S_TCODE        XD03 FK03 MM03 (selective probes use BAPI getlist)
4. Activate the Migration Cockpit RFC layer (LTMC_API,
   /UI/MIG_OBJ_LOAD). If you cannot activate it, the tool's
   auto-degrade chain (BAPI substitute → IDoc inbound) carries
   the load — but a 100%-MC landscape needs this step.
5. Confirm BAPI_XBP_JOB_OPEN works from any RFC client. The
   pre-cutover spool capture (FAGLB03 + MB5B) depends on it.`;
