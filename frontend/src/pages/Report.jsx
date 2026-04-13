import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import {
  ArrowLeft, FileText, Building2, Code, Database, Settings,
  Shield, Plug, CheckCircle2, AlertTriangle, XCircle, TrendingUp,
  Calendar, Clock, Zap, Download, ShieldCheck,
} from 'lucide-react';
import { SAMPLE_RUN, PHASES } from '../data/sampleData';
import { apiFetch } from '../api';

function Section({ title, icon: Icon, children, delay = 0, accent = '#3b82f6' }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.4 }}
      className="glass rounded-2xl overflow-hidden"
    >
      <div className="px-6 py-4 border-b border-white/[0.04] flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ backgroundColor: `${accent}15` }}>
          <Icon size={16} style={{ color: accent }} />
        </div>
        <h3 className="text-sm font-semibold text-white/80 uppercase tracking-wider">{title}</h3>
      </div>
      <div className="p-6">{children}</div>
    </motion.div>
  );
}

function Row({ label, value, color, mono }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-white/[0.02] last:border-0">
      <span className="text-sm text-white/50">{label}</span>
      <span className={`text-sm font-semibold ${mono ? 'font-mono' : ''}`} style={{ color: color || '#fff' }}>
        {typeof value === 'number' ? value.toLocaleString() : String(value)}
      </span>
    </div>
  );
}

function RiskBadge({ severity }) {
  const colors = { HIGH: '#ef4444', MEDIUM: '#f59e0b', LOW: '#10b981' };
  const c = colors[severity] || '#fff';
  return (
    <span className="text-[10px] px-2 py-0.5 rounded-full font-semibold" style={{ backgroundColor: `${c}15`, color: c }}>
      {severity}
    </span>
  );
}

const PHASE_COLORS_MAP = {
  blue: '#3b82f6',
  purple: '#8b5cf6',
  amber: '#f59e0b',
  cyan: '#06b6d4',
  green: '#10b981',
};

export default function Report() {
  const navigate = useNavigate();
  const r = SAMPLE_RUN.post_migration_report;
  const [latestRunDate, setLatestRunDate] = useState(null);
  const [hasRun, setHasRun] = useState(false);

  useEffect(() => {
    apiFetch('/api/runs')
      .then((res) => res.ok ? res.json() : Promise.reject(res.statusText))
      .then((runs) => {
        if (runs.length > 0) {
          setHasRun(true);
          // run id format: run_YYYYMMDD_HHMMSS
          const ts = runs[0].timestamp;
          if (ts) {
            const date = `${ts.slice(0, 4)}-${ts.slice(4, 6)}-${ts.slice(6, 8)}`;
            setLatestRunDate(date);
          }
        }
      })
      .catch(() => {});
  }, []);

  if (!r) {
    return (
      <div className="p-8 text-center text-white/40">
        <p>No post-migration report available yet. Run the pipeline first.</p>
        <button onClick={() => navigate('/')} className="mt-4 text-accent-blue hover:underline text-sm">Back to Dashboard</button>
      </div>
    );
  }

  const es = r.executive_summary;
  const cr = r.code_remediation;
  const dm = r.data_migration;
  const cfg = r.configuration;
  const ra = r.roles_and_authorizations;
  const integ = r.integrations;
  const gls = r.go_live_scorecard;
  const risk = r.risk_assessment;
  const roadmap = r.post_golive_roadmap;
  const tm = r.technical_metrics;
  const sapCompliance = r.sap_compliance;

  const gradeColor = { A: '#10b981', B: '#f59e0b', C: '#f97316', D: '#ef4444' }[gls.grade] || '#3b82f6';

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button
          onClick={() => navigate('/')}
          className="w-9 h-9 rounded-xl glass flex items-center justify-center text-white/40 hover:text-white/70 transition-colors"
        >
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <motion.h1 initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} className="text-2xl font-bold text-white">
            Post-Migration <span className="gradient-text">Report</span>
          </motion.h1>
          <p className="text-xs text-white/30 mt-0.5">{r.report_metadata.classification}</p>
        </div>
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.2 }}
          className="flex items-center gap-3">
          <span className="text-[11px] text-white/30 font-mono flex items-center gap-1">
            <Calendar size={12} /> {latestRunDate || r.report_metadata.generated?.split('T')[0]}
          </span>
          <button
            onClick={async () => {
              if (!hasRun) {
                alert('No pipeline run found. Please run the migration pipeline first to generate a report.');
                return;
              }
              try {
                const res = await apiFetch('/api/runs/latest/pdf');
                if (res.status === 404) {
                  alert('No pipeline run found. Please run the migration pipeline first to generate a report.');
                  return;
                }
                if (!res.ok) {
                  const err = await res.json().catch(() => ({}));
                  alert(err.error || 'Failed to download PDF');
                  return;
                }
                const blob = await res.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'migration-report.pdf';
                document.body.appendChild(a);
                a.click();
                a.remove();
                URL.revokeObjectURL(url);
              } catch (e) {
                console.error('PDF download error:', e);
                alert('PDF download failed — is the API server running?');
              }
            }}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-accent-blue/10 text-accent-blue text-xs font-semibold
                       hover:bg-accent-blue/20 transition-all border border-accent-blue/20"
          >
            <Download size={14} /> Download PDF
          </button>
        </motion.div>
      </div>

      {/* Executive Summary Banner */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="glass rounded-2xl p-6 relative overflow-hidden"
      >
        <div className="absolute inset-0 bg-gradient-to-r from-accent-blue/5 via-transparent to-accent-green/5" />
        <div className="relative">
          <div className="flex items-center gap-2 mb-4">
            <Building2 size={16} className="text-accent-blue" />
            <h2 className="text-lg font-bold text-white">{es.client}</h2>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <p className="text-[10px] text-white/30 uppercase">Source</p>
              <p className="text-sm text-white/70 font-medium">{es.source_system}</p>
            </div>
            <div>
              <p className="text-[10px] text-white/30 uppercase">Target</p>
              <p className="text-sm text-white/70 font-medium">{es.target_system}</p>
            </div>
            <div>
              <p className="text-[10px] text-white/30 uppercase">Approach</p>
              <p className="text-sm text-white/70 font-medium">{es.migration_approach}</p>
            </div>
            <div>
              <p className="text-[10px] text-white/30 uppercase">GO-LIVE</p>
              <p className="text-2xl font-bold" style={{ color: gradeColor }}>
                {gls.grade} <span className="text-sm font-normal">({gls.score})</span>
              </p>
            </div>
          </div>
          <div className="mt-4 flex items-center gap-3">
            <span className="text-xs px-3 py-1 rounded-full font-semibold" style={{ backgroundColor: `${gradeColor}15`, color: gradeColor }}>
              {es.recommendation}
            </span>
            <span className="text-xs text-white/30 font-mono">{es.overall_status}</span>
          </div>
        </div>
      </motion.div>

      {/* SAP Compliance & Methodology Section */}
      <Section title="SAP Compliance & Methodology" icon={ShieldCheck} delay={0.12} accent="#3b82f6">
        {/* Phase alignment table */}
        <h4 className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-3">Phase Alignment — SAP Activate Methodology</h4>
        <div className="space-y-2 mb-6">
          {PHASES.map((phase) => {
            const phaseColor = PHASE_COLORS_MAP[phase.color] || '#3b82f6';
            return (
              <div key={phase.id} className="flex items-center gap-3 py-2 px-3 rounded-xl bg-white/[0.02]">
                <div className="w-6 h-6 rounded-md flex items-center justify-center text-[10px] font-bold"
                  style={{ backgroundColor: `${phaseColor}15`, color: phaseColor }}>
                  {phase.id}
                </div>
                <div className="flex-1">
                  <span className="text-xs text-white/60 font-medium">{phase.name}</span>
                  <span className="text-[10px] text-white/25 ml-2">{phase.subtitle}</span>
                </div>
                <div className="flex items-center gap-1.5 text-[10px] text-accent-green font-medium">
                  <CheckCircle2 size={12} className="text-accent-green" />
                  Complete
                </div>
              </div>
            );
          })}
        </div>

        {/* SAP Tool compliance checklist */}
        <h4 className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-3">SAP Tool Compliance</h4>
        <div className="space-y-2 mb-5">
          {(sapCompliance?.items || []).map((item, i) => (
            <div key={i} className="flex items-start gap-2 text-xs text-white/50">
              <CheckCircle2 size={13} className="text-accent-green mt-0.5 shrink-0" />
              <div>
                <span className="font-semibold text-white/60">{item.tool}</span>
                <span className="text-white/30"> — {item.detail}</span>
              </div>
            </div>
          ))}
        </div>

        {/* Statement */}
        <div className="p-4 rounded-xl bg-accent-blue/5 border border-accent-blue/10">
          <div className="flex items-start gap-2">
            <Shield size={14} className="text-accent-blue mt-0.5 shrink-0" />
            <p className="text-xs text-white/50 leading-relaxed">
              {sapCompliance?.statement || 'This migration was executed using SAP-approved tools and methodology. Post-migration SAP support is retained.'}
            </p>
          </div>
        </div>
      </Section>

      {/* Code Remediation - the star of the show */}
      <Section title="Code Remediation" icon={Code} delay={0.15} accent="#06b6d4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
          <div className="p-3 rounded-xl bg-white/[0.02] text-center">
            <p className="text-2xl font-bold text-white">{cr.summary.total_issues_detected}</p>
            <p className="text-[10px] text-white/30 mt-1">Issues Detected</p>
          </div>
          <div className="p-3 rounded-xl bg-accent-green/5 text-center">
            <p className="text-2xl font-bold text-accent-green">{cr.summary.auto_remediated}</p>
            <p className="text-[10px] text-accent-green/60 mt-1">Auto-Fixed</p>
          </div>
          <div className="p-3 rounded-xl bg-accent-cyan/5 text-center">
            <p className="text-2xl font-bold text-accent-cyan">{cr.summary.total_fixes_applied}</p>
            <p className="text-[10px] text-accent-cyan/60 mt-1">Fixes Applied</p>
          </div>
          <div className="p-3 rounded-xl bg-accent-blue/5 text-center">
            <p className="text-2xl font-bold text-accent-blue">{cr.summary.fix_rate_percentage}%</p>
            <p className="text-[10px] text-accent-blue/60 mt-1">Fix Rate</p>
          </div>
        </div>

        {/* Fix Rate Bar */}
        <div className="mb-5">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-white/40">Auto-Fix Coverage</span>
            <span className="text-xs font-mono text-white/40">{cr.summary.fix_rate_percentage}%</span>
          </div>
          <div className="h-3 rounded-full bg-white/5 overflow-hidden">
            <motion.div
              className="h-full rounded-full bg-gradient-to-r from-accent-blue to-accent-green"
              initial={{ width: 0 }}
              animate={{ width: `${cr.summary.fix_rate_percentage}%` }}
              transition={{ duration: 1.2, delay: 0.5, ease: [0.4, 0, 0.2, 1] }}
            />
          </div>
        </div>

        <h4 className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-3">Fix Engine Breakdown</h4>
        <div className="space-y-2 mb-5">
          {Object.entries(cr.fix_breakdown).map(([key, val]) => (
            <div key={key} className="flex items-center justify-between py-1.5 text-xs">
              <span className="text-white/40">{key.replace(/_/g, ' ')}</span>
              <span className="text-white/60 font-mono text-[11px]">{val}</span>
            </div>
          ))}
        </div>

        <h4 className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-3">Key Transformations</h4>
        <div className="space-y-1.5">
          {cr.key_transformations.map((t, i) => (
            <div key={i} className="flex items-start gap-2 text-xs text-white/40">
              <CheckCircle2 size={12} className="text-accent-green mt-0.5 shrink-0" />
              <span>{t}</span>
            </div>
          ))}
        </div>

        {cr.remaining_manual_review > 0 && (
          <div className="mt-5 p-3 rounded-xl bg-accent-amber/5 border border-accent-amber/10">
            <div className="flex items-center gap-2 mb-2">
              <AlertTriangle size={14} className="text-accent-amber" />
              <span className="text-xs font-semibold text-accent-amber">{cr.summary.remaining_manual_review} Items Need Manual Review</span>
            </div>
            <div className="space-y-1">
              {cr.manual_review_items.map((item, i) => (
                <p key={i} className="text-[11px] text-white/30 pl-5">• {item}</p>
              ))}
            </div>
          </div>
        )}
      </Section>

      {/* Data Migration */}
      <Section title="Data Migration" icon={Database} delay={0.2} accent="#10b981">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <h4 className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-3">Financial Data</h4>
            <Row label="Source Documents (BKPF)" value={dm.finance.source_documents_bkpf} />
            <Row label="Source Line Items (BSEG)" value={dm.finance.source_line_items_bseg} />
            <Row label="Target ACDOCA Records" value={dm.finance.target_acdoca_records} color="#10b981" />
            <Row label="Reconciliation" value={dm.finance.reconciliation} color={dm.finance.reconciliation === 'PASSED' ? '#10b981' : '#f59e0b'} />
          </div>
          <div>
            <h4 className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-3">Business Partner Conversion</h4>
            <Row label="Customers Migrated" value={dm.business_partner_conversion.customers_migrated} />
            <Row label="Vendors Migrated" value={dm.business_partner_conversion.vendors_migrated} />
            <Row label="BPs Created (BUT000)" value={dm.business_partner_conversion.business_partners_created} color="#10b981" />
            <Row label="Duplicates Merged" value={dm.business_partner_conversion.duplicates_merged} color="#f59e0b" />
            <Row label="CVI Sync" value={dm.business_partner_conversion.cvi_synchronization} color="#10b981" />
          </div>
        </div>
      </Section>

      {/* Config + Roles side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Section title="Configuration" icon={Settings} delay={0.25} accent="#f59e0b">
          <Row label="Checklist Items Applied" value={cfg.checklist_items_applied} />
          <Row label="Journal Ledgers" value={cfg.s4_specific_config.universal_journal_ledgers} />
          <Row label="Number Ranges" value={cfg.s4_specific_config.number_ranges_created} />
          <Row label="Fiori Catalogs" value={cfg.s4_specific_config.fiori_catalogs_registered} />
          <div className="mt-4 pt-3 border-t border-white/[0.04]">
            <h4 className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-2">India Localization</h4>
            <Row label="GST Registrations" value={cfg.india_localization.gst_registrations} />
            <Row label="TDS Configured" value={cfg.india_localization.tds_configured ? 'Yes' : 'No'} color={cfg.india_localization.tds_configured ? '#10b981' : '#ef4444'} />
            <Row label="E-Invoice" value={cfg.india_localization.einvoice_configured ? 'Yes' : 'No'} color={cfg.india_localization.einvoice_configured ? '#10b981' : '#ef4444'} />
          </div>
        </Section>

        <Section title="Roles & Authorizations" icon={Shield} delay={0.3} accent="#8b5cf6">
          <Row label="Source PFCG Roles" value={ra.source_roles} />
          <Row label="Fiori Apps Mapped" value={ra.fiori_apps_mapped} color="#06b6d4" />
          <Row label="Single Roles Created" value={ra.single_roles_created} />
          <Row label="Composite Roles Created" value={ra.composite_roles_created} />
          <Row label="Users Assigned" value={ra.users_assigned} color="#10b981" />
          <div className="mt-4 pt-3 border-t border-white/[0.04]">
            <h4 className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-2">Key T-code to Fiori Mappings</h4>
            <div className="space-y-1">
              {ra.key_mappings.slice(0, 4).map((m, i) => (
                <p key={i} className="text-[11px] text-white/30">{m}</p>
              ))}
            </div>
          </div>
        </Section>
      </div>

      {/* Integrations */}
      <Section title="Integrations" icon={Plug} delay={0.35} accent="#ef4444">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
          <div className="text-center">
            <p className="text-xl font-bold text-white">{integ.rfc_destinations_total}</p>
            <p className="text-[10px] text-white/30">RFC Total</p>
          </div>
          <div className="text-center">
            <p className="text-xl font-bold text-accent-green">{integ.auto_migrated}</p>
            <p className="text-[10px] text-accent-green/60">Auto-Migrated</p>
          </div>
          <div className="text-center">
            <p className="text-xl font-bold text-accent-amber">{integ.manual_review_needed}</p>
            <p className="text-[10px] text-accent-amber/60">Manual Review</p>
          </div>
          <div className="text-center">
            <p className="text-xl font-bold text-accent-blue">{integ.automation_rate}</p>
            <p className="text-[10px] text-accent-blue/60">Automation Rate</p>
          </div>
        </div>
        <h4 className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-2">Critical India Integrations</h4>
        <div className="space-y-1.5">
          {integ.critical_integrations.map((ci, i) => (
            <div key={i} className="flex items-center gap-2 text-xs text-white/40">
              <Zap size={11} className="text-accent-amber" />
              {ci}
            </div>
          ))}
        </div>
      </Section>

      {/* Risk Assessment */}
      <Section title="Risk Assessment" icon={AlertTriangle} delay={0.4} accent="#f59e0b">
        <div className="flex items-center gap-2 mb-4">
          <span className="text-sm text-white/50">Overall Risk:</span>
          <RiskBadge severity={risk.overall_risk} />
        </div>
        <div className="space-y-3 mb-5">
          {risk.risks.map((r, i) => (
            <div key={i} className="p-3 rounded-xl bg-white/[0.02]">
              <div className="flex items-center gap-2 mb-1">
                <RiskBadge severity={r.severity} />
                <span className="text-xs font-semibold text-white/60">{r.area}</span>
              </div>
              <p className="text-xs text-white/40 mb-1">{r.description}</p>
              <p className="text-[10px] text-accent-blue/60">Mitigation: {r.mitigation}</p>
            </div>
          ))}
        </div>
        <h4 className="text-xs font-semibold text-white/50 uppercase tracking-wider mb-3">Recommendations</h4>
        <div className="space-y-1.5">
          {risk.recommendations.map((rec, i) => (
            <div key={i} className="flex items-start gap-2 text-xs text-white/40">
              <TrendingUp size={12} className="text-accent-blue mt-0.5 shrink-0" />
              <span>{rec}</span>
            </div>
          ))}
        </div>
      </Section>

      {/* Post Go-Live Roadmap */}
      <Section title="Post Go-Live Roadmap" icon={Calendar} delay={0.45} accent="#8b5cf6">
        <div className="space-y-6">
          {roadmap.map((phase, pi) => (
            <div key={pi}>
              <h4 className="text-sm font-semibold text-white/70 mb-3 flex items-center gap-2">
                <div className="w-6 h-6 rounded-md bg-accent-purple/10 text-accent-purple flex items-center justify-center text-[10px] font-bold">
                  {pi + 1}
                </div>
                {phase.phase}
              </h4>
              <div className="space-y-1.5 pl-8">
                {phase.activities.map((act, ai) => (
                  <p key={ai} className="text-xs text-white/40">• {act}</p>
                ))}
              </div>
            </div>
          ))}
        </div>
      </Section>

      {/* Technical Metrics Footer */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.5 }}
        className="glass rounded-2xl p-4"
      >
        <div className="flex items-center justify-center gap-8 text-[11px] text-white/20 font-mono">
          <span>{tm.rfc_calls_executed?.toLocaleString()} RFC calls</span>
          <span>•</span>
          <span>{tm.pipeline_duration_seconds}s runtime</span>
          <span>•</span>
          <span>{tm.programs_deployed} programs deployed</span>
          <span>•</span>
          <span>Transport: {tm.transport_request}</span>
        </div>
      </motion.div>
    </div>
  );
}
