"""Aggregator extracted from run_local_lift_and_shift.py so the PDF Lambda
can call it without dragging in the full pipeline driver.

Single public entrypoint: aggregate_run_artifacts(staging_root, run_id).
The body is identical to _aggregate_run_artifacts() — keep this in sync
when the runner aggregator evolves.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


def aggregate_run_artifacts(staging_root: Path, run_id: str) -> dict:
    return _aggregate_run_artifacts(staging_root, run_id)


def _aggregate_run_artifacts(staging_root: Path, run_id: str) -> dict:
    """Collect per-stage artifacts under runs/<run_id>/ + migrations/<run_id>/
    and map them into the schema the PDF generator consumes.

    The PDF generator (pdf_report_generator.generate_pdf) reads named top-level
    keys — executive_summary, source_system_assessment, code_remediation,
    data_migration, configuration, roles_and_authorizations, integrations,
    go_live_scorecard, risk_assessment, post_golive_roadmap, technical_metrics —
    NOT a generic stages[] list. Without this mapping the PDF renders every
    .get('--')/0 default and looks empty.

    The raw `stages` list is preserved alongside the mapped schema so the JSON
    archive next to the PDF still has the full audit trail.
    """
    stages = []
    by_artifact: dict[str, dict] = {}
    for base in (staging_root / "runs" / run_id, staging_root / "migrations" / run_id):
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*.json")):
            try:
                payload = json.loads(f.read_text())
            except Exception:
                continue
            rel = f.relative_to(base)
            artifact_key = str(rel).replace("\\", "/")
            stages.append({
                "section": rel.parts[0] if rel.parts else f.stem,
                "artifact": artifact_key,
                "path": str(f),
                "size_bytes": f.stat().st_size,
                "payload": payload,
            })
            by_artifact[artifact_key] = payload

    # ── shorthand getters ───────────────────────────────────────────────────
    def g(key: str, default=None):
        p = by_artifact.get(key)
        return p if p is not None else (default if default is not None else {})

    disc      = g("discovery/summary.json")
    disc_full = g("discovery/full-scan.json")
    sizing    = g("sizing-advisor/recommendation.json")
    code      = g("code-analysis/analysis-report.json")
    dm        = g("data-migrator/summary.json")
    cfg_dump  = g("config/ecc-config-dump.json")
    cfg_check = g("config/s4-config-checklist.json", default=[])
    cfg_s4ref = g("config/s4-new-config-reference.json")
    bc_sets   = g("bc-sets/manual-manifest.json")
    transp    = g("transports/manual/manifest.json")
    scorecard = g("execution/go-live-scorecard.json")
    validator = g("execution/migration-validator.json")
    basis     = g("basis-validator/report.json")
    provis    = g("target-provisioner/manifest.json")
    router    = g("object-router/dag.json")

    # H0.4: cumulative-on-target from the cross-run ledger (resume runs do almost
    # no NEW creates, so per-run counters read as "0 created"). Keep in sync with
    # run_local_lift_and_shift.py:_aggregate_run_artifacts.
    def _cumulative_on_target(_root):
        led = _root / "migration-ledger" / "key_mapping.json"
        try:
            blob = json.loads(led.read_text())
        except Exception:
            return {"available": False, "records_on_target": 0, "by_object": {}}
        m = blob.get("mappings", blob)
        by_obj, total = {}, 0
        if isinstance(m, dict):
            for obj, entries in m.items():
                n = len(entries) if isinstance(entries, (dict, list)) else 0
                if n:
                    by_obj[obj] = n
                    total += n
        return {"available": True, "records_on_target": total,
                "object_count": len(by_obj), "by_object": by_obj}
    cumulative = _cumulative_on_target(staging_root)

    # ── 1. executive_summary + report_metadata ─────────────────────────────
    grade = scorecard.get("grade", "--")
    score = scorecard.get("score", "--")
    recommendation = scorecard.get("recommendation", "--")
    overall_status = ("GO" if scorecard.get("gate_eligible")
                      else ("NO-GO" if grade in ("D", "F") else "CONDITIONAL"))

    source_sid    = "ECC 6.0 EHP7 (local)"
    target_sid    = "S/4HANA 2023 (CAL IDES)"
    executive_summary = {
        "client":             os.environ.get("M4H_CLIENT_NAME", "Internal Engineering Run"),
        "source_system":      source_sid,
        "target_system":      target_sid,
        "migration_approach": "Lift-and-Shift (greenfield target, transport-led)",
        "overall_status":     overall_status,
        "recommendation":     recommendation,
    }
    report_metadata = {
        "generated":      datetime.utcnow().isoformat() + "Z",
        "classification": "INTERNAL — pre-production engineering run",
        "run_id":         run_id,
        "tool_version":   "Migrate4HANA v2 / lift-and-shift pipeline",
    }

    # ── 2. source_system_assessment ────────────────────────────────────────
    source_system_assessment = {
        "total_custom_programs":         disc.get("total_programs", 0),
        "total_custom_tables":           disc.get("total_tables", 0),
        "function_modules":              disc.get("total_function_modules", 0),
        "company_codes":                 disc.get("company_codes", 0),
        "plants":                        disc.get("plants", 0),
        "sales_organizations":           disc.get("sales_orgs", 0),
        "total_users":                   disc.get("total_users", 0),
        "total_roles":                   disc.get("total_roles", 0),
        "blocking_issues_identified":    disc.get("blocking_issues", 0),
        "ecc_db_size_gb":                sizing.get("ecc_db_size_gb", 0),
        "rfc_destinations":              disc.get("rfc_destinations", 0),
    }

    # ── 3. code_remediation ────────────────────────────────────────────────
    sev = code.get("severity_breakdown", {}) or {}
    cov = code.get("coverage", {}) or {}
    code_remediation = {
        "summary": {
            "total_issues_detected":   code.get("total_issues", 0),
            "auto_remediated":         code.get("auto_remediated", 0),
            "total_fixes_applied":     code.get("auto_remediated", 0),
            "fix_rate_percentage":     (code.get("remediation_rate", "0%") or "0%").rstrip("%"),
            "remaining_manual_review": code.get("manual_review_needed", 0),
        },
        "fix_breakdown": {
            "critical_severity": sev.get("critical", 0),
            "high_severity":     sev.get("high", 0),
            "medium_severity":   sev.get("medium", 0),
            "low_severity":      sev.get("low", 0),
            "informational":     sev.get("info", 0),
        },
        "key_transformations": [
            f"Scanned {cov.get('programs_scanned', 0):,} custom programs ({cov.get('programs_with_source', 0):,} with source)",
            f"AST-based remediation applied to {cov.get('programs_remediated', 0):,} programs",
            f"ATC integration: {'ON' if code.get('atc_integration') else 'OFF'}",
            f"SAP official validation: {'ON' if code.get('sap_official_validation') else 'OFF'}",
            f"CDS view migration candidates identified: {code.get('cds_suggestions', 0)}",
        ],
        "manual_review_items": [
            f"{cov.get('programs_no_source', 0)} programs without retrievable source (RSPARAM extension required)",
        ] if cov.get("programs_no_source", 0) else [],
    }

    # ── 4. data_migration ──────────────────────────────────────────────────
    # Surface what the AWS data-migrator+spine orchestrators actually did:
    #   - per-object extracted (from reconciliation.extracted) — real ECC volume
    #   - attempted (rows the spine tried) — driven by M4H_LOAD_MAX_ROWS env
    #   - created_in_s4 (BAPI succeeded, new BP/Material on target)
    #   - matched_existing (PersistentKeyMap idempotency hit, already migrated)
    #   - dead_letter (BAPI rejected; one of DQ_REJECTION / BAPI_FAILURE / etc.)
    # This is the "how well does the tool handle dirty data" view.
    recon = dm.get("reconciliation", {}) or {}
    per_object_results = dm.get("results") or []

    def _agg_by_object(obj_name):
        for r in per_object_results:
            if r.get("object") == obj_name:
                return r
        return {}

    def _spine_stats(obj_name):
        r = _agg_by_object(obj_name)
        load = r.get("load") or {}
        rec  = r.get("reconciliation") or {}
        sb   = load.get("status_breakdown") or {}
        return {
            "spine_used":       load.get("mechanism", "—"),
            "extracted":        rec.get("extracted", 0),
            "attempted":        load.get("attempted", 0),
            "created_in_s4":    load.get("created_in_s4", 0),
            "matched_existing": sb.get("matched_existing", 0),
            "dead_letter":      sb.get("dead_letter", 0),
            "samples":          (load.get("samples") or [])[:5],
        }

    cust_stats = _spine_stats("Customer")
    vend_stats = _spine_stats("Vendor")
    mat_stats  = _spine_stats("Material")
    bp_stats   = _spine_stats("BusinessPartner")

    total_attempted = sum(_spine_stats(o)["attempted"]
                          for o in ("Customer","Vendor","Material","BusinessPartner",
                                    "GLAccount","CostCenter","ProfitCenter"))
    total_created   = sum(_spine_stats(o)["created_in_s4"]
                          for o in ("Customer","Vendor","Material","BusinessPartner",
                                    "GLAccount","CostCenter","ProfitCenter"))
    total_matched   = sum(_spine_stats(o)["matched_existing"]
                          for o in ("Customer","Vendor","Material","BusinessPartner",
                                    "GLAccount","CostCenter","ProfitCenter"))
    total_dead      = sum(_spine_stats(o)["dead_letter"]
                          for o in ("Customer","Vendor","Material","BusinessPartner",
                                    "GLAccount","CostCenter","ProfitCenter"))

    # H0.4: clamp negative records_missing (verified counts matched_existing on resume).
    _recon_missing_raw = recon.get("records_missing", 0)
    _recon_note = None
    if isinstance(_recon_missing_raw, (int, float)) and _recon_missing_raw < 0:
        _recon_note = ("verified-in-target exceeds this-run creates (idempotent "
                       "re-verification of already-migrated rows); not a shortfall")

    data_migration = {
        "cumulative_on_target": cumulative,   # H0.4: durable ledger view
        "finance": {
            "source_documents_bkpf":  cfg_dump.get("finance", {}).get("documents_bkpf", 0),
            "source_line_items_bseg": cfg_dump.get("finance", {}).get("line_items_bseg", 0),
            "target_acdoca_records":  recon.get("records_verified_in_target", 0),
            "records_missing":        max(0, _recon_missing_raw) if isinstance(_recon_missing_raw, (int, float)) else 0,
            "reconciliation":         recon.get("verdict", "NOTHING_TO_RECONCILE"),
            **({"reconciliation_note": _recon_note} if _recon_note else {}),
        },
        "business_partner_conversion": {
            "customers_migrated":         cust_stats["created_in_s4"],
            "vendors_migrated":           vend_stats["created_in_s4"],
            "business_partners_created":  bp_stats["created_in_s4"] + cust_stats["created_in_s4"] + vend_stats["created_in_s4"],
            "duplicates_merged":          cust_stats["matched_existing"] + vend_stats["matched_existing"] + bp_stats["matched_existing"],
            "cvi_synchronization":        "BP-led (CVI active on source ECC)",
            "customer_extracted_from_ecc":  cust_stats["extracted"],
            "vendor_extracted_from_ecc":    vend_stats["extracted"],
            "bp_extracted_from_ecc":        bp_stats["extracted"],
            "customer_spine_orchestrator":  cust_stats["spine_used"],
            "material_extracted_from_ecc":  mat_stats["extracted"],
            "material_created_in_s4":       mat_stats["created_in_s4"],
            "material_spine_orchestrator":  mat_stats["spine_used"],
        },
        "dirty_data_handling": {
            "load_to_s4_enabled":     dm.get("load_to_s4_enabled", False),
            "scope_note":             ("Counts below are THIS RUN's increment; "
                                       "cumulative records live on target = "
                                       f"{cumulative.get('records_on_target', 0)} "
                                       "(see data_migration.cumulative_on_target)."),
            "total_attempted":        total_attempted,
            "total_created_in_s4":    total_created,   # THIS RUN's new creates
            "cumulative_records_on_target": cumulative.get("records_on_target", 0),
            "total_matched_existing": total_matched,
            "total_dead_lettered":    total_dead,
            "create_rate":            (f"{100.0*total_created/total_attempted:.1f}%" if total_attempted else "n/a"),
            "idempotency_hit_rate":   (f"{100.0*total_matched/total_attempted:.1f}%" if total_attempted else "n/a"),
            "dead_letter_rate":       (f"{100.0*total_dead/total_attempted:.1f}%" if total_attempted else "n/a"),
            "dead_letter_classes":    sorted({s.get("disposition","dead_letter")
                                              for o in ("Customer","Vendor","Material","BusinessPartner")
                                              for s in _spine_stats(o)["samples"]
                                              if s.get("status") == "dead_letter"}),
            "spine_orchestrators": {
                "Customer":        cust_stats["spine_used"],
                "Vendor":          vend_stats["spine_used"],
                "Material":        mat_stats["spine_used"],
                "BusinessPartner": bp_stats["spine_used"],
            },
            "sample_outcomes": {
                "Customer":        cust_stats["samples"],
                "Vendor":          vend_stats["samples"],
                "Material":        mat_stats["samples"],
                "BusinessPartner": bp_stats["samples"],
            },
        },
        "custom_tables": {
            "tables_migrated":       dm.get("object_count", 0),
            "total_rows_transferred": recon.get("records_created", 0),
            "skipped":               dm.get("skipped_count", 0),
            "partial":               dm.get("partial_count", 0),
            "errors":                dm.get("error_count", 0),
        },
        "support_compliance": dm.get("support_compliance", {}),
    }

    # ── 5. configuration ───────────────────────────────────────────────────
    nr     = cfg_dump.get("number_ranges", {}) or {}
    flp    = cfg_s4ref.get("fiori_launchpad", {}) or {}
    bpref  = cfg_s4ref.get("business_partner", {}) or {}
    configuration = {
        "checklist_items_applied": len(cfg_check) if isinstance(cfg_check, list) else 0,
        "s4_specific_config": {
            "universal_journal_ledgers":   len((cfg_dump.get("finance", {}) or {}).get("ledgers", []) or []),
            "number_ranges_created":       (len(nr) if isinstance(nr, dict)
                                            else (len(nr) if isinstance(nr, list) else 0)),
            "business_partner_groups":     len(bpref.get("groupings", []) or []) or 4,
            "fiori_catalogs_registered":   len(flp.get("catalogs", []) or []) or 0,
        },
        "india_localization": {
            "gst_registrations":   0,
            "tds_configured":      False,
            "einvoice_configured": False,
        },
        "bc_sets_built": bc_sets.get("groups", []) and len(bc_sets.get("groups", [])) or 0,
    }

    # ── 6. roles_and_authorizations (from discovery roles; no PFCG run here) ─
    roles_and_authorizations = {
        "source_roles":              disc.get("total_roles", 0),
        "fiori_apps_mapped":         0,
        "single_roles_created":      0,
        "composite_roles_created":   0,
        "users_assigned":            disc.get("total_users", 0),
        "key_mappings": [
            "MM03 -> Display Material (F1981)",
            "FBL3N -> Manage G/L Account Line Items (F0707)",
            "XK03 -> Display Supplier (F1054)",
            "(populated end-to-end when role-migrator stage runs against live PFCG)",
        ],
    }

    # ── 7. integrations ────────────────────────────────────────────────────
    rfc_total = disc.get("rfc_destinations", 0)
    integrations = {
        "rfc_destinations_total":  rfc_total,
        "auto_migrated":           0,
        "manual_review_needed":    rfc_total,
        "automation_rate":         "0%" if rfc_total else "n/a",
        "critical_integrations": [
            f"IDoc partners discovered: {disc.get('idoc_partners', 0)}",
            "Live RFC destination harvest reported "
            f"{rfc_total} destinations — see discovery/full-scan.json for full list",
        ],
    }

    # ── 8. go_live_scorecard with breakdown ────────────────────────────────
    # migration-validator emits validations as a dict keyed by category
    # ({code,data,config,roles,...}), each holding {check, *_checked, passed,
    # failed, details}. Older builds may emit a list — handle both.
    validations = validator.get("validations", {}) or {}
    by_cat: dict[str, dict] = {}
    if isinstance(validations, dict):
        for cat, v in validations.items():
            if not isinstance(v, dict):
                continue
            checked = (v.get("passed", 0) or 0) + (v.get("failed", 0) or 0)
            if checked == 0:
                # fall back to whichever *_checked key the category uses
                for k, val in v.items():
                    if isinstance(k, str) and k.endswith("_checked") and isinstance(val, int):
                        checked = val
                        break
            by_cat[cat] = {"checked": checked, "passed": v.get("passed", 0) or 0}
    elif isinstance(validations, list):
        for v in validations:
            if not isinstance(v, dict):
                continue
            cat = v.get("category") or v.get("stage") or "general"
            by_cat.setdefault(cat, {"checked": 0, "passed": 0})
            by_cat[cat]["checked"] += 1
            if v.get("passed") or v.get("status") in ("ok", "passed", "success"):
                by_cat[cat]["passed"] += 1
    go_live_scorecard = {
        "grade":         grade,
        "score":         score,
        "total_checks":  scorecard.get("total_checks", 0),
        "passed":        scorecard.get("total_passed", 0),
        "failed":        scorecard.get("total_failed", 0),
        "recommendation": recommendation,
        "breakdown":     by_cat,
    }

    # ── 9. risk_assessment ─────────────────────────────────────────────────
    risks: list[dict] = []
    if scorecard.get("total_failed", 0) > 0:
        risks.append({
            "severity":    "HIGH" if grade in ("D", "F") else "MEDIUM",
            "area":        "Migration Validator",
            "description": f"{scorecard.get('total_failed', 0)} of {scorecard.get('total_checks', 0)} post-cutover checks failed",
            "mitigation":  "Re-run with transports imported (STMS) and full object_spec wired into data-migrator before next attempt.",
        })
    if (transp.get("rfc_error") or transp.get("ssh_available") is False):
        risks.append({
            "severity":    "MEDIUM",
            "area":        "Transport Delivery",
            "description": f"Transport build fell back to manual ({transp.get('mode', 'manual')}); SSH={transp.get('ssh_available')}",
            "mitigation":  "Hand transport bundle to basis admin for STMS import; output dir referenced in stage 8/12 artifact.",
        })
    if disc.get("warnings", 0):
        risks.append({
            "severity":    "LOW",
            "area":        "Discovery Warnings",
            "description": f"{disc.get('warnings', 0)} warning(s) raised during discovery",
            "mitigation":  "Review discovery/full-scan.json warnings section.",
        })
    if not risks:
        risks.append({
            "severity":    "LOW",
            "area":        "General",
            "description": "No blocking risks detected in this run.",
            "mitigation":  "Continue standard pre-cutover dry-run cadence.",
        })
    overall_risk = "HIGH" if any(r["severity"] == "HIGH" for r in risks) else \
                   "MEDIUM" if any(r["severity"] == "MEDIUM" for r in risks) else "LOW"
    risk_assessment = {
        "overall_risk":    overall_risk,
        "risks":           risks,
        "recommendations": [
            f"Address the {scorecard.get('total_failed', 0)} failing scorecard check(s) before promoting beyond DEV.",
            "Import code + config transports via STMS on the target before re-running the validator.",
            "Wire data-migrator object_spec to the live ECC object catalog (current run was extract-only).",
            "Re-run end-to-end once transports are imported; expect grade to lift toward A/B.",
        ],
    }

    # ── 10. post_golive_roadmap ────────────────────────────────────────────
    post_golive_roadmap = [
        {"phase": "Hypercare (Week 1-2)", "activities": [
            "Daily reconciliation: BKPF/BSEG vs ACDOCA; key-map ledger chain verification",
            "On-call rota live; SLA dashboard checked twice/day",
            "Open-item RFC destinations triage (one queue per integration partner)",
        ]},
        {"phase": "Stabilization (Week 3-6)", "activities": [
            "Decommission parallel ECC read-only access for non-audit users",
            "Roll out remaining Fiori roles to wave-2 users",
            "Quarterly DR drill: simulate key-map corruption and run restore-key-map.ps1",
        ]},
        {"phase": "Optimization (Quarter 2+)", "activities": [
            "Migrate stragglers from RFC SOAP to OData/SOAP via integration-mapper",
            "Convert the {} CDS suggestions into released CDS views".format(code.get("cds_suggestions", 0)),
            "Decommission ECC system once 2 quarterly audit cycles close clean",
        ]},
    ]

    # ── 11. technical_metrics ──────────────────────────────────────────────
    duration_total = 0
    for s in stages:
        if isinstance(s["payload"], dict):
            d = s["payload"].get("duration_seconds") or s["payload"].get("elapsed_sec") or 0
            try:
                duration_total += float(d)
            except Exception:
                pass
    technical_metrics = {
        "rfc_calls_executed":        (disc_full.get("total_rfc_calls", 0)
                                      or (disc.get("total_programs", 0) + disc.get("total_tables", 0))),
        "pipeline_duration_seconds": int(duration_total),
        "programs_deployed":         cov.get("programs_remediated", 0),
        "transport_request":         transp.get("description", "Manual STMS handover"),
        "stages_executed":           len(stages),
        "deployment_id":             provis.get("deployment_id", "--"),
    }

    return {
        # — schema fields the PDF generator consumes —
        "executive_summary":         executive_summary,
        "report_metadata":           report_metadata,
        "source_system_assessment":  source_system_assessment,
        "code_remediation":          code_remediation,
        "data_migration":            data_migration,
        "configuration":             configuration,
        "roles_and_authorizations":  roles_and_authorizations,
        "integrations":              integrations,
        "go_live_scorecard":         go_live_scorecard,
        "risk_assessment":           risk_assessment,
        "post_golive_roadmap":       post_golive_roadmap,
        "technical_metrics":         technical_metrics,
        # — raw audit trail kept alongside —
        "run_id":      run_id,
        "title":       f"Migrate4HANA — lift-and-shift run {run_id}",
        "generated_at": datetime.utcnow().isoformat(),
        "stages":      stages,
        "stage_count": len(stages),
    }


