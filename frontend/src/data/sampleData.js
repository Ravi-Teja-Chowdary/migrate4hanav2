// Sample pipeline data matching the SAP Activate Methodology 5-phase structure

export const PHASES = [
  { id: 1, name: "Prepare", subtitle: "Assessment & Pre-Checks", color: "blue", icon: "Search", stageIds: [1, 2, 3, 4] },
  { id: 2, name: "Explore", subtitle: "Application Preparation", color: "purple", icon: "Code", stageIds: [5, 6, 7, 8] },
  { id: 3, name: "Realize - Conversion", subtitle: "Technical System Conversion", color: "amber", icon: "Database", stageIds: [9, 10] },
  { id: 4, name: "Realize - Post-Conversion", subtitle: "Post-Conversion Migration", color: "cyan", icon: "Settings", stageIds: [11, 12, 13, 14] },
  { id: 5, name: "Deploy & Run", subtitle: "Testing & Go-Live", color: "green", icon: "Rocket", stageIds: [15, 16, 17] },
];

export const PHASE_COLORS = {
  blue: '#3b82f6',
  purple: '#8b5cf6',
  amber: '#f59e0b',
  cyan: '#06b6d4',
  green: '#10b981',
};

export const STAGES = [
  // Phase 1: Prepare (Assessment & Pre-Checks)
  { id: 1,  key: 'discovery',             name: 'System Discovery & Landscape Analysis',    phase: 'Prepare',                    phaseNumber: 1, color: '#3b82f6', icon: 'Search' },
  { id: 2,  key: 'maintenance_planner',    name: 'Maintenance Planner Validation',           phase: 'Prepare',                    phaseNumber: 1, color: '#3b82f6', icon: 'ClipboardCheck' },
  { id: 3,  key: 'readiness_check',        name: 'SAP Readiness Check',                      phase: 'Prepare',                    phaseNumber: 1, color: '#3b82f6', icon: 'ShieldCheck' },
  { id: 4,  key: 'simplification_check',   name: 'Simplification Item Check',                phase: 'Prepare',                    phaseNumber: 1, color: '#3b82f6', icon: 'ListChecks' },

  // Phase 2: Explore (Application Preparation)
  { id: 5,  key: 'code_analysis',          name: 'Custom Code Analysis & ATC Remediation',   phase: 'Explore',                    phaseNumber: 2, color: '#8b5cf6', icon: 'Code' },
  { id: 6,  key: 'cvi_preparation',        name: 'CVI & Business Partner Preparation',       phase: 'Explore',                    phaseNumber: 2, color: '#8b5cf6', icon: 'UserCheck' },
  { id: 7,  key: 'data_assessment',        name: 'Master Data Assessment & Cleansing',       phase: 'Explore',                    phaseNumber: 2, color: '#8b5cf6', icon: 'Database' },
  { id: 8,  key: 'config_assessment',      name: 'Configuration & Integration Assessment',   phase: 'Explore',                    phaseNumber: 2, color: '#8b5cf6', icon: 'Settings' },

  // Phase 3: Realize - Conversion
  { id: 9,  key: 'pre_conversion_gate',    name: 'Pre-Conversion Cutover Gate',              phase: 'Realize - Conversion',       phaseNumber: 3, color: '#f59e0b', icon: 'ShieldAlert' },
  { id: 10, key: 'sum_dmo',                name: 'SUM/DMO Orchestration & Monitoring',       phase: 'Realize - Conversion',       phaseNumber: 3, color: '#f59e0b', icon: 'HardDrive' },

  // Phase 4: Realize - Post-Conversion
  { id: 11, key: 'spau_spdd',              name: 'SPAU/SPDD & Code Deployment',              phase: 'Realize - Post-Conversion',  phaseNumber: 4, color: '#06b6d4', icon: 'Upload' },
  { id: 12, key: 'finance_migration',      name: 'Finance Migration (FINS Monitor)',         phase: 'Realize - Post-Conversion',  phaseNumber: 4, color: '#06b6d4', icon: 'DollarSign' },
  { id: 13, key: 'material_ledger_config', name: 'Material Ledger & Config Application',     phase: 'Realize - Post-Conversion',  phaseNumber: 4, color: '#06b6d4', icon: 'Wrench' },
  { id: 14, key: 'role_integration',       name: 'Role Provisioning & Integration Activation', phase: 'Realize - Post-Conversion', phaseNumber: 4, color: '#06b6d4', icon: 'Shield' },

  // Phase 5: Deploy & Run (Testing & Go-Live)
  { id: 15, key: 'business_process_test',  name: 'Automated Business Process Testing',       phase: 'Deploy & Run',               phaseNumber: 5, color: '#10b981', icon: 'TestTube2' },
  { id: 16, key: 'golive_cutover',         name: 'Go-Live Cutover Orchestration',            phase: 'Deploy & Run',               phaseNumber: 5, color: '#10b981', icon: 'Rocket' },
  { id: 17, key: 'validation_scorecard',   name: 'Migration Validation & GO-LIVE Scorecard', phase: 'Deploy & Run',               phaseNumber: 5, color: '#10b981', icon: 'CheckCircle2' },
];

export const SAMPLE_RUN = {
  id: 'run_20260305_050830',
  timestamp: '2026-03-05T05:08:30',
  company: 'Bharat Industrial Solutions Pvt Ltd',
  mode: 'full',
  duration: 4.2,
  rfc_calls: 13725,
  status: 'completed',
  results: {
    // Phase 1: Prepare
    discovery: {
      status: 'success',
      blocking_issues: 0,
      summary: {
        total_programs: 861,
        total_tables: 94,
        total_function_modules: 389,
        company_codes: 4,
        plants: 12,
        sales_orgs: 8,
        total_roles: 342,
        total_users: 1847,
        rfc_destinations: 67,
        idoc_partners: 13,
        blocking_issues: 19,
        warnings: 3,
      },
    },
    maintenance_planner: {
      status: 'success',
      target_release: 'S/4HANA 2023 FPS02',
      stack_components: 47,
      addon_compatibility: { compatible: 12, incompatible: 0, requires_upgrade: 2 },
      business_functions: { active: 89, deprecated: 12 },
    },
    readiness_check: {
      status: 'success',
      data_collection_status: 'complete',
      simplification_items_relevant: 156,
      custom_code_impact: { high: 3, medium: 45, low: 168 },
      fiori_readiness: 'partial',
      sizing_recommendation: '512GB HANA',
      estimated_effort_days: 45,
    },
    simplification_check: {
      status: 'success',
      total_items_checked: 312,
      red_items: 0,
      yellow_items: 8,
      green_items: 304,
      remediation_tasks: 8,
      conversion_readiness: 'GO',
      prerequisite_notes_applied: 24,
      prerequisite_notes_missing: 0,
    },

    // Phase 2: Explore
    code_analysis: {
      status: 'success',
      total_issues: 146,
      critical_issues: 89,
      auto_remediated: 213,
      fix_rate: 98.6,
      total_fixes_applied: 234,
      manual_review: 3,
      fixes_by_level: {
        deep_knowledge_engine: 130,
        level1_table_field_rewriter: 8,
        level2_structure_modernizer: 92,
        level2b_aggressive_rewriter: 4,
      },
      programs_fixed: 27,
    },
    cvi_preparation: {
      status: 'success',
      results: {
        customers: 3500,
        vendors: 1500,
        bp_created: 5000,
        duplicates_merged: 0,
        cvi_synchronization: 'Active',
      },
    },
    data_assessment: {
      status: 'success',
      results: {
        finance_docs: 5000,
        finance_lines: 19930,
        customers: 3500,
        vendors: 1500,
        bp_created: 5000,
        duplicates_merged: 0,
        custom_tables: 94,
        custom_table_rows: 4389616,
      },
    },
    config_assessment: {
      status: 'success',
      checklist_items: 9,
      rfc_total: 67,
      automated: 63,
      manual: 4,
    },

    // Phase 3: Realize - Conversion
    pre_conversion_gate: {
      status: 'success',
      go_no_go: 'GO',
    },
    sum_dmo: {
      status: 'success',
      orchestration_status: 'orchestrated',
      sum_version: 'SUM 2.0 SP15',
      phases_completed: 8,
      total_phases: 8,
      downtime_hours: 4.2,
      errors_encountered: 0,
      database_migrated_to: 'SAP HANA 2.0 SPS07',
    },

    // Phase 4: Realize - Post-Conversion
    spau_spdd: {
      status: 'success',
      spau_objects: 34,
      spdd_objects: 12,
      auto_adjusted: 38,
      manual_required: 8,
      transport_deployed: true,
      results: {
        summary: {
          transport_id: 'S4HK900001',
          deployed: 27,
          activated: 27,
        },
      },
    },
    finance_migration: {
      status: 'success',
      fins_monitor_status: 'complete',
      tables_converted: ['BSIS\u2192ACDOCA', 'BSAS\u2192ACDOCA', 'COEP\u2192ACDOCA'],
      documents_migrated: 19930,
      reconciliation_variance: '0.00',
      material_ledger_active: true,
      results: {
        finance: { documents_loaded: 5000, line_items: 19930 },
        business_partner: { partners_created: 5000, merged: 0 },
        commits: 3,
      },
    },
    material_ledger_config: {
      status: 'success',
      material_ledger_active: true,
      valuation_areas: 12,
      config_items_applied: 89,
      number_ranges_created: 5,
      results: {
        summary: {
          number_ranges: 3,
          ledgers: 2,
          bp_groups: 3,
          gst_registrations: 3,
          tds_configured: true,
          einvoice_configured: true,
          fiori_catalogs: 3,
        },
      },
    },
    role_integration: {
      status: 'success',
      total_roles: 342,
      fiori_mapped: 14,
      results: {
        summary: {
          single_roles_created: 15,
          composite_roles_created: 3,
          users_assigned: 375,
          rfc_destinations_created: 7,
          idoc_partners_created: 3,
          india_endpoints_created: 5,
        },
      },
    },

    // Phase 5: Deploy & Run
    business_process_test: {
      status: 'success',
      test_scenarios: 48,
      passed: 46,
      failed: 0,
      skipped: 2,
      processes_validated: ['Order-to-Cash', 'Procure-to-Pay', 'Record-to-Report', 'Plan-to-Produce'],
    },
    golive_cutover: {
      status: 'success',
      users_locked: 1847,
      delta_backup_complete: true,
      final_cutover_duration_minutes: 28,
      users_unlocked: 1847,
      cutover_status: 'GO-LIVE COMPLETE',
    },
    validation_scorecard: {
      status: 'success',
      scorecard: {
        grade: 'A',
        score: '100.0%',
        total_checks: 85,
        total_passed: 85,
        total_failed: 0,
        recommendation: 'READY FOR GO-LIVE',
        checks: {
          code: { checked: 27, passed: 27, failed: 0 },
          data: { checked: 2, passed: 2 },
          config: { checked: 21, passed: 21 },
          roles: { checked: 18, passed: 18 },
          integrations: { checked: 12, passed: 12 },
          sap_compliance: { checked: 3, passed: 3, failed: 0 },
          finance_reconciliation: { checked: 2, passed: 2, failed: 0 },
        },
      },
    },
  },
  post_migration_report: {
    report_metadata: {
      generated: '2026-03-05T05:08:34',
      classification: 'CONFIDENTIAL \u2014 Client Deliverable',
      tool_version: 'Migrate4HANA v2.0',
    },
    executive_summary: {
      client: 'Bharat Industrial Solutions Pvt Ltd',
      source_system: 'SAP ECC 6.0 EHP8',
      target_system: 'SAP S/4HANA 2023 FPS02',
      migration_approach: 'SAP Activate Methodology \u2014 System Conversion (Brownfield) with Smart Orchestration',
      overall_status: 'Completed \u2014 Ready for Go-Live',
      recommendation: 'PROCEED TO GO-LIVE',
    },
    sap_compliance: {
      methodology: 'SAP Activate',
      items: [
        { tool: 'Maintenance Planner', status: 'validated', detail: 'Target system S/4HANA 2023 FPS02 validated' },
        { tool: 'SAP Readiness Check', status: 'complete', detail: 'System assessed — 156 simplification items reviewed' },
        { tool: 'Simplification Item Check', status: 'passed', detail: 'All RED items resolved, 8 YELLOW items documented' },
        { tool: 'SUM/DMO', status: 'complete', detail: 'Database conversion executed by SAP SUM 2.0 SP15' },
        { tool: 'FINS_MASS_DATA_MONITOR', status: 'complete', detail: 'Finance data migrated — 19,930 documents' },
        { tool: 'Material Ledger', status: 'activated', detail: 'Activated via CKMSTART — 12 valuation areas' },
        { tool: 'SPAU/SPDD', status: 'applied', detail: 'Adjustments tracked and applied — 46 objects processed' },
      ],
      statement: 'This migration was executed using SAP-approved tools and methodology. Post-migration SAP support is retained.',
    },
    source_system_assessment: {
      total_custom_programs: 861,
      total_custom_tables: 94,
      function_modules: 389,
      company_codes: 4,
      plants: 12,
      sales_organizations: 8,
      total_roles: 342,
      total_users: 1847,
      blocking_issues_identified: 19,
    },
    code_remediation: {
      summary: {
        total_issues_detected: 216,
        auto_remediated: 213,
        total_fixes_applied: 234,
        fix_rate_percentage: 98.6,
        remaining_manual_review: 3,
      },
      fix_breakdown: {
        deep_knowledge_engine: 130,
        level1_table_field_rewriter: 8,
        level2_structure_modernizer: 92,
        level2b_aggressive_rewriter: 4,
      },
      key_transformations: [
        'BKPF/BSEG \u2192 ACDOCA universal journal migration (27 tables)',
        'KNA1/LFA1 \u2192 BUT000 Business Partner conversion',
        'KONV \u2192 PRCD_ELEMENTS pricing migration',
        'VBRK/VBRP \u2192 billing document field alignment',
        'Obsolete ABAP statements (MOVE, COMPUTE, MULTIPLY, etc.) modernized',
        'SELECT\u2026ENDSELECT loops replaced with INTO TABLE bulk fetches',
        'READ TABLE\u2026BINARY SEARCH updated with sorted table syntax',
        'India-specific GST/TDS table references updated to S/4 equivalents',
      ],
      manual_review_items: [
        'CALL SCREEN/SELECTION-SCREEN statements (Fiori migration needed)',
        'EXEC SQL blocks (review for HANA SQL compatibility)',
        'Custom SAPGUI function calls (Fiori replacement required)',
      ],
      remaining_manual_review: 3,
    },
    data_migration: {
      finance: {
        source_documents_bkpf: 5000,
        source_line_items_bseg: 19930,
        target_acdoca_records: 19930,
        reconciliation: 'PASSED',
      },
      business_partner_conversion: {
        customers_migrated: 3500,
        vendors_migrated: 1500,
        business_partners_created: 5000,
        duplicates_merged: 0,
        cvi_synchronization: 'Active',
      },
      custom_tables: {
        tables_migrated: 94,
        total_rows_transferred: 4389616,
        field_mapping_applied: true,
      },
    },
    configuration: {
      checklist_items_applied: 9,
      s4_specific_config: {
        universal_journal_ledgers: 2,
        number_ranges_created: 3,
        business_partner_groups: 3,
        fiori_catalogs_registered: 3,
      },
      india_localization: {
        gst_registrations: 3,
        tds_configured: true,
        einvoice_configured: true,
      },
    },
    roles_and_authorizations: {
      source_roles: 342,
      fiori_apps_mapped: 14,
      single_roles_created: 15,
      composite_roles_created: 3,
      users_assigned: 375,
      key_mappings: [
        'VA01 (Create Sales Order) \u2192 F1814 (Manage Sales Orders)',
        'ME21N (Create PO) \u2192 F2425 (Manage Purchase Orders)',
        'FB01 (Post Document) \u2192 F0717 (Manage Journal Entries)',
        'MM01 (Create Material) \u2192 F3013 (Manage Product Master)',
        'XK01 (Create Vendor) \u2192 F1740 (Manage Business Partner)',
      ],
    },
    integrations: {
      rfc_destinations_total: 67,
      auto_migrated: 63,
      manual_review_needed: 4,
      automation_rate: '94.0%',
      created: {
        rfc_destinations: 7,
        idoc_partners: 3,
        india_endpoints: 5,
      },
      critical_integrations: [
        'GST Portal API \u2192 E-Invoice generation (NIC)',
        'E-Way Bill generation \u2192 GSTN portal',
        'TDS quarterly returns \u2192 TRACES portal',
        'Bank payment integration \u2192 NEFT/RTGS gateway',
      ],
    },
    go_live_scorecard: {
      grade: 'A',
      score: '100.0%',
      total_checks: 85,
      passed: 85,
      failed: 0,
      breakdown: {
        code_deployment: { checked: 27, passed: 27 },
        data_integrity: { checked: 2, passed: 2 },
        configuration: { checked: 21, passed: 21 },
        authorization: { checked: 18, passed: 18 },
        integration: { checked: 12, passed: 12 },
        sap_compliance: { checked: 3, passed: 3 },
        finance_reconciliation: { checked: 2, passed: 2 },
      },
    },
    risk_assessment: {
      overall_risk: 'LOW',
      risks: [
        {
          area: 'Manual Code Review',
          severity: 'MEDIUM',
          description: '3 items require manual developer review (CALL SCREEN, EXEC SQL, SAPGUI)',
          mitigation: 'Allocate 1 developer day for manual remediation before cutover weekend',
        },
        {
          area: 'Integration Testing',
          severity: 'MEDIUM',
          description: '4 RFC destinations need manual configuration in target landscape',
          mitigation: 'Schedule integration test window with downstream system owners',
        },
        {
          area: 'User Training',
          severity: 'LOW',
          description: 'Fiori launchpad is new UX for 1847 end users',
          mitigation: 'Conduct 3-day Fiori navigation training; deploy guided tours',
        },
      ],
      recommendations: [
        'Enable HANA column-store partitioning on ACDOCA for optimal query performance',
        'Conduct Fiori Launchpad training for all 1847 end users before go-live',
        'Implement data archiving strategy for ACDOCA (projected 50M+ records/year)',
        'Schedule quarterly SAP kernel/HANA revision upgrades',
        'Set up Solution Manager for change management and monitoring',
      ],
    },
    post_golive_roadmap: [
      {
        phase: 'Hypercare (Weeks 1\u20134)',
        activities: [
          '24/7 support desk with SAP Basis and functional consultants',
          'Daily reconciliation of financial postings (ACDOCA vs legacy)',
          'Monitor HANA memory and disk consumption',
          'Track and resolve user-reported issues within 4-hour SLA',
        ],
      },
      {
        phase: 'Stabilization (Months 2\u20133)',
        activities: [
          'Performance tuning of custom reports on HANA',
          'Fiori app adoption tracking and UX feedback collection',
          'Month-end and quarter-end close dry runs',
          'Integration monitoring for GST/TDS portal submissions',
        ],
      },
      {
        phase: 'Optimization (Months 4\u20136)',
        activities: [
          'Activate additional Fiori apps based on user feedback',
          'Implement embedded analytics (CDS views + KPI tiles)',
          'Archive historical data from legacy tables',
          'Plan for next SAP upgrade cycle (annual FPS updates)',
        ],
      },
    ],
    technical_metrics: {
      rfc_calls_executed: 13725,
      pipeline_duration_seconds: 4.2,
      programs_deployed: 27,
      transport_request: 'S4HK900001',
    },
  },
};

export function getStageStatus(run, stageKey) {
  if (!run || !run.results[stageKey]) return 'pending';
  return run.results[stageKey].status === 'success' ? 'completed' : 'failed';
}

export function getStageDuration() {
  // Simulated per-stage timings
  return {
    discovery: 0.3, maintenance_planner: 0.2, readiness_check: 0.4, simplification_check: 0.3,
    code_analysis: 0.8, cvi_preparation: 0.3, data_assessment: 0.2, config_assessment: 0.2,
    pre_conversion_gate: 0.1, sum_dmo: 1.5,
    spau_spdd: 0.5, finance_migration: 1.2, material_ledger_config: 0.3, role_integration: 0.3,
    business_process_test: 0.6, golive_cutover: 0.4, validation_scorecard: 0.2,
  };
}
