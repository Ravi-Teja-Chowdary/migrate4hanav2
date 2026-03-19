import { useParams, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  ArrowLeft, CheckCircle2, AlertTriangle, Code, Database, Settings,
  Shield, Plug, Search, PlayCircle, Upload, HardDrive, Wrench,
  UserCheck, Zap, ExternalLink, ClipboardCheck, ShieldCheck, ListChecks,
  ShieldAlert, DollarSign, TestTube2, Rocket,
} from 'lucide-react';
import { STAGES, SAMPLE_RUN } from '../data/sampleData';

const ICONS = {
  Search, Code, Database, Settings, Shield, Plug, PlayCircle, Upload, HardDrive, Wrench, UserCheck, Zap, CheckCircle2,
  ClipboardCheck, ShieldCheck, ListChecks, ShieldAlert, DollarSign, TestTube2, Rocket,
};

function DataRow({ label, value, color }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-white/[0.03] last:border-0">
      <span className="text-sm text-white/50">{label}</span>
      <span className="text-sm font-semibold" style={{ color: color || '#fff' }}>
        {typeof value === 'number' ? value.toLocaleString() : String(value)}
      </span>
    </div>
  );
}

function Section({ title, children, delay = 0 }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.4 }}
      className="glass rounded-2xl p-6"
    >
      <h3 className="text-sm font-semibold text-white/60 uppercase tracking-wider mb-4">{title}</h3>
      {children}
    </motion.div>
  );
}

// ========== Phase 1: Prepare ==========

function DiscoveryDetail({ data }) {
  const s = data.summary;
  return (
    <div className="space-y-6">
      <Section title="System Landscape" delay={0.1}>
        <DataRow label="Company Codes" value={s.company_codes} />
        <DataRow label="Plants" value={s.plants} />
        <DataRow label="Sales Organizations" value={s.sales_orgs} />
      </Section>
      <Section title="Custom Development" delay={0.15}>
        <DataRow label="Custom Programs" value={s.total_programs} />
        <DataRow label="Custom Tables" value={s.total_tables} />
        <DataRow label="Function Modules" value={s.total_function_modules} />
      </Section>
      <Section title="Users & Access" delay={0.2}>
        <DataRow label="PFCG Roles" value={s.total_roles} />
        <DataRow label="Total Users" value={s.total_users} />
      </Section>
      <Section title="Integrations" delay={0.25}>
        <DataRow label="RFC Destinations" value={s.rfc_destinations} />
        <DataRow label="IDoc Partners" value={s.idoc_partners} />
      </Section>
      <Section title="Readiness Issues" delay={0.3}>
        <DataRow label="Blocking Issues" value={s.blocking_issues} color={s.blocking_issues > 0 ? '#ef4444' : '#10b981'} />
        <DataRow label="Warnings" value={s.warnings} color={s.warnings > 0 ? '#f59e0b' : '#10b981'} />
      </Section>
    </div>
  );
}

function MaintenancePlannerDetail({ data }) {
  return (
    <div className="space-y-6">
      <Section title="Target Release" delay={0.1}>
        <DataRow label="Target Release" value={data.target_release} color="#3b82f6" />
        <DataRow label="Stack Components" value={data.stack_components} />
      </Section>
      <Section title="Add-on Compatibility" delay={0.15}>
        <DataRow label="Compatible" value={data.addon_compatibility.compatible} color="#10b981" />
        <DataRow label="Incompatible" value={data.addon_compatibility.incompatible} color={data.addon_compatibility.incompatible > 0 ? '#ef4444' : '#10b981'} />
        <DataRow label="Requires Upgrade" value={data.addon_compatibility.requires_upgrade} color={data.addon_compatibility.requires_upgrade > 0 ? '#f59e0b' : '#10b981'} />
      </Section>
      <Section title="Business Functions" delay={0.2}>
        <DataRow label="Active" value={data.business_functions.active} color="#10b981" />
        <DataRow label="Deprecated" value={data.business_functions.deprecated} color="#f59e0b" />
      </Section>
    </div>
  );
}

function ReadinessCheckDetail({ data }) {
  return (
    <div className="space-y-6">
      <Section title="Readiness Overview" delay={0.1}>
        <DataRow label="Data Collection" value={data.data_collection_status} color={data.data_collection_status === 'complete' ? '#10b981' : '#f59e0b'} />
        <DataRow label="Simplification Items (Relevant)" value={data.simplification_items_relevant} />
        <DataRow label="Fiori Readiness" value={data.fiori_readiness} color={data.fiori_readiness === 'full' ? '#10b981' : '#f59e0b'} />
      </Section>
      <Section title="Custom Code Impact" delay={0.15}>
        <DataRow label="High Impact" value={data.custom_code_impact.high} color="#ef4444" />
        <DataRow label="Medium Impact" value={data.custom_code_impact.medium} color="#f59e0b" />
        <DataRow label="Low Impact" value={data.custom_code_impact.low} color="#10b981" />
        <div className="mt-3 h-3 rounded-full bg-white/5 overflow-hidden flex">
          <div className="h-full bg-red-500" style={{ width: `${(data.custom_code_impact.high / (data.custom_code_impact.high + data.custom_code_impact.medium + data.custom_code_impact.low)) * 100}%` }} />
          <div className="h-full bg-amber-500" style={{ width: `${(data.custom_code_impact.medium / (data.custom_code_impact.high + data.custom_code_impact.medium + data.custom_code_impact.low)) * 100}%` }} />
          <div className="h-full bg-green-500" style={{ width: `${(data.custom_code_impact.low / (data.custom_code_impact.high + data.custom_code_impact.medium + data.custom_code_impact.low)) * 100}%` }} />
        </div>
      </Section>
      <Section title="Sizing & Effort" delay={0.2}>
        <DataRow label="HANA Sizing Recommendation" value={data.sizing_recommendation} color="#06b6d4" />
        <DataRow label="Estimated Effort" value={`${data.estimated_effort_days} days`} />
      </Section>
    </div>
  );
}

function SimplificationCheckDetail({ data }) {
  const isGo = data.conversion_readiness === 'GO';
  return (
    <div className="space-y-6">
      <Section title="Simplification Item Results" delay={0.1}>
        <DataRow label="Total Items Checked" value={data.total_items_checked} />
        <div className="grid grid-cols-3 gap-3 mt-4">
          <div className="p-3 rounded-xl bg-red-500/5 text-center border border-red-500/10">
            <p className="text-2xl font-bold text-red-400">{data.red_items}</p>
            <p className="text-[10px] text-red-400/60 mt-1 font-semibold">RED</p>
          </div>
          <div className="p-3 rounded-xl bg-amber-500/5 text-center border border-amber-500/10">
            <p className="text-2xl font-bold text-amber-400">{data.yellow_items}</p>
            <p className="text-[10px] text-amber-400/60 mt-1 font-semibold">YELLOW</p>
          </div>
          <div className="p-3 rounded-xl bg-green-500/5 text-center border border-green-500/10">
            <p className="text-2xl font-bold text-green-400">{data.green_items}</p>
            <p className="text-[10px] text-green-400/60 mt-1 font-semibold">GREEN</p>
          </div>
        </div>
      </Section>
      <Section title="Remediation & Prerequisites" delay={0.15}>
        <DataRow label="Remediation Tasks" value={data.remediation_tasks} color={data.remediation_tasks > 0 ? '#f59e0b' : '#10b981'} />
        <DataRow label="Prerequisite Notes Applied" value={data.prerequisite_notes_applied} color="#10b981" />
        <DataRow label="Prerequisite Notes Missing" value={data.prerequisite_notes_missing} color={data.prerequisite_notes_missing > 0 ? '#ef4444' : '#10b981'} />
      </Section>
      <Section title="Conversion Readiness" delay={0.2}>
        <div className="flex items-center justify-center py-6">
          <div
            className="px-8 py-4 rounded-2xl text-2xl font-bold"
            style={{
              backgroundColor: isGo ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
              color: isGo ? '#10b981' : '#ef4444',
              border: `2px solid ${isGo ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
            }}
          >
            {data.conversion_readiness}
          </div>
        </div>
      </Section>
    </div>
  );
}

// ========== Phase 2: Explore ==========

function CodeAnalysisDetail({ data }) {
  return (
    <Section title="Analysis Results" delay={0.1}>
      <DataRow label="Total Issues" value={data.total_issues} color="#f59e0b" />
      <DataRow label="Critical Issues" value={data.critical_issues} color="#ef4444" />
      <DataRow label="Auto-Remediated" value={data.auto_remediated} color="#10b981" />
      <DataRow label="Programs Fixed" value={data.programs_fixed} color="#10b981" />
      <DataRow label="Manual Review" value={data.manual_review} color="#f59e0b" />
      <div className="mt-4 p-3 rounded-xl bg-accent-green/5">
        <p className="text-xs text-accent-green">
          {data.fix_rate}% auto-fix rate — {data.total_fixes_applied} total fixes applied
        </p>
      </div>
      {data.fixes_by_level && (
        <div className="mt-4">
          <h4 className="text-xs font-semibold text-white/40 uppercase tracking-wider mb-2">Fix Engine Breakdown</h4>
          {Object.entries(data.fixes_by_level).map(([key, val]) => (
            <DataRow key={key} label={key.replace(/_/g, ' ')} value={val} />
          ))}
        </div>
      )}
    </Section>
  );
}

function CviPreparationDetail({ data }) {
  const r = data.results || {};
  return (
    <div className="space-y-6">
      <Section title="Business Partner Conversion" delay={0.1}>
        <DataRow label="Customers (KNA1)" value={r.customers || 0} />
        <DataRow label="Vendors (LFA1)" value={r.vendors || 0} />
        <DataRow label="Business Partners Created" value={r.bp_created || 0} color="#10b981" />
        <DataRow label="Duplicates Merged" value={r.duplicates_merged || 0} color="#f59e0b" />
        <DataRow label="CVI Synchronization" value={r.cvi_synchronization || 'N/A'} color="#10b981" />
      </Section>
    </div>
  );
}

function DataAssessmentDetail({ data }) {
  const r = data.results || {};
  return (
    <div className="space-y-6">
      <Section title="Finance Data" delay={0.1}>
        <DataRow label="Document Headers (BKPF)" value={r.finance_docs || 0} />
        <DataRow label="Line Items (BSEG -> ACDOCA)" value={r.finance_lines || 0} />
      </Section>
      <Section title="Business Partner Assessment" delay={0.15}>
        <DataRow label="Customers (KNA1)" value={r.customers || 0} />
        <DataRow label="Vendors (LFA1)" value={r.vendors || 0} />
        <DataRow label="Business Partners to Create" value={r.bp_created || 0} color="#10b981" />
        <DataRow label="Duplicates to Merge" value={r.duplicates_merged || 0} color="#f59e0b" />
      </Section>
      <Section title="Custom Tables" delay={0.2}>
        <DataRow label="Tables to Migrate" value={r.custom_tables || 0} />
        <DataRow label="Total Rows" value={r.custom_table_rows || 0} />
      </Section>
    </div>
  );
}

function ConfigAssessmentDetail({ data }) {
  return (
    <div className="space-y-6">
      <Section title="Configuration Assessment" delay={0.1}>
        <DataRow label="Checklist Items" value={data.checklist_items} />
        <div className="mt-3 space-y-2">
          {['Universal Journal ledgers', 'Business Partner setup', 'Fiori Launchpad', 'GST / E-Invoice config', 'TDS sections', 'Output Management', 'COPA in Universal Journal', 'Fiori spaces and pages', 'BP grouping for India'].map((item, i) => (
            <div key={i} className="flex items-center gap-2 text-xs text-white/40">
              <CheckCircle2 size={12} className="text-accent-green" />
              {item}
            </div>
          ))}
        </div>
      </Section>
      <Section title="Integration Assessment" delay={0.15}>
        <DataRow label="Total RFC Destinations" value={data.rfc_total} />
        <DataRow label="Auto-Migratable" value={data.automated} color="#10b981" />
        <DataRow label="Manual Review" value={data.manual} color="#f59e0b" />
        <div className="mt-3 h-2 rounded-full bg-white/5 overflow-hidden">
          <div
            className="h-full rounded-full bg-accent-green"
            style={{ width: `${(data.automated / data.rfc_total) * 100}%` }}
          />
        </div>
        <p className="text-[10px] text-white/25 mt-1">
          {Math.round((data.automated / data.rfc_total) * 100)}% automation rate
        </p>
      </Section>
    </div>
  );
}

// ========== Phase 3: Realize - Conversion ==========

function PreConversionGateDetail({ data }) {
  const isGo = data.go_no_go === 'GO';
  return (
    <Section title="Pre-Conversion Cutover Decision" delay={0.1}>
      <div className="flex items-center justify-center py-6">
        <div
          className="px-8 py-4 rounded-2xl text-2xl font-bold"
          style={{
            backgroundColor: isGo ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
            color: isGo ? '#10b981' : '#ef4444',
            border: `2px solid ${isGo ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
          }}
        >
          {data.go_no_go}
        </div>
      </div>
    </Section>
  );
}

function SumDmoDetail({ data }) {
  return (
    <div className="space-y-6">
      <Section title="SUM/DMO Orchestration" delay={0.1}>
        <DataRow label="SUM Version" value={data.sum_version} color="#3b82f6" />
        <DataRow label="Database Migrated To" value={data.database_migrated_to} color="#06b6d4" />
        <DataRow label="Downtime" value={`${data.downtime_hours} hours`} color="#f59e0b" />
        <DataRow label="Errors Encountered" value={data.errors_encountered} color={data.errors_encountered > 0 ? '#ef4444' : '#10b981'} />
      </Section>
      <Section title="Phase Progress" delay={0.15}>
        <div className="space-y-2">
          {Array.from({ length: data.total_phases }, (_, i) => (
            <div key={i} className="flex items-center gap-3 py-1.5">
              <CheckCircle2 size={14} className={i < data.phases_completed ? 'text-accent-green' : 'text-white/10'} />
              <span className={`text-xs ${i < data.phases_completed ? 'text-white/60' : 'text-white/20'}`}>
                SUM Phase {i + 1}
              </span>
              {i < data.phases_completed && (
                <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-accent-green/10 text-accent-green ml-auto font-medium">
                  COMPLETE
                </span>
              )}
            </div>
          ))}
        </div>
      </Section>
      <div className="p-4 rounded-xl bg-accent-blue/5 border border-accent-blue/10">
        <div className="flex items-start gap-2">
          <Shield size={14} className="text-accent-blue mt-0.5 shrink-0" />
          <div>
            <p className="text-xs font-semibold text-accent-blue">SAP-Supported Conversion</p>
            <p className="text-[11px] text-white/40 mt-1 leading-relaxed">
              Database migration performed by SAP SUM/DMO — SAP-supported conversion. Post-migration SAP support is retained.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ========== Phase 4: Realize - Post-Conversion ==========

function SpauSpddDetail({ data }) {
  const s = data.results?.summary || {};
  return (
    <div className="space-y-6">
      <Section title="SPAU/SPDD Objects" delay={0.1}>
        <DataRow label="SPAU Objects" value={data.spau_objects} />
        <DataRow label="SPDD Objects" value={data.spdd_objects} />
        <DataRow label="Auto-Adjusted" value={data.auto_adjusted} color="#10b981" />
        <DataRow label="Manual Required" value={data.manual_required} color={data.manual_required > 0 ? '#f59e0b' : '#10b981'} />
        <DataRow label="Transport Deployed" value={data.transport_deployed ? 'Yes' : 'No'} color={data.transport_deployed ? '#10b981' : '#ef4444'} />
      </Section>
      <Section title="Code Deployment" delay={0.15}>
        <DataRow label="Transport Request" value={s.transport_id || 'N/A'} color="#06b6d4" />
        <DataRow label="Programs Deployed" value={s.deployed || 0} color="#10b981" />
        <DataRow label="Programs Activated" value={s.activated || 0} color="#10b981" />
      </Section>
    </div>
  );
}

function FinanceMigrationDetail({ data }) {
  return (
    <div className="space-y-6">
      <Section title="FINS Monitor Status" delay={0.1}>
        <DataRow label="FINS Monitor" value={data.fins_monitor_status} color={data.fins_monitor_status === 'complete' ? '#10b981' : '#f59e0b'} />
        <DataRow label="Documents Migrated" value={data.documents_migrated} color="#10b981" />
        <DataRow label="Material Ledger Active" value={data.material_ledger_active ? 'Yes' : 'No'} color={data.material_ledger_active ? '#10b981' : '#ef4444'} />
      </Section>
      <Section title="Table Conversions" delay={0.15}>
        <div className="space-y-2">
          {(data.tables_converted || []).map((t, i) => (
            <div key={i} className="flex items-center gap-2 text-xs text-white/50">
              <CheckCircle2 size={12} className="text-accent-green" />
              <span className="font-mono">{t}</span>
            </div>
          ))}
        </div>
      </Section>
      <Section title="Reconciliation" delay={0.2}>
        <div className="flex items-center justify-between py-4">
          <span className="text-sm text-white/50">Reconciliation Variance</span>
          <span
            className="text-2xl font-bold font-mono"
            style={{ color: data.reconciliation_variance === '0.00' ? '#10b981' : '#ef4444' }}
          >
            {data.reconciliation_variance}
          </span>
        </div>
        {data.reconciliation_variance === '0.00' && (
          <div className="p-3 rounded-xl bg-accent-green/5 border border-accent-green/10">
            <p className="text-xs text-accent-green flex items-center gap-2">
              <CheckCircle2 size={12} /> Perfect reconciliation — zero variance
            </p>
          </div>
        )}
      </Section>
    </div>
  );
}

function MaterialLedgerConfigDetail({ data }) {
  const s = data.results?.summary || {};
  return (
    <div className="space-y-6">
      <Section title="Material Ledger" delay={0.1}>
        <DataRow label="Material Ledger Active" value={data.material_ledger_active ? 'Yes' : 'No'} color={data.material_ledger_active ? '#10b981' : '#ef4444'} />
        <DataRow label="Valuation Areas" value={data.valuation_areas} />
        <DataRow label="Config Items Applied" value={data.config_items_applied} color="#10b981" />
        <DataRow label="Number Ranges Created" value={data.number_ranges_created} />
      </Section>
      <Section title="Configuration Applied" delay={0.15}>
        <DataRow label="Number Ranges" value={s.number_ranges || 0} />
        <DataRow label="Universal Journal Ledgers" value={s.ledgers || 0} />
        <DataRow label="BP Groups" value={s.bp_groups || 0} />
        <DataRow label="GST Registrations" value={s.gst_registrations || 0} />
        <DataRow label="TDS Configured" value={s.tds_configured ? 'Yes' : 'No'} color={s.tds_configured ? '#10b981' : '#ef4444'} />
        <DataRow label="E-Invoice Configured" value={s.einvoice_configured ? 'Yes' : 'No'} color={s.einvoice_configured ? '#10b981' : '#ef4444'} />
        <DataRow label="Fiori Catalogs" value={s.fiori_catalogs || 0} />
      </Section>
    </div>
  );
}

function RoleIntegrationDetail({ data }) {
  const s = data.results?.summary || {};
  return (
    <div className="space-y-6">
      <Section title="Role Provisioning" delay={0.1}>
        <DataRow label="Total Roles" value={data.total_roles} />
        <DataRow label="Fiori Apps Mapped" value={data.fiori_mapped} color="#06b6d4" />
        <DataRow label="Single Roles Created" value={s.single_roles_created || 0} />
        <DataRow label="Composite Roles Created" value={s.composite_roles_created || 0} />
        <DataRow label="Users Assigned" value={s.users_assigned || 0} color="#10b981" />
      </Section>
      <Section title="Integration Activation" delay={0.15}>
        <DataRow label="RFC Destinations Created" value={s.rfc_destinations_created || 0} />
        <DataRow label="IDoc Partners Created" value={s.idoc_partners_created || 0} />
        <DataRow label="India Endpoints Created" value={s.india_endpoints_created || 0} color="#f59e0b" />
      </Section>
    </div>
  );
}

// ========== Phase 5: Deploy & Run ==========

function BusinessProcessTestDetail({ data }) {
  return (
    <div className="space-y-6">
      <Section title="Test Results" delay={0.1}>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
          <div className="p-3 rounded-xl bg-white/[0.02] text-center">
            <p className="text-2xl font-bold text-white">{data.test_scenarios}</p>
            <p className="text-[10px] text-white/30 mt-1">Total Scenarios</p>
          </div>
          <div className="p-3 rounded-xl bg-accent-green/5 text-center">
            <p className="text-2xl font-bold text-accent-green">{data.passed}</p>
            <p className="text-[10px] text-accent-green/60 mt-1">Passed</p>
          </div>
          <div className="p-3 rounded-xl bg-accent-red/5 text-center">
            <p className="text-2xl font-bold text-accent-red">{data.failed}</p>
            <p className="text-[10px] text-accent-red/60 mt-1">Failed</p>
          </div>
          <div className="p-3 rounded-xl bg-accent-amber/5 text-center">
            <p className="text-2xl font-bold text-accent-amber">{data.skipped}</p>
            <p className="text-[10px] text-accent-amber/60 mt-1">Skipped</p>
          </div>
        </div>
      </Section>
      <Section title="Validated Business Processes" delay={0.15}>
        <div className="space-y-2">
          {(data.processes_validated || []).map((p, i) => (
            <div key={i} className="flex items-center gap-2 text-xs text-white/50">
              <CheckCircle2 size={12} className="text-accent-green" />
              <span className="font-medium">{p}</span>
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}

function GoliveCutoverDetail({ data }) {
  return (
    <div className="space-y-6">
      <Section title="Cutover Execution" delay={0.1}>
        <DataRow label="Users Locked" value={data.users_locked} />
        <DataRow label="Delta Backup Complete" value={data.delta_backup_complete ? 'Yes' : 'No'} color={data.delta_backup_complete ? '#10b981' : '#ef4444'} />
        <DataRow label="Final Cutover Duration" value={`${data.final_cutover_duration_minutes} minutes`} />
        <DataRow label="Users Unlocked" value={data.users_unlocked} color="#10b981" />
      </Section>
      <Section title="Go-Live Status" delay={0.15}>
        <div className="flex items-center justify-center py-8">
          <motion.div
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ type: 'spring', stiffness: 200, delay: 0.3 }}
            className="px-10 py-6 rounded-2xl text-center"
            style={{
              backgroundColor: 'rgba(16, 185, 129, 0.1)',
              border: '2px solid rgba(16, 185, 129, 0.3)',
            }}
          >
            <p className="text-3xl font-bold text-accent-green">{data.cutover_status}</p>
            <p className="text-xs text-accent-green/60 mt-2">All systems operational</p>
          </motion.div>
        </div>
      </Section>
    </div>
  );
}

function ValidationScorecardDetail({ data }) {
  const sc = data.scorecard;
  return (
    <div className="space-y-6">
      <Section title="Scorecard" delay={0.1}>
        <DataRow label="Grade" value={sc.grade} color={sc.grade === 'A' ? '#10b981' : '#f59e0b'} />
        <DataRow label="Score" value={sc.score} color="#10b981" />
        <DataRow label="Total Checks" value={sc.total_checks} />
        <DataRow label="Passed" value={sc.total_passed} color="#10b981" />
        <DataRow label="Failed" value={sc.total_failed} color={sc.total_failed > 0 ? '#ef4444' : '#10b981'} />
        <DataRow label="Recommendation" value={sc.recommendation} color="#10b981" />
      </Section>
      {sc.checks && (
        <Section title="Check Breakdown" delay={0.15}>
          {Object.entries(sc.checks).map(([key, val]) => (
            <DataRow key={key} label={key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())} value={`${val.passed}/${val.checked}`} color={val.passed === val.checked ? '#10b981' : '#f59e0b'} />
          ))}
        </Section>
      )}
    </div>
  );
}

const DETAIL_RENDERERS = {
  // Phase 1: Prepare
  discovery: DiscoveryDetail,
  maintenance_planner: MaintenancePlannerDetail,
  readiness_check: ReadinessCheckDetail,
  simplification_check: SimplificationCheckDetail,
  // Phase 2: Explore
  code_analysis: CodeAnalysisDetail,
  cvi_preparation: CviPreparationDetail,
  data_assessment: DataAssessmentDetail,
  config_assessment: ConfigAssessmentDetail,
  // Phase 3: Realize - Conversion
  pre_conversion_gate: PreConversionGateDetail,
  sum_dmo: SumDmoDetail,
  // Phase 4: Realize - Post-Conversion
  spau_spdd: SpauSpddDetail,
  finance_migration: FinanceMigrationDetail,
  material_ledger_config: MaterialLedgerConfigDetail,
  role_integration: RoleIntegrationDetail,
  // Phase 5: Deploy & Run
  business_process_test: BusinessProcessTestDetail,
  golive_cutover: GoliveCutoverDetail,
  validation_scorecard: ValidationScorecardDetail,
};

export default function StageDetail() {
  const { stageKey } = useParams();
  const navigate = useNavigate();

  const stage = STAGES.find((s) => s.key === stageKey);
  const data = SAMPLE_RUN.results[stageKey];
  const Renderer = DETAIL_RENDERERS[stageKey];
  const Icon = ICONS[stage?.icon] || Zap;

  if (!stage || !data) {
    return (
      <div className="p-8 text-center text-white/40">
        <p>Stage not found.</p>
        <button onClick={() => navigate('/')} className="mt-4 text-accent-blue hover:underline text-sm">
          Back to Dashboard
        </button>
      </div>
    );
  }

  return (
    <div className="p-8 max-w-3xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button
          onClick={() => navigate('/')}
          className="w-9 h-9 rounded-xl glass flex items-center justify-center text-white/40 hover:text-white/70 transition-colors"
        >
          <ArrowLeft size={16} />
        </button>
        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center"
            style={{ backgroundColor: `${stage.color}15` }}
          >
            <Icon size={20} style={{ color: stage.color }} />
          </div>
          <div>
            <motion.h1
              initial={{ opacity: 0, x: -16 }}
              animate={{ opacity: 1, x: 0 }}
              className="text-2xl font-bold text-white"
            >
              Stage {stage.id}: {stage.name}
            </motion.h1>
            <p className="text-xs text-white/30 uppercase tracking-wider">{stage.phase} · Phase {stage.phaseNumber}</p>
          </div>
        </div>
      </div>

      {/* Status badge */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="flex items-center gap-2"
      >
        <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-accent-green/10 text-accent-green text-xs font-medium">
          <CheckCircle2 size={12} />
          {data.status === 'success' ? 'Completed Successfully' : data.status}
        </div>
      </motion.div>

      {/* Detail content */}
      {Renderer ? <Renderer data={data} /> : (
        <Section title="Raw Data">
          <pre className="text-xs font-mono text-white/40 whitespace-pre-wrap">
            {JSON.stringify(data, null, 2)}
          </pre>
        </Section>
      )}
    </div>
  );
}
